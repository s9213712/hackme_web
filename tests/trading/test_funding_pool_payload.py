"""Regression tests for P3 funding-pool APR display.

Before P3 the base APR ``10`` was displayed as ``9.9999999`` after a
round-trip through the daily-rate quantize. These tests pin the display
contract so the cosmetic drift cannot regress.
"""

from decimal import Decimal, ROUND_HALF_UP

from services.trading.accounting.funding_pool import funding_pool_payload
from services.trading.constants import APR_DAYS_PER_YEAR


def _daily_from_apr(apr_percent):
    dec = Decimal(str(apr_percent or 0))
    if dec <= 0:
        return 0.0
    return float((dec / APR_DAYS_PER_YEAR).quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP))


def _apr_from_daily(daily_percent):
    dec = Decimal(str(daily_percent or 0))
    if dec <= 0:
        return 0.0
    return float((dec * APR_DAYS_PER_YEAR).quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP))


def _payload(**overrides):
    defaults = dict(
        balance=10000,
        outstanding=0,
        requested_principal=0,
        borrowed_asset="POINTS",
        base_apr=10.0,
        pressure=4.0,
        initial_points=10000,
        daily_from_apr=_daily_from_apr,
        apr_from_daily=_apr_from_daily,
    )
    defaults.update(overrides)
    return funding_pool_payload(**defaults)


def test_zero_utilisation_keeps_apr_exactly_at_base():
    payload = _payload()
    assert payload["base_interest_apr_percent"] == 10.0
    # Pre-P3 these were 9.9999999.
    assert payload["effective_interest_apr_percent"] == 10.0
    assert payload["projected_interest_apr_percent"] == 10.0


def test_partial_utilisation_scales_apr_above_base():
    # 50% utilisation × pressure 4.0 = 3.0× base rate -> 30% APR ish.
    payload = _payload(balance=5000, outstanding=5000)
    assert payload["base_interest_apr_percent"] == 10.0
    assert payload["effective_interest_apr_percent"] > payload["base_interest_apr_percent"]
    # Tolerate the natural numeric width but bound the upper tail to 6dp.
    text = f"{payload['effective_interest_apr_percent']:.10f}".rstrip("0").rstrip(".")
    assert "." not in text or len(text.split(".")[1]) <= 6, text


def test_zero_pressure_keeps_apr_at_base_even_at_full_utilisation():
    payload = _payload(balance=0, outstanding=10000, pressure=0.0)
    assert payload["effective_interest_apr_percent"] == payload["base_interest_apr_percent"]


def test_zero_base_apr_stays_zero():
    payload = _payload(base_apr=0.0)
    assert payload["base_interest_apr_percent"] == 0.0
    assert payload["effective_interest_apr_percent"] == 0.0
    assert payload["projected_interest_apr_percent"] == 0.0
