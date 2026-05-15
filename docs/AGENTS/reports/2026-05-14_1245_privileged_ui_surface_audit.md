# 2026-05-14 Privileged UI Surface Audit

## Findings

- **Medium - fixed:** ComfyUI `模型管理` was visible in the initial markup and only hidden later by JavaScript. Non-root users cannot use local model management, so the subtab now starts hidden and is revealed only when the active account is `root` and ComfyUI is in local mode.

## Audit Coverage

- Checked privileged entry points in the main markup: server center, account management, root chess engine panel, game weekly award, economy root/admin panels, trading root card, root quick settings, and ComfyUI model management.
- Confirmed these surfaces are hidden in initial markup and revealed by role/module state instead of being merely disabled.
- Added frontend assertions to keep the ComfyUI model-management tab and other privileged surfaces from regressing to visible-by-default markup.

## Verification

- `node --check public/js/36-comfyui.js`
- `python3 -m pytest tests/frontend/comfyui/test_comfyui_workflow_template_ui.py -q`
- `python3 -m pytest tests/frontend/layout/test_ui_polish.py -q`
- `python3 -m pytest tests/frontend/trading/test_frontend_economy.py -q`
