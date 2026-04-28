import hashlib
import hmac
import json
import uuid
from datetime import datetime, timezone


CURRENCIES = {"soft", "hard"}
LEDGER_DIRECTIONS = {"credit", "debit", "freeze", "unfreeze", "reverse", "transfer_in", "transfer_out"}
LEDGER_STATUSES = {"pending", "confirmed", "reversed", "disputed", "frozen"}
WALLET_STATUSES = {"active", "frozen", "limited", "closed"}

DEFAULT_RULES = (
    ("daily_login", "daily_login", "credit", "soft", 5, 5, 5, 24 * 60 * 60, 0, 0, 0, 1, 0, {"label": "每日登入"}),
    ("create_post", "forum_post_reward", "credit", "soft", 3, 3, 30, 0, 1, 0, 0, 1, 0, {"label": "發文獎勵"}),
    ("create_comment", "forum_comment_reward", "credit", "soft", 1, 1, 50, 60, 1, 0, 0, 1, 0, {"label": "留言獎勵"}),
    ("receive_like", "content_like_reward", "credit", "soft", 1, 1, 25, 0, 0, 0, 0, 1, 0, {"label": "被按讚獎勵"}),
    ("quality_post_bonus", "quality_post_bonus", "credit", "soft", 20, 20, 100, 0, 1, 1, 0, 1, 1, {"label": "優質文章獎勵"}),
    ("valid_bug_report_low", "bug_bounty_low", "credit", "soft", 50, 50, 150, 0, 0, 1, 0, 1, 1, {"label": "低風險有效 bug"}),
    ("valid_bug_report_medium", "bug_bounty_medium", "credit", "hard", 50, 50, 150, 0, 0, 1, 0, 1, 1, {"label": "中風險有效 bug"}),
    ("valid_bug_report_high", "bug_bounty_high", "credit", "hard", 200, 200, 400, 0, 0, 1, 0, 1, 1, {"label": "高風險有效 bug"}),
    ("game_daily_quest", "game_daily_quest", "credit", "soft", 10, 10, 10, 24 * 60 * 60, 0, 0, 0, 1, 0, {"label": "遊戲每日任務"}),
    ("marketplace_sale_income", "marketplace_sale_income", "credit", "hard", 0, 0, None, 0, 0, 1, 0, 1, 1, {"label": "商城收入"}),
)

DEFAULT_PRICE_CATALOG = (
    ("post_cost_standard", "一般發文成本", "forum", "soft", 1, 0, 1, 10, 1, {"description": "防止洗版的基本回收"}),
    ("post_pin_24h", "文章置頂 24 小時", "forum", "soft", 100, 0, 50, 300, 1, {}),
    ("cloud_storage_1gb_30d", "雲端容量 1GB / 30 天", "cloud_drive", "soft", 100, 0, 50, 500, 1, {}),
    ("cloud_storage_10gb_30d", "雲端容量 10GB / 30 天", "cloud_drive", "hard", 30, 0, 10, 100, 1, {}),
    ("comfyui_txt2img_basic", "基礎生圖一次", "comfyui", "soft", 5, 1, 1, 25, 1, {}),
    ("comfyui_txt2img_highres", "高解析生圖一次", "comfyui", "hard", 2, 1, 1, 20, 1, {}),
    ("comfyui_batch_10", "批次生圖 10 張", "comfyui", "hard", 15, 1, 5, 80, 1, {}),
    ("server_rental_cpu_1h", "CPU Server 1 小時", "server_rental", "hard", 5, 1, 2, 30, 1, {}),
    ("server_rental_gpu_1h", "GPU Server 1 小時", "server_rental", "hard", 50, 1, 20, 200, 1, {}),
    ("game_virtual_item_common", "普通虛寶", "game", "soft", 20, 0, 5, 100, 1, {}),
    ("game_virtual_item_premium", "高級虛寶", "game", "hard", 5, 0, 1, 50, 1, {}),
    ("username_change", "改名", "account", "soft", 200, 0, 100, 1000, 1, {}),
    ("profile_decoration", "個人頁裝飾", "account", "soft", 50, 0, 10, 250, 1, {}),
)


def utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


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


def public_account_id(chain_secret, user_id):
    secret = chain_secret.encode("utf-8") if isinstance(chain_secret, str) else bytes(chain_secret or b"")
    return hmac.new(secret, str(int(user_id)).encode("utf-8"), hashlib.sha256).hexdigest()


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
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_points_ledger_no_delete
        BEFORE DELETE ON points_ledger
        BEGIN
            SELECT RAISE(ABORT, 'points ledger is append-only');
        END
        """
    )
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


class PointsLedgerService:
    def __init__(self, *, get_db, chain_secret, audit=None):
        self.get_db = get_db
        self.chain_secret = chain_secret
        self.audit = audit or (lambda *args, **kwargs: None)

    def ensure_schema(self, conn):
        ensure_points_economy_schema(conn)

    def _public_account_id(self, user_id):
        return public_account_id(self.chain_secret, user_id)

    def _audit_log(self, conn, event_type, severity, message, *, actor=None, target_user_id=None, ledger_id=None, block_id=None, metadata=None):
        conn.execute(
            """
            INSERT INTO points_chain_audit_logs (
                event_type, severity, actor_user_id, actor_role, target_user_id,
                related_ledger_id, related_block_id, message, metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_type,
                severity,
                int(actor["id"]) if actor and actor.get("id") else None,
                actor.get("role") if actor else None,
                target_user_id,
                ledger_id,
                block_id,
                message,
                _json_dumps(metadata or {}),
                utc_now(),
            ),
        )

    def ensure_wallet(self, conn, user_id):
        now = utc_now()
        conn.execute(
            """
            INSERT OR IGNORE INTO points_wallets (user_id, created_at, updated_at)
            VALUES (?, ?, ?)
            """,
            (int(user_id), now, now),
        )
        return conn.execute("SELECT * FROM points_wallets WHERE user_id=?", (int(user_id),)).fetchone()

    def get_wallet(self, user_id):
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            wallet = self.ensure_wallet(conn, user_id)
            conn.commit()
            return self.serialize_wallet(wallet)
        finally:
            conn.close()

    def serialize_wallet(self, row):
        if not row:
            return None
        return {
            "user_id": row["user_id"],
            "public_account_id": self._public_account_id(row["user_id"]),
            "soft_balance": row["soft_balance"],
            "hard_balance": row["hard_balance"],
            "soft_frozen": row["soft_frozen"],
            "hard_frozen": row["hard_frozen"],
            "total_soft_earned": row["total_soft_earned"],
            "total_hard_earned": row["total_hard_earned"],
            "total_soft_spent": row["total_soft_spent"],
            "total_hard_spent": row["total_hard_spent"],
            "wallet_status": row["wallet_status"],
            "risk_level": row["risk_level"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def serialize_ledger(self, row, *, include_user_id=False):
        data = {
            "id": row["id"],
            "ledger_uuid": row["ledger_uuid"],
            "public_account_id": row["public_account_id"],
            "currency_type": row["currency_type"],
            "direction": row["direction"],
            "amount": row["amount"],
            "balance_before": row["balance_before"],
            "balance_after": row["balance_after"],
            "action_type": row["action_type"],
            "reference_type": row["reference_type"],
            "reference_id": row["reference_id"],
            "reason": row["reason"],
            "public_metadata": _json_loads(row["public_metadata_json"], {}),
            "metadata_hash": row["metadata_hash"],
            "previous_ledger_hash": row["previous_ledger_hash"],
            "ledger_hash": row["ledger_hash"],
            "chain_block_id": row["chain_block_id"],
            "risk_flag": row["risk_flag"],
            "risk_score": row["risk_score"],
            "status": row["status"],
            "created_at": row["created_at"],
        }
        if include_user_id:
            data["user_id"] = row["user_id"]
            data["created_by"] = row["created_by"]
            data["created_by_role"] = row["created_by_role"]
        return data

    def _balance_column(self, currency_type):
        if currency_type not in CURRENCIES:
            raise ValueError("currency_type must be soft or hard")
        return "soft_balance" if currency_type == "soft" else "hard_balance"

    def _frozen_column(self, currency_type):
        return "soft_frozen" if currency_type == "soft" else "hard_frozen"

    def _earned_column(self, currency_type):
        return "total_soft_earned" if currency_type == "soft" else "total_hard_earned"

    def _spent_column(self, currency_type):
        return "total_soft_spent" if currency_type == "soft" else "total_hard_spent"

    def _last_ledger_hash(self, conn):
        row = conn.execute("SELECT ledger_hash FROM points_ledger ORDER BY id DESC LIMIT 1").fetchone()
        return row["ledger_hash"] if row else None

    def _existing_idempotent(self, conn, idempotency_key):
        if not idempotency_key:
            return None
        return conn.execute("SELECT * FROM points_ledger WHERE idempotency_key=?", (idempotency_key,)).fetchone()

    def _record_transaction(
        self,
        conn,
        *,
        user_id,
        currency_type,
        direction,
        amount,
        action_type,
        reference_type=None,
        reference_id=None,
        idempotency_key=None,
        reason="",
        public_metadata=None,
        private_metadata=None,
        sensitive_metadata_encrypted="",
        actor=None,
        risk_flag="none",
        risk_score=0,
    ):
        if currency_type not in CURRENCIES:
            raise ValueError("currency_type must be soft or hard")
        if direction not in LEDGER_DIRECTIONS:
            raise ValueError("unsupported ledger direction")
        amount = int(amount)
        if amount <= 0:
            raise ValueError("amount must be positive")
        existing = self._existing_idempotent(conn, idempotency_key)
        if existing:
            return existing, False

        wallet = self.ensure_wallet(conn, user_id)
        if wallet["wallet_status"] == "closed":
            raise ValueError("wallet is closed")
        if wallet["wallet_status"] == "frozen" and direction in {"credit", "debit", "freeze", "unfreeze"}:
            raise ValueError("wallet is frozen")

        balance_col = self._balance_column(currency_type)
        frozen_col = self._frozen_column(currency_type)
        earned_col = self._earned_column(currency_type)
        spent_col = self._spent_column(currency_type)
        balance_before = int(wallet[balance_col])
        frozen_before = int(wallet[frozen_col])
        balance_after = balance_before
        frozen_after = frozen_before
        earned_delta = 0
        spent_delta = 0

        if direction in {"credit", "transfer_in"}:
            balance_after += amount
            earned_delta = amount
        elif direction in {"debit", "transfer_out", "reverse"}:
            if balance_before < amount:
                raise ValueError("insufficient balance")
            balance_after -= amount
            spent_delta = amount
        elif direction == "freeze":
            if balance_before < amount:
                raise ValueError("insufficient balance")
            balance_after -= amount
            frozen_after += amount
        elif direction == "unfreeze":
            if frozen_before < amount:
                raise ValueError("insufficient frozen balance")
            balance_after += amount
            frozen_after -= amount

        public_json = _json_dumps(public_metadata or {})
        private_json = _json_dumps(private_metadata or {})
        meta_hash = metadata_hash(public_metadata or {}, private_metadata or {}, sensitive_metadata_encrypted or "")
        now = utc_now()
        ledger_uuid = str(uuid.uuid4())
        ledger_data = {
            "ledger_uuid": ledger_uuid,
            "public_account_id": self._public_account_id(user_id),
            "currency_type": currency_type,
            "direction": direction,
            "amount": amount,
            "balance_before": balance_before,
            "balance_after": balance_after,
            "action_type": action_type,
            "reference_type": reference_type,
            "reference_id": str(reference_id) if reference_id is not None else None,
            "metadata_hash": meta_hash,
            "previous_ledger_hash": self._last_ledger_hash(conn),
            "created_at": now,
        }
        ledger_hash = compute_ledger_hash(ledger_data)
        cur = conn.execute(
            """
            INSERT INTO points_ledger (
                ledger_uuid, user_id, public_account_id, currency_type, direction, amount,
                balance_before, balance_after, action_type, reference_type, reference_id,
                idempotency_key, reason, public_metadata_json, private_metadata_json,
                sensitive_metadata_encrypted, metadata_hash, previous_ledger_hash, ledger_hash,
                risk_flag, risk_score, created_by, created_by_role, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'confirmed', ?)
            """,
            (
                ledger_uuid,
                int(user_id),
                ledger_data["public_account_id"],
                currency_type,
                direction,
                amount,
                balance_before,
                balance_after,
                action_type,
                reference_type,
                ledger_data["reference_id"],
                idempotency_key,
                reason or "",
                public_json,
                private_json,
                sensitive_metadata_encrypted or "",
                meta_hash,
                ledger_data["previous_ledger_hash"],
                ledger_hash,
                risk_flag,
                int(risk_score or 0),
                int(actor["id"]) if actor and actor.get("id") else None,
                actor.get("role") if actor else None,
                now,
            ),
        )
        conn.execute(
            f"""
            UPDATE points_wallets
            SET {balance_col}=?, {frozen_col}=?, {earned_col}={earned_col}+?, {spent_col}={spent_col}+?, updated_at=?
            WHERE user_id=?
            """,
            (balance_after, frozen_after, earned_delta, spent_delta, now, int(user_id)),
        )
        row = conn.execute("SELECT * FROM points_ledger WHERE id=?", (cur.lastrowid,)).fetchone()
        self._audit_log(
            conn,
            "LEDGER_APPEND",
            "info",
            f"{direction} {amount} {currency_type} for user {user_id}",
            actor=actor,
            target_user_id=int(user_id),
            ledger_id=row["id"],
            metadata={"action_type": action_type, "reference_type": reference_type, "reference_id": reference_id},
        )
        return row, True

    def record_transaction(self, **kwargs):
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            conn.commit()
            conn.execute("BEGIN IMMEDIATE")
            row, created = self._record_transaction(conn, **kwargs)
            conn.commit()
            return {"ok": True, "created": created, "ledger": self.serialize_ledger(row, include_user_id=True), "wallet": self.get_wallet(row["user_id"])}
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _rule_for_key(self, conn, rule_key):
        return conn.execute("SELECT * FROM points_rules WHERE rule_key=? AND enabled=1", (rule_key,)).fetchone()

    def earn_points(self, *, user_id, rule_key, reference_type=None, reference_id=None, idempotency_key=None, metadata=None, actor=None):
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            conn.commit()
            conn.execute("BEGIN IMMEDIATE")
            rule = self._rule_for_key(conn, rule_key)
            if not rule:
                raise ValueError("points rule not found or disabled")
            if rule["direction"] != "credit":
                raise ValueError("rule is not a credit rule")
            if rule["requires_admin_review"]:
                pending = self._create_pending_reward(
                    conn,
                    user_id=user_id,
                    currency_type=rule["currency_type"],
                    amount=rule["base_amount"],
                    action_type=rule["action_type"],
                    reference_type=reference_type,
                    reference_id=reference_id,
                    metadata=metadata,
                    submitted_by=actor["id"] if actor else user_id,
                )
                conn.commit()
                return {"ok": True, "pending_review": True, "pending_reward": dict(pending)}
            amount = int(rule["base_amount"])
            self._enforce_rule_limits(conn, user_id=user_id, rule=rule, amount=amount)
            row, created = self._record_transaction(
                conn,
                user_id=user_id,
                currency_type=rule["currency_type"],
                direction="credit",
                amount=amount,
                action_type=rule["action_type"],
                reference_type=reference_type,
                reference_id=reference_id,
                idempotency_key=idempotency_key or f"{rule_key}:{user_id}:{reference_type or ''}:{reference_id or ''}",
                reason=f"rule:{rule_key}",
                public_metadata=metadata or {},
                actor=actor,
            )
            conn.commit()
            return {"ok": True, "created": created, "ledger": self.serialize_ledger(row), "wallet": self.get_wallet(user_id)}
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _enforce_rule_limits(self, conn, *, user_id, rule, amount):
        today = datetime.now(timezone.utc).date().isoformat()
        if rule["daily_user_limit"]:
            row = conn.execute(
                """
                SELECT COALESCE(SUM(amount), 0) AS total
                FROM points_ledger
                WHERE user_id=? AND action_type=? AND status='confirmed' AND created_at>=?
                """,
                (int(user_id), rule["action_type"], today),
            ).fetchone()
            if int(row["total"] or 0) + int(amount) > int(rule["daily_user_limit"]):
                raise ValueError("daily user points limit exceeded")
        if rule["cooldown_seconds"]:
            row = conn.execute(
                """
                SELECT created_at FROM points_ledger
                WHERE user_id=? AND action_type=? AND status='confirmed'
                ORDER BY created_at DESC LIMIT 1
                """,
                (int(user_id), rule["action_type"]),
            ).fetchone()
            if row and row["created_at"]:
                try:
                    last = datetime.fromisoformat(row["created_at"].replace("Z", "+00:00"))
                    elapsed = (datetime.now(timezone.utc) - last).total_seconds()
                    if elapsed < int(rule["cooldown_seconds"]):
                        raise ValueError("points rule cooldown active")
                except ValueError:
                    raise
                except Exception:
                    pass

    def spend_points(self, *, user_id, item_key, quantity=1, reference_type=None, reference_id=None, idempotency_key=None, metadata=None, actor=None):
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            conn.commit()
            conn.execute("BEGIN IMMEDIATE")
            item = conn.execute("SELECT * FROM economy_price_catalog WHERE item_key=? AND enabled=1", (item_key,)).fetchone()
            if not item:
                raise ValueError("price catalog item not found or disabled")
            quantity = max(1, int(quantity or 1))
            amount = int(item["base_price"]) * quantity
            row, created = self._record_transaction(
                conn,
                user_id=user_id,
                currency_type=item["currency_type"],
                direction="debit",
                amount=amount,
                action_type=f"spend:{item_key}",
                reference_type=reference_type or "price_catalog",
                reference_id=reference_id or item_key,
                idempotency_key=idempotency_key or f"spend:{user_id}:{item_key}:{reference_id or uuid.uuid4()}",
                reason=f"spend:{item['item_name']}",
                public_metadata={"item_key": item_key, "quantity": quantity, **(metadata or {})},
                actor=actor,
            )
            conn.commit()
            return {"ok": True, "created": created, "ledger": self.serialize_ledger(row), "wallet": self.get_wallet(user_id), "item": dict(item)}
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def admin_adjust(self, *, actor, user_id, currency_type, direction, amount, reason, reference_id=None):
        if direction not in {"credit", "debit"}:
            raise ValueError("direction must be credit or debit")
        if not str(reason or "").strip():
            raise ValueError("reason is required")
        return self.record_transaction(
            user_id=user_id,
            currency_type=currency_type,
            direction=direction,
            amount=amount,
            action_type=f"admin_adjust_{direction}",
            reference_type="admin_adjustment",
            reference_id=reference_id or f"actor:{actor.get('id')}:target:{user_id}:{utc_now()}",
            idempotency_key=None,
            reason=reason,
            public_metadata={"admin_action": True},
            private_metadata={"actor_username": actor.get("username")},
            actor=actor,
        )

    def _create_pending_reward(self, conn, *, user_id, currency_type, amount, action_type, reference_type=None, reference_id=None, metadata=None, submitted_by=None):
        cur = conn.execute(
            """
            INSERT INTO points_pending_rewards (
                user_id, currency_type, amount, action_type, reference_type, reference_id,
                status, submitted_by, metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)
            """,
            (int(user_id), currency_type, int(amount), action_type, reference_type, str(reference_id or ""), submitted_by, _json_dumps(metadata or {}), utc_now()),
        )
        return conn.execute("SELECT * FROM points_pending_rewards WHERE id=?", (cur.lastrowid,)).fetchone()

    def create_pending_reward(self, *, actor, user_id, currency_type, amount, action_type, reference_type=None, reference_id=None, metadata=None):
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            conn.commit()
            conn.execute("BEGIN IMMEDIATE")
            row = self._create_pending_reward(
                conn,
                user_id=user_id,
                currency_type=currency_type,
                amount=amount,
                action_type=action_type,
                reference_type=reference_type,
                reference_id=reference_id,
                metadata=metadata,
                submitted_by=actor.get("id") if actor else None,
            )
            self._audit_log(conn, "PENDING_REWARD_CREATED", "info", f"pending reward {row['id']} created", actor=actor, target_user_id=int(user_id))
            conn.commit()
            return dict(row)
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def review_pending_reward(self, *, actor, pending_reward_id, decision, review_note=""):
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            conn.commit()
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM points_pending_rewards WHERE id=?", (int(pending_reward_id),)).fetchone()
            if not row:
                raise ValueError("pending reward not found")
            if row["status"] != "pending":
                raise ValueError("pending reward already reviewed")
            decision = str(decision or "").lower()
            if decision not in {"approve", "reject"}:
                raise ValueError("decision must be approve or reject")
            status = "approved" if decision == "approve" else "rejected"
            conn.execute(
                """
                UPDATE points_pending_rewards
                SET status=?, reviewed_by=?, review_note=?, reviewed_at=?
                WHERE id=? AND status='pending'
                """,
                (status, actor.get("id") if actor else None, review_note or "", utc_now(), int(pending_reward_id)),
            )
            ledger = None
            if decision == "approve":
                ledger, _ = self._record_transaction(
                    conn,
                    user_id=row["user_id"],
                    currency_type=row["currency_type"],
                    direction="credit",
                    amount=row["amount"],
                    action_type=row["action_type"],
                    reference_type=row["reference_type"] or "pending_reward",
                    reference_id=row["reference_id"] or str(row["id"]),
                    idempotency_key=f"pending_reward:{row['id']}",
                    reason=review_note or "approved pending reward",
                    public_metadata={"pending_reward_id": row["id"]},
                    actor=actor,
                )
            self._audit_log(conn, "PENDING_REWARD_REVIEWED", "info", f"pending reward {pending_reward_id} {status}", actor=actor, target_user_id=row["user_id"], ledger_id=ledger["id"] if ledger else None)
            refreshed = conn.execute("SELECT * FROM points_pending_rewards WHERE id=?", (int(pending_reward_id),)).fetchone()
            conn.commit()
            return {"pending_reward": dict(refreshed), "ledger": self.serialize_ledger(ledger) if ledger else None}
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def list_ledger(self, *, user_id=None, limit=50, offset=0, include_user_id=False):
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            limit = min(200, max(1, int(limit or 50)))
            offset = max(0, int(offset or 0))
            if user_id:
                rows = conn.execute(
                    "SELECT * FROM points_ledger WHERE user_id=? ORDER BY id DESC LIMIT ? OFFSET ?",
                    (int(user_id), limit, offset),
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM points_ledger ORDER BY id DESC LIMIT ? OFFSET ?", (limit, offset)).fetchall()
            return [self.serialize_ledger(row, include_user_id=include_user_id) for row in rows]
        finally:
            conn.close()

    def list_rules(self):
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            return [dict(row) for row in conn.execute("SELECT * FROM points_rules ORDER BY rule_key").fetchall()]
        finally:
            conn.close()

    def list_catalog(self):
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            rows = conn.execute("SELECT * FROM economy_price_catalog WHERE enabled=1 ORDER BY category, base_price, item_key").fetchall()
            return [{**dict(row), "metadata": _json_loads(row["metadata_json"], {})} for row in rows]
        finally:
            conn.close()

    def list_pending_rewards(self, *, status="pending", limit=100):
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            rows = conn.execute(
                "SELECT * FROM points_pending_rewards WHERE status=? ORDER BY created_at DESC LIMIT ?",
                (status or "pending", min(200, max(1, int(limit or 100)))),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def seal_block(self, *, actor=None, limit=100):
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            conn.commit()
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                """
                SELECT * FROM points_ledger
                WHERE status='confirmed' AND chain_block_id IS NULL
                ORDER BY id ASC LIMIT ?
                """,
                (min(500, max(1, int(limit or 100))),),
            ).fetchall()
            if not rows:
                conn.commit()
                return {"ok": True, "sealed": False, "msg": "no unsealed ledger entries"}
            last = conn.execute("SELECT * FROM points_chain_blocks ORDER BY block_number DESC LIMIT 1").fetchone()
            block_number = int(last["block_number"] + 1) if last else 1
            prev_hash = last["block_hash"] if last else None
            hashes = [row["ledger_hash"] for row in rows]
            sealed_at = utc_now()
            block_data = {
                "block_number": block_number,
                "previous_block_hash": prev_hash,
                "merkle_root": merkle_root(hashes),
                "ledger_count": len(rows),
                "first_ledger_id": rows[0]["id"],
                "last_ledger_id": rows[-1]["id"],
                "sealed_at": sealed_at,
            }
            block_hash = compute_block_hash(block_data)
            cur = conn.execute(
                """
                INSERT INTO points_chain_blocks (
                    block_number, previous_block_hash, merkle_root, block_hash,
                    ledger_count, first_ledger_id, last_ledger_id, sealed_by,
                    sealed_by_node, sealed_at, seal_status, anchor_status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'sealed', 'local_only', ?)
                """,
                (
                    block_number,
                    prev_hash,
                    block_data["merkle_root"],
                    block_hash,
                    len(rows),
                    rows[0]["id"],
                    rows[-1]["id"],
                    actor.get("id") if actor else None,
                    "single-node",
                    sealed_at,
                    sealed_at,
                ),
            )
            block_id = cur.lastrowid
            ids = [row["id"] for row in rows]
            conn.execute(
                f"UPDATE points_ledger SET chain_block_id=? WHERE id IN ({','.join('?' for _ in ids)})",
                (block_id, *ids),
            )
            self._audit_log(conn, "POINTS_BLOCK_SEALED", "info", f"sealed points block {block_number}", actor=actor, block_id=block_id, metadata={"ledger_count": len(rows)})
            block = conn.execute("SELECT * FROM points_chain_blocks WHERE id=?", (block_id,)).fetchone()
            conn.commit()
            return {"ok": True, "sealed": True, "block": dict(block)}
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def verify_chain(self):
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            errors = []
            previous = None
            for row in conn.execute("SELECT * FROM points_ledger ORDER BY id ASC").fetchall():
                if row["previous_ledger_hash"] != previous:
                    errors.append({"type": "ledger_previous_hash", "ledger_id": row["id"]})
                expected = compute_ledger_hash(row)
                if row["ledger_hash"] != expected:
                    errors.append({"type": "ledger_hash", "ledger_id": row["id"]})
                previous = row["ledger_hash"]
            previous_block = None
            for block in conn.execute("SELECT * FROM points_chain_blocks ORDER BY block_number ASC").fetchall():
                if block["previous_block_hash"] != previous_block:
                    errors.append({"type": "block_previous_hash", "block_id": block["id"]})
                ledgers = conn.execute(
                    "SELECT ledger_hash FROM points_ledger WHERE id BETWEEN ? AND ? ORDER BY id ASC",
                    (block["first_ledger_id"], block["last_ledger_id"]),
                ).fetchall()
                hashes = [row["ledger_hash"] for row in ledgers]
                if len(hashes) != int(block["ledger_count"]):
                    errors.append({"type": "block_ledger_count", "block_id": block["id"]})
                if merkle_root(hashes) != block["merkle_root"]:
                    errors.append({"type": "block_merkle_root", "block_id": block["id"]})
                if compute_block_hash(block) != block["block_hash"]:
                    errors.append({"type": "block_hash", "block_id": block["id"]})
                previous_block = block["block_hash"]
            counts = {
                "ledger_entries": conn.execute("SELECT COUNT(*) AS c FROM points_ledger").fetchone()["c"],
                "sealed_blocks": conn.execute("SELECT COUNT(*) AS c FROM points_chain_blocks").fetchone()["c"],
                "unsealed_entries": conn.execute("SELECT COUNT(*) AS c FROM points_ledger WHERE chain_block_id IS NULL").fetchone()["c"],
            }
            return {"ok": not errors, "errors": errors[:100], "error_count": len(errors), "counts": counts}
        finally:
            conn.close()

    def ledger_proof(self, ledger_uuid):
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            ledger = conn.execute("SELECT * FROM points_ledger WHERE ledger_uuid=?", (ledger_uuid,)).fetchone()
            if not ledger:
                return None
            if not ledger["chain_block_id"]:
                return {"sealed": False, "ledger": self.serialize_ledger(ledger), "ledger_hash": ledger["ledger_hash"]}
            block = conn.execute("SELECT * FROM points_chain_blocks WHERE id=?", (ledger["chain_block_id"],)).fetchone()
            rows = conn.execute(
                "SELECT id, ledger_hash FROM points_ledger WHERE id BETWEEN ? AND ? ORDER BY id ASC",
                (block["first_ledger_id"], block["last_ledger_id"]),
            ).fetchall()
            hashes = [row["ledger_hash"] for row in rows]
            ids = [row["id"] for row in rows]
            index = ids.index(ledger["id"])
            return {
                "sealed": True,
                "ledger_uuid": ledger["ledger_uuid"],
                "public_account_id": ledger["public_account_id"],
                "ledger_hash": ledger["ledger_hash"],
                "block_number": block["block_number"],
                "merkle_root": block["merkle_root"],
                "merkle_path": merkle_proof(hashes, index),
                "block_hash": block["block_hash"],
            }
        finally:
            conn.close()

    def economy_stats(self):
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            wallet = conn.execute(
                """
                SELECT COALESCE(SUM(soft_balance), 0) AS soft_balance,
                       COALESCE(SUM(hard_balance), 0) AS hard_balance,
                       COALESCE(SUM(soft_frozen), 0) AS soft_frozen,
                       COALESCE(SUM(hard_frozen), 0) AS hard_frozen,
                       COUNT(*) AS wallets
                FROM points_wallets
                """
            ).fetchone()
            ledger = conn.execute(
                """
                SELECT
                    COALESCE(SUM(CASE WHEN currency_type='soft' AND direction IN ('credit','transfer_in') THEN amount ELSE 0 END), 0) AS soft_issued,
                    COALESCE(SUM(CASE WHEN currency_type='soft' AND direction IN ('debit','transfer_out','reverse') THEN amount ELSE 0 END), 0) AS soft_spent,
                    COALESCE(SUM(CASE WHEN currency_type='hard' AND direction IN ('credit','transfer_in') THEN amount ELSE 0 END), 0) AS hard_issued,
                    COALESCE(SUM(CASE WHEN currency_type='hard' AND direction IN ('debit','transfer_out','reverse') THEN amount ELSE 0 END), 0) AS hard_spent,
                    COUNT(*) AS ledger_entries
                FROM points_ledger
                WHERE status='confirmed'
                """
            ).fetchone()
            chain = self.verify_chain()
            return {"wallets": dict(wallet), "ledger": dict(ledger), "chain": chain}
        finally:
            conn.close()
