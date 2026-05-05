from decimal import Decimal, ROUND_CEILING

from services.trading.constants import ASSET_SCALE
from services.trading.validators import _to_decimal


def notional_points(quantity_units, price_points):
    quantity_units = int(quantity_units)
    if quantity_units <= 0:
        return 0
    price_decimal = _to_decimal(price_points, name="price_points", minimum=0)
    exact_notional = (Decimal(quantity_units) * price_decimal) / Decimal(ASSET_SCALE)
    if exact_notional <= 0:
        return 0
    return int(exact_notional.quantize(Decimal("1"), rounding=ROUND_CEILING))
