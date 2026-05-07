"""Trading clock helper.

Centralizes the timestamp string used by trading service modules so
the same duplicated `_now_text()` does not need to live in 7 separate
files (services/trading/{funding,verification,markets,orders,margin,
grid}.py and services/trading/bots/service.py).

`now_text()` returns local-time ISO8601 to match the existing byte-
for-byte behavior of every duplicated `_now_text()`. Migrating to UTC
is a behavior change and requires a separate slice + root authorization
— do not change the implementation here without that approval.
"""

from datetime import datetime


def now_text() -> str:
    """Return local-time ISO8601 timestamp.

    Mirrors `datetime.now().isoformat()` exactly so callers that switch
    from a local `_now_text()` to this helper see no observable change
    in stored timestamps.
    """
    return datetime.now().isoformat()
