# 2026-05-26 10:26 5000 Profile Quick Settings / Process Detail QA

## Findings

- Fixed: 系統管理「相關背景程式資源」只顯示簡短主程式分類，無法看到實際 command line。現在 API 回傳 `command` / `command_truncated`，前端同列顯示角色、完整命令、`comm` 與 `ppid`。
- Fixed: 個人主頁外觀設定仍混在「編輯資料」，且 `profile_style` 欄位沒有由前端送出，新增模板/配色也沒有完整套用。現在外觀控制移到主頁「主頁快速設定」，側邊個人面板新增入口，控制項變更會即時預覽並保存 `profile_style`。

## Coverage

- `node --check public/js/00-core.js`
- `node --check public/js/50-admin.js`
- `node --check public/js/58-profile-friends.js`
- `python3 -m py_compile routes/system_admin_sections/security_routes.py`
- `pytest tests/frontend/admin/test_frontend_security_center_layout.py::test_system_environment_processes_and_integrity_are_rendered_below_resources -q`
- `pytest tests/frontend/users/test_profile_friends_frontend.py::test_profile_friends_panel_is_wired_as_user_module -q`
- `pytest tests/users/test_profile_friends.py -q`

## Live 5000

- Synced changed files into `/tmp/hackme_web_accept_20260526_server_mode_prelaunch_update_card/hackme_web`.
- Reloaded gunicorn master `752480` with HUP.
- Bumped static asset query strings for `styles.css`, `00-core.js`, `50-admin.js`, and `58-profile-friends.js` so browsers do not keep the old UI.
- Verified `/api/admin/environment/resources` returns detailed process `command`.
- Verified live assets contain `profile-quick-customize-card`, `profile_style: collectProfileStyleFromForm()`, and `主程式 / 詳細命令`.
- Performed live `test` account profile style save/revert; `profile_style` persisted and returned correctly.
