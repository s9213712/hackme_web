# Encryption Runtime Boundary

This document explains what an engineer can and cannot recover if they can
touch the deployed `hackme_web` runtime files directly.

Use this together with [WEB.md](../WEB.md) and [VIDEO_PLATFORM.md](../video/VIDEO_PLATFORM.md)
when reviewing Cloud Drive / video privacy promises.

## Scope

This is an operator / engineer trust-boundary document, not a user guide.

Assume the engineer can read:

- `runtime/storage/...`
- `runtime/database/database.db`
- `runtime/.filekey`
- other runtime secrets present on the same host

The question is: can that engineer recover plaintext file contents without the
end user?

## Privacy Modes

### `standard_plain`

- Files are stored as plaintext on disk.
- Anyone with filesystem access to the stored file can read the content.

This mode is not intended to hide data from the server or from engineers with
host access.

### `server_encrypted`

- Files are stored encrypted at rest.
- The server keeps the file-encryption key in runtime state.
- Routes such as preview, download, and video streaming can decrypt the file on
  the server side.

Engineering consequence:

- an engineer with runtime file access **can** decrypt `server_encrypted`
  objects if they also have the runtime file-encryption key
- this mode reduces disk / backup exposure
- this mode is **not E2EE**

Code path:

- decrypt helper: `services/storage/cloud_drive.py`
- file preview / download: `routes/files.py`
- video stream / HLS packaging: `routes/videos.py`, `services/media/streaming.py`

### `e2ee`

- The browser encrypts the file before upload.
- The server stores ciphertext, encrypted metadata, nonce, and recipient-specific
  wrapped keys.
- The server does **not** receive the user's original E2EE password.
- The server does **not** keep a raw file key that can decrypt the ciphertext by
  itself.

Engineering consequence:

- an engineer with runtime file access can read ciphertext and wrapped key
  records
- that engineer cannot decrypt the file from runtime state alone
- the same runtime server file key used for `server_encrypted` files does not
  decrypt E2EE files

Code path:

- E2EE key fetch for an authenticated recipient only: `routes/files.py`
- wrapped key storage: `services/storage/cloud_drive.py`

## Video Sharing Boundary

### Non-E2EE video

- `standard_plain` and `server_encrypted` videos can use server-side stream
  preparation and HLS derivatives.

### Strict E2EE video

- strict E2EE videos do **not** use server-side HLS
- playback stays browser-side
- when an owner publishes an unlisted E2EE video, the browser:
  1. asks for the original E2EE password once
  2. unwraps the file key locally
  3. generates a random 256-bit share key
  4. wraps the file key again with AES-GCM
  5. uploads only the wrapped share envelope

The share key itself travels only in the URL fragment, for example:

```text
/shared/videos/<token>#vk=<base64url-share-key>
```

The fragment is never sent to the server as part of the HTTP request.

Engineering consequence:

- the server can store the wrapped share envelope
- the server still does not learn the raw file key
- if the engineer steals runtime files and database rows but **not** the URL
  fragment, that is still insufficient to decrypt the E2EE video

If the complete share URL fragment leaks from a browser, clipboard, or user
copy/paste channel, then the holder of that complete link has the same access as
the intended viewer. That is expected; the fragment is bearer material.

## What The Server Must Never Accept

The server must reject any request that tries to upload or update:

- `raw_file_key`
- `e2ee_password`
- `vk`
- equivalent raw share-key fields

Current enforcement:

- `routes/videos.py`

## Recovery Promise

### `server_encrypted`

- recoverable by the server while the correct runtime file key still exists
- can become unavailable after key rotation / reset if old ciphertext remains

### `e2ee`

- not recoverable by the server
- if the user loses the original E2EE password, the file is unrecoverable
- if an owner loses an E2EE video share fragment, the share cannot be restored;
  it must be regenerated

## Regression Evidence

The current regression that locks this promise:

- `tests/storage/test_cloud_drive_attachments.py`
  `test_runtime_engineer_can_decrypt_server_encrypted_but_not_e2ee`

What it proves:

- a runtime engineer can decrypt `server_encrypted` ciphertext with the runtime
  server key
- the same runtime key does not decrypt E2EE ciphertext
- E2EE runtime state contains only ciphertext plus wrapped key material

## Final Interpretation

`server_encrypted` protects against casual disk / backup exposure, but not
against the running server or an engineer with runtime secrets.

`e2ee` is the mode that protects plaintext confidentiality even if the server
filesystem and runtime state are exposed, because the decryptable secret remains
with the user/browser rather than the server.
