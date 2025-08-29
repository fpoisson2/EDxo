import json
import time
from flask import Blueprint, jsonify, current_app, render_template, url_for, request, stream_with_context
from flask_login import login_required

from ...celery_app import celery
from ...config.env import CELERY_BROKER_URL


tasks_bp = Blueprint("tasks", __name__, url_prefix="/tasks")


def _is_cancel_requested(task_id: str) -> bool:
    """Return True if a cooperative cancel flag is present in Redis for task_id."""
    try:
        import redis
        r = redis.Redis.from_url(CELERY_BROKER_URL)
        return bool(r.get(f"edxo:cancel:{task_id}"))
    except Exception:
        return False


def _is_task_known(task_id: str) -> bool:
    """Return True if the task appears anywhere (active/reserved/scheduled) or has a result key.

    This helps us treat unknown PENDING tasks (e.g., after server restart) as cleaned up.
    """
    try:
        # Check workers for any mention of the task
        insp = celery.control.inspect(timeout=0.5)
        for getter in (insp.active, insp.reserved, insp.scheduled):
            try:
                snapshot = getter() or {}
            except Exception:
                snapshot = {}
            for _w, tasks in (snapshot or {}).items():
                for t in tasks or []:
                    # Various shapes depending on Celery version
                    tid = None
                    if isinstance(t, dict):
                        tid = t.get('id') or (t.get('request') or {}).get('id')
                        if not tid and 'request' in t and hasattr(t['request'], 'id'):
                            tid = getattr(t['request'], 'id', None)
                    if tid and tid == task_id:
                        return True
        # Check Redis result backend for stored state
        try:
            import redis
            backend_url = celery.conf.result_backend
            r = redis.Redis.from_url(backend_url)
            # Common Celery backend key patterns
            if r.exists(f"celery-task-meta-{task_id}"):
                return True
            if r.exists(f"celery-task-set-meta-{task_id}"):
                return True
        except Exception:
            # If backend not accessible, we cannot assert existence; fall through
            pass
    except Exception:
        pass
    return False

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

    # Normalize stuck/unknown tasks to REVOKED for better UX
    if state in ("PENDING", "STARTED", "PROGRESS"):
        if _is_cancel_requested(task_id):
            state = "REVOKED"
            if isinstance(meta, dict):
                meta = {**meta, "message": meta.get("message") or "Tâche annulée (avant démarrage)."}
            else:
                meta = {"message": "Tâche annulée (avant démarrage)."}
        elif not _is_task_known(task_id):
            # After restart, a started/progress task may be orphaned; present as revoked/cleaned
            state = "REVOKED"
            msg = "Tâche interrompue/nettoyée après redémarrage."
            meta = {**meta, "message": meta.get("message") or msg} if isinstance(meta, dict) else {"message": msg}
    message = meta.get("message") if isinstance(meta, dict) else None

    result_payload = res.result if state == "SUCCESS" else None
    if state == "SUCCESS" and not result_payload:
        result_payload = meta if isinstance(meta, dict) else None
    # Map logical error payloads to FAILURE for better UX
    try:
        if state == "SUCCESS":
            payload = result_payload if isinstance(result_payload, dict) else {}
            # Some tasks return {'status': 'error', 'message': '...'} on exceptions
            if isinstance(payload, dict) and (payload.get('status') == 'error'):
                state = "FAILURE"
                if not message:
                    message = payload.get('message') or ''
    except Exception:
        pass

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
        # Prefer a cooperative sleep when available (gevent), else fallback
        try:
            from gevent import sleep as _sleep
        except Exception:
            _sleep = time.sleep

        # Avoid expensive Celery inspect on every loop when PENDING
        pending_ticks = 0
        while True:
            try:
                res = AsyncResult(task_id, app=celery)
                state = res.state
                meta = res.info if isinstance(res.info, dict) else {}

                # Mirror the status endpoint: if cancel flag is set or task is unknown, treat as REVOKED
                if state in ("PENDING", "STARTED", "PROGRESS"):
                    pending_ticks += 1
                    if _is_cancel_requested(task_id):
                        state = "REVOKED"
                        if isinstance(meta, dict):
                            meta = {**meta, "message": meta.get("message") or "Tâche annulée (avant démarrage)."}
                        else:
                            meta = {"message": "Tâche annulée (avant démarrage)."}
                    elif (pending_ticks % 15) == 0:  # check at most ~ every 15s
                        if not _is_task_known(task_id):
                            state = "REVOKED"
                            msg = "Tâche interrompue/nettoyée après redémarrage."
                            meta = {**meta, "message": meta.get("message") or msg} if isinstance(meta, dict) else {"message": msg}
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
                _sleep(1.0)
            except GeneratorExit:
                # Client disconnected; stop the generator quickly
                break
            except Exception as e:
                yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"
                break

    headers = {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache, no-transform",
        "Connection": "keep-alive",
        # Disable buffering if behind Nginx
        "X-Accel-Buffering": "no",
    }
    return current_app.response_class(stream_with_context(event_stream()), headers=headers)


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
