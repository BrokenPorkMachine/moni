"""Replaceable scheduler, persistence, and notification boundaries."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path
    from agent import AgentInfo
    from history import StateTransition
    from moni import CheckResult


class CheckExecutor(Protocol):
    def run(self, checks: list[dict], workers: int | None = None) -> list["CheckResult"]:
        """Execute checks and return results in configuration order."""


class ObservationStore(Protocol):
    def record(self, path: "Path", results: list["CheckResult"]) -> list["StateTransition"]:
        """Persist observations and return state transitions."""


class TransitionNotifier(Protocol):
    def send(
        self, url: str, transitions: list["StateTransition"], *, attempts: int = 3
    ) -> bool:
        """Deliver state transitions without coupling delivery to execution."""


class ThreadedCheckExecutor:
    """Standard-library concurrent executor used by the local CLI agent."""

    def __init__(self, run_check: Callable[[dict], "CheckResult"]) -> None:
        self._run_check = run_check

    def run(self, checks: list[dict], workers: int | None = None) -> list["CheckResult"]:
        if not checks:
            return []
        max_workers = workers or min(32, len(checks))
        results: list["CheckResult" | None] = [None] * len(checks)
        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="moni") as pool:
            futures = {pool.submit(self._run_check, check): index for index, check in enumerate(checks)}
            for future in as_completed(futures):
                results[futures[future]] = future.result()
        return [item for item in results if item is not None]


class SQLiteObservationStore:
    def record(self, path: "Path", results: list["CheckResult"]) -> list["StateTransition"]:
        import history

        return history.record_results(path, results)


class WebhookTransitionNotifier:
    def send(
        self, url: str, transitions: list["StateTransition"], *, attempts: int = 3
    ) -> bool:
        import notifier

        return notifier.send_transitions(url, transitions, attempts=attempts)
