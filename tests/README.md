# Test Layout Policy

This repository has many test files because it protects several different
surfaces at once:

- backend business logic
- frontend contract rendering
- deployment and operator scripts
- smoke, pentest, and release gates

The goal is not to reduce file count at any cost. The goal is to make test
ownership and failure diagnosis clearer.

## Current Problem

The top-level `tests/` folder mixes:

- long-running domain suites
- tiny one-page UI regressions
- script/CLI tests
- smoke wrappers
- release-policy checks

That makes it harder to know where a new test belongs.

## Target Grouping

Future moves should converge toward:

- `tests/frontend/`
- `tests/trading/`
- `tests/video/`
- `tests/storage/`
- `tests/security/`
- `tests/server_mode/`
- `tests/scripts/`
- `tests/contracts/`

## Merge Rules

Merge files only when they share:

- the same bounded feature
- the same fixture pattern
- the same regression story

Do not merge unrelated tests just to make `ls tests` shorter.

## Good Consolidation Candidates

- scattered `test_frontend_*` files that cover the same page or feature area
- script-focused tests such as deploy/probe/recovery/pentest/stress wrappers
- small UI contract tests that share the same HTML/JS fixture

## Files That Should Stay Focused

These should remain dedicated because they guard large invariants:

- `test_trading_engine.py`
- `test_trading_reference_prices.py`
- `test_points_chain.py`
- `test_snapshots.py`
- `test_security_issue_regressions.py`
- `test_prepush_v2.py`

## New Test Rule

Before creating a new top-level `test_*.py` file:

1. check whether an existing suite already owns the same feature
2. extend that suite if the setup and regression story match
3. create a new file only when the feature boundary is genuinely separate

The long-term direction is clearer domain ownership, not one file per tiny UI
detail.
