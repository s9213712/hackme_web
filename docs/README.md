# Documentation Map

Use this file as the canonical doc index. Entry docs should point back here
instead of repeating deep feature narratives.

The repository root keeps only [README.md](../README.md) and
[SECURITY.md](../SECURITY.md). Everything else lives here.

## First Route

- [00_START_HERE.md](00_START_HERE.md): role-based reading order
- [01_DEPLOY_QUICKSTART.md](01_DEPLOY_QUICKSTART.md): shortest path to a
  working local or staging deployment
- [02_DEPLOY_PRODUCTION.md](02_DEPLOY_PRODUCTION.md): production hardening,
  reverse proxy, backups, and release gate expectations
- [SYSTEM_DEPENDENCIES.md](SYSTEM_DEPENDENCIES.md): canonical Python packages,
  system binaries, optional feature tools, and external integration checklist

## Role Guides

- [03_ADMIN_GUIDE.md](03_ADMIN_GUIDE.md): root/admin operations and feature
  combinations
- [04_USER_GUIDE.md](04_USER_GUIDE.md): end-user workflow guide
- [05_FEATURES_OVERVIEW.md](05_FEATURES_OVERVIEW.md): all major modules,
  dependencies, failure hints, and test routes

## Core Systems

- [06_SECURITY_MODEL.md](06_SECURITY_MODEL.md): security layers and boundaries
- [07_POINTSCHAIN.md](07_POINTSCHAIN.md): ledger, recovery, and economy trust model
- [08_TRADING_ENGINE.md](08_TRADING_ENGINE.md): trading scope, dependencies,
  limits, and validation path
- [09_SNAPSHOT_RESET_RESTORE.md](09_SNAPSHOT_RESET_RESTORE.md): restore/reset
  boundaries and recovery workflow

## QA And Support

- [11_QA_TESTING.md](11_QA_TESTING.md): test-layer map, script relationships,
  and operator-facing validation route
- [security/QA_ARCHITECTURE.md](security/QA_ARCHITECTURE.md): QA/security
  tooling governance, validation vocabulary, production-gate script contract,
  and functional-smoke phase catalog
- [12_TROUBLESHOOTING.md](12_TROUBLESHOOTING.md): common errors and first-pass diagnosis

## Deep Reference

- [API_REFERENCE.md](API_REFERENCE.md): canonical implemented API route map
- [CLI_ADMIN_PLAYBOOK.md](CLI_ADMIN_PLAYBOOK.md): curl/cmd playbook for root,
  admin, and developer operations
- [For_developer.md](For_developer.md): API, schema, runtime layout, feature flags
- [architecture/DATABASE_LAYOUT.md](architecture/DATABASE_LAYOUT.md): current DB split, hot-path isolation, and next split candidates
- [EXTERNAL_API_COMMAND_MATRIX.md](EXTERNAL_API_COMMAND_MATRIX.md): current
  exchange / Civitai / ComfyUI upstream command inventory
- [WEB.md](WEB.md): detailed page-by-page UI behavior
- [DEPLOYMENT.md](DEPLOYMENT.md): script-level deployment and operations reference
- [SECURITY.md](SECURITY.md): current security controls and known limits
- [games/chess_model_files.md](games/chess_model_files.md): chess experiment model file formats and import compatibility
- [games/chess_training_pipeline.md](games/chess_training_pipeline.md): chess replay collection, dataset prep, offline training, benchmark, and promotion flow

### Trading Reference Set

- [trading/README.md](trading/README.md): trading docs index
- [TRADING.md](trading/TRADING.md): full trading, bots, workflow editor, and backtest details
- [TRADING_BOT_AUDIT.md](trading/TRADING_BOT_AUDIT.md): bot audit workflow and operator meaning
- [TRADING_RISK_PRICE.md](trading/TRADING_RISK_PRICE.md): reference vs risk-grade price rules
- [BACKTEST_CAPACITY_AND_TEMPLATE_BENCHMARKS.md](trading/BACKTEST_CAPACITY_AND_TEMPLATE_BENCHMARKS.md): trading backtest cap measurement and benchmark asset notes
- [BTC_TRADE_INTEGRATION.md](trading/BTC_TRADE_INTEGRATION.md): external BTC_trade repo integration and operator flow

### Video And Encryption Reference Set

- [video/README.md](video/README.md): video docs index
- [VIDEO_PLATFORM.md](video/VIDEO_PLATFORM.md): detailed video module reference
- [VIDEO_STREAMING_ARCHITECTURE.md](video/VIDEO_STREAMING_ARCHITECTURE.md): formal
  HLS / encrypted-media streaming Phase C design
- [ops_boundaries/README.md](ops_boundaries/README.md): runtime boundary docs index
- [ENCRYPTION_RUNTIME_BOUNDARY.md](ops_boundaries/ENCRYPTION_RUNTIME_BOUNDARY.md): what a
  runtime engineer can decrypt vs what strict E2EE still protects
- [RUNTIME_RESET_AND_RECOVERY.md](ops_boundaries/RUNTIME_RESET_AND_RECOVERY.md): detailed
  reset/snapshot/PointsChain boundary notes

### ComfyUI And Server Mode Reference Set

- [comfyui/README.md](comfyui/README.md): ComfyUI operator docs index
- [COMFYUI_ADMIN.md](comfyui/COMFYUI_ADMIN.md): root/admin-only ComfyUI and Civitai operations
- [server_mode_v2/README.md](server_mode_v2/README.md): Server Mode v2 spec bundle index
- [SERVER_MODE_V2_PROFILE_MATRIX.md](server_mode_v2/SERVER_MODE_V2_PROFILE_MATRIX.md): canonical mode matrix
- [server_mode_v2/03_production_gate_playbook.md](server_mode_v2/03_production_gate_playbook.md): production gate 13 reports, signing rules, and filesystem auto-detect trust boundary
- [server_mode_v2/04_production_gate_validation_report.md](server_mode_v2/04_production_gate_validation_report.md): 2026-05-09 production gate 驗收紀錄，含 warning / unverified / old-commit / all-green 實測與 live `50909` target-commit mismatch 收斂
- [SERVER_MODE_V2_TEST_PLAN.md](server_mode_v2/SERVER_MODE_V2_TEST_PLAN.md): mode redesign coverage
- [SERVER_MODE_V2_MIGRATION_PLAN.md](server_mode_v2/SERVER_MODE_V2_MIGRATION_PLAN.md): migration history

## Release, Security, And Testing

- [UPDATE_SUMMARY.md](UPDATE_SUMMARY.md): current release notes
- [BRANCHING_AND_RELEASE.md](BRANCHING_AND_RELEASE.md): branch numbering and release policy
- [RELEASE_LAYOUT.md](RELEASE_LAYOUT.md): tracked source vs runtime boundaries
- [security/PRE_RELEASE_CHECKLIST.md](security/PRE_RELEASE_CHECKLIST.md): blocking release checklist
- [security/PRODUCTION_SIGNOFF_CHECKLIST.md](security/PRODUCTION_SIGNOFF_CHECKLIST.md): whole-site sign-off criteria
- [security/FUNCTIONAL_SMOKE.md](security/FUNCTIONAL_SMOKE.md): isolated runtime smoke runner
- [security/QA_ARCHITECTURE.md](security/QA_ARCHITECTURE.md): QA/security
  governance rules and validation naming contract
- [security/FUNCTIONAL_PERMISSION_PENTEST.md](security/FUNCTIONAL_PERMISSION_PENTEST.md): role-based permission pentest
- [security/PENTEST.md](security/PENTEST.md): security runner and whole-site gate usage
- [security/TRADING_STRESS_PENTEST.md](security/TRADING_STRESS_PENTEST.md): trading correctness/stress script
- [security/SERVER_MODE_V2_RED_TEAM_PLAYBOOK.md](security/SERVER_MODE_V2_RED_TEAM_PLAYBOOK.md): adversarial mode tests

## Maintainer Structure

- [REPOSITORY_STRUCTURE.md](REPOSITORY_STRUCTURE.md): canonical placement logic
  for `docs/`, `scripts/`, `tests/`, runtime baggage, and cleanup priorities
- [../scripts/README.md](../scripts/README.md): script entrypoint and grouping policy
- [../tests/README.md](../tests/README.md): test grouping and consolidation policy

## History, Research, And Archive

- [README.zh-TW.md](README.zh-TW.md): concise Traditional Chinese shortcut
- [VERSION_STORY.md](VERSION_STORY.md): project history and abandoned branches
- [archive/research/BLOCKCHAIN/README.md](archive/research/BLOCKCHAIN/README.md): PointsChain v2 design specs (Phase 1+ pending root authorization)

Archive content is historical evidence, not canonical operator guidance. Prefer
the files listed above unless you are tracing old implementation decisions.
