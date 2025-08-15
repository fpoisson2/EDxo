from __future__ import annotations

import argparse
import asyncio
import os
import sys

from agents import Runner, SQLiteSession
import logging
import warnings
import os
from sqlalchemy.exc import SAWarning
from src.utils.logging_config import setup_logging

from src.agent.context import EDxoContext, set_current_context
from src.agent.edxo_agent import build_agents


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser("edxo-agents", description="Run the EDxo multi-turn agent (OpenAI Agents SDK)")
    p.add_argument("--username", help="DB username for login (tools can also set this)")
    p.add_argument("--password", help="DB password for login (tools can also set this)")
    p.add_argument("--session-id", default="edxo_local", help="Session id for multi-turn memory")
    p.add_argument("--memory-db", default=None, help="SQLite file for session persistence (default: in-memory)")
    return p


async def main_async(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    # Quiet mode: reduce noisy logs and warnings in CLI runs
    # - Set env to avoid starting background scheduler logs
    os.environ.setdefault("GUNICORN_WORKER_ID", "1")
    os.environ.setdefault("LOG_LEVEL", "WARNING")

    # Configure project logging at WARNING
    setup_logging(level=logging.WARNING)
    # Silence common noisy loggers
    for name in [
        "httpx",
        "apscheduler",
        "apscheduler.scheduler",
        "src.celery_app",
        "src.utils.scheduler_instance",
        "flask_wtf.csrf",
        "werkzeug",
        "sqlalchemy",
        "agents",
        "agents.tracing",
        "openai",
        "celery",
    ]:
        logging.getLogger(name).setLevel(logging.ERROR)

    # Filter noisy warnings (SQLAlchemy relationship overlap, Flask-Limiter storage)
    warnings.filterwarnings("ignore", category=SAWarning)
    warnings.filterwarnings(
        "ignore",
        message=r"Using the in-memory storage for tracking rate limits.*",
        module=r"flask_limiter\.extension",
        category=UserWarning,
    )

    agent = build_agents()

    # Set context (credentials can be set dynamically via the use_account tool)
    ctx = EDxoContext(username=args.username, password=args.password)
    set_current_context(ctx)

    # Session memory for multi-turn
    session = SQLiteSession(args.session_id, args.memory_db) if args.memory_db else SQLiteSession(args.session_id)

    print("EDxo Agent ready. Type 'exit' or Ctrl-C to quit.")
    while True:
        try:
            user_input = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not user_input:
            continue
        if user_input.lower() in {"exit", "quit"}:
            break
        try:
            result = await Runner.run(agent, user_input, session=session)
            print("agent>", result.final_output)
        except Exception as e:
            print("agent> Error:", e, file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        return asyncio.run(main_async(argv))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
