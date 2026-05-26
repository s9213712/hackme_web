# 2026-05-24 21:25 5000 Live QA - Storage Root / ComfyUI Gate

Target: `https://127.0.0.1:5000`

## Findings Fixed

- **MEDIUM - ComfyUI template preview accepted `AnimateDiffSampler`**
  - Evidence: `functional_permission_pentest.py` initially returned `108 passed / 1 failed`; the failing check was `root comfyui template preview rejects denylisted class`, with HTTP 200 instead of 400.
  - Fix: moved `AnimateDiffSampler` out of importer media allowlist and into explicit denylist; added endpoint and allowlist tests.
  - Verification: rerun after reload returned `109 passed / 0 failed`.

- **HIGH - Switching dev cloud-drive root could strand active files in old runtime storage**
  - Evidence: after starting `:5000` with `--cloud-drive-root /mnt/d/hackme_web_cloud_drive_test`, 4 active `uploaded_files` rows pointed under the new root but existed only in `/tmp/hackme_web_pc0_5000_wallet_ui/runtime/storage`.
  - Fix: `test_for_develop.sh` now copies missing legacy `runtime/storage` files into the configured cloud-drive root on startup, without deleting old files or overwriting new ones.
  - Verification: restart printed `storage migration: copied=420`; recent active file check showed `missing_count=0`, `outside_root_count=0`.

## Coverage

- `member_probe.py` against live `:5000`: 17 checks passed, 0 findings.
- `functional_permission_pentest.py` against live `:5000`: 109 passed, 0 failed after fix.
- `stress_test.py` against live `:5000`: 240 requests at concurrency 24, 0 server errors, p95 521.23 ms, statuses were expected `200/401/404`.
- Storage root verification: latest 23 active uploaded files exist under `/mnt/d/hackme_web_cloud_drive_test`.

## Local Checks

- `bash -n test_for_develop.sh`
- `python3 -m py_compile services/comfyui/template/allowlist.py routes/comfyui_sections/template_routes.py`
- `pytest -q tests/scripts/deploy/test_deploy_script.py`
- `pytest -q tests/comfyui/test_template_allowlist.py tests/comfyui/test_template_preview_endpoint.py`

## Runtime

- Current live PID: `2607106`
- Runner: gunicorn, workers=3, threads=6
- Storage root: `/mnt/d/hackme_web_cloud_drive_test`
- Storage cap: `1024 MB`
