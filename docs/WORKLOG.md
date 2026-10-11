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
