# 2026-05-31 Cloud Drive / E2EE / Storage Audit

Scope: targeted code review, fixes, and live audit for the user-reported hackme_web issues around cloud drive encryption naming, E2EE session UX, quota deletion, 7-day storage catalog, password policy toggles, album deletion, avatar encryption support, trusted hosts, timezone options, and deployment prompt wording.

## Fixed in this pass

- Encrypted cloud uploads no longer expose the original filename in the physical storage path:
  - E2EE files use random `*.e2ee`.
  - Server-side encrypted files use random `*.server_encrypt`.
  - UI/API still preserve `original_filename_plain_for_public`.
- Cloud-drive delete now permanently removes the physical file, marks related DB rows deleted/revoked, and recalculates storage usage instead of silently leaving bytes on disk.
- Deleting/trashing a storage folder now also deletes matching album records and revokes album share links.
- Server secret/key files are chmodded to `0600` when loaded, not only when newly created.
- Local interface IPs are added to Flask trusted hosts so direct `host:port` deployment does not reject the server's own IP by default.
- Cloud storage purchase/birthday duration is now consistently 7 days in backend defaults, frontend quick settings/admin defaults, docs, and tests.
- Login can set an in-memory global E2EE passphrase. It auto-fills E2EE upload and is tried first for E2EE preview; logout clears it and active uploads trigger a logout warning.
- E2EE passphrase strength now follows the app's password policy shape and removes the previous hard 10-character minimum.
- E2EE preview after refresh now prompts for a password instead of failing with a stale-cache message.
- Album gallery shows a decrypt-preview path for E2EE files and has a delete button in both album list surfaces.
- Frontend/backend now expose a global `password_strength_policy_enabled` setting. When disabled, registration/password reset/admin password paths skip strength policy while still rejecting empty/overlong passwords.
- User/server timezone choices now include fixed UTC-12 through UTC+12 options.
- Server-side encrypted cloud images can be selected and served as avatars. Raw E2EE avatar sources are rejected with an explicit message because the backend cannot decrypt them; a browser-decrypted avatar derivative flow is still needed.
- `test_for_develop.sh` capacity prompt no longer describes blank and `-1` as the same choice.

## Verification

- `python3 -m py_compile` on modified backend modules.
- `node --check` on modified frontend modules and trading JS.
- `bash -n test_for_develop.sh`.
- Targeted tests:
  - `tests/storage/test_cloud_drive_attachments.py`
  - `tests/storage/test_upload_security.py`
  - `tests/storage/test_avatar_upload.py`
  - `tests/account/auth/test_account_register.py::test_register_can_disable_password_strength_policy`
- Live isolated audit:
  - `/home/s92137/hackme_web/test_for_develop.sh --cli --run-root /tmp/hackme_web_audit_20260531_after --port 50742 --skip-install --no-capacity-probe`
  - `member_probe.py --base-url https://127.0.0.1:50742`
  - Result: 17 checks, 0 findings.

## Remaining follow-up

- Cloud drive multi-select/select-all is still not fully implemented for both file and folder actions.
- Video upload still needs an explicit multi-select streaming-mode purchase UX; playback already supports prepared HLS/realtime/E2EE paths.
- E2EE avatar support needs a browser-side decrypt-and-upload-derived-avatar flow. The server must not directly read the original E2EE file.
- CI 03/04 and full GitHub Actions log triage were not completed in this pass.
- A full Playwright mobile/desktop exploratory sweep should still be run after the remaining UI work.
