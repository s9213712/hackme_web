from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_trading_backtest_20000_probe_includes_latest_regressions():
    probe = (ROOT / "scripts" / "trading_backtest_20000_probe.py").read_text(encoding="utf-8")

    assert "single_candle_rejected_without_silent_fetch" in probe
    assert "workflow_flat_bollinger_guard" in probe
    assert "backtest_outlier_jump_skipped" in probe
    assert 'choices=("all", "conditional", "dca", "workflow", "grid", "route", "over_limit", "flat_bollinger", "outlier_jump", "single_candle_rejected")' in probe
    assert 'payload.get("max_backtest_candles_per_batch") == 10_000' in probe


def test_workflow_template_validation_includes_flat_sequence_guard():
    script = (ROOT / "security" / "trading_workflow_template_validation.py").read_text(encoding="utf-8")

    assert 'FLAT_SEQUENCE_GUARD_TEMPLATE_IDS = {"bollinger_reversion", "swing_bb_ma50"}' in script
    assert "def validate_flat_sequence_guard" in script
    assert '"flat_sequence_guard": flat_guard' in script
    assert '"workflow_graph templates are validated via trigger scenarios, flat-sequence guards, and engine backtest sanity checks"' in script


def test_trading_exchange_validation_includes_avg_cost_sanity_and_clean_workflow_case():
    script = (ROOT / "security" / "trading_exchange_validation.py").read_text(encoding="utf-8")

    assert 'workflow_tmp = Path(tmp) / "workflow_case"' in script
    assert "workflow bot honors nested condition and does not repeat exhausted scaling steps" in script
    assert "incremental spot buys preserve sane average cost accounting" in script
    assert "ETH/POINTS live price is 1000; average cost should stay in a sane range after DCA and conditional buys." in script
