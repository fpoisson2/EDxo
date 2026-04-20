"""Human-in-the-loop agent tool: request a partial review from the user.

When invoked, the tool:
1. Publishes a `review_request` meta update on the running Celery task so the
   frontend (SSE) can open a modal displaying the proposal.
2. Subscribes to a Redis pub/sub channel and blocks until the user submits
   feedback (via `POST /tasks/<task_id>/review_response`) or the timeout
   elapses.
3. Returns the user's free-text feedback to the agent so it can iterate.

Returns the literal string `"TIMEOUT"` if no answer arrives in the allowed
window, or `"CANCELLED"` if the task was cancelled during the wait.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any, Dict, Optional

import redis as redis_lib
from agents import function_tool
from celery import current_task

from src.config.env import CELERY_BROKER_URL

logger = logging.getLogger(__name__)


def _cancel_flag(task_id: str) -> bool:
    try:
        r = redis_lib.Redis.from_url(CELERY_BROKER_URL)
        return bool(r.get(f"edxo:cancel:{task_id}"))
    except Exception:
        return False


def _publish_review_request(task_id: str, payload: Dict[str, Any]) -> None:
    """Expose the review request to the frontend via Celery task meta.

    We intentionally stamp the meta on the existing Celery task (so SSE
    consumers pick it up through `/tasks/events/<task_id>`). We avoid
    overwriting existing progress keys by merging a dedicated nested dict.
    """
    if current_task is None:
        return
    try:
        meta = {
            "message": payload.get("question") or "Révision partielle demandée",
            "review_request": payload,
        }
        current_task.update_state(state="PROGRESS", meta=meta)
    except Exception:
        logger.exception("[agent] unable to publish review request")


def _wait_for_feedback_sync(task_id: str, review_id: str, timeout_seconds: int) -> str:
    """Block until feedback arrives on the Redis channel, or timeout/cancel."""
    channel = f"edxo:review_response:{task_id}:{review_id}"
    try:
        r = redis_lib.Redis.from_url(CELERY_BROKER_URL)
    except Exception:
        logger.exception("[agent] redis unavailable for review tool")
        return "TIMEOUT"
    pubsub = r.pubsub()
    try:
        pubsub.subscribe(channel)
        # Drain the subscribe confirmation
        for _ in range(5):
            msg = pubsub.get_message(timeout=0.1)
            if msg is None:
                break
        deadline_ticks = max(1, int(timeout_seconds * 2))
        for _ in range(deadline_ticks):
            if _cancel_flag(task_id):
                return "CANCELLED"
            msg = pubsub.get_message(timeout=0.5)
            if not msg:
                continue
            if msg.get("type") != "message":
                continue
            data = msg.get("data")
            if isinstance(data, (bytes, bytearray)):
                try:
                    data = data.decode("utf-8")
                except Exception:
                    data = data.decode("utf-8", errors="replace")
            if not data:
                continue
            try:
                parsed = json.loads(data)
                if isinstance(parsed, dict) and "feedback" in parsed:
                    return str(parsed.get("feedback") or "")
            except Exception:
                return str(data)
            return str(data)
        return "TIMEOUT"
    finally:
        try:
            pubsub.unsubscribe(channel)
            pubsub.close()
        except Exception:
            pass


@function_tool
async def request_user_review(
    section: str,
    proposed_content_json: str,
    question: str,
    timeout_seconds: int = 600,
) -> str:
    """Present a partial proposal to the user and wait for their feedback.

    Args:
        section: Section identifier ("objectif_terminal", "calendrier", ...).
        proposed_content_json: JSON-encoded payload the user will see/review.
        question: Concrete question to the user ("Ce plan te convient-il ?").
        timeout_seconds: Maximum wait time before returning "TIMEOUT".

    Returns:
        The user's textual feedback, or "ACCEPTED" if they approved as-is,
        or "TIMEOUT"/"CANCELLED" in the corresponding cases.
    """
    task_id = None
    try:
        if current_task is not None:
            task_id = current_task.request.id
    except Exception:
        task_id = None

    if not task_id:
        return "TIMEOUT"

    try:
        proposed_content = json.loads(proposed_content_json) if proposed_content_json else {}
    except Exception:
        proposed_content = {"raw": proposed_content_json}

    review_id = uuid.uuid4().hex
    payload = {
        "review_id": review_id,
        "section": section,
        "question": question,
        "proposed_content": proposed_content,
        "timeout_seconds": int(timeout_seconds),
    }
    _publish_review_request(task_id, payload)

    feedback = await asyncio.to_thread(
        _wait_for_feedback_sync, task_id, review_id, int(timeout_seconds)
    )
    logger.info("[agent] review %s received feedback (%d chars)", review_id, len(feedback or ""))
    return feedback or "TIMEOUT"


REVIEW_TOOLS = [request_user_review]
