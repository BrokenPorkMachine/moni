# Compatibility and upgrade policy

Moni follows semantic versioning for its CLI, configuration, SQLite history,
and read-only HTTP API.

- Patch releases fix defects without changing documented behavior.
- Minor releases may add commands, options, fields, and endpoints. Existing
  options and response fields remain valid.
- Major releases may remove or change behavior and include a migration note.

Configuration documents without a `version` field are treated as version 1.
Use `moni migrate PATH --output PATH` to make that version explicit. Moni
does not modify a source configuration during migration.

SQLite history is append-oriented. New tables and columns may be added by a
minor release; operators should retain a backup before upgrading. The
`moni history` command is the supported inspection interface.

Upgrade procedure:

1. Run `make smoke` and `make release-check` from the new checkout.
2. Back up configuration and any opted-in SQLite history.
3. Run the migration command when the release notes require it.
4. Install the new wheel and run `moni validate CONFIG`.
5. Resume the service or scheduled checks and inspect `moni history` output.

For a release, run `make release-attest GPG_KEY=KEY_ID`. It builds twice with
`SOURCE_DATE_EPOCH=0`, compares the wheel hashes, writes `SHA256SUMS`, and
creates an armored detached GPG signature when a key ID is supplied. Publish
the wheel, manifest, and signature together.
