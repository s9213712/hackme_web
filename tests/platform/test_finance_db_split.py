import sqlite3

from services.server.finance_database import get_finance_db, migrate_finance_tables_if_needed


def test_finance_db_exposes_core_users_as_temp_view(tmp_path):
    core_path = tmp_path / "database.db"
    finance_path = tmp_path / "finance.db"
    core = sqlite3.connect(core_path)
    try:
        core.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT NOT NULL, role TEXT)")
        core.execute("INSERT INTO users (id, username, role) VALUES (1, 'root', 'super_admin')")
        core.commit()
    finally:
        core.close()

    conn = get_finance_db(finance_path, core_db_path=core_path)
    try:
        conn.execute("CREATE TABLE points_ledger (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, amount INTEGER)")
        conn.execute("INSERT INTO points_ledger (user_id, amount) VALUES (1, 25)")
        row = conn.execute(
            "SELECT u.username, l.amount FROM points_ledger l JOIN users u ON u.id=l.user_id"
        ).fetchone()
        assert row["username"] == "root"
        assert row["amount"] == 25
    finally:
        conn.close()

    raw = sqlite3.connect(finance_path)
    try:
        assert raw.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'").fetchone() is None
    finally:
        raw.close()


def test_finance_migration_copies_points_and_trading_once(tmp_path):
    core_path = tmp_path / "database.db"
    finance_path = tmp_path / "finance.db"
    core = sqlite3.connect(core_path)
    try:
        core.executescript(
            """
            CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT NOT NULL);
            CREATE TABLE points_ledger (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ledger_uuid TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                amount INTEGER NOT NULL
            );
            CREATE TABLE trading_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_uuid TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                market_symbol TEXT NOT NULL
            );
            INSERT INTO users VALUES (1, 'root');
            INSERT INTO points_ledger (ledger_uuid, user_id, amount) VALUES ('l1', 1, 10);
            INSERT INTO trading_orders (order_uuid, user_id, market_symbol) VALUES ('o1', 1, 'BTC/POINTS');
            """
        )
        core.commit()
    finally:
        core.close()

    first = migrate_finance_tables_if_needed(core_db_path=core_path, finance_db_path=finance_path)
    second = migrate_finance_tables_if_needed(core_db_path=core_path, finance_db_path=finance_path)

    assert first["ok"] is True
    assert first["skipped"] is False
    assert second["skipped"] is True
    finance = sqlite3.connect(finance_path)
    try:
        assert finance.execute("SELECT COUNT(*) FROM points_ledger").fetchone()[0] == 1
        assert finance.execute("SELECT COUNT(*) FROM trading_orders").fetchone()[0] == 1
        assert finance.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'").fetchone() is None
    finally:
        finance.close()
