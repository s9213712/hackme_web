# WEB

`WEB.md` describes the user-facing web application. API details and deployment
defaults live in [For_developer.md](For_developer.md).

If you are onboarding a deployer or an end user, start with
[04_USER_GUIDE.md](04_USER_GUIDE.md) and
[05_FEATURES_OVERVIEW.md](05_FEATURES_OVERVIEW.md) first. This file is the
page-by-page deep reference.

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

Privacy / encryption modes are deliberately explicit because not every mode is
end-to-end encrypted:

| Mode | Best for | Server can read plaintext | Scan / preview | Main risk |
|---|---|---:|---|---|
| `standard_plain` | Normal files, attachments, album display, shared files | Yes | Best scan/preview/share compatibility | Stored as plaintext on the server filesystem |
| `server_encrypted` | Reducing disk/backup exposure while keeping server features | Yes, by temporary server-side decrypt | Server decrypts for scan, preview, and plaintext download | Not E2EE; server/root can decrypt |
| `e2ee` | Highly private storage | No | Browser-side decrypt preview after the user enters the E2EE password; server can only inspect ciphertext/metadata | Losing the user-chosen E2EE file password makes the file unrecoverable |

Use `standard_plain` when users need normal cloud-drive behavior. Use
`server_encrypted` when protecting at-rest storage is useful but server-side
scan/preview/download support is still required. Use E2EE when confidentiality
is more important than server-side scanning and recovery support. E2EE files can
still be previewed by the browser after the user enters the file password.
For the runtime trust boundary between `server_encrypted` and strict `e2ee`,
see [ENCRYPTION_RUNTIME_BOUNDARY.md](ENCRYPTION_RUNTIME_BOUNDARY.md).

E2EE uses a user-entered file encryption password in the browser. The browser
derives a wrapping key with PBKDF2-SHA256 and uses it to encrypt the per-file
key before upload. The server stores only ciphertext, encrypted metadata, salt,
nonce, and the wrapped file key; it does not receive the plaintext password or a
decryptable master key. A user can decrypt on another computer by entering the
same E2EE password, but the server cannot reset or recover forgotten E2EE
passwords. During preview, the password is cached only in browser memory for
the current logged-in page session and is cleared on logout or browser close.

Remote downloads are integrated into Cloud Drive:

- HTTP/HTTPS direct links
- magnet links
- uploaded `.torrent` files

BT/magnet/`.torrent` downloads require `aria2c` on the server. Downloaded files
are saved through the same quota, scan, privacy-mode, and logical-folder
pipeline as normal uploads.

Root can configure per-member-level Cloud Drive transfer controls under
`伺服器設定 -> 雲端硬碟 -> 階級傳輸限速`:

- upload speed in KB/s
- download speed in KB/s
- priority from 0 to 100

`0` disables that transfer direction for the level. Root is not throttled.
Download throttling is applied while streaming files from Flask. Upload
throttling is an application-layer admission delay because the HTTP request body
has already reached Flask by the time route code runs; for strict network-layer
upload QoS, deploy an nginx or reverse-proxy limit in front of the app.

### Albums

Albums have their own page for gallery-style browsing. Albums are backed by the
storage file manager and do not duplicate physical cloud-drive files.

Set album visibility to `不列出，持連結可看` to generate an album share URL.
Open the album detail or preview panel and use the `複製` button next to
`持連結可看` to copy the URL for another person. Album share links can also
have an optional password; the password is stored as a hash and must be shared
out of band with the recipient.

### Video Platform

The `影音` page publishes videos already stored in Cloud Drive. It does not
upload to a separate filesystem.

The current page behavior described here is still Video Platform v1. The formal
future HLS / segmented streaming design for large media is documented in
[VIDEO_STREAMING_ARCHITECTURE.md](VIDEO_STREAMING_ARCHITECTURE.md).

- owner selects one of their own Cloud Drive video files
- visibility can be public, unlisted, or private
- playback uses `/api/videos/<id>/stream`, not a raw storage path
- users can like, comment, and tip
- tips are recorded through PointsChain

E2EE files are intentionally not publishable as normal server-streamed / HLS
videos because the server cannot safely preview or stream plaintext without
receiving decryptable material. They can, however, be published as `持連結可看`
shared videos: the owner enters the original E2EE password once at publish
time, the browser unwraps the file key locally, and the browser re-wraps that
file key into a share envelope that still keeps the server blind to the raw key
and original password. For normal web-player HLS, use `standard_plain` or
`server_encrypted`.

If a `server_encrypted` file was written with an older server file key that is
no longer available, the video page now fails safely: the cover endpoint shows
an explanatory placeholder and stream/content endpoints return a structured
`decrypt_unavailable` error instead of a generic server error.
The strict E2EE publish/share boundary is also documented in
[ENCRYPTION_RUNTIME_BOUNDARY.md](ENCRYPTION_RUNTIME_BOUNDARY.md).

### ComfyUI

The AI image page checks whether the configured ComfyUI API is reachable. Users
can select a model, VAE, LoRA entries, prompts, and generation parameters, then
save the generated image into Cloud Drive, share it to the ComfyUI forum board,
or discard the preview. Generation now runs through an async job path so the
page can keep showing queue/node progress until the image is complete. The page
also shows the current mode explicitly (`local` vs `remote / cloud API`) so
users do not need to infer it from start/stop buttons. The mode is shown both
as a badge and as a short explanation line near the panel title.
The default generation wait budget is now 30 minutes on both the frontend
progress poll and the backend route, so large models or slow local GPUs do not
fail early just because the UI timeout was shorter than the actual job.

Root can configure ComfyUI in two modes from server settings:

- Remote mode: set a full API URL such as `http://127.0.0.1:8192`. Discarding a
  preview only clears the web preview because a remote ComfyUI API does not offer
  a safe file-delete endpoint. In this mode the root-only Civitai API key field
  and model-download tools are hidden because the server cannot download models
  into a remote ComfyUI host through the normal API.
- Local mode: set a local ComfyUI folder and startup script. The image page shows
  a `Start ComfyUI` button; the server only runs the startup script when a user
  presses that button. If another user already started the shared ComfyUI backend,
  later users can use it directly. Root also sees a `Stop ComfyUI` button when
  the shared local process is already available.
- In the root settings page, token-like fields are now mode-aware: the
  `Turnstile site key` only appears when CAPTCHA mode is `turnstile`, and the
  `Civitai API Key` only appears when ComfyUI is in local mode.
- The AI page keeps the main ComfyUI generation form focused on generation
  only. Root's Civitai model-download tools now live in a separate collapsed
  panel at the bottom of the page so downloading models does not crowd the
  generation controls.
- Each selected LoRA now exposes separate `Model` and `CLIP` strength fields in
  the page. The frontend stores those values in the local draft, and the
  backend still re-validates them into the allowed range before they reach the
  ComfyUI workflow. If that LoRA was downloaded through the root Civitai panel
  and its official `trainedWords` were recorded, adding the LoRA will also
  auto-append any missing trigger words into the positive prompt. The current
  UI only allows LoRAs whose recorded `base_model` is one of `SDXL`, `Pony`,
  `Illustrious`, or `Noob`; `SD1.5`, `Flux`, and unknown-metadata LoRAs are
  rendered as unavailable and the backend rejects direct requests too. Removing
  a selected LoRA now also removes its trigger words unless another selected
  LoRA still needs the same term; selecting `不使用 LoRA` and pressing `加入`
  clears the selected LoRA list.
- The page also exposes a VAE selector. Keeping `use checkpoint builtin VAE`
  uses the model's bundled VAE; selecting another VAE inserts a `VAELoader`
  node into the generated workflow.
- Available Embeddings are loaded from the ComfyUI API and rendered as clickable
  shortcut buttons. Clicking one inserts `<embeddings:name>` into the positive
  prompt; the backend translates that shortcut into ComfyUI's actual embedding
  prompt syntax before queueing the workflow. Clicking the same Embedding again
  removes it. If the Embedding name contains `neg` / `negative`, the shortcut
  targets the negative prompt by default.
- While a long ComfyUI task is running, the frontend idle auto-logout countdown
  is paused so the session does not expire mid-task. That currently includes
  local startup polling, async generation, and root's local-model download job.

The reference Linux/WSL startup script template is
`scripts/comfyui_run_in_linux.template.sh`. Copy it into a ComfyUI portable
folder as `run_in_linux.sh`, then set that folder and script name in root
settings. Do not document or commit workstation-specific absolute paths; use
deployment-local paths such as `/opt/comfyui-portable` in examples. The script
reuses an existing virtual environment when available, creates one only if
needed, installs dependencies with `--install-only`, and supports `--doctor` for
environment checks.

ComfyUI model downloads are root-only. Checkpoints are saved under
`ComfyUI/models/checkpoints`, and LoRA files are saved under
`ComfyUI/models/loras` inside the configured local ComfyUI project. The same
panel can also download Embedding and VAE files into the matching local ComfyUI
model folders. ControlNet and Hypernetwork downloads are intentionally not
offered in this UI because the current generation form does not expose matching
runtime controls. Local mode can delete generated output files when a user
discards a preview; ownership is checked so users can only save or delete their
own generated image references. Root can paste a Civitai page URL, inspect
model versions/files, see the version's official `trainedWords` / trigger
words, and download a selected checkpoint, LoRA, Embedding, or VAE into the
configured local project from that bottom collapsed panel; when a LoRA is
downloaded this way, the server stores a small sidecar metadata file next to
that LoRA so future page loads can auto-insert the same trigger words when the
LoRA is selected again. An optional Civitai API key can be stored in server
settings for authenticated downloads.
Interrupt requests are guarded because ComfyUI interrupt is global: normal users
only interrupt the backend when no other user's generation is active, while root
can force a global interrupt.

### Appeals

Users can view violation history and submit appeals. The same page also shows
appealable member-governance notices such as role/status/points-rights changes.
Root/manager review is handled from the management pages.

### Account Management

Managers and root can review users, approve registrations, manage roles, inspect
violations, review appeals/reports, and handle governance workflows according to
their authority. Rejecting a pending registration removes that application
account entirely. Deleting an existing account is a soft-delete: the account is
hidden from default admin lists, access is revoked, attached storage is trashed,
and authenticated users can open `我的資料` to keep a personal appearance
override without changing the root-managed global default theme. That personal
override now covers font family, background style, panel style, sidebar width,
colors, layout, density, radius, font scale, and content width. Root still owns
the global default theme, and can separately decide whether personal appearance
overrides are allowed at all.
but audit/trading/comment history remains preserved for review. Member-rights
changes send a governance notice to the affected user and link to Appeals when
the action is appealable.

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

The Economy branch includes a first-stage spot exchange. The UI displays
`BTC/USDT`, `ETH/USDT`, `XRP/USDT`, `BNB/USDT`, and `PAXG/USDT`; the internal
API symbols remain `BTC/POINTS`, `ETH/POINTS`, `XRP/POINTS`, `BNB/POINTS`, and
`PAXG/POINTS`. Spot trading is open to normal users and root. Normal-user
settlement uses the local PointsChain ledger, while root spot settlement uses a
separate simulated trading balance. POINTS are treated as USDT-equivalent in the
trading UI (`1 POINT = 1 USDT`) so market prices match the public quote unit.
BTC/ETH spot execution uses backend public live prices. The provider fallback
chain is Binance, OKX, Coinbase Exchange, Kraken, Gemini, Bitstamp, CoinGecko,
then last-good cache within the configured staleness window. The backend applies
the market jump threshold after live history exists and fails closed when no
fresh or trusted cached price is available.

The exchange page also shows public candlestick charts for supported display
markets such as BTC/USDT, ETH/USDT, XRP/USDT, BNB/USDT, and PAXG/USDT. The
chart provider chain is Binance, OKX, Coinbase Exchange, Kraken, Gemini, then
Bitstamp. The default timeframe is 15 minutes, with 1-hour, 4-hour, and daily
options available. The chart is also used by the frontend to refresh
the displayed current price; the backend still fetches its own price again
before execution:

- `BTC/POINTS` maps to public BTC/USDT or BTC/USD provider symbols.
- `ETH/POINTS` maps to public ETH/USDT or ETH/USD provider symbols.
- `XRP/POINTS` maps to public XRP/USDT or XRP/USD provider symbols.
- `BNB/POINTS` maps to public BNB/USDT provider symbols where available.
- `PAXG/POINTS` maps to public PAXG/USDT provider symbols where available.
- The fixed display conversion is `1 POINT = 1 USDT`.
- If public providers are unavailable, live-price execution can temporarily use
  the recent last-good price within the configured staleness window. After that
  it fails closed with a clear error.
- A future weighted-price mode should aggregate multiple fresh providers,
  discard stale/outlier prices, and halt trading when provider agreement is too
  weak. That is the intended extreme-market protection path beyond simple
  priority fallback.
- Open limit orders are scanned by the trading maintenance worker and are
  filled when the current execution price reaches the limit.
- Spot trading bots are owned by the user. The exchange page separates DCA bots,
  grid bots, workflow strategy bots, backtest analysis, and execution records.
  DCA bots convert a fixed POINTS budget into a market buy quantity at scan
  time, and exhausted DCA/workflow bots can add more `max_runs` directly from
  the trading page. Grid bots place multiple buy/sell levels inside a configured
  range and can prompt the user to buy missing spot inventory before creation.
  Strategy bots use readable workflow JSON generated by the standalone
  `/trading-workflow-editor.html` page. The workflow editor is node graph based:
  it stores `nodes` and `edges`, validates input/output ports, supports
  TRUE/FALSE branches, nested AND/OR/NOT logic nodes, cooldown/control nodes,
  branch priority, and sequential action steps. Backtests use the same DCA,
  grid, or workflow configuration and never place orders or mutate ledger
  state. Bot execution is manually scanned from the exchange page in this
  version to avoid unattended runaway trading.
- Spot positions expose backend-calculated cost basis, current value,
  unrealized PnL, realized PnL, and cumulative fees. Cost basis includes the
  remaining spot cost, an estimated entry fee, and the estimated exit fee at the
  current market price. Realized PnL is recorded on each sell fill and is
  replay-verified by the trading state checker.
- See [Trading System And Bots](TRADING.md) for the full trading, bot,
  workflow editor, backtest, and validation guide.

When `root` enables BTC_trade in trading settings, the BTC market can also show
a BTC-only signal panel. The feature is disabled by default. On enable, the
server can clone/update the configured GitHub branch and run BTC_trade setup
steps; any failure only hides the panel and shows a root warning. The panel
understands the newer BTC_trade runtime report fields, including strategy
version, fear/greed, portfolio equity, PnL, report text, and next prediction
countdown. The optional bridge script is owned by this project at
`scripts/btc_signal_bridge.py`.

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
  records margin collateral freezes in PointsChain, shows account-level
  cross-margin equity/maintenance/free-margin status, scans for liquidation,
  and verifies collateral locks during trading state checks. Individual rows
  still show a per-position estimated liquidation price, but actual forced
  liquidation is based on whole-account maintenance.

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
