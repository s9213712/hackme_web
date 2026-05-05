from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_functional_smoke_waits_for_reset_restart_reconnect():
    script = (ROOT / "security" / "run_functional_smoke.sh").read_text(encoding="utf-8")
    docs = (ROOT / "docs" / "security" / "FUNCTIONAL_SMOKE.md").read_text(encoding="utf-8")

    assert 'RESET_OFFLINE_TIMEOUT="${RESET_OFFLINE_TIMEOUT:-20}"' in script
    assert 'RESET_RECONNECT_TIMEOUT="${RESET_RECONNECT_TIMEOUT:-180}"' in script
    assert "wait_for_restart_reconnect()" in script
    assert 'server_started_at "$RAW_DIR/reset_before_version.json"' in script
    assert 'request "server reset runtime state"' in script
    assert 'wait_for_restart_reconnect "server reset restart reconnect"' in script
    assert 'data.get("started_at", "")' in script
    assert "server did not go offline within" in script
    assert "offline phase" in script
    assert "server did not reconnect with a new started_at within" in script
    assert "RESET_OFFLINE_TIMEOUT" in docs
    assert "RESET_RECONNECT_TIMEOUT" in docs
    assert "20 秒內觀察連線失敗" in docs
    assert "started_at" in docs
    assert "3 分鐘內重新連線" in docs


def test_functional_smoke_covers_latest_trading_and_announcement_paths():
    script = (ROOT / "security" / "run_functional_smoke.sh").read_text(encoding="utf-8")
    docs = (ROOT / "docs" / "security" / "FUNCTIONAL_SMOKE.md").read_text(encoding="utf-8")

    assert 'request "trading live price" "GET" "/api/trading/live-price?market=ETH/POINTS" "200"' in script
    assert 'request "trading reference prices" "GET" "/api/trading/reference-prices?market=ETH/POINTS&interval=15m&limit=24" "200"' in script
    assert 'request "trading grid preview" "POST" "/api/trading/grid/preview" "200"' in script
    assert 'request "trading root price fusion status" "GET" "/api/root/trading/price-fusion-status?market_symbol=ETH/POINTS" "200"' in script
    assert 'request "trading root bot audit dashboard" "GET" "/api/root/trading/bot-audit/dashboard?limit=10" "200"' in script
    assert 'request "trading root bot audit manual run" "POST" "/api/root/trading/bot-audit/run" "200"' in script
    assert 'request "community edit announcement" "PUT" "/api/community/announcements/${ANNOUNCEMENT_ID}" "200"' in script
    assert '"price_type" in data and "source" in data and "confidence" in data and "stale" in data and "degraded" in data and "provider_count" in data' in script
    assert '"reference_price_context" in data and "risk_grade_price_context" in data' in script
    assert '"connected" in data and "fallback" in data and "last_update_at" in data and "exclusion_reason" in data and "transport_state" in data' in script
    assert '"transport_state" in data.get("status", {}) and "connected" in data.get("status", {}) and "fallback" in data.get("status", {}) and "stale" in data.get("status", {}) and "confidence" in data.get("status", {}) and "provider_count" in data.get("status", {}) and "last_update_at" in data.get("status", {}) and "exclusion_reason" in data.get("status", {})' in script
    assert "trading extras" in docs
    assert "announcement create/edit" in docs
