# Security and data handling

Moni is local-first. It does not send monitoring data to a Moni-operated
service. Network traffic is limited to configured HTTP/TCP checks and opted-in
webhook or agent-report destinations.

Threat boundaries:

- Configuration, environment variables, SQLite history, and webhook secrets
  are operator-controlled sensitive data.
- HTTP checks can expose endpoint metadata to the configured service; Moni
  reads at most one response byte after receiving the status.
- Webhooks receive state-transition names and timestamps, not response bodies.
- Agent reports require HMAC-SHA256 signatures, freshness, known agent names,
  report IDs, and per-agent nonces. Non-loopback service binds require a
  bearer token.

Operators should keep history files and secret environment variables private,
use HTTPS for remote webhooks and agents, bind loopback unless remote access
is required, and rotate shared secrets after suspected compromise. Moni does
not provide TLS termination, secret storage, or authorization beyond the
documented bearer-token and shared-secret checks.
