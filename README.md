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

Checks may declare a `group` and string `tags`. Select a group with
`--group NAME` and require one or more tags with repeatable `--tag NAME`.
JSON output includes the group and tags for downstream tooling.
Use `--log-level info --log-format json` for structured diagnostic records on
stderr; diagnostic records never include endpoint values or substituted
environment values.

Run `moni serve examples/moni.json` to expose a loopback-only API. `GET
/health` reports aggregate status and `GET /checks` returns the latest
structured results. The service refreshes checks every 30 seconds by default;
use `--interval SECONDS` to change it. Add `--history PATH --retention ROWS`
to persist service observations while keeping only the newest bounded number
of rows.
Send `SIGHUP` to a running `moni serve` process to reload its JSON
configuration. A malformed replacement is rejected and the previous active
configuration continues running.
Non-loopback binds require `--auth-token TOKEN`; clients must send
`Authorization: Bearer TOKEN`. Keep the token out of shell history and process
list exposure where possible.

The Python API also provides an authenticated coordinator contract for future
multi-agent service mode. Agents create canonical JSON reports and sign them
with an HMAC-SHA256 shared secret; the coordinator rejects unknown agents,
forged signatures, stale reports, and duplicate report IDs. Reports are
accepted at `POST /reports` when a server is created with an `agent.Coordinator`.
The existing CLI remains single-agent mode until coordinator configuration is
added.

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

String configuration values may reference `${NAME}` or `${NAME:-default}`.
Unset required variables cause validation to fail with the variable name only;
Moni never prints the substituted value. Numeric fields remain JSON numbers and
should not be supplied through environment substitution in v0.2.

See [DEVELOPMENT_PLAN.md](DEVELOPMENT_PLAN.md) for scope and delivery gates.

