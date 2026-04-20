"""Factory helpers for building plan-cadre / plan-de-cours agents and
relaying their streaming events to Celery task meta (consumed by the existing
`/tasks/events/<task_id>` SSE endpoint).
"""
from __future__ import annotations

import json
import logging
from typing import Any, Iterable, List, Optional, Sequence, Type

from agents import Agent, ModelSettings, Runner
from celery.exceptions import Ignore
from pydantic import BaseModel, create_model

from src.config.env import CELERY_BROKER_URL

logger = logging.getLogger(__name__)


def _cancel_requested(task_id: Optional[str]) -> bool:
    if not task_id:
        return False
    try:
        import redis

        r = redis.Redis.from_url(CELERY_BROKER_URL)
        return bool(r.get(f"edxo:cancel:{task_id}"))
    except Exception:
        return False


def _truncate(value: Any, limit: int = 500) -> str:
    try:
        if isinstance(value, (dict, list)):
            s = json.dumps(value, ensure_ascii=False)
        else:
            s = str(value)
    except Exception:
        s = repr(value)
    return s if len(s) <= limit else (s[:limit] + "…")


def build_partial_response_type(
    base_type: Type[BaseModel],
    fields: Sequence[str],
    *,
    name_suffix: str = "Partial",
) -> Type[BaseModel]:
    """Create a dynamic Pydantic submodel keeping only the requested fields.

    Used when the user asks for a targeted improvement (e.g. a single column
    of the plan-cadre or a single field of the plan-de-cours) so the agent
    returns only the relevant subset.
    """
    kept = [f for f in fields if f in base_type.model_fields]
    if not kept:
        return base_type
    submodel_fields = {}
    for f in kept:
        model_field = base_type.model_fields[f]
        submodel_fields[f] = (model_field.annotation, model_field)
    name = f"{base_type.__name__}{name_suffix}"
    return create_model(name, __base__=BaseModel, **submodel_fields)


def build_agent(
    *,
    name: str,
    instructions: str,
    model: str,
    reasoning_effort: Optional[str] = None,
    verbosity: Optional[str] = None,
    output_type: Type[BaseModel],
    tools: Sequence[Any],
) -> Agent:
    """Construct an Agents SDK `Agent` preserving our reasoning/verbosity knobs."""
    settings_kwargs: dict = {}
    reasoning: dict = {"summary": "auto"}
    if reasoning_effort in {"minimal", "low", "medium", "high"}:
        reasoning["effort"] = reasoning_effort
    settings_kwargs["reasoning"] = reasoning
    # Note: `verbosity` is currently not passed through because the Agents
    # SDK claims the `text` parameter for structured output, preventing us
    # from injecting `text.verbosity` without breaking JSON schema
    # enforcement. The setting is read but ignored for now; revisit when
    # the SDK exposes a first-class `verbosity` field.
    _ = verbosity
    return Agent(
        name=name,
        instructions=instructions or "",
        model=model,
        model_settings=ModelSettings(**settings_kwargs),
        tools=list(tools),
        output_type=output_type,
    )


class AgentCeleryBridge:
    """Relay Agents SDK stream events into Celery's `update_state` stream.

    Emits:
      * `meta.stream_chunk` + `meta.stream_buffer` + `meta.seq` on text deltas
      * `meta.reasoning_summary` on reasoning deltas
      * `meta.tool_call` on each tool invocation
      * `meta.tool_result` on each tool result (truncated preview)
    """

    def __init__(self, task):
        self.task = task
        self.task_id = getattr(getattr(task, "request", None), "id", None)
        self.buffer = ""
        self.seq = 0
        self.reasoning_summary = ""
        self.tool_calls: List[dict] = []
        self.tool_results: List[dict] = []

    def _emit(self, meta: dict) -> None:
        try:
            self.task.update_state(state="PROGRESS", meta=meta)
        except Exception:
            logger.exception("[agent] failed to update Celery state")

    def _handle_raw_event(self, data: Any) -> None:
        etype = getattr(data, "type", "") or ""
        if etype.endswith("response.output_text.delta") or etype == "response.output_text.delta":
            delta = getattr(data, "delta", "") or getattr(data, "text", "") or ""
            if delta:
                self.buffer += delta
                self.seq += 1
                self._emit({
                    "message": "Génération en cours...",
                    "stream_chunk": delta,
                    "stream_buffer": self.buffer,
                    "seq": self.seq,
                })
        elif (
            etype.endswith("response.reasoning_summary_text.delta")
            or etype == "response.reasoning_summary_text.delta"
        ):
            rs = getattr(data, "delta", "") or ""
            if rs:
                self.reasoning_summary = (self.reasoning_summary + rs).strip()
                self._emit({
                    "message": "Résumé du raisonnement",
                    "reasoning_summary": self.reasoning_summary,
                })

    def _handle_run_item(self, item: Any) -> None:
        item_type = getattr(item, "type", "") or ""
        raw = getattr(item, "raw_item", None)
        if item_type == "tool_call_item":
            name = (
                getattr(raw, "name", None)
                or getattr(item, "name", None)
                or "tool"
            )
            arguments_raw = getattr(raw, "arguments", None)
            try:
                arguments = json.loads(arguments_raw) if isinstance(arguments_raw, str) else arguments_raw
            except Exception:
                arguments = arguments_raw
            call_id = (
                getattr(raw, "call_id", None)
                or getattr(raw, "id", None)
                or getattr(item, "call_id", None)
            )
            record = {"name": name, "arguments": arguments, "call_id": call_id}
            self.tool_calls.append(record)
            self._emit({
                "message": f"Outil: {name}",
                "tool_call": record,
            })
        elif item_type == "tool_call_output_item":
            call_id = (
                getattr(raw, "call_id", None)
                or getattr(raw, "id", None)
                or getattr(item, "call_id", None)
            )
            output = getattr(item, "output", None)
            if output is None:
                output = getattr(raw, "output", None)
            record = {"call_id": call_id, "output_preview": _truncate(output, 500)}
            self.tool_results.append(record)
            self._emit({
                "message": "Résultat d'outil",
                "tool_result": record,
            })

    async def consume(self, streamed_result) -> None:
        """Iterate `stream_events()` of a RunResultStreaming object.

        Raises celery `Ignore` when cancellation is requested.
        """
        async for event in streamed_result.stream_events():
            if _cancel_requested(self.task_id):
                try:
                    streamed_result.cancel()
                except Exception:
                    pass
                self._emit({"message": "Tâche annulée par l'utilisateur."})
                raise Ignore()
            etype = getattr(event, "type", "")
            if etype == "raw_response_event":
                self._handle_raw_event(getattr(event, "data", None))
            elif etype == "run_item_stream_event":
                name = getattr(event, "name", "")
                item = getattr(event, "item", None)
                logger.info("[agent] run_item_stream_event name=%s item_type=%s", name, getattr(item, "type", None))
                self._handle_run_item(item)


def aggregate_usage(raw_responses: Iterable[Any]) -> tuple[int, int]:
    """Sum input/output tokens across every Responses API turn."""
    total_in = 0
    total_out = 0
    for r in raw_responses or []:
        usage = getattr(r, "usage", None)
        if not usage:
            continue
        try:
            total_in += int(getattr(usage, "input_tokens", 0) or 0)
            total_out += int(getattr(usage, "output_tokens", 0) or 0)
        except Exception:
            continue
    return total_in, total_out


async def run_agent_streaming(agent: Agent, seed_input: str, *, bridge: AgentCeleryBridge):
    """Execute the agent with streaming and push events to Celery meta.

    Returns the final `RunResultStreaming` object (which exposes
    `final_output` and `raw_responses`).
    """
    result = Runner.run_streamed(agent, input=seed_input)
    await bridge.consume(result)
    return result
