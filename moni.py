#!/usr/bin/env python3
"""Moni: small dependency-free HTTP/TCP service monitor."""

from __future__ import annotations

import argparse
import json
import socket
import history
import notifier
import sys
import threading
import time
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2
VERSION = "0.1.0"


class ConfigError(ValueError):
    """Raised when a Moni configuration is invalid."""


@dataclass(frozen=True)
class CheckResult:
    name: str
    type: str
    ok: bool
    latency_ms: float | None
    status: int | None = None
    error: str | None = None


def load_config(path: Path) -> list[dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"cannot read config {path}: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("checks"), list):
        raise ConfigError("config must be an object with a checks array")
    checks = data["checks"]
    for index, check in enumerate(checks):
        validate_check(check, index)
    return checks


def validate_check(check: Any, index: int = 0) -> None:
    if not isinstance(check, dict):
        raise ConfigError(f"checks[{index}] must be an object")
    name = check.get("name")
    kind = check.get("type")
    if not isinstance(name, str) or not name.strip():
        raise ConfigError(f"checks[{index}].name must be a non-empty string")
    if kind not in {"http", "tcp"}:
        raise ConfigError(f"checks[{index}].type must be http or tcp")
    timeout = check.get("timeout_seconds", 5)
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout <= 0:
        raise ConfigError(f"checks[{index}].timeout_seconds must be positive")
    if kind == "http":
        url = check.get("url")
        if not isinstance(url, str) or not url.startswith(("http://", "https://")):
            raise ConfigError(f"checks[{index}].url must be an HTTP(S) URL")
        expected = check.get("expected_status", 200)
        if not isinstance(expected, int) or not 100 <= expected <= 599:
            raise ConfigError(f"checks[{index}].expected_status must be an HTTP status")
    else:
        if not isinstance(check.get("host"), str) or not check["host"]:
            raise ConfigError(f"checks[{index}].host must be a non-empty string")
        port = check.get("port")
        if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
            raise ConfigError(f"checks[{index}].port must be between 1 and 65535")


def run_http(check: dict[str, Any]) -> CheckResult:
    started = time.monotonic()
    name = check["name"]
    timeout = float(check.get("timeout_seconds", 5))
    expected = check.get("expected_status", 200)
    try:
        request = Request(check["url"], headers={"User-Agent": "Moni/0.1"}, method="GET")
        with urlopen(request, timeout=timeout) as response:
            status = response.status
            response.read(1)
        ok = status == expected
        error = None if ok else f"expected HTTP {expected}, got {status}"
        return result(check, ok, started, status=status, error=error)
    except HTTPError as exc:
        status = exc.code
        error = f"expected HTTP {expected}, got {status}"
        return result(check, status == expected, started, status=status, error=error)
    except (OSError, URLError, TimeoutError) as exc:
        return result(check, False, started, error=str(exc) or exc.__class__.__name__)


def run_tcp(check: dict[str, Any]) -> CheckResult:
    started = time.monotonic()
    try:
        with socket.create_connection(
            (check["host"], check["port"]), timeout=float(check.get("timeout_seconds", 5))
        ):
            pass
        return result(check, True, started)
    except (OSError, TimeoutError) as exc:
        return result(check, False, started, error=str(exc) or exc.__class__.__name__)


def result(
    check: dict[str, Any], ok: bool, started: float, *, status: int | None = None, error: str | None = None
) -> CheckResult:
    return CheckResult(
        name=check["name"],
        type=check["type"],
        ok=ok,
        latency_ms=round((time.monotonic() - started) * 1000, 2),
        status=status,
        error=error,
    )


def run_check(check: dict[str, Any]) -> CheckResult:
    return run_http(check) if check["type"] == "http" else run_tcp(check)


def run_checks(checks: list[dict[str, Any]], workers: int | None = None) -> list[CheckResult]:
    if not checks:
        return []
    max_workers = workers or min(32, len(checks))
    results: list[CheckResult | None] = [None] * len(checks)
    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="moni") as pool:
        futures = {pool.submit(run_check, check): index for index, check in enumerate(checks)}
        for future in as_completed(futures):
            results[futures[future]] = future.result()
    return [item for item in results if item is not None]


def render(results: list[CheckResult], json_output: bool) -> str:
    if json_output:
        return json.dumps([asdict(item) for item in results], indent=2) + "\n"
    lines = []
    for item in results:
        state = "PASS" if item.ok else "FAIL"
        detail = f" HTTP {item.status}" if item.status is not None else ""
        if item.error:
            detail += f" — {item.error}"
        lines.append(f"{state} {item.name} [{item.type}] {item.latency_ms:.2f} ms{detail}")
    return "\n".join(lines) + ("\n" if lines else "No checks configured.\n")


def render_history(rows: list[dict[str, Any]], json_output: bool) -> str:
    if json_output:
        return json.dumps(rows, indent=2) + "\n"
    if not rows:
        return "No observations.\n"
    lines = []
    for row in rows:
        state = "PASS" if row["ok"] else "FAIL"
        checked_at = datetime.fromtimestamp(row["checked_at"], timezone.utc).isoformat()
        detail = f" HTTP {row['status']}" if row["status"] is not None else ""
        if row["error"]:
            detail += f" — {row['error']}"
        lines.append(f"{checked_at} {state} {row['name']} [{row['type']}] {row['latency_ms']:.2f} ms{detail}")
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="moni", description="Check HTTP and TCP services.")
    parser.add_argument("--version", action="version", version=f"moni {VERSION}")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("validate", "check"):
        sub = subparsers.add_parser(command)
        sub.add_argument("config", type=Path)
        if command == "check":
            sub.add_argument("--json", action="store_true", help="emit JSON results")
            sub.add_argument("--workers", type=int, default=None)
            sub.add_argument(
                "--repeat",
                type=float,
                default=None,
                metavar="SECONDS",
                help="repeat checks until interrupted",
            )
            sub.add_argument("--history", type=Path, default=None, metavar="PATH", help="append results to SQLite")
            sub.add_argument("--webhook", default=None, metavar="URL", help="POST changed states to a webhook")
            sub.add_argument("--webhook-attempts", type=int, default=3, metavar="N")
    history_parser = subparsers.add_parser("history", help="inspect stored observations")
    history_parser.add_argument("path", type=Path)
    history_parser.add_argument("--limit", type=int, default=20)
    history_parser.add_argument("--json", action="store_true", help="emit JSON rows")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "history":
            if args.limit <= 0:
                raise ConfigError("--limit must be positive")
            rows = history.recent_observations(args.path, args.limit)
            sys.stdout.write(render_history(rows, args.json))
            return EXIT_OK
        checks = load_config(args.config)
        if args.command == "validate":
            print(f"valid: {len(checks)} checks")
            return EXIT_OK
        if args.workers is not None and args.workers <= 0:
            raise ConfigError("--workers must be positive")
        if args.repeat is not None and args.repeat <= 0:
            raise ConfigError("--repeat must be positive")
        if args.webhook is not None and args.history is None:
            raise ConfigError("--webhook requires --history so state survives restarts")
        if args.webhook is not None and not notifier.valid_webhook_url(args.webhook):
            raise ConfigError("--webhook must be an HTTP(S) URL with a host")
        if args.webhook_attempts <= 0:
            raise ConfigError("--webhook-attempts must be positive")
        if args.repeat is None:
            results = run_checks(checks, args.workers)
            transitions = []
            if args.history is not None:
                transitions = history.record_results(args.history, results)
            notification_failed = args.webhook is not None and not notifier.send_transitions(
                args.webhook, transitions, attempts=args.webhook_attempts
            )
            sys.stdout.write(render(results, args.json))
            return EXIT_OK if all(item.ok for item in results) and not notification_failed else EXIT_FAILED

        saw_failure = False
        try:
            while True:
                results = run_checks(checks, args.workers)
                saw_failure = saw_failure or not all(item.ok for item in results)
                transitions = []
                if args.history is not None:
                    transitions = history.record_results(args.history, results)
                if args.webhook is not None and not notifier.send_transitions(
                    args.webhook, transitions, attempts=args.webhook_attempts
                ):
                    saw_failure = True
                    print("moni: webhook delivery failed", file=sys.stderr)
                sys.stdout.write(render(results, args.json))
                sys.stdout.flush()
                time.sleep(args.repeat)
        except KeyboardInterrupt:
            print("moni: stopped", file=sys.stderr)
            return EXIT_FAILED if saw_failure else EXIT_OK
    except (ConfigError, RuntimeError) as exc:
        print(f"moni: {exc}", file=sys.stderr)
        return EXIT_USAGE


if __name__ == "__main__":
    raise SystemExit(main())
