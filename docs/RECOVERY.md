# Recovery guidance

Moni's source configuration is the authoritative definition of checks. Keep
it in version control without secrets; provide secrets through the environment
at runtime.

For a damaged or lost history database:

1. Stop the process that writes the database.
2. Restore the latest SQLite file backup, or start with a new path.
3. Run a one-shot check with `--history PATH` to recreate the schema.
4. Verify with `moni history PATH --summary --json`.

Loss of history resets persisted check state. The next result establishes an
initial state and does not emit a state-change webhook; verify the service
manually before treating the recovered monitor as authoritative.

For a failed webhook destination, Moni retains failed state-change events in
the opted-in history database and retries them on a later process or cycle.
Check `moni history PATH --json` and the destination logs before deleting the
history file.
