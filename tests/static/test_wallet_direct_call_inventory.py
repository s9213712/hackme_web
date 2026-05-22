import json
from pathlib import Path

from scripts.security.gate.wallet_direct_call_inventory import build_payload, render_markdown, scan_repo


def _write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_wallet_direct_call_inventory_classifies_core_product_and_tests(tmp_path):
    _write(
        tmp_path / "services" / "points_chain" / "service.py",
        """
def core(conn, points_service):
    points_service._record_transaction(conn, user_id=1)
    conn.execute("UPDATE points_wallets SET soft_balance=? WHERE user_id=?", (1, 1))
""",
    )
    _write(
        tmp_path / "routes" / "comfyui.py",
        """
def bill(points_service):
    return points_service.spend_points(user_id=1, item_key='comfyui_txt2img_basic')
""",
    )
    _write(
        tmp_path / "routes" / "unsafe_wallet.py",
        """
def unsafe(conn):
    conn.execute("UPDATE points_wallets SET soft_balance=soft_balance+1 WHERE user_id=?", (1,))
""",
    )
    _write(
        tmp_path / "tests" / "points" / "test_seed.py",
        """
def seed(points):
    points.record_transaction(user_id=1, amount=1, direction='credit')
""",
    )

    findings = scan_repo(tmp_path, roots=["services", "routes"], include_tests=True)
    records = {(item.file, item.symbol, item.classification) for item in findings}

    assert ("services/points_chain/service.py", "_record_transaction", "allowed_internal_primitive") in records
    assert ("services/points_chain/service.py", "points_wallets", "allowed_internal_primitive") in records
    assert ("routes/comfyui.py", "spend_points", "blocker_product_bypass") in records
    assert ("routes/unsafe_wallet.py", "points_wallets", "blocker_product_bypass") in records
    assert ("tests/points/test_seed.py", "record_transaction", "test_helper") in records


def test_wallet_direct_call_inventory_reports_json_and_markdown(tmp_path):
    _write(
        tmp_path / "routes" / "games.py",
        """
def reward(points_service):
    points_service.record_transaction(user_id=1, amount=5, direction='credit')
""",
    )

    payload = build_payload(tmp_path, scan_repo(tmp_path, roots=["routes"]), include_tests=False)
    markdown = render_markdown(payload)

    encoded = json.dumps(payload)
    assert '"blocker_product_bypass"' in encoded
    assert "routes/games.py" in markdown
    assert "| blocker_product_bypass | ledger_service_call | `record_transaction` |" in markdown
    assert payload["summary"]["blockers"] == 1


def test_wallet_direct_call_inventory_ignores_read_only_wallet_sql(tmp_path):
    _write(
        tmp_path / "routes" / "economy.py",
        """
def read(conn):
    return conn.execute("SELECT soft_balance FROM points_wallets WHERE user_id=?", (1,)).fetchone()
""",
    )

    findings = scan_repo(tmp_path, roots=["routes"])

    assert findings == []


def test_wallet_direct_call_inventory_detects_direct_name_and_import_alias_calls(tmp_path):
    _write(
        tmp_path / "routes" / "direct_calls.py",
        """
from services.somewhere import record_transaction as rt, rollback_ledger as rb, spend_points

def direct():
    record_transaction(user_id=1)
    rt(user_id=1)
    spend_points(user_id=1)
    rollback_ledger(ledger_uuid='a')
    rb(ledger_uuid='b')
""",
    )

    findings = scan_repo(tmp_path, roots=["routes"])
    symbols = [item.symbol for item in findings]

    assert symbols.count("record_transaction") == 2
    assert symbols.count("rollback_ledger") == 2
    assert symbols.count("spend_points") == 1
    assert {item.classification for item in findings} == {"blocker_product_bypass"}
