# Frontend UI Playwright Audit - 2026-05-14 07:56 CST

## Findings

No blocking frontend defects remain confirmed after the fixes in this pass.

### Resolved During Audit - ComfyUI first screen was too dense

- Severity: Medium, fixed.
- Behavior: the ComfyUI module mixed generation controls, history rerun, workflow builder, and root model management in one long surface. This made the intended next action hard to read, especially after adding Hugging Face Diffusers, GGUF, official model families, and workflow templates.
- Fix: split ComfyUI into subviews: `生成`, `歷史重跑`, `Workflow`, `模型管理`. The default view now shows generation only; template details stay hidden until a template is selected; root-only model controls are not shown to non-root users.
- Evidence: `/tmp/hackme_frontend_ui_audit_54240/frontend_ui_audit.json`, screenshots in `/tmp/hackme_frontend_ui_audit_54240`.

### Residual IA Risk - Trading and Economy are still high-density pages

- Severity: Low, recommendation.
- Behavior: no horizontal overflow or broken layout was detected, but Trading is still a high-scroll operational page and Economy shows many cards in one module.
- Evidence: custom Playwright metrics reported Trading `scroll_height=2486`, Economy `visible_cards=16`, and `overflow_px=0` for all checked modules.
- Recommendation: if the next cleanup is scoped, split Trading into `市場`, `下單`, `機器人`, `紀錄`; split Economy into wallet/ledger/catalog/admin subviews.

## Coverage

- Deep Playwright site check: PASS.
  - Command: `python3 /home/s92137/hackme_web/scripts/testing/playwright_deep_site_check.py --runtime-root /tmp/hackme_web_playwright_ui_audit_after_subtabs_2_20260514 --max-chess-human-moves 6`
  - Report: `/tmp/hackme_web_playwright_ui_audit_after_subtabs_2_20260514/reports/qa/playwright_deep_site_check_20260513T235452Z.md`
  - Covered login/register, admin/member management, forum, drive/E2EE, videos/HLS/share, games/chess score, economy/trading, launch/security health, ComfyUI workflow builder, module switching at `1366x768` and `390x844`, visual workflow editor, Civitai missing-key guard, and chess AI smoke.

- Targeted frontend UI audit: PASS.
  - Report: `/tmp/hackme_frontend_ui_audit_54240/frontend_ui_audit.json`
  - Screenshots: `/tmp/hackme_frontend_ui_audit_54240`
  - Covered ComfyUI subviews, official templates for ZIT/Anima/NetaYume/Flux/SD3.5/Wan, human-readable model labels, direct model path hints, Diffusers repo input replacing workflow selection, desktop/mobile overflow, and browser console/page errors.

- Targeted tests: PASS.
  - `python3 -m pytest -q tests/frontend/comfyui tests/comfyui/test_system_workflows.py tests/comfyui/test_template_ui_schema.py tests/frontend/storage/test_frontend_drive_preview.py`
  - `node --check public/js/36-comfyui.js`
  - `node --check public/js/36-comfyui-workflows.js`
  - `python3 -m py_compile services/comfyui/template/ui_schema.py scripts/comfyui/materialize_system_workflows.py scripts/testing/playwright_deep_site_check.py`

## False Positives Invalidated

- The first post-change deep Playwright run failed `comfyui_workflow_builder_journey` and `comfyui_main_page_visual_button` because the test still expected workflow controls to be visible on the ComfyUI default view. The product behavior was intentional after introducing subviews. The test now opens the `Workflow` subview before asserting those controls.

## Notes

- Browser/page error list was empty in both the targeted ComfyUI audit and the final deep site check.
- Full-site module checks found no horizontal overflow across chat, community, drive, videos, games, ComfyUI, economy, trading, accounts, and server modules.
