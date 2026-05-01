# Server Security Modes

This document records the built-in security mode defaults. Root may create a
custom profile from the Security Center. Built-in profiles are not overwritten:
if root changes the details of a built-in mode, the UI asks to save those values
as a custom profile and then switches the server mode to that custom profile.

`superweak` is intentionally unsafe. It exists only for controlled local testing:
entering it creates a `before_superweak` snapshot, disables the major protection
mechanisms below, and requires `ENABLE_SUPERWEAK`.

| Mechanism | production | preprod | internal_test | test | superweak |
|---|---:|---:|---:|---:|---:|
| HTTPS setting | on | on | on | on | off |
| Audit hash chain | on | on | on | on | off |
| Audit log UI/API | on | on | on | on | off |
| Integrity Guard scan | on | on | on | on | off |
| Integrity Guard strict mode | on | on | on | off | off |
| Failed-login IP blocking | on | on | on | on | off |
| Failed-login violation records | on | on | on | on | off |
| Rate-limit violation records | on | on | on | on | off |
| Browser-only request filter | on | on | on | off | off |
| Root IP whitelist enforcement | off by default | off by default | off by default | off by default | off |
| PointsChain / economy APIs | on | on | on | on | off |
| Captcha | math | unchanged | unchanged | unchanged | none |
| Open registration | off | unchanged | off | unchanged | unchanged |

Notes:

- `production` also applies production hardening: test accounts are disabled,
  default accounts must reset passwords, and strict upload scanning policy is
  enabled.
- `internal_test` revokes non-root sessions and requires an internal-test token
  for non-root users.
- `test` keeps audit, IP lock, and Integrity Guard enabled but does not block
  startup on Integrity Guard strict findings.
- `superweak` does not delete existing ledger or audit data; it disables the
  runtime gates and APIs so weak-mode testing does not continue sealing or
  exposing those control surfaces.
