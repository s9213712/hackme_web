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

Set album visibility to `不列出，持連結可看` to generate an album share URL.
Open the album detail or preview panel and use the `複製` button next to
`持連結可看` to copy the URL for another person. Album share links can also
have an optional password; the password is stored as a hash and must be shared
out of band with the recipient.

### ComfyUI

The AI image page checks whether the configured ComfyUI API is reachable. If the
service is unavailable, the page is disabled. Users can select a model, enter a
prompt and generation parameters, generate an image, then either save it into
Cloud Drive or discard it.

Root can change the ComfyUI API host/IP and port from server settings. Enter
only the host name or IP in the host field, for example `localhost` or
`192.168.1.20`; do not include `http://`, paths, query strings, or credentials.

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
- server health dashboard with grouped service status, work queue, storage,
  readiness/anomaly, and audit-chain findings
- integrity guard; pending warnings are visible for 24 hours, then auto-approved
- server modes
- access controls
- security mechanism toggles
- threshold management
- custom security profiles
- snapshot / restore / reset controls
- system environment summary

The PointsChain operations panel includes a root-only one-click abnormal-chain
handler. It is intended for safe-mode recovery: the button verifies the chain,
uses the prepared healthy backup only when available, rebuilds wallets from the
ledger, and reports manual-required when no trusted backup exists.

### Points Exchange

The Economy branch includes a first-stage spot exchange for `BTC/POINTS` and
`ETH/POINTS`. Spot trading is open to normal users and root. Normal-user
settlement uses the local PointsChain ledger, while root spot settlement uses a
separate simulated trading balance. POINTS are treated as USDT-equivalent in the
trading UI (`1 POINT = 1 USDT`) so market prices match the public quote unit.
BTC/ETH spot execution can use either the backend live Binance public price or
root manual prices, depending on the root trading settings. The default source
is Binance public API. If the live source is enabled, the backend keeps a
last-good price cache, applies the market jump threshold after live history
exists, and fails closed when the price feed is unavailable beyond the allowed
staleness window.

The exchange page also shows a Binance public API candlestick chart for BTC/USDT
and ETH/USDT. The default timeframe is daily, with 15-minute, 1-hour, and
4-hour options available. The chart is also used by the frontend to refresh the
displayed current price; the backend still fetches its own price again before
execution:

- `BTC/POINTS` maps to Binance `BTCUSDT`.
- `ETH/POINTS` maps to Binance `ETHUSDT`.
- The fixed display conversion is `1 POINT = 1 USDT`.
- If Binance is unavailable, live-price execution can temporarily use the
  recent last-good price within the configured staleness window. After that it
  fails closed with a clear error.
- Open limit orders are scanned by the trading maintenance worker and are
  filled when the current execution price reaches the limit.
- Spot positions expose backend-calculated cost basis, current value,
  unrealized PnL, realized PnL, and cumulative fees. Cost basis includes the
  remaining spot cost, an estimated entry fee, and the estimated exit fee at the
  current market price. Realized PnL is recorded on each sell fill and is
  replay-verified by the trading state checker.

Trading funds are separated by account type:

- Normal users trade with the POINTS they actually own in their PointsChain
  wallet.
- `root` can use spot and contract simulation with a separate simulated trading
  balance. It starts at 10000 POINTS and does not write to PointsChain or mutate
  the root account wallet.
- Root can reset this simulated trading balance back to 10000 POINTS from the
  exchange control panel.
- Contract/futures functionality is root-only at this stage. Root can open and
  close simulated long/short positions; non-root users can only use spot.
- Borrow trading is experimental and root-controlled. When enabled, the server
  records margin collateral freezes in PointsChain, scans for liquidation, and
  verifies collateral locks during trading state checks.

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
- local TLS certificate/key files
- integrity manifest
- bug reports
- local security reports

For clean deployments, clone the repository, install dependencies, and run
`scripts/run_prod.sh`. On first deployment it opens a setup wizard for bootstrap
passwords, runtime paths, HTTPS policy, and Gunicorn settings.
