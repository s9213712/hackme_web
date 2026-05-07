"""Pure trading accounting helpers.

This module groups the small numeric helpers that make up the shared
accounting core for trading. The concrete engine in
``services.trading.engine`` still owns orchestration and state changes;
these helpers only perform deterministic calculations.
"""

from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_DOWN, ROUND_HALF_UP

from services.trading.constants import ASSET_SCALE
from services.trading.validators import _to_decimal


def quantity_to_units(value):
    try:
        dec = Decimal(str(value or "")).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("quantity must be a positive number") from exc
    if not dec.is_finite():
        raise ValueError("quantity must be a positive number")
    if dec <= 0:
        raise ValueError("quantity must be positive")
    units = int(dec * ASSET_SCALE)
    if units <= 0:
        raise ValueError("quantity is too small")
    return units


def units_to_quantity(units):
    units = int(units or 0)
    text = f"{units // ASSET_SCALE}.{units % ASSET_SCALE:08d}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def _quantity_step_units_from_precision(precision):
    precision_value = max(0, min(8, int(precision or 0)))
    return 10 ** max(0, 8 - precision_value)


def _decimal_units(value):
    return int((Decimal(str(value)) * Decimal(ASSET_SCALE)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def notional_points(quantity_units, price_points):
    quantity_units = int(quantity_units)
    if quantity_units <= 0:
        return 0
    price_decimal = _to_decimal(price_points, name="price_points", minimum=0)
    exact_notional = (Decimal(quantity_units) * price_decimal) / Decimal(ASSET_SCALE)
    if exact_notional <= 0:
        return 0
    return int(exact_notional.quantize(Decimal("1"), rounding=ROUND_CEILING))


def fee_points(notional, fee_rate_percent):
    exact_fee = (Decimal(int(notional or 0)) * Decimal(str(fee_rate_percent or 0))) / Decimal("100")
    if exact_fee <= 0:
        return 0
    return int(exact_fee.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
