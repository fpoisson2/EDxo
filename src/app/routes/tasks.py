import json
import time
from flask import Blueprint, jsonify, current_app, render_template, url_for, request
from flask_login import login_required

from ...celery_app import celery
from ...config.env import CELERY_BROKER_URL


tasks_bp = Blueprint("tasks", __name__, url_prefix="/tasks")


@tasks_bp.get("/status/<task_id>")
@login_required
def unified_task_status(task_id):
    """Return a unified JSON status for any Celery task.

    Response keys:
    - state: PENDING|PROGRESS|SUCCESS|FAILURE|REVOKED
    - message: optional short message from task meta
    - meta: full meta dict if provided
    - result: final task result when SUCCESS (fallback to meta if empty)
    """
    from celery.result import AsyncResult

    res = AsyncResult(task_id, app=celery)
    state = res.state
    meta = res.info if isinstance(res.info, dict) else {}
    message = meta.get("message") if isinstance(meta, dict) else None

    result_payload = res.result if state == "SUCCESS" else None
    if state == "SUCCESS" and not result_payload:
        result_payload = meta if isinstance(meta, dict) else None

    current_app.logger.info("[tasks.status] %s -> %s", task_id, state)
    return jsonify({
        "task_id": task_id,
        "state": state,
        "message": message or "",
        "meta": meta,
        "result": result_payload,
    })


@tasks_bp.get("/events/<task_id>")
@login_required
def unified_task_events(task_id):
    """Server-Sent Events (SSE) stream for task progress, polling the backend.

    Emits events: open, progress, ping, done, error.
    """
    from celery.result import AsyncResult

    def event_stream():
        last_snapshot = None
        yield "event: open\ndata: {}\n\n"
        while True:
            try:
                res = AsyncResult(task_id, app=celery)
                state = res.state
                meta = res.info if isinstance(res.info, dict) else {}
                snapshot = (state, json.dumps(meta, sort_keys=True, ensure_ascii=False))
                if snapshot != last_snapshot:
                    payload = {"state": state, "meta": meta}
                    yield f"event: progress\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                    last_snapshot = snapshot
                if state in ("SUCCESS", "FAILURE", "REVOKED"):
                    payload = {"state": state, "result": res.result if state == "SUCCESS" else None, "meta": meta}
                    yield f"event: done\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                    break
                yield "event: ping\ndata: {}\n\n"
                time.sleep(1.0)
            except Exception as e:
                yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"
                break

    headers = {"Content-Type": "text/event-stream", "Cache-Control": "no-cache", "Connection": "keep-alive"}
    return current_app.response_class(event_stream(), headers=headers)


@tasks_bp.post("/cancel/<task_id>")
@login_required
def cancel_task(task_id):
    """Request cancellation of a Celery task.

    Attempts to revoke the task and terminate it if running. Returns JSON with
    a best-effort view of the resulting state (REVOKED if applicable).
    """
    try:
        from celery.result import AsyncResult
        # Best-effort revoke; terminate running task with SIGTERM
        celery.control.revoke(task_id, terminate=True, signal="SIGTERM")

        # Cooperative cancel flag via Redis (checked by long-running tasks)
        try:
            import redis
            r = redis.Redis.from_url(CELERY_BROKER_URL)
            r.setex(f"edxo:cancel:{task_id}", 3600, "1")
        except Exception:
            current_app.logger.warning("[tasks.cancel] Redis flag not set (continuing nonetheless)")

        res = AsyncResult(task_id, app=celery)
        state = res.state
        current_app.logger.info("[tasks.cancel] %s -> revoke requested; state=%s", task_id, state)

        return jsonify({
            "ok": True,
            "task_id": task_id,
            "state": state,
            "message": "Annulation demandée.",
        }), 202
    except Exception as e:
        current_app.logger.exception("[tasks.cancel] Failed to revoke %s: %s", task_id, e)
        return jsonify({
            "ok": False,
            "task_id": task_id,
            "error": str(e),
        }), 500


@tasks_bp.get("/track/<task_id>")
@login_required
def track_task(task_id):
    """Render a generic tracking page for any task using the shared template."""
    status_api_url = url_for("tasks.unified_task_status", task_id=task_id)
    events_url = url_for("tasks.unified_task_events", task_id=task_id)
    return render_template(
        "task_status.html",
        task_id=task_id,
        status_api_url=status_api_url,
        events_url=events_url,
    )
