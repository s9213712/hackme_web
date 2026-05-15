# Final Code Review Freeze Check - 2026-05-14

This review was run against branch `03b.Comfyui` on 2026-05-14. It is a freeze gate review, not a merge approval. No push was performed.

## 1. Scope

Checked areas:

- Git/worktree hygiene and diff sanity
- Secret, token, webhook, local path, cache, and runtime artifact scans
- ComfyUI official workflow folders and workflow graph format
- Trading workflow templates and trading calculation coverage
- Cloud Drive, E2EE media, sharing, storage, and quota-facing tests
- Games local modules, chess AI tests, and Playwright games smoke
- Admin/root settings, frontend layout, docs release policy, scripts, and decrypt CLI
- Desktop/mobile Playwright smoke with authenticated root flows

Not fully covered:

- Live Civitai/Hugging Face/ComfyUI generation against external services; optional settings were not configured in the Playwright run.
- A dedicated browser script for every single mode/card combination across every page was not added in this pass. Existing static/frontend tests cover several ComfyUI hiding rules, and Playwright covered tab/mobile layout broadly.

## 2. Git And File Summary

`git diff --check`: passed.

Current worktree is not freeze-clean:

- Modified tracked files: 117
- Deleted tracked files: 1
- Untracked files: 444
- Diff stat: 118 files changed, 9704 insertions, 1041 deletions

Top-level dirty areas:

- `docs`: 6 modified, 430 untracked
- `public`: 18 modified, 2 untracked
- `routes`: 9 modified
- `scripts`: 25 modified, 7 untracked
- `services`: 26 modified, 1 deleted, 3 untracked
- `tests`: 32 modified, 2 untracked
- `bootstrap.schema.sql`: 1 modified

Tracked cache check:

- No tracked `__pycache__`, `.pyc`, or `.pytest_cache` files were found.

Untracked cache/runtime hygiene:

- The repo working tree contains untracked `.pytest_cache`, `__pycache__`, and `.pyc` files. These must be cleaned before a freeze baseline.
- `public/data` is absent, but trading frontend/tests still reference the old benchmark JSON path. See P1-3.

## 3. Risk Summary By Module

### P0

No confirmed P0 was found in this pass: no real plaintext secret, private key, real webhook, real API token, or direct cross-user data exposure was confirmed by the commands run here.

### P1

1. Chess EXP5 opening guard regression. **Resolved in follow-up fix.**
   - Failing test: `tests/games/test_chess_exp5_architecture.py::test_exp5_opening_guard_prefers_development_over_low_value_pawn_capture`
   - Actual move was `b5d3`; the test expects a back-rank knight/bishop development move.
   - This is gameplay/AI behavior risk before freeze.

2. Chess EXP4 guarded overlay audit regression. **Resolved in follow-up fix.**
   - Failing test: `tests/scripts/games/test_chess_exp4_guarded_overlay_unsafe_override_audit_script.py::test_exp4_guarded_overlay_audit_extracts_unsafe_rows_and_clusters`
   - Expected `unsafe_override_count == 1`, got `0`.
   - This weakens the audit script's ability to catch unsafe chess overlay behavior.

3. Trading benchmark asset contract is broken after `public/data` removal. **Resolved in follow-up fix.**
   - Failing test: `tests/trading/backtest/test_trading_backtest_capacity.py::test_canonical_workflow_template_benchmark_asset_matches_frontend_contract`
   - Missing file: `public/data/workflow_template_benchmarks.json`
   - Frontend still fetches `/data/workflow_template_benchmarks.json` in `public/js/56-trading.js`.
   - If `public/data` is intentionally deleted, frontend and tests need to move to an API endpoint or generated runtime source.

4. Playwright smoke exits non-zero due browser console/server error. **Mitigated in follow-up fix.**
   - `GET /api/games/multiplayer/invites/pending` returned one transient `503`.
   - Later calls returned `200`, but the browser console still captured a failed resource load.
   - This is relevant to the recent multiplayer invite feature and should be fixed or explicitly retried/suppressed only if truly expected.

5. ComfyUI frontend wiring test is stale or behavior changed without test update. **Resolved in follow-up fix.**
   - Failing test: `tests/comfyui/storage/test_comfyui_frontend_is_wired`
   - Test expects exact string `const show = currentUser === "root";`.
   - Current code uses root/local mode helpers such as `const isRoot = currentUser === "root";` and `canManageComfyuiLocalModels()`.
   - If behavior is correct, update the test to assert behavior/semantic gating rather than the old literal string.

6. Docs release policy gate fails.
   - Failing test: `tests/platform/test_release_policy.py::test_root_keeps_only_readme_markdown_and_docs_has_index`
   - `docs/README.md` is missing expected canonical links such as `07_POINTSCHAIN.md`.
   - Freeze docs and actual docs index are inconsistent.

7. Worktree volume is too large for freeze without triage.
   - 562 status entries are present.
   - Many untracked docs/evidence files are likely intentional research output, but they must be explicitly keep/update/archive/delete classified before committing.

### P2

1. Local absolute path residue exists in docs/reports/evidence.
   - Examples include Stockfish binary/source paths and evidence `source_path` values in chess reports/evidence.
   - These are not secrets by themselves, but they should be sanitized to relative paths or moved to archived local-only evidence before freeze.

2. Secret scans contain many expected code/test references.
   - Test fixtures include fake values such as Civitai/test tokens.
   - Docs reference CSRF/session/token concepts and example URLs.
   - No real secret was confirmed, but the volume of matches makes allowlisting useful.

3. `workflows/system` no longer exists.
   - System trading templates are currently under `workflows/trading_bot`.
   - Docs/tests/checklists should stop referring to `workflows/system` unless it is intentionally restored.

4. `docs/TRADING_WORKFLOW_CALCULATION.md` is absent.
   - The code has tests and implementation coverage for fee, slippage, drawdown, precision, min order, and intervals, but the requested canonical calculation document does not exist.

5. Playwright production readiness panel reports missing production gate evidence.
   - The launch-check page correctly reports missing clean smoke, adversarial, redteam, pytest, pentest, snapshot restore, points chain, and cloud-drive quota reports in the isolated runtime.
   - This is expected for an isolated smoke runtime, but should not be mistaken for a production-ready gate.

### P3

- Several TODO/debug/print-like scan hits are expected CLI/test output, but final freeze can still benefit from a smaller allowlist-based scanner.
- UI mode hiding is partially covered by current tests; a dedicated final UI mode matrix script would make this stronger.

## 4. Secret, Path, URL, And Cache Scan

Commands run:

- Local path scan for home paths, temp roots, localhost URLs, and loopback ports.
- Secret keyword scan for API key, secret, token, password, bearer, authorization, cookie, session, private key, RSA/OpenSSH/private-key markers.
- Webhook scan for ngrok, Discord webhook, Slack API, Telegram, bot token, and Civitai token patterns.
- Cache scan for `__pycache__`, `.pytest_cache`, and `.pyc`.

Results:

- No real plaintext token/private key/webhook was confirmed.
- ComfyUI workflow files contain no external URL, absolute path, or path traversal pattern.
- Many docs and scripts contain legitimate examples or code references to tokens/passwords.
- Chess evidence and reports contain local absolute paths. These should not be included in a freeze baseline without sanitization.
- Untracked cache files exist in the working tree and should be removed before freeze.

## 5. ComfyUI Workflow Templates

`workflows/comfyui` audit:

- Template folders found: 16
- Every folder has `manifest.json`, `workflow.json`, and `README.md`.
- Every `workflow.json` parsed as JSON.
- Every `workflow.json` was classified as API prompt graph, not UI graph.
- No workflow contained external URL, absolute local path, or `../`.
- No workflow exceeded 1 MiB.

Template folders checked:

- `ace_step_15_t2a_song`
- `bytedance_seedream_5_lite_t2i`
- `controlnet_canny`
- `family_anima_txt2img`
- `family_netayume_txt2img`
- `family_zit_txt2img`
- `flux2_image_edit`
- `grok_image_edit`
- `img2img_basic`
- `inpaint_basic`
- `outpaint_basic`
- `sd35_simple_example`
- `sdxl_simple_example`
- `txt2img_basic`
- `upscale_basic`
- `wan22_14b_i2v_subgraphed`

Status: pass.

## 6. Trading Workflow And Calculation Review

Trading templates:

- `workflows/trading_bot` contains 11 JSON templates.
- Each template has `id`, `label`, `description`, `scope`, `explanation`, and `workflow`.
- Each `id` matches its filename.
- Each template has `scope=system`.

Calculation coverage observed:

- `services/trading/backtest.py` contains explicit handling for execution slippage, fee points, drawdown, quantity precision, lot size, min order size, min order points, max order points, intervals, and UTC timestamp normalization.
- `services/trading/bots/service.py` contains DCA/grid bot interval, stop loss, take profit, shared parameter, and performance fields.
- `public/js/56-trading.js` has frontend estimates for fees, PnL, margin interest timing, liquidation estimates, and reference chart intervals.

Open risks:

- The deleted `public/data/workflow_template_benchmarks.json` static asset is no longer part of the active contract. The benchmark script writes to `workflows/trading_bot/benchmarks/`, and the frontend reads through `/api/trading/workflow-template-benchmarks`.
- `docs/TRADING_WORKFLOW_CALCULATION.md` is missing, so there is no single canonical document tying fee/slippage/PnL/drawdown/timezone/precision/min-order rules to the implementation.

## 7. Cloud Drive / Storage / Video

Passing pytest slice:

- `tests/storage`
- `tests/frontend/storage`
- `tests/video/api`
- `tests/frontend/video`
- `tests/share`

Playwright passed:

- Drive upload E2EE flow
- Standard upload flow
- Video upload/share flow
- Shared HLS playback

Important note:

- Strict E2EE behavior is documented in `docs/ops_boundaries/ENCRYPTION_RUNTIME_BOUNDARY.md`: the server must not receive the user's original E2EE password or raw file key for E2EE files.
- The server-side decrypt CLI only applies to server-encrypted files, not strict E2EE. This boundary should remain prominent.

## 8. Server-Side Decrypt Script

Checked `scripts/admin/decrypt_server_files.py`.

Status:

- Includes a privacy/legal warning in `PRIVACY_LEGAL_WARNING`.
- Prints the warning to stderr on execution.
- Includes the warning in generated manifests.
- Requires `--confirm-plaintext-output` before writing plaintext.
- Rejects output directories inside live storage or public web assets.

Status: pass.

## 9. Frontend / Playwright

Playwright command:

```sh
PYTHONPATH=. PYTHONPYCACHEPREFIX=<tmp-review-root>/pycache python3 scripts/testing/playwright_deep_site_check.py --runtime-root <tmp-review-root>/playwright_deep --max-chess-human-moves 4
```

Result:

- Script started isolated HTTPS server successfully.
- Most checks passed, including login, admin accounts, forum, drive, videos, games, economy, trading, security health, ComfyUI builder, desktop tabs, mobile tabs, and visual workflow editor.
- Exit code was non-zero because browser errors contained a `503` from `/api/games/multiplayer/invites/pending`.

Report files:

- `<tmp-review-root>/playwright_deep/reports/qa/playwright_deep_site_check_20260514T115619Z.json`
- `<tmp-review-root>/playwright_deep/reports/qa/playwright_deep_site_check_20260514T115619Z.md`

Server log scan:

- No unexpected `Traceback`, `500`, `KeyError`, `TypeError`, `ValueError`, or `sqlite3.OperationalError` was found in the Playwright runtime logs.
- One `503` was found for multiplayer pending invites.

## 10. Static And Pytest Results

Static checks:

- `git diff --check`: passed.
- `node --check` over 51 `public/js/*.js` files: passed.
- `python3 -m compileall` over `routes`, `services`, `scripts`, `tests` with pycache redirected to `/tmp`: passed.

Pytest slices:

Passed:

- `tests/storage`
- `tests/frontend/storage`
- `tests/video/api`
- `tests/frontend/video`
- `tests/share`

Failed:

- `tests/games` + `tests/frontend/games`: 1 failure
  - `test_exp5_opening_guard_prefers_development_over_low_value_pawn_capture`
- `tests/comfyui` + `tests/frontend/comfyui`: 1 failure
  - `test_comfyui_frontend_is_wired`
- Trading/core/workflow/backtest/grid/mode/pricing/frontend trading slice: 1 failure
  - `test_canonical_workflow_template_benchmark_asset_matches_frontend_contract`
- Account/frontend/points/regressions/scripts/security/server-mode/services/snapshots/system/users/video-security/video-streaming slice: 1 failure
  - `test_exp4_guarded_overlay_audit_extracts_unsafe_rows_and_clusters`
- Community/platform/admin/layout/scripts-admin slice: 1 failure
  - `test_root_keeps_only_readme_markdown_and_docs_has_index`

## 11. Keep / Update / Archive / Delete Notes

Keep:

- `workflows/comfyui/*` official template folders.
- `workflows/trading_bot/*.json` system trading bot templates.
- `scripts/admin/decrypt_server_files.py`, with its privacy warning and confirm gate.
- Existing storage/video/share tests that passed and cover recent E2EE/share behavior.

Update:

- `public/js/56-trading.js` and trading tests/docs to stop depending on deleted `public/data/workflow_template_benchmarks.json`, or restore a generated canonical replacement. **Done: moved to server API + `workflows/trading_bot/benchmarks/`.**
- `docs/README.md` canonical links to match release policy tests, or update the release policy if the docs map changed intentionally. **Done.**
- ComfyUI wiring tests to assert semantic root-only/local-model behavior instead of a stale literal string. **Done.**
- `docs/TRADING_WORKFLOW_CALCULATION.md` should be added to document fee, slippage, PnL, drawdown, interval, timezone, precision, and min-order rules.

Archive or sanitize:

- Chess evidence/reports with local absolute paths.
- Large untracked experiment/evidence outputs under `docs/games/evidence`.

Delete before freeze:

- Untracked `.pytest_cache`, `__pycache__`, and `.pyc` files.
- Any temporary scripts that are not intended to become maintained repo tooling.

## 12. Required Before Next Stage

Minimum gate to enter next stage:

- Fix all P1 test failures listed above.
- Resolve the `public/data` benchmark contract intentionally.
- Remove or sanitize local absolute paths in docs/evidence before committing.
- Clean untracked cache files.
- Decide keep/archive/delete for all 444 untracked files.
- Re-run `git diff --check`.
- Re-run JS syntax checks.
- Re-run Python compileall.
- Re-run the failed pytest slices and at least one broad Playwright smoke.
- Confirm Playwright browser errors are empty.

Current recommendation:

Do not freeze or merge this working tree yet. The structure is close enough to review meaningfully, but the current state still has clear P1 gate failures and repository hygiene issues.
