from decimal import Decimal, InvalidOperation, ROUND_DOWN, ROUND_HALF_UP

from services.trading.constants import ASSET_SCALE


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
