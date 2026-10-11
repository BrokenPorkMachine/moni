"""Small loopback HTTP surface for Moni's current check state."""

from __future__ import annotations

import json
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock
from typing import Any
from urllib.parse import urlparse

import agent


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


def make_handler(
    store: StateStore,
    auth_token: str | None = None,
    coordinator: agent.Coordinator | None = None,
) -> type[BaseHTTPRequestHandler]:
    class MoniHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if auth_token is not None:
                provided = self.headers.get("Authorization", "")
                if not hmac.compare_digest(provided, f"Bearer {auth_token}"):
                    self._send(401, {"error": "authentication required"})
                    return
            path = urlparse(self.path).path
            results = store.snapshot()
            if path == "/health":
                payload = {"ok": all(item["ok"] for item in results), "checks": len(results)}
                self._send(200, payload)
            elif path == "/checks":
                self._send(200, {"checks": results})
            else:
                self._send(404, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            if coordinator is None or urlparse(self.path).path != "/reports":
                self._send(404, {"error": "not found"})
                return
            signature = self.headers.get("X-Moni-Signature", "")
            try:
                length = int(self.headers.get("Content-Length", "0"))
                report = json.loads(self.rfile.read(length))
                coordinator.accept(report, signature)
            except (ValueError, TypeError, json.JSONDecodeError, agent.ReportError) as exc:
                self._send(401, {"error": str(exc)})
                return
            self._send(202, {"accepted": True})

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


def create_server(
    host: str,
    port: int,
    store: StateStore,
    auth_token: str | None = None,
    coordinator: agent.Coordinator | None = None,
) -> ThreadingHTTPServer:
    if host not in {"127.0.0.1", "localhost", "::1"} and not auth_token:
        raise ValueError("--auth-token is required for non-loopback service binds")
    return ThreadingHTTPServer((host, port), make_handler(store, auth_token, coordinator))
