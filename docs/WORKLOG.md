# Moni worklog

## Initial workload — 2026-10-11

Created the development plan and implemented the first M0/M1 vertical slice:

- JSON configuration loading and validation.
- HTTP(S) status checks with timeout and expected-status handling.
- TCP connectivity checks with timeout handling.
- Concurrent execution while preserving configuration order.
- Human-readable and JSON output.
- Exit codes `0` pass, `1` failed check, and `2` configuration/usage error.
- Dependency-free Python implementation.

Validation:

```text
python3 -m unittest discover -s tests -v   6 passed
python3 moni.py validate examples/moni.json passed
python3 moni.py check examples/moni.json --json  failed checks as expected
```

The smoke check cannot pass in the restricted environment because external
network access and local socket operations are unavailable; deterministic
network behavior is covered with mocks. The next workload is M1 hardening:
CLI error-path tests, repeat mode, and a local test server in environments
that permit socket binding.

## Second workload — 2026-10-11

Implemented the repeat-mode operator workflow and hardened CLI validation:

- `check --repeat SECONDS` runs until Ctrl-C.
- Repeated checks continue after failures and report a failure exit status when
  interrupted after any failed cycle.
- Invalid worker and repeat values return usage exit code `2`.
- README documents continuous operation.

Validation: `python3 -m unittest discover -s tests -v` passed 7 tests.

## Third workload — 2026-10-11

Closed the M1/M2 deterministic acceptance gaps:

- Added timeout handling coverage.
- Added malformed-configuration coverage.
- Added failed-check exit-code coverage.
- Added graceful Ctrl-C coverage for repeat mode.
- Updated the plan status: M0, M1, and M2 are complete; M3 is next.

Validation: `python3 -m unittest discover -s tests -v` passed 11 tests and
the sample configuration validates successfully.

## Fourth workload — 2026-10-11

Started M3 with optional SQLite observation history:

- Added a versioned `observations` table and index.
- Added `--history PATH` to one-shot and repeat checks.
- Stored timestamp, check identity, pass/fail, latency, status, and error.
- Added parent-directory creation and explicit connection cleanup.
- Kept persistence disabled unless the operator opts in.

Validation: `python3 -m unittest discover -s tests -v` passed 13 tests with
`ResourceWarning` promoted to errors; the sample configuration validates.

## Fifth workload — 2026-10-11

Added persisted state transitions to the SQLite history contract:

- Added `check_state` with last-known status and change timestamp.
- `record_results()` now returns initial/current state transition records.
- Changes are detected without coupling persistence to notification delivery.
- Added regression coverage for initial state and recovery/failure changes.

Validation: `python3 -m unittest discover -s tests -v` passed 14 tests with
`ResourceWarning` promoted to errors.

## Sixth workload — 2026-10-11

Completed M3 persistence and alert delivery:

- Added optional webhook POSTs for pass/fail state changes only.
- Added bounded exponential retry with configurable attempt count.
- Required SQLite history when webhooks are enabled, preserving state across
  restarts.
- Made notification failure visible through one-shot exit code `1`.
- Confirmed check execution remains separate from notification delivery.

Validation: `python3 -m unittest discover -s tests -v` passed 18 tests with
`ResourceWarning` promoted to errors. M4 release hardening is next.

## Seventh workload — 2026-10-11

Completed M4 release hardening:

- Added `pyproject.toml` metadata and a `moni` console entry point.
- Added Makefile smoke targets and Python 3.11–3.13 CI workflow.
- Added `.gitignore`, version output, and wheel-build support.
- Restricted webhook destinations to HTTP(S) URLs with a host.

Validation:

```text
make smoke                                      passed
python3 moni.py --version                       moni 0.1.0
python3 -m pip wheel . --no-deps --no-build-isolation  passed
python3 -m unittest discover -s tests -v       20 passed
```

Moni v0.1 is complete against the development-plan scope.

## Long-term workload 1 — 2026-10-11

Started v0.2 operator ergonomics with a read-only history command:

- Added `moni history PATH` with human-readable and JSON output.
- Added newest-first ordering and positive `--limit` validation.
- Converted missing or invalid SQLite history into exit code `2` diagnostics.
- Kept the command read-only; it never changes observations or state.

Validation: `python3 -m unittest discover -s tests -v` passed 22 tests with
`ResourceWarning` promoted to errors; configuration validation passed.
