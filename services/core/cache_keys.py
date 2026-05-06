"""Server Mode v2 — namespaced cache-key helper.

Phase 6 of SERVER_MODE_V2_IMPLEMENTATION_PLAN.md.

Without this helper, code like:

    cache[f"orderbook:{symbol}"] = depth   # BUG

silently lets internal_test orders' order-book overwrite production's.
The fix is to force every cache key through `make_cache_key(...)`,
which:

1. Refuses keys that don't carry the current mode (TypeError if mode
   kw is missing — caught at import / test time, not in production).
2. Refuses internal_test keys without a tester_id (ValueError — every
   tester gets their own scoped namespace).
3. Returns a deterministically-ordered colon-separated key string so
   future migrations (Redis prefix scans, key-cleanup workers) can
   reason about it.

Example:

    >>> make_cache_key("orderbook", mode="production", market="BTC/POINTS")
    'orderbook:production:market=BTC/POINTS'

    >>> make_cache_key("orderbook", mode="internal_test", tester_id=7, market="BTC/POINTS")
    'orderbook:internal_test:tester7:market=BTC/POINTS'

    >>> make_cache_key("orderbook", market="BTC/POINTS")
    Traceback (most recent call last):
        ...
    TypeError: ...

This module is intentionally tiny — it's a discipline-enforcement
helper, not a cache implementation. The actual cache backend (in-
process dict, file, future Redis) keys off the strings produced here.
"""

from __future__ import annotations

from typing import Optional


_REQUIRES_TESTER_ID_MODES = frozenset({"internal_test"})


def make_cache_key(
    logical: str,
    *,
    mode: str,
    tester_id: Optional[int] = None,
    **dims,
) -> str:
    """Compose a mode-scoped cache key.

    Required keyword args:
        mode: the current Server Mode v2 mode string. Empty / non-string
            raises ValueError. Missing the kwarg raises TypeError (the
            normal Python behavior — strict, easy to spot in tests).

    Optional:
        tester_id: required when mode == 'internal_test'; ignored
            otherwise (a non-internal_test caller passing tester_id
            still works, but the id is stamped into the key for
            traceability).
        **dims: arbitrary string-able dimension key/value pairs. Sorted
            by key so two callers producing the same logical/mode/dims
            always emit the same key.
    """
    if not isinstance(logical, str) or not logical.strip():
        raise ValueError("logical name must be a non-empty string")
    if not isinstance(mode, str) or not mode.strip():
        raise ValueError("mode must be a non-empty string")
    if mode in _REQUIRES_TESTER_ID_MODES and tester_id is None:
        raise ValueError(
            f"mode={mode!r} requires tester_id — every tester gets a scoped key namespace"
        )
    parts = [logical, mode]
    if tester_id is not None:
        parts.append(f"tester{int(tester_id)}")
    for k in sorted(dims):
        v = dims[k]
        # Cache keys must be strings; coerce + reject embedded colons
        # so the format stays one-pass parseable.
        v_str = str(v)
        if ":" in v_str or ":" in str(k):
            raise ValueError(f"cache-key dim {k!r}={v_str!r} contains ':' which is the namespace separator")
        parts.append(f"{k}={v_str}")
    return ":".join(parts)


def parse_cache_key(key: str) -> dict:
    """Inverse of `make_cache_key` for ops / log inspection.

    Returns: {logical, mode, tester_id?, dims: {...}}.
    Raises ValueError if the key doesn't look like one we produced.
    """
    if not isinstance(key, str) or ":" not in key:
        raise ValueError(f"not a make_cache_key string: {key!r}")
    parts = key.split(":")
    if len(parts) < 2:
        raise ValueError(f"too few segments: {key!r}")
    logical = parts[0]
    mode = parts[1]
    out = {"logical": logical, "mode": mode, "dims": {}}
    rest = parts[2:]
    if rest and rest[0].startswith("tester"):
        try:
            out["tester_id"] = int(rest[0][len("tester"):])
        except ValueError:
            pass
        rest = rest[1:]
    for seg in rest:
        if "=" in seg:
            k, _, v = seg.partition("=")
            out["dims"][k] = v
    return out
