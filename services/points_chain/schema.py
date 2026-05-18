import hashlib
import hmac
import json
import os
import re
import shutil
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from services.core.sqlite_safe import table_columns as safe_table_columns


DISPLAY_CURRENCY = "points"
INTERNAL_CURRENCY = "soft"
CURRENCIES = {DISPLAY_CURRENCY, "soft", "hard"}
LEGACY_CURRENCY_RE = re.compile(r"\b(?:soft|hard)\b", re.IGNORECASE)
LEDGER_DIRECTIONS = {"credit", "debit", "freeze", "unfreeze", "reverse", "transfer_in", "transfer_out"}
LEDGER_STATUSES = {"pending", "confirmed", "reversed", "disputed", "frozen"}
WALLET_STATUSES = {"active", "frozen", "limited", "closed"}
DEFAULT_BLOCK_INTERVAL_SECONDS = 24 * 60 * 60
DEFAULT_BLOCK_LEDGER_THRESHOLD = 30
DEFAULT_BLOCK_MAX_INTERVAL_SECONDS = 24 * 60 * 60
SIGNUP_BONUS_POINTS = 100
ADMIN_INITIAL_POINTS = 1000
USER_INITIAL_POINTS = 100
ADMIN_WEEKLY_SALARY_POINTS = 250
BIRTHDAY_GIFT_POINTS = 500
POINTS_CHAIN_SCHEMA_VERSION = 1
DEFAULT_BACKUP_INTERVAL_MINUTES = 60
DEFAULT_BACKUP_KEEP_RECENT = 5
DEFAULT_BACKUP_KEEP_DAILY = 7
DEFAULT_BACKUP_KEEP_WEEKLY = 4
MAX_LEDGER_METADATA_JSON_BYTES = 4096
PRICE_ITEM_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_:-]{1,79}$")
PRICE_CATEGORY_RE = re.compile(r"^[a-z][a-z0-9_:-]{1,79}$")

DEFAULT_RULES = (
    ("daily_login", "daily_login", "credit", "soft", 5, 5, 5, 24 * 60 * 60, 0, 0, 0, 1, 0, {"label": "每日登入"}),
    ("create_post", "forum_post_reward", "credit", "soft", 3, 3, 30, 0, 1, 0, 0, 1, 0, {"label": "發文獎勵"}),
    ("create_comment", "forum_comment_reward", "credit", "soft", 1, 1, 50, 60, 1, 0, 0, 1, 0, {"label": "留言獎勵"}),
    ("receive_like", "content_like_reward", "credit", "soft", 1, 1, 25, 0, 0, 0, 0, 1, 0, {"label": "被按讚獎勵"}),
    ("quality_post_bonus", "quality_post_bonus", "credit", "soft", 20, 20, 100, 0, 1, 1, 0, 1, 1, {"label": "優質文章獎勵"}),
    ("valid_bug_report_low", "bug_bounty_low", "credit", "soft", 50, 50, 150, 0, 0, 1, 0, 1, 1, {"label": "低風險有效 bug"}),
    ("valid_bug_report_medium", "bug_bounty_medium", "credit", INTERNAL_CURRENCY, 50, 50, 150, 0, 0, 1, 0, 1, 1, {"label": "中風險有效 bug"}),
    ("valid_bug_report_high", "bug_bounty_high", "credit", INTERNAL_CURRENCY, 200, 200, 400, 0, 0, 1, 0, 1, 1, {"label": "高風險有效 bug"}),
    ("game_daily_quest", "game_daily_quest", "credit", "soft", 10, 10, 10, 24 * 60 * 60, 0, 0, 0, 1, 0, {"label": "遊戲每日任務"}),
    ("marketplace_sale_income", "marketplace_sale_income", "credit", INTERNAL_CURRENCY, 0, 0, None, 0, 0, 1, 0, 1, 1, {"label": "商城收入"}),
    ("new_user_signup_bonus", "new_user_signup_bonus", "credit", INTERNAL_CURRENCY, SIGNUP_BONUS_POINTS, SIGNUP_BONUS_POINTS, SIGNUP_BONUS_POINTS, 0, 0, 0, 0, 1, 1, {"label": "新註冊禮"}),
    ("birthday_gift", "birthday_gift", "credit", INTERNAL_CURRENCY, BIRTHDAY_GIFT_POINTS, BIRTHDAY_GIFT_POINTS, BIRTHDAY_GIFT_POINTS, 0, 0, 0, 0, 1, 1, {"label": "生日禮金"}),
    ("admin_initial_grant", "admin_initial_grant", "credit", INTERNAL_CURRENCY, ADMIN_INITIAL_POINTS, ADMIN_INITIAL_POINTS, ADMIN_INITIAL_POINTS, 0, 0, 0, 0, 1, 1, {"label": "管理帳號創始補助"}),
    ("user_initial_grant", "user_initial_grant", "credit", INTERNAL_CURRENCY, USER_INITIAL_POINTS, USER_INITIAL_POINTS, USER_INITIAL_POINTS, 0, 0, 0, 0, 1, 1, {"label": "一般帳號創始補助"}),
    ("admin_weekly_salary", "admin_weekly_salary", "credit", INTERNAL_CURRENCY, ADMIN_WEEKLY_SALARY_POINTS, ADMIN_WEEKLY_SALARY_POINTS, ADMIN_WEEKLY_SALARY_POINTS, 0, 0, 0, 0, 1, 1, {"label": "管理帳號週薪"}),
)

DEFAULT_PRICE_CATALOG = (
    ("post_cost_standard", "一般發文成本", "forum", "soft", 1, 0, 1, 10, 1, {"description": "防止洗版的基本回收"}),
    ("post_pin_24h", "文章置頂 24 小時", "forum", "soft", 100, 0, 50, 300, 1, {}),
    ("cloud_storage_1gb_30d", "雲端容量 1GB / 7 天", "cloud_drive", "soft", 100, 0, 50, 500, 1, {"storage_bytes": 1024 ** 3, "duration_days": 7, "label": "雲端容量 1GB / 7 天"}),
    ("comfyui_txt2img_basic", "基礎生圖一次", "comfyui", "soft", 5, 1, 1, 25, 1, {}),
    ("comfyui_txt2img_highres", "高解析生圖一次", "comfyui", INTERNAL_CURRENCY, 2, 1, 1, 20, 1, {}),
    ("comfyui_batch_10", "批次生圖 10 張", "comfyui", INTERNAL_CURRENCY, 15, 1, 5, 80, 1, {}),
    ("server_rental_cpu_1h", "CPU Server 1 小時", "server_rental", INTERNAL_CURRENCY, 5, 1, 2, 30, 1, {}),
    ("server_rental_gpu_1h", "GPU Server 1 小時", "server_rental", INTERNAL_CURRENCY, 50, 1, 20, 200, 1, {}),
    ("game_virtual_item_common", "普通虛寶", "game", "soft", 20, 0, 5, 100, 1, {}),
    ("game_virtual_item_premium", "高級虛寶", "game", INTERNAL_CURRENCY, 5, 0, 1, 50, 1, {}),
    ("username_change", "改名", "account", "soft", 200, 0, 100, 1000, 1, {}),
    ("profile_decoration", "個人頁裝飾", "account", "soft", 50, 0, 10, 250, 1, {}),
)


def normalize_currency_type(currency_type=None):
    currency = str(currency_type or DISPLAY_CURRENCY).strip().lower()
    if currency not in CURRENCIES:
        raise ValueError("currency_type must be points")
    return INTERNAL_CURRENCY


def display_currency_type(currency_type=None):
    return DISPLAY_CURRENCY


def public_currency_text(value):
    if not isinstance(value, str):
        return value
    return LEGACY_CURRENCY_RE.sub(DISPLAY_CURRENCY, value)


def public_currency_payload(value):
    if isinstance(value, dict):
        return {key: public_currency_payload(item) for key, item in value.items()}
    if isinstance(value, list):
        return [public_currency_payload(item) for item in value]
    return public_currency_text(value)


def utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_utc_timestamp(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_text(value):
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def _json_loads(raw, fallback=None):
    if not raw:
        return fallback if fallback is not None else {}
    try:
        value = json.loads(raw)
        return value if isinstance(value, (dict, list)) else (fallback if fallback is not None else {})
    except Exception:
        return fallback if fallback is not None else {}


def _json_dumps(value):
    return canonical_json(value if value is not None else {})


def _metadata_json_checked(value, *, label):
    raw = _json_dumps(value if value is not None else {})
    if len(raw.encode("utf-8")) > MAX_LEDGER_METADATA_JSON_BYTES:
        raise ValueError(f"{label} is too large")
    return raw


def actor_value(actor, key, default=None):
    if not actor:
        return default
    if hasattr(actor, "keys"):
        return actor[key] if key in actor.keys() else default
    return actor.get(key, default) if hasattr(actor, "get") else default


def table_columns(conn, table):
    try:
        return safe_table_columns(conn, table)
    except Exception:
        return set()


def public_account_id(chain_secret, user_id):
    secret_bytes = chain_secret.encode("utf-8") if isinstance(chain_secret, str) else bytes(chain_secret or b"")
    return hmac.new(secret_bytes, str(int(user_id)).encode("utf-8"), hashlib.sha256).hexdigest()


def metadata_hash(public_metadata=None, private_metadata=None, sensitive_metadata_encrypted=""):
    payload = {
        "private_metadata_digest": sha256_text(_json_dumps(private_metadata or {})),
        "public_metadata": public_metadata or {},
        "sensitive_metadata_ciphertext_digest": sha256_text(sensitive_metadata_encrypted or ""),
    }
    return sha256_text(canonical_json(payload))


def ledger_hash_payload(row):
    return {
        "ledger_uuid": row["ledger_uuid"],
        "public_account_id": row["public_account_id"],
        "currency_type": row["currency_type"],
        "direction": row["direction"],
        "amount": int(row["amount"]),
        "balance_before": int(row["balance_before"]),
        "balance_after": int(row["balance_after"]),
        "action_type": row["action_type"],
        "reference_type": row["reference_type"],
        "reference_id": row["reference_id"],
        "metadata_hash": row["metadata_hash"],
        "previous_ledger_hash": row["previous_ledger_hash"],
        "created_at": row["created_at"],
    }


def compute_ledger_hash(row):
    return sha256_text(canonical_json(ledger_hash_payload(row)))


def create_points_ledger_immutable_trigger(conn):
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_points_ledger_core_immutable
        BEFORE UPDATE OF ledger_uuid, user_id, public_account_id, currency_type, direction, amount,
                         balance_before, balance_after, action_type, reference_type, reference_id,
                         idempotency_key, reason, public_metadata_json, private_metadata_json,
                         sensitive_metadata_encrypted, metadata_hash, previous_ledger_hash,
                         ledger_hash, created_by, created_by_role, created_at
        ON points_ledger
        BEGIN
            SELECT RAISE(ABORT, 'points ledger core fields are immutable');
        END
        """
    )


def merkle_root(hashes):
    if not hashes:
        return sha256_text("")
    level = [str(item) for item in hashes]
    while len(level) > 1:
        if len(level) % 2:
            level.append(level[-1])
        level = [sha256_text(level[i] + level[i + 1]) for i in range(0, len(level), 2)]
    return level[0]


def merkle_proof(hashes, index):
    if index < 0 or index >= len(hashes):
        return []
    proof = []
    level = [str(item) for item in hashes]
    idx = index
    while len(level) > 1:
        original_len = len(level)
        if len(level) % 2:
            level.append(level[-1])
        sibling = idx - 1 if idx % 2 else idx + 1
        proof.append({
            "position": "left" if idx % 2 else "right",
            "hash": level[sibling],
            "duplicated": sibling >= original_len,
        })
        idx //= 2
        level = [sha256_text(level[i] + level[i + 1]) for i in range(0, len(level), 2)]
    return proof


def compute_block_hash(block):
    payload = {
        "block_number": int(block["block_number"]),
        "previous_block_hash": block["previous_block_hash"],
        "merkle_root": block["merkle_root"],
        "ledger_count": int(block["ledger_count"]),
        "first_ledger_id": int(block["first_ledger_id"]),
        "last_ledger_id": int(block["last_ledger_id"]),
        "sealed_at": block["sealed_at"],
    }
    return sha256_text(canonical_json(payload))


def block_signature_payload(block):
    return canonical_json({
        "block_hash": block["block_hash"],
        "block_number": int(block["block_number"]),
        "merkle_root": block["merkle_root"],
        "previous_block_hash": block["previous_block_hash"],
    })


def ensure_points_economy_schema(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS points_wallets (
            user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            soft_balance INTEGER NOT NULL DEFAULT 0 CHECK (soft_balance >= 0),
            hard_balance INTEGER NOT NULL DEFAULT 0 CHECK (hard_balance >= 0),
            soft_frozen INTEGER NOT NULL DEFAULT 0 CHECK (soft_frozen >= 0),
            hard_frozen INTEGER NOT NULL DEFAULT 0 CHECK (hard_frozen >= 0),
            total_soft_earned INTEGER NOT NULL DEFAULT 0,
            total_hard_earned INTEGER NOT NULL DEFAULT 0,
            total_soft_spent INTEGER NOT NULL DEFAULT 0,
            total_hard_spent INTEGER NOT NULL DEFAULT 0,
            wallet_status TEXT NOT NULL DEFAULT 'active',
            risk_level TEXT NOT NULL DEFAULT 'normal',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS points_ledger (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ledger_uuid TEXT NOT NULL UNIQUE,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            public_account_id TEXT NOT NULL,
            currency_type TEXT NOT NULL,
            direction TEXT NOT NULL,
            amount INTEGER NOT NULL CHECK (amount > 0),
            balance_before INTEGER NOT NULL,
            balance_after INTEGER NOT NULL,
            action_type TEXT NOT NULL,
            reference_type TEXT,
            reference_id TEXT,
            idempotency_key TEXT UNIQUE,
            reason TEXT,
            public_metadata_json TEXT,
            private_metadata_json TEXT,
            sensitive_metadata_encrypted TEXT,
            metadata_hash TEXT NOT NULL,
            previous_ledger_hash TEXT,
            ledger_hash TEXT NOT NULL UNIQUE,
            chain_block_id INTEGER REFERENCES points_chain_blocks(id) ON DELETE SET NULL,
            risk_flag TEXT DEFAULT 'none',
            risk_score INTEGER NOT NULL DEFAULT 0,
            created_by INTEGER,
            created_by_role TEXT,
            status TEXT NOT NULL DEFAULT 'confirmed',
            created_at TEXT NOT NULL,
            CHECK (currency_type IN ('soft', 'hard')),
            CHECK (direction IN ('credit', 'debit', 'freeze', 'unfreeze', 'reverse', 'transfer_in', 'transfer_out')),
            CHECK (status IN ('pending', 'confirmed', 'reversed', 'disputed', 'frozen'))
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS points_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rule_key TEXT NOT NULL UNIQUE,
            action_type TEXT NOT NULL,
            direction TEXT NOT NULL,
            currency_type TEXT NOT NULL,
            base_amount INTEGER NOT NULL,
            min_amount INTEGER NOT NULL DEFAULT 0,
            max_amount INTEGER,
            daily_user_limit INTEGER,
            daily_global_limit INTEGER,
            cooldown_seconds INTEGER NOT NULL DEFAULT 0,
            requires_quality_check INTEGER NOT NULL DEFAULT 0,
            requires_admin_review INTEGER NOT NULL DEFAULT 0,
            min_account_age_days INTEGER NOT NULL DEFAULT 0,
            enabled INTEGER NOT NULL DEFAULT 1,
            metadata_json TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            CHECK (direction IN ('credit', 'debit')),
            CHECK (currency_type IN ('soft', 'hard'))
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS points_pending_rewards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            currency_type TEXT NOT NULL,
            amount INTEGER NOT NULL CHECK (amount > 0),
            action_type TEXT NOT NULL,
            reference_type TEXT,
            reference_id TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            submitted_by INTEGER,
            reviewed_by INTEGER,
            review_note TEXT,
            metadata_json TEXT,
            created_at TEXT NOT NULL,
            reviewed_at TEXT,
            CHECK (currency_type IN ('soft', 'hard')),
            CHECK (status IN ('pending', 'approved', 'rejected', 'expired', 'cancelled'))
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS economy_price_catalog (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_key TEXT NOT NULL UNIQUE,
            item_name TEXT NOT NULL,
            category TEXT NOT NULL,
            currency_type TEXT NOT NULL,
            base_price INTEGER NOT NULL,
            dynamic_pricing INTEGER NOT NULL DEFAULT 0,
            min_price INTEGER,
            max_price INTEGER,
            enabled INTEGER NOT NULL DEFAULT 1,
            metadata_json TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            CHECK (currency_type IN ('soft', 'hard'))
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS points_chain_blocks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            block_number INTEGER NOT NULL UNIQUE,
            previous_block_hash TEXT,
            merkle_root TEXT NOT NULL,
            block_hash TEXT NOT NULL UNIQUE,
            ledger_count INTEGER NOT NULL,
            first_ledger_id INTEGER NOT NULL,
            last_ledger_id INTEGER NOT NULL,
            sealed_by INTEGER,
            sealed_by_node TEXT,
            sealed_at TEXT NOT NULL,
            seal_status TEXT NOT NULL DEFAULT 'sealed',
            anchor_status TEXT NOT NULL DEFAULT 'local_only',
            external_anchor_ref TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS points_chain_block_signatures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            block_id INTEGER NOT NULL REFERENCES points_chain_blocks(id) ON DELETE CASCADE,
            node_id TEXT NOT NULL,
            signature_algorithm TEXT NOT NULL,
            public_key_fingerprint TEXT NOT NULL,
            signature TEXT NOT NULL,
            signed_at TEXT NOT NULL,
            UNIQUE(block_id, node_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS points_chain_nodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            node_id TEXT NOT NULL UNIQUE,
            node_name TEXT NOT NULL,
            node_type TEXT NOT NULL,
            public_key TEXT NOT NULL,
            public_key_fingerprint TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS points_chain_audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            severity TEXT NOT NULL,
            actor_user_id INTEGER,
            actor_role TEXT,
            target_user_id INTEGER,
            related_ledger_id INTEGER,
            related_block_id INTEGER,
            message TEXT NOT NULL,
            metadata_json TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS points_disputes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ledger_id INTEGER NOT NULL REFERENCES points_ledger(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            status TEXT NOT NULL DEFAULT 'open',
            reason TEXT NOT NULL,
            resolution TEXT,
            resolved_by INTEGER,
            created_at TEXT NOT NULL,
            resolved_at TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS points_chain_recovery_state (
            id INTEGER PRIMARY KEY CHECK (id=1),
            safe_mode INTEGER NOT NULL DEFAULT 0,
            reason TEXT,
            verification_json TEXT,
            forensic_bundle_id TEXT,
            restore_plan_json TEXT,
            created_at TEXT,
            updated_at TEXT,
            restored_at TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS points_chain_backup_catalog (
            backup_id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            created_at TEXT NOT NULL,
            chain_height INTEGER NOT NULL DEFAULT 0,
            latest_block_hash TEXT,
            ledger_row_count INTEGER NOT NULL DEFAULT 0,
            wallet_count INTEGER NOT NULL DEFAULT 0,
            schema_version INTEGER NOT NULL,
            backup_path TEXT NOT NULL,
            manifest_path TEXT NOT NULL,
            files_hash TEXT NOT NULL,
            signature TEXT NOT NULL,
            verified INTEGER NOT NULL DEFAULT 0,
            verification_json TEXT,
            reason TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS points_economy_daily_stats (
            stat_date TEXT PRIMARY KEY,
            soft_issued INTEGER NOT NULL DEFAULT 0,
            soft_spent INTEGER NOT NULL DEFAULT 0,
            soft_burned INTEGER NOT NULL DEFAULT 0,
            hard_issued INTEGER NOT NULL DEFAULT 0,
            hard_spent INTEGER NOT NULL DEFAULT 0,
            hard_burned INTEGER NOT NULL DEFAULT 0,
            active_users INTEGER NOT NULL DEFAULT 0,
            suspicious_transactions INTEGER NOT NULL DEFAULT 0,
            marketplace_volume INTEGER NOT NULL DEFAULT 0,
            ai_generation_volume INTEGER NOT NULL DEFAULT 0,
            server_rental_volume INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_points_ledger_user_time ON points_ledger(user_id, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_points_ledger_action_ref ON points_ledger(action_type, reference_type, reference_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_points_ledger_block ON points_ledger(chain_block_id, id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_points_pending_status ON points_pending_rewards(status, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_points_chain_blocks_number ON points_chain_blocks(block_number)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_points_chain_backup_created ON points_chain_backup_catalog(created_at)")
    # Phase 3 of SERVER_MODE_V2_IMPLEMENTATION_PLAN.md — DB-level guard.
    # Final line of defense: any non-production write to points_chain_blocks
    # is aborted by the trigger before the row hits disk. Phases 7 + 2
    # catch most bugs at the application layer; this trigger catches
    # whatever slips through.
    from services.platform.db_mode_triggers import install_mode_triggers_schema
    install_mode_triggers_schema(conn)
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_points_ledger_no_delete
        BEFORE DELETE ON points_ledger
        BEGIN
            SELECT RAISE(ABORT, 'points ledger is append-only');
        END
        """
    )
    create_points_ledger_immutable_trigger(conn)
    now = utc_now()
    for rule in DEFAULT_RULES:
        conn.execute(
            """
            INSERT OR IGNORE INTO points_rules (
                rule_key, action_type, direction, currency_type, base_amount, min_amount, max_amount,
                cooldown_seconds, requires_quality_check, requires_admin_review, min_account_age_days,
                enabled, daily_user_limit, metadata_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (*rule[:13], _json_dumps(rule[13]), now, now),
        )
    for item in DEFAULT_PRICE_CATALOG:
        conn.execute(
            """
            INSERT OR IGNORE INTO economy_price_catalog (
                item_key, item_name, category, currency_type, base_price, dynamic_pricing,
                min_price, max_price, enabled, metadata_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (*item[:9], _json_dumps(item[9]), now, now),
        )
    conn.execute(
        """
        UPDATE points_wallets
        SET soft_balance=soft_balance+hard_balance,
            hard_balance=0,
            soft_frozen=soft_frozen+hard_frozen,
            hard_frozen=0,
            total_soft_earned=total_soft_earned+total_hard_earned,
            total_hard_earned=0,
            total_soft_spent=total_soft_spent+total_hard_spent,
            total_hard_spent=0,
            updated_at=?
        WHERE hard_balance != 0
           OR hard_frozen != 0
           OR total_hard_earned != 0
           OR total_hard_spent != 0
        """,
        (now,),
    )
    conn.execute("UPDATE points_rules SET currency_type=? WHERE currency_type='hard'", (INTERNAL_CURRENCY,))
    conn.execute("UPDATE economy_price_catalog SET currency_type=? WHERE currency_type='hard'", (INTERNAL_CURRENCY,))
    conn.execute("UPDATE points_pending_rewards SET currency_type=? WHERE currency_type='hard'", (INTERNAL_CURRENCY,))


class ChainModeViolation(RuntimeError):
    """Phase 7 of SERVER_MODE_V2_IMPLEMENTATION_PLAN.md.

    PointsChain block writes are valid in `production` only. Any
    attempt to seal / mutate `points_chain_blocks` from a non-
    production runtime mode raises this exception so the call is
    blocked before the SQL ever executes.

    Treat this exception as a release blocker — it should never
    surface in normal operation. If you see one, the audit chain has
    been very nearly polluted.
    """

    def __init__(self, mode, action="chain_write"):
        self.mode = mode
        self.action = action
        super().__init__(
            f"chain {action} forbidden in mode={mode!r}; production-only"
        )
