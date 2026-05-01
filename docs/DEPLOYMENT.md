# Deployment And Operations Scripts

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
./deploy.sh --lite-hint
```

Generated runtime files remain local and must not be committed:

- `.env`
- `.fkey`
- `.csrfkey`
- `.chain_seed`
- `.integrity_key`
- `integrity_manifest.json`
- `cert.pem`
- `key.pem`
- database, logs, storage, chats, anchors, and reports

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

The script reports approximate requests per second, status distribution, and
latency percentiles. It is not a replacement for production-grade load testing,
but it gives a repeatable baseline for the current host. It refuses public
targets by default; use `--i-own-this-target` only for staging or systems you are
explicitly authorized to test. Concurrency is capped at `100`.

## Pre-push Validation

Run the project-level validation before publishing:

```bash
python3 scripts/pre_push_checks.py
```

The helper compiles Python under `server.py`, `routes/`, `services/`,
`security/`, `scripts/`, and `tests/`, checks that the Release ID appears in the
required docs, starts an isolated server, and runs the smoke suite.
