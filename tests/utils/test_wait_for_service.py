from __future__ import annotations

import socket
import socketserver
import threading
import time

import pytest

from src.utils.wait_for_service import wait_for_service


class _NoopHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:  # pragma: no cover - the test never sends data
        pass


def _start_tcp_server() -> tuple[socketserver.TCPServer, threading.Thread]:
    server = socketserver.TCPServer(("127.0.0.1", 0), _NoopHandler)
    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()
    return server, thread


def test_wait_for_service_returns_when_service_is_available() -> None:
    server, thread = _start_tcp_server()
    try:
        wait_for_service("127.0.0.1", server.server_address[1], timeout=2.0, interval=0.05)
    finally:
        server.shutdown()
        thread.join(timeout=1)
        server.server_close()


def test_wait_for_service_raises_timeout_when_unreachable() -> None:
    unused_port = _find_unused_port()
    start = time.monotonic()
    with pytest.raises(TimeoutError):
        wait_for_service("127.0.0.1", unused_port, timeout=0.3, interval=0.05)
    assert time.monotonic() - start >= 0.3


def _find_unused_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]
