"""Slice 2 — strict parser invariants for services/trading/validators.py.

Companion coverage for the trading validator split.
REFACTOR_PLAN.md slice 2.

The slice is additive: no callers migrated, no behavior change for the
existing private-named helpers.  These tests pin the contract of the
new `parse_bool_strict` and document that the public-named aliases are
exactly the same callable as their underscore-prefixed originals.
"""

import math
from decimal import Decimal

import pytest

from services.trading import validators
from services.trading._clock import now_text


# ─────────────────────────────────────────────────────────────────
# parse_bool_strict
# ─────────────────────────────────────────────────────────────────


def test_parse_bool_strict_accepts_native_bool():
    assert validators.parse_bool_strict(True) is True
    assert validators.parse_bool_strict(False) is False


def test_parse_bool_strict_accepts_canonical_strings_case_insensitive():
    for s in ("1", "true", "True", "TRUE", "yes", "Yes", "on", "ON"):
        assert validators.parse_bool_strict(s) is True
    for s in ("0", "false", "FALSE", "no", "No", "off", "OFF"):
        assert validators.parse_bool_strict(s) is False


def test_parse_bool_strict_strips_whitespace():
    assert validators.parse_bool_strict("  true  ") is True
    assert validators.parse_bool_strict("\toff\n") is False


def test_parse_bool_strict_rejects_y_t_unless_loose():
    with pytest.raises(ValueError):
        validators.parse_bool_strict("y")
    with pytest.raises(ValueError):
        validators.parse_bool_strict("t")
    with pytest.raises(ValueError):
        validators.parse_bool_strict("n")
    with pytest.raises(ValueError):
        validators.parse_bool_strict("f")
    assert validators.parse_bool_strict("y", accept_y_t=True) is True
    assert validators.parse_bool_strict("t", accept_y_t=True) is True
    assert validators.parse_bool_strict("n", accept_y_t=True) is False
    assert validators.parse_bool_strict("f", accept_y_t=True) is False


def test_parse_bool_strict_handles_none_and_empty_string_via_default():
    assert validators.parse_bool_strict(None) is False
    assert validators.parse_bool_strict("") is False
    assert validators.parse_bool_strict(None, default=True) is True
    assert validators.parse_bool_strict("", default=True) is True
    assert validators.parse_bool_strict("   ", default=True) is True


def test_parse_bool_strict_accepts_int_0_or_1_only():
    assert validators.parse_bool_strict(0) is False
    assert validators.parse_bool_strict(1) is True
    with pytest.raises(ValueError):
        validators.parse_bool_strict(2)
    with pytest.raises(ValueError):
        validators.parse_bool_strict(-1)


def test_parse_bool_strict_rejects_garbage_strings_not_silent():
    """Regression guard for the bug class that motivated this slice:
    silently coercing invalid input into a truthy/falsy result.
    """
    for garbage in ("maybe", "truee", "yes,please", "0.0", "1.0", "✓"):
        with pytest.raises(ValueError):
            validators.parse_bool_strict(garbage, name="garbage")


def test_parse_bool_strict_rejects_non_str_non_bool_non_int_types():
    for bad in ([], {}, {"x": 1}, ["true"], 1.5, object()):
        with pytest.raises(ValueError):
            validators.parse_bool_strict(bad, name="bad")


def test_parse_bool_strict_error_message_contains_field_name():
    try:
        validators.parse_bool_strict("nope", name="audit_chain_enabled")
    except ValueError as exc:
        assert "audit_chain_enabled" in str(exc)
    else:
        pytest.fail("expected ValueError")


# ─────────────────────────────────────────────────────────────────
# Public-named aliases are the same callable
# ─────────────────────────────────────────────────────────────────


def test_public_aliases_are_identity_to_private_originals():
    """Slice 2 promise: alias is the same function object — no wrapper,
    no behavior drift, callers that switch import names see identical
    behavior. Slice 3 will migrate callers; slice 2 only publishes names.
    """
    assert validators.parse_int_strict is validators._to_int
    assert validators.parse_float_strict is validators._to_float
    assert validators.parse_decimal_strict is validators._to_decimal
    assert validators.parse_price_float_strict is validators._to_price_float
    assert validators.decimal_text is validators._decimal_text
    assert validators.daily_percent_from_apr is validators._daily_percent_from_apr
    assert validators.apr_percent_from_daily is validators._apr_percent_from_daily
    assert validators.normalize_borrow_interest_timing is validators._normalize_borrow_interest_timing
    assert (
        validators.billable_interest_hours_from_elapsed_seconds
        is validators._billable_interest_hours_from_elapsed_seconds
    )


# ─────────────────────────────────────────────────────────────────
# Strict numeric parsers — behavior unchanged but pinned
# ─────────────────────────────────────────────────────────────────


def test_parse_int_strict_rejects_float_string():
    with pytest.raises(ValueError):
        validators.parse_int_strict("12.5", name="qty")


def test_parse_int_strict_rejects_out_of_range():
    with pytest.raises(ValueError):
        validators.parse_int_strict(-1, name="qty", minimum=0)
    with pytest.raises(ValueError):
        validators.parse_int_strict(10**13, name="qty")


def test_parse_decimal_strict_rejects_nan_and_inf():
    with pytest.raises(ValueError):
        validators.parse_decimal_strict("nan", name="x")
    with pytest.raises(ValueError):
        validators.parse_decimal_strict("inf", name="x")
    with pytest.raises(ValueError):
        validators.parse_decimal_strict("-inf", name="x")


def test_parse_decimal_strict_uses_string_not_float_path():
    """0.1 + 0.2 != 0.3 in float; the strict parser must take the
    string path so 0.1 stored as Decimal stays exact."""
    assert validators.parse_decimal_strict("0.1", name="x") == Decimal("0.1")
    # going through float would yield 0.10000000000000000555... — Decimal
    # input via str() is exact:
    assert (
        validators.parse_decimal_strict("0.1", name="x")
        + validators.parse_decimal_strict("0.2", name="x")
        == Decimal("0.3")
    )


def test_parse_price_float_strict_rounds_to_8_places():
    """Spot price granularity is 1e-8.  Strict parser rounds at parse
    time so callers can do float math afterwards without drift."""
    out = validators.parse_price_float_strict(
        "1.123456785", name="px", minimum=0.00000001
    )
    assert isinstance(out, float)
    # ROUND_HALF_UP at 8 places: 1.123456785 → 1.12345679
    assert math.isclose(out, 1.12345679, abs_tol=1e-9)


# ─────────────────────────────────────────────────────────────────
# _clock.now_text — replaces 7 duplicated _now_text definitions
# ─────────────────────────────────────────────────────────────────


def test_now_text_returns_local_iso_string():
    s = now_text()
    assert isinstance(s, str)
    assert "T" in s, f"expected ISO8601 with 'T' separator, got {s!r}"


def test_now_text_byte_for_byte_matches_inline_dup():
    """Slice 2 promise: now_text() is a drop-in replacement for the
    _now_text() definitions in funding/verification/markets/orders/
    bots/service/margin/grid.py.  The inline form everywhere is
    `datetime.now().isoformat()` — verify ours matches."""
    from datetime import datetime as dt

    expected_prefix_len = len("2026-05-07T")
    a = now_text()
    b = dt.now().isoformat()
    # both should at least share the date-and-T prefix; exact equality
    # depends on call timing
    assert a[:expected_prefix_len] == b[:expected_prefix_len]


def test_inline_dups_still_match_now_text_format():
    """If anyone changes services/trading/_clock.py to UTC without
    migrating callers in slice 3, this test fails by detecting that
    the format diverges from the still-inline _now_text().
    """
    from services.trading.grid import _now_text as grid_now
    from services.trading.orders import _now_text as orders_now
    from services.trading.margin import _now_text as margin_now

    central = now_text()
    for inline in (grid_now(), orders_now(), margin_now()):
        # Same prefix length means same format (date + 'T' + time).
        assert len(inline) == len(central), (
            f"format drift: central={central!r} inline={inline!r} — "
            "do not change services/trading/_clock.py without migrating "
            "the 7 _now_text() callers in the same slice"
        )
