"""Utility helpers to wait for network services before starting workers."""
from __future__ import annotations

import argparse
import socket
import sys
import time
from typing import Iterable, Tuple

AddressInfo = Tuple[int, int, int, str, Tuple[str, int]]


def _iter_addresses(host: str, port: int) -> Iterable[AddressInfo]:
    """Yield address info tuples for ``host``/``port``.

    A thin wrapper over ``socket.getaddrinfo`` that normalises the call and
    always requests TCP sockets. The helper exists so it can be patched during
    tests if needed.
    """

    return socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)


def wait_for_service(host: str, port: int, *, timeout: float = 30.0, interval: float = 1.0) -> None:
    """Block until ``host:port`` is reachable or raise ``TimeoutError``.

    The function tries to resolve and connect to the service repeatedly until
    ``timeout`` seconds elapse. ``interval`` controls the delay between attempts.
    """

    deadline = time.monotonic() + timeout
    last_error: Exception | None = None

    while time.monotonic() < deadline:
        try:
            addresses = list(_iter_addresses(host, port))
        except socket.gaierror as exc:  # DNS resolution failure
            last_error = exc
            time.sleep(interval)
            continue

        for family, socktype, proto, _canonname, sockaddr in addresses:
            sock = socket.socket(family, socktype, proto)
            try:
                sock.settimeout(interval)
                sock.connect(sockaddr)
            except OSError as exc:
                last_error = exc
                continue
            else:
                sock.close()
                return
            finally:
                sock.close()

        time.sleep(interval)

    error_message = f"Timed out after {timeout:.1f}s waiting for {host}:{port}"
    if last_error:
        error_message += f" ({last_error})"
    raise TimeoutError(error_message)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Wait for a TCP service to become available.")
    parser.add_argument("host", help="Hostname or IP address of the service")
    parser.add_argument("port", type=int, help="Port of the service")
    parser.add_argument("--timeout", type=float, default=30.0, help="Maximum wait time in seconds (default: 30)")
    parser.add_argument("--interval", type=float, default=1.0, help="Delay between attempts in seconds (default: 1)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    try:
        wait_for_service(args.host, args.port, timeout=args.timeout, interval=args.interval)
    except TimeoutError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
