# Documentation New Feature Coverage Audit

Date: 2026-05-16 18:56 Asia/Taipei

## Scope

Rechecked deployer, admin, user, developer, API, QA, troubleshooting, and domain README docs for the recent feature set:

- personal profiles, friend codes, friend-gated targeting, and chat anonymity
- Cloud Drive capacity split, resumable upload, BT/direct-link task center, share preview/edit, and album UX
- video publish/search/share handoff, HLS readiness behavior, and E2EE streaming boundaries
- ComfyUI external-process hardening, small-VRAM guidance, and in-process Diffusers risk
- system resource board
- trading background run-once enqueue, snapshot-backed root reports, fee/interest settlement rules, grid/workflow bot reserves
- PointsChain in-circulation reporting
- Stockfish depth UI and Exp6 documentation
- `test_for_develop.sh` `/tmp` copy boundary

## Updated Docs

- `docs/03_ADMIN_GUIDE.md`
- `docs/04_USER_GUIDE.md`
- `docs/05_FEATURES_OVERVIEW.md`
- `docs/07_POINTSCHAIN.md`
- `docs/08_TRADING_ENGINE.md`
- `docs/11_QA_TESTING.md`
- `docs/12_TROUBLESHOOTING.md`
- `docs/01_DEPLOY_QUICKSTART.md`
- `docs/API_REFERENCE.md`
- `docs/For_developer.md`
- `docs/README.zh-TW.md`
- `docs/WEB.md`
- `docs/social/USER_PROFILES_AND_FRIENDS.md`
- `docs/comfyui/README.md`
- `docs/games/README.md`
- `docs/trading/TRADING.md`
- `docs/video/README.md`

## Important Status Clarifications

- PM / private group friend-gating is documented as landed.
- Game invite friend-gating and direct strict-E2EE file-key share friend-gating are documented as remaining gaps.
- Root / manager PM to non-friends is documented as a management exception, not a general targeting bypass.
- HLS, E2EE streaming, BT/direct-link downloads, ComfyUI generation, and trading run-once are documented as background/external-worker style work, not main-request synchronous work.
- Trading root reports, pools, and all-user positions are documented as snapshot reads; missing snapshots should return 503 instead of forcing live full-site recomputation.
- The old fee wording was replaced: fee/interest accrual preserves decimal carry and only rounds up to integer POINT at settlement boundaries.
- User-facing docs avoid describing the root derivative simulation path as a legal/financial agreement; the legacy `/contracts` route name is only mentioned for API compatibility.

## Remaining Follow-Up Gaps

- Public profile entry points from every username/avatar surface still need full UI wiring.
- Game invite endpoints still need backend friend-target enforcement.
- Direct strict-E2EE file-key sharing still needs backend friend-target enforcement.
- `server_encrypted` large-file encryption/decryption remains capped/guarded; full background encryption pipeline is not documented as complete.

## Verification

- Searched current formal docs for stale phrases such as `下一階段`, `future HLS`, `四捨五入`, `manually scanned`, `契約`, and `合約`.
- Cross-checked implemented route names for share editing, target options, remote-download controls, resumable upload, chat anonymity fields, and trading run-once enqueue before updating API docs.
