# Moni

Moni is a dependency-free service monitor for HTTP(S) endpoints and TCP
services.

## Quick start

```sh
python3 moni.py validate examples/moni.json
python3 moni.py check examples/moni.json
python3 moni.py check examples/moni.json --json
python3 moni.py check examples/moni.json --repeat 30
```

Exit codes:

- `0`: every check passed.
- `1`: at least one check failed.
- `2`: invalid arguments or configuration.

Use `--repeat SECONDS` to run continuously until Ctrl-C. A repeated run keeps
checking after failures and returns `1` when interrupted if any cycle failed.

See [DEVELOPMENT_PLAN.md](DEVELOPMENT_PLAN.md) for scope and delivery gates.

