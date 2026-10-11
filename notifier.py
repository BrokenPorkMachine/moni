"""Retrying webhook delivery for Moni state transitions."""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING
from urllib.parse import urlparse
from urllib.request import Request, urlopen

if TYPE_CHECKING:
    from history import StateTransition


def valid_webhook_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def send_transitions(
    url: str,
    transitions: list["StateTransition"],
    *,
    attempts: int = 3,
    backoff_seconds: float = 0.25,
) -> bool:
    """Send changed transitions, retrying failures with exponential backoff."""
    changed = [transition for transition in transitions if transition.changed]
    if not changed:
        return True
    payload = json.dumps(
        {
            "events": [
                {
                    "name": transition.name,
                    "type": transition.type,
                    "previous_ok": transition.previous_ok,
                    "current_ok": transition.current_ok,
                    "changed_at": transition.changed_at,
                }
                for transition in changed
            ]
        }
    ).encode("utf-8")
    request = Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "Moni/0.1"},
        method="POST",
    )
    for attempt in range(max(1, attempts)):
        try:
            with urlopen(request, timeout=5) as response:
                response.read(1)
                if 200 <= response.status < 300:
                    return True
        except OSError:
            pass
        if attempt + 1 < max(1, attempts):
            time.sleep(backoff_seconds * (2**attempt))
    return False
