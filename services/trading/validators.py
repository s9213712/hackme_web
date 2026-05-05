import math
from decimal import Decimal, ROUND_HALF_UP

from services.trading.constants import APR_DAYS_PER_YEAR


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
