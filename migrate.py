#!/usr/bin/env python3
"""
Migration: Flat users table → Normalized 3NF schema
- Backs up existing database.db → database.db.bak
- Creates new normalized tables
- Migrates existing user data
"""

import os, sqlite3, shutil, json
from datetime import datetime

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
DB_PATH    = os.path.join(BASE_DIR, "database.db")
DB_BAK     = DB_PATH + ".bak"

SCHEMA = """
-- users: core account identity
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
    -- Timestamps
    created_at TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- user_passwords: password history (currently 1 per user)
CREATE TABLE IF NOT EXISTS user_passwords (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    password_hash   TEXT    NOT NULL,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- login_attempts: full audit trail
CREATE TABLE IF NOT EXISTS login_attempts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER REFERENCES users(id) ON DELETE SET NULL,
    ip_address   TEXT,
    user_agent   TEXT,
    success      INTEGER NOT NULL DEFAULT 0,
    attempted_at TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- sessions: active sessions (replaces Fernet token storage)
CREATE TABLE IF NOT EXISTS sessions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash   TEXT    NOT NULL UNIQUE,
    ip_address   TEXT,
    user_agent   TEXT,
    expires_at   TEXT    NOT NULL,
    created_at   TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_sessions_token_hash ON sessions(token_hash);
CREATE INDEX IF NOT EXISTS idx_sessions_user_id     ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_login_attempts_user   ON login_attempts(user_id);
CREATE INDEX IF NOT EXISTS idx_login_attempts_ip    ON login_attempts(ip_address);
CREATE INDEX IF NOT EXISTS idx_login_attempts_time   ON login_attempts(attempted_at);
"""

def migrate():
    if not os.path.exists(DB_PATH):
        print("database.db not found — nothing to migrate.")
        return

    # Back up
    shutil.copy2(DB_PATH, DB_BAK)
    print(f"✓ Backed up → {DB_BAK}")

    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()

    # Inspect existing columns
    cur.execute("PRAGMA table_info(users)")
    existing_cols = {row[1] for row in cur.fetchall()}
    print(f"✓ Existing users columns: {existing_cols}")

    # Read existing data
    cur.execute("SELECT username, password FROM users")
    existing_rows = cur.fetchall()
    print(f"✓ Found {len(existing_rows)} existing user(s): {[r[0] for r in existing_rows]}")

    # Wipe old flat table, recreate normalized
    cur.execute("DROP TABLE IF EXISTS users")
    conn.commit()

    # Create new schema
    cur.executescript(SCHEMA)
    conn.commit()
    print("✓ New schema created")

    # Migrate: re-insert users
    for username, pw_hash in existing_rows:
        cur.execute(
            "INSERT INTO users (username, status, created_at, updated_at) VALUES (?, 'active', datetime('now'), datetime('now'))",
            (username,)
        )
        user_row = cur.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
        if user_row and pw_hash:
            cur.execute(
                "INSERT INTO user_passwords (user_id, password_hash) VALUES (?, ?)",
                (user_row[0], pw_hash)
            )
    conn.commit()
    print(f"✓ Migrated {len(existing_rows)} user(s) + passwords")
    conn.close()
    print("✓ Migration complete!")
    print(f"\n  Restored DB: {DB_PATH}")
    print(f"  Backup:      {DB_BAK}")

if __name__ == "__main__":
    migrate()
