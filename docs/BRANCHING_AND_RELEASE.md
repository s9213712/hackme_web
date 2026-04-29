# Branching and Release Policy

## Branch Numbering

Feature branches use a two-digit order prefix:

```text
01-feature-name
02-next-feature
03-sidebar
04-economy
```

Rules:

- `main` stays unprefixed because it is the default integration branch.
- Number prefixes represent branch creation / project sequence order, not
  priority.
- Use the next unused number when starting a new feature branch.
- Keep names lowercase and use hyphens after the numeric prefix.
- If a branch already exists without a prefix, rename it before pushing new
  work from that branch.

Current sequence:

```text
01-feature-new-development
02-feature-forum-governance-security-modes
03-sidebar
04-economy
```

## Release ID Rule

The server release ID lives in:

```text
services/release_info.py
```

When a change adds or changes a user-facing production feature, increment the
last numeric segment by 1 before release.

Example:

```text
2026.04.29-016 -> 2026.04.29-017
```

Also update visible documentation references:

- `README.md`
- `docs/README.zh-TW.md`
- `docs/For_developer.md`

Bug fixes that only repair a broken implementation may keep the same release ID
until the next production-facing feature release, unless the fix itself is being
published as a distinct server build.
