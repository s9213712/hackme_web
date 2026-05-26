# PointsChain Deployment Checklist

Before promoting RC1:

1. `python3 scripts/qa/points_chain_release_gate.py`
2. live isolated Playwright governance probe passes.
3. pentest/session security report has no unresolved P0/P1.
4. stress/destructive PointsChain report has no negative balance, duplicate credit, or replay mismatch.
5. production profile guard rejects default credentials and dev overrides.
6. snapshot-boundary drill verifies ordinary runtime restore boundaries and confirms PointsChain ledger backup/restore remains disabled.
7. root/admin legacy direct wallet APIs still return disabled/410.
8. latest `docs/AGENTS/reports/*pointschain*` report has no open blocker.

Production-only rules:

- no default credential startup.
- no direct product ledger writes.
- no untimelocked mint.
- no unprotected treasury movement.
- no exchange fund movement outside policy.
- no silent failure in wallet, governance, trading, or service fee payment flows.
