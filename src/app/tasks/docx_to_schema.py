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

# Schema describing the expected structure of the model's output
SCHEMA_OF_SCHEMA = {
    "name": "SchemaProposal",
    "strict": True,
    "schema": {
        "type": "object",
        "required": ["title", "description", "json_schema", "example"],
        "properties": {
            "title": {"type": "string"},
            "description": {"type": "string"},
            "json_schema": {"type": "object", "additionalProperties": True},
            "example": {"type": "object", "additionalProperties": True}
        },
        "additionalProperties": False
    }
}

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
def docx_to_json_schema_task(self, docx_path: str, model: str, reasoning: str, verbosity: str, user_id: int, openai_cls=OpenAI):
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
            "content": [{"type": "input_text", "text": "Propose un JSON Schema minimal, cohérent et normalisé pour représenter ce document."}],
        },
        {
            "role": "user",
            "content": [{"type": "input_file", "file_id": uploaded.id}],
        },
    ]
    text_params = {
        "format": {"type": "json_schema", **SCHEMA_OF_SCHEMA},
        "verbosity": verbosity,
    }
    reasoning_params = {"effort": reasoning}

    with client.responses.stream(
        model=model,
        input=input_blocks,
        text=text_params,
        reasoning=reasoning_params,
        tools=[],
        store=False,
    ) as stream:
        for event in stream:
            etype = getattr(event, "type", "")
            if etype == "response.output_text.delta":
                push({"stream_chunk": event.delta})
            elif etype in {"response.reasoning_summary.delta", "response.reasoning_summary_text.delta"}:
                push({"reasoning_summary": event.delta})
        final = stream.get_final_response()

    usage = getattr(final, "usage", None)
    api_usage = {
        "prompt_tokens": getattr(usage, "input_tokens", 0),
        "completion_tokens": getattr(usage, "output_tokens", 0),
        "model": model,
    }
    parsed = getattr(final, "output_parsed", None)
    if parsed is None:
        result_text = getattr(final, "output_text", "")
        try:
            parsed = json.loads(result_text)
        except Exception:
            parsed = result_text
    return {"status": "success", "result": parsed, "api_usage": api_usage}
