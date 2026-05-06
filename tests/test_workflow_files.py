import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_trading_workflow_templates_live_under_workflows_directory():
    workflow_root = ROOT / "workflows"
    system_dir = workflow_root / "system"
    custom_dir = workflow_root / "custom"
    assert system_dir.is_dir()
    assert custom_dir.is_dir()

    expected = {
        "dip_buy",
        "breakout_buy",
        "stop_loss",
        "rsi_scale",
        "ma_pullback",
        "bollinger_reversion",
        "kd_momentum",
        "risk_guard",
    }
    found = {path.stem for path in system_dir.glob("*.json")}
    assert expected <= found

    for path in system_dir.glob("*.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["scope"] == "system"
        explanation = payload.get("explanation")
        assert isinstance(explanation, dict), path.name
        for key in ("purpose", "entry_conditions", "actions", "risk_notes", "best_for", "tuning"):
            assert explanation.get(key), f"{path.name} missing explanation.{key}"
        assert payload["workflow"]["strategy_kind"] == "workflow_graph"
        assert payload["workflow"]["nodes"]
        assert payload["workflow"]["edges"] or payload["workflow"]["start_node_id"] == "start"


def test_workflow_custom_files_are_runtime_data_not_committed_templates():
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "!workflows/system/*.json" in gitignore
    assert "workflows/custom/*" in gitignore
    assert "!workflows/custom/.gitkeep" in gitignore

    routes = (ROOT / "routes" / "trading.py").read_text(encoding="utf-8")
    frontend = (ROOT / "public" / "js" / "56-trading.js").read_text(encoding="utf-8")
    index = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
    assert '"/api/trading/workflow-templates"' in routes
    assert '"/api/trading/workflow-templates/custom"' in routes
    assert '"/api/trading/workflow-editor/backtest"' in routes
    assert '"/trading/workflow-templates"' in frontend
    assert '"/trading/workflow-templates/custom"' in frontend
    assert 'id="trading-workflow-custom-save-btn"' in index
