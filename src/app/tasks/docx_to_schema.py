import os
import json
import logging
import subprocess
from typing import Optional

from celery import shared_task
from docx import Document
from openai import OpenAI

from ..models import User, db
from .import_plan_cadre import _create_pdf_from_text

logger = logging.getLogger(__name__)


def _extract_reasoning_summary_from_response(response):
    """Extract reasoning summary text from a Responses API result."""
    summary = ""
    try:
        if hasattr(response, "reasoning") and response.reasoning:
            for r in response.reasoning:
                for item in getattr(r, "summary", []) or []:
                    if getattr(item, "type", "") == "summary_text":
                        summary += getattr(item, "text", "") or ""
    except Exception:
        pass
    if not summary:
        try:
            for out in getattr(response, "output", []) or []:
                if getattr(out, "type", "") == "reasoning":
                    for item in getattr(out, "summary", []) or []:
                        if getattr(item, "type", "") == "summary_text":
                            summary += getattr(item, "text", "") or ""
        except Exception:
            pass
    return summary.strip()

def _docx_to_pdf(docx_path: str) -> str:
    """Convert a DOCX file to PDF using LibreOffice.

    Falls back to a simple text-based PDF if the conversion fails.
    Returns the path to the generated PDF.
    """
    pdf_path = os.path.splitext(docx_path)[0] + ".pdf"
    outdir = os.path.dirname(docx_path) or "."
    try:
        subprocess.run(
            [
                "libreoffice",
                "--headless",
                "--convert-to",
                "pdf",
                "--outdir",
                outdir,
                docx_path,
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if not os.path.exists(pdf_path):
            raise FileNotFoundError("PDF conversion failed")
    except Exception:
        try:
            doc = Document(docx_path)
            text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
        except Exception:
            text = ""
        _create_pdf_from_text(text or "Document importé", pdf_path)
    return pdf_path

@shared_task(bind=True, name="app.tasks.docx_to_schema.convert")
def docx_to_json_schema_task(self, docx_path: str, model: str, reasoning: str, verbosity: str, system_prompt: str, user_id: int, openai_cls=OpenAI):
    """Convert a DOCX file to a JSON Schema using OpenAI's file API with streaming."""
    task_id = self.request.id
    logger.info("[%s] Starting DOCX→Schema for %s", task_id, docx_path)

    user: Optional[User]
    with db.session.no_autoflush:
        user = db.session.get(User, user_id)
    if not user or not user.openai_key:
        return {"status": "error", "message": "Clé OpenAI manquante."}

    pdf_path = _docx_to_pdf(docx_path)
    client = openai_cls(api_key=user.openai_key)
    with open(pdf_path, "rb") as fh:
        uploaded = client.files.create(file=fh, purpose="user_data")

    def push(meta):
        try:
            self.update_state(state="PROGRESS", meta=meta)
        except Exception:
            logger.exception("Failed to update task state")

    input_blocks = [
        {
            "role": "system",
            "content": [{"type": "input_text", "text": system_prompt}],
        },
        {
            "role": "user",
            "content": [{"type": "input_file", "file_id": uploaded.id}],
        },
    ]
    response_format = {
        "type": "json_schema",
        "json_schema": {
            "name": "docx_schema_result",
            "schema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["title", "description", "schema", "markdown"],
                "properties": {
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "schema": {"type": "object"},
                    "markdown": {"type": "string"},
                },
            },
        },
    }
    request_kwargs = dict(
        model=model,
        input=input_blocks,
        text={"verbosity": verbosity},
        reasoning={"effort": reasoning, "summary": "auto"},
        tools=[],
        store=True,
        response_format=response_format,
    )

    streamed_text = ""
    reasoning_summary_text = ""
    seq = 0
    try:
        with client.responses.stream(**request_kwargs) as stream:
            for event in stream:
                etype = getattr(event, "type", "") or ""
                if etype.endswith("response.output_text.delta") or etype == "response.output_text.delta":
                    delta = getattr(event, "delta", "") or getattr(event, "text", "") or ""
                    if delta:
                        streamed_text += delta
                        seq += 1
                        push({
                            "message": "Analyse en cours...",
                            "stream_chunk": delta,
                            "stream_buffer": streamed_text,
                            "seq": seq,
                        })
                elif etype.endswith("response.reasoning_summary_text.delta") or etype == "response.reasoning_summary_text.delta":
                    rs_delta = getattr(event, "delta", "") or ""
                    if rs_delta:
                        reasoning_summary_text += rs_delta
                        push({"message": "Résumé du raisonnement", "reasoning_summary": reasoning_summary_text})
            final = stream.get_final_response()
            if not reasoning_summary_text:
                reasoning_summary_text = _extract_reasoning_summary_from_response(final)
                if reasoning_summary_text:
                    push({"message": "Résumé du raisonnement", "reasoning_summary": reasoning_summary_text})
    except Exception:
        final = client.responses.create(**request_kwargs)
        reasoning_summary_text = _extract_reasoning_summary_from_response(final)
        if reasoning_summary_text:
            push({"message": "Résumé du raisonnement", "reasoning_summary": reasoning_summary_text})
        try:
            text = getattr(final, "output_text", "") or ""
            if text:
                push({"message": "Analyse terminée", "stream_buffer": text})
        except Exception:
            pass

    usage = getattr(final, "usage", None)
    api_usage = {
        "prompt_tokens": getattr(usage, "input_tokens", 0),
        "completion_tokens": getattr(usage, "output_tokens", 0),
        "model": model,
    }

    parsed = None
    try:
        parsed = getattr(final, "output_parsed", None)
    except Exception:
        parsed = None
    if parsed is None:
        json_text = None
        try:
            json_text = getattr(final, "output_text", None)
        except Exception:
            json_text = None
        if not json_text and streamed_text:
            json_text = streamed_text
        if json_text:
            try:
                parsed = json.loads(json_text)
            except Exception:
                parsed = json_text

    if isinstance(parsed, dict):
        title = parsed.get('title')
        description = parsed.get('description')
        schema_obj = parsed.get('schema')
        markdown = parsed.get('markdown', '')
        if isinstance(schema_obj, dict):
            if title and 'title' not in schema_obj:
                schema_obj['title'] = title
            if description and 'description' not in schema_obj:
                schema_obj['description'] = description
        result_payload = {
            'title': title,
            'description': description,
            'schema': schema_obj,
            'markdown': markdown,
        }
    else:
        result_payload = {'title': None, 'description': None, 'schema': parsed, 'markdown': ''}

    logger.info("[%s] OpenAI usage: %s", task_id, api_usage)
    return {"status": "success", "result": result_payload, "api_usage": api_usage}
