from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_functional_smoke_waits_for_reset_restart_reconnect():
    script = (ROOT / "security" / "run_functional_smoke.sh").read_text(encoding="utf-8")
    docs = (ROOT / "security" / "FUNCTIONAL_SMOKE.md").read_text(encoding="utf-8")

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
    assert "20 秒內必須觀察到連線失敗" in docs
    assert "3 分鐘內重新連線" in docs
