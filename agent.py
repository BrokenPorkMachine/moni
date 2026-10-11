"""Agent identity and authenticated result transport primitives."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import json
import time
from typing import Any
from uuid import uuid4


@dataclass(frozen=True)
class AgentInfo:
    name: str
    version: str
    capabilities: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "version": self.version,
            "capabilities": list(self.capabilities),
        }


class ReportError(ValueError):
    """Raised when an agent report is invalid or cannot be authenticated."""


def _canonical_report(report: dict[str, Any]) -> bytes:
    return json.dumps(report, sort_keys=True, separators=(",", ":")).encode("utf-8")


def create_report(
    info: AgentInfo,
    results: list[dict[str, Any]],
    *,
    report_id: str | None = None,
    sent_at: float | None = None,
    nonce: str | None = None,
) -> dict[str, Any]:
    """Create a deterministic, transport-ready report envelope."""
    return {
        "agent": info.as_dict(),
        "report_id": report_id or str(uuid4()),
        "sent_at": time.time() if sent_at is None else sent_at,
        "nonce": nonce or str(uuid4()),
        "results": results,
    }


def sign_report(report: dict[str, Any], secret: str) -> str:
    if not secret:
        raise ReportError("agent secret must be non-empty")
    digest = hmac.new(secret.encode("utf-8"), _canonical_report(report), hashlib.sha256).hexdigest()
    return f"sha256={digest}"


class Coordinator:
    """Accept authenticated reports and expose the latest result per agent."""

    def __init__(self, secrets: dict[str, str], *, max_age_seconds: float = 300.0) -> None:
        if not secrets or any(not name or not secret for name, secret in secrets.items()):
            raise ValueError("coordinator requires non-empty agent secrets")
        if max_age_seconds <= 0:
            raise ValueError("max_age_seconds must be positive")
        self.secrets = dict(secrets)
        self.max_age_seconds = max_age_seconds
        self._reports: dict[str, dict[str, Any]] = {}
        self._accepted_ids: set[str] = set()
        self._accepted_nonces: set[tuple[str, str]] = set()

    def accept(self, report: dict[str, Any], signature: str, *, now: float | None = None) -> None:
        """Verify and accept one report, rejecting replay and forged writes."""
        if not isinstance(report, dict):
            raise ReportError("report must be an object")
        identity = report.get("agent")
        if not isinstance(identity, dict) or not isinstance(identity.get("name"), str):
            raise ReportError("report.agent.name must be a string")
        name = identity["name"]
        secret = self.secrets.get(name)
        if secret is None or not isinstance(signature, str):
            raise ReportError("unknown agent or missing signature")
        expected = sign_report(report, secret)
        if not hmac.compare_digest(signature, expected):
            raise ReportError("invalid report signature")
        report_id = report.get("report_id")
        nonce = report.get("nonce")
        sent_at = report.get("sent_at")
        if not isinstance(report_id, str) or not report_id:
            raise ReportError("report_id must be a non-empty string")
        if not isinstance(nonce, str) or not nonce:
            raise ReportError("nonce must be a non-empty string")
        if not isinstance(sent_at, (int, float)) or isinstance(sent_at, bool):
            raise ReportError("sent_at must be a number")
        current = time.time() if now is None else now
        if abs(current - sent_at) > self.max_age_seconds:
            raise ReportError("report is outside the accepted time window")
        if report_id in self._accepted_ids or (name, nonce) in self._accepted_nonces:
            raise ReportError("duplicate report")
        self._accepted_ids.add(report_id)
        self._accepted_nonces.add((name, nonce))
        self._reports[name] = dict(report)

    def snapshot(self) -> list[dict[str, Any]]:
        return [dict(self._reports[name]) for name in sorted(self._reports)]


def local_agent(name: str = "local") -> AgentInfo:
    if not name.strip():
        raise ValueError("agent name must be non-empty")
    return AgentInfo(
        name=name,
        version="0.1.0",
        capabilities=("http", "tcp", "history", "webhook"),
    )
