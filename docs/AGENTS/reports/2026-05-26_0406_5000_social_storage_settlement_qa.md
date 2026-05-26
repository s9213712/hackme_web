# 2026-05-26 04:06 Live :5000 Social / Storage / Settlement QA

Scope: continued live QA on `https://127.0.0.1:5000` while preserving the new PointsChain architecture baseline: PC1 Canonical Settlement Layer, PC0 Operational Wrapped Layer, and Bridge Cross-Ledger Settlement Layer.

## Findings

### P2 Fixed: community lock API accepted the wrong field silently

The lock endpoint only read `locked`. A caller sending `is_locked: true` received a success response, but the route interpreted the missing `locked` field as false and effectively left the thread unlocked. That made manual/API QA look like the thread was locked while a normal member could still reply.

Fix:

- `routes/community.py` now accepts both `locked` and `is_locked`.
- Missing lock state now returns 400 instead of silently unlocking.
- String booleans such as `"false"` are parsed correctly.
- The response returns both `locked` and `is_locked`.
- Regression coverage was added to `tests/community/test_community_permissions.py`.

## Verified

- Live server stayed responsive; no new traceback or 500 appeared during this pass.
- Chat duplicate attachment submission stores only one `cloud_file_refs` row for the message and returns one attachment in the API payload.
- Invalid sticker submission is rejected with 400 and does not crash the chat API.
- HTML-like chat content is sanitized before storage/display.
- Private message notification is generated for the recipient.
- Reported private messages become mutation-locked; owner edit/delete attempts return 409 until review.
- Community thread creation, reply, reaction, and moderator lock flow work on live `:5000`.
- After the live patch, a normal member reply to a confirmed locked thread is rejected with `此主題已鎖定，暫停留言`.
- New registration creates an official PC0 wallet, a PC1 deposit address, and credits the signup bonus to the PC0 wallet.
- `test` account member probe storage failures were caused by live daily upload quota exhaustion, not by preview logic.
- A fresh QA account promoted from `newbie` to `normal` uploaded `qa.png`; `/api/cloud-drive/files/<id>/preview` returned an image preview payload.
- Root financial invariant endpoint returned `status: pass`, `flow_gap_points: 0`, and `pc0_operational_ledgers_not_sealed_into_pc1_blocks: pass`.

## Architecture Baseline

The current docs and frontend already reflect the latest formal direction:

- `docs/architecture/POINTSCHAIN_FINANCIAL_SETTLEMENT_NETWORK.md`
  defines PointsChain as a Permissioned Financial Settlement Network.
- The required layers are documented as PC1 Canonical Settlement Layer, PC0 Operational Wrapped Layer, and Bridge Cross-Ledger Settlement Layer.
- The release gate language requires explorer federation, pending settlement isolation, hash-chain auditability, reserve transparency, and forbidden mixing checks.
- `public/js/55-economy.js` now labels the supply dashboard as a multi-ledger settlement control plane instead of a single closed-loop chain formula.

## Commands

- `python3 /home/s92137/.codex/skills/hackme-web-qa/scripts/member_probe.py --base-url https://127.0.0.1:5000 --root-password root --test-password test --out /tmp/hackme_web_live_member_probe_20260526_0401/member_probe.json`
  - Exit 1 due to quota-limited uploads on the long-lived `test` account.
- Manual API checks with `root`, `admin`, `test`, and `qa_upload_0402`.
- `pytest tests/points/test_financial_settlement_architecture_docs.py tests/frontend/trading/test_frontend_economy.py tests/community/test_chat_permissions.py tests/community/test_community_permissions.py -q`
  - Passed.
- `python3 -m py_compile routes/community.py && pytest tests/community/test_community_permissions.py tests/points/test_financial_settlement_architecture_docs.py tests/frontend/trading/test_frontend_economy.py -q`
  - Passed.

## Notes

The live member probe should be run against a fresh isolated environment when used as a release gate. On this long-running `:5000` instance, repeated QA has already consumed `test` account upload limits, so quota-related probe failures need reproduction with a fresh account before being treated as product regressions.
