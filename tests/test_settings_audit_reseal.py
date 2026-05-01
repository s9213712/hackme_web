import sqlite3

from services import settings


def test_reenabling_audit_chain_marks_startup_reseal_required(tmp_path):
    db_path = tmp_path / "settings.db"
    old_state = dict(settings._STATE)
    old_system_settings = settings._SYSTEM_SETTINGS

    def get_db():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    try:
        settings.configure_settings_service(
            get_db=get_db,
            load_json=lambda path, default=None: default or {},
            base_dir=str(tmp_path),
        )
        conn = get_db()
        settings.init_system_settings_table(conn)
        settings._seed_missing_settings_to_db(conn)
        conn.commit()
        conn.close()
        settings.refresh_system_settings()

        disabled = settings.save_settings({"audit_chain_enabled": False, "audit_chain_reseal_required": False})
        assert disabled["audit_chain_enabled"] is False
        assert disabled["audit_chain_reseal_required"] is False

        enabled = settings.save_settings({"audit_chain_enabled": True})

        assert enabled["audit_chain_enabled"] is True
        assert enabled["audit_chain_reseal_required"] is True
    finally:
        settings._STATE.update(old_state)
        settings._SYSTEM_SETTINGS = old_system_settings
