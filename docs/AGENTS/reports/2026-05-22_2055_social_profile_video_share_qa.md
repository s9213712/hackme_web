# Social Profile / Video Share Targeted QA

## Result

No confirmed blockers in the targeted profile, follow, and video-share pass.

## Coverage

- Unit/API: `pytest -q tests/users/test_profile_friends.py tests/video/api/test_video_comments.py tests/platform/test_feature_flags.py::test_default_password_change_guard_can_be_disabled_for_isolated_runtime`
- Frontend syntax: `node --check public/js/00-core.js public/js/25-community.js public/js/39-videos.js public/js/58-profile-friends.js`
- Live Playwright: root login without forced password change, public profile navigation, enlarged avatar, follow action, profile stats, video social-share action, share count, interaction score, and community `[[video-share:...]]` render.
- Live API negative/burst: unauthenticated follow rejected, self-follow rejected, duplicate follow does not double count, 5 social-share requests returned 200 and increased share count.

## Artifacts

- `/tmp/hackme_web_isolated_54343/hackme_web/runtime/reports/qa/social_profile_video_share_playwright.json`
- Live isolated server kept running: `https://127.0.0.1:54343`

## Notes

- The isolated runtime had `feature_videos_enabled=false`; for live QA only, `feature_videos_enabled`, `feature_privacy_uploads_enabled`, and `feature_storage_albums_enabled` were enabled in that isolated runtime.
- The QA fixture video uses `cloud_file_id=qa-social-profile-video-file` and title `QA 社交分享測試`.
