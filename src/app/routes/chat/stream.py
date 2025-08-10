"""Logique de diffusion SSE simplifiée."""
import json
from typing import Iterable, List


def simple_stream(message: str, history: List[object]) -> Iterable[str]:
    """Génère un flux SSE très simple."""
    yield "data: " + json.dumps({"type": "content", "content": message}) + "\n\n"
    yield "data: {\"type\": \"done\"}\n\n"
