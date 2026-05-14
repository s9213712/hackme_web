"""Trading bot modules.

`service.py` owns bot CRUD and orchestration, while the sibling modules keep
pure workflow, indicator, and audit reduction logic.
"""

from .service import (
    bot_condition_checks,
    bot_trigger_hit,
    get_bot_audit_dashboard,
    increase_trading_bot_max_runs,
    list_trading_bots,
    run_due_bot_audits,
    run_due_trading_bots,
    run_trading_bot_once,
    run_trading_bots,
    save_trading_bot,
    set_trading_bot_share_parameters,
)

__all__ = [
    "bot_condition_checks",
    "bot_trigger_hit",
    "get_bot_audit_dashboard",
    "increase_trading_bot_max_runs",
    "list_trading_bots",
    "run_due_bot_audits",
    "run_due_trading_bots",
    "run_trading_bot_once",
    "run_trading_bots",
    "save_trading_bot",
    "set_trading_bot_share_parameters",
]
