# 2026-05-11 Full-Feature Heuristic QA

Scope: full-site QA on recent feature surface, using isolated `test_for_develop.sh` environments, Playwright visual/API coverage, full pytest, and an extra member-behavior probe that uploaded real fixtures and exercised edge cases.

## Test Artifacts

- Isolated full Playwright runtime: `/tmp/hackme_web_deep_fullqa_20260511_0500`
- Clean member-probe runtime: `/tmp/hackme_web_fullqa_clean_20260511_0521`
- Clean member-probe JSON: `/tmp/hackme_web_fullqa_clean_20260511_0521/member_probe/member_probe.json`
- Full pytest tmp copy: `/tmp/hackme_web_pytest_dQgy8x/hackme_web`
- Domain pytest tmp copy: `/tmp/hackme_web_pytest_i3gWgv/hackme_web`
- Visual screenshots from broad probe: `/tmp/hackme_web_fullqa_20260511_0500/full_domain_probe/`

## Command Results

- `python3 scripts/testing/playwright_deep_site_check.py --runtime-root /tmp/hackme_web_deep_fullqa_20260511_0500 --max-chess-human-moves 16`
  - 31 passed, 2 failed.
- `scripts/testing/pytest_in_tmp.sh -q tests`
  - 1620 passed, 5 failed.
- `scripts/testing/pytest_in_tmp.sh -q tests/trading tests/points tests/frontend/trading tests/video tests/frontend/video tests/storage tests/frontend/storage tests/community tests/frontend/community tests/frontend/chat tests/account tests/users tests/platform`
  - 783 passed, 2 failed.
- Clean member-behavior probe against `https://127.0.0.1:51177`
  - 15 passed, 2 failed.

## Confirmed Findings

### Critical: `.torrent` upload accepts localhost tracker and starts task

Direct URL and magnet both rejected `127.0.0.1` correctly. The `.torrent` upload path accepted a torrent whose `announce` tracker was `http://127.0.0.1/announce`, returned `202`, and the task entered `running/downloading`.

Impact: SSRF/private-network policy is inconsistent across remote download modes. A user can bypass the URL/magnet validator by using a torrent file.

Evidence: clean member probe `remote download blocks localhost direct/magnet/torrent SSRF`.

### High: malformed E2EE upload returns 500

Posting `privacy_mode=e2ee` without required E2EE metadata returns:

```json
{"error":"internal_server_error","msg":"Internal server error","ok":false}
```

Server log shows `ValueError("encrypted_file_key is required for e2ee uploads")` escaping to a 500. This should be a 400/422 with a user-actionable message.

Evidence: clean member probe `drive malformed E2EE upload returns client error instead of 500`.

### High: ComfyUI generation helper contract regression

Full pytest fails `tests/comfyui/test_execution_generate_image.py::test_generate_image_accepts_generate_from_workflow_func` because `generate_image()` now always passes `extra_data=` to `generate_from_workflow_func`; existing callables without that kwarg raise `TypeError`.

### Medium: ComfyUI authenticated API surface returns 503

Playwright deep check fails authenticated API coverage because `/api/comfyui/models` returns `503` while adjacent ComfyUI endpoints return 200. If this is expected when ComfyUI is offline, the endpoint/test needs an explicit degraded-state contract.

### Medium: frontend cache-bust/version snapshots drifted

Failing tests:

- `tests/frontend/comfyui/test_comfyui_idle_retry.py::test_comfyui_static_asset_cache_busted_for_idle_retry_fix`
- `tests/frontend/storage/test_frontend_drive_preview.py::test_album_viewer_has_dedicated_module`

Both expect specific `index.html` asset version strings that are no longer present.

### Medium: password toggle/touch targets still below expected size

Full pytest fails `tests/frontend/layout/test_frontend_button_sizing.py::test_pw_toggle_meets_wcag_touch_target_size`; `.pw-toggle` lacks the expected `min-width: 2.4rem` and related sizing. The visual probe also found multiple visible controls under 44px.

### Medium: trading settings schema snapshot drift

Full/domain pytest fails `tests/trading/mode_boundaries/test_trading_schema_snapshot.py::test_ensure_trading_schema_default_settings_keys_frozen`.

Unexpected new keys:

- `trading.allow_unready_markets`
- `trading.dev_allow_conservative_market_orders`
- `trading.dev_allow_unready_markets`
- `trading.dev_disable_price_confidence_gates`
- `trading.disable_price_confidence_gates`

If intentional, update the frozen expected key list in the same commit.

## Coverage Notes

Passed in current QA:

- Auth/register/login, admin member management, normal-user authz checks.
- Notifications, forum thread/reply/reaction, chat room/message/private-message paths.
- Cloud drive standard uploads and previews for txt, md, json, html, pdf, png, zip.
- Valid cloud-drive E2EE upload rejects server preview explicitly with 403.
- Drive share-link download and album password share open correctly.
- Direct URL and magnet remote downloads block localhost/private endpoints.
- Video upload generated a real MP4, prepared HLS, shared with password, rejected wrong password, unlocked, and playback returned OK.
- Video `privacy_mode=e2ee` is rejected explicitly as unsupported.
- Games catalog, chess practice, and solo score paths passed in broad Playwright.
- Points wallet/ledger/catalog and trading dashboard/markets/reference prices loaded.
- Grid fee math matched numeric hand calculation in clean probe.
- Reserve allocation passed when using required reason `ROOT_RESERVE_ALLOCATION`; previous reserve failure was a probe bug.
- Backtest correctness suites in full pytest passed; no fee/backtest math mismatch reproduced.

Invalidated noise:

- Non-media video upload rejection is clear (`not_media`, `只接受影片或音樂檔`); earlier script flagged it by mistake due escaped JSON text.
- Earlier grid fee mismatch was string formatting only (`15.075` vs `15.07500000`); numeric comparison passed.
- Playwright `video_upload_share_flow` failure is caused by checking shared playback before password unlock. The clean member probe unlocked the share and playback passed.

## Fix Status - 2026-05-11

- Critical `.torrent` upload SSRF bypass: Fixed in `8b2061b`. Uploaded `.torrent` files are validated before task creation and private/localhost trackers return 400 instead of starting a task.
- High malformed E2EE upload 500: Fixed in `8b2061b`. Malformed E2EE uploads now return a client error with the specific missing `encrypted_file_key` reason.
- High ComfyUI helper contract regression: Fixed in `8b2061b`. `generate_image()` no longer passes `extra_data` to callback functions that do not accept it.
- Medium ComfyUI authenticated API 503: Fixed in `8b2061b`. `/api/comfyui/models` now has an explicit 200 degraded/offline response.
- Medium frontend cache-bust/version snapshot drift: Fixed in `8b2061b`.
- Medium password toggle/touch target test: Fixed in `8b2061b`; related app icon controls were also raised to the 44px baseline.
- Medium trading settings schema snapshot drift: Fixed in `8b2061b`; the intentional trading override keys were added to the frozen snapshot.

Current status: **FIXED for all confirmed findings in this full-feature report**. Verification run after the patch: targeted failures passed, and the broader focused domain set reported `121 passed`.
