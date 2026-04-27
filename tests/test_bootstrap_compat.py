import sqlite3
from pathlib import Path

from services import bootstrap


def _get_db_factory(db_path):
    def get_db():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    return get_db


def _ensure_session_columns(conn):
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(sessions)").fetchall()}
    if "is_revoked" not in cols:
        conn.execute("ALTER TABLE sessions ADD COLUMN is_revoked INTEGER NOT NULL DEFAULT 0")
    if "revoked_at" not in cols:
        conn.execute("ALTER TABLE sessions ADD COLUMN revoked_at TEXT")
    if "last_seen" not in cols:
        conn.execute("ALTER TABLE sessions ADD COLUMN last_seen TEXT")
    if "device_info" not in cols:
        conn.execute("ALTER TABLE sessions ADD COLUMN device_info TEXT")
    if "ip_country" not in cols:
        conn.execute("ALTER TABLE sessions ADD COLUMN ip_country TEXT")
    conn.execute("UPDATE sessions SET is_revoked=0 WHERE is_revoked IS NULL")
    conn.execute("UPDATE sessions SET last_seen=created_at WHERE last_seen IS NULL")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_expires_at ON sessions(expires_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_last_seen ON sessions(last_seen)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_revoked ON sessions(is_revoked)")


def _noop(*args, **kwargs):
    return None


def test_init_db_repairs_legacy_sessions_before_schema_replay(tmp_path, monkeypatch):
    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE schema_migrations (
            version     INTEGER PRIMARY KEY,
            name        TEXT NOT NULL,
            applied_at  TEXT NOT NULL
        );
        INSERT INTO schema_migrations (version, name, applied_at) VALUES
            (1, 'bootstrap schema_migrations metadata table', '2026-01-01T00:00:00'),
            (2, 'ensure legacy-compatible users columns', '2026-01-01T00:00:00'),
            (3, 'ensure violation_appeals columns', '2026-01-01T00:00:00'),
            (4, 'ensure system_settings baseline rows', '2026-01-01T00:00:00');

        CREATE TABLE sessions (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id      INTEGER NOT NULL,
            token_hash   TEXT    NOT NULL UNIQUE,
            ip_address   TEXT,
            user_agent   TEXT,
            expires_at   TEXT    NOT NULL,
            created_at   TEXT    NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE chat_rooms (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            name           TEXT    NOT NULL UNIQUE,
            owner_user_id  INTEGER,
            is_active      INTEGER NOT NULL DEFAULT 1,
            created_at     TEXT    NOT NULL DEFAULT (datetime('now'))
        );
        """
    )
    conn.commit()
    conn.close()

    schema_path = Path(__file__).resolve().parents[1] / "database" / "bootstrap.schema.sql"
    missing_json = str(tmp_path / "missing.json")
    original_state = dict(bootstrap._STATE)

    monkeypatch.setenv("HTML_LEARNING_ROOT_PASSWORD", "root")

    try:
        bootstrap.configure_bootstrap_service(
            get_db=_get_db_factory(str(db_path)),
            db_path=str(db_path),
            schema_path=str(schema_path),
            legacy_fail_log=missing_json,
            legacy_blocked_ips=missing_json,
            legacy_rate_limit=missing_json,
            legacy_audit_log=missing_json,
            chain_seed="seed",
            chain_hash=lambda prev_hash, entry_json: f"{prev_hash}:{len(entry_json)}",
            load_json=lambda path: {},
            normalize_text=lambda value: value if isinstance(value, str) else "",
            hash_password=lambda value: f"hash:{value}",
            audit=_noop,
            refresh_system_settings=_noop,
            init_system_settings_table=_noop,
            seed_missing_settings=_noop,
            import_legacy_settings_files=_noop,
            default_settings={},
        )
        bootstrap.init_db(
            ensure_secure_audit_columns=_noop,
            ensure_user_columns=_noop,
            ensure_appeal_columns=_noop,
            ensure_session_columns=_ensure_session_columns,
            ensure_security_support_schema=_noop,
            ensure_official_chat_room=_noop,
            hash_password=lambda value: f"hash:{value}",
        )
    finally:
        bootstrap._STATE.clear()
        bootstrap._STATE.update(original_state)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    session_cols = {row["name"] for row in conn.execute("PRAGMA table_info(sessions)").fetchall()}
    chat_room_cols = {row["name"] for row in conn.execute("PRAGMA table_info(chat_rooms)").fetchall()}
    user_cols = {row["name"] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
    login_location_cols = {row["name"] for row in conn.execute("PRAGMA table_info(login_locations)").fetchall()}
    member_rule_cols = {row["name"] for row in conn.execute("PRAGMA table_info(member_level_rules)").fetchall()}
    member_audit_cols = {row["name"] for row in conn.execute("PRAGMA table_info(member_level_audit)").fetchall()}
    proposal_cols = {row["name"] for row in conn.execute("PRAGMA table_info(moderation_proposals)").fetchall()}
    vote_cols = {row["name"] for row in conn.execute("PRAGMA table_info(moderation_votes)").fetchall()}
    moderation_action_cols = {row["name"] for row in conn.execute("PRAGMA table_info(moderation_actions)").fetchall()}
    mod_note_cols = {row["name"] for row in conn.execute("PRAGMA table_info(user_mod_notes)").fetchall()}
    reputation_event_cols = {row["name"] for row in conn.execute("PRAGMA table_info(reputation_events)").fetchall()}
    snapshot_cols = {row["name"] for row in conn.execute("PRAGMA table_info(snapshots)").fetchall()}
    restore_event_cols = {row["name"] for row in conn.execute("PRAGMA table_info(snapshot_restore_events)").fetchall()}
    server_mode_cols = {row["name"] for row in conn.execute("PRAGMA table_info(server_modes)").fetchall()}
    uploaded_file_cols = {row["name"] for row in conn.execute("PRAGMA table_info(uploaded_files)").fetchall()}
    encrypted_key_cols = {row["name"] for row in conn.execute("PRAGMA table_info(encrypted_file_keys)").fetchall()}
    scan_result_cols = {row["name"] for row in conn.execute("PRAGMA table_info(file_scan_results)").fetchall()}
    access_log_cols = {row["name"] for row in conn.execute("PRAGMA table_info(file_access_logs)").fetchall()}
    cloud_policy_cols = {row["name"] for row in conn.execute("PRAGMA table_info(cloud_drive_security_policies)").fetchall()}
    user_storage_cols = {row["name"] for row in conn.execute("PRAGMA table_info(user_storage)").fetchall()}
    storage_file_cols = {row["name"] for row in conn.execute("PRAGMA table_info(storage_files)").fetchall()}
    storage_quota_log_cols = {row["name"] for row in conn.execute("PRAGMA table_info(storage_quota_log)").fetchall()}
    album_cols = {row["name"] for row in conn.execute("PRAGMA table_info(albums)").fetchall()}
    album_file_cols = {row["name"] for row in conn.execute("PRAGMA table_info(album_files)").fetchall()}
    cloud_ref_cols = {row["name"] for row in conn.execute("PRAGMA table_info(cloud_file_refs)").fetchall()}
    grant_cols = {row["name"] for row in conn.execute("PRAGMA table_info(file_access_grants)").fetchall()}
    announcement_request_cols = {row["name"] for row in conn.execute("PRAGMA table_info(announcement_attachment_requests)").fetchall()}
    report_cols = {row["name"] for row in conn.execute("PRAGMA table_info(reports)").fetchall()}
    notification_cols = {row["name"] for row in conn.execute("PRAGMA table_info(notifications)").fetchall()}
    dm_thread_cols = {row["name"] for row in conn.execute("PRAGMA table_info(dm_threads)").fetchall()}
    dm_message_cols = {row["name"] for row in conn.execute("PRAGMA table_info(direct_messages)").fetchall()}
    blocked_cols = {row["name"] for row in conn.execute("PRAGMA table_info(blocked_users)").fetchall()}
    captcha_cols = {row["name"] for row in conn.execute("PRAGMA table_info(captcha_challenges)").fetchall()}
    integrity_finding_cols = {row["name"] for row in conn.execute("PRAGMA table_info(integrity_findings)").fetchall()}
    integrity_run_cols = {row["name"] for row in conn.execute("PRAGMA table_info(integrity_scan_runs)").fetchall()}
    integrity_manifest_cols = {row["name"] for row in conn.execute("PRAGMA table_info(integrity_manifest_versions)").fetchall()}
    migration_versions = [row["version"] for row in conn.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()]
    root_user = conn.execute("SELECT username, must_change_password, is_default_password FROM users WHERE username='root'").fetchone()
    conn.close()

    assert {"is_revoked", "revoked_at", "last_seen", "device_info", "ip_country"} <= session_cols
    assert "is_private" in chat_room_cols
    assert {
        "member_level", "base_level", "effective_level", "trust_score", "points", "reputation",
        "violation_score", "sanction_status", "sanction_until", "level_updated_at",
        "level_updated_by", "level_update_reason", "locked_until", "password_strength_score",
        "must_change_password", "is_default_password", "deleted_at",
        "avatar_file_id", "avatar_crop_json",
    } <= user_cols
    assert {"ip_hash", "login_at", "is_suspicious"} <= login_location_cols
    assert {
        "level", "can_post", "can_comment", "can_report", "daily_post_limit",
        "post_rate_limit_per_hour", "attachment_quota_mb", "report_weight",
        "downgrade_violation_threshold", "session_idle_timeout_minutes", "require_admin_approval",
    } <= member_rule_cols
    assert {"actor", "target_user", "old_base_level", "new_effective_level", "reason", "source"} <= member_audit_cols
    assert {"target_user_id", "action_type", "status", "required_votes", "approve_count"} <= proposal_cols
    assert {"proposal_id", "voter_user_id", "vote"} <= vote_cols
    assert {"moderator_id", "action_type", "target_type", "target_id"} <= moderation_action_cols
    assert {"moderator_id", "user_id", "note"} <= mod_note_cols
    assert {"user_id", "delta", "reason", "source_user_id"} <= reputation_event_cols
    assert {"id", "type", "status", "storage_path", "checksum"} <= snapshot_cols
    assert {"id", "snapshot_id", "restore_mode", "pre_restore_snapshot_id"} <= restore_event_cols
    assert {"current_mode", "previous_mode", "active_snapshot_id"} <= server_mode_cols
    assert {"privacy_mode", "risk_level", "scan_status", "client_scan_report_json"} <= uploaded_file_cols
    assert {"file_id", "recipient_user_id", "encrypted_file_key", "revoked_at"} <= encrypted_key_cols
    assert {"scanner_name", "result", "details_json"} <= scan_result_cols
    assert {"file_id", "actor_user_id", "action", "result"} <= access_log_cols
    assert {
        "scope", "block_unclean_downloads", "max_archive_files", "max_daily_downloads",
        "deep_archive_scan_enabled", "max_archive_depth", "office_macro_scan_enabled",
        "image_reencode_enabled", "image_reencode_max_pixels", "yara_enabled", "yara_command", "yara_rules_path",
    } <= cloud_policy_cols
    assert {"user_id", "quota_bytes", "used_bytes", "reserved_bytes", "file_count"} <= user_storage_cols
    assert {"file_id", "owner_user_id", "virtual_path", "is_trashed", "deleted_at"} <= storage_file_cols
    assert {"user_id", "delta_bytes", "before_used_bytes", "after_used_bytes", "source"} <= storage_quota_log_cols
    assert {"owner_user_id", "title", "visibility", "cover_file_id", "deleted_at"} <= album_cols
    assert {"album_id", "storage_file_id", "file_id", "sort_order", "caption"} <= album_file_cols
    assert {"file_id", "context_type", "context_id", "permission_snapshot_json"} <= cloud_ref_cols
    assert {"file_id", "granted_to_user_id", "context_type", "can_download", "revoked_at"} <= grant_cols
    assert {"file_id", "requested_by", "announcement_id", "status", "reviewed_by"} <= announcement_request_cols
    assert {"target_type", "reporter_user_id", "reported_user_id", "status", "claimed_by_user_id"} <= report_cols
    assert {"user_id", "type", "title", "body", "is_read", "read_at"} <= notification_cols
    assert {"participant_a_id", "participant_b_id", "created_by_user_id", "updated_at"} <= dm_thread_cols
    assert {"thread_id", "sender_user_id", "recipient_user_id", "is_read", "sender_deleted_at", "recipient_deleted_at"} <= dm_message_cols
    assert {"blocker_user_id", "blocked_user_id", "reason"} <= blocked_cols
    assert {"id", "mode", "answer_hash", "expires_at", "used_at"} <= captcha_cols
    assert {"file_path", "old_hash", "new_hash", "change_type", "status", "reviewed_by"} <= integrity_finding_cols
    assert {"started_at", "finished_at", "files_checked", "manifest_signature_valid"} <= integrity_run_cols
    assert {"manifest_hash", "manifest_signature", "approved_by"} <= integrity_manifest_cols
    assert migration_versions == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24]
    assert root_user["username"] == "root"
    assert root_user["must_change_password"] == 1
    assert root_user["is_default_password"] == 1


def test_init_db_allows_existing_root_password_without_bootstrap_env(tmp_path, monkeypatch):
    db_path = tmp_path / "existing-root.db"
    schema_path = Path(__file__).resolve().parents[1] / "database" / "bootstrap.schema.sql"

    conn = sqlite3.connect(db_path)
    conn.executescript(schema_path.read_text(encoding="utf-8"))
    now = "2026-01-01T00:00:00"
    cur = conn.execute(
        "INSERT INTO users (username, status, role, created_at, updated_at) VALUES (?, 'active', 'super_admin', ?, ?)",
        ("root", now, now),
    )
    conn.execute(
        "INSERT INTO user_passwords (user_id, password_hash, created_at) VALUES (?, ?, ?)",
        (cur.lastrowid, "hash:root", now),
    )
    conn.commit()
    conn.close()

    missing_json = str(tmp_path / "missing.json")
    original_state = dict(bootstrap._STATE)
    monkeypatch.delenv("HTML_LEARNING_ROOT_PASSWORD", raising=False)

    try:
        bootstrap.configure_bootstrap_service(
            get_db=_get_db_factory(str(db_path)),
            db_path=str(db_path),
            schema_path=str(schema_path),
            legacy_fail_log=missing_json,
            legacy_blocked_ips=missing_json,
            legacy_rate_limit=missing_json,
            legacy_audit_log=missing_json,
            chain_seed="seed",
            chain_hash=lambda prev_hash, entry_json: f"{prev_hash}:{len(entry_json)}",
            load_json=lambda path: {},
            normalize_text=lambda value: value if isinstance(value, str) else "",
            hash_password=lambda value: f"hash:{value}",
            audit=_noop,
            refresh_system_settings=_noop,
            init_system_settings_table=_noop,
            seed_missing_settings=_noop,
            import_legacy_settings_files=_noop,
            default_settings={},
        )
        bootstrap.init_db(
            ensure_secure_audit_columns=_noop,
            ensure_user_columns=_noop,
            ensure_appeal_columns=_noop,
            ensure_session_columns=_ensure_session_columns,
            ensure_security_support_schema=_noop,
            ensure_official_chat_room=_noop,
            hash_password=lambda value: f"hash:{value}",
        )
    finally:
        bootstrap._STATE.clear()
        bootstrap._STATE.update(original_state)

    conn = sqlite3.connect(db_path)
    count = conn.execute("SELECT COUNT(*) FROM user_passwords").fetchone()[0]
    conn.close()
    assert count == 1
