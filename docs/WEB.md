# WEB

`WEB.md` describes the user-facing web application. API details and deployment
defaults live in [For_developer.md](For_developer.md).

Before any production release, use
[security/PRE_RELEASE_CHECKLIST.md](security/PRE_RELEASE_CHECKLIST.md). The
checklist treats completed pentesting and completed full functional smoke
testing as blocking release requirements.

## UI Shell

After login, the app uses a full-viewport sidebar layout.

- The sidebar is flush with the browser's left edge.
- The middle menu area scrolls independently when there are too many modules.
- The footer stays fixed at the bottom and shows account information, points,
  violation deductions, effective permission level, server connection status,
  and release ID.
- The sidebar collapse state is saved in `localStorage`.
- Top-right compact icon buttons handle profile editing, notifications, bug
  reports, logout, and the idle logout countdown.

## Main Pages

### Chat

Users can create or join chat rooms, send messages, refresh room state, attach
cloud-drive files, and report inappropriate messages. Chat actions are still
checked against member-level permissions.

### Direct Messages

The DM page provides one-to-one station-mail style messaging, unread tracking,
message soft-delete, and user blocking.

### Announcements

Announcements are separated from the forum page. Authorized users can publish
announcements, pin important items, and submit attachment requests that require
root review.

### Forum

The forum is board-first:

- users enter a board list first
- then open a board to see thread lists
- then open a thread to read posts and replies

The default community model includes board categories, board requests, board
review, thread review, reactions, pinned/locked threads, and moderation tools
for board maintainers.

### Cloud Drive

Cloud Drive supports:

- local uploads with visible progress
- privacy-mode selection with human-readable labels
- quota and scan-policy status
- image, media, PDF, text, and archive previews when policy allows
- text-file editing for safe owner-owned text files
- file delete and download actions
- logical folders, move/organize flow, trash, restore, and purge
- album creation and album viewing
- share links for storage files

Remote downloads are integrated into Cloud Drive:

- HTTP/HTTPS direct links
- magnet links
- uploaded `.torrent` files

BT/magnet/`.torrent` downloads require `aria2c` on the server. Downloaded files
are saved through the same quota, scan, privacy-mode, and logical-folder
pipeline as normal uploads.

### Albums

Albums have their own page for gallery-style browsing. Albums are backed by the
storage file manager and do not duplicate physical cloud-drive files.

### ComfyUI

The AI image page checks whether the configured ComfyUI API is reachable. If the
service is unavailable, the page is disabled. Users can select a model, enter a
prompt and generation parameters, generate an image, then either save it into
Cloud Drive or discard it.

Root can change the ComfyUI API port from server settings.

Non-root accounts are charged points after ComfyUI successfully returns images.
Failed generations are not charged. Discarding a successful preview does not
refund the generation cost.

### Web Terminal

Web Terminal is an optional root-only page. It starts a restricted Linux
container instead of a host shell, mounts only root's existing Cloud Drive
storage into `/home/root`, and removes the container when the session closes or
times out. Install and verify the optional host dependencies with:

```bash
./install_web_terminal_dependencies.sh --doctor --venv .venv
./install_web_terminal_dependencies.sh --all --venv .venv
```

The installer builds the required `hackme-web-terminal:base` Docker image and
prints concrete repair commands when Docker permissions require a new login
shell or service restart.

Root can switch the terminal network mode in server settings:

- `none`: offline container
- `bridge`: full standard Docker internet access, current default
- `host`: host network namespace, highest risk

Root can also switch the terminal Ubuntu distribution in server settings:

- `ubuntu-24.04`: `hackme-web-terminal:ubuntu-24.04`, current default
- `ubuntu-22.04`: `hackme-web-terminal:ubuntu-22.04`

### Appeals

Users can view violation history and submit appeals. Root/manager review is
handled from the management pages.

### Account Management

Managers and root can review users, approve registrations, manage roles, inspect
violations, review appeals/reports, and handle governance workflows according to
their authority.

### Security Center

Root-facing security and operations pages are grouped under Security Center:

- security overview
- audit log
- server log
- health checks
- integrity guard; pending warnings are visible for 24 hours, then auto-approved
- server modes
- access controls
- security mechanism toggles
- threshold management
- custom security profiles
- snapshot / restore / reset controls
- system environment summary

## Account and Permission Model

Roles:

- `super_admin`: full control plane
- `manager`: operational moderation and user review
- `user`: normal application use

Member levels:

- `newbie`
- `normal`
- `trusted`
- `vip`
- `restricted`
- `suspended`

`root` and bootstrap admin-style accounts are special operational accounts and
are not treated like ordinary user-level accounts.

## Runtime Files

The web app creates runtime data on first boot. These files are intentionally not
tracked by git:

- SQLite database
- logs
- chat transcripts
- upload/storage files
- generated keys
- integrity manifest
- bug reports
- local security reports

For clean deployments, clone the repository, install dependencies, and run
`scripts/run_prod.sh`. On first deployment it opens a setup wizard for bootstrap
passwords, runtime paths, HTTPS policy, and Gunicorn settings.
