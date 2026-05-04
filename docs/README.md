# Documentation Map

The repository root keeps only [README.md](../README.md) and
[SECURITY.md](../SECURITY.md). Everything else lives here.

## First Route

- [00_START_HERE.md](00_START_HERE.md): role-based reading order
- [01_DEPLOY_QUICKSTART.md](01_DEPLOY_QUICKSTART.md): shortest path to a
  working local or staging deployment
- [02_DEPLOY_PRODUCTION.md](02_DEPLOY_PRODUCTION.md): production hardening,
  reverse proxy, backups, and release gate expectations

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
- [10_WEB_TERMINAL.md](10_WEB_TERMINAL.md): archived feature status and links

## QA And Support

- [11_QA_TESTING.md](11_QA_TESTING.md): test-layer map, script relationships,
  and operator-facing validation route
- [12_TROUBLESHOOTING.md](12_TROUBLESHOOTING.md): common errors and first-pass diagnosis

## Deep Reference

- [For_developer.md](For_developer.md): API, schema, runtime layout, feature flags
- [WEB.md](WEB.md): detailed page-by-page UI behavior
- [TRADING.md](TRADING.md): full trading, bots, workflow editor, and backtest details
- [VIDEO_PLATFORM.md](VIDEO_PLATFORM.md): detailed video module reference
- [SECURITY.md](SECURITY.md): current security controls and known limits
- [RUNTIME_RESET_AND_RECOVERY.md](RUNTIME_RESET_AND_RECOVERY.md): detailed
  reset/snapshot/PointsChain boundary notes
- [DEPLOYMENT.md](DEPLOYMENT.md): script-level deployment and operations reference
- [AGENTS/README.md](AGENTS/README.md): entry for agent rules, QA runbooks, and
  archived QA reports
- [AGENTS/QA_MISSION_FOR_AGENTS.md](AGENTS/QA_MISSION_FOR_AGENTS.md): deep QA
  runbook for agents and manual exploratory testing
- [AGENTS/RULES_FOR_AGENTS.md](AGENTS/RULES_FOR_AGENTS.md): project-wide
  completion rules for docs, tests, UX, mobile checks, and delivery reporting

## Release, Security, And Testing

- [UPDATE_SUMMARY.md](UPDATE_SUMMARY.md): current release notes
- [BRANCHING_AND_RELEASE.md](BRANCHING_AND_RELEASE.md): branch numbering and release policy
- [RELEASE_LAYOUT.md](RELEASE_LAYOUT.md): tracked source vs runtime boundaries
- [security/PRE_RELEASE_CHECKLIST.md](security/PRE_RELEASE_CHECKLIST.md): blocking release checklist
- [security/PRODUCTION_SIGNOFF_CHECKLIST.md](security/PRODUCTION_SIGNOFF_CHECKLIST.md): whole-site sign-off criteria
- [security/FUNCTIONAL_SMOKE.md](security/FUNCTIONAL_SMOKE.md): isolated runtime smoke runner
- [security/FUNCTIONAL_PERMISSION_PENTEST.md](security/FUNCTIONAL_PERMISSION_PENTEST.md): role-based permission pentest
- [security/PENTEST.md](security/PENTEST.md): security runner and whole-site gate usage
- [security/TRADING_STRESS_PENTEST.md](security/TRADING_STRESS_PENTEST.md): trading correctness/stress script
- [security/SERVER_MODE_V2_RED_TEAM_PLAYBOOK.md](security/SERVER_MODE_V2_RED_TEAM_PLAYBOOK.md): adversarial mode tests
- [SERVER_MODE_V2_PROFILE_MATRIX.md](SERVER_MODE_V2_PROFILE_MATRIX.md): canonical mode matrix
- [SERVER_MODE_V2_TEST_PLAN.md](SERVER_MODE_V2_TEST_PLAN.md): mode redesign coverage
- [SERVER_MODE_V2_MIGRATION_PLAN.md](SERVER_MODE_V2_MIGRATION_PLAN.md): migration history
- [SECURITY_MODES.md](SECURITY_MODES.md): legacy redirect for old links

## History, Research, And Archive

- [README.zh-TW.md](README.zh-TW.md): concise Traditional Chinese shortcut
- [VERSION_STORY.md](VERSION_STORY.md): project history and abandoned branches
- [archive/research/README.md](archive/research/README.md): archived research
  notes and retired implementation workflows
- [research/finished/GRID_TRADING_BOT_DESIGN_REPORT.md](research/finished/GRID_TRADING_BOT_DESIGN_REPORT.md): future grid-bot research
- [archive/webterminal/README.md](archive/webterminal/README.md): archived WebTerminal attempts
