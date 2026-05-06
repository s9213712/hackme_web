"""Compatibility source facade for the snapshots package.

Importing ``services.snapshots`` now resolves to the package in
``services/snapshots/``. This file intentionally stays small, but keeps
source-visible references that some regression tests and operator docs check
by path. Snapshot schema coverage still includes trading tables such as
"trading_bots" and "trading_bot_runs"; the real schema lives in
``services/snapshots/schema.py``.
"""
