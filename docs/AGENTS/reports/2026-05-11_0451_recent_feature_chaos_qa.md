# Recent Feature Chaos QA - 2026-05-11 04:51 CST

## Scope

- Focus: recent commits on ComfyUI visual workflow editor/dependency validation, video/HLS share flow, and current dirty chess live-learning validation changes.
- Isolated dev server: `https://127.0.0.1:51175`
- Dev runtime: `/tmp/hackme_web_qa_recent_20260511_044000/hackme_web`
- Deep Playwright runtime: `/tmp/hackme_web_deep_recent_20260511_044100`
- Heuristic evidence:
  - `/tmp/hackme_web_qa_recent_20260511_044000/chaos2/chaos_report.json`
  - `/tmp/hackme_web_qa_recent_20260511_044000/chaos3/supplemental_report.json`

## Commands

```bash
./test_for_develop.sh --port 51175 --run-root /tmp/hackme_web_qa_recent_20260511_044000
python3 scripts/testing/playwright_deep_site_check.py --runtime-root /tmp/hackme_web_deep_recent_20260511_044100 --max-chess-human-moves 12
python3 scripts/testing/playwright_comfyui_workflow_builder_check.py
scripts/testing/pytest_in_tmp.sh -q tests/comfyui tests/frontend/comfyui tests/scripts/games/test_chess_live_learning_validation_script.py tests/games/test_chess_self_play_training.py
```

Additional chaos probes randomly switched modules, spammed recent feature entry points, imported malformed workflow JSON, imported unknown custom-node workflow graphs, uploaded wrong file types, submitted invalid trading values, attempted path traversal style drive upload paths, and probed normal-user direct API access.

## Verdict

Overall verdict: **FAIL - needs triage before treating recent feature work as stable**.

The ComfyUI standalone visual editor itself held up well: malformed JSON showed an error, unknown custom nodes appeared in the dependency validation panel, ghost layout IDs were cleaned from export, node spam did not crash the editor, and mobile width stayed within viewport.

The broader app still exposed regressions and UX failure modes under heuristic use.

## Findings

### QA-20260511-CHAOS-001 - High - Invalid trading order returns API 400 but no clear user-facing rejection

Chaos action: set `#trading-quantity` to `-1` and submit.

Observed:

- Browser recorded `POST /api/trading/orders -> 400`.
- The visible page status did not show a clear rejection reason. The captured status text only showed the generic trading feature description.

Risk: user sees nothing actionable after a rejected order; this is a silent failure from the UI perspective.

Evidence: `/tmp/hackme_web_qa_recent_20260511_044000/chaos2/chaos_report.json`

### QA-20260511-CHAOS-002 - High - Deep Playwright video upload/share flow fails shared HLS validation

`playwright_deep_site_check.py` failed:

```text
video_upload_share_flow: ui_progress=True, progress=100%, list=200, hls=True, shared_hls=False
```

The JSON detail shows direct HLS became ready, but shared playback returned `password_required`, so the shared HLS assertion failed.

Risk: either the test is missing the expected password flow, or password-protected shared HLS playback is not wired as expected. This needs product/test triage because it is a recent media/share surface.

Evidence:

- `/tmp/hackme_web_deep_recent_20260511_044100/reports/qa/playwright_deep_site_check_20260510T203851Z.md`
- `/tmp/hackme_web_deep_recent_20260511_044100/reports/qa/playwright_deep_site_check_20260510T203851Z.json`

### QA-20260511-CHAOS-003 - Medium - ComfyUI workflow import controls expose a hidden 0x0 JSON field

On the ComfyUI main page, the workflow import/edit controls were visible, but `#comfyui-workflow-json` measured as `width=0`, `height=0`, not visible/editable. The layout JSON textarea was visible.

Risk: users can reach import/save controls while the primary workflow JSON input is effectively inaccessible. This also broke an initial Playwright fill attempt, which mirrors a user-facing state mismatch.

Evidence: `/tmp/hackme_web_qa_recent_20260511_044000/chaos2/chaos_report.json`

### QA-20260511-CHAOS-004 - Medium - Upload mode overlay intercepts drive/video follow-up actions

Chaos actions:

- Select a `.txt` through the video upload input, then try to publish.
- Select a file in Drive with path `../../outside/../chaos.txt`, then try to upload.

Observed:

- Video publish click became unstable/not visible after file selection.
- Drive upload click was intercepted by `#drive-upload-mode-overlay`.
- The overlay may be intended, but the interaction is easy to trap: the original action remains visible underneath while the overlay steals pointer events.

Risk: users can think the primary upload/publish button is broken after selecting a file.

Evidence: `/tmp/hackme_web_qa_recent_20260511_044000/chaos2/chaos_report.json`

### QA-20260511-CHAOS-005 - Medium - Authenticated API surface check fails on offline ComfyUI models endpoint

`playwright_deep_site_check.py` failed:

```text
authenticated_api_surface: /api/comfyui/models -> 503
```

This may be expected when ComfyUI is offline, but the check marks it as a site-level failure and the browser logs it as a console/resource error.

Risk: expected offline dependency state looks like a regression and can hide real API failures.

Suggested triage: either make `/api/comfyui/models` return a 200 degraded/offline payload for authenticated UI polling, or mark this endpoint as an expected optional dependency failure in the deep checker.

Evidence: `/tmp/hackme_web_deep_recent_20260511_044100/reports/qa/playwright_deep_site_check_20260510T203851Z.md`

### QA-20260511-CHAOS-006 - Medium - Targeted pytest regressions in ComfyUI tests

Targeted recent-feature pytest run result:

```text
2 failed, 375 passed
```

Failures:

- `tests/comfyui/generation/test_comfyui_generation.py::test_comfyui_generate_async_job_captures_request_meta_before_thread_handoff`
  - Expected `COMFYUI_GENERATE` audit row to preserve `X-Forwarded-For` and `User-Agent`; assertion failed.
- `tests/frontend/comfyui/test_comfyui_idle_retry.py::test_comfyui_static_asset_cache_busted_for_idle_retry_fix`
  - Expected `/js/36-comfyui.js?v=20260509-comfyui-stop-local-runtime` in `public/index.html`; current HTML does not contain that cache-bust string.

Evidence: pytest temp copy kept at `/tmp/hackme_web_pytest_IlP8ja/hackme_web`

## Confirmed Good Under Chaos

- ComfyUI visual editor malformed JSON import shows: `匯入失敗：Unexpected end of JSON input`.
- Unknown custom node import surfaces `CustomMagicNode` in the validation panel.
- Ghost layout ID `ghost-node` was not preserved in exported workflow layout.
- Visual editor node spam reached 26 nodes without crashing.
- Visual editor mobile width stayed `390/390/390`, no horizontal page overflow.
- Normal user direct admin API probes returned `403` for `/api/admin/users` and `/api/admin/health`.

## Notes

- The current working tree already contained unrelated dirty changes in chess validation files plus untracked `runtime`/`storage`.
- Temporary QA screenshots are under:
  - `/tmp/hackme_web_qa_recent_20260511_044000/chaos2/`
  - `/tmp/hackme_web_qa_recent_20260511_044000/chaos3/`

## Fix Status - 2026-05-11

- `QA-20260511-CHAOS-001`: Fixed in `8b2061b`. Trading quantity `<= 0` is blocked in the frontend with a visible message before the order request is sent.
- `QA-20260511-CHAOS-002`: No code fix needed from this report. The later full-feature probe confirmed the failure was caused by checking shared playback before password unlock; unlocked shared HLS playback passed.
- `QA-20260511-CHAOS-003`: Fixed in the follow-up fine-detail patch. The advanced JSON/debug details block is now open by default, so the workflow JSON textarea is measurable and directly editable when the user chooses the advanced path.
- `QA-20260511-CHAOS-004`: Fixed in the follow-up fine-detail patch. The upload mode dialog is now an explicit modal dialog with higher stacking priority, clearer blocking text, keyboard focus, and Esc/backdrop cancel behavior.
- `QA-20260511-CHAOS-005`: Fixed in `8b2061b`. `/api/comfyui/models` now returns a 200 degraded/offline payload instead of 503 when ComfyUI is unavailable.
- `QA-20260511-CHAOS-006`: Fixed in `8b2061b`. ComfyUI async audit ordering and ComfyUI frontend cache-bust snapshot were updated.

Current status: **FIXED for all confirmed findings in this report**.
