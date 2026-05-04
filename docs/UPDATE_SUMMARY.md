# Update Summary

Release ID: `2026.05.04-074`

## 2026.05.04-074

## Highlights

- Root trading settings are now split out of the overloaded `計費` page into a
  dedicated `交易所` settings tab.
- The trading settings UI is reorganized into focused groups:
  - basic trading / borrowing / liquidation controls
  - price source and fusion diagnostics
  - bot auto-scan and audit dashboard
  - BTC_trade integration
  - per-market overrides
- Existing field ids and backend payload formats stay intact, so the change is
  a UI / IA cleanup rather than a breaking settings-schema migration.

## Validation

- `PYTHONPATH=. python3 -m pytest -q tests/test_frontend_economy.py tests/test_release_policy.py`
- `python3 scripts/pre_push_checks.py --ci`
- `git diff --check`

## 2026.05.04-073

## Highlights

- The trading page `目前價格` card now refreshes once per second through a
  lightweight `GET /api/trading/live-price` route instead of waiting for the
  heavier 5-second dashboard refresh.
- Price direction is now visualized directly in the card: up ticks turn green,
  down ticks turn red, and degraded fallback / cached sources show a yellow
  warning badge.
- The `live-price` response now returns `price_health`, `fallback_reason`,
  `excluded_sources`, and `defaulted_market`, so the frontend can explain why a
  price is degraded instead of silently treating it as healthy.
- Cached fallback prices no longer truncate fractional values via `int(...)`;
  the fallback path now preserves decimal precision so `0.12345678` does not
  become `0`, and `123.99` does not become `123`.
- `GET /api/trading/live-price` is documented as a safe-read route that still
  refreshes the cached `trading_markets.manual_price_points / price_source`
  fields in SQLite for downstream order-entry and dashboard consistency.

## Validation

- `PYTHONPATH=. python3 -m pytest -q tests/test_trading_engine.py tests/test_trading_reference_prices.py tests/test_frontend_economy.py tests/test_release_policy.py`
- `python3 scripts/pre_push_checks.py --ci`
- `git diff --check`

## 2026.05.04-072

## Highlights

- Root trading settings now expose a `BTC_trade 一鍵啟動預測` button after the
  repo path is configured. The start flow first checks whether the BTC_trade
  data file is stale and whether model artifacts are older than the latest
  data, then only reruns `update_data.py` / `retrain_models.py` when needed,
  and finally launches `hourly_check.py`.
- Long BTC_trade model training no longer gets treated as an immediate timeout
  failure. The start flow now runs as a background job, and the root panel
  polls job status until it either sees a fresh `runtime/report_log_4h.jsonl`
  or explicitly reports that the latest prediction is still within the valid
  freshness window.
- The root `檢查 BTC_trade` status text now includes a compact summary of
  data/model/prediction freshness instead of only saying whether the report is
  available.

## Validation

- `PYTHONPATH=. python3 -m pytest -q tests/test_trading_reference_prices.py -k 'btc_trade or start_status or start_returns_background_job or artifact_freshness'`
- `PYTHONPATH=. python3 -m pytest -q tests/test_frontend_economy.py -k 'btc_trade or reference_polling'`
- `python3 -m py_compile services/btc_trade_bridge.py routes/trading.py`

## 2026.05.04-071

## Highlights

- The trading page no longer lets single-source reference-price polling
  overwrite the fused/live execution reference price shown in the order card.
  Reference candles now stay in the chart lane only, while the visible
  `目前價格` and order estimate keep using the real market price returned by the
  trading dashboard.
- This closes the UI mismatch where users could see the displayed trading price
  jump between very different values even though the actual execution
  reference price had not changed the same way.

## Validation

- `PYTHONPATH=. python3 -m pytest -q tests/test_frontend_economy.py`
- `git diff --check`

## 2026.05.04-070

## Highlights

- Trading backtests no longer silently replace a user-supplied short candle set
  with live public-market history. The route now requires an explicit
  `auto_fetch_reference_candles=true` opt-in before it downloads reference
  candles, so isolated QA and hand-built scenarios stay isolated by default.
- The backtest engine now guards obviously abnormal jump candles and flat
  Bollinger ranges. Extreme outlier candles are skipped with explicit warnings
  instead of booking fake profits, and `std=0` flat sequences no longer
  trigger `below_lower` / `above_upper` Bollinger conditions.
- Root now has a dedicated trading-bot audit dashboard. Bots remain `未稽核`
  until they either produce at least one trade or stay enabled for 24 hours;
  after that the scheduler records green/yellow/red audit runs, surfaces recent
  findings, and lists trading bug reports in the same root-only panel.

## Validation

- `PYTHONPATH=. python3 -m pytest -q tests/test_trading_engine.py -k "audit or backtest or bollinger or outlier or 20000"`
- `PYTHONPATH=. python3 -m pytest -q tests/test_trading_reference_prices.py tests/test_frontend_economy.py tests/test_bug_reports.py tests/test_release_policy.py`
- `python3 scripts/pre_push_checks.py --ci`

## 2026.05.04-069

## Highlights

- Trading backtest date pickers no longer expect users to understand the
  `20,000`-candle cap. When a user picks a start or end datetime, the UI now
  immediately explains how far the other side can be extended at the current
  timeframe and clamps the input range accordingly.

## 2026.05.04-068

## Highlights

- Root trading settings now include a root-only live fusion dashboard. It can
  show the currently effective provider ratios, excluded exchanges, degraded
  states, and whether the fused price has fallen back into conservative
  single-source mode.
- Fused-price diagnostics are now explicit instead of silent. Failed exchange
  order books are exposed as excluded providers, `manual_weights` with all
  zeros is flagged as invalid and shown as an `auto_depth` fallback, and
  order-book total failure is surfaced as `價格來源降級` instead of pretending
  it is still a normal fused price.
- Price-fusion QA now covers default mode, auto-depth weighting, provider
  exclusion, manual-weight equal weighting, all-zero manual fallback, and the
  single-source ticker fallback chain.

## Validation

- `PYTHONPATH=. python3 -m pytest -q tests/test_trading_engine.py -k "price_fusion or live_price_fusion or root_trading_settings_default_to_fused_weighted_auto_depth"`
- `PYTHONPATH=. python3 -m pytest -q tests/test_trading_reference_prices.py -k "price_fusion or fused_price"`
- `PYTHONPATH=. python3 -m pytest -q tests/test_frontend_economy.py -k "root_trading or trading_exchange_is_separate_from_wallet_page"`
- `python3 scripts/pre_push_checks.py --ci`

## 2026.05.04-067

## Highlights

- Trading backtests no longer force users to manually split any range above a
  single execution batch. The backend now accepts up to `20,000` candles per
  run and internally continues long windows in contiguous `10,000`-candle
  segments, so large windows keep one result set while still staying inside a
  bounded resource cap.
- The browser no longer tries to carry segmented backtest state itself. It now
  sends one request, lets the backend preserve DCA intervals, workflow state,
  and grid state across internal batches, and clearly tells the user when a
  run was segmented automatically.
- Backtest download metadata now reports both the overall candle cap and the
  per-batch execution cap, so deployers and QA can tell whether a run was
  blocked by the total limit or simply split into multiple backend chunks.

## Validation

- `PYTHONPATH=. python3 -m pytest -q tests/test_trading_engine.py tests/test_trading_reference_prices.py`
- `python3 scripts/pre_push_checks.py --ci`

## 2026.05.04-066

## Highlights

- Margin interest now keeps fractional carry in micropoints instead of rounding
  every small accrual straight up to the next full POINT. Small-principal
  positions now accumulate residual interest until it crosses a whole point,
  which removes the old `50 @ 1% / day -> 1 point after 1 day` overcharge.
- Historical backtests now allow up to `10,000` candles end-to-end, so
  full-year `BTC/USDT 1h` windows like `2024-01-01 ~ 2024-12-31` are no longer
  blocked by the old `5000`-candle ceiling.
- The funding-pool pressure multiplier now respects an explicit root value of
  `0` instead of silently falling back to the default multiplier.

## Validation

- `PYTHONPATH=. python3 -m pytest -q tests/test_release_policy.py tests/test_smoke_suite_regressions.py tests/test_pentest_script.py tests/test_functional_permission_pentest.py tests/test_trading_engine.py tests/test_trading_reference_prices.py tests/test_frontend_economy.py`
- `python3 security/trading_exchange_validation.py --out /tmp/trading_exchange_validation_issue_followup`
- `python3 scripts/pre_push_checks.py --ci`

## 2026.05.03-065

## Highlights

- Trading now defaults to a fused live price instead of a single fixed public
  ticker source. Root can keep automatic depth-based weights or switch to
  manual per-exchange weights across Binance, OKX, Coinbase, Kraken, Gemini,
  and Bitstamp; if one API fails, the remaining healthy exchanges are
  re-normalized automatically.
- DCA bots now accept `max_runs = -1` as an unlimited schedule. The backend
  stores this as a sentinel, the frontend renders it as `不限制`, and the
  `增加次數` flow now no-ops cleanly for unlimited bots.
- The deterministic trading validation script was resynced with the current
  grid engine result (`1072` instead of the stale `1065`), and the trading QA
  report set gained a follow-up note that records the code changes and retest
  results.

## Validation

- `PYTHONPATH=. python3 -m pytest -q tests/test_trading_engine.py tests/test_trading_reference_prices.py tests/test_frontend_economy.py`
- `python3 security/trading_exchange_validation.py --out /tmp/trading_exchange_validation_followup`
- `python3 scripts/pre_push_checks.py --ci`

## 2026.05.03-064

## Highlights

- The personal appearance override reset action was moved to the main user-edit
  footer so ordinary users can find it without hunting inside the collapsed
  appearance controls.
- The reset copy now explains that it returns the account to root's global
  default appearance and still requires the final `儲存` action before writing
  to the profile.
- Appearance docs and QA guidance were updated so deployers know where the
  reset action lives and how to verify that the override is actually cleared.

## Validation

- `PYTHONPATH=. python3 -m pytest -q tests/test_frontend_personalization.py tests/test_frontend_drive_preview.py tests/test_user_profile_appearance.py`
- `python3 scripts/pre_push_checks.py --ci`

## 2026.05.03-063

## Highlights

- QA tooling defaults were aligned. `tests/smoke_suite.py` now uses the same
  smoke credentials as `run_functional_smoke.sh` and
  `functional_permission_pentest`, so the default runbook no longer breaks on
  mismatched rotated passwords.
- The Python smoke suite now snapshots and restores feature flags after it
  temporarily enables chat/community/games-related modules. This prevents the
  suite from leaving `feature_economy_enabled` or sibling flags in a mutated
  state for later checks in the same runtime.
- `security/run_pentest.sh` now gives `whole-site-production-gate` a higher
  timeout floor automatically, so the wrapper's generic `180s` limit no longer
  kills that gate before the underlying Python checker finishes.
- Trading fee calculation for integer POINT ledgers now uses `Decimal` plus
  round-half-up instead of always `ceil`-biasing small orders upward. This
  removes the strongest systematic overcharge behavior on small spot trades.

## Validation

- `PYTHONPATH=. python3 -m pytest -q tests/test_smoke_suite_regressions.py tests/test_pentest_script.py tests/test_trading_engine.py`
- `python3 scripts/pre_push_checks.py --ci`

## 2026.05.03-062

## Highlights

- Root settings and session UX were tightened after QA. The shared settings
  success banner now auto-clears instead of lingering indefinitely, and idle
  logout warnings no longer reuse the same banner area.
- Feature-gated APIs no longer stop at a generic `此功能目前已由 root 關閉`.
  The response payload now names the blocked feature, missing parent features,
  and already-enabled dependent modules that will be affected together.
- Local/remote ComfyUI, user appearance, storage/albums, and related frontend
  navigation fixes were grouped into a dedicated code split, while regression
  coverage and legacy wrapper cleanup were split into separate commits.

## Validation

- `python3 scripts/pre_push_checks.py --ci`
- `git diff --check`

## 2026.05.03-061

## Highlights

- The root settings success banner no longer lingers indefinitely. A normal
  green `設定已儲存` message now auto-clears after a short delay, while
  incomplete feature-dependency warnings stay visible as a separate warning
  state.
- The idle logout countdown warning no longer reuses the root settings status
  area, so operators do not see unrelated countdown notices overwriting or
  mixing with settings-save feedback.
- Feature-gated `503` responses are no longer generic-only. The payload now
  includes the blocked feature label plus missing parent features or currently
  enabled dependent modules that will also be affected, so root can tell what
  to open together instead of only seeing `此功能目前已由 root 關閉`.

## Validation

- `PYTHONPATH=. python3 -m pytest -q tests/test_frontend_auth_timeout.py tests/test_feature_flags.py tests/test_functional_permission_pentest.py`
- `python3 scripts/pre_push_checks.py --ci`

## 2026.05.03-060

## Highlights

- Root settings now hide token fields when the matching mode is not active.
  `Turnstile site key` only appears when registration CAPTCHA is set to
  `turnstile`, instead of staying visible in `none / math / image` mode.
- The ComfyUI settings copy now states more explicitly that remote API mode is
  generation-only. In remote mode, the root-only local model-download path and
  `Civitai API Key` stay hidden because the app cannot download models into a
  remote ComfyUI host through the normal API.
- Admin, feature-overview, troubleshooting, and QA docs were updated so a new
  deployer can tell whether a missing token field is expected mode behavior or
  an actual UI bug.

## Validation

- `PYTHONPATH=. python3 -m pytest -q tests/test_frontend_captcha.py tests/test_comfyui_integration.py`
- `python3 scripts/pre_push_checks.py --ci`

## 2026.05.03-059

## Highlights

- ComfyUI long-running tasks now suspend the frontend idle auto-logout
  countdown more consistently. This no longer applies only to generation:
  local startup polling and root's local Civitai model downloads now also keep
  the session alive while the task is still running.
- Static regression tests were expanded so future frontend changes must keep
  the `ComfyUI 產圖中` / `ComfyUI 啟動中` / `ComfyUI 模型下載中` idle-suspend hooks.

## Validation

- `PYTHONPATH=. python3 -m pytest -q tests/test_frontend_auth_timeout.py tests/test_comfyui_integration.py`
- `python3 scripts/pre_push_checks.py --ci`

## 2026.05.03-058

## Highlights

- Site appearance control is now split cleanly between global defaults and
  personal overrides. Root still owns the global theme, while logged-in users
  can save a personal theme from `修改資料 -> 個人外觀`.
- The appearance editor now exposes more than just colors: users and root can
  adjust font family, background style, panel style, sidebar width, layout,
  density, radius, font scale, and content width.
- The old `feature_personalization_enabled` switch is now effectively the
  "allow personal appearance overrides" control. It defaults to on, lives next
  to root's appearance settings, and shows a clear disabled message to users if
  root turns it off.
- Root's settings page now clears the stale `設定已儲存` banner as soon as
  another field is edited, so operators no longer keep seeing an outdated
  success state while making new unsaved changes.

## Validation

- `PYTHONPATH=. python3 -m pytest -q tests/test_frontend_personalization.py tests/test_user_profile_appearance.py tests/test_frontend_chat.py tests/test_frontend_economy.py tests/test_frontend_governance.py tests/test_frontend_drive_preview.py tests/test_mobile_responsive_layout.py tests/test_comfyui_integration.py`
- `python3 scripts/pre_push_checks.py --ci`

## 2026.05.03-057

## Highlights

- The ComfyUI page now shows the active connection mode more explicitly. The
  panel header includes a visible mode badge plus a short explanatory line, so
  users can tell at a glance whether they are in local mode or cloud/remote API
  mode.
- The mode explanation now clarifies what each mode means operationally:
  local mode allows root-controlled local start/stop and local model download,
  while cloud/remote mode is generation-only and does not expose local model
  management.
- Troubleshooting and feature-overview docs were updated so operators know to
  use the visible mode badge as the first check when ComfyUI behavior looks
  different from expectations.

## Validation

- `PYTHONPATH=. python3 -m pytest -q tests/test_comfyui_integration.py`

## 2026.05.03-056

## Highlights

- LoRA trigger words are now persisted after root downloads a LoRA through the
  local-mode Civitai panel. The server writes a small sidecar metadata file next
  to the downloaded LoRA so the trigger-word mapping survives page refreshes and
  later sessions.
- `/api/comfyui/models` now returns `lora_details` alongside the plain LoRA
  name list. The frontend uses that metadata to auto-append any missing trigger
  words into the positive prompt when a user adds a known LoRA.
- The auto-insert behavior is intentionally conservative: it only applies to
  LoRAs with known saved metadata and only appends missing terms, so repeated
  add/remove actions do not keep duplicating the same trigger words.
- Admin/operator, feature-overview, troubleshooting, and QA docs were updated
  so this behavior and its limits are documented from both deployer and root
  perspectives.

## Validation

- `PYTHONPATH=. python3 -m pytest -q tests/test_comfyui_integration.py`

## 2026.05.03-055

## Highlights

- The ComfyUI generation form now supports both `Embedding` and `VAE`
  parameters instead of only listing them conceptually. Users can click an
  embedding shortcut button to insert it into the positive prompt, and can
  switch between the checkpoint builtin VAE or an installed standalone VAE.
- The backend translates the UI's `<embeddings:name>` helper token into actual
  ComfyUI embedding prompt syntax before queueing the workflow, and custom VAE
  selection now inserts a real `VAELoader` node into the generated workflow.
- Root's local-mode Civitai download panel no longer offers outdated
  `Hypernetwork` or currently unsupported `ControlNet` downloads. The panel now
  focuses on the types this UI can actually use: checkpoint, LoRA, embedding,
  and VAE.
- Civitai inspect/download responses now surface official `trainedWords`, so
  root can see a model version's trigger words before downloading a LoRA and in
  the post-download result message.
- Documentation and QA guidance were updated so deployers and root operators
  can see the new ComfyUI limits and validation points without digging through
  source first.

## Validation

- `PYTHONPATH=. python3 -m pytest -q tests/test_comfyui_integration.py`

## 2026.05.03-054

## Highlights

- Removed the unfinished ComfyUI acceleration / credits UI that was added under
  the wrong assumption that Comfy Cloud paid credits could be surfaced and used
  through the existing page flow.
- The AI generation panel is back to the usable core: main ComfyUI connection
  mode, local start/stop controls, async progress, billing confirmation, and
  result save/share/discard behavior.
- Root's Civitai model download tools remain available, but they now live in a
  separate collapsed panel at the bottom of the AI page so generation and model
  management are clearly separated.
- The AI page now states the active mode explicitly (`local` vs `remote`) and
  hides Civitai/model-download controls when the root setting is in remote
  mode.
- Each selected LoRA now exposes separate `model` and `clip` strength controls,
  and the frontend pauses idle auto-logout while generation is running.
- Personal appearance settings are no longer root-only: authenticated users can
  keep their own appearance override while root still owns the global default
  theme.
- Server settings now keep only the active ComfyUI connection settings plus the
  Civitai API key; the temporary root acceleration URL field is removed.
- Documentation was reorganized from a deployer-first perspective: README is
  now brief, new numbered entry guides were added under `docs/`, and the older
  large guides were downgraded to deep-reference status instead of being
  deleted.
- Regression coverage was updated for the new frontend layout/scripts and the
  simplified ComfyUI settings surface.

## Validation

- `PYTHONPATH=. python3 -m pytest -q tests/test_comfyui_integration.py tests/test_frontend_chat.py tests/test_frontend_economy.py tests/test_frontend_governance.py`
- `python3 scripts/pre_push_checks.py --ci`

## 2026.05.03-051

## Highlights

- ComfyUI generation now supports asynchronous job progress. The web page polls
  `/api/comfyui/jobs/<job_id>`, shows queue/node progress, and keeps the user on
  the AI page while local-mode startup is still in progress.
- Root can inspect a Civitai model page URL, choose a version/file, and
  download checkpoints or LoRA files into the configured local ComfyUI project.
  Root can also stop the shared local ComfyUI process from the page.
- Account governance is stricter and more auditable: rejecting a pending
  registration deletes the application account, normal user deletion becomes
  soft-delete with history preservation, deleted users are hidden from default
  admin lists, and member-rights changes create governance notices plus appeal
  restore context when appropriate.
- Trading now exposes first-class grid bot routes/UI plus bot max-run
  extension. Grid bots support底倉 checks before creation, manual scans that
  place counter-orders after fills, and backtest selection alongside DCA and
  workflow bots.
- Server-encrypted Cloud Drive / Video media no longer fails with a generic 500
  after a server file-key rotation. Previews return an explanatory placeholder
  where possible, and raw content/stream APIs return `decrypt_unavailable`.
- The blocking pre-push gate is modularized under `scripts/prepush/`, adds
  cleanup helpers, and now has dedicated regression coverage for release-sync,
  governance/account, and trading updates.

## Validation

- `python3 scripts/pre_push_checks.py --ci`
- `PYTHONPATH=. python3 -m pytest -q tests/test_prepush_v2.py tests/test_frontend_account_admin.py tests/test_comfyui_integration.py tests/test_account_sessions.py tests/test_sanction_notices.py tests/test_trading_engine.py tests/test_video_publish.py tests/test_security_issue_regressions.py`

## 2026.05.02-050

## Highlights

- ComfyUI root settings now support local and remote connection modes. Local
  mode keeps startup explicit: users press the AI-page start button before
  generation, and already-running local ComfyUI instances can be reused by
  other users.
- Added `scripts/comfyui_run_in_linux.template.sh` as a reusable Linux
  startup template. It checks for an existing virtual environment, creates one
  only when needed, installs dependencies idempotently, and avoids embedding
  workstation-specific paths.
- ComfyUI generation ownership is tracked per user. Save, discard, share, and
  interrupt actions only operate on that user's generated image references;
  user interrupts avoid stopping other users' active backend jobs.
- Cloud Drive and album behavior is improved for E2EE session preview,
  document creation, media previews, queued remote downloads, and generated
  ComfyUI output albums.
- Video Platform publishing now works through the existing Cloud Drive storage
  layer for direct uploads and server-encrypted media without exposing storage
  paths.
- Documentation was cleaned to describe ComfyUI local/remote operation and to
  remove local machine path examples.

## Highlights

- Whole-site production gate is now available through
  `security/whole_site_production_gate.py` and
  `security/run_pentest.sh --only whole-site-production-gate`.
- Latest local gate evidence before the Video Platform module passed against
  `http://127.0.0.1:5000`:
  12/12 modules PASS, `critical_findings=0`, `high_findings=0`,
  `medium_findings=0`, `production_readiness=YES`.
- Latest evidence files:
  `security/reports/20260502T150309Z/raw/whole_site_production_gate_20260502_230524.json`
  and
  `security/reports/20260502T150309Z/raw/whole_site_production_gate_20260502_230524.md`.
- The gate aggregates Server Mode v2, auth/session, RBAC, snapshot/restore,
  PointsChain/economy, Cloud Drive, Video Platform, trading, forum/community/reporting,
  integrity, audit/logs, stress/reliability, pytest, `py_compile`, generated
  report policy, and `git diff --check`.
- Latest-password lookup now uses the monotonic `user_passwords.id` order
  instead of textual `created_at` ordering, avoiding stale-password selection
  when timestamp formats differ.
- Feature-disabled API gates now return unauthenticated requests as `401`
  before reporting feature-disabled `503`, so permission tests see the real
  authorization boundary.
- `functional_permission_pentest.py` now accepts `PENTEST_USER_PASSWORD` in
  addition to the legacy `PENTEST_TEST_PASSWORD`.
- `trading_stress_pentest.py` no longer rotates root's password by default;
  production-gate targets must use already-initialized test credentials or pass
  `--root-new-password` explicitly.

## Operator Notes

- Keep the whole-site gate evidence together with the Server Mode v2
  adversarial, Red Team L2, and live HTTP reports. The whole-site gate is the
  aggregate production decision; the Server Mode v2 reports remain its
  control-plane evidence.
- Server Mode v2 production_ready is narrower than whole-site
  production_ready. The whole-site gate must be run before production sign-off.
- Off-host append-only log replication / filesystem-level immutable storage is
  still a deployment-environment control; the local gate records it as an
  unresolved deployment risk unless verified separately.
- Runtime logs, generated reports, SQLite databases, pycache, and local keys are
  generated artifacts. They should remain ignored and must not be committed.
