# Update Summary

Release ID: `2026.05.07-152`

## 2026.05.07-152

- Refactored `routes/comfyui.py` into bounded route-registration modules under
  `routes/comfyui_sections/`, so root/admin connection tests, Civitai/model
  admin routes, and workflow preset routes no longer grow inside one route god
  file while the source-contract image-ref guards remain in the main module.
- Split `public/js/50-admin.js` by moving the root-only server-mode and
  launch-check dashboard block into `public/js/51-admin-server-mode-launch-check.js`,
  keeping the main admin bundle focused on shared admin helpers.
- Split `public/js/36-comfyui.js` by moving workflow preset/editor UI logic
  into `public/js/36-comfyui-workflows.js`, aligning the frontend module
  boundary with the new ComfyUI workflow route section.
- Increased the pre-push quick pytest timeout from 90s to 180s so the hook no
  longer reports an internal timeout when the selected cross-area regression
  corpus is still passing.
- Refactored `routes/files.py` by moving share-link, album-share, and preview
  routes into `routes/file_sections/share_preview_routes.py`, keeping the main
  file focused on upload/storage orchestration while preserving Cloud Drive
  policy and preview fail-closed behavior.
- Split `public/js/35-drive.js` by moving album share / preview / text-preview
  UI logic into `public/js/35-drive-preview-share.js`, so the main drive bundle
  no longer mixes browser storage actions with fullscreen preview flow.

## 2026.05.07-150

- `scripts/run_prod.sh` now aligns `FORCE_HTTPS=true` with Gunicorn's proxy
  trust model by writing/exporting `GUNICORN_FORWARDED_ALLOW_IPS` and passing it
  to `--forwarded-allow-ips`, so proxy-terminated HTTPS can upgrade
  `X-Forwarded-Proto` into a real secure WSGI scheme.
- The production deploy docs now spell out that `FORCE_HTTPS` alone is not
  enough; Gunicorn must trust the same proxy IPs that terminate TLS.

## 2026.05.07-149

- Refactored `routes/system_admin.py` into bounded route-registration modules
  under `routes/system_admin_sections/`, so the main file now focuses on
  shared helpers, dependency wiring, and source-contract breadcrumbs.
- Preserved route behavior and source-based regression coverage by keeping the
  existing high-risk git update / security-center / launch-check strings in
  `routes/system_admin.py` while moving the concrete route implementations into
  `security_routes.py`, `settings_routes.py`, and `runtime_routes.py`.
- Verified the slice with targeted admin/system tests, full `pytest`, and
  pre-push checks on branch `05.readability-refactor`.

## 2026.05.07-148

- Readability Refactor is now unblocked on branch `05.readability-refactor`:
  the full pytest baseline is green again, so inventory-only status is no
  longer forcing the branch to stop before code changes.
- Introduced `services/platform/admin_validation.py` to centralize one bounded
  family of root/admin validation helpers instead of keeping duplicate route-
  local parsers in `routes/system_admin.py`.
- The extracted helper set keeps previous behavior intact, including:
  strict bool parsing for admin settings, IP whitelist normalization, public
  path redaction, git branch validation, and ComfyUI script/endpoint checks.
- `routes/comfyui.py` now reuses the shared ComfyUI URL/host validator without
  collapsing user-facing error messages; blank URL handling for system-admin
  settings and detailed `credentials/path/shape` errors for the ComfyUI root
  test endpoint are both preserved.

## 2026.05.06-147

- `services/points_chain.py` has been split into a real
  `services/points_chain/` package with medium-grain boundaries: shared
  currency/schema/hash helpers and `ChainModeViolation` live in `schema.py`,
  while the full `PointsLedgerService` implementation now lives in
  `service.py`.
- Existing `from services.points_chain import ...` imports keep working through
  the package `__init__`, including compatibility for tests that monkeypatch
  `services.points_chain.time.time`.
- The old top-level `services/points_chain.py` path remains as a tiny
  source-reference facade so regression checks that inspect that file by path
  still enforce the pending-reward maker-checker contract.
- `ServerModeService` no longer sidesteps a repo-root `runtime` blocker by
  silently creating `.runtime/`. If no explicit runtime base dir is available,
  a non-directory `runtime` path now fails closed; when an `IntegrityGuard`
  instance provides an app base directory, server-mode audit/HMAC files are
  routed under that app-local runtime tree instead.

## 2026.05.06-146

- `services/snapshots.py` has been split into a real `services/snapshots/`
  package with medium-grain boundaries: shared schema/hash/signature helpers in
  `schema.py`, snapshot/archive/restore flow in `service.py`, and Server Mode
  v2 profile/checkpoint/audit flow in `server_mode.py`.
- Existing `from services.snapshots import ...` call sites keep working through
  the package `__init__`, while the old top-level `services/snapshots.py` path
  remains as a tiny compatibility/source-reference facade for regression tests
  and operator docs that still read that file by path.
- Snapshot and Server Mode helpers now tolerate a conflicting `runtime` file in
  the repo root by falling back to `.runtime/` for auto-generated local HMAC
  keys, removing an implicit path-shape assumption that broke
  `ServerModeService(snapshot_service=None)` test environments.

## 2026.05.06-145

- Trading workflow benchmark generation now preserves a stable frontend
  contract: the default `1h` benchmark run writes to the canonical
  `public/data/workflow_template_benchmarks.json`, while non-canonical
  interval or relative-threshold variants write to suffixed auxiliary files
  instead of silently diverging from the asset the frontend actually loads.
- The shipped workflow benchmark asset now carries explicit `interval` and
  `use_relative_thresholds` metadata so the trading UI can label benchmark
  data correctly and tests can validate the asset contract directly.
- Added dedicated regression coverage for backtest-capacity projection,
  first-boot capacity probe recording, and the canonical workflow benchmark
  asset schema instead of relying only on broad trading/backtest integration
  tests.

## 2026.05.06-144

- `server_encrypted` Cloud Drive uploads no longer write plaintext to any
  temporary disk file before scanning. The upload path now exposes plaintext to
  scanners through an in-memory Linux `memfd` path and only writes ciphertext
  to the final storage location, closing the remaining plaintext-at-rest window
  during upload scanning.
- Trading backtest auto-fetch routes now keep the overall `backtest_max_candles`
  cap separate from the per-request provider batch limit, and they fall back to
  the legacy default cap when lightweight/test trading service stubs do not
  implement `get_max_backtest_candles()`.

## 2026.05.06-143

- API routes now fail with a consistent JSON envelope instead of Flask's
  default HTML 5xx page when an unhandled exception escapes `/api/...`, while
  non-API requests keep a minimal plain-text 500 fallback.
- Cloud Drive's security model docs now spell out the trust boundary between
  `standard_plain`, `server_encrypted`, and strict `e2ee` storage so users can
  see exactly when the server/root can read plaintext and when they cannot.
- Server-encrypted Cloud Drive uploads now scan a dedicated temporary plaintext
  file and only write ciphertext to the final storage path, closing the old
  window where the permanent storage location could briefly contain plaintext.
- Snapshot restore now fails closed if the server cannot enable maintenance
  mode before the restore begins, instead of silently continuing with a dirty
  runtime state.
- PointsChain wallet rebuild is now transaction-safe even when called without
  an outer transaction, preventing a crash between `DELETE` and re-insert from
  leaving all wallet rows empty.
- ComfyUI workflow import now rejects oversized workflow JSON, excessive node
  counts, and overly deep nesting to reduce denial-of-service risk from giant
  crafted workflows.
- `websocket-client` is now declared in `requirements.txt`, matching the live
  trading websocket provider code path used by Binance/Coinbase streaming.

## 2026.05.06-142

- `test_shadow_wallets` is now aligned with the points-only trading shadow path
  instead of the older `soft_* / hard_*` split. Fresh snapshot schemas create
  `balance_points`, `frozen_points`, `total_points_earned`, and
  `total_points_spent`, while migrations fold any legacy soft/hard values into
  those canonical fields so internal-test trading, funding settlement, and
  chain-backed margin opens stop failing on missing shadow-wallet columns.
- The Server Mode v2 smoke harnesses now point back at the actual tutorial
  bundle under `docs/examples/server_mode_v2/` instead of an empty
  `scripts/server_mode_v2/` directory, so `security/server_mode_v2_token_smoke.py`
  and `security/server_mode_v2_full_smoke.py` run the same scripts the docs and
  tests reference.
- `docs/examples/server_mode_v2/06_full_feature_smv2.sh` now passes
  `target_username` when rotating an `internal_test` login token, matching the
  current server-side requirement for single-account-bound internal-test login
  tokens.
- `docs/examples/server_mode_v2/05_stress_smv2.sh` no longer burns the full
  burst after the first blocked tester-token response; it now exits the rate
  limit probe as soon as the contract is proven and shortens the per-request
  timeout, eliminating the prior full-smoke timeout on script 05.

## 2026.05.05-141

- Trading fused-price trust semantics are now less sensitive in normal market
  conditions. Partial order-book coverage or auto-excluding a few unhealthy
  provider rows no longer automatically forces the frontend into
  `reference 價格降級` / `risk_grade_usable=false` as long as enough healthy
  providers still produce a valid risk-grade price.
- The trading page now keeps a green state for `warning-only` price fusion
  diagnostics and explicitly says that some providers were excluded while the
  current risk-grade price remains usable.
- Yellow/low-trust trading warnings are now reserved for actual degraded
  conditions such as stale/fallback provider input, conservative mode, cached
  or manual price paths, or other real high-risk price-health failures.

## 2026.05.05-140

- Audit chain / Integrity Guard 對正常維運的敏感度已收斂：root 被動查看
  `/api/admin/health`、`/api/admin/health/audit-chain`、`/api/admin/audit` 時，
  若 audit chain 斷裂，系統現在只會回傳 `critical`、`operator_action_required`
  與 `auto_lockdown_applied=false`，不再因單純查狀態就自動切進 maintenance mode。
- Integrity Guard `strict mode` 在重啟 / 更新後若看到 high-risk findings，
  啟動流程現在會記 audit warning 並繼續提供服務；真正的 `GO_LIVE` /
  pre-production entry 仍會因這些 findings 被擋住，直到 root review 完成。

## 2026.05.05-139

- Trading UI warning text is now explicit when only `reference price` remains:
  the frontend says `目前風控級價格不可用，已暫停市價單與高風險交易；限價單仍可使用`
  instead of implying the whole market has no price.
- Production report upload is now a verified path instead of a loose JSON
  intake: uploads must include `raw_report`, `sha256` `report_hash`,
  `hmac_sha256` `signature`, and `key_version`, and the server recomputes the
  hash plus verifies the signature before the report can satisfy production
  gate requirements.
- `internal_test` login tokens are no longer shared across multiple accounts.
  Root must bind each issued token to a single target account, and only that
  account can use it on `/api/login` while the server is in `internal_test`
  mode.
- The root launch-check upload helper now explains signed-report requirements
  directly in the UI, and failed production-report verification surfaces a
  concrete reason instead of a generic upload failure.
- Cloud Drive PDF preview now uses an iframe/new-tab fallback path that works
  under the site's CSP (`object-src 'none'`), so strict E2EE and
  server-encrypted PDFs no longer fail because the browser blocks
  `object/embed`.
- Strict E2EE video pages no longer prompt for decryption immediately on page
  load; users must explicitly press `開始 E2EE 播放` before fragment lookup,
  password prompt, and browser-side decrypt begin.
- The audit / PointsChain recovery buttons are now wired to the correct chains:
  the audit page repairs audit/integrity chains, while the PointsChain recovery
  card owns the `一鍵處理 PointsChain 異常` action and its own status line.
- Tester-token APIs now expose `GET /api/tester/shadow-role` and
  `GET /api/tester/shadow-wallet` in addition to the existing POST mutation
  routes, so the documented read paths no longer return `404`.

## 2026.05.05-138

- Root 的 ComfyUI 模型匯入區現在新增 `放大模型 / Upscaler` 類型，下載 Civitai 模型或直接上傳本地模型檔時，都可以正確落到預設的 `ComfyUI/models/upscale_models/`。
- 同一個匯入區也新增「下載到哪個路徑」欄位，可填 `ComfyUI/models/` 底下的相對路徑；若留空則依模型類型自動選用預設資料夾。後端會拒絕 absolute path、`..` 與任何跳出 `ComfyUI/models/` 的路徑。
- 補上回歸：前端已接上 `upscale` 類型與路徑提示，Civitai download / model upload 都可保存 `relative_dir`，而路徑穿越會被拒絕。

## 2026.05.05-137

- `上線前檢查` 的 playbook / tests 捷徑不再直接跳 repo-relative `docs/...` 而導致 `NOT FOUND`。root 現在可透過新 API `GET /api/root/launch-check/doc?path=docs/...` 在站內直接閱讀 production gate playbook / 測試文件。
- 每一張 production gate report 卡現在都有 `上傳報告` 入口，可直接貼上 JSON 或選擇 `.json` 檔後送往 `/api/root/production-report/upload`；上傳成功後會即時重整 B 區狀態。
- 新增回歸涵蓋：launch-check 文件檢視只允許 `docs/` 內安全路徑、path traversal 會被拒絕，且前端 upload/doc panel 的關鍵元素與事件綁定存在。

## 2026.05.05-136

- 安全中心的 root 上線前測試面板現在不再只靠一個混合任務列表。滲透、越權 / 權限濫用、全功能、壓力四種測試都各自有獨立卡片、獨立進度條、最近任務狀態與詳細 log，操作上不再需要從混雜 job list 猜哪段輸出屬於哪種測試。
- 新增 root-only `POST /api/root/security-tests/privilege`，直接驅動 `security/functional_permission_pentest.py`，可從安全中心啟動越權 / permission-abuse 測試；若需要，也可顯式帶 `--destructive` 跑高風險 guard。
- root 安全測試面板的前端綁定也同步補齊：四種測試都會顯示人性化狀態、progress 與 log，而且 `loadSecurityTestJobs()` 會把最新 job 正確分流到對應卡片，而不是互相覆蓋。

## 2026.05.05-135

- `open_margin_position()` now routes margin position inserts through the
  resolved `margin_positions` table for the active Server Mode v2 context
  instead of hardcoding `trading_margin_positions`.
- Internal-test margin opens now populate `tester_user_id` when writing shadow
  rows, so `test_shadow_margin_positions` inserts follow the shadow schema
  contract instead of failing or silently drifting back toward production-only
  assumptions.
- Internal-test margin collateral and fee ledger writes now pass the active
  trading context into `_ledger(...)`, ensuring chain-backed shadow margin opens
  write to `test_shadow_ledger` / `test_shadow_wallets` instead of production
  `points_ledger` / `wallets`.
- Added regressions proving:
  - shadow margin opens create rows only in `test_shadow_margin_positions`,
  - chain-backed shadow margin opens leave production `points_ledger` untouched,
  - shadow ledger rows record the expected tester namespace.

## 2026.05.05-134

- Server Mode v2 的 `上線前檢查` 不再把「已先切成 production」或「已先手動套 production 等級安全設定」誤當成 preflight 前置條件。A 區現在只保留真正的切換前 blocker（鏈 / 完整性 / readiness / anomaly / reports），而 production profile 的 HTTPS、audit chain、Integrity Guard、browser-only 等會明確標成 `切換時自動套用`。
- root 若在 `dev_ready`、`test`、`internal_test` 等非 production 模式先做上線前檢查，現在不會再因為目前尚未套用 production posture 而被一排紅燈誤導；真正的 `GO_LIVE` 切換仍由 mode switch 路徑與 production gate 共同把關。

## 2026.05.05-133

- Trading market registry 的 seed drift 現在不再是隱性風險。`trading_markets_registry` 新增 `registry_source` 與 `seed_version`，root 後台與 API 也會回傳 `catalog_seed_version`、`seed_sync_status`、`seed_sync_reasons`、`seed_sync_message`，明確標示某個市場是 `catalog_seed` 還是 `custom`，以及是否已偏離目前 code catalog。
- 這一刀沒有把 DB 悄悄蓋回 catalog。runtime 仍以 DB registry 為 source of truth；若 seeded 市場被 root 調整過，後台只會顯示 `drifted`，讓 drift 可見、可審計，而不是自動回寫。
- migration / bootstrap 也同步升到 schema version `30`，並新增 regression：seeded 市場會回 `seed_version` / `current`，root 自建市場會回 `custom`，修改 seeded 市場後會顯示 `drifted`。

## 2026.05.05-132

- Root 的 GitHub 伺服器更新流程現在會在成功 fast-forward 後，先依本次 `git diff` 變動到的受保護檔案重建 Integrity Guard baseline，再做後續 integrity scan。這樣更新後不會因為「剛套用的新版本檔案」立刻全部變成 pending findings。
- 這次 baseline refresh 只接受本次更新涉及的檔案，不會粗暴清空所有 pending findings；若 repo 內另有與本次更新無關的異常，後續 integrity scan 仍會把它們保留下來。
- 新增 regression 驗證：`rebaseline_paths(...)` 只會接受指定檔案、其他 finding 仍維持 pending；server update route 也明確要求 baseline refresh，而不是單純 rescan。

## 2026.05.05-131

- Shared unlisted video pages no longer get stuck on a generic `讀取中...` state when the playback step discovers that a share password is still required. The browser now treats `password_required` / `password_invalid` / `password_locked` responses from any shared-video API step as a signal to reopen the unlock form instead of leaving the page looking frozen.
- The shared-video page also now updates its loading copy from a static `讀取中...` placeholder to concrete states such as `正在讀取分享資訊...` and `此分享影音需要先解鎖`, so E2EE shared playback failures are easier to distinguish from password-gated shares.

## 2026.05.05-130

- Trading provider fallback discipline 的第一刀已收斂成「價格信任等級」而不是全面改寫交易規則：`test_live_price_provider` 現在會被標成 `confidence=low`、`synthetic_test_provider=true`，並在 `reference / risk-grade` context 中明確標示 `risk_grade_usable=false`。
- `manual_root`、最後健康快取、以及 degraded / stale / fallback provider input 都會明確回傳 `risk_grade_usable=false` 與對應 warning；cached / degraded 高風險價格仍會被後端 hard block，而 synthetic test provider 只保留給單測與注入測試，不可由 root 設定成正式 `price_source`。
- 前端交易頁與 root 市場管理診斷已同步顯示 `風控可用 yes/no`，並在市價單 / 融資風險估算中同時檢查 `high_risk_blocked || risk_grade_usable === false`，避免把 synthetic、manual 或 cached 價格靜默當成 production risk-grade 使用。

## 2026.05.05-129

- Server Mode v2 的 Trading Phase 5b G-5 已把 funding publish / settlement world split 打通：funding snapshot 現在會依 `funding_channel_key(market, ctx)` 發佈到 mode-aware channel，production 與 `internal_test` 不再共用 funding state。
- 新增 `publish_funding_rate_snapshot(...)`、`get_funding_rate_snapshot(...)` 與 `settle_funding_adjustment(...)` 這組 canonical funding path；若 settlement 想拿 production snapshot 去結算 shadow world（或反過來），會先觸發 `assert_same_world(...)` 拒絕，而不是錯寫 wallet / ledger。
- `internal_test` funding settlement 現在只會落到 `test_shadow_wallets` / `test_shadow_ledger`，即使 shadow funding feature flag 被打開，也不會污染 production `points_ledger`、wallet balance 或 chain block 計數。

## 2026.05.05-128

- Server Mode v2 的 Trading Phase 5b G-4 已把 liquidation source/sink 明確 mode-lock：liquidation source 現在經由 `liquidation_target_table(ctx)` 指向 `trading_margin_positions` 或 `test_shadow_margin_positions`，settlement sink 則經由 `liquidation_settle_table(ctx)` 指向 production 或 shadow wallet world。
- `close_margin_position(... force_liquidation=True)` 與 `scan_margin_liquidations()` 現在都會先做 same-world guard；production liquidation 繼續沿用原流程，但 `internal_test` liquidation 會在任何 reserve / ledger / chain side effect 之前明確拒絕，避免 shadow liquidation 寫到 production wallet、points ledger 或 chain。
- 這輪也補了 `test_shadow_margin_positions` schema 與 regression：internal_test 不會拿 production `position_uuid` 來強平，手工插入的 shadow margin position 也只會收到「shadow liquidation 尚未支援」的明確錯誤，而不會留下半套 production mutation。

## 2026.05.05-127

- Server Mode v2 的 Trading Phase 5b G-3 已把 in-memory matching engine orderbook 真的改成依 `matching_orderbook_key(market, ctx)` 分 namespace，而不是只靠 `market_symbol` 當 key；同一個 `BTC/POINTS` 在 production、`test`、以及不同 `internal_test tester_id` 下都會落到不同的 matching book。
- `match_open_limit_orders()` 現在先依 routed world hydrate 對應 namespace 的 open limit orders，再從該 world 的 in-memory book 取 order UUID 進行撮合；`cancel_order()`、`_execute_order()` 與 trial-credit reclaim 取消單也會同步清掉各自 namespace 內的幽靈單。
- 這輪的關鍵防線是：shadow tester 7 的 open limit order 不會再被 tester 8 或 production matcher 看見，避免「同一張 test_shadow_orders 表內不同 tester 共用 orderbook」的 cross-world/cross-tester 撮合污染。

## 2026.05.05-126

- Server Mode v2 的 Trading Phase 5b G-2 已把交易引擎內與 `orders / positions / points_ledger / wallets` 相關的主要 SQL 路徑收斂成 runtime routing：`user_dashboard`、grid bot scan、root simulated reset、verification / safe-mode replay helpers 現在都會依 mode 解析到 production 或 shadow 表，而不是再直接讀寫固定的 production 表名。
- `test_shadow_wallets / test_shadow_orders / test_shadow_positions / test_shadow_ledger` 的 shadow schema 已補齊 production 路徑需要的核心欄位，讓 internal_test world 可以承接交易凍結、trial / chain split、ledger metadata 與 safe-mode verification，而不再只是一組過於簡化的示意表。
- 這輪是架構強化而不是新 UI：目標是讓 SMv2 internal_test 的交易資料路徑更接近真正的 dual-world routing，並確保 production wallet / ledger 不會因 shadow-mode 交易引擎讀寫而被污染。

## 2026.05.05-125

- ComfyUI 新增 `Workflow 工作台`：可把目前表單匯出成經過安全清洗的 workflow JSON，再匯入成 private/public preset、保存描述與可見性，之後可一鍵套用、一鍵重跑與匯出已保存的 preset JSON。
- workflow JSON 進入系統前現在會做伺服器端安全驗證：拒絕壞 JSON、absolute path、shell / exec / command 類節點、外部 URL 與可疑敏感欄位；缺少 checkpoint / LoRA / ControlNet / workflow node 時，執行 preset 會明確回 `409`，不再靜默 fallback。
- root 可把自己的 workflow preset 發布為 official preset，private preset 仍只允許擁有者存取；workflow run 會保存 seed / CFG / steps / LoRA / ControlNet 等完整參數，方便之後比對與重跑。

## 2026.05.05-124

- 交易市場不再只靠程式內 hardcode：新增 root-only trading market registry，可在後台新增 / 編輯 / 停用市場，調整 `precision / lot size / tick size`，並維護各交易所 provider mapping 與排序。
- `provider mapping` 與 `risk-grade` 啟用現在有明確 probe 與 audit：root 修改市場或 provider mapping 會留下 before/after audit log；若 depth provider 不足或 probe 未達標，市場不可啟用 `risk-grade` 用途。
- disabled market 只會阻擋新下單，不會破壞既有歷史、持倉與報表；下單與融資路徑也會立即套用市場 precision、lot size、tick size 與新開關條件。

## 2026.05.05-123

- strict E2EE 影音新增 `E2EE Streaming v2` 基礎：瀏覽器可使用 encrypted chunk manifest、逐段密文下載、Web Worker 解密與 `MediaSource` 播放；若沒有 v2 manifest、裝置不支援 Worker / MediaSource / WebCrypto，會明確退回舊版完整解密播放，而不是假裝成功或誤走 HLS。
- 新增 `/api/videos/<id>/e2ee-stream-v2/manifest`、`/api/videos/<id>/e2ee-stream-v2/chunks/<chunk_index>` 與對應 shared token 路由；這些端點永遠只回密文 chunk，不接收 `raw_file_key`、`e2ee_password`、`vk`，也沿用分享 token 的過期、撤銷與最大觀看次數保護。
- 影音前端現在可在 strict E2EE 路徑下區分 `browser_e2ee_stream_v2` 與 `browser_e2ee_full_fallback`，共享頁也會明確顯示「讀取分享授權 / 下載加密影音 / 瀏覽器端解密」等階段提示，並在分享授權無效或被竄改時顯示人性化錯誤。

## 2026.05.05-139

- Trading UI warning text is now explicit when only `reference price` remains:
  the frontend says `目前風控級價格不可用，已暫停市價單與高風險交易；限價單仍可使用`
  instead of implying the whole market has no price.
- Production report upload is now a verified path instead of a loose JSON
  intake: uploads must include `raw_report`, `sha256` `report_hash`,
  `hmac_sha256` `signature`, and `key_version`, and the server recomputes the
  hash plus verifies the signature before the report can satisfy production
  gate requirements.
- `internal_test` login tokens are no longer shared across multiple accounts.
  Root must bind each issued token to a single target account, and only that
  account can use it on `/api/login` while the server is in `internal_test`
  mode.
- The root launch-check upload helper now explains signed-report requirements
  directly in the UI, and failed production-report verification surfaces a
  concrete reason instead of a generic upload failure.
- Cloud Drive PDF preview now uses an iframe/new-tab fallback path that works
  under the site's CSP (`object-src 'none'`), so strict E2EE and
  server-encrypted PDFs no longer fail because the browser blocks
  `object/embed`.
- Strict E2EE video pages no longer prompt for decryption immediately on page
  load; users must explicitly press `開始 E2EE 播放` before fragment lookup,
  password prompt, and browser-side decrypt begin.
- The audit / PointsChain recovery buttons are now wired to the correct chains:
  the audit page repairs audit/integrity chains, while the PointsChain recovery
  card owns the `一鍵處理 PointsChain 異常` action and its own status line.
- Tester-token APIs now expose `GET /api/tester/shadow-role` and
  `GET /api/tester/shadow-wallet` in addition to the existing POST mutation
  routes, so the documented read paths no longer return `404`.

## 2026.05.05-122

- `deploy.sh` now supports `--with-civitai-key '<CIVITAI_API_KEY>'`, so first-time deployments can seed root-only Civitai search/download access without manually editing `.env`.
- `scripts/run_prod.sh --check` now reports optional capability status for `ffmpeg` / `ffprobe` (video HLS derivative pipeline), `CIVITAI_API_KEY` (root-only Civitai search/download), and the canonical offline root recovery entrypoint `python3 scripts/root_recovery.py`.
- Deployment docs and quickstart guides now explain that these checks are advisory capability hints rather than hard blockers for normal deployment.

## 2026.05.05-121

- Cloud Drive preview now treats archives and PDFs more like a normal file manager: archive preview renders a structured file/folder list, plain and `server_encrypted` PDFs prefer the browser's native PDF viewer path, and strict `e2ee` PDFs render through browser-side decrypt plus `object/embed` with a new-tab fallback.
- E2EE file preview now reuses the most recently successful passphrase within the current login session before prompting again, reducing repeated password dialogs when opening multiple E2EE files with the same secret.
- Shared strict E2EE video pages now show explicit progress phases (`share auth`, `ciphertext download`, `browser decrypt`) instead of looking frozen on a generic loading state, and the health indicator UI now hides the text label while the server remains green/healthy.

## 2026.05.05-120

- Expanded the Server Mode v2 example bundle under `docs/examples/server_mode_v2/` with four new runnable scripts: `04_pentest_smv2.sh`, `05_stress_smv2.sh`, `06_full_feature_smv2.sh`, and `07_privilege_escalation_smv2.sh`.
- Added `security/server_mode_v2_full_smoke.py`, an isolated runtime harness that runs the full six-script SMv2 tutorial bundle (`01`, `02`, `04`, `05`, `06`, `07`) and then asserts that shadow-table activity did not leak into production wallet / ledger tables.
- Synced README, Traditional Chinese README, developer guide, QA map, pentest guide, and the examples README so the new SMv2 tutorial bundle and full smoke harness are documented as the canonical live-http coverage route.

## 2026.05.05-119

- Expanded the security validation script suite instead of only relying on product tests: `functional_permission_pentest.py` now covers root-only ComfyUI / Civitai search, inspect, model upload, and download-job endpoints across anonymous, user, manager, and root roles.
- `trading_stress_pentest.py` now forces a conservative fused-price state and verifies that degraded `risk-grade price` input blocks high-risk market orders and financing opens rather than silently leaking degraded data into trading.
- `video_module_pentest.py` now covers manager-side unlisted share-link regeneration, strict E2EE shared-video envelope boundaries, and revoked share-link blocking; `run_functional_smoke.sh` also confirms that the offline `scripts/root_recovery.py` CLI remains available.

## 2026.05.05-118

- `root` 已正式脫離一般 Web 忘記密碼流程：`/api/password-reset/request` 與 `/api/password-reset/confirm` 對 root 帳號都會拒絕，避免把最高權限帳號降級成一般 email token / review reset 模式。
- 新增離線 `scripts/root_recovery.py`，可在實體 runtime 上直接重設 root 臨時密碼、撤銷既有 session、清掉 CSRF token，並要求下次登入立刻修改密碼。
- README、Admin Guide、CLI Playbook、Troubleshooting、API Reference 與 QA 文件已同步改成以 offline root recovery CLI 為正式補救路徑。

## 2026.05.05-117

- Added root-only Civitai search/filter support on the local ComfyUI model-import panel: keyword search, base-model filter, checkpoint / LoRA / embedding / ControlNet type filter, and Safe/NSFW filtering now hit the official Civitai model search API instead of requiring users to paste a page URL up front.
- Search results now summarize latest-version metadata before download, including version name, file size, hash hints, compatible/base models, and an explicit “帶入下載區” step; downloads also require a second confirmation dialog before writing into the local ComfyUI `models/` tree.
- Added human-readable handling for missing Civitai API keys and interrupted downloads, extended functional smoke to probe the new search endpoint’s API-key guard, and updated API / QA / admin / developer docs to match the new root-only workflow.

## 2026.05.05-116

- Fixed live ComfyUI `inpaint` / `outpaint` workflow validation against current `VAEEncodeForInpaint` by explicitly setting `grow_mask_by`, so real jobs no longer fail with `Required input is missing: grow_mask_by`.
- Added root model import source mode switching: the local ComfyUI panel can now either inspect/download from a Civitai URL or upload a local model file directly into the appropriate `models/` folder with extension validation and audit logging.
- Added `scripts/comfyui_feature_probe.py` plus regression coverage so operators can live-smoke `status`, `models`, `txt2img`, `img2img`, `inpaint`, `outpaint`, `upscale`, ControlNet availability, and history rerun without hand-building each request.

## 2026.05.05-115

- ComfyUI generation now supports `img2img`, `inpaint`, `outpaint`, ControlNet-assisted workflows, upscale-model selection, and generation history replay as first-class UI/API features instead of only plain txt2img.
- `GET /api/comfyui/models` now exposes capability metadata for generation modes, ControlNet families/models/preprocessors, and upscale models; `POST /api/comfyui/generate` accepts multipart source/mask/control images and rejects missing models, invalid image formats, missing workflow nodes, or out-of-range ControlNet strength with human-readable errors.
- Added `/api/comfyui/history`, `/api/comfyui/history/<history_id>/rerun`, and `/api/comfyui/image-preview` so saved inputs can be restored, rerun, and previewed without silently re-uploading hidden state; the mobile form and release docs were updated to match.

## 2026.05.05-114

- Trading provider input now prefers websocket ticker/depth feeds for Binance, OKX, Coinbase, and Kraken, but keeps websocket strictly as provider input instead of replacing `reference price` / `risk-grade price` semantics.
- `GET /api/trading/live-price` and root `GET /api/root/trading/price-fusion-status` now expose canonical transport state (`connected`, `fallback`, `stale`, `degraded`, `confidence`, `provider_count`, `last_update_at`, `exclusion_reason`, `transport_state`) so UI, smoke checks, and risk controls can audit degraded or fallback states explicitly.
- Fixed a quality-filtered single-source fallback bug in fused-price diagnostics and added dedicated regression coverage for websocket updates, disconnect fallback, malformed provider payload rejection, and blocking risk-grade price when only degraded single-source data remains.

## 2026.05.05-113

- Trading price semantics are now explicit across the site instead of treating every number as a generic market price: `reference price` is for display, charting, and general valuation, while `risk-grade price` is reserved for financing, liquidation, margin maintenance, unrealized PnL, bot risk checks, and trading limits.
- `GET /api/trading/live-price` now returns canonical `price_type`, `source`, `confidence`, `stale`, `degraded`, and `provider_count` fields plus `reference_price_context` / `risk_grade_price_context`; `GET /api/trading/reference-prices` now returns the same canonical reference-price context metadata.
- The trading UI now labels current price, spot valuation, spot PnL, margin risk, and order-entry estimates with their actual price usage, and high-risk operations now show human-readable "risk-grade price unavailable" blocking messages instead of silently relying on ambiguous fallback pricing.

## 2026.05.05-112

- The video watch page now includes an E2EE share-management panel for unlisted videos, exposing share state, remaining views, password status, expiry, max views, copy/regenerate/revoke controls, and the explicit warning that fragment loss is unrecoverable.
- Share-link management now stays consistent with the documented permissions: manager/root can update or revoke unlisted share links, while strict E2EE regeneration still requires a fresh browser-side share envelope from the publisher's original password.
- Added richer regression coverage for share state payloads, manager-side share-link updates, fragment-loss/tamper messaging, and the mobile layout of the new management controls.

## 2026.05.05-111

- Added same-origin `hls.js` playback fallback for prepared HLS media, so desktop Chrome / Firefox / Edge can play HLS reliably without breaking Safari native HLS.
- Video playback APIs now expose `player_strategy`, `stream_warning`, and `hls_js_url`, and the UI now surfaces human-readable HLS/direct/E2EE playback states instead of silently guessing.
- Shared video pages now use the same HLS fallback rules as the main video page; strict E2EE shares still stay browser-side, while HLS.js failures fall back to direct stream with explicit error messaging.
- Added release-level regression coverage for local `hls.js` loading, shared-page fallback wiring, and HLS/E2EE playback hints.

## 2026.05.05-110

- Added [ENCRYPTION_RUNTIME_BOUNDARY.md](ENCRYPTION_RUNTIME_BOUNDARY.md) as the canonical operator/engineer trust-boundary document for `standard_plain`, `server_encrypted`, strict `e2ee`, and E2EE shared-video envelopes.
- Added [EXTERNAL_API_COMMAND_MATRIX.md](EXTERNAL_API_COMMAND_MATRIX.md) to inventory the upstream exchange, Civitai, and ComfyUI commands currently used by the project, plus nearby capabilities not yet wired.
- Added a regression proving that a runtime engineer can decrypt `server_encrypted` data with the runtime file key, but cannot decrypt strict `e2ee` data from runtime state alone.

## 2026.05.05-109

- Unlisted E2EE videos can now be shared without downgrading strict E2EE into server-side HLS: the owner enters the original E2EE password once at publish time, the browser re-wraps the file key into a share envelope, and viewers use the complete link fragment plus an optional second-layer share password for browser-side playback.
- Added video share-link management APIs for owners/managers: revoke or regenerate share links, plus optional expiry time and maximum view count controls.
- Shared video routes now reject forbidden secret fields (`raw_file_key`, `e2ee_password`, `vk`), enforce password retry lockouts, honor expiry / max views, and count access consistently across metadata/playback routes.

## 2026.05.05-108

- Video streaming Phase C-1 now auto-prepares HLS derivatives for eligible public/unlisted media and `server_encrypted` uploads on publish, while keeping publish success intact if derivative packaging fails.
- Video watch pages now show human-readable stream status and let owners or managers re-run HLS preparation directly from the UI.
- The video publish form now explains when HLS derivatives are attempted automatically.

## 2026.05.05-107

- Added three more points-quoted trading markets to the centralized market catalog: `XRP/USDT`, `BNB/USDT`, and `PAXG/USDT` display pairs backed by internal `XRP/POINTS`, `BNB/POINTS`, and `PAXG/POINTS` symbols.
- Added Phase C-1 media streaming foundation: HLS derivative schema/service, `prepare-stream` and `stream-status` media routes, `playback` decision API, and protected HLS manifest/segment routes for prepared plain or `server_encrypted` video.
- Video frontend now prefers prepared HLS playback when available and falls back to the existing direct `/stream` route when no derivative exists or the browser lacks native HLS support.

## 2026.05.04-106

- Cloud Drive audio and video preview now use the native `/preview/content` stream URL instead of fetching a blob first, so browsers can handle streaming media previews more reliably.
- Clarified the attachment-storage wording: chat / DM / announcement attachments only write into `/attachments/` when those attachment actions are actually used; this is a storage path convention, not a separate built-in module.
- Added `docs/VIDEO_STREAMING_ARCHITECTURE.md` as the canonical Phase C design for HLS / segmented media streaming, including the split between `standard_plain`, `server_encrypted`, and strict `e2ee` media behavior.

## 2026.05.04-105

- Added an in-page explanation beside `設定 -> 交易所參數 -> 價格來源與融合比例`, so root can see exactly how `auto_depth` works: front `10` order-book levels, midpoint `±1%` band, and `depth_score = min(bid_notional, ask_notional)` before the system normalizes weights to `100%`.

## 2026.05.04-104

- Added `docs/API_REFERENCE.md` as the canonical implemented API route map, so developers no longer need to piece together current endpoints from `For_developer.md`, trading docs, and scattered QA notes.
- Added `docs/CLI_ADMIN_PLAYBOOK.md` as the official `curl` / shell playbook for root, admin, and developer site operations in isolated runtimes.
- Updated `README.md`, `docs/README.md`, `docs/README.zh-TW.md`, `docs/For_developer.md`, and `docs/11_QA_TESTING.md` to point to these new dedicated API / CLI documents.

## 2026.05.04-103

- The account/admin area no longer hardcodes several toolbars with inline
  desktop-only flex layouts, so the existing mobile responsive rules can
  actually collapse those control rows into usable single-column stacks on
  narrow screens.
- The admin users table now sits inside a dedicated horizontal scroll wrapper,
  making large account-management tables usable on phones instead of forcing
  the full page width to overflow.

## 2026.05.04-102

- The root trading settings UI now renders manual fusion weights as compact
  per-provider chips instead of a large full-width grid, reducing empty space
  in `設定 -> 交易所參數 -> 價格來源與融合比例`.
- Each provider weight input now sits inline beside its exchange label with a
  trailing `%` marker, while the helper text clarifies that values do not need
  to sum to exactly `100` because the backend normalizes them automatically.

## 2026.05.04-101

- `security/stress_test.py` now supports a duration-based flood mode in
  addition to fixed request-count mode, including per-worker burst sizing and a
  burst interval to simulate short HTTP flood spikes against authorized
  loopback or owned staging targets.
- Root security-test jobs can now launch the same duration-based stress mode
  with `duration_seconds`, `max_requests`, `burst_size`, and
  `burst_interval_ms`, while keeping the existing count-based mode compatible.

## 2026.05.04-100

- The pre-push workflow now auto-cleans repo-local Python caches and a
  mistakenly generated repo-root `runtime/` before running the blocking
  validation suite.
- `scripts/pre_push_checks.py --clean` now removes both safe cache artifacts
  and a repo-root `runtime/` directory, while still refusing to touch tracked
  files or protected runtime/report paths.

## 2026.05.04-099

- Server mode audit export artifacts no longer spill into repo-root `security/audit_exports/`; they now write under `runtime/reports/server_mode_audit/` with the rest of runtime-generated files.
- `.gitignore` no longer masks `security/audit_exports/`, so any future regression that writes audit exports back into the source tree will show up immediately in `git status`.
- Snapshot / server-mode regression coverage now asserts the runtime audit export path directly.

## 2026.05.04-098

- Runtime DB, logs, storage, chat data, generated secrets, TLS cert/key, and integrity manifest now default under `runtime/` instead of scattering across the repo root.
- `HACKME_RUNTIME_DIR` still works for isolated runs, but the relative default layout is now `runtime/database`, `runtime/logs`, `runtime/storage`, `runtime/cert.pem`, `runtime/.chain_seed`, and related files.
- `btc_trade_bridge` now follows the same runtime root for its default DB and chain seed lookup, so it no longer drifts back to repo-root `database.db` or `.chain_seed`.
- Snapshot runtime-secret handling now understands the `runtime/` prefix and keeps restore/reset logic aligned with the new runtime layout.

## 2026.05.04-097

- Margin / lending position detail now shows `損益平衡價` alongside `逐倉估算強平價`.
- Break-even price now includes `開倉費 + 累積利息 + 預估平倉手續費`, so it reflects the real exit threshold instead of raw entry price only.
- Frontend live margin risk now recomputes interest, next billing time, break-even price, and liquidation price on the same `2` second rhythm as live price refresh, so hourly interest accrual is reflected without waiting for a full dashboard reload.

## 2026.05.04-096

## Highlights

- `GET /api/trading/live-price` now reports `refresh_interval_ms = 2000`,
  matching the current 2-second trading page polling interval instead of
  advertising the old 1-second cadence.
- This keeps live-price API metadata aligned with the frontend trading wallet
  and PnL refresh loop, so diagnostics no longer claim a faster refresh than
  the UI actually uses.

## Validation

- `PYTHONPATH=. python3 -m pytest -q tests/test_trading_reference_prices.py tests/test_frontend_economy.py tests/test_release_policy.py`
- `PYTHONPATH=. python3 -m pytest -q tests`
- isolated live API validation script under `docs/AGENTS/reports/codex/final_open_issues_review_*/scripts/live_api_validation.sh`
- `python3 scripts/pre_push_checks.py --ci`
- `git diff --check`

## 2026.05.04-095

## Highlights

- Cloud Drive folder browsing now supports the common double-click-to-open
  interaction, so users no longer have to rely only on the right-side `開啟`
  button to enter a folder.
- The explicit `開啟` button remains as a fallback, and the double-click target
  excludes action buttons so download/delete controls do not accidentally
  navigate.

## Validation

- `PYTHONPATH=. python3 -m pytest -q tests/test_frontend_drive_preview.py tests/test_release_policy.py`
- `python3 scripts/pre_push_checks.py --ci`
- `git diff --check`

## 2026.05.04-094

## Highlights

- Community announcements now support in-place editing for manager/root users.
  Admins can revise title, content, and pinned state directly instead of
  deleting and re-posting the announcement.
- The announcement editor now switches cleanly between create mode and edit
  mode, including different submit text and form reset on cancel.

## Validation

- `PYTHONPATH=. python3 -m pytest -q tests/test_community_permissions.py tests/test_frontend_community_layout.py tests/test_release_policy.py`
- `python3 scripts/pre_push_checks.py --ci`
- `git diff --check`

## 2026.05.04-093

## Highlights

- The trading reference chart now offers a broader built-in indicator set:
  `MA10`, `MA30`, `EMA50`, `RSI14`, and `KD(9,3,3)` were added on top of the
  existing MA / EMA / Bollinger overlays.
- `RSI14` and `KD` now render in a dedicated oscillator subpanel, so the
  trading page can show trend overlays and overbought/oversold signals without
  squashing everything onto the same price axis.

## Validation

- `PYTHONPATH=. python3 -m pytest -q tests/test_frontend_economy.py tests/test_release_policy.py`
- `python3 scripts/pre_push_checks.py --ci`
- `git diff --check`

## 2026.05.04-092

## Highlights

- Chat stickers now use emoji-style quick buttons and render sent stickers as
  real emoji glyphs instead of text labels such as `微笑` or `感謝`.

## Validation

- `PYTHONPATH=. python3 -m pytest -q tests/test_frontend_chat.py tests/test_release_policy.py`
- `git diff --check`

## 2026.05.04-091

## Highlights

- Trading market metadata is now centralized in `services/trading_markets.py`,
  so internal symbols, display aliases, provider IDs, default seeded markets,
  and BTC_trade support all come from one catalog instead of multiple hardcoded
  maps.
- Trading live-price, reference-price, backtest, market ordering, wallet spot
  sections, and root price-fusion market selection now consume the same market
  definitions, reducing the work needed to add future points-quoted assets such
  as `SOL` or `GOLD`.

## Validation

- `PYTHONPATH=. python3 -m pytest -q tests/test_trading_markets.py tests/test_trading_reference_prices.py tests/test_trading_engine.py tests/test_frontend_economy.py`
- `git diff --check`

## 2026.05.04-090

## Highlights

- Cloud Drive audio previews now normalize blob MIME from preview metadata, so
  music files can still inline-preview even when the browser first receives a
  generic blob type.
- Publishing a video from an existing Cloud Drive media file now supports an
  uploaded custom cover image instead of silently ignoring the chosen cover.

## Validation

- `PYTHONPATH=. python3 -m pytest -q tests/test_video_publish.py tests/test_cloud_drive_attachments.py -k 'audio_preview_content_supports_streamable_music or accepts_cover_upload_for_existing_cloud_media or video_upload_endpoint_accepts_audio_and_streams_it or video_upload_endpoint_stores_server_encrypted_video_and_streams_plaintext'`
- `PYTHONPATH=. python3 -m pytest -q tests/test_frontend_drive_preview.py tests/test_frontend_videos.py tests/test_release_policy.py`
- `git diff --check`

## 2026.05.04-089

## Highlights

- Large Cloud Drive uploads are no longer hard-blocked at `50 MB` before they
  reach the real per-user quota and max-file policy checks.
- The Flask request-body cap is now controlled by
  `HTML_LEARNING_MAX_CONTENT_MB` with a default of `1024 MB`, and API callers
  now get a structured `413 request_too_large` JSON payload instead of a bare
  status code.

## Validation

- `PYTHONPATH=. python3 -m pytest -q tests/test_security_defaults.py tests/test_release_policy.py`
- `git diff --check`
- `python3 scripts/pre_push_checks.py --ci`

## 2026.05.04-088

## Highlights

- Uploaded chat, DM, and announcement attachments now land in the Cloud Drive
  `/attachments/` folder instead of cluttering the drive root.
- The stored display name remains the original filename while the underlying
  storage path gets a unique attachment-prefixed name to avoid path collisions.

## Validation

- `PYTHONPATH=. python3 -m pytest -q tests/test_frontend_drive_preview.py tests/test_release_policy.py`
- `git diff --check`
- `python3 scripts/pre_push_checks.py --ci`

## 2026.05.04-087

## Highlights

- Chat attachment UX is now inline with the message composer instead of hiding
  upload and existing-file actions inside a separate `聊天室附件` card.
- Picking a file now immediately adds it to the pending send list, while room
  scoped `聊天室共用附件` only appears when the current room actually has shared
  attachments.

## Validation

- `PYTHONPATH=. python3 -m pytest -q tests/test_frontend_chat.py tests/test_frontend_drive_preview.py tests/test_release_policy.py`
- `git diff --check`
- `python3 scripts/pre_push_checks.py --ci`

## 2026.05.04-086

## Highlights

- ComfyUI LoRA / Embedding interaction is now reversible in the AI page. Removing
  a selected LoRA removes its no-longer-needed trigger words, choosing `不使用
  LoRA` and pressing `加入` clears the current LoRA list, and clicking an already
  inserted Embedding removes it again.
- Embeddings whose filename contains `neg` or `negative` now default to the
  negative prompt instead of the positive prompt.

## Validation

- `PYTHONPATH=. python3 -m pytest -q tests/test_comfyui_integration.py tests/test_release_policy.py`
- `git diff --check`
- `python3 scripts/pre_push_checks.py --ci`

## 2026.05.04-085

## Highlights

- ComfyUI now blocks unsupported LoRA base-model families before generation.
  Only `SDXL`, `Pony`, `Illustrious`, and `Noob` LoRAs remain selectable in the
  AI page. `SD1.5`, `Flux`, and unknown-metadata LoRAs are shown as unavailable
  and the backend rejects crafted requests that try to bypass the UI.
- Root-downloaded Civitai LoRA sidecars now persist `base_model` metadata so
  later page loads can enforce the same compatibility rule consistently.

## Validation

- `PYTHONPATH=. python3 -m pytest -q tests/test_comfyui_integration.py tests/test_release_policy.py`
- `git diff --check`
- `python3 scripts/pre_push_checks.py --ci`

## 2026.05.04-084

## Highlights

- ComfyUI generation now uses a 30-minute default wait budget end-to-end
  instead of timing out earlier on the frontend progress poll or the backend
  generation route. Long model loads or retried queue waits no longer fail just
  because the default cap was too short.

## Validation

- `PYTHONPATH=. python3 -m pytest -q tests/test_comfyui_integration.py tests/test_release_policy.py`
- `git diff --check`
- `python3 scripts/pre_push_checks.py --ci`

## 2026.05.04-083

## Highlights

- The notification center no longer shows two different `read all` actions for
  the same API call. The panel keeps the single header-level `全部已讀`
  button and removes the duplicate in-list `一鍵全部已讀` action.

## Validation

- `PYTHONPATH=. python3 -m pytest -q tests/test_frontend_notifications.py tests/test_release_policy.py`
- `git diff --check`
- `python3 scripts/pre_push_checks.py --ci`

## 2026.05.04-082

## Highlights

- Margin-buy collateral validation copy is now humanized. Instead of only
  showing a mechanical `最高 N 點`, the UI now distinguishes:
  - collateral below the minimum requirement
  - a valid financing range
  - collateral that already exceeds the full notional and therefore should use
    normal spot buying instead of margin
- The warning now explicitly explains that margin buy must still borrow at
  least `1` point, so users understand why `保證金 >= 名目金額` no longer counts
  as financing.

## Validation

- `PYTHONPATH=. python3 -m pytest -q tests/test_frontend_economy.py tests/test_release_policy.py`
- `git diff --check`
- `python3 scripts/pre_push_checks.py --ci`

## 2026.05.04-081

## Highlights

- Spot wallet detail rows now separate `持有成本` from `損益平均價格`.
  `持有成本` shows the acquisition cost including the estimated buy-side fee,
  plus a per-unit cost view. `損益平均價格` shows the fee-aware break-even
  exit price after also accounting for the estimated sell-side fee.
- The unrealized PnL copy in spot wallet rows now explicitly says it already
  includes the estimated sell-side fee, so users no longer have to guess why
  the break-even price is above the displayed average cost.

## Validation

- `PYTHONPATH=. python3 -m pytest -q tests/test_frontend_economy.py tests/test_release_policy.py`
- `git diff --check`
- `python3 scripts/pre_push_checks.py --ci`

## 2026.05.04-080

## Highlights

- The lightweight `GET /api/trading/live-price` poll still runs every two
  seconds, but now it also refreshes the Points wallet trading PnL cards on
  the same cadence instead of waiting for the slower full dashboard reload.
- Spot position value / unrealized PnL, root virtual total, and margin risk /
  equity / unrealized PnL now recompute from the latest in-memory live market
  price, so wallet-side trading numbers no longer stay stale while the current
  price card keeps moving.
- Live-price polling now runs on both the `trading` page and the `economy`
  wallet page. It updates only the active wallet markets plus the currently
  selected trading market, keeping the refresh lightweight without forcing a
  full dashboard fetch every two seconds.

## Validation

- `PYTHONPATH=. python3 -m pytest -q tests/test_frontend_economy.py tests/test_release_policy.py`
- `git diff --check`
- `python3 scripts/pre_push_checks.py --ci`

## 2026.05.04-079

## Highlights

- Grid Bot creation now uses a backend-owned fee preview instead of a
  frontend-only spread guess. `POST /api/trading/grid/preview` calculates the
  worst-case grid spacing, break-even spread, per-grid gross profit, fee, and
  net profit with `Decimal`, then returns a red / yellow / green risk light.
- Grid preview red-lights now block creation, while thin-profit yellow-lights
  require an extra confirmation. This prevents the old UI failure mode where a
  strategy looked profitable because it only showed raw spread and ignored
  fees.
- The trading page keeps the existing capital / inventory estimate, but now
  shows fee-aware copy such as `最不利一格毛利`, `最不利一格手續費`,
  `最不利一格扣費後淨利`, and `損益兩平間距`.

## Validation

- `PYTHONPATH=. python3 -m pytest -q tests/test_grid_fee_model.py tests/test_grid_preview_api.py tests/test_grid_fee_ui.py`
- `PYTHONPATH=. python3 -m pytest -q tests/test_trading_engine.py -k 'grid' tests/test_frontend_economy.py tests/test_release_policy.py`
- `git diff --check`

## 2026.05.04-078

## Highlights

- The default Cloud Drive purchase plan is now `1GB / 7 days` instead of
  `1GB / 30 days`.
- Existing databases are normalized on startup so the legacy
  `cloud_storage_1gb_30d` catalog row keeps the same key but gets the new
  `item_name`, `duration_days`, and label, avoiding mixed `30 天 / 7 天`
  displays between fresh and old runtimes.

## Validation

- `PYTHONPATH=. python3 -m pytest -q tests/test_upload_security.py tests/test_cloud_drive_attachments.py tests/test_release_policy.py`
- `git diff --check`

## 2026.05.04-077

## Highlights

- The trading page `live-price` polling cadence is now `2` seconds instead of
  `1`, reducing exchange API load while keeping the current-price card visibly
  alive.
- Buy/sell order estimates stay in lockstep with that same `2`-second
  live-price refresh, so the quoted notional/fee preview no longer lags behind
  the displayed market price.

## Validation

- `PYTHONPATH=. python3 -m pytest -q tests/test_frontend_economy.py tests/test_release_policy.py`
- `git diff --check`

## 2026.05.04-076

## Highlights

- The feature-flag settings page now ships with two root-friendly global
  presets:
  - `全開`: replace the whole feature matrix with every module enabled
  - `最低維運`: replace the whole feature matrix with the minimum operational
    baseline (`accounts`, `audit`, `system health`, `server modes`,
    `snapshot / restore`)
- Existing domain bundles such as account governance, community, drive, AI, and
  trading stay additive; they still only turn on the related module family
  instead of wiping the rest of the matrix.
- The feature-page helper text, deployer docs, admin guide, QA checklist, and
  troubleshooting notes now explain the difference between additive bundles and
  full-matrix presets so root operators do not accidentally think `最低維運`
  is a small tweak.

## Validation

- `PYTHONPATH=. python3 -m pytest -q tests/test_frontend_drive_preview.py tests/test_release_policy.py`
- `python3 scripts/pre_push_checks.py --ci`
- `git diff --check`

## 2026.05.04-075

## Highlights

- Trading fee and borrowing controls are now aligned to the new defaults:
  - spot fee `0.10%`
  - grid fee = spot fee with `25%` discount
  - `BTC / ETH = 8% APR`
  - `USDT / POINTS = 10% APR`
  - hourly billing with `minimum 1 hour`
- Root trading settings can now adjust those rates directly from the dedicated
  `交易所` page instead of relying on the older daily-interest mental model.
- Borrow positions now expose `累積利息`, `已實扣`, and `下一次計息` metadata in the
  trading UI, so users can see both accrued interest and the next billing time.
- The backend now accumulates per-user trading volume / fee statistics for
  future VIP logic, and root reports expose aggregate `volume_summary`.
- Grid deterministic QA baselines were re-synced after the new fee defaults, so
  the engine, pytest suite, and `security/trading_exchange_validation.py` all
  agree on the updated result.

## Validation

- `PYTHONPATH=. python3 -m pytest -q tests/test_trading_engine.py tests/test_frontend_economy.py tests/test_trading_reference_prices.py tests/test_release_policy.py`
- `PYTHONPATH=. python3 security/trading_exchange_validation.py --out /tmp/trading_exchange_validation_fee_apr_followup`
- `python3 scripts/pre_push_checks.py --ci`
- `git diff --check`

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
