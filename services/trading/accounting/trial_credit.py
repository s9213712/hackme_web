"""Pure trading trial-credit helpers."""

import math
from datetime import datetime, timedelta


def trial_credit_expires_at(now_text, *, days_valid):
    return (datetime.fromisoformat(now_text) + timedelta(days=int(days_valid or 0))).isoformat()


def trial_credit_status_after_delta(current_status, *, next_available, next_locked, next_deployed):
    next_status = current_status
    if next_status == "active" and int(next_available) == 0 and int(next_locked) == 0 and int(next_deployed) == 0:
        next_status = "depleted"
    return next_status


def trial_units_for_buy(*, quantity_units, trial_used_points, total_points):
    trial_used_points = int(trial_used_points or 0)
    quantity_units = int(quantity_units or 0)
    total_points = max(1, int(total_points or 0))
    if trial_used_points <= 0 or quantity_units <= 0:
        return 0
    trial_units = quantity_units if trial_used_points >= total_points else int((quantity_units * trial_used_points) // total_points)
    if trial_units <= 0:
        trial_units = 1
    return min(quantity_units, trial_units)


def trial_allocate_sell_result(*, available_trial_units, trial_cost_total, quantity_units, net_credit_points):
    available_trial_units = int(available_trial_units or 0)
    trial_cost_total = int(trial_cost_total or 0)
    quantity_units = int(quantity_units or 0)
    net_credit_points = int(net_credit_points or 0)
    if available_trial_units <= 0 or trial_cost_total <= 0 or quantity_units <= 0 or net_credit_points <= 0:
        return {
            "trial_units": 0,
            "trial_cost_points": 0,
            "trial_repaid_points": 0,
            "trial_profit_points": 0,
            "wallet_credit_points": net_credit_points,
            "remaining_units": available_trial_units,
            "remaining_cost": trial_cost_total,
        }
    trial_units = min(available_trial_units, quantity_units)
    if trial_units == available_trial_units:
        trial_cost = trial_cost_total
    else:
        trial_cost = int(math.ceil(trial_cost_total * trial_units / available_trial_units))
    trial_net_credit = int(math.floor(net_credit_points * trial_units / quantity_units))
    trial_repaid = min(trial_net_credit, trial_cost)
    trial_profit = max(0, trial_net_credit - trial_cost)
    wallet_credit = max(0, net_credit_points - trial_repaid)
    remaining_units = max(0, available_trial_units - trial_units)
    remaining_cost = max(0, trial_cost_total - trial_cost)
    return {
        "trial_units": trial_units,
        "trial_cost_points": trial_cost,
        "trial_repaid_points": trial_repaid,
        "trial_profit_points": trial_profit,
        "wallet_credit_points": wallet_credit,
        "remaining_units": remaining_units,
        "remaining_cost": remaining_cost,
    }


def trial_credit_payload(trial, *, days_valid):
    if not trial:
        return None
    return {
        "initial_points": int(trial["initial_points"] or 0),
        "available_points": int(trial["available_points"] or 0),
        "locked_points": int(trial["locked_points"] or 0),
        "deployed_points": int(trial["deployed_points"] or 0),
        "status": trial["status"],
        "activated_at": trial["activated_at"],
        "expires_at": trial["expires_at"],
        "reclaimed_at": trial["reclaimed_at"],
        "reclaim_blocked_reason": str(trial["reclaim_blocked_reason"] or "") if "reclaim_blocked_reason" in trial.keys() else "",
        "reclaim_blocked_at": trial["reclaim_blocked_at"] if "reclaim_blocked_at" in trial.keys() else None,
        "pending_reclaim": bool(str(trial["reclaim_blocked_reason"] or "").strip()) if "reclaim_blocked_reason" in trial.keys() else False,
        "days_valid": int(days_valid or 0),
    }
