# Moni long-term development plan

This roadmap extends the completed v0.1 local monitor into a dependable,
privacy-conscious monitoring product. Each release must preserve the v0.1
properties: standard-library runtime, explicit opt-in persistence, bounded
network work, deterministic tests, and clear exit codes.

## Product direction

Moni should become a small monitoring system that is useful at three scales:

1. A developer running checks from a laptop.
2. A small team sharing history and notifications.
3. An organization operating multiple agents with controlled access.

The product should remain inspectable and self-hostable. No feature should
require sending endpoint data or credentials to a Moni-operated cloud service.

## Release roadmap

### v0.2 — Operator ergonomics

Goals:

- Inspect recent SQLite observations from the CLI.
- Support environment-variable references in configuration without logging
  secret values.
- Add check groups, tags, and per-group execution.
- Add structured logging and stable output schemas.
- Improve configuration diagnostics with paths and actionable corrections.

Exit gate: an operator can run, inspect, and filter a local monitor without
opening the database manually; all new behavior has offline tests.

### v0.3 — Local service mode

Goals:

- Provide a foreground HTTP API for health, current state, and recent history.
- Add a minimal read-only dashboard served locally.
- Add graceful reload of configuration.
- Add retention limits for SQLite history.
- Add API authentication for non-loopback binds.

Exit gate: Moni can run as a local service with bounded storage and a
documented security model.

### v0.4 — Agent model

Goals:

- Separate scheduler, check executor, persistence, and notifier interfaces.
- Run checks from named agents with agent identity and capability reporting.
- Add signed or mutually authenticated result transport.
- Keep the existing CLI as a single-agent mode.

Exit gate: two local agents can report to a local coordinator without
duplicate observations or unauthenticated writes.

### v0.5 — Reliability and integrations

Goals:

- Add maintenance windows and silences.
- Add notification deduplication and delivery history.
- Add latency/error-rate summaries and export formats.
- Add configuration migration tooling.
- Add test fixtures for slow, flaky, and partially unavailable services.

Exit gate: repeated failures do not cause notification storms, and operators
can explain every alert from persisted evidence.

### v1.0 — Stable self-hosted release

Goals:

- Publish a compatibility and upgrade policy.
- Provide signed release artifacts and reproducible builds.
- Provide threat model, data-handling documentation, and recovery guidance.
- Maintain API/configuration compatibility guarantees.

Exit gate: a new user can install, configure, operate, upgrade, and recover
Moni using only the repository documentation.

## Long-term non-goals

- Collecting arbitrary user payloads from monitored services.
- Storing credentials in plaintext.
- A mandatory hosted SaaS control plane.
- Browser automation before the core agent model is stable.
- Automatic remediation without an explicit operator policy.

## Work-loop protocol

For every workload:

1. Read this roadmap and `DEVELOPMENT_PLAN.md`.
2. Select the smallest unblocked slice in the earliest incomplete release.
3. Write or update tests before broadening the implementation.
4. Run focused tests and the full `make smoke` gate.
5. Update `docs/WORKLOG.md` with evidence and blockers.
6. Commit and push the scoped change.
7. Reassess the release exit gate before starting another slice.

## Current status

- v0.1: complete and pushed.
- v0.2: complete; history inspection, environment references, groups/tags,
  filtering, structured result metadata, diagnostics, and structured logging
  are implemented. v0.3 is next.
- v0.3: complete; loopback health/current-check endpoints, bounded SQLite
  retention, SIGHUP configuration reload, and authenticated non-loopback
  access are implemented. The v0.3 exit gate is met for the documented local
  service scope.
- v0.4: complete for the local coordinator scope; named agent identity and
  capabilities, HMAC-signed freshness-checked reports, report and nonce replay
  protection, CLI wiring, and replaceable scheduler/persistence/notifier
  boundaries are implemented. Durable coordinator storage remains deferred.
- v0.5: in progress; persisted latency/success summaries and JSON export are
  implemented. Maintenance windows, notification delivery history, and
  configuration migration remain.
- v0.6–v1.0: not started.

