"""Pure trading margin-interest helpers."""

from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP


def margin_interest_total_hours(
    row,
    *,
    now_text,
    billable_interest_hours_from_elapsed_seconds,
    default_interval_hours,
    default_minimum_hours,
):
    principal = int(row["principal_points"] or 0)
    rate_percent = float(row["interest_percent_daily"] or 0)
    if principal <= 0 or rate_percent <= 0:
        return 0
    try:
        opened_at = datetime.fromisoformat(str(row["opened_at"]))
        closed_at = datetime.fromisoformat(str(now_text))
    except Exception:
        return 0
    seconds = max(0, (closed_at - opened_at).total_seconds())
    hours = billable_interest_hours_from_elapsed_seconds(
        seconds,
        interval_hours=int(row["interest_interval_hours"] or default_interval_hours) if "interest_interval_hours" in row.keys() else default_interval_hours,
        minimum_hours=int(row["interest_minimum_hours"] or default_minimum_hours) if "interest_minimum_hours" in row.keys() else default_minimum_hours,
    )
    return max(0, hours)


def margin_interest_due_micropoints(*, principal, rate_percent, hours, point_micro_scale):
    principal = int(principal or 0)
    rate_percent = float(rate_percent or 0)
    hours = max(0, int(hours or 0))
    if principal <= 0 or rate_percent <= 0 or hours <= 0:
        return 0
    hourly_rate = (Decimal(str(rate_percent)) / Decimal("100")) / Decimal("24")
    total_micro = Decimal(principal) * hourly_rate * Decimal(hours) * Decimal(point_micro_scale)
    return int(total_micro.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def margin_interest_due_points(
    row,
    *,
    hours,
    point_micro_scale,
    due_micropoints_func,
):
    principal = int(row["principal_points"] or 0)
    rate_percent = float(row["interest_percent_daily"] or 0)
    hours = max(0, int(hours or 0))
    if principal <= 0 or rate_percent <= 0 or hours <= 0:
        return 0
    carry = int(row["interest_carry_micropoints"] or 0) if "interest_carry_micropoints" in row.keys() else 0
    total_micro = due_micropoints_func(
        principal=principal,
        rate_percent=rate_percent,
        hours=hours,
    ) + carry
    return int(total_micro // point_micro_scale)


def margin_interest_points(
    row,
    *,
    now_text,
    point_micro_scale,
    total_hours_func,
    due_micropoints_func,
):
    accrued_hours = int(row["interest_accrued_hours"] or 0) if "interest_accrued_hours" in row.keys() else 0
    total_hours = total_hours_func(row, now_text=now_text)
    due_hours = max(0, total_hours - accrued_hours)
    capitalized = int(row["interest_points"] or 0)
    carry = int(row["interest_carry_micropoints"] or 0) if "interest_carry_micropoints" in row.keys() else 0
    due_micro = due_micropoints_func(
        principal=int(row["principal_points"] or 0),
        rate_percent=float(row["interest_percent_daily"] or 0),
        hours=due_hours,
    )
    return capitalized + int((carry + due_micro) // point_micro_scale)
