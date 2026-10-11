#!/usr/bin/env python3
"""Moni: small dependency-free HTTP/TCP service monitor."""

from __future__ import annotations

import argparse
import api
import agent
import components
import json
import logging
import os
import re
import signal
import socket
import history
import notifier
import sys
import threading
import time
from datetime import datetime, timezone
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2
VERSION = "0.1.0"
ENV_REFERENCE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(:-([^}]*))?\}")
LOGGER = logging.getLogger("moni")


class ConfigError(ValueError):
    """Raised when a Moni configuration is invalid."""


class JsonLogFormatter(logging.Formatter):
    """Render diagnostic records as one machine-readable object per line."""

    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "level": record.levelname.lower(),
                "message": record.getMessage(),
            }
        )


def configure_logging(level: str, log_format: str) -> None:
    handler = logging.StreamHandler()
    if log_format == "json":
        handler.setFormatter(JsonLogFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    LOGGER.handlers.clear()
    LOGGER.addHandler(handler)
    LOGGER.setLevel(getattr(logging, level.upper()))
    LOGGER.propagate = False


@dataclass(frozen=True)
class CheckResult:
    name: str
    type: str
    ok: bool
    latency_ms: float | None
    status: int | None = None
    error: str | None = None
    group: str = "default"
    tags: tuple[str, ...] = ()


def load_config(path: Path) -> list[dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"cannot read config {path}: {exc}") from exc
    data = expand_environment(data)
    if not isinstance(data, dict) or not isinstance(data.get("checks"), list):
        raise ConfigError("config must be an object with a checks array")
    checks = data["checks"]
    names: set[str] = set()
    for index, check in enumerate(checks):
        validate_check(check, index)
        if check["name"] in names:
            raise ConfigError(f"checks[{index}].name must be unique")
        names.add(check["name"])
    return checks


def reload_config(path: Path, current: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Load a replacement configuration, preserving the active one on error."""
    try:
        replacement = load_config(path)
    except ConfigError as exc:
        LOGGER.error("configuration reload rejected: %s", exc)
        return current
    LOGGER.info("configuration reloaded with %d checks", len(replacement))
    return replacement


def expand_environment(value: Any, path: str = "config") -> Any:
    """Expand string values using ${NAME} or ${NAME:-default} references."""
    if isinstance(value, dict):
        return {key: expand_environment(item, f"{path}.{key}") for key, item in value.items()}
    if isinstance(value, list):
        return [expand_environment(item, f"{path}[{index}]") for index, item in enumerate(value)]
    if not isinstance(value, str):
        return value

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        default = match.group(3)
        current = os.environ.get(name)
        if current is None or (current == "" and default is not None):
            if default is not None:
                return default
            raise ConfigError(f"{path}: environment variable {name} is not set")
        return current

    return ENV_REFERENCE.sub(replace, value)


def validate_check(check: Any, index: int = 0) -> None:
    if not isinstance(check, dict):
        raise ConfigError(f"checks[{index}] must be an object")
    name = check.get("name")
    kind = check.get("type")
    if not isinstance(name, str) or not name.strip():
        raise ConfigError(f"checks[{index}].name must be a non-empty string")
    if kind not in {"http", "tcp"}:
        raise ConfigError(f"checks[{index}].type must be http or tcp")
    group = check.get("group", "default")
    if not isinstance(group, str) or not group.strip():
        raise ConfigError(f"checks[{index}].group must be a non-empty string")
    tags = check.get("tags", [])
    if not isinstance(tags, list) or any(not isinstance(tag, str) or not tag.strip() for tag in tags):
        raise ConfigError(f"checks[{index}].tags must be an array of non-empty strings")
    if len(tags) != len(set(tags)):
        raise ConfigError(f"checks[{index}].tags must not contain duplicates")
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
        group=check.get("group", "default"),
        tags=tuple(check.get("tags", [])),
    )


def run_check(check: dict[str, Any]) -> CheckResult:
    return run_http(check) if check["type"] == "http" else run_tcp(check)


def run_checks(checks: list[dict[str, Any]], workers: int | None = None) -> list[CheckResult]:
    return components.ThreadedCheckExecutor(run_check).run(checks, workers)


def select_checks(
    checks: list[dict[str, Any]], group: str | None = None, tags: list[str] | None = None
) -> list[dict[str, Any]]:
    required_tags = tags or []
    return [
        check
        for check in checks
        if (group is None or check.get("group", "default") == group)
        and all(tag in check.get("tags", []) for tag in required_tags)
    ]


def merge_transitions(*groups: list[history.StateTransition]) -> list[history.StateTransition]:
    """Merge transition lists while preserving the first occurrence of an event."""
    merged: list[history.StateTransition] = []
    seen: set[tuple[str, str, float, bool]] = set()
    for group in groups:
        for transition in group:
            key = (transition.name, transition.type, transition.changed_at, transition.current_ok)
            if transition.changed and key not in seen:
                seen.add(key)
                merged.append(transition)
    return merged


def parse_agent_secrets(values: list[str]) -> dict[str, str]:
    """Resolve serve's NAME=ENV_VAR entries without putting secrets in argv."""
    secrets: dict[str, str] = {}
    for value in values:
        name, separator, environment_name = value.partition("=")
        if not separator or not name.strip() or not environment_name.strip():
            raise ConfigError("--agent-secret must use NAME=ENV_VAR")
        if name in secrets:
            raise ConfigError(f"duplicate --agent-secret for agent {name}")
        secret = os.environ.get(environment_name)
        if not secret:
            raise ConfigError(f"agent secret environment variable {environment_name} is not set")
        secrets[name] = secret
    return secrets


def maintenance_window_active(window: str | None, now: datetime | None = None) -> bool:
    """Return whether a local HH:MM-HH:MM maintenance window is active."""
    if window is None:
        return False
    start_text, separator, end_text = window.partition("-")
    if not separator:
        raise ConfigError("--maintenance-window must use HH:MM-HH:MM")
    try:
        start = datetime.strptime(start_text, "%H:%M").time()
        end = datetime.strptime(end_text, "%H:%M").time()
    except ValueError as exc:
        raise ConfigError("--maintenance-window must use HH:MM-HH:MM") from exc
    current = (datetime.now() if now is None else now).time()
    return start <= current < end if start <= end else current >= start or current < end


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


def render_summary(rows: list[dict[str, Any]], json_output: bool) -> str:
    if json_output:
        return json.dumps(rows, indent=2) + "\n"
    if not rows:
        return "No observations.\n"
    return "".join(
        f"{row['name']} [{row['type']}] {row['success_rate']:.2%} pass, "
        f"{row['average_latency_ms']:.2f} ms average ({row['observations']} observations)\n"
        for row in rows
    )


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
            sub.add_argument("--group", default=None, help="run only checks in this group")
            sub.add_argument("--tag", action="append", default=[], help="run checks containing this tag")
            sub.add_argument(
                "--silence",
                action="append",
                default=[],
                help="suppress webhook notifications for this check name",
            )
            sub.add_argument(
                "--maintenance-window",
                default=None,
                metavar="START-END",
                help="suppress webhook notifications during local HH:MM-HH:MM",
            )
            sub.add_argument("--log-level", choices=("debug", "info", "warning"), default="warning")
            sub.add_argument("--log-format", choices=("text", "json"), default="text")
    history_parser = subparsers.add_parser("history", help="inspect stored observations")
    history_parser.add_argument("path", type=Path)
    history_parser.add_argument("--limit", type=int, default=20)
    history_parser.add_argument("--json", action="store_true", help="emit JSON rows")
    history_parser.add_argument("--summary", action="store_true", help="aggregate all observations by check")
    serve_parser = subparsers.add_parser("serve", help="serve current check state over loopback HTTP")
    serve_parser.add_argument("config", type=Path)
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8765)
    serve_parser.add_argument("--interval", type=float, default=30.0, metavar="SECONDS")
    serve_parser.add_argument("--workers", type=int, default=None)
    serve_parser.add_argument("--history", type=Path, default=None, metavar="PATH")
    serve_parser.add_argument("--retention", type=int, default=None, metavar="ROWS")
    serve_parser.add_argument("--auth-token", default=None, help="Bearer token for non-loopback API access")
    serve_parser.add_argument(
        "--agent-secret",
        action="append",
        default=[],
        metavar="NAME=ENV_VAR",
        help="enable signed agent reports using a secret loaded from ENV_VAR",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "history":
            if args.limit <= 0:
                raise ConfigError("--limit must be positive")
            if args.summary:
                rows = history.summarize_observations(args.path)
                sys.stdout.write(render_summary(rows, args.json))
            else:
                rows = history.recent_observations(args.path, args.limit)
                sys.stdout.write(render_history(rows, args.json))
            return EXIT_OK
        checks = load_config(args.config)
        if args.command == "validate":
            print(f"valid: {len(checks)} checks")
            return EXIT_OK
        if args.command == "serve":
            if args.port <= 0 or args.port > 65535:
                raise ConfigError("--port must be between 1 and 65535")
            if args.interval <= 0:
                raise ConfigError("--interval must be positive")
            if args.retention is not None and args.retention <= 0:
                raise ConfigError("--retention must be positive")
            if args.workers is not None and args.workers <= 0:
                raise ConfigError("--workers must be positive")
            secrets = parse_agent_secrets(args.agent_secret)
            store = api.StateStore()
            coordinator = agent.Coordinator(secrets) if secrets else None
            server = api.create_server(args.host, args.port, store, args.auth_token, coordinator)
            stop = threading.Event()
            checks_lock = threading.Lock()
            active_checks = checks

            def reload_signal(_signum: int, _frame: Any) -> None:
                nonlocal active_checks
                with checks_lock:
                    active_checks = reload_config(args.config, active_checks)

            signal.signal(signal.SIGHUP, reload_signal)

            def refresh() -> None:
                while not stop.is_set():
                    with checks_lock:
                        scheduled_checks = list(active_checks)
                    results = run_checks(scheduled_checks, args.workers)
                    store.replace([asdict(item) for item in results])
                    if args.history is not None:
                        history.record_results(args.history, results)
                        if args.retention is not None:
                            history.prune_observations(args.history, args.retention)
                    stop.wait(args.interval)

            worker = threading.Thread(target=refresh, name="moni-scheduler", daemon=True)
            worker.start()
            LOGGER.info("serving Moni API on %s:%d", args.host, args.port)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                LOGGER.info("stopping Moni API")
            finally:
                stop.set()
                server.server_close()
            return EXIT_OK
        configure_logging(args.log_level, args.log_format)
        original_count = len(checks)
        checks = select_checks(checks, args.group, args.tag)
        LOGGER.info("selected %d of %d configured checks", len(checks), original_count)
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
            LOGGER.debug("running one-shot check cycle")
            results = run_checks(checks, args.workers)
            transitions = []
            if args.history is not None:
                transitions = history.record_results(args.history, results)
                if args.webhook is not None:
                    transitions = merge_transitions(history.pending_notifications(args.history), transitions)
            transitions = [
                transition
                for transition in transitions
                if transition.name not in args.silence and not maintenance_window_active(args.maintenance_window)
            ]
            notification_failed = args.webhook is not None and not notifier.send_transitions(
                args.webhook, transitions, attempts=args.webhook_attempts
            )
            if args.webhook is not None and args.history is not None:
                history.record_notification_delivery(args.history, transitions, not notification_failed)
            sys.stdout.write(render(results, args.json))
            return EXIT_OK if all(item.ok for item in results) and not notification_failed else EXIT_FAILED

        saw_failure = False
        try:
            while True:
                LOGGER.debug("running repeated check cycle")
                delivery_failed = False
                results = run_checks(checks, args.workers)
                saw_failure = saw_failure or not all(item.ok for item in results)
                transitions = []
                if args.history is not None:
                    transitions = history.record_results(args.history, results)
                    if args.webhook is not None:
                        transitions = merge_transitions(history.pending_notifications(args.history), transitions)
                transitions = [
                    transition
                    for transition in transitions
                    if transition.name not in args.silence
                    and not maintenance_window_active(args.maintenance_window)
                ]
                if args.webhook is not None and not notifier.send_transitions(
                    args.webhook, transitions, attempts=args.webhook_attempts
                ):
                    delivery_failed = True
                    saw_failure = True
                    print("moni: webhook delivery failed", file=sys.stderr)
                if args.webhook is not None and args.history is not None:
                    history.record_notification_delivery(args.history, transitions, not delivery_failed)
                sys.stdout.write(render(results, args.json))
                sys.stdout.flush()
                time.sleep(args.repeat)
        except KeyboardInterrupt:
            print("moni: stopped", file=sys.stderr)
            return EXIT_FAILED if saw_failure else EXIT_OK
    except (ConfigError, RuntimeError, ValueError) as exc:
        print(f"moni: {exc}", file=sys.stderr)
        return EXIT_USAGE


if __name__ == "__main__":
    raise SystemExit(main())
