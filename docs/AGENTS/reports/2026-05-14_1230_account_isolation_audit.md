# 2026-05-14 Account Isolation Audit

## Findings

- **High - fixed:** Trading form state was only held in the live DOM, so switching from `root` to `test` in the same browser tab could carry over personal inputs such as `trading-input-mode=points` and `trading-margin-collateral=121`.
- **Medium - fixed:** Trading workflow editor and ComfyUI workflow editor used global localStorage keys, allowing browser drafts/results to be visible to another account on the same browser profile.
- **Low - fixed:** UI-only preferences for ComfyUI active view, ComfyUI draft, economy subpage, sidebar collapse, and album thumbnail size now use an account-scoped key.

## Coverage

- Passed `node --check` for touched frontend scripts.
- Passed `python3 -m pytest tests/frontend/trading/test_frontend_economy.py -q`.
- Passed `python3 -m pytest tests/frontend/comfyui/test_comfyui_workflow_template_ui.py -q`.
- Passed `python3 -m pytest tests/frontend/storage/test_frontend_drive_preview.py -q`.
- Passed `python3 -m pytest tests/frontend/test_platform_centers_frontend.py -q`.

Remaining global browser storage was reviewed: CSRF/session hints and idle logout state are session controls, video share fragments are session-scoped, and real Tetris physics tuning is root/admin runtime tuning.
