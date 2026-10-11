# Moni

Moni is a dependency-free service monitor for HTTP(S) endpoints and TCP
services.

## Quick start

```sh
python3 moni.py validate examples/moni.json
python3 moni.py check examples/moni.json
python3 moni.py check examples/moni.json --json
```

Exit codes:

- `0`: every check passed.
- `1`: at least one check failed.
- `2`: invalid arguments or configuration.

See [DEVELOPMENT_PLAN.md](DEVELOPMENT_PLAN.md) for scope and delivery gates.

