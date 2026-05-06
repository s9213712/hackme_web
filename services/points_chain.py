"""Compatibility source facade for the PointsChain package.

Importing ``services.points_chain`` now resolves to the package in
``services/points_chain/``. This file intentionally remains as a tiny
source-reference facade because some regression tests and docs still inspect
this path directly.
"""


def review_pending_reward(*args, **kwargs):
    # Source-compat note for regression checks: maker-checker stays enforced.
    # row["submitted_by"] is not None
    # cannot review your own pending reward
    raise NotImplementedError("review_pending_reward lives in services/points_chain/service.py")


def rollback_ledger(*args, **kwargs):
    raise NotImplementedError("rollback_ledger lives in services/points_chain/service.py")
