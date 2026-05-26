# 2026-05-24 10:28 +0800 `:5000` 相簿分享管理整合

## Findings

- No open regressions found in this pass.

## Fix Verified

- 相簿頁不再顯示分享 URL、複製按鈕、建立/編輯分享密碼欄位；只保留 `分享` 入口。
- `分享` 入口會把相簿切成 `不列出，持連結可看`，並跳到分享管理開啟該 album share 的設定表單。
- 分享管理現在能管理 album share 的密碼、到期時間、最大存取次數、重置存取次數、撤銷與紀錄。
- 後端 `album_share_links` 增加 `expires_at` / `max_views`，公開相簿 API 會對過期與次數耗盡回 `410`，並給 `expired` / `view_limit_reached` reason。

## Coverage

- Static / unit:
  - `py_compile`: `services/storage/catalog.py`, `services/storage/albums.py`, `routes/share_management.py`, `routes/file_sections/share_preview_routes.py`
  - `node --check`: `public/js/35-drive.js`, `public/js/35-drive-preview-share.js`, `public/js/57-platform-centers.js`
  - `pytest -q tests/storage/test_storage_albums_schema.py tests/share/test_share_management_access_events.py tests/storage/test_cloud_drive_attachments.py::test_storage_album_crud_and_file_membership tests/frontend/storage/test_frontend_drive_preview.py tests/frontend/test_platform_centers_frontend.py`
- Live `:5000`:
  - Synced repo to `/tmp/hackme_web_dev_20260523_231210_3869876/hackme_web` and HUP reloaded gunicorn master `1182501`.
  - `/tmp/hackme_5000_album_share_center_probe.py`: passed. Created an album, enabled share, updated album share settings from `/api/shares/album/<id>`, verified password gate, view-limit exhaustion, and expired response.
  - `/tmp/hackme_5000_album_share_front_probe.py`: passed. Browser loaded the real front-end, verified old album password fields are gone, triggered the rendered album share button, and confirmed Share Management opened an album edit form with password, expiry, and max-view controls.
  - `/api/version`: healthy after reload, `started_at=2026-05-24T02:09:17Z`.

## Notes

- `runtime/logs/server.log` had old database-lock traces from earlier stress activity, but no new server error entries from this album-share verification window.
