# Discord Attachment Policy

Attachments are high-risk because they can bypass site privacy, scanning, or
E2EE assumptions. V1 is link-only.

## V1: Link-only

Web attachment to Discord:

- post only a `hackme_web` file page link
- do not upload file bytes to Discord
- do not expose private direct storage paths
- do not export strict E2EE plaintext
- do not export server-encrypted plaintext as a Discord file

Discord attachment to web:

- do not auto-download binary content
- store only external attachment metadata or a review item
- show Discord CDN link only when policy allows
- do not treat CDN URL as passing `hackme_web` permission

## V2: Quarantine Import

Only after separate approval:

```text
Discord attachment
  -> download into quarantine
  -> size/type validation
  -> upload_security scan
  -> Cloud Drive external_import
  -> attach to forum/chat after permission check
```

V2 still forbids:

- auto-decrypting E2EE content
- exporting private storage bytes to Discord
- importing executable or blocked file types
- bypassing Cloud Drive ownership and visibility checks

## Audit

Attachment audit records must include hashes, metadata, decision, and reason.
They must not include private direct storage paths, secret-bearing URLs, or
plaintext E2EE content.
