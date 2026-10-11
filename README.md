# Moni

Moni is a dependency-free service monitor for HTTP(S) endpoints and TCP
services.

Install the package locally with `python3 -m pip install .`, or run
`python3 moni.py` directly from a checkout. The package requires Python 3.11+
and has no runtime dependencies.

## Quick start

```sh
python3 moni.py validate examples/moni.json
python3 moni.py check examples/moni.json
python3 moni.py check examples/moni.json --json
python3 moni.py check examples/moni.json --repeat 30
python3 moni.py check examples/moni.json --history .moni/history.sqlite
python3 moni.py history .moni/history.sqlite --limit 20
python3 moni.py history .moni/history.sqlite --json
python3 moni.py check examples/moni.json --history .moni/history.sqlite \
  --webhook https://monitoring.example/hooks/moni
moni --version
```

Exit codes:

- `0`: every check passed.
- `1`: at least one check failed.
- `2`: invalid arguments or configuration.

Use `--repeat SECONDS` to run continuously until Ctrl-C. A repeated run keeps
checking after failures and returns `1` when interrupted if any cycle failed.
Use `--history PATH` to append observations to a local SQLite database; history
is optional and disabled unless explicitly requested.

The database stores raw observations plus the last-known state for each named
check. The Python API returns `StateTransition` records when a check changes
between passing and failing. Use `--webhook URL` with `--history PATH` to POST
only state changes. Delivery retries up to three times with exponential
backoff; a failed delivery makes a one-shot check return `1`.

Use `moni history PATH` to inspect recent persisted observations without
opening SQLite directly; add `--json` for machine-readable output.

See [DEVELOPMENT_PLAN.md](DEVELOPMENT_PLAN.md) for scope and delivery gates.

