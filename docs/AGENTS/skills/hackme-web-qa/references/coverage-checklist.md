# hackme_web QA Coverage Checklist

Use this as a report checklist, not as a substitute for exploration.

## Fix Verification

- Re-run or manually reproduce every previously reported issue.
- Confirm expected status codes and user-visible messages, not only pytest pass/fail.
- Separate script false positives from product bugs.

## Frontend and Browser

- Navigate desktop and mobile widths.
- Check console errors, failed network requests, invisible failures, disabled buttons, stale loading states, and tiny touch targets.
- Try invalid inputs, double submits, expired/missing CSRF, wrong passwords, empty forms, huge values, unsupported modes, and permission boundaries.

## Storage, Media, and Sharing

- Upload and preview txt, md, json, html, pdf, png/jpg, zip, video.
- Test E2EE valid metadata and malformed metadata.
- Test direct URL, magnet, and `.torrent`; private/localhost endpoints must be blocked consistently.
- Test file share links, album password shares, video password unlock, HLS/playback, max-view/password failure cases.

## Economy and Trading

- Verify wallet, ledger, catalog, admin adjustment, reserve allocation.
- Compare fee and grid preview numbers with independent Decimal math.
- Run backtest tests or scripts when trading logic changed.
- Check margin/lending collateral, idempotency, liquidation/risk errors, and reserve pool verification.

## Community and Governance

- Test admin/root/manager/user permission differences.
- Test forum, chat/private messages, notifications, moderation/reporting, account blocking/review flows.

## Report Artifacts

- Store markdown under `docs/AGENTS/reports`.
- Link JSON/screenshots/runtime paths in the report.
- Stop QA servers and record anything left running only if stopping failed.
