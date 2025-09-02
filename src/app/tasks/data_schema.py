import json
import logging
from typing import Optional

from celery import shared_task
from openai import OpenAI

from ..models import db, User, DocxSchemaPage, DocxSchemaEntry
from .docx_to_schema import _docx_to_pdf  # reuse robust converter

logger = logging.getLogger(__name__)


def _push_progress(task_self, meta: dict):
    try:
        task_self.update_state(state="PROGRESS", meta=meta)
    except Exception:
        logger.exception("Failed to update task state")


def _run_structured_stream(task_self, client, request_kwargs):
    streamed_text = ""
    reasoning_summary_text = ""
    try:
        with client.responses.stream(**request_kwargs) as stream:
            for event in stream:
                etype = getattr(event, "type", "") or ""
                if etype.endswith("response.output_text.delta") or etype == "response.output_text.delta":
                    delta = getattr(event, "delta", "") or getattr(event, "text", "") or ""
                    if delta:
                        streamed_text += delta
                        _push_progress(task_self, {"message": "Génération en cours…", "stream_chunk": delta, "stream_buffer": streamed_text})
                elif etype.endswith("response.reasoning_summary_text.delta") or etype == "response.reasoning_summary_text.delta":
                    rdelta = getattr(event, "delta", "") or ""
                    if rdelta:
                        reasoning_summary_text += rdelta
                        _push_progress(task_self, {"message": "Résumé du raisonnement", "reasoning_summary": reasoning_summary_text})
            final = stream.get_final_response()
            return final, streamed_text, reasoning_summary_text
    except Exception:
        # Fallback non-streaming
        final = client.responses.create(**request_kwargs)
        try:
            text = getattr(final, "output_text", "") or ""
            if text:
                streamed_text = text
                _push_progress(task_self, {"message": "Génération terminée", "stream_buffer": text})
        except Exception:
            pass
        return final, streamed_text, reasoning_summary_text


def _extract_usage(resp) -> dict:
    usage = getattr(resp, "usage", None)
    return {
        "prompt_tokens": getattr(usage, "input_tokens", 0),
        "completion_tokens": getattr(usage, "output_tokens", 0),
    }


def _parse_final_json(final, streamed_text: str):
    parsed = None
    try:
        parsed = getattr(final, "output_parsed", None)
        if hasattr(parsed, "model_dump"):
            parsed = parsed.model_dump()
    except Exception:
        parsed = None
    if parsed is None:
        try:
            text = getattr(final, "output_text", None) or streamed_text
            if isinstance(text, str) and text.strip():
                parsed = json.loads(text)
        except Exception:
            parsed = None
    return parsed


def _build_text_format_for_schema(schema: dict) -> dict:
    return {"format": {"type": "json_schema", "name": "DocxSchemaData", "schema": schema, "strict": True}}


@shared_task(bind=True, name="app.tasks.data_schema.generate_entry")
def data_schema_generate_entry_task(self, page_id: int, user_id: int, system_prompt: str, model: str, reasoning: str, verbosity: str, extra_instructions: Optional[str] = None, openai_cls=OpenAI):
    page = db.session.get(DocxSchemaPage, page_id)
    user = db.session.get(User, user_id)
    if not page or not user or not user.openai_key:
        return {"status": "error", "message": "Paramètres invalides (page/utilisateur/clé)."}

    client = openai_cls(api_key=user.openai_key)
    schema = page.json_schema if isinstance(page.json_schema, dict) else {}
    input_blocks = [
        {"role": "system", "content": [{"type": "input_text", "text": system_prompt or ""}]},
        {"role": "user", "content": [{"type": "input_text", "text": (extra_instructions or "") + "\n\nProduit uniquement un JSON strict conforme au schéma."}]},
    ]
    request_kwargs = dict(
        model=model,
        input=input_blocks,
        text=_build_text_format_for_schema(schema),
        reasoning={"effort": reasoning or "medium", "summary": "auto"},
        store=True,
    )

    final, streamed_text, _rs = _run_structured_stream(self, client, request_kwargs)
    payload = _parse_final_json(final, streamed_text) or {}
    if not isinstance(payload, (dict, list)):
        return {"status": "error", "message": "Réponse IA invalide."}

    # Persist entry
    entry = DocxSchemaEntry(page_id=page.id, data=payload, title=(payload.get('title') if isinstance(payload, dict) else None), created_by_id=user.id)
    db.session.add(entry)
    db.session.commit()

    result = {"entry_id": entry.id, "data": payload}
    validation_url = f"/docx_schema/{page.id}/entries/{entry.id}/edit"
    return {"status": "success", "result": result, "validation_url": validation_url, "api_usage": _extract_usage(final)}


@shared_task(bind=True, name="app.tasks.data_schema.improve_entry")
def data_schema_improve_entry_task(self, page_id: int, entry_id: int, user_id: int, system_prompt: str, model: str, reasoning: str, verbosity: str, extra_instructions: Optional[str] = None, openai_cls=OpenAI):
    page = db.session.get(DocxSchemaPage, page_id)
    src = db.session.get(DocxSchemaEntry, entry_id)
    user = db.session.get(User, user_id)
    if not page or not src or not user or not user.openai_key:
        return {"status": "error", "message": "Paramètres invalides (page/entrée/utilisateur/clé)."}

    client = openai_cls(api_key=user.openai_key)
    schema = page.json_schema if isinstance(page.json_schema, dict) else {}
    input_blocks = [
        {"role": "system", "content": [{"type": "input_text", "text": system_prompt or ""}]},
        {"role": "user", "content": [
            {"type": "input_text", "text": (extra_instructions or "Améliorer les données en respectant le schéma.")},
            {"type": "input_text", "text": json.dumps(src.data, ensure_ascii=False)},
        ]},
    ]
    request_kwargs = dict(
        model=model,
        input=input_blocks,
        text=_build_text_format_for_schema(schema),
        reasoning={"effort": reasoning or "medium", "summary": "auto"},
        store=True,
    )
    final, streamed_text, _rs = _run_structured_stream(self, client, request_kwargs)
    payload = _parse_final_json(final, streamed_text) or {}
    if not isinstance(payload, (dict, list)):
        return {"status": "error", "message": "Réponse IA invalide."}

    entry = DocxSchemaEntry(page_id=page.id, data=payload, title=(payload.get('title') if isinstance(payload, dict) else None), created_by_id=user.id)
    db.session.add(entry)
    db.session.commit()

    result = {"entry_id": entry.id, "data": payload}
    validation_url = f"/docx_schema/{page.id}/entries/{entry.id}/edit"
    return {"status": "success", "result": result, "validation_url": validation_url, "api_usage": _extract_usage(final)}


@shared_task(bind=True, name="app.tasks.data_schema.import_from_file")
def data_schema_import_from_file_task(self, page_id: int, file_path: str, user_id: int, system_prompt: str, model: str, reasoning: str, verbosity: str, openai_cls=OpenAI):
    page = db.session.get(DocxSchemaPage, page_id)
    user = db.session.get(User, user_id)
    if not page or not user or not user.openai_key:
        return {"status": "error", "message": "Paramètres invalides (page/utilisateur/clé)."}

    pdf_path = _docx_to_pdf(file_path)
    client = openai_cls(api_key=user.openai_key)
    with open(pdf_path, "rb") as fh:
        uploaded = client.files.create(file=fh, purpose="user_data")

    schema = page.json_schema if isinstance(page.json_schema, dict) else {}
    input_blocks = [
        {"role": "system", "content": [{"type": "input_text", "text": system_prompt or ""}]},
        {"role": "user", "content": [
            {"type": "input_file", "file_id": uploaded.id},
            {"type": "input_text", "text": "Extraire strictement en JSON conforme au schéma."},
        ]},
    ]
    request_kwargs = dict(
        model=model,
        input=input_blocks,
        text=_build_text_format_for_schema(schema),
        reasoning={"effort": reasoning or "medium", "summary": "auto"},
        store=True,
    )

    final, streamed_text, _rs = _run_structured_stream(self, client, request_kwargs)
    payload = _parse_final_json(final, streamed_text) or {}
    if not isinstance(payload, (dict, list)):
        return {"status": "error", "message": "Réponse IA invalide."}

    entry = DocxSchemaEntry(page_id=page.id, data=payload, title=(payload.get('title') if isinstance(payload, dict) else None), created_by_id=user.id)
    db.session.add(entry)
    db.session.commit()

    result = {"entry_id": entry.id, "data": payload}
    validation_url = f"/docx_schema/{page.id}/entries/{entry.id}/edit"
    return {"status": "success", "result": result, "validation_url": validation_url, "api_usage": _extract_usage(final)}

