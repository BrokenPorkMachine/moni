# Moni development plan

## Product assumption

Moni is a small, local-first service monitor for developers and small teams.
It runs checks against HTTP(S) endpoints and TCP services, reports structured
results, and returns a useful process exit code for scripts and CI.

The first release is intentionally dependency-free: Python 3.11+ standard
library only. No hosted control plane, credentials, or third-party alert
service is required.

## v0.1 goals

- Load a JSON configuration file.
- Run HTTP and TCP checks concurrently.
- Enforce per-check timeouts.
- Report latency, status, and error details as JSON or readable text.
- Return exit code 0 when all checks pass, 1 when any check fails, and 2 for
  invalid configuration or command usage.
- Provide deterministic tests without requiring network access.

## Non-goals for v0.1

- Long-running daemon scheduling.
- Authentication flows.
- Persistent history or a web UI.
- Notifications through email, Slack, or PagerDuty.
- Synthetic browser checks.
- Automatic remediation.

## Milestones

### M0 — Foundation

Deliver a documented CLI, configuration schema, test harness, and clean
repository workflow.

Exit gate: `python3 -m unittest discover -s tests -v` passes and the CLI can
validate a sample configuration.

### M1 — Check engine

Implement HTTP and TCP checks, timeout handling, concurrent execution, stable
result objects, and exit-code semantics.

Exit gate: fixture-driven tests cover pass, fail, timeout, malformed config,
and mixed HTTP/TCP results.

### M2 — Operator workflow

Add human-readable output, `validate` and `check` commands, repeat interval,
and graceful interruption.

Exit gate: a user can install nothing beyond Python, write a config, run Moni,
and understand which service failed.

### M3 — Persistence and alerts

Add optional SQLite history, threshold-based state transitions, and pluggable
webhook notifications.

Exit gate: state changes are persisted and notifications are retried without
blocking unrelated checks.

### M4 — Release hardening

Add packaging, CI, documentation examples, security review, and compatibility
checks for supported Python versions.

Exit gate: reproducible test and release commands pass from a clean checkout.

## Work-loop rules

1. Read this plan before each workload.
2. Select the highest-priority unblocked milestone slice.
3. Implement the smallest complete vertical slice.
4. Run focused tests, then the full regression suite.
5. Update the worklog with evidence and remaining blockers.
6. Commit only scoped Moni changes and push the current branch.
7. Reassess completeness and repeat.

## Current status

- M0: complete.
- M1: complete; deterministic pass, fail, timeout, malformed-config, and
  mixed-check coverage is present.
- M2: complete; human-readable output, validation, one-shot checks, repeat
  mode, and graceful interruption are implemented.
- M3: complete; optional SQLite history, persisted state transitions, and
  bounded retrying webhook delivery are implemented and tested.
- M4: complete; package metadata, CI workflow, smoke commands, versioning,
  wheel build, and webhook URL validation are implemented and tested.

