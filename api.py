"""Small loopback HTTP surface for Moni's current check state."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock
from typing import Any
from urllib.parse import urlparse


class StateStore:
    def __init__(self) -> None:
        self._lock = Lock()
        self._results: list[dict[str, Any]] = []

    def replace(self, results: list[dict[str, Any]]) -> None:
        with self._lock:
            self._results = [dict(result) for result in results]

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(result) for result in self._results]


def make_handler(store: StateStore) -> type[BaseHTTPRequestHandler]:
    class MoniHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            results = store.snapshot()
            if path == "/health":
                payload = {"ok": all(item["ok"] for item in results), "checks": len(results)}
                self._send(200, payload)
            elif path == "/checks":
                self._send(200, {"checks": results})
            else:
                self._send(404, {"error": "not found"})

        def _send(self, status: int, payload: dict[str, Any]) -> None:
            body = (json.dumps(payload, sort_keys=True) + "\n").encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:
            return

    return MoniHandler


def create_server(host: str, port: int, store: StateStore) -> ThreadingHTTPServer:
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("serve host must be loopback until API authentication is implemented")
    return ThreadingHTTPServer((host, port), make_handler(store))
