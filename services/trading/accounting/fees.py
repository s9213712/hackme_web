from decimal import Decimal, ROUND_HALF_UP


def fee_points(notional, fee_rate_percent):
    exact_fee = (Decimal(int(notional or 0)) * Decimal(str(fee_rate_percent or 0))) / Decimal("100")
    if exact_fee <= 0:
        return 0
    return int(exact_fee.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
