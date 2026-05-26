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
BIRTHDAY_GIFT_POINTS = 1000
POINTS_CHAIN_SCHEMA_VERSION = 1
DEFAULT_BACKUP_INTERVAL_MINUTES = 60
DEFAULT_BACKUP_KEEP_RECENT = 5
DEFAULT_BACKUP_KEEP_DAILY = 7
DEFAULT_BACKUP_KEEP_WEEKLY = 4
MAX_LEDGER_METADATA_JSON_BYTES = 4096
PRICE_ITEM_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_:-]{1,79}$")
PRICE_CATEGORY_RE = re.compile(r"^[a-z][a-z0-9_:-]{1,79}$")
GOV_RATE_UNIT_SUFFIX = "b" + "ps"
GOV_QUORUM_RATE_COLUMN = "quorum_" + GOV_RATE_UNIT_SUFFIX
GOV_PASS_THRESHOLD_RATE_COLUMN = "pass_threshold_" + GOV_RATE_UNIT_SUFFIX
GOV_YES_THRESHOLD_RATE_COLUMN = "yes_threshold_" + GOV_RATE_UNIT_SUFFIX
GOV_VOTE_DIFFERENTIAL_REQUIRED_RATE_COLUMN = "vote_differential_required_" + GOV_RATE_UNIT_SUFFIX
GOVERNANCE_DOMAINS = {
    "PUBLIC_COMMON_INTEREST",
    "OFFICIAL_TREASURY",
    "EMERGENCY_SECURITY",
    "PROTOCOL_PARAMETER",
    "ADMIN_POLICY",
}
GOVERNANCE_ACTION_TYPES = {
    "MARK_SCAM",
    "FREEZE_ADDRESS",
    "UNFREEZE_ADDRESS",
    "ROLLBACK_BRANCH",
    "EMERGENCY_LOCKDOWN",
    "AUTO_BURN_POLICY",
    "MINT_REQUEST",
    "TREASURY_TRANSFER",
    "EXCHANGE_FUND_REPLENISH",
    "CONTEST_REWARD_PAYOUT",
    "TREASURY_SIGNER_CHANGE",
    "PARAMETER_CHANGE",
    "FEATURE_ACTIVATION",
    "HARD_FORK_ACCEPTANCE",
}
GOVERNANCE_LIFECYCLE_STATUSES = {
    "DRAFT",
    "REVIEW",
    "VOTING",
    "SUCCEEDED",
    "FAILED",
    "QUEUED",
    "TIMELOCKED",
    "EXECUTED",
    "VETOED",
    "EXPIRED",
    "CANCELLED",
}

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
    ("cloud_storage_1gb_30d", "雲端容量 1GB / 30 天", "cloud_drive", "soft", 100, 0, 50, 500, 1, {"storage_bytes": 1024 ** 3, "duration_days": 30, "label": "雲端容量 1GB / 30 天"}),
    ("comfyui_txt2img_basic", "基礎生圖一次", "comfyui", "soft", 5, 1, 1, 25, 1, {}),
    ("comfyui_txt2img_highres", "高解析生圖一次", "comfyui", INTERNAL_CURRENCY, 12, 1, 5, 60, 1, {}),
    ("comfyui_batch_10", "批次生圖 10 張", "comfyui", INTERNAL_CURRENCY, 45, 1, 20, 200, 1, {}),
    ("video_publish_basic", "影音發布處理費", "video", INTERNAL_CURRENCY, 2, 0, 1, 20, 1, {}),
    ("video_boost_24h", "影音曝光加成 24 小時", "video", INTERNAL_CURRENCY, 80, 0, 30, 300, 1, {}),
    ("server_rental_cpu_1h", "CPU Server 1 小時", "server_rental", INTERNAL_CURRENCY, 5, 1, 2, 30, 1, {}),
    ("server_rental_gpu_1h", "GPU Server 1 小時", "server_rental", INTERNAL_CURRENCY, 50, 1, 20, 200, 1, {}),
    ("game_entry_standard", "遊戲一般入場", "game", INTERNAL_CURRENCY, 1, 0, 1, 10, 1, {}),
    ("game_virtual_item_common", "普通虛寶", "game", "soft", 20, 0, 5, 100, 1, {}),
    ("game_virtual_item_premium", "高級虛寶", "game", INTERNAL_CURRENCY, 5, 0, 1, 50, 1, {}),
    ("marketplace_listing_fee", "市集上架費", "marketplace", INTERNAL_CURRENCY, 3, 0, 1, 30, 1, {}),
    ("ai_agent_task_basic", "AI Agent 基礎任務", "ai_task", INTERNAL_CURRENCY, 10, 1, 5, 100, 1, {}),
    ("username_change", "改名", "account", "soft", 200, 0, 100, 1000, 1, {}),
    ("profile_decoration", "個人頁裝飾", "account", "soft", 50, 0, 10, 250, 1, {}),
    ("violation_fine", "違規罰款繳納", "governance", INTERNAL_CURRENCY, 300, 0, 1, 100000, 1, {"destination": "burn", "description": "違規罰款由用戶授權付款，預設銷毀以避免官方靠處分獲利。"}),
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
        BEFORE UPDATE OF ledger_uuid, chain_branch, user_id, public_account_id, currency_type, direction, amount,
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


def create_points_chain_block_immutable_triggers(conn):
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_points_chain_blocks_no_update
        BEFORE UPDATE ON points_chain_blocks
        BEGIN
            SELECT RAISE(ABORT, 'points chain blocks are append-only');
        END
        """
    )
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_points_chain_blocks_no_delete
        BEFORE DELETE ON points_chain_blocks
        BEGIN
            SELECT RAISE(ABORT, 'points chain blocks are append-only');
        END
        """
    )
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_points_chain_block_signatures_no_update
        BEFORE UPDATE ON points_chain_block_signatures
        BEGIN
            SELECT RAISE(ABORT, 'points chain block signatures are append-only');
        END
        """
    )
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_points_chain_block_signatures_no_delete
        BEFORE DELETE ON points_chain_block_signatures
        BEGIN
            SELECT RAISE(ABORT, 'points chain block signatures are append-only');
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
        CREATE TABLE IF NOT EXISTS points_wallet_identity_balances (
            chain_branch TEXT NOT NULL,
            wallet_address TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            wallet_identity_id INTEGER,
            wallet_type TEXT NOT NULL DEFAULT '',
            custody_mode TEXT NOT NULL DEFAULT '',
            available_points INTEGER NOT NULL DEFAULT 0 CHECK (available_points >= 0),
            frozen_points INTEGER NOT NULL DEFAULT 0 CHECK (frozen_points >= 0),
            pending_outgoing_points INTEGER NOT NULL DEFAULT 0 CHECK (pending_outgoing_points >= 0),
            last_ledger_id INTEGER NOT NULL DEFAULT 0,
            last_transfer_request_id INTEGER NOT NULL DEFAULT 0,
            last_bridge_event_id INTEGER NOT NULL DEFAULT 0,
            balance_hash TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL,
            PRIMARY KEY (chain_branch, wallet_address)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS points_wallet_identity_balance_state (
            chain_branch TEXT PRIMARY KEY,
            replay_height INTEGER NOT NULL DEFAULT 0,
            last_ledger_hash TEXT NOT NULL DEFAULT '',
            last_transfer_request_id INTEGER NOT NULL DEFAULT 0,
            last_bridge_event_id INTEGER NOT NULL DEFAULT 0,
            wallet_root_hash TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS points_ledger (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ledger_uuid TEXT NOT NULL UNIQUE,
            chain_branch TEXT NOT NULL DEFAULT 'main',
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
    ledger_cols = table_columns(conn, "points_ledger")
    if "chain_branch" not in ledger_cols:
        conn.execute("ALTER TABLE points_ledger ADD COLUMN chain_branch TEXT NOT NULL DEFAULT 'main'")
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
        CREATE TABLE IF NOT EXISTS points_chain_acceleration_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_uuid TEXT NOT NULL UNIQUE,
            ledger_uuid TEXT NOT NULL,
            payer_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            fee_points INTEGER NOT NULL,
            target_proved_count INTEGER NOT NULL DEFAULT 20,
            estimated_seconds_min INTEGER NOT NULL,
            estimated_seconds_max INTEGER NOT NULL,
            fee_ledger_uuid TEXT,
            status TEXT NOT NULL DEFAULT 'accepted',
            created_at TEXT NOT NULL,
            CHECK (fee_points > 0),
            CHECK (target_proved_count > 0),
            CHECK (estimated_seconds_min > 0),
            CHECK (estimated_seconds_max >= estimated_seconds_min)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS points_chain_transfer_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_uuid TEXT NOT NULL UNIQUE,
            chain_branch TEXT NOT NULL DEFAULT 'main',
            request_hash TEXT NOT NULL,
            tx_group_hash TEXT NOT NULL UNIQUE,
            sender_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            recipient_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            source_wallet_address TEXT NOT NULL,
            destination_wallet_address TEXT NOT NULL,
            destination_unowned INTEGER NOT NULL DEFAULT 0 CHECK (destination_unowned IN (0, 1)),
            amount_points INTEGER NOT NULL,
            fee_points INTEGER NOT NULL DEFAULT 0,
            transaction_type TEXT NOT NULL DEFAULT 'wallet_transfer',
            source_fund_key TEXT NOT NULL DEFAULT '',
            memo TEXT NOT NULL DEFAULT '',
            transfer_out_ledger_uuid TEXT,
            transfer_in_ledger_uuid TEXT,
            fee_ledger_uuid TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL,
            CHECK (amount_points > 0),
            CHECK (fee_points >= 0)
        )
        """
    )
    transfer_cols = table_columns(conn, "points_chain_transfer_requests")
    if "chain_branch" not in transfer_cols:
        conn.execute("ALTER TABLE points_chain_transfer_requests ADD COLUMN chain_branch TEXT NOT NULL DEFAULT 'main'")
    if "memo" not in transfer_cols:
        conn.execute("ALTER TABLE points_chain_transfer_requests ADD COLUMN memo TEXT NOT NULL DEFAULT ''")
    if "transaction_type" not in transfer_cols:
        conn.execute("ALTER TABLE points_chain_transfer_requests ADD COLUMN transaction_type TEXT NOT NULL DEFAULT 'wallet_transfer'")
    if "source_fund_key" not in transfer_cols:
        conn.execute("ALTER TABLE points_chain_transfer_requests ADD COLUMN source_fund_key TEXT NOT NULL DEFAULT ''")
    if "destination_unowned" not in transfer_cols:
        conn.execute("ALTER TABLE points_chain_transfer_requests ADD COLUMN destination_unowned INTEGER NOT NULL DEFAULT 0 CHECK (destination_unowned IN (0, 1))")
    transfer_column_defs = {
        "settlement_rail": "TEXT NOT NULL DEFAULT 'cold_chain' CHECK (settlement_rail IN ('internal_hot_wallet','internal_system_burn','cold_chain','deposit_bridge_credit','withdrawal_bridge_lock','withdrawal_bridge_broadcast','withdrawal_bridge_confirm','withdrawal_bridge_refund'))",
        "chain_required": "INTEGER NOT NULL DEFAULT 1 CHECK (chain_required IN (0,1))",
        "approval_required": "INTEGER NOT NULL DEFAULT 1 CHECK (approval_required IN (0,1))",
        "network_fee_points": "INTEGER NOT NULL DEFAULT 0 CHECK (network_fee_points >= 0)",
        "service_fee_points": "INTEGER NOT NULL DEFAULT 0 CHECK (service_fee_points >= 0)",
    }
    transfer_cols = table_columns(conn, "points_chain_transfer_requests")
    for column, ddl in transfer_column_defs.items():
        if column not in transfer_cols:
            conn.execute(f"ALTER TABLE points_chain_transfer_requests ADD COLUMN {column} {ddl}")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS points_chain_deposit_addresses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            chain TEXT NOT NULL DEFAULT 'points_chain_sim',
            address TEXT NOT NULL UNIQUE,
            vault_key TEXT NOT NULL DEFAULT 'default',
            status TEXT NOT NULL DEFAULT 'active',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            CHECK (status IN ('active', 'disabled', 'rotated'))
        )
        """
    )
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_points_chain_deposit_one_active
        ON points_chain_deposit_addresses(user_id, chain)
        WHERE status='active'
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS points_chain_bridge_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bridge_uuid TEXT NOT NULL UNIQUE,
            bridge_type TEXT NOT NULL,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            chain TEXT NOT NULL DEFAULT 'points_chain_sim',
            chain_tx_hash TEXT NOT NULL,
            source_address TEXT NOT NULL DEFAULT '',
            destination_address TEXT NOT NULL DEFAULT '',
            hot_wallet_address TEXT NOT NULL DEFAULT '',
            amount_points INTEGER NOT NULL CHECK (amount_points > 0),
            network_fee_points INTEGER NOT NULL DEFAULT 0 CHECK (network_fee_points >= 0),
            confirmations INTEGER NOT NULL DEFAULT 0 CHECK (confirmations >= 0),
            required_confirmations INTEGER NOT NULL DEFAULT 20 CHECK (required_confirmations > 0),
            risk_status TEXT NOT NULL DEFAULT 'accepted',
            status TEXT NOT NULL DEFAULT 'pending',
            internal_ledger_uuid TEXT NOT NULL DEFAULT '',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            confirmed_at TEXT,
            credited_at TEXT,
            refunded_at TEXT,
            updated_at TEXT NOT NULL,
            CHECK (bridge_type IN ('deposit', 'withdrawal')),
            CHECK (risk_status IN ('accepted', 'review', 'blocked')),
            CHECK (status IN ('pending', 'confirmed', 'credited', 'failed', 'refunded'))
        )
        """
    )
    bridge_cols = table_columns(conn, "points_chain_bridge_events")
    bridge_column_defs = {
        "bridge_uuid": "TEXT NOT NULL DEFAULT ''",
        "bridge_type": "TEXT NOT NULL DEFAULT 'deposit'",
        "chain": "TEXT NOT NULL DEFAULT 'points_chain_sim'",
        "chain_tx_hash": "TEXT NOT NULL DEFAULT ''",
        "source_address": "TEXT NOT NULL DEFAULT ''",
        "destination_address": "TEXT NOT NULL DEFAULT ''",
        "hot_wallet_address": "TEXT NOT NULL DEFAULT ''",
        "amount_points": "INTEGER NOT NULL DEFAULT 1",
        "network_fee_points": "INTEGER NOT NULL DEFAULT 0",
        "confirmations": "INTEGER NOT NULL DEFAULT 0",
        "required_confirmations": "INTEGER NOT NULL DEFAULT 20",
        "risk_status": "TEXT NOT NULL DEFAULT 'accepted'",
        "status": "TEXT NOT NULL DEFAULT 'pending'",
        "internal_ledger_uuid": "TEXT NOT NULL DEFAULT ''",
        "metadata_json": "TEXT NOT NULL DEFAULT '{}'",
        "confirmed_at": "TEXT",
        "credited_at": "TEXT",
        "refunded_at": "TEXT",
        "updated_at": "TEXT NOT NULL DEFAULT ''",
    }
    for column, ddl in bridge_column_defs.items():
        if column not in bridge_cols:
            conn.execute(f"ALTER TABLE points_chain_bridge_events ADD COLUMN {column} {ddl}")
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_points_chain_bridge_uuid
        ON points_chain_bridge_events(bridge_uuid)
        WHERE bridge_uuid<>''
        """
    )
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_points_chain_bridge_chain_tx
        ON points_chain_bridge_events(chain, chain_tx_hash)
        WHERE chain_tx_hash<>''
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_points_chain_bridge_user
        ON points_chain_bridge_events(user_id, bridge_type, status, created_at)
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS points_service_fee_charges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            charge_uuid TEXT NOT NULL UNIQUE,
            chain_branch TEXT NOT NULL DEFAULT 'main',
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            item_key TEXT NOT NULL,
            quantity INTEGER NOT NULL DEFAULT 1 CHECK (quantity > 0),
            amount_points INTEGER NOT NULL CHECK (amount_points > 0),
            currency_type TEXT NOT NULL DEFAULT 'soft',
            source_wallet_address TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'reserved',
            idempotency_key TEXT UNIQUE,
            freeze_ledger_uuid TEXT,
            unfreeze_ledger_uuid TEXT,
            debit_ledger_uuid TEXT,
            batch_uuid TEXT,
            reference_type TEXT,
            reference_id TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            settled_at TEXT,
            cancelled_at TEXT,
            CHECK (currency_type IN ('soft', 'hard')),
            CHECK (status IN ('reserved', 'settled', 'cancelled'))
        )
        """
    )
    service_fee_cols = table_columns(conn, "points_service_fee_charges")
    if "chain_branch" not in service_fee_cols:
        conn.execute("ALTER TABLE points_service_fee_charges ADD COLUMN chain_branch TEXT NOT NULL DEFAULT 'main'")
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_points_service_fee_user_status
        ON points_service_fee_charges(user_id, status, source_wallet_address, created_at)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_points_service_fee_batch
        ON points_service_fee_charges(batch_uuid)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_points_service_fee_item_time
        ON points_service_fee_charges(item_key, created_at)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_points_service_fee_branch_user_status
        ON points_service_fee_charges(chain_branch, user_id, status, source_wallet_address, created_at)
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
        f"""
        CREATE TABLE IF NOT EXISTS points_chain_governance_proposals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            proposal_uuid TEXT NOT NULL UNIQUE,
            proposal_type TEXT NOT NULL,
            governance_domain TEXT NOT NULL DEFAULT 'PUBLIC_COMMON_INTEREST',
            action_type TEXT NOT NULL DEFAULT 'MARK_SCAM',
            lifecycle_status TEXT NOT NULL DEFAULT 'VOTING',
            proposal_severity TEXT NOT NULL DEFAULT 'NORMAL',
            sponsor_required INTEGER NOT NULL DEFAULT 0 CHECK (sponsor_required IN (0, 1)),
            sponsor_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            sponsor_role TEXT NOT NULL DEFAULT '',
            sponsored_at TEXT,
            proposal_deposit_points INTEGER NOT NULL DEFAULT 0,
            proposal_deposit_status TEXT NOT NULL DEFAULT 'not_required',
            title TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            reason TEXT NOT NULL,
            reference TEXT NOT NULL DEFAULT '',
            target_wallet_address TEXT NOT NULL DEFAULT '',
            target_address TEXT NOT NULL DEFAULT '',
            target_branch TEXT NOT NULL DEFAULT '',
            requested_amount INTEGER NOT NULL DEFAULT 0,
            requested_asset TEXT NOT NULL DEFAULT 'points',
            incident_tx_hash TEXT NOT NULL DEFAULT '',
            base_block_number INTEGER,
            base_block_hash TEXT NOT NULL DEFAULT '',
            payload_json TEXT NOT NULL DEFAULT '{{}}',
            evidence_json TEXT NOT NULL DEFAULT '[]',
            impact_scope TEXT NOT NULL DEFAULT '',
            risk_summary TEXT NOT NULL DEFAULT '',
            opposition_record TEXT NOT NULL DEFAULT '',
            eligible_voters_json TEXT NOT NULL DEFAULT '[]',
            eligible_voter_count INTEGER NOT NULL DEFAULT 0,
            quorum_count INTEGER NOT NULL DEFAULT 0,
            {GOV_QUORUM_RATE_COLUMN} INTEGER NOT NULL DEFAULT 0,
            {GOV_PASS_THRESHOLD_RATE_COLUMN} INTEGER NOT NULL DEFAULT 0,
            {GOV_YES_THRESHOLD_RATE_COLUMN} INTEGER NOT NULL DEFAULT 0,
            {GOV_VOTE_DIFFERENTIAL_REQUIRED_RATE_COLUMN} INTEGER NOT NULL DEFAULT 0,
            yes_count INTEGER NOT NULL DEFAULT 0,
            no_count INTEGER NOT NULL DEFAULT 0,
            abstain_count INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'voting',
            voting_starts_at TEXT,
            voting_ends_at TEXT,
            timelock_until TEXT,
            timelock_ends_at TEXT,
            expires_at TEXT NOT NULL,
            root_veto_allowed INTEGER NOT NULL DEFAULT 0 CHECK (root_veto_allowed IN (0, 1)),
            root_veto_used INTEGER NOT NULL DEFAULT 0 CHECK (root_veto_used IN (0, 1)),
            root_vetoed_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
            root_vetoed_at TEXT,
            root_veto_reason TEXT NOT NULL DEFAULT '',
            execution_payload_hash TEXT NOT NULL DEFAULT '',
            proposer_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            proposer_role TEXT,
            executed_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
            executed_at TEXT,
            execution_result_json TEXT NOT NULL DEFAULT '{{}}',
            prev_audit_hash TEXT NOT NULL DEFAULT '',
            audit_hash TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            CHECK (proposal_type IN ('scam_address_label', 'freeze_wallet_address', 'unfreeze_wallet_address', 'emergency_recovery_branch', 'official_treasury_operation', 'protocol_parameter_change', 'emergency_security_action', 'admin_policy_action')),
            CHECK (governance_domain IN ('PUBLIC_COMMON_INTEREST', 'OFFICIAL_TREASURY', 'EMERGENCY_SECURITY', 'PROTOCOL_PARAMETER', 'ADMIN_POLICY')),
            CHECK (action_type IN ('MARK_SCAM', 'FREEZE_ADDRESS', 'UNFREEZE_ADDRESS', 'ROLLBACK_BRANCH', 'EMERGENCY_LOCKDOWN', 'AUTO_BURN_POLICY', 'MINT_REQUEST', 'TREASURY_TRANSFER', 'EXCHANGE_FUND_REPLENISH', 'CONTEST_REWARD_PAYOUT', 'TREASURY_SIGNER_CHANGE', 'PARAMETER_CHANGE', 'FEATURE_ACTIVATION', 'HARD_FORK_ACCEPTANCE')),
            CHECK (lifecycle_status IN ('DRAFT', 'REVIEW', 'VOTING', 'SUCCEEDED', 'FAILED', 'QUEUED', 'TIMELOCKED', 'EXECUTED', 'VETOED', 'EXPIRED', 'CANCELLED')),
            CHECK (proposal_severity IN ('LOW', 'NORMAL', 'HIGH', 'CRITICAL')),
            CHECK (proposal_deposit_status IN ('not_required', 'reserved', 'returned', 'burned')),
            CHECK (status IN ('voting', 'passed', 'rejected', 'executed', 'expired', 'cancelled'))
        )
        """
    )
    governance_cols = table_columns(conn, "points_chain_governance_proposals")
    governance_column_defs = {
        "governance_domain": "TEXT NOT NULL DEFAULT 'PUBLIC_COMMON_INTEREST'",
        "action_type": "TEXT NOT NULL DEFAULT 'MARK_SCAM'",
        "lifecycle_status": "TEXT NOT NULL DEFAULT 'VOTING'",
        "proposal_severity": "TEXT NOT NULL DEFAULT 'NORMAL'",
        "sponsor_required": "INTEGER NOT NULL DEFAULT 0",
        "sponsor_user_id": "INTEGER",
        "sponsor_role": "TEXT NOT NULL DEFAULT ''",
        "sponsored_at": "TEXT",
        "proposal_deposit_points": "INTEGER NOT NULL DEFAULT 0",
        "proposal_deposit_status": "TEXT NOT NULL DEFAULT 'not_required'",
        "description": "TEXT NOT NULL DEFAULT ''",
        "target_address": "TEXT NOT NULL DEFAULT ''",
        "target_branch": "TEXT NOT NULL DEFAULT ''",
        "requested_amount": "INTEGER NOT NULL DEFAULT 0",
        "requested_asset": "TEXT NOT NULL DEFAULT 'points'",
        "impact_scope": "TEXT NOT NULL DEFAULT ''",
        "risk_summary": "TEXT NOT NULL DEFAULT ''",
        "opposition_record": "TEXT NOT NULL DEFAULT ''",
        GOV_YES_THRESHOLD_RATE_COLUMN: "INTEGER NOT NULL DEFAULT 0",
        GOV_VOTE_DIFFERENTIAL_REQUIRED_RATE_COLUMN: "INTEGER NOT NULL DEFAULT 0",
        "voting_starts_at": "TEXT",
        "voting_ends_at": "TEXT",
        "timelock_ends_at": "TEXT",
        "root_veto_allowed": "INTEGER NOT NULL DEFAULT 0",
        "root_veto_used": "INTEGER NOT NULL DEFAULT 0",
        "root_vetoed_by": "INTEGER",
        "root_vetoed_at": "TEXT",
        "root_veto_reason": "TEXT NOT NULL DEFAULT ''",
        "execution_payload_hash": "TEXT NOT NULL DEFAULT ''",
        "prev_audit_hash": "TEXT NOT NULL DEFAULT ''",
        "audit_hash": "TEXT NOT NULL DEFAULT ''",
    }
    for column, ddl in governance_column_defs.items():
        if column not in governance_cols:
            conn.execute(f"ALTER TABLE points_chain_governance_proposals ADD COLUMN {column} {ddl}")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS points_chain_governance_votes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            proposal_uuid TEXT NOT NULL REFERENCES points_chain_governance_proposals(proposal_uuid) ON DELETE CASCADE,
            voter_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            vote TEXT NOT NULL,
            reason TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(proposal_uuid, voter_user_id),
            CHECK (vote IN ('yes', 'no', 'abstain'))
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS points_chain_governance_multisig_signatures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            proposal_uuid TEXT NOT NULL REFERENCES points_chain_governance_proposals(proposal_uuid) ON DELETE CASCADE,
            signer_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            signer_wallet_address TEXT NOT NULL,
            signature_mode TEXT NOT NULL DEFAULT 'wallet_signature',
            signature_hash TEXT NOT NULL,
            signed_payload_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(proposal_uuid, signer_wallet_address),
            CHECK (signature_mode IN ('wallet_signature', 'server_attested'))
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS points_chain_governance_audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            audit_uuid TEXT NOT NULL UNIQUE,
            proposal_uuid TEXT NOT NULL,
            event_type TEXT NOT NULL,
            actor_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            actor_role TEXT,
            payload_hash TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            prev_audit_hash TEXT NOT NULL DEFAULT '',
            audit_hash TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_points_chain_governance_audit_no_update
        BEFORE UPDATE ON points_chain_governance_audit_log
        BEGIN
            SELECT RAISE(ABORT, 'governance audit log is append-only');
        END
        """
    )
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_points_chain_governance_audit_no_delete
        BEFORE DELETE ON points_chain_governance_audit_log
        BEGIN
            SELECT RAISE(ABORT, 'governance audit log is append-only');
        END
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS points_chain_address_risk_labels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            wallet_address TEXT NOT NULL UNIQUE,
            risk_level TEXT NOT NULL DEFAULT 'suspected_scam',
            status TEXT NOT NULL DEFAULT 'active',
            label TEXT NOT NULL DEFAULT 'scam_warning',
            reason TEXT NOT NULL,
            evidence_json TEXT NOT NULL DEFAULT '[]',
            proposal_uuid TEXT NOT NULL REFERENCES points_chain_governance_proposals(proposal_uuid) ON DELETE RESTRICT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            revoked_at TEXT,
            CHECK (status IN ('active', 'revoked')),
            CHECK (risk_level IN ('suspected_scam', 'confirmed_scam', 'critical_scam'))
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS points_chain_address_freezes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            wallet_address TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL DEFAULT 'active',
            reason TEXT NOT NULL,
            evidence_json TEXT NOT NULL DEFAULT '[]',
            freeze_proposal_uuid TEXT NOT NULL REFERENCES points_chain_governance_proposals(proposal_uuid) ON DELETE RESTRICT,
            release_proposal_uuid TEXT REFERENCES points_chain_governance_proposals(proposal_uuid) ON DELETE RESTRICT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            released_at TEXT,
            CHECK (status IN ('active', 'released'))
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS points_chain_address_provisional_freezes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            wallet_address TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL DEFAULT 'active',
            reason TEXT NOT NULL,
            evidence_json TEXT NOT NULL DEFAULT '[]',
            source_dispute_uuid TEXT NOT NULL DEFAULT '',
            linked_proposal_uuid TEXT NOT NULL DEFAULT '',
            reviewed_by INTEGER,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            released_at TEXT,
            CHECK (status IN ('active', 'released', 'expired'))
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS points_chain_governance_branches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            branch_uuid TEXT NOT NULL UNIQUE,
            proposal_uuid TEXT NOT NULL REFERENCES points_chain_governance_proposals(proposal_uuid) ON DELETE RESTRICT,
            parent_branch_uuid TEXT NOT NULL DEFAULT '',
            branch_name TEXT NOT NULL,
            base_block_number INTEGER,
            base_block_hash TEXT NOT NULL DEFAULT '',
            incident_tx_hash TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'proposed',
            is_canonical INTEGER NOT NULL DEFAULT 0 CHECK (is_canonical IN (0, 1)),
            write_enabled INTEGER NOT NULL DEFAULT 0 CHECK (write_enabled IN (0, 1)),
            recovery_type TEXT NOT NULL DEFAULT 'canonical_pointer_only',
            replay_plan_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            activated_at TEXT,
            CHECK (status IN ('proposed', 'canonical_recovery', 'archived', 'read_only_archived'))
        )
        """
    )
    branch_cols = table_columns(conn, "points_chain_governance_branches")
    if "write_enabled" not in branch_cols:
        conn.execute("ALTER TABLE points_chain_governance_branches ADD COLUMN write_enabled INTEGER NOT NULL DEFAULT 0")
    if "recovery_type" not in branch_cols:
        conn.execute("ALTER TABLE points_chain_governance_branches ADD COLUMN recovery_type TEXT NOT NULL DEFAULT 'canonical_pointer_only'")
    conn.execute(
        """
        UPDATE points_chain_governance_branches
        SET write_enabled=1
        WHERE is_canonical=1 AND write_enabled=0
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
    conn.execute("CREATE INDEX IF NOT EXISTS idx_points_wallet_identity_balances_user ON points_wallet_identity_balances(chain_branch, user_id, wallet_type, wallet_address)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_points_ledger_branch_user_time ON points_ledger(chain_branch, user_id, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_points_ledger_branch_id ON points_ledger(chain_branch, id DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_points_ledger_branch_user_id_desc ON points_ledger(chain_branch, user_id, id DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_points_ledger_action_ref ON points_ledger(action_type, reference_type, reference_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_points_ledger_block ON points_ledger(chain_block_id, id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_points_pending_status ON points_pending_rewards(status, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_points_chain_blocks_number ON points_chain_blocks(block_number)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_points_chain_accel_ledger ON points_chain_acceleration_requests(ledger_uuid, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_points_chain_transfer_wallets ON points_chain_transfer_requests(source_wallet_address, destination_wallet_address, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_points_chain_transfer_branch_wallets ON points_chain_transfer_requests(chain_branch, source_wallet_address, destination_wallet_address, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_points_chain_transfer_pending_source ON points_chain_transfer_requests(chain_branch, status, source_wallet_address, request_uuid)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_points_chain_backup_created ON points_chain_backup_catalog(created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_points_chain_governance_status ON points_chain_governance_proposals(status, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_points_chain_governance_domain ON points_chain_governance_proposals(governance_domain, lifecycle_status, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_points_chain_governance_action ON points_chain_governance_proposals(action_type, lifecycle_status, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_points_chain_governance_proposer ON points_chain_governance_proposals(proposer_user_id, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_points_chain_governance_type ON points_chain_governance_proposals(proposal_type, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_points_chain_governance_votes_user ON points_chain_governance_votes(voter_user_id, proposal_uuid)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_points_chain_governance_multisig_proposal ON points_chain_governance_multisig_signatures(proposal_uuid, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_points_chain_governance_audit_proposal ON points_chain_governance_audit_log(proposal_uuid, id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_points_chain_address_risk_status ON points_chain_address_risk_labels(status, wallet_address)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_points_chain_address_freeze_status ON points_chain_address_freezes(status, wallet_address)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_points_chain_address_provisional_freeze_status ON points_chain_address_provisional_freezes(status, expires_at, wallet_address)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_points_chain_branch_canonical ON points_chain_governance_branches(is_canonical, created_at)")
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
    create_points_chain_block_immutable_triggers(conn)
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

    PointsChain block writes are valid in `production` and the isolated
    development `dev_ready` mode. Any attempt to seal / mutate
    `points_chain_blocks` from another runtime mode raises this exception
    so the call is blocked before the SQL ever executes.

    Treat this exception as a release blocker — it should never
    surface in normal operation. If you see one, the audit chain has
    been very nearly polluted.
    """

    def __init__(self, mode, action="chain_write"):
        self.mode = mode
        self.action = action
        super().__init__(
            f"chain {action} forbidden in mode={mode!r}; production/dev_ready only"
        )
