# Documentation Index

This directory contains the project guides. The repository root keeps only the
short [README](../README.md) plus GitHub-required metadata such as
[`SECURITY.md`](../SECURITY.md).

## Start Here

- [Traditional Chinese README](README.zh-TW.md): concise Chinese entry point
- [Web UI Guide](WEB.md): user-facing pages and feature behavior
- [Trading System And Bots](TRADING.md): spot exchange, borrow trading,
  trading bots, workflow editor, backtesting, and validation scripts
- [Video Platform v1](VIDEO_PLATFORM.md): Cloud Drive backed video publishing,
  playback, comments, likes, and PointsChain tips
- [Grid Trading Bot Design Report](research_reports/GRID_TRADING_BOT_DESIGN_REPORT.md):
  research-only design for a future spot grid trading bot
- [Developer Guide](For_developer.md): API, deployment, runtime state, and
  operator notes
- [Version Story](VERSION_STORY.md): project history, branch decisions, and
  abandoned WebTerminal notes
- [Update Summary](UPDATE_SUMMARY.md): latest release notes shown by the root
  GitHub update center
- [Runtime Reset And Recovery](RUNTIME_RESET_AND_RECOVERY.md): reset,
  snapshot/restore, and PointsChain recovery boundaries
- [Server Mode v2 Profile Matrix](SERVER_MODE_V2_PROFILE_MATRIX.md): canonical
  modes, safety matrix, confirmation phrases, and production gate reports
- [Server Mode v2 Migration Plan](SERVER_MODE_V2_MIGRATION_PLAN.md): six-phase
  migration plan for checkpointed mode switching and test data isolation
- [Server Mode v2 Test Plan](SERVER_MODE_V2_TEST_PLAN.md): unit, integration,
  security, and smoke checks for the mode redesign
- [Deployment And Operations Scripts](DEPLOYMENT.md): one-command deployment,
  functional smoke, permission pentest, and stress test usage
- [Release Layout](RELEASE_LAYOUT.md): tracked source, runtime data, generated
  artifacts, and cleanup boundaries
- [Project Phase Status](PHASE_STATUS.md): current project status and pending
  phase notes
- [Implementation Workflow](implementation_workflow.md): development workflow
  and implementation notes

## Security And Release

- [Security Policy](SECURITY.md): current security controls and known limits
- [Branching And Release](BRANCHING_AND_RELEASE.md): branch numbering and
  release ID policy
- [Pre-release Checklist](security/PRE_RELEASE_CHECKLIST.md): blocking checks
  before production release
- [Production Sign-off Checklist](security/PRODUCTION_SIGNOFF_CHECKLIST.md):
  Server Mode v2 sign-off, whole-site gate command, and final readiness criteria
- [Server Mode v2 Red Team Playbook](security/SERVER_MODE_V2_RED_TEAM_PLAYBOOK.md):
  adversarial test plan for mode, token, snapshot, and lockdown controls
- [Secrets Scanning](security/secrets_scanning.md): secret scanning policy and
  allowlist handling

## Test Script Guides

- [Pentest Runner](security/PENTEST.md): security test runner usage, including
  `--only whole-site-production-gate`
- [Functional Smoke Runner](security/FUNCTIONAL_SMOKE.md): full feature smoke
  test runner usage
- [Functional Permission Pentest](security/FUNCTIONAL_PERMISSION_PENTEST.md):
  role-based permission pentest usage
- [Server Mode v2 Test Plan](SERVER_MODE_V2_TEST_PLAN.md): includes clean
  smoke, adversarial, Red Team L2, and live HTTP/session/kill-9 smoke commands
- [Deployment And Operations Scripts](DEPLOYMENT.md): includes functional smoke,
  permission pentest, traffic stress test, and pre-push validation commands
- [Trading Stress Pentest](security/TRADING_STRESS_PENTEST.md): controlled spot
  and borrow-trading stress/security validation
- [Video Module Pentest](VIDEO_PLATFORM.md#security-tests): Cloud Drive video
  permission and PointsChain tip validation
