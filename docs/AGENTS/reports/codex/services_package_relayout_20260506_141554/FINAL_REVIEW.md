**Scope**
This review covers the current `services/` package re-layout candidate only.

Status:
- `Services package re-layout: ACCEPTED AS MERGE CANDIDATE`
- `Merge status: PENDING FINAL REVIEW`
- `Current diff classification: mixed`
  - package relayout changes
  - benchmark / capacity / workflow template changes

**Moved Modules**
| Old module path | New module path | Notes |
| --- | --- | --- |
| `services.access_controls` | `services.security.access_controls` | top-level façade preserved |
| `services.btc_trade_bridge` | `services.trading.btc_bridge` | top-level façade preserved |
| `services.captcha` | `services.security.captcha` | top-level façade preserved |
| `services.cloud_drive` | `services.storage.cloud_drive` | top-level façade preserved |
| `services.comfyui_client` | `services.comfyui.client` | top-level façade preserved |
| `services.comfyui_workflows` | `services.comfyui.workflows` | top-level façade preserved |
| `services.e2ee_streaming` | `services.media.e2ee_streaming` | top-level façade preserved |
| `services.file_previews` | `services.media.previews` | top-level façade preserved |
| `services.identity` | `services.security.identity` | top-level façade preserved |
| `services.media_streaming` | `services.media.streaming` | top-level façade preserved |
| `services.password_strength` | `services.security.password_strength` | top-level façade preserved |
| `services.permissions` | `services.security.permissions` | top-level façade preserved |
| `services.remote_downloads` | `services.storage.remote_downloads` | top-level façade preserved |
| `services.security_events` | `services.security.events` | top-level façade preserved |
| `services.server_mode_context` | `services.server_mode.context` | top-level façade preserved |
| `services.server_mode_routing` | `services.server_mode.routing` | top-level façade preserved |
| `services.storage_capacity_audit` | `services.storage.capacity_audit` | top-level façade preserved |
| `services.storage_maintenance` | `services.storage.maintenance` | top-level façade preserved |
| `services.storage_paths` | `services.storage.paths` | top-level façade preserved |
| `services.storage_quota_enforcement` | `services.storage.quota_enforcement` | top-level façade preserved |
| `services.storage_quota_overrides` | `services.storage.quota_overrides` | top-level façade preserved |
| `services.storage_quota_purchases` | `services.storage.quota_purchases` | top-level façade preserved |
| `services.trading_markets` | `services.trading.markets` | top-level façade preserved |
| `services.trading_mode_gate` | `services.trading.mode_gate` | top-level façade preserved |
| `services.trading_price_streams` | `services.trading.streams` | top-level façade preserved |
| `services.videos` | `services.media.videos` | top-level façade preserved |

New package-local modules added without a prior top-level counterpart:
- `services.comfyui.constants`
- `services.comfyui.execution`
- `services.comfyui.files`
- `services.comfyui.workflow.builder`
- `services.comfyui.workflow.summary`
- `services.comfyui.validation.rules`
- `services.comfyui.validation.sanitize`
- `services.trading.catalog`

**Compatibility Façades**
The following legacy modules remain import-compatible by aliasing the new implementation module with `sys.modules[__name__] = _impl`:

- `services/access_controls.py`
- `services/btc_trade_bridge.py`
- `services/captcha.py`
- `services/cloud_drive.py`
- `services/comfyui_client.py`
- `services/comfyui_workflows.py`
- `services/e2ee_streaming.py`
- `services/file_previews.py`
- `services/identity.py`
- `services/media_streaming.py`
- `services/password_strength.py`
- `services/permissions.py`
- `services/remote_downloads.py`
- `services/security_events.py`
- `services/server_mode_context.py`
- `services/server_mode_routing.py`
- `services/storage_capacity_audit.py`
- `services/storage_maintenance.py`
- `services/storage_paths.py`
- `services/storage_quota_enforcement.py`
- `services/storage_quota_overrides.py`
- `services/storage_quota_purchases.py`
- `services/trading_markets.py`
- `services/trading_mode_gate.py`
- `services/trading_price_streams.py`
- `services/videos.py`

**Old Import Paths Still Usable**
Confirmed old import paths still in live use across routes, services, and tests:

- Routes:
  - `routes/public.py` uses `services.access_controls`, `services.captcha`
  - `routes/files.py` uses `services.cloud_drive`, `services.file_previews`, `services.remote_downloads`, `services.storage_*`
  - `routes/videos.py` uses `services.videos`, `services.media_streaming`, `services.e2ee_streaming`, `services.cloud_drive`
  - `routes/comfyui.py` uses `services.comfyui_client`, `services.comfyui_workflows`, `services.cloud_drive`
  - `routes/trading.py` uses `services.btc_trade_bridge`, `services.trading_markets`

- Services:
  - `services/trading_engine.py` still imports `services.server_mode_context`, `services.server_mode_routing`, `services.trading_mode_gate`, `services.trading_markets`, `services.trading_price_streams`
  - `services/upload_security.py` still imports `services.identity`, `services.storage_quota_overrides`, `services.storage_quota_purchases`
  - `services/member_levels.py` still imports `services.storage_quota_enforcement`

- Tests:
  - `tests/test_access_controls.py`, `tests/test_captcha.py`, `tests/test_cloud_drive_attachments.py`, `tests/test_comfyui_integration.py`, `tests/test_remote_downloads.py`, `tests/test_storage_paths.py`, `tests/test_storage_maintenance.py`, `tests/test_trading_markets.py`, `tests/test_video_*`

**Tests Depending On Monkeypatching Old Paths**
These tests depend on old module paths or private module members remaining patchable:

- `tests/test_remote_downloads.py`
  - monkeypatches `services.remote_downloads.shutil.which`
  - monkeypatches `services.remote_downloads.subprocess.Popen`
  - monkeypatches `services.remote_downloads.socket.getaddrinfo`
  - monkeypatches `services.remote_downloads.download_direct_link`
  - monkeypatches `services.remote_downloads.download_torrent_file_with_aria2`

- `tests/test_comfyui_integration.py`
  - monkeypatches `services.comfyui_client.urllib.request.urlopen`
  - binds `ComfyUIClient._build_text_to_image_base`
  - binds `ComfyUIClient._attach_controlnet`

- `tests/test_upload_security.py`
  - monkeypatches `services.storage_capacity_audit.shutil.disk_usage`

- `tests/test_cloud_drive_attachments.py`
  - imports `services.cloud_drive as cloud_drive`
  - monkeypatches `cloud_drive.scan_uploaded_file`

- `tests/test_video_streaming.py`
  - imports `services.media_streaming as media_streaming`
  - monkeypatches `media_streaming._run_probe`
  - monkeypatches `media_streaming._run_ffmpeg_hls`

Because of these tests, alias-style façades were kept instead of `from ... import *` wrappers.

**Source-Based Tests Watching Old File Contents**
Result:
- No source-based tests were found that directly assert the contents of the moved top-level façade files listed above.

Source-based tests do still pin old file contents for higher-risk files that were intentionally not package-moved in this round:
- `server.py`
- `services/upload_security.py`
- `services/snapshots.py`
- `services/points_chain.py`
- `services/storage_albums.py`
- `services/trading_engine.py`

This is one reason those files were left out of the current package re-layout slice.

**Runtime Path / Config / Dynamic Import Impact**
Dynamic import scan result:
- No relevant `importlib.import_module`, `__import__`, `SourceFileLoader`, or similar dynamic module loading was found for the moved `services.*` modules.

Runtime/config impact:
- The package re-layout does not rename runtime directories, env vars, or config keys.
- Existing runtime-sensitive modules still resolve through old import paths via façades.
- `server.py` runtime path/config contracts remain guarded by source-based tests and are not part of this relayout scope.

Residual compatibility note:
- Some new package implementations still import old façade paths internally, for example `services.storage.cloud_drive` importing `services.storage_paths`. This is acceptable for compatibility, but can be tightened in later cleanup once façade dependence is no longer needed.

**Validation**
Relayout-targeted validation previously run on the current content set:

- `PYTHONPATH=. python3 -m pytest -q tests/test_storage_paths.py tests/test_storage_maintenance.py tests/test_cloud_drive_attachments.py tests/test_video_streaming.py tests/test_upload_security.py tests/test_comfyui_integration.py`
  - `185 passed`

- `PYTHONPATH=. python3 -m pytest -q tests/test_access_controls.py tests/test_captcha.py tests/test_identity_schema.py tests/test_password_strength.py tests/test_security_events.py tests/test_trading_mode_gate.py tests/test_routing_service.py tests/test_smv2_context.py`
  - `122 passed`

- `PYTHONPATH=. python3 -m pytest -q tests/test_cloud_drive_attachments.py tests/test_video_publish.py tests/test_video_permission.py tests/test_video_comments.py tests/test_video_tips.py tests/test_video_security.py tests/test_video_streaming.py tests/test_trading_markets.py tests/test_trading_market_registry.py tests/test_trading_websocket_inputs.py tests/test_trading_mode_gate.py`
  - `132 passed`

- `PYTHONPATH=. python3 -m pytest -q tests/test_comfyui_integration.py tests/test_trading_reference_prices.py tests/test_security_defaults.py`
  - `112 passed`

- `HACKME_RUNTIME_DIR=/tmp/hackme_web_services_reorg2_20260506 PYTHONPATH=. python3 -m pytest -q tests/`
  - `1072 passed`

- `python3 scripts/pre_push_checks.py --ci`
  - `11 PASS / 0 FAIL`

- `git diff --check`
  - `pass`

**Mixed Diff Review**
The current worktree is broader than relayout-only.

Relayout-related content:
- service package moves and internal import rewiring
- top-level compatibility façades
- ComfyUI client/workflow modularization into package submodules

Non-relayout content mixed into the same worktree:
- backtest capacity / benchmark feature files
- workflow benchmark asset updates
- workflow template additions
- release sync docs/version updates

Required commit split:
1. `commit A`: services package relayout only
2. `commit B`: benchmark / capacity / workflow templates

**Rollback Plan**
If the relayout merge candidate causes regressions:

1. Revert `commit A` only.
   - This restores top-level implementations and removes package-local re-layout changes while leaving benchmark/template work untouched.

2. If needed, keep `commit B` in place.
   - Benchmark/capacity/template changes are intentionally isolated so they can survive a relayout rollback.

3. Re-run:
   - relayout-targeted pytest groups
   - full `pytest -q tests/`
   - `python3 scripts/pre_push_checks.py --ci`

4. Only after rollback stabilization, reopen a narrower relayout slice.
