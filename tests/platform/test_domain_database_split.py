import json
import sqlite3

from services.server.domain_databases import analyze_database, export_domain_tables, export_domains_to_database, table_domain


def _seed_main_db(path):
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY,
                username TEXT NOT NULL
            );
            CREATE TABLE uploaded_files (
                id TEXT PRIMARY KEY,
                owner_user_id INTEGER NOT NULL,
                storage_path TEXT NOT NULL,
                privacy_mode TEXT NOT NULL,
                risk_level TEXT NOT NULL,
                scan_status TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE encrypted_file_keys (
                id TEXT PRIMARY KEY,
                file_id TEXT NOT NULL,
                recipient_user_id INTEGER NOT NULL,
                encrypted_file_key TEXT NOT NULL,
                wrapped_by TEXT NOT NULL,
                key_version INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE points_ledger (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ledger_uuid TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                amount INTEGER NOT NULL,
                ledger_hash TEXT NOT NULL
            );
            CREATE TABLE trading_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_uuid TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                market_symbol TEXT NOT NULL
            );
            CREATE TABLE job_center_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_uuid TEXT NOT NULL,
                job_type TEXT NOT NULL,
                title TEXT NOT NULL,
                source_module TEXT NOT NULL,
                status TEXT NOT NULL,
                progress_percent INTEGER NOT NULL,
                stage TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE misc_table (
                id INTEGER PRIMARY KEY,
                value TEXT
            );
            INSERT INTO users VALUES (1, 'root');
            INSERT INTO uploaded_files VALUES ('f1', 1, '/x.bin', 'e2ee', 'unknown_encrypted', 'skipped', 12, '2026-05-24T00:00:00');
            INSERT INTO encrypted_file_keys VALUES ('k1', 'f1', 1, 'wrapped', 'browser_passphrase_pbkdf2_v2', 1, '2026-05-24T00:00:00');
            INSERT INTO points_ledger (ledger_uuid, user_id, amount, ledger_hash) VALUES ('l1', 1, 100, 'h1');
            INSERT INTO trading_orders (order_uuid, user_id, market_symbol) VALUES ('o1', 1, 'BTC/POINTS');
            INSERT INTO job_center_jobs (job_uuid, job_type, title, source_module, status, progress_percent, stage, created_at, updated_at)
            VALUES ('j1', 'probe', 'Probe', 'pytest', 'succeeded', 100, 'done', '2026-05-24T00:00:00', '2026-05-24T00:00:00');
            INSERT INTO misc_table VALUES (1, 'left in main');
            """
        )
        conn.commit()
    finally:
        conn.close()


def test_domain_table_classifier_marks_sensitive_domains():
    assert table_domain("encrypted_file_keys") == "storage"
    assert table_domain("points_ledger") == "points_chain"
    assert table_domain("trading_orders") == "trading"
    assert table_domain("job_center_jobs") == "jobs"
    assert table_domain("csrf_tokens") == "already_split:auth"
    assert table_domain("not_known") == "unclassified"


def test_analyze_database_groups_existing_tables(tmp_path):
    db_path = tmp_path / "database.db"
    _seed_main_db(db_path)

    report = analyze_database(db_path)

    assert report["table_count"] == 7
    assert report["domains"]["storage"]["tables"] == 2
    assert report["domains"]["points_chain"]["rows"] == 1
    assert report["domains"]["trading"]["rows"] == 1
    assert report["domains"]["jobs"]["rows"] == 1
    assert report["domains"]["unclassified"]["tables"] == 1


def test_export_domain_tables_copies_rows_and_manifest_hashes(tmp_path):
    db_path = tmp_path / "database.db"
    out_dir = tmp_path / "split"
    _seed_main_db(db_path)

    manifest = export_domain_tables(
        db_path,
        out_dir,
        domains={"storage", "points_chain", "trading", "jobs"},
        overwrite=True,
    )

    assert (out_dir / "storage_catalog.db").exists()
    assert (out_dir / "points_chain.db").exists()
    assert (out_dir / "trading.db").exists()
    assert (out_dir / "jobs.db").exists()
    assert (out_dir / "domain_split_manifest.json").exists()
    assert manifest["domains"]["storage"]["tables"]["encrypted_file_keys"]["rows"] == 1
    assert manifest["domains"]["points_chain"]["tables"]["points_ledger"]["rows"] == 1
    assert manifest["domains"]["trading"]["tables"]["trading_orders"]["rows"] == 1
    assert manifest["domains"]["jobs"]["tables"]["job_center_jobs"]["rows"] == 1

    storage = sqlite3.connect(out_dir / "storage_catalog.db")
    try:
        assert storage.execute("SELECT encrypted_file_key FROM encrypted_file_keys").fetchone()[0] == "wrapped"
        assert storage.execute("SELECT privacy_mode FROM uploaded_files").fetchone()[0] == "e2ee"
    finally:
        storage.close()

    stored_manifest = json.loads((out_dir / "domain_split_manifest.json").read_text(encoding="utf-8"))
    assert stored_manifest["domains"]["storage"]["sha256"] == manifest["domains"]["storage"]["sha256"]
    assert any(row["table"] == "misc_table" for row in manifest["skipped"])


def test_export_domains_to_database_keeps_finance_domains_together(tmp_path):
    db_path = tmp_path / "database.db"
    finance_path = tmp_path / "finance.db"
    _seed_main_db(db_path)

    manifest = export_domains_to_database(
        db_path,
        finance_path,
        domains={"points_chain", "trading"},
        overwrite=True,
    )

    assert finance_path.exists()
    assert manifest["table_count"] == 2
    assert manifest["row_count"] == 2
    assert manifest["tables"]["points_ledger"]["rows"] == 1
    assert manifest["tables"]["trading_orders"]["rows"] == 1
    finance = sqlite3.connect(finance_path)
    try:
        assert finance.execute("SELECT ledger_uuid FROM points_ledger").fetchone()[0] == "l1"
        assert finance.execute("SELECT order_uuid FROM trading_orders").fetchone()[0] == "o1"
        assert finance.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'").fetchone() is None
    finally:
        finance.close()
