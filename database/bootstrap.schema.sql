CREATE TABLE IF NOT EXISTS chat_message_reports (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 message_id INTEGER NOT NULL REFERENCES chat_messages(id) ON DELETE CASCADE,
 room_id INTEGER NOT NULL REFERENCES chat_rooms(id) ON DELETE CASCADE,
 reporter_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 reported_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 reason TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'pending',
 reviewed_by TEXT,
 reviewed_at TEXT,
 review_note TEXT,
 created_at TEXT NOT NULL DEFAULT (datetime('now')),
 UNIQUE(message_id, reporter_user_id)
);

CREATE TABLE IF NOT EXISTS chat_messages (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            room_id        INTEGER NOT NULL REFERENCES chat_rooms(id) ON DELETE CASCADE,
            sender_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE SET NULL,
            content        TEXT    NOT NULL,
            is_blocked     INTEGER NOT NULL DEFAULT 0,
            blocked_reason TEXT,
            created_at     TEXT    NOT NULL DEFAULT (datetime('now'))
        );

CREATE TABLE IF NOT EXISTS chat_room_members (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            room_id    INTEGER NOT NULL REFERENCES chat_rooms(id) ON DELETE CASCADE,
            user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            joined_at  TEXT    NOT NULL DEFAULT (datetime('now')),
            UNIQUE(room_id, user_id)
        );

CREATE TABLE IF NOT EXISTS chat_rooms (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            name           TEXT    NOT NULL,
            owner_user_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            is_private     INTEGER NOT NULL DEFAULT 0,
            is_active      INTEGER NOT NULL DEFAULT 1,
            created_at     TEXT    NOT NULL DEFAULT (datetime('now'))
        );

CREATE TABLE IF NOT EXISTS csrf_tokens (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    token_hash   TEXT    NOT NULL UNIQUE,
    username     TEXT    NOT NULL,
    expires_at   TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS ip_blocks (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    ip_address     TEXT    NOT NULL UNIQUE,
    blocked_until  TEXT    NOT NULL,
    reason         TEXT,
    created_at     TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS login_attempts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER REFERENCES users(id) ON DELETE SET NULL,
    ip_address   TEXT,
    user_agent   TEXT,
    success      INTEGER NOT NULL DEFAULT 0,
    attempted_at TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS schema_migrations (
            version     INTEGER PRIMARY KEY,
            name        TEXT NOT NULL,
            applied_at  TEXT NOT NULL
        );

CREATE TABLE IF NOT EXISTS secure_audit (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ts          TEXT    NOT NULL,
            action      TEXT    NOT NULL,
            ip          TEXT,
            user        TEXT,
            success     INTEGER NOT NULL DEFAULT 0,
            ua          TEXT,
            detail      TEXT,
            chain_hash  TEXT    NOT NULL   /* SHA256HMAC(prev_hash || entry_json) */
        , prev_hash TEXT, entry_hash TEXT);

CREATE TABLE IF NOT EXISTS secure_violations (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id        INTEGER NOT NULL,
            username       TEXT    NOT NULL,
            points         INTEGER NOT NULL DEFAULT 1,
            reason         TEXT    NOT NULL,
            triggered_by   TEXT    NOT NULL,   /* 'system' | 'manager' | 'super_admin' */
            actor_username TEXT    NOT NULL,   /* 操作者 */
            created_at     TEXT    NOT NULL,
            prev_hash      TEXT    NOT NULL,   /* 上一筆記錄的 chain_hash */
            entry_hash     TEXT    NOT NULL    /* 本筆記錄的 hash */
        );

CREATE TABLE IF NOT EXISTS security_events (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type   TEXT    NOT NULL,   /* 'login_fail' | 'ip_block' | 'rate_limit' | '403_access' */
            ip_address   TEXT    NOT NULL,
            target_user  TEXT,
            detail       TEXT,
            created_at   TEXT    NOT NULL
        );

CREATE TABLE IF NOT EXISTS sessions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash   TEXT    NOT NULL UNIQUE,
    ip_address   TEXT,
    user_agent   TEXT,
    device_info  TEXT,
    ip_country   TEXT,
    expires_at   TEXT    NOT NULL,
    is_revoked   INTEGER NOT NULL DEFAULT 0,
    revoked_at   TEXT,
    last_seen    TEXT,
    created_at   TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS system_settings (
            key         TEXT PRIMARY KEY,
            value       TEXT NOT NULL,
            updated_at  TEXT NOT NULL,
            updated_by  TEXT
        );

CREATE TABLE IF NOT EXISTS user_passwords (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    password_hash   TEXT    NOT NULL,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS users (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    username   TEXT    NOT NULL UNIQUE,
    email      TEXT,
    -- Personal info (reserved for future expansion)
    real_name        TEXT,
    birthdate        TEXT,
    id_number        TEXT,
    phone            TEXT,
    -- Account status
    status     TEXT    NOT NULL DEFAULT 'active',
    member_level TEXT  NOT NULL DEFAULT 'normal',
    trust_score INTEGER NOT NULL DEFAULT 0,
    points INTEGER NOT NULL DEFAULT 0,
    reputation INTEGER NOT NULL DEFAULT 0,
    email_verified INTEGER NOT NULL DEFAULT 0,
    two_factor_enabled INTEGER NOT NULL DEFAULT 0,
    failed_login_count INTEGER NOT NULL DEFAULT 0,
    locked_until TEXT,
    password_strength_score INTEGER NOT NULL DEFAULT 0,
    last_login_at TEXT,
    password_changed_at TEXT,
    must_change_password INTEGER NOT NULL DEFAULT 0,
    is_default_password INTEGER NOT NULL DEFAULT 0,
    deleted_at TEXT,
    -- Timestamps
    created_at TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT    NOT NULL DEFAULT (datetime('now'))
, role TEXT NOT NULL DEFAULT 'user', nickname TEXT, blocked_until TEXT, violation_count INTEGER NOT NULL DEFAULT 0, chat_violation_warned INTEGER NOT NULL DEFAULT 0);

CREATE TABLE IF NOT EXISTS violation_appeals (
            id                      INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id                 INTEGER NOT NULL,
            username                TEXT    NOT NULL,
            latest_violation_id     INTEGER,
            violation_count_snapshot INTEGER NOT NULL DEFAULT 0,
            penalty_points          INTEGER NOT NULL DEFAULT 0,
            pre_status              TEXT    NOT NULL DEFAULT 'active',
            pre_role                TEXT    NOT NULL DEFAULT 'user',
            reason                  TEXT    NOT NULL,
            status                  TEXT    NOT NULL DEFAULT 'pending',  /* pending / approved / rejected */
            reviewed_by             TEXT,
            reviewed_at             TEXT,
            review_note             TEXT,
            created_at              TEXT    NOT NULL,
            CONSTRAINT fk_appeal_user FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );

CREATE INDEX IF NOT EXISTS idx_appeal_created_at ON violation_appeals(created_at);

CREATE INDEX IF NOT EXISTS idx_appeal_status     ON violation_appeals(status);

CREATE INDEX IF NOT EXISTS idx_appeal_user      ON violation_appeals(user_id);

CREATE INDEX IF NOT EXISTS idx_chat_messages_room     ON chat_messages(room_id);

CREATE INDEX IF NOT EXISTS idx_chat_messages_time     ON chat_messages(created_at);

CREATE INDEX IF NOT EXISTS idx_chat_reports_message ON chat_message_reports(message_id);

CREATE INDEX IF NOT EXISTS idx_chat_reports_status ON chat_message_reports(status);

CREATE INDEX IF NOT EXISTS idx_chat_room_members_room ON chat_room_members(room_id);

CREATE INDEX IF NOT EXISTS idx_chat_room_members_user ON chat_room_members(user_id);

CREATE INDEX IF NOT EXISTS idx_csrf_token_hash ON csrf_tokens(token_hash);
CREATE INDEX IF NOT EXISTS idx_csrf_expires_at ON csrf_tokens(expires_at);

CREATE INDEX IF NOT EXISTS idx_ip_blocks_ip ON ip_blocks(ip_address);
CREATE INDEX IF NOT EXISTS idx_ip_blocks_until ON ip_blocks(blocked_until);

CREATE INDEX IF NOT EXISTS idx_login_attempts_ip    ON login_attempts(ip_address);

CREATE INDEX IF NOT EXISTS idx_login_attempts_time   ON login_attempts(attempted_at);

CREATE INDEX IF NOT EXISTS idx_login_attempts_user   ON login_attempts(user_id);

CREATE INDEX IF NOT EXISTS idx_sec_event_ip    ON security_events(ip_address);

CREATE INDEX IF NOT EXISTS idx_sec_event_time  ON security_events(created_at);

CREATE INDEX IF NOT EXISTS idx_sec_event_type  ON security_events(event_type);
CREATE INDEX IF NOT EXISTS idx_sec_event_type_ip_time ON security_events(event_type, ip_address, created_at);

CREATE INDEX IF NOT EXISTS idx_sec_viol_actor  ON secure_violations(actor_username);

CREATE INDEX IF NOT EXISTS idx_sec_viol_reason  ON secure_violations(reason);

CREATE INDEX IF NOT EXISTS idx_sec_viol_user   ON secure_violations(user_id);

CREATE INDEX IF NOT EXISTS idx_secure_audit_action ON secure_audit(action);

CREATE INDEX IF NOT EXISTS idx_secure_audit_ts    ON secure_audit(ts);

CREATE INDEX IF NOT EXISTS idx_secure_audit_user   ON secure_audit(user);

CREATE INDEX IF NOT EXISTS idx_sessions_token_hash ON sessions(token_hash);

CREATE INDEX IF NOT EXISTS idx_sessions_expires_at ON sessions(expires_at);
CREATE INDEX IF NOT EXISTS idx_sessions_last_seen ON sessions(last_seen);

CREATE INDEX IF NOT EXISTS idx_sessions_revoked ON sessions(is_revoked);

CREATE INDEX IF NOT EXISTS idx_sessions_user_id     ON sessions(user_id);
