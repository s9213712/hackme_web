# Update Summary

Release ID: `2026.05.02-045`

## Highlights

- Server Mode v2 enterprise sign-off now has a live HTTP smoke test:
  `security/server_mode_v2_live_http_smoke.py`.
- The live smoke starts an isolated loopback Flask server, logs in through the
  real CSRF/session-cookie stack, probes tester-token traversal payloads, enters
  superweak, kills the server process with SIGKILL, restarts it, validates
  rollback, enters `incident_lockdown`, and verifies old sessions/tokens are
  blocked.
- Adversarial and Red Team L2 reports now mark their standalone readiness as
  `CONDITIONAL_YES`; production readiness becomes `YES` only after the live HTTP
  smoke also passes.
- Session lookups no longer write `sessions.last_seen` on every request. The
  refresh is throttled to reduce SQLite write-lock contention during high
  frontend polling or mode-test traffic.
- The server mode UI now reports the actual HTTP/error detail when mode loading
  fails instead of only showing a generic failure message.
- Documentation now distinguishes the `internal_test` login token from the
  Server Mode v2 tester API token.

## Operator Notes

- Before switching to production, keep `server_mode_v2_adversarial.py`,
  `server_mode_v2_redteam_l2.py`, and `server_mode_v2_live_http_smoke.py`
  evidence together. The first two prove model-level controls; the live smoke
  proves the Flask HTTP/session process path.
- Off-host append-only log replication / filesystem-level immutable storage is
  still a deployment-environment control and is not verified by local smoke
  tests.
- Runtime logs, generated reports, SQLite databases, pycache, and local keys are
  generated artifacts. They should remain ignored and must not be committed.
