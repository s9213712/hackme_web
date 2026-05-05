# Deployment And Operations Scripts

This file is the script-level reference. New deployers should start with
[01_DEPLOY_QUICKSTART.md](01_DEPLOY_QUICKSTART.md) and
[02_DEPLOY_PRODUCTION.md](02_DEPLOY_PRODUCTION.md), then come back here when
they need exact command modes and script flags.

## One-Command Deployment

Use the root helper:

```bash
./deploy.sh
```

On first run it creates `.venv`, installs `requirements.txt`, delegates the
interactive production setup wizard to `scripts/run_prod.sh`, initializes the
database, and starts Gunicorn.

Useful modes:

```bash
./deploy.sh --check-only
./deploy.sh --init-db-only
./deploy.sh --with-comfyui http://127.0.0.1:8192
./deploy.sh --with-turnstile '<TURNSTILE_SECRET_KEY>'
./deploy.sh --with-civitai-key '<CIVITAI_API_KEY>'
./deploy.sh --lite-hint
./deploy.sh --check-only --skip-install
```

`--skip-install` 適合已經有可用 `.venv`、但當前環境不想每次重新碰 pip 網路的情境。
單獨執行 `./deploy.sh --lite-hint` 時，現在只會輸出低配部署建議，不會先建立 `.venv`。
`--with-civitai-key` 只會把 root-only Civitai 搜尋/下載所需的 `CIVITAI_API_KEY`
寫進 `.env`；沒有這個 key，ComfyUI 本地模型上傳仍可用，只是無法直接搜尋/下載
Civitai 模型。

Generated runtime files remain local and must not be committed:

- `.env`
- `runtime/.fkey`
- `runtime/.filekey`
- `runtime/.csrfkey`
- `runtime/.chain_seed`
- `runtime/.integrity_key`
- `runtime/integrity_manifest.json`
- `runtime/cert.pem`
- `runtime/key.pem`
- `runtime/database/`, `runtime/logs/`, `runtime/storage/`, `runtime/chats/`,
  `runtime/anchors/`, and `runtime/reports/`

## Capability Checks

`scripts/run_prod.sh --check` 現在除了檢查必填 env 與 runtime 目錄，也會額外提示：

- `ffmpeg` / `ffprobe` 是否存在
  - 影響影音平台的 HLS 衍生檔與 metadata probe
- `CIVITAI_API_KEY` 是否存在
  - 影響 root-only Civitai 搜尋 / 下載
- `scripts/root_recovery.py`
  - root 忘記密碼時的正式 offline 補救入口

這些能力提示屬於**可選擴充檢查**，不會阻擋一般部署。

## Functional Smoke

Run:

```bash
security/run_functional_smoke.sh
```

It starts an isolated temporary server, tests core features, verifies
snapshot/restore/reset behavior, checks TLS file generation, and writes reports
under `security/reports`.

## Functional Permission Pentest

Run:

```bash
security/run_pentest.sh --target http://127.0.0.1:5000 --only functional-permissions
```

It logs in as root, manager, normal user, and anonymous clients to verify
allowed actions, blocked actions, high-risk confirmation/CSRF guards, JSON error
format, and no 500/502/503 regressions.

## Stress Test

Run a lightweight local traffic estimate:

```bash
security/stress_test.py --target http://127.0.0.1:5000 --requests 500 --concurrency 50
```

Run a short duration-based flood simulation against a loopback server you own:

```bash
python3 security/stress_test.py \
  --target http://127.0.0.1:5000 \
  --mode duration \
  --duration-seconds 20 \
  --max-requests 4000 \
  --concurrency 80 \
  --burst-size 10 \
  --burst-interval-ms 200
```

The script reports approximate requests per second, status distribution, and
latency percentiles. It is not a replacement for production-grade load testing,
but it gives a repeatable baseline for the current host. It refuses public
targets by default; use `--i-own-this-target` only for staging or systems you are
explicitly authorized to test. Concurrency is capped at `100`, and duration mode
still honors a safety `--max-requests` cap.

## Pre-push Validation

Run the project-level validation before publishing:

```bash
python3 scripts/pre_push_checks.py
```

The helper compiles Python under `server.py`, `routes/`, `services/`,
`security/`, `scripts/`, and `tests/`, checks that the Release ID appears in the
required docs, rejects tracked runtime artifacts and local workstation paths,
runs config/CI safety checks, runs `git diff --check`, runs the plaintext secret
scanner, runs `gitleaks` and `node --check` when those tools are installed, and
runs a focused pytest set. The default mode is fast and does not start the
server. Use `--full` when you need the isolated `/tmp` server smoke, API
contract, snapshot/restore, Server Mode, PointsChain, and log-chain checks.

`--ci` is a non-interactive/sanitized execution mode; it does not automatically
enable heavyweight checks. Optional cleanup flags list their deletion plan first
and require confirmation unless `--yes` is used:

```bash
python3 scripts/pre_push_checks.py --clean --clean-temp --yes
```

- `--clean`: remove safe repository caches such as `__pycache__`,
  `.pytest_cache`, `.mypy_cache`, `.ruff_cache`, `.coverage`, `htmlcov`,
  `dist`, `build`, `*.pyc`, and `*.pyo`. It never removes user/runtime data,
  reports, key files, `.gitkeep`, or tracked files unless they are explicit
  cache artifacts.
- `--clean-temp`: remove old `/tmp/html_learning_prepush_*` and
  `/tmp/html_learning_secrets_*` directories, keeping the newest two by
  default.
- `--keep-temp`: keep this run's isolated runtime even in `--ci` success.
- `--yes`: skip cleanup confirmation.

Install the hook with:

```bash
bash hooks/install-hooks.sh
```

The hook bumps `APP_RELEASE_ID`, amends the current commit, runs
`scripts/pre_push_checks.py --ci`, and blocks the push on failure.
