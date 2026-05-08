# Deployment And Operations Scripts

This file is the script-level reference. New deployers should start with
[01_DEPLOY_QUICKSTART.md](01_DEPLOY_QUICKSTART.md) and
[02_DEPLOY_PRODUCTION.md](02_DEPLOY_PRODUCTION.md), then come back here when
they need exact command modes and script flags. For the canonical dependency
matrix, see [SYSTEM_DEPENDENCIES.md](SYSTEM_DEPENDENCIES.md).

## Direct Deployment

正式部署改成直接走 `server.py`：

```bash
python3 server.py --doctor
python3 server.py
```

`--doctor` 會先檢查 runtime 目錄是否存在且可寫；若環境缺失，會直接報錯，不會靜默幫你補建。
如果你只是要本機開發，不要走這條，改用 repo root `./test_for_develop.sh`。

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

`python3 server.py --doctor` 主要檢查的是 runtime 目錄是否完整可用；影音與第三方能力則仍需部署者自行確認：

- `ffmpeg` / `ffprobe` 是否存在
  - 影響影音平台的 HLS 衍生檔與 metadata probe
- `CIVITAI_API_KEY` 是否存在
  - 影響 root-only Civitai 搜尋 / 下載
- `scripts/admin/root_recovery.py`
  - root 忘記密碼時的正式 offline 補救入口

這些能力提示屬於**可選擴充檢查**，不會阻擋一般部署。
更完整的 system binary / external service 清單請看
[SYSTEM_DEPENDENCIES.md](SYSTEM_DEPENDENCIES.md)。

## Functional Smoke

Run:

```bash
scripts/security/pentest/run_functional_smoke.sh
```

It starts an isolated temporary server, tests core features, verifies
snapshot/restore/reset behavior, checks TLS file generation, and writes reports
under `runtime/reports/security`.

## Functional Permission Pentest

Run:

```bash
scripts/security/pentest/run_pentest.sh --target http://127.0.0.1:5000 --only functional-permissions
```

It logs in as root, manager, normal user, and anonymous clients to verify
allowed actions, blocked actions, high-risk confirmation/CSRF guards, JSON error
format, and no 500/502/503 regressions.

## Stress Test

Run a lightweight local traffic estimate:

```bash
scripts/security/pentest/stress_test.py --target http://127.0.0.1:5000 --requests 500 --concurrency 50
```

Run a short duration-based flood simulation against a loopback server you own:

```bash
python3 scripts/security/pentest/stress_test.py \
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
python3 scripts/prepush/pre_push_checks.py
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
python3 scripts/prepush/pre_push_checks.py --clean --clean-temp --yes
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
`scripts/prepush/pre_push_checks.py --ci`, and blocks the push on failure.
