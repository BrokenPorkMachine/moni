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

## Long-term workload 2 — 2026-10-11

Added safe environment-variable references to JSON configuration:

- Supports `${NAME}` for required values.
- Supports `${NAME:-default}` for optional string values.
- Expands recursively through objects and arrays before validation.
- Missing-variable errors identify only the variable name and configuration
  path; substituted values are never logged.
- Numeric fields remain JSON numbers in v0.2 and reject string substitution.

Validation: `make smoke` passed and the full suite passed 24 tests with
`ResourceWarning` promoted to errors.

## Long-term workload 3 — 2026-10-11

Added grouped and tagged checks for local operator workflows:

- Added optional `group` and `tags` metadata with validation and duplicate-name
  protection for stable persisted state.
- Added repeatable `--tag` and `--group` filters to `check`.
- Included group and tags in structured JSON results while preserving the
  existing human-readable output and exit codes.
- Documented the metadata and updated the sample configuration.

Validation: `python3 -m unittest discover -s tests -v` passed 27 tests with
`ResourceWarning` promoted to errors; `make smoke` and `git diff --check` also
passed.

## Long-term workload 4 — 2026-10-11

Completed the v0.2 diagnostics and structured-logging slice:

- Added configurable warning/info/debug logging for check execution.
- Added JSON log records with timestamps, levels, and safe messages on stderr.
- Kept endpoint and environment-substituted values out of diagnostic records.
- Added formatter coverage and advanced the roadmap status to v0.2 complete.

Validation: `python3 -m unittest discover -s tests -v` passed 28 tests with
`ResourceWarning` promoted to errors; `make smoke`, `git diff --check`, and a
filtered JSON/logging smoke invocation also passed.

## Long-term workload 5 — 2026-10-11

Started v0.3 local service mode:

- Added a dependency-free foreground `serve` command with a background check
  scheduler.
- Added loopback-only `GET /health` and `GET /checks` JSON endpoints.
- Added synchronized state snapshots and explicit refusal of non-loopback
  binds until authentication exists.
- Added endpoint and host-safety tests.

Validation: `python3 -m unittest discover -s tests -v` passed 30 tests with
`ResourceWarning` promoted to errors; `make smoke` and `git diff --check` also
passed. Socket binding was not attempted because this sandbox denies local
socket operations; handler-level endpoint coverage passed.

## Long-term workload 6 — 2026-10-11

Added bounded history retention for service mode:

- Added a tested `prune_observations()` database operation that retains the
  newest rows by timestamp and id.
- Added `serve --history PATH --retention ROWS` for bounded service storage.
- Added positive retention validation and documented the operator workflow.

Validation: `python3 -m unittest discover -s tests -v` passed 31 tests with
`ResourceWarning` promoted to errors; `make smoke` and `git diff --check` also
passed.

## Long-term workload 7 — 2026-10-11

Added graceful configuration reload for service mode:

- `moni serve` now reloads configuration on `SIGHUP` without stopping the API.
- Reload validation is atomic: invalid replacements are logged and the active
  configuration remains unchanged.
- Scheduler snapshots configuration under a lock before each check cycle.
- Added valid-reload and rejected-reload tests.

Validation: `python3 -m unittest discover -s tests -v` passed 33 tests with
`ResourceWarning` promoted to errors; `make smoke` and `git diff --check` also
passed.

## Long-term workload 8 — 2026-10-11

Completed the v0.3 service security slice:

- Added bearer-token authentication for non-loopback API binds.
- Preserved unauthenticated loopback operation for local-only deployments.
- Added unauthorized-request coverage and documented the security model.
- Advanced the roadmap: v0.3 is complete and v0.4 agent architecture is next.

Validation: `python3 -m unittest discover -s tests -v` passed 34 tests with
`ResourceWarning` promoted to errors; `make smoke` and `git diff --check` also
passed.
