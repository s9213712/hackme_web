import math
from decimal import Decimal, ROUND_HALF_UP

from services.trading.constants import APR_DAYS_PER_YEAR


# Public bool literal table.  Centralizes the `{"1","true","yes","on"}` set
# duplicated across 22 sites (see
# Kept small so trading validators do not grow back into the old monolithic engine.
# §4.1).  Slice 2 publishes the table + parser; slice 3 migrates callers.
_TRUE_LITERALS = frozenset({"1", "true", "yes", "on"})
_TRUE_LITERALS_LOOSE = frozenset({"1", "true", "yes", "on", "y", "t"})
_FALSE_LITERALS = frozenset({"0", "false", "no", "off"})
_FALSE_LITERALS_LOOSE = frozenset({"0", "false", "no", "off", "n", "f"})


def parse_bool_strict(value, *, default=False, accept_y_t=False, name="value"):
    """Strictly parse a value into bool.

    Accepts:
      - `bool` → returned as-is
      - `None` or empty string → `default`
      - `int 0/1` → `False/True`
      - `str` matching one of the literal sets (case-insensitive, stripped)

    Rejects (raises ValueError):
      - any other type (`dict`, `list`, etc.)
      - any string outside the literal set (e.g. `"maybe"`, `"truee"`)
      - any non-0/1 int

    `accept_y_t=True` extends the accepted strings to include
    `{"y","t"}` / `{"n","f"}` (some legacy callers used this loose form;
    new code should not).

    Why not `bool(value)`: `bool({"x":1})` is `True` and `bool("False")`
    is also `True` — silently coerces invalid input into a truthy result.
    Operators and bots passing malformed flags should get a 400, not a
    surprise behavior change.
    """
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, int):
        if value == 0:
            return False
        if value == 1:
            return True
        raise ValueError(f"{name} must be a boolean (got int {value!r})")
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized == "":
            return default
        true_set = _TRUE_LITERALS_LOOSE if accept_y_t else _TRUE_LITERALS
        false_set = _FALSE_LITERALS_LOOSE if accept_y_t else _FALSE_LITERALS
        if normalized in true_set:
            return True
        if normalized in false_set:
            return False
        raise ValueError(f"{name} must be a boolean literal (got {value!r})")
    raise ValueError(f"{name} must be a boolean (got {type(value).__name__})")


def _to_int(value, *, name, minimum=0, maximum=10**12):
    try:
        number = int(value)
    except Exception as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if number < minimum or number > maximum:
        raise ValueError(f"{name} out of range")
    return number


def _to_float(value, *, name, minimum=0.0, maximum=10**12):
    try:
        number = float(value)
    except Exception as exc:
        raise ValueError(f"{name} must be a number") from exc
    if number < minimum or number > maximum:
        raise ValueError(f"{name} out of range")
    return number


def _to_decimal(value, *, name, minimum=None, maximum=None):
    try:
        number = Decimal(str(value))
    except Exception as exc:
        raise ValueError(f"{name} must be a number") from exc
    if not number.is_finite():
        raise ValueError(f"{name} must be a finite number")
    if minimum is not None and number < Decimal(str(minimum)):
        raise ValueError(f"{name} out of range")
    if maximum is not None and number > Decimal(str(maximum)):
        raise ValueError(f"{name} out of range")
    return number


def _to_price_float(value, *, name, minimum=0.00000001, maximum=10**12):
    return float(
        _to_decimal(value, name=name, minimum=minimum, maximum=maximum).quantize(
            Decimal("0.00000001"),
            rounding=ROUND_HALF_UP,
        )
    )


def _decimal_text(value, *, places="0.00000001"):
    dec = Decimal(str(value or 0)).quantize(Decimal(places), rounding=ROUND_HALF_UP)
    text = format(dec, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _daily_percent_from_apr(apr_percent):
    dec = Decimal(str(apr_percent or 0))
    if dec <= 0:
        return 0.0
    return float((dec / APR_DAYS_PER_YEAR).quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP))


def _apr_percent_from_daily(daily_percent):
    dec = Decimal(str(daily_percent or 0))
    if dec <= 0:
        return 0.0
    return float((dec * APR_DAYS_PER_YEAR).quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP))


def _normalize_borrow_interest_timing(interval_hours=None, minimum_hours=None):
    interval = int(interval_hours or 1)
    minimum = int(minimum_hours or 1)
    interval = max(1, min(interval, 168))
    minimum = max(1, min(minimum, 168))
    return interval, minimum


def _billable_interest_hours_from_elapsed_seconds(seconds, *, interval_hours=1, minimum_hours=1):
    seconds = max(0.0, float(seconds or 0))
    interval_hours, minimum_hours = _normalize_borrow_interest_timing(interval_hours, minimum_hours)
    if seconds <= 0:
        return 0
    interval_seconds = interval_hours * 3600.0
    billed_hours = int(math.ceil(seconds / interval_seconds)) * interval_hours
    return max(minimum_hours, billed_hours)


# Public-named aliases of the strict numeric parsers above.  The original
# `_to_*` names mark these helpers as private to validators.py, but 13
# caller modules already cross-import them (INVENTORY §4.4), which makes
# the underscore prefix misleading.  Callers should migrate to the public
# names; the legacy names remain as aliases so this slice is purely
# additive (no behavior change, no caller migration required).
parse_int_strict = _to_int
parse_float_strict = _to_float
parse_decimal_strict = _to_decimal
parse_price_float_strict = _to_price_float
decimal_text = _decimal_text
daily_percent_from_apr = _daily_percent_from_apr
apr_percent_from_daily = _apr_percent_from_daily
normalize_borrow_interest_timing = _normalize_borrow_interest_timing
billable_interest_hours_from_elapsed_seconds = _billable_interest_hours_from_elapsed_seconds
