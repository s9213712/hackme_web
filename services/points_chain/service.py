"""PointsChain ledger, wallet, and verification service."""

import threading
from datetime import timedelta

from . import schema as _schema
from .economy_layer import (
    append_economy_event,
    bootstrap_economy_layer,
    economy_fund_address,
    ensure_economy_layer_schema,
    economy_layer_report,
    replay_economy_events,
)
from .wallet_identity import (
    WALLET_ADDRESS_RE,
    address_dispute_payload,
    canonical_public_jwk,
    ensure_wallet_identity_schema,
    verify_wallet_address_dispute_signature,
    verify_wallet_service_fee_signature,
    verify_wallet_transaction_signature,
)

globals().update({name: value for name, value in _schema.__dict__.items() if not name.startswith("__")})

EXPLORER_FINALITY_PROVED_COUNT = 20
EXPLORER_BASE_FINALITY_MIN_SECONDS = 120
EXPLORER_BASE_FINALITY_MAX_SECONDS = 180
EXPLORER_ACCELERATED_FINALITY_MIN_SECONDS = 30
EXPLORER_ACCELERATED_FINALITY_MAX_SECONDS = 45
EXPLORER_ACCELERATION_REFERENCE_FEE_POINTS = 20
EXPLORER_MAX_ACCELERATION_FEE_POINTS = 10000
SERVICE_BATCH_SETTLEMENT_MIN_POINTS = 100
WALLET_CREATION_FEE_BASE_POINTS = 25
WALLET_CREATION_FEE_MULTIPLIER = 2
WALLET_CREATION_FEE_MAX_POINTS = 100_000
PROVISIONAL_ADDRESS_FREEZE_SECONDS = 24 * 60 * 60
DISPUTE_INITIAL_FREEZE_SECONDS = 60 * 60
DISPUTE_ESCALATED_FREEZE_SECONDS = 24 * 60 * 60
DISPUTE_VOTING_GRACE_SECONDS = 10 * 60
DISPUTE_FROM_DAILY_LIMIT = 3
GOV_RATE_UNIT_SUFFIX = "b" + "ps"
GOV_QUORUM_RATE_FIELD = "quorum_" + GOV_RATE_UNIT_SUFFIX
GOV_PASS_THRESHOLD_RATE_FIELD = "pass_threshold_" + GOV_RATE_UNIT_SUFFIX
GOV_YES_THRESHOLD_RATE_FIELD = "yes_threshold_" + GOV_RATE_UNIT_SUFFIX
GOV_VOTE_DIFFERENTIAL_REQUIRED_RATE_FIELD = "vote_differential_required_" + GOV_RATE_UNIT_SUFFIX
GOV_VOTE_DIFFERENTIAL_RATE_FIELD = "vote_differential_" + GOV_RATE_UNIT_SUFFIX
GOV_APPROVAL_RATE_FIELD = "approval_" + GOV_RATE_UNIT_SUFFIX
GOV_QUORUM_DELTA_RATE_FIELD = "quorum_delta_" + GOV_RATE_UNIT_SUFFIX


def _connection_path(conn):
    try:
        row = conn.execute("PRAGMA database_list").fetchone()
        return str(row["file"] if hasattr(row, "keys") else row[2])
    except Exception:
        return ""


class PointsLedgerService:
    _schema_lock = threading.Lock()
    _schema_ready_paths = set()
    _wallet_lock = threading.Lock()

    def __init__(self, *, get_db, chain_secret, audit=None, backup_dir=None, mode_reader=None, security_event_recorder=None):
        self.get_db = get_db
        self.chain_secret = chain_secret
        self.audit = audit or (lambda *args, **kwargs: None)
        self.backup_dir = Path(backup_dir or os.environ.get("POINTS_CHAIN_BACKUP_DIR") or "./secure_backups/points_chain")
        # Phase 7: production-only guard. mode_reader is injected so
        # this module stays decoupled from server / Flask. Default
        # behavior when no reader is configured: refuse the write —
        # this is intentional. A non-configured reader means we can't
        # prove we're in production, and PointsChain MUST default to
        # safe-locked, never to production-routing.
        self._mode_reader = mode_reader
        self._security_event_recorder = security_event_recorder or (lambda *a, **kw: None)

    def rc1_facade(self):
        from .wallet_facade import WalletServiceFacade

        return WalletServiceFacade(points_service=self)

    def ensure_schema(self, conn):
        db_path = _connection_path(conn)
        if db_path and db_path in self._schema_ready_paths:
            return
        with self._schema_lock:
            if db_path and db_path in self._schema_ready_paths:
                return
            ensure_points_economy_schema(conn)
            ensure_wallet_identity_schema(conn)
            ensure_economy_layer_schema(conn)
            if db_path:
                self._schema_ready_paths.add(db_path)

    def _public_account_id(self, user_id):
        return public_account_id(self.chain_secret, user_id)

    def _node_fingerprint(self):
        return sha256_text(f"pointschain-node:{self.chain_secret}")

    def _sign_block(self, block):
        hmac_key = str(self.chain_secret or "").encode("utf-8")
        return hmac.new(hmac_key, block_signature_payload(block).encode("utf-8"), hashlib.sha256).hexdigest()

    def _sign_backup_manifest(self, manifest_without_signature):
        hmac_key = f"points-chain-backup:{self.chain_secret or ''}".encode("utf-8")
        return hmac.new(hmac_key, canonical_json(manifest_without_signature).encode("utf-8"), hashlib.sha256).hexdigest()

    def _backup_root(self):
        root = self.backup_dir.expanduser()
        root.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(root, 0o700)
        except Exception:
            pass
        for name in ("backups", "forensics"):
            path = root / name
            path.mkdir(parents=True, exist_ok=True)
            try:
                os.chmod(path, 0o700)
            except Exception:
                pass
        return root

    def _safe_mode_row(self, conn):
        return conn.execute("SELECT * FROM points_chain_recovery_state WHERE id=1").fetchone()

    def _safe_mode_status(self, conn):
        row = self._safe_mode_row(conn)
        if not row:
            return {"safe_mode": False}
        plan = _json_loads(row["restore_plan_json"], {})
        return {
            "safe_mode": bool(row["safe_mode"]),
            "reason": row["reason"] or "",
            "forensic_bundle_id": row["forensic_bundle_id"],
            "restore_plan": plan,
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "restored_at": row["restored_at"],
            "verification": _json_loads(row["verification_json"], {}),
        }

    def safe_mode_status(self):
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            return self._safe_mode_status(conn)
        finally:
            conn.close()

    def _assert_chain_writable(self, conn, action):
        row = self._safe_mode_row(conn)
        if row and int(row["safe_mode"] or 0):
            raise ValueError(f"PointsChain safe mode active; {action} is paused until root restores a healthy ledger backup")

    def _assert_production_mode(self, action):
        """Phase 7 guard for block sealing modes.

        Reads the mode every call (no caching) so a switch out of
        an allowed sealing mode immediately blocks subsequent writes. If the mode
        reader is unavailable or raises, we still refuse the write —
        chain integrity outweighs convenience. The violation is
        logged as a `chain_mode_violation` security event so the
        attempt is visible even when the caller swallows the
        exception.
        """
        mode = None
        try:
            if callable(self._mode_reader):
                mode = self._mode_reader()
        except Exception:
            mode = None
        if mode not in {"production", "dev_ready"}:
            try:
                self._security_event_recorder(
                    "chain_mode_violation",
                    target_user="-",
                    detail=f"action={action},mode={mode!r}",
                )
            except Exception:
                pass
            raise ChainModeViolation(mode, action=action)

    def _main_branch_uuid(self):
        return "main"

    def _canonical_branch_uuid(self, conn):
        try:
            row = conn.execute(
                """
                SELECT branch_uuid
                FROM points_chain_governance_branches
                WHERE is_canonical=1 AND write_enabled=1
                ORDER BY id DESC LIMIT 1
                """
            ).fetchone()
            if row and row["branch_uuid"]:
                return str(row["branch_uuid"])
        except Exception:
            pass
        return self._main_branch_uuid()

    def _branch_metadata(self, conn, branch_uuid=None):
        branch = str(branch_uuid or self._canonical_branch_uuid(conn) or self._main_branch_uuid()).strip() or self._main_branch_uuid()
        if branch == self._main_branch_uuid():
            row = conn.execute(
                """
                SELECT COUNT(*) AS archived_count
                FROM points_chain_governance_branches
                WHERE parent_branch_uuid='' AND status IN ('archived', 'read_only_archived')
                """
            ).fetchone()
            archived = bool(row and int(row["archived_count"] or 0))
            return {
                "branch_uuid": branch,
                "branch_name": "main",
                "parent_branch_uuid": "",
                "is_canonical": not archived,
                "write_enabled": not archived,
                "status": "read_only_archived" if archived else "canonical_main",
                "asset_universe": "main",
            }
        row = conn.execute(
            "SELECT * FROM points_chain_governance_branches WHERE branch_uuid=?",
            (branch,),
        ).fetchone()
        if not row:
            return {
                "branch_uuid": branch,
                "branch_name": branch,
                "parent_branch_uuid": "",
                "is_canonical": False,
                "write_enabled": False,
                "status": "unknown",
                "asset_universe": branch,
            }
        return {
            "branch_uuid": row["branch_uuid"],
            "branch_name": row["branch_name"],
            "parent_branch_uuid": row["parent_branch_uuid"],
            "is_canonical": bool(row["is_canonical"]),
            "write_enabled": bool(row["write_enabled"]),
            "status": row["status"],
            "asset_universe": row["branch_uuid"],
            "recovery_type": row["recovery_type"] if "recovery_type" in row.keys() else "canonical_pointer_only",
            "activated_at": row["activated_at"],
        }

    def _assert_canonical_write_branch(self, conn, branch_uuid):
        branch = str(branch_uuid or self._main_branch_uuid()).strip() or self._main_branch_uuid()
        canonical = self._canonical_branch_uuid(conn)
        if branch != canonical:
            raise PermissionError("chain branch is no longer canonical; old-branch assets are read-only and cannot be spent on the active branch")
        meta = self._branch_metadata(conn, branch)
        if not meta.get("write_enabled", True):
            raise PermissionError("chain branch is read-only and cannot accept new transactions")
        return branch

    def _wallet_totals_from_ledger(self, rows, *, branch_uuid=None):
        totals = {}
        branch_filter = str(branch_uuid or "").strip()
        for row in rows:
            if branch_filter and str(row["chain_branch"] if "chain_branch" in row.keys() else "main") != branch_filter:
                continue
            user_id = int(row["user_id"])
            item = totals.setdefault(user_id, {
                "balance": 0,
                "frozen": 0,
                "earned": 0,
                "spent": 0,
            })
            amount = int(row["amount"])
            direction = row["direction"]
            public_metadata = _json_loads(row["public_metadata_json"], {})
            earned_delta, spent_delta = self._wallet_statement_deltas(
                direction=direction,
                amount=amount,
                action_type=row["action_type"],
                public_metadata=public_metadata,
            )
            if direction in {"credit", "transfer_in"}:
                item["balance"] += amount
            elif direction in {"debit", "transfer_out", "reverse"}:
                item["balance"] -= amount
            elif direction == "freeze":
                item["balance"] -= amount
                item["frozen"] += amount
            elif direction == "unfreeze":
                item["balance"] += amount
                item["frozen"] -= amount
            item["earned"] += earned_delta
            item["spent"] += spent_delta
            if item["balance"] < 0 or item["frozen"] < 0:
                raise ValueError(f"ledger replay would create negative wallet for user {user_id}")
        return totals

    def _wallet_statement_totals_for_user(self, conn, user_id):
        branch = self._canonical_branch_uuid(conn)
        rows = conn.execute(
            """
            SELECT * FROM points_ledger
            WHERE user_id=? AND chain_branch=?
            ORDER BY id ASC
            """,
            (int(user_id), branch),
        ).fetchall()
        return self._wallet_totals_from_ledger(rows, branch_uuid=branch).get(int(user_id), {
            "balance": 0,
            "frozen": 0,
            "earned": 0,
            "spent": 0,
        })

    def _wallet_identity_adjusted_totals(self, conn, user_id, total):
        adjusted = dict(total or {"balance": 0, "frozen": 0, "earned": 0, "spent": 0})
        try:
            identity_balances = self._wallet_identity_balances_for_user(conn, user_id, include_pending=False)
        except Exception:
            return adjusted
        if not identity_balances.get("has_identity"):
            return adjusted
        balances = identity_balances.get("balances") or {}
        adjusted["balance"] = sum(int(item.get("balance") or 0) for item in balances.values())
        adjusted["frozen"] = sum(int(item.get("frozen") or 0) for item in balances.values())
        return adjusted

    def _wallet_identity_has_history(self, conn, user_id):
        try:
            return bool(self._wallet_identity_state_for_user(conn, user_id).get("has_identity"))
        except Exception:
            return False

    def _rebuild_wallets_from_ledger(self, conn):
        started_transaction = False
        if not conn.in_transaction:
            conn.execute("BEGIN IMMEDIATE")
            started_transaction = True
        try:
            branch = self._canonical_branch_uuid(conn)
            rows = conn.execute("SELECT * FROM points_ledger WHERE chain_branch=? ORDER BY id ASC", (branch,)).fetchall()
            totals = self._wallet_totals_from_ledger(rows, branch_uuid=branch)
            now = utc_now()
            existing = {
                int(row["user_id"]): dict(row)
                for row in conn.execute("SELECT * FROM points_wallets").fetchall()
            }
            conn.execute("DELETE FROM points_wallets")
            user_ids = {int(row["id"]) for row in conn.execute("SELECT id FROM users").fetchall()}
            user_ids.update(totals.keys())
            for user_id in sorted(user_ids):
                old = existing.get(user_id, {})
                total = totals.get(user_id, {"balance": 0, "frozen": 0, "earned": 0, "spent": 0})
                total = self._wallet_identity_adjusted_totals(conn, user_id, total)
                conn.execute(
                    """
                    INSERT INTO points_wallets (
                        user_id, soft_balance, hard_balance, soft_frozen, hard_frozen,
                        total_soft_earned, total_hard_earned, total_soft_spent, total_hard_spent,
                        wallet_status, risk_level, created_at, updated_at
                    ) VALUES (?, ?, 0, ?, 0, ?, 0, ?, 0, ?, ?, ?, ?)
                    """,
                    (
                        user_id,
                        int(total["balance"]),
                        int(total["frozen"]),
                        int(total["earned"]),
                        int(total["spent"]),
                        old.get("wallet_status") or "active",
                        old.get("risk_level") or "normal",
                        old.get("created_at") or now,
                        now,
                    ),
                )
            if started_transaction:
                conn.commit()
            return {"wallets_rebuilt": len(user_ids), "source_ledger_rows": len(rows)}
        except Exception:
            if started_transaction:
                conn.rollback()
            raise

    def _verify_wallets_against_ledger(self, conn):
        branch = self._canonical_branch_uuid(conn)
        rows = conn.execute("SELECT * FROM points_ledger WHERE chain_branch=? ORDER BY id ASC", (branch,)).fetchall()
        totals = self._wallet_totals_from_ledger(rows, branch_uuid=branch)
        wallet_rows = {
            int(row["user_id"]): row
            for row in conn.execute("SELECT * FROM points_wallets ORDER BY user_id ASC").fetchall()
        }
        user_ids = set(wallet_rows.keys())
        user_ids.update(totals.keys())
        user_ids.update(int(row["id"]) for row in conn.execute("SELECT id FROM users").fetchall())
        errors = []
        for user_id in sorted(user_ids):
            wallet = wallet_rows.get(user_id)
            expected = totals.get(user_id, {"balance": 0, "frozen": 0, "earned": 0, "spent": 0})
            expected = self._wallet_identity_adjusted_totals(conn, user_id, expected)
            if not wallet:
                if any(int(expected[key]) for key in ("balance", "frozen", "earned", "spent")):
                    repairable_derived_cache = self._wallet_identity_has_history(conn, user_id)
                    errors.append({
                        "type": "wallet_missing",
                        "severity": "medium" if repairable_derived_cache else "critical",
                        "message": f"wallet for user #{user_id} is missing but ledger has balance data",
                        "user_id": user_id,
                        "expected": expected,
                        "repairable_derived_cache": repairable_derived_cache,
                    })
                continue
            comparisons = {
                "soft_balance": int(expected["balance"]),
                "soft_frozen": int(expected["frozen"]),
                "total_soft_earned": int(expected["earned"]),
                "total_soft_spent": int(expected["spent"]),
                "hard_balance": 0,
                "hard_frozen": 0,
                "total_hard_earned": 0,
                "total_hard_spent": 0,
            }
            mismatches = []
            for column, expected_value in comparisons.items():
                actual_value = int(wallet[column] or 0)
                if actual_value != expected_value:
                    mismatches.append({"field": column, "expected": expected_value, "actual": actual_value})
            if mismatches:
                repairable_derived_cache = self._wallet_identity_has_history(conn, user_id)
                errors.append({
                    "type": "wallet_ledger_mismatch",
                    "severity": "medium" if repairable_derived_cache else "critical",
                    "message": f"wallet for user #{user_id} does not match ledger replay",
                    "user_id": user_id,
                    "mismatches": mismatches,
                    "repairable_derived_cache": repairable_derived_cache,
                })
        return errors

    def restore_from_backup(self, *, actor, backup_id, confirm):
        if str(confirm or "") != "RESTORE POINTSCHAIN":
            raise ValueError("confirm must be RESTORE POINTSCHAIN")
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            conn.commit()
            conn.execute("BEGIN IMMEDIATE")
            state = self._safe_mode_status(conn)
            if not state.get("safe_mode"):
                raise ValueError("PointsChain is not in safe mode")
            catalog, payload, manifest = self._load_backup_from_catalog(conn, backup_id)
            if not catalog:
                raise ValueError("backup not found")
            verification = self._verify_backup_payload(payload, manifest)
            if not verification["ok"]:
                raise ValueError("backup verification failed")
            abnormal = self._create_ledger_backup(conn, reason="pre_restore_abnormal_state", kind="pre_restore_abnormal")

            conn.execute("DROP TRIGGER IF EXISTS trg_points_ledger_no_delete")
            conn.execute("DROP TRIGGER IF EXISTS trg_points_ledger_core_immutable")
            conn.execute("DROP TRIGGER IF EXISTS trg_points_chain_blocks_no_update")
            conn.execute("DROP TRIGGER IF EXISTS trg_points_chain_blocks_no_delete")
            conn.execute("DROP TRIGGER IF EXISTS trg_points_chain_block_signatures_no_update")
            conn.execute("DROP TRIGGER IF EXISTS trg_points_chain_block_signatures_no_delete")
            conn.execute("DROP TRIGGER IF EXISTS trg_points_chain_governance_audit_no_update")
            conn.execute("DROP TRIGGER IF EXISTS trg_points_chain_governance_audit_no_delete")
            conn.execute("DROP TRIGGER IF EXISTS trg_points_economy_events_no_update")
            conn.execute("DROP TRIGGER IF EXISTS trg_points_economy_events_no_delete")
            conn.execute("DROP TRIGGER IF EXISTS trg_points_economy_incidents_core_immutable")
            conn.execute("DROP TRIGGER IF EXISTS trg_points_economy_incidents_no_update")
            conn.execute("DROP TRIGGER IF EXISTS trg_points_economy_incidents_no_delete")
            restore_tables = [
                "points_chain_address_provisional_freezes",
                "points_chain_address_freezes",
                "points_chain_address_risk_labels",
                "points_chain_governance_multisig_signatures",
                "points_chain_governance_votes",
                "points_chain_governance_branches",
                "points_chain_governance_proposals",
                "points_chain_governance_audit_log",
                "points_service_fee_charges",
                "points_chain_transfer_requests",
                "points_economy_derived_balances",
                "points_economy_snapshots",
                "points_economy_incidents",
                "points_economy_events",
                "points_economy_fund_wallets",
                "points_wallet_identities",
            ]
            for table in restore_tables:
                if table_columns(conn, table):
                    conn.execute(f"DELETE FROM {table}")
            conn.execute("DELETE FROM points_chain_block_signatures")
            conn.execute("DELETE FROM points_ledger")
            conn.execute("DELETE FROM points_chain_blocks")
            conn.execute("DELETE FROM points_chain_audit_logs")

            ledger_cols = [row["name"] for row in conn.execute("PRAGMA table_info(points_ledger)").fetchall()]
            block_cols = [row["name"] for row in conn.execute("PRAGMA table_info(points_chain_blocks)").fetchall()]
            sig_cols = [row["name"] for row in conn.execute("PRAGMA table_info(points_chain_block_signatures)").fetchall()]
            audit_cols = [row["name"] for row in conn.execute("PRAGMA table_info(points_chain_audit_logs)").fetchall()]

            def insert_rows(table, cols, rows):
                if not rows:
                    return
                placeholders = ",".join("?" for _ in cols)
                col_sql = ",".join(cols)
                for row in rows:
                    conn.execute(
                        f"INSERT INTO {table} ({col_sql}) VALUES ({placeholders})",
                        tuple(row.get(col) for col in cols),
                    )

            insert_rows("points_chain_blocks", block_cols, payload.get("points_chain_blocks") or [])
            insert_rows("points_ledger", ledger_cols, payload.get("points_ledger") or [])
            insert_rows("points_chain_block_signatures", sig_cols, payload.get("points_chain_block_signatures") or [])
            insert_rows("points_chain_audit_logs", audit_cols, payload.get("points_chain_audit_logs") or [])
            for table in reversed(restore_tables):
                rows = payload.get(table) or []
                if not rows or not table_columns(conn, table):
                    continue
                cols = [row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
                insert_rows(table, cols, rows)
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
            self.ensure_schema(conn)
            rebuild = self._rebuild_wallets_from_ledger(conn)
            post = self._verify_chain_on_conn(conn, mark_safe_mode=False)
            if not post["ok"]:
                raise ValueError("restored chain verification failed")
            branch_rows = conn.execute(
                "SELECT branch_uuid, is_canonical, write_enabled FROM points_chain_governance_branches WHERE is_canonical=1 AND write_enabled=1"
            ).fetchall()
            ledger_branch_rows = conn.execute(
                "SELECT DISTINCT chain_branch FROM points_ledger"
            ).fetchall()
            ledger_branches = {str(row["chain_branch"] or "main") for row in ledger_branch_rows}
            if any(branch != "main" for branch in ledger_branches) and len(branch_rows) != 1:
                self._enter_safe_mode(
                    conn,
                    {
                        "ok": False,
                        "errors": [{
                            "type": "restore_branch_pointer_inconsistent",
                            "severity": "critical",
                            "message": "restored ledger has non-main branch rows but canonical branch pointer is missing or ambiguous",
                            "ledger_branches": sorted(ledger_branches),
                            "canonical_branch_count": len(branch_rows),
                        }],
                    },
                    "restore_branch_pointer_inconsistent",
                )
                conn.commit()
                raise ValueError("restored branch pointer is inconsistent")
            gov_audit = self._governance_audit_verify_locked(conn)
            if not gov_audit.get("ok"):
                self._enter_safe_mode(conn, gov_audit, "restore_governance_audit_inconsistent")
                conn.commit()
                raise ValueError("restored governance audit verification failed")
            now = utc_now()
            recovery_summary = {
                "restored": True,
                "restored_at": now,
                "backup_id": backup_id,
                "pre_restore_backup_id": abnormal.get("backup_id"),
                "wallet_rebuild": rebuild,
                "verification_ok": bool(post.get("ok")),
                "verification_counts": post.get("counts", {}),
            }
            conn.execute(
                """
                UPDATE points_chain_recovery_state
                SET safe_mode=0, restored_at=?, updated_at=?, restore_plan_json=?
                WHERE id=1
                """,
                (now, now, _json_dumps({**state.get("restore_plan", {}), **recovery_summary})),
            )
            self._audit_log(
                conn,
                "POINTS_CHAIN_RECOVERY_APPLIED",
                "critical",
                f"PointsChain restored from backup {backup_id}",
                actor=actor,
                metadata={
                    "backup_id": backup_id,
                    "pre_restore_backup_id": abnormal.get("backup_id"),
                    "wallet_rebuild": rebuild,
                    "verification": post,
                },
            )
            conn.commit()
            return {
                "ok": True,
                "msg": "PointsChain 已還原並驗證完成",
                "backup_id": backup_id,
                "pre_restore_backup_id": abnormal.get("backup_id"),
                "wallet_rebuild": rebuild,
                "verification": post,
                "recovery": self._safe_mode_status(conn),
            }
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _ensure_local_node(self, conn):
        now = utc_now()
        fingerprint = self._node_fingerprint()
        conn.execute(
            """
            INSERT OR IGNORE INTO points_chain_nodes (
                node_id, node_name, node_type, public_key, public_key_fingerprint,
                enabled, created_at, updated_at
            ) VALUES ('single-node', 'Local PointsChain node', 'local_hmac', ?, ?, 1, ?, ?)
            """,
            (fingerprint, fingerprint, now, now),
        )

    def _backfill_missing_block_signatures(self, conn):
        self._ensure_local_node(conn)
        now = utc_now()
        blocks = conn.execute(
            """
            SELECT b.*
            FROM points_chain_blocks b
            LEFT JOIN points_chain_block_signatures s ON s.block_id=b.id AND s.node_id='single-node'
            WHERE s.id IS NULL
            ORDER BY b.block_number ASC
            """
        ).fetchall()
        for block in blocks:
            if compute_block_hash(block) != block["block_hash"]:
                continue
            conn.execute(
                """
                INSERT INTO points_chain_block_signatures (
                    block_id, node_id, signature_algorithm, public_key_fingerprint, signature, signed_at
                ) VALUES (?, 'single-node', 'hmac-sha256', ?, ?, ?)
                """,
                (block["id"], self._node_fingerprint(), self._sign_block(block), now),
            )

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
                int(actor_value(actor, "id")) if actor_value(actor, "id") else None,
                actor_value(actor, "role"),
                target_user_id,
                ledger_id,
                block_id,
                message,
                _json_dumps(metadata or {}),
                utc_now(),
            ),
        )

    def reset_runtime_chain(self, *, actor=None, reason="", pre_reset_snapshot_id=""):
        """Reset the live PointsChain runtime state after a full server reset.

        The pre-reset server snapshot remains the recovery source. The active
        ledger, blocks, wallets, pending rewards, disputes, recovery state, and
        daily stats are cleared so the next startup can bootstrap a fresh
        genesis allocation. A PointsChain audit entry is left as the first event
        in the new chain audit log.
        """
        conn = self.get_db()
        reset_tables = [
            "points_chain_block_signatures",
            "points_chain_blocks",
            "points_chain_governance_audit_log",
            "points_chain_governance_votes",
            "points_chain_address_risk_labels",
            "points_chain_address_freezes",
            "points_chain_address_provisional_freezes",
            "points_chain_governance_branches",
            "points_chain_governance_proposals",
            "points_disputes",
            "points_ledger",
            "points_wallets",
            "points_pending_rewards",
            "points_economy_daily_stats",
            "points_chain_recovery_state",
            "points_chain_backup_catalog",
            "points_chain_audit_logs",
        ]
        backup_files = {"removed": [], "skipped": []}
        try:
            self.ensure_schema(conn)
            before = self._chain_head_summary(conn)
            conn.commit()
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("DROP TRIGGER IF EXISTS trg_points_ledger_no_delete")
            conn.execute("DROP TRIGGER IF EXISTS trg_points_ledger_core_immutable")
            conn.execute("DROP TRIGGER IF EXISTS trg_points_chain_blocks_no_update")
            conn.execute("DROP TRIGGER IF EXISTS trg_points_chain_blocks_no_delete")
            conn.execute("DROP TRIGGER IF EXISTS trg_points_chain_block_signatures_no_update")
            conn.execute("DROP TRIGGER IF EXISTS trg_points_chain_block_signatures_no_delete")
            conn.execute("DROP TRIGGER IF EXISTS trg_points_chain_governance_audit_no_update")
            conn.execute("DROP TRIGGER IF EXISTS trg_points_chain_governance_audit_no_delete")
            for table in reset_tables:
                conn.execute(f"DELETE FROM {table}")
            try:
                placeholders = ",".join("?" for _ in reset_tables)
                conn.execute(f"DELETE FROM sqlite_sequence WHERE name IN ({placeholders})", reset_tables)
            except Exception:
                pass
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
            self._audit_log(
                conn,
                "POINTS_CHAIN_RESET",
                "warning",
                "PointsChain reset during server runtime reset",
                actor=actor,
                metadata={
                    "reason": reason or "",
                    "pre_reset_snapshot_id": pre_reset_snapshot_id or "",
                    "before": before,
                    "reset_tables": reset_tables,
                },
            )
            backup_root = self.backup_dir.expanduser()
            backup_path = backup_root / "backups"
            if str(backup_path) not in {"", "/"} and backup_path.exists():
                try:
                    shutil.rmtree(backup_path)
                    backup_files["removed"].append(str(backup_path))
                except Exception as exc:
                    backup_files["skipped"].append({"path": str(backup_path), "reason": str(exc)})
            self._backup_root()
            conn.commit()
            return {
                "ok": True,
                "reset": True,
                "before": before,
                "cleared_tables": reset_tables,
                "backup_files": backup_files,
            }
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _public_chain_audit_metadata(self, value):
        if isinstance(value, dict):
            sanitized = {}
            for key, item in value.items():
                if key == "user_id":
                    try:
                        sanitized["public_account_id"] = self._public_account_id(int(item))
                    except Exception:
                        sanitized["public_account_id"] = ""
                    continue
                if key in {"actor_username", "target_username", "username"}:
                    continue
                sanitized[key] = self._public_chain_audit_metadata(item)
            return sanitized
        if isinstance(value, list):
            return [self._public_chain_audit_metadata(item) for item in value]
        return value

    def list_chain_audit_logs(self, *, limit=100):
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            rows = conn.execute(
                """
                SELECT * FROM points_chain_audit_logs
                ORDER BY id DESC LIMIT ?
                """,
                (min(200, max(1, int(limit or 100))),),
            ).fetchall()
            logs = []
            for row in rows:
                item = {key: row[key] for key in row.keys() if key != "metadata_json"}
                item["message"] = public_currency_text(item.get("message") or "")
                item["metadata"] = public_currency_payload(
                    self._public_chain_audit_metadata(_json_loads(row["metadata_json"], {}))
                )
                logs.append(item)
            return logs
        finally:
            conn.close()

    def _governance_mode(self):
        try:
            return self._mode_reader() if callable(self._mode_reader) else ""
        except Exception:
            return ""

    def _governance_is_production(self):
        return self._governance_mode() == "production"

    def _governance_actor_role(self, actor):
        username = str(actor_value(actor, "username") or "")
        role = str(actor_value(actor, "role") or "user")
        if username == "root":
            return "super_admin"
        return role

    def _governance_role_rank(self, role):
        return {"user": 0, "manager": 1, "super_admin": 2}.get(str(role or "user"), 0)

    def _governance_is_manager_actor(self, actor):
        return self._governance_role_rank(self._governance_actor_role(actor)) >= self._governance_role_rank("manager")

    def _governance_member_level_rank(self, level):
        return {
            "suspended": -2,
            "restricted": -1,
            "newbie": 0,
            "normal": 1,
            "trusted": 2,
            "vip": 3,
        }.get(str(level or "normal").strip().lower(), 1)

    def _governance_actor_effective_level(self, conn, actor):
        for key in ("effective_level", "member_level", "base_level"):
            value = str(actor_value(actor, key) or "").strip().lower()
            if value:
                return value
        user_id = int(actor_value(actor, "id") or 0)
        if user_id <= 0:
            return "normal"
        try:
            user_cols = table_columns(conn, "users")
            available = [key for key in ("effective_level", "member_level", "base_level") if key in user_cols]
            if not available:
                return "normal"
            row = conn.execute(
                f"SELECT {', '.join(available)} FROM users WHERE id=?",
                (user_id,),
            ).fetchone()
            if not row:
                return "normal"
            for key in available:
                value = str(row[key] or "").strip().lower()
                if value:
                    return value
        except Exception:
            return "normal"
        return "normal"

    def _governance_public_proposer_allowed(self, conn, actor):
        return self._governance_member_level_rank(self._governance_actor_effective_level(conn, actor)) >= self._governance_member_level_rank("trusted")

    def _governance_domain_for_action(self, action_type, default="PUBLIC_COMMON_INTEREST"):
        action_type = str(action_type or "").strip().upper()
        if action_type in {"MINT_REQUEST", "TREASURY_TRANSFER", "EXCHANGE_FUND_REPLENISH", "CONTEST_REWARD_PAYOUT", "TREASURY_SIGNER_CHANGE"}:
            return "OFFICIAL_TREASURY"
        if action_type in {"EMERGENCY_LOCKDOWN", "ROLLBACK_BRANCH"}:
            return "EMERGENCY_SECURITY"
        if action_type in {"PARAMETER_CHANGE", "FEATURE_ACTIVATION", "HARD_FORK_ACCEPTANCE"}:
            return "PROTOCOL_PARAMETER"
        return str(default or "PUBLIC_COMMON_INTEREST").strip().upper()

    def _governance_legacy_type_for_action(self, action_type, conn=None):
        action_type = str(action_type or "").strip().upper()
        if action_type == "MARK_SCAM":
            proposal_type = "scam_address_label"
        elif action_type == "FREEZE_ADDRESS":
            proposal_type = "freeze_wallet_address"
        elif action_type == "UNFREEZE_ADDRESS":
            proposal_type = "unfreeze_wallet_address"
        elif action_type == "ROLLBACK_BRANCH":
            proposal_type = "emergency_recovery_branch"
        elif action_type in {"MINT_REQUEST", "TREASURY_TRANSFER", "EXCHANGE_FUND_REPLENISH", "CONTEST_REWARD_PAYOUT", "TREASURY_SIGNER_CHANGE"}:
            proposal_type = "official_treasury_operation"
        elif action_type == "EMERGENCY_LOCKDOWN":
            proposal_type = "emergency_security_action"
        elif action_type in {"PARAMETER_CHANGE", "FEATURE_ACTIVATION", "HARD_FORK_ACCEPTANCE", "AUTO_BURN_POLICY"}:
            proposal_type = "protocol_parameter_change"
        else:
            proposal_type = "admin_policy_action"
        if conn is not None:
            try:
                sql = conn.execute(
                    "SELECT sql FROM sqlite_master WHERE type='table' AND name='points_chain_governance_proposals'"
                ).fetchone()
                ddl = str(sql["sql"] if hasattr(sql, "keys") else sql[0]) if sql else ""
                if proposal_type not in ddl and "emergency_recovery_branch" in ddl:
                    return "emergency_recovery_branch"
            except Exception:
                pass
        return proposal_type

    def _governance_policy(self, proposal_type=None, *, governance_domain=None, action_type=None):
        action_type = str(action_type or "").strip().upper()
        domain = str(governance_domain or self._governance_domain_for_action(action_type)).strip().upper()
        if domain == "OFFICIAL_TREASURY":
            return {
                "domain": "OFFICIAL_TREASURY",
                "voter_scope": "manager_plus",
                "root_veto_allowed": True,
                GOV_QUORUM_RATE_FIELD: 6000,
                "minimum_quorum": 2,
                GOV_PASS_THRESHOLD_RATE_FIELD: 6000,
                GOV_VOTE_DIFFERENTIAL_REQUIRED_RATE_FIELD: 1,
                "timelock_seconds": 12 * 60 * 60 if self._governance_is_production() else 0,
                "expires_seconds": 7 * 24 * 60 * 60,
            }
        if domain == "EMERGENCY_SECURITY":
            return {
                "domain": "EMERGENCY_SECURITY",
                "voter_scope": "manager_plus",
                "root_veto_allowed": False,
                GOV_QUORUM_RATE_FIELD: 5000,
                "minimum_quorum": 2,
                GOV_PASS_THRESHOLD_RATE_FIELD: 8000,
                GOV_VOTE_DIFFERENTIAL_REQUIRED_RATE_FIELD: 1,
                "timelock_seconds": 0,
                "expires_seconds": 24 * 60 * 60,
            }
        if action_type in {"MARK_SCAM", "FREEZE_ADDRESS", "UNFREEZE_ADDRESS", "AUTO_BURN_POLICY"} or domain == "PUBLIC_COMMON_INTEREST":
            return {
                "domain": "PUBLIC_COMMON_INTEREST",
                "voter_scope": "active_users",
                "root_veto_allowed": False,
                GOV_QUORUM_RATE_FIELD: 3000,
                "minimum_quorum": 5,
                GOV_PASS_THRESHOLD_RATE_FIELD: 6667,
                GOV_VOTE_DIFFERENTIAL_REQUIRED_RATE_FIELD: 1000,
                "timelock_seconds": 24 * 60 * 60 if self._governance_is_production() else 0,
                "expires_seconds": 7 * 24 * 60 * 60,
            }
        if domain == "PROTOCOL_PARAMETER":
            return {
                "domain": "PROTOCOL_PARAMETER",
                "voter_scope": "active_users",
                "root_veto_allowed": False,
                GOV_QUORUM_RATE_FIELD: 3000,
                "minimum_quorum": 5,
                GOV_PASS_THRESHOLD_RATE_FIELD: 6667,
                GOV_VOTE_DIFFERENTIAL_REQUIRED_RATE_FIELD: 1000,
                "timelock_seconds": 48 * 60 * 60 if self._governance_is_production() else 0,
                "expires_seconds": 10 * 24 * 60 * 60,
            }
        if domain == "ADMIN_POLICY":
            return {
                "domain": "ADMIN_POLICY",
                "voter_scope": "manager_plus",
                "root_veto_allowed": True,
                GOV_QUORUM_RATE_FIELD: 6000,
                "minimum_quorum": 2,
                GOV_PASS_THRESHOLD_RATE_FIELD: 6000,
                GOV_VOTE_DIFFERENTIAL_REQUIRED_RATE_FIELD: 1,
                "timelock_seconds": 12 * 60 * 60 if self._governance_is_production() else 0,
                "expires_seconds": 7 * 24 * 60 * 60,
            }
        raise ValueError("unsupported governance proposal type")

    def _governance_severity_policy(self, severity):
        severity = str(severity or "NORMAL").strip().upper()
        if severity not in {"LOW", "NORMAL", "HIGH", "CRITICAL"}:
            raise ValueError("unsupported proposal severity")
        return {
            "LOW": {GOV_QUORUM_DELTA_RATE_FIELD: -500, "timelock_multiplier": 1, "deposit_points": 50},
            "NORMAL": {GOV_QUORUM_DELTA_RATE_FIELD: 0, "timelock_multiplier": 1, "deposit_points": 100},
            "HIGH": {GOV_QUORUM_DELTA_RATE_FIELD: 1000, "timelock_multiplier": 2, "deposit_points": 250},
            "CRITICAL": {GOV_QUORUM_DELTA_RATE_FIELD: 2000, "timelock_multiplier": 1, "deposit_points": 500},
        }[severity]

    def _active_governance_voter_ids(self, conn, *, voter_scope="active_users"):
        user_cols = table_columns(conn, "users")
        where = []
        if "status" in user_cols:
            where.append("COALESCE(status, 'active')='active'")
        if "deleted_at" in user_cols:
            where.append("deleted_at IS NULL")
        if str(voter_scope or "") == "manager_plus":
            if "username" in user_cols and "role" in user_cols:
                where.append("(username='root' OR role IN ('manager', 'super_admin'))")
            elif "role" in user_cols:
                where.append("role IN ('manager', 'super_admin')")
        sql = "SELECT id FROM users"
        if where:
            sql += " WHERE " + " AND ".join(where)
        return sorted(int(row["id"]) for row in conn.execute(sql).fetchall())

    def _governance_quorum_count(self, eligible_count, policy):
        eligible_count = max(0, int(eligible_count or 0))
        if eligible_count <= 0:
            return 1
        quorum = (eligible_count * int(policy[GOV_QUORUM_RATE_FIELD]) + 9999) // 10000
        minimum = int(policy["minimum_quorum"])
        if eligible_count >= minimum:
            quorum = max(quorum, minimum)
        else:
            quorum = eligible_count
        if eligible_count >= 2:
            quorum = max(2, quorum)
        return max(1, min(eligible_count, quorum))

    def _governance_time_after(self, seconds):
        return datetime.fromtimestamp(time.time() + int(seconds or 0), timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    def _governance_evidence(self, evidence):
        if evidence is None:
            return []
        if isinstance(evidence, str):
            evidence = [evidence]
        if not isinstance(evidence, list):
            raise ValueError("evidence must be a list")
        items = []
        for item in evidence[:20]:
            value = str(item or "").strip()
            if value:
                items.append(value[:240])
        return items

    def _governance_require_root(self, actor):
        if actor_value(actor, "username") != "root":
            raise PermissionError("只有 root 可以建立或執行 PointsChain governance proposal")

    def _governance_require_proposer(self, actor, governance_domain):
        if not actor_value(actor, "id"):
            raise PermissionError("login required")
        domain = str(governance_domain or "").strip().upper()
        if domain in {"OFFICIAL_TREASURY", "EMERGENCY_SECURITY", "ADMIN_POLICY"} and not self._governance_is_manager_actor(actor):
            raise PermissionError("manager+ required for this governance proposal")
        if domain == "PROTOCOL_PARAMETER" and not self._governance_is_manager_actor(actor):
            raise PermissionError("manager+ required for protocol governance proposal")

    def _governance_proposer_authority(self, conn, *, actor, governance_domain, action_type, severity, target_address=""):
        user_id = int(actor_value(actor, "id") or 0)
        if user_id <= 0:
            raise PermissionError("login required")
        domain = str(governance_domain or "").strip().upper()
        is_manager = self._governance_is_manager_actor(actor)
        if domain in {"OFFICIAL_TREASURY", "EMERGENCY_SECURITY", "ADMIN_POLICY"}:
            if not is_manager:
                raise PermissionError("manager+ required for this governance proposal")
            return {"sponsor_required": False, "deposit_points": 0, "deposit_status": "not_required", "authority": "manager_plus"}
        if domain == "PROTOCOL_PARAMETER":
            if is_manager:
                return {"sponsor_required": False, "deposit_points": 0, "deposit_status": "not_required", "authority": "manager_plus"}
            raise PermissionError("manager+ required for protocol governance proposal in RC1")
        # PUBLIC_COMMON_INTEREST: manager+ can directly propose. Normal users
        # can file a proposal, but it stays in REVIEW until manager+ sponsors it.
        if is_manager:
            return {"sponsor_required": False, "deposit_points": 0, "deposit_status": "not_required", "authority": "manager_plus_public"}
        if not self._governance_public_proposer_allowed(conn, actor):
            raise PermissionError("trusted member level or manager+ required for public governance proposal")
        recent = conn.execute(
            """
            SELECT COUNT(*) AS c
            FROM points_chain_governance_proposals
            WHERE proposer_user_id=? AND created_at>=?
            """,
            (
                user_id,
                datetime.fromtimestamp(time.time() - 24 * 60 * 60, timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            ),
        ).fetchone()
        if int(recent["c"] or 0) >= 3:
            raise ValueError("proposal rate limit exceeded: maximum 3 public proposals per 24h")
        duplicate = conn.execute(
            """
            SELECT proposal_uuid FROM points_chain_governance_proposals
            WHERE governance_domain=? AND action_type=? AND target_address=?
              AND lifecycle_status IN ('REVIEW', 'VOTING', 'SUCCEEDED', 'QUEUED', 'TIMELOCKED')
            ORDER BY id DESC LIMIT 1
            """,
            (domain, str(action_type or "").strip().upper(), str(target_address or "")),
        ).fetchone()
        if duplicate:
            raise ValueError("similar active proposal already exists")
        severity_policy = self._governance_severity_policy(severity)
        return {
            "sponsor_required": True,
            "deposit_points": int(severity_policy["deposit_points"]),
            "deposit_status": "not_required",
            "authority": "public_review_requires_sponsor",
        }

    def _governance_require_executor(self, actor):
        if not self._governance_is_manager_actor(actor):
            raise PermissionError("manager+ required to execute PointsChain governance proposal")

    def _governance_begin_immediate(self, conn):
        if conn.in_transaction:
            conn.commit()
        conn.execute("BEGIN IMMEDIATE")

    def _governance_execution_payload_hash(self, *, action_type, governance_domain, target_wallet_address="", target_address="", target_branch="", requested_amount=0, requested_asset="points", payload=None):
        return sha256_text(canonical_json({
            "action_type": str(action_type or "").strip().upper(),
            "governance_domain": str(governance_domain or "").strip().upper(),
            "target_wallet_address": str(target_wallet_address or "").strip().lower(),
            "target_address": str(target_address or "").strip().lower(),
            "target_branch": str(target_branch or "").strip(),
            "requested_amount": int(requested_amount or 0),
            "requested_asset": str(requested_asset or "points").strip().lower(),
            "payload": payload or {},
        }))

    def _governance_multisig_signing_payload(self, row):
        return {
            "action": "points_governance_multisig_sign",
            "proposal_uuid": row["proposal_uuid"],
            "governance_domain": row["governance_domain"],
            "action_type": row["action_type"],
            "target_wallet_address": row["target_wallet_address"],
            "requested_amount": int(row["requested_amount"] or 0),
            "requested_asset": row["requested_asset"],
            "execution_payload_hash": row["execution_payload_hash"],
        }

    def _governance_multisig_policy_locked(self, conn, *, fund_key="official_treasury"):
        rows = conn.execute(
            """
            SELECT u.id AS user_id, u.username, u.role, w.address, w.wallet_type, w.custody_mode,
                   w.public_key_hash, w.metadata_json, w.created_at
            FROM users u
            JOIN points_wallet_identities w ON w.user_id=u.id
            WHERE COALESCE(u.status, 'active')='active'
              AND (u.username='root' OR u.role IN ('manager', 'super_admin'))
              AND w.status IN ('pending_backup', 'active')
            ORDER BY CASE WHEN u.username='root' THEN 0 WHEN u.role='super_admin' THEN 1 WHEN u.role='manager' THEN 2 ELSE 3 END,
                     u.id ASC, w.is_primary DESC, w.id ASC
            """
        ).fetchall()
        seen_users = set()
        signers = []
        for row in rows:
            user_id = int(row["user_id"])
            if user_id in seen_users:
                continue
            seen_users.add(user_id)
            role = "super_admin" if row["username"] == "root" else row["role"]
            signer_weight = 3 if row["username"] == "root" else (2 if role == "super_admin" else 1)
            metadata = _json_loads(row["metadata_json"], {})
            device_id = str(metadata.get("device_id") or metadata.get("signer_device_id") or "").strip()
            if not device_id:
                device_id = "wallet:" + sha256_text(f"{user_id}:{row['address']}")[:16]
            signers.append({
                "user_id": user_id,
                "username": row["username"],
                "role": role,
                "signer_id": "treasury-signer:" + sha256_text(f"{user_id}:{row['address']}")[:20],
                "wallet_address": row["address"],
                "wallet_type": row["wallet_type"],
                "custody_mode": row["custody_mode"],
                "weight": signer_weight,
                "device_id": device_id,
                "pubkey_fingerprint": str(row["public_key_hash"] or "")[:24],
                "signer_created_at": row["created_at"],
                "last_used_at": str(metadata.get("last_signer_used_at") or ""),
                "revoked": False,
            })
        if len(signers) < 2:
            raise ValueError("official treasury multisig requires at least two manager+ signer wallets")
        total_weight = sum(int(item.get("weight") or 0) for item in signers)
        threshold = max(2, (len(signers) * 60 + 99) // 100)
        threshold = min(len(signers), threshold)
        threshold_weight = max(1, (total_weight * 60 + 99) // 100)
        return {
            "policy_version": "OFFICIAL_TREASURY_MULTISIG_V1",
            "fund_key": str(fund_key or "official_treasury"),
            "wallet_type": "official_treasury_multisig",
            "wallet_scope": "official_treasury",
            "custody_mode": "multisig",
            "spend_capability": "enabled",
            "threshold": threshold,
            "threshold_weight": threshold_weight,
            "signer_count": len(signers),
            "total_weight": total_weight,
            "signers": signers,
            "signer_user_ids": [item["user_id"] for item in signers],
            "signer_addresses": [item["wallet_address"] for item in signers],
            "signature_required_after_governance": True,
            "server_hot_attestation_allowed": True,
            "signer_identity_model": "manager_identity_distinct_from_treasury_signer_wallet_v1",
            "signer_weight_model": "weighted_threshold_v1",
            "device_binding_model": "device_id_and_pubkey_fingerprint_snapshot_v1",
        }

    def _governance_execution_payload_hash_for_row(self, row):
        return self._governance_execution_payload_hash(
            action_type=row["action_type"],
            governance_domain=row["governance_domain"],
            target_wallet_address=row["target_wallet_address"],
            target_address=row["target_address"],
            target_branch=row["target_branch"],
            requested_amount=row["requested_amount"],
            requested_asset=row["requested_asset"],
            payload=_json_loads(row["payload_json"], {}),
        )

    def _last_governance_audit_hash(self, conn):
        row = conn.execute("SELECT audit_hash FROM points_chain_governance_audit_log ORDER BY id DESC LIMIT 1").fetchone()
        return row["audit_hash"] if row else ""

    def _append_governance_audit_locked(self, conn, *, proposal_uuid, event_type, actor=None, metadata=None, payload_hash=""):
        now = utc_now()
        prev_hash = self._last_governance_audit_hash(conn)
        audit_uuid = f"pcgovaudit:{uuid.uuid4()}"
        row_payload = {
            "audit_uuid": audit_uuid,
            "proposal_uuid": str(proposal_uuid or ""),
            "event_type": str(event_type or ""),
            "actor_user_id": int(actor_value(actor, "id") or 0) or None,
            "actor_role": self._governance_actor_role(actor) if actor else "",
            "payload_hash": str(payload_hash or ""),
            "metadata": metadata or {},
            "prev_audit_hash": prev_hash,
            "created_at": now,
        }
        audit_hash = sha256_text(canonical_json(row_payload))
        conn.execute(
            """
            INSERT INTO points_chain_governance_audit_log (
                audit_uuid, proposal_uuid, event_type, actor_user_id, actor_role,
                payload_hash, metadata_json, prev_audit_hash, audit_hash, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                audit_uuid,
                row_payload["proposal_uuid"],
                row_payload["event_type"],
                row_payload["actor_user_id"],
                row_payload["actor_role"],
                row_payload["payload_hash"],
                _json_dumps(metadata or {}),
                prev_hash,
                audit_hash,
                now,
            ),
        )
        return {"audit_uuid": audit_uuid, "audit_hash": audit_hash, "prev_audit_hash": prev_hash, "created_at": now}

    def _create_governance_proposal_locked(
        self,
        conn,
        *,
        actor,
        proposal_type,
        governance_domain=None,
        action_type=None,
        title,
        reason,
        description="",
        reference="",
        target_wallet_address="",
        target_address="",
        target_branch="",
        requested_amount=0,
        requested_asset="points",
        incident_tx_hash="",
        base_block_number=None,
        base_block_hash="",
        payload=None,
        evidence=None,
        impact_scope="",
        risk_summary="",
        opposition_record="",
        proposal_severity="NORMAL",
    ):
        action_type = str(action_type or "").strip().upper() or {
            "scam_address_label": "MARK_SCAM",
            "freeze_wallet_address": "FREEZE_ADDRESS",
            "unfreeze_wallet_address": "UNFREEZE_ADDRESS",
            "emergency_recovery_branch": "ROLLBACK_BRANCH",
        }.get(str(proposal_type or ""), "MARK_SCAM")
        if action_type not in GOVERNANCE_ACTION_TYPES:
            raise ValueError("unsupported governance action type")
        governance_domain = self._governance_domain_for_action(action_type, governance_domain or "PUBLIC_COMMON_INTEREST")
        if governance_domain not in GOVERNANCE_DOMAINS:
            raise ValueError("unsupported governance domain")
        self._governance_require_proposer(actor, governance_domain)
        proposal_type = self._governance_legacy_type_for_action(action_type, conn=conn)
        title = str(title or "").strip()[:160]
        description = str(description or "").strip()[:4000]
        reason = str(reason or "").strip()
        reference = str(reference or "").strip()[:240]
        if not title:
            raise ValueError("proposal title required")
        if len(reason) < 8:
            raise ValueError("proposal reason must be at least 8 characters")
        target_wallet_address = str(target_wallet_address or target_address or "").strip().lower()
        target_address = str(target_address or target_wallet_address or "").strip().lower()
        if target_wallet_address:
            if not WALLET_ADDRESS_RE.fullmatch(target_wallet_address):
                raise ValueError("wallet address format is invalid")
        if target_address and target_address.startswith("pc1") and not WALLET_ADDRESS_RE.fullmatch(target_address):
            raise ValueError("target address format is invalid")
        target_branch = str(target_branch or "").strip()[:160]
        requested_amount = int(requested_amount or 0)
        if requested_amount < 0:
            raise ValueError("requested_amount must be >= 0")
        requested_asset = public_currency_text(str(requested_asset or "points").strip().lower())[:40] or "points"
        if incident_tx_hash:
            incident_tx_hash = str(incident_tx_hash).strip()
        payload = payload or {}
        proposal_severity = str(proposal_severity or "NORMAL").strip().upper()
        severity_policy = self._governance_severity_policy(proposal_severity)
        authority = self._governance_proposer_authority(
            conn,
            actor=actor,
            governance_domain=governance_domain,
            action_type=action_type,
            severity=proposal_severity,
            target_address=target_address,
        )
        execution_payload_hash = self._governance_execution_payload_hash(
            action_type=action_type,
            governance_domain=governance_domain,
            target_wallet_address=target_wallet_address,
            target_address=target_address,
            target_branch=target_branch,
            requested_amount=requested_amount,
            requested_asset=requested_asset,
            payload=payload,
        )
        policy = self._governance_policy(proposal_type, governance_domain=governance_domain, action_type=action_type)
        policy = {
            **policy,
            GOV_QUORUM_RATE_FIELD: max(1, int(policy[GOV_QUORUM_RATE_FIELD]) + int(severity_policy[GOV_QUORUM_DELTA_RATE_FIELD])),
            "timelock_seconds": int(policy["timelock_seconds"]) * int(severity_policy["timelock_multiplier"]),
        }
        eligible_voters = self._active_governance_voter_ids(conn, voter_scope=policy["voter_scope"])
        eligible_count = len(eligible_voters)
        if eligible_count < 2:
            raise ValueError("governance proposal requires at least 2 eligible voters")
        quorum_count = self._governance_quorum_count(eligible_count, policy)
        now = utc_now()
        proposal_uuid = f"pcgov:{uuid.uuid4()}"
        timelock_until = self._governance_time_after(policy["timelock_seconds"])
        expires_at = self._governance_time_after(policy["expires_seconds"])
        lifecycle_status = "REVIEW" if authority["sponsor_required"] else "VOTING"
        status = "voting"
        audit = self._append_governance_audit_locked(
            conn,
            proposal_uuid=proposal_uuid,
            event_type="PROPOSAL_CREATED",
            actor=actor,
            payload_hash=execution_payload_hash,
            metadata={
                "governance_domain": governance_domain,
                "action_type": action_type,
                "target_wallet_address": target_wallet_address,
                "requested_amount": requested_amount,
                "requested_asset": requested_asset,
                "quorum_count": quorum_count,
                "eligible_voter_count": eligible_count,
                "proposal_severity": proposal_severity,
                "sponsor_required": authority["sponsor_required"],
                "proposal_authority": authority["authority"],
            },
        )
        conn.execute(
            f"""
            INSERT INTO points_chain_governance_proposals (
                proposal_uuid, proposal_type, governance_domain, action_type, lifecycle_status,
                proposal_severity, sponsor_required, proposal_deposit_points,
                proposal_deposit_status, title, description, reason, reference, target_wallet_address, target_address,
                target_branch, requested_amount, requested_asset, incident_tx_hash,
                base_block_number, base_block_hash, payload_json, evidence_json,
                impact_scope, risk_summary, opposition_record, eligible_voters_json,
                eligible_voter_count, quorum_count, {GOV_QUORUM_RATE_FIELD}, {GOV_PASS_THRESHOLD_RATE_FIELD},
                {GOV_YES_THRESHOLD_RATE_FIELD}, {GOV_VOTE_DIFFERENTIAL_REQUIRED_RATE_FIELD}, status,
                voting_starts_at, voting_ends_at, timelock_until, timelock_ends_at,
                expires_at, root_veto_allowed, execution_payload_hash,
                proposer_user_id, proposer_role, prev_audit_hash, audit_hash,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                proposal_uuid,
                proposal_type,
                governance_domain,
                action_type,
                lifecycle_status,
                proposal_severity,
                1 if authority["sponsor_required"] else 0,
                int(authority["deposit_points"]),
                authority["deposit_status"],
                title,
                description,
                reason[:2000],
                reference,
                target_wallet_address,
                target_address,
                target_branch,
                requested_amount,
                requested_asset,
                incident_tx_hash,
                int(base_block_number) if base_block_number not in (None, "") else None,
                str(base_block_hash or "").strip()[:128],
                _json_dumps(payload),
                _json_dumps(self._governance_evidence(evidence)),
                str(impact_scope or "").strip()[:1000],
                str(risk_summary or "").strip()[:1000],
                str(opposition_record or "").strip()[:2000],
                _json_dumps(eligible_voters),
                eligible_count,
                quorum_count,
                int(policy[GOV_QUORUM_RATE_FIELD]),
                int(policy[GOV_PASS_THRESHOLD_RATE_FIELD]),
                int(policy[GOV_PASS_THRESHOLD_RATE_FIELD]),
                int(policy[GOV_VOTE_DIFFERENTIAL_REQUIRED_RATE_FIELD]),
                status,
                now,
                expires_at,
                timelock_until,
                timelock_until,
                expires_at,
                1 if policy["root_veto_allowed"] else 0,
                execution_payload_hash,
                int(actor_value(actor, "id")) if actor_value(actor, "id") else None,
                self._governance_actor_role(actor),
                audit["prev_audit_hash"],
                audit["audit_hash"],
                now,
                now,
            ),
        )
        self._audit_log(
            conn,
            "POINTS_CHAIN_GOVERNANCE_PROPOSAL_CREATED",
            "warning" if proposal_type == "emergency_recovery_branch" else "info",
            f"PointsChain governance proposal created: {proposal_type}",
            actor=actor,
            metadata={
                "proposal_uuid": proposal_uuid,
                "proposal_type": proposal_type,
                "target_wallet_address": target_wallet_address,
                "incident_tx_hash": incident_tx_hash,
                "eligible_voter_count": eligible_count,
                "quorum_count": quorum_count,
                "mode": self._governance_mode(),
            },
        )
        return self._serialize_governance_proposal(conn, conn.execute(
            "SELECT * FROM points_chain_governance_proposals WHERE proposal_uuid=?",
            (proposal_uuid,),
        ).fetchone(), actor=actor)

    def create_address_risk_proposal(self, *, actor, wallet_address, reason, evidence=None, reference=""):
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            self._governance_begin_immediate(conn)
            proposal = self._create_governance_proposal_locked(
                conn,
                actor=actor,
                proposal_type="scam_address_label",
                governance_domain="PUBLIC_COMMON_INTEREST",
                action_type="MARK_SCAM",
                title="標記疑似詐騙地址",
                description="公開標記高風險或詐騙地址；root 沒有 veto，需全站投票通過。",
                reason=reason,
                reference=reference,
                target_wallet_address=wallet_address,
                target_address=wallet_address,
                evidence=evidence,
                payload={"risk_level": "confirmed_scam", "label": "governance_confirmed_scam"},
                impact_scope="public explorer warning and wallet risk label",
                risk_summary="False positives can damage legitimate wallet reputation; evidence refs are required.",
            )
            conn.commit()
            return {"ok": True, "proposal": proposal}
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def create_wallet_freeze_proposal(self, *, actor, wallet_address, reason, evidence=None, reference="", release=False):
        proposal_type = "unfreeze_wallet_address" if release else "freeze_wallet_address"
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            self._governance_begin_immediate(conn)
            proposal = self._create_governance_proposal_locked(
                conn,
                actor=actor,
                proposal_type=proposal_type,
                governance_domain="PUBLIC_COMMON_INTEREST",
                action_type="UNFREEZE_ADDRESS" if release else "FREEZE_ADDRESS",
                title="解除治理凍結地址" if release else "治理凍結地址",
                description="公開決定是否限制地址轉出；不改寫 ledger，不沒收餘額。",
                reason=reason,
                reference=reference,
                target_wallet_address=wallet_address,
                target_address=wallet_address,
                evidence=evidence,
                payload={
                    "freeze_model": "block_outgoing_transfers_only",
                    "ledger_mutation": "forbidden",
                    "release": bool(release),
                },
                impact_scope="wallet outgoing transfer gate only",
                risk_summary="A freeze blocks outgoing transfers but does not transfer ownership or mutate confirmed ledger history.",
            )
            conn.commit()
            return {"ok": True, "proposal": proposal}
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def create_emergency_recovery_branch_proposal(
        self,
        *,
        actor,
        incident_tx_hash,
        reason,
        base_block_number=None,
        base_block_hash="",
        excluded_tx_hashes=None,
        recovery_strategy="treasury_compensation",
        loss_cause="protocol_fault",
        compensation_rate_bps=None,
        victim_statement="",
        victim_evidence_refs=None,
        victim_claims=None,
        incident_tx_hashes=None,
        product_exposure=None,
        counterparty_reply=None,
        reference="",
    ):
        if not str(incident_tx_hash or "").strip():
            raise ValueError("incident tx hash required")
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            self._governance_begin_immediate(conn)
            strategy = str(recovery_strategy or "treasury_compensation").strip().lower()
            if strategy not in {"treasury_compensation", "tainted_remainder_return", "exclude_tainted_descendants"}:
                raise ValueError("unsupported recovery strategy")
            compensation_policy = self._recovery_compensation_policy(
                loss_cause=loss_cause,
                requested_rate_bps=compensation_rate_bps,
            )
            reviewed_claims = self._normalize_recovery_claims(
                victim_claims=victim_claims,
                default_statement=victim_statement,
                default_evidence_refs=victim_evidence_refs,
            )
            incident_refs = self._governance_evidence([incident_tx_hash, *(incident_tx_hashes or [])])
            proposal = self._create_governance_proposal_locked(
                conn,
                actor=actor,
                proposal_type="emergency_recovery_branch",
                governance_domain="EMERGENCY_SECURITY",
                action_type="ROLLBACK_BRANCH",
                title="建立緊急 recovery branch",
                description="緊急安全治理決定是否建立 recovery branch；本系統只切換 canonical branch pointer，不刪改舊 ledger。",
                reason=reason,
                reference=reference,
                incident_tx_hash=incident_tx_hash,
                base_block_number=base_block_number,
                base_block_hash=base_block_hash,
                target_branch=f"recovery:{incident_tx_hash}",
                evidence=[incident_tx_hash],
                payload={
                    "incident_tx_hashes": incident_refs,
                    "excluded_tx_hashes": self._governance_evidence(excluded_tx_hashes or []),
                    "recovery_strategy": strategy,
                    "recovery_options": {
                        "treasury_compensation": {
                            "label": "官方補缺",
                            "description": "保留後續交易；排除事故交易後造成的缺口由官方 treasury 依補償政策承擔。",
                            "treasury_compensation": True,
                            "downstream_clawback": False,
                        },
                        "tainted_remainder_return": {
                            "label": "用戶自負責",
                            "description": "保留後續交易；不由官方補償，只把駭客錢包尚未花出的 tainted remainder 退回被盜者。",
                            "treasury_compensation": False,
                            "downstream_clawback": False,
                        },
                        "exclude_tainted_descendants": {
                            "label": "嚴格排除污染後代",
                            "description": "建立 recovery branch 時排除事故交易與可追蹤的污染後代；適用系統性污染，會影響後續收款者。",
                            "treasury_compensation": False,
                            "downstream_clawback": True,
                        },
                    },
                    "loss_cause": compensation_policy["loss_cause"],
                    "compensation_rate_bps": compensation_policy["compensation_rate_bps"],
                    "compensation_policy": compensation_policy,
                    "victim_statement": str(victim_statement or "").strip()[:4000],
                    "victim_evidence_refs": self._governance_evidence(victim_evidence_refs or []),
                    "victim_claims": reviewed_claims,
                    "counterparty_reply": counterparty_reply if isinstance(counterparty_reply, dict) else {},
                    "product_exposure": product_exposure if isinstance(product_exposure, dict) else {},
                    "branch_model": "branch_isolated_asset_universe_v1",
                    "ledger_mutation": "forbidden",
                    "cross_branch_merge_forbidden": True,
                    "normal_successor_transactions_preserved": strategy in {"treasury_compensation", "tainted_remainder_return"},
                    "victim_shortfall_compensated_by_treasury": strategy == "treasury_compensation",
                    "tainted_remainder_return_only": strategy == "tainted_remainder_return",
                },
                impact_scope="emergency chain branch acceptance; public after-action review required when user balances or trust are affected",
                risk_summary="Recovery branch is a critical emergency action. It creates a new canonical asset universe from parent replay and never mutates historical ledger rows.",
                proposal_severity="CRITICAL",
            )
            conn.commit()
            return {"ok": True, "proposal": proposal}
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def create_treasury_transfer_proposal(
        self,
        *,
        actor,
        destination_wallet_address,
        amount,
        reason,
        reference="",
        action_type="TREASURY_TRANSFER",
        memo="",
    ):
        action_type = str(action_type or "TREASURY_TRANSFER").strip().upper()
        if action_type not in {"TREASURY_TRANSFER", "EXCHANGE_FUND_REPLENISH", "CONTEST_REWARD_PAYOUT"}:
            raise ValueError("unsupported treasury governance action")
        amount = int(amount or 0)
        if amount <= 0:
            raise ValueError("amount must be positive")
        destination = str(destination_wallet_address or "").strip().lower()
        if action_type == "EXCHANGE_FUND_REPLENISH":
            exchange_address = economy_fund_address(self.chain_secret, "exchange_fund")
            if destination and destination != exchange_address:
                raise ValueError("exchange fund replenishment destination must be the EXCHANGE fund system address")
            destination = exchange_address
        if not WALLET_ADDRESS_RE.fullmatch(destination):
            raise ValueError("destination wallet address format is invalid")
        title_map = {
            "TREASURY_TRANSFER": "官方 Treasury 撥款提案",
            "EXCHANGE_FUND_REPLENISH": "撥補交易所基金提案",
            "CONTEST_REWARD_PAYOUT": "競賽獎金撥款提案",
        }
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            self._governance_begin_immediate(conn)
            destination_fund_key = self._official_transfer_destination_fund_key(destination)
            multisig_policy = self._governance_multisig_policy_locked(conn, fund_key="official_treasury")
            active_branch = self._canonical_branch_uuid(conn)
            proposal = self._create_governance_proposal_locked(
                conn,
                actor=actor,
                proposal_type="official_treasury_operation",
                governance_domain="OFFICIAL_TREASURY",
                action_type=action_type,
                title=title_map[action_type],
                description="官方錢包資產操作由 manager+ 共同投票；root 只能否決，不能單人通過。",
                reason=reason,
                reference=reference,
                target_wallet_address=destination,
                target_address=destination,
                requested_amount=amount,
                requested_asset="points",
                payload={
                    "chain_branch": active_branch,
                    "destination_wallet_address": destination,
                    "destination_fund_key": destination_fund_key or "",
                    "memo": public_currency_text(memo or reason or title_map[action_type]),
                    "official_multisig_policy": multisig_policy,
                },
                evidence=[reference] if reference else [],
                impact_scope="official treasury balance and recipient pending transfer",
                risk_summary="Uses official treasury funds; manager+ approval is required and root may veto before execution.",
            )
            conn.commit()
            return {"ok": True, "proposal": proposal}
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def create_mint_request_proposal(self, *, actor, amount, reason, destination_fund_key="official_treasury", reference=""):
        amount = int(amount or 0)
        if amount <= 0:
            raise ValueError("amount must be positive")
        destination_fund_key = str(destination_fund_key or "official_treasury").strip().lower()
        if destination_fund_key not in {"official_treasury", "promo_fund", "exchange_fund"}:
            raise ValueError("mint destination fund is unsupported")
        reference = str(reference or "").strip()[:240]
        if len(reference) < 8:
            raise ValueError("mint reference/idempotency key required")
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            self._governance_begin_immediate(conn)
            active_branch = self._canonical_branch_uuid(conn)
            policy = bootstrap_economy_layer(
                conn,
                chain_secret=self.chain_secret,
                actor={"role": "system", "id": None},
                chain_branch=active_branch,
            )["policy"]
            self._mint_request_precheck_locked(
                conn,
                amount=amount,
                reference=reference,
                policy=policy,
                chain_branch=active_branch,
            )
            destination = economy_fund_address(self.chain_secret, destination_fund_key)
            multisig_policy = self._governance_multisig_policy_locked(conn, fund_key=destination_fund_key)
            proposal = self._create_governance_proposal_locked(
                conn,
                actor=actor,
                proposal_type="official_treasury_operation",
                governance_domain="OFFICIAL_TREASURY",
                action_type="MINT_REQUEST",
                title="Mint 申請提案",
                description="Mint 只能由 manager+ 通過並經 timelock；root 可 veto，但不能單人 mint。",
                reason=reason,
                reference=reference,
                target_wallet_address=destination,
                target_address=destination,
                requested_amount=amount,
                requested_asset="points",
                payload={
                    "chain_branch": active_branch,
                    "destination_fund_key": destination_fund_key,
                    "official_multisig_policy": multisig_policy,
                },
                impact_scope="max supply, releasable supply, and destination official fund",
                risk_summary="Mint increases active supply and remains capped by max_supply minus reserved_locked.",
            )
            conn.commit()
            return {"ok": True, "proposal": proposal}
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _mint_request_precheck_locked(self, conn, *, amount, reference, policy=None, chain_branch=None, exclude_proposal_uuid=""):
        amount = int(amount or 0)
        if amount <= 0:
            raise ValueError("amount must be positive")
        reference = str(reference or "").strip()
        if len(reference) < 8:
            raise ValueError("mint reference/idempotency key required")
        duplicate_sql = """
            SELECT proposal_uuid, lifecycle_status, status
            FROM points_chain_governance_proposals
            WHERE action_type='MINT_REQUEST'
              AND reference=?
              AND lifecycle_status NOT IN ('FAILED', 'CANCELLED', 'VETOED', 'EXPIRED')
        """
        duplicate_params = [reference]
        if exclude_proposal_uuid:
            duplicate_sql += " AND proposal_uuid<>?"
            duplicate_params.append(str(exclude_proposal_uuid))
        duplicate_sql += " LIMIT 1"
        duplicate = conn.execute(
            duplicate_sql,
            tuple(duplicate_params),
        ).fetchone()
        if duplicate:
            raise ValueError("mint idempotency key already used")
        branch = str(chain_branch or self._canonical_branch_uuid(conn) or self._main_branch_uuid())
        policy = policy or bootstrap_economy_layer(
            conn,
            chain_secret=self.chain_secret,
            actor={"role": "system", "id": None},
            chain_branch=branch,
        )["policy"]
        max_once = int(policy.get("mint_replenish_max_once") or 0)
        if max_once > 0 and amount > max_once:
            raise ValueError("mint amount exceeds per-proposal cap")
        replay = replay_economy_events(
            conn,
            policy=policy,
            chain_secret=self.chain_secret,
            persist_cache=False,
            chain_branch=branch,
        )
        releasable = int(policy["max_supply"]) - int(policy["reserved_locked"])
        if int(replay["minted_total"]) + amount > releasable:
            raise ValueError("mint would exceed releasable supply")
        daily_cap = int(policy.get("mint_replenish_daily_cap") or max_once or 0)
        if daily_cap > 0:
            today = utc_now()[:10]
            row = conn.execute(
                """
                SELECT COALESCE(SUM(amount), 0) AS total
                FROM points_economy_events
                WHERE status='confirmed'
                  AND chain_branch=?
                  AND source_fund_key='mint'
                  AND transaction_type='governance_mint_request'
                  AND created_at LIKE ?
                """,
                (branch, f"{today}%"),
            ).fetchone()
            if int(row["total"] or 0) + amount > daily_cap:
                raise ValueError("mint amount exceeds daily cap")
        return {"policy": policy, "replay": replay, "daily_cap": daily_cap, "per_proposal_cap": max_once}

    def create_public_governance_proposal(
        self,
        *,
        actor,
        action_type,
        title,
        reason,
        target_address="",
        incident_tx_hash="",
        reference="",
        evidence=None,
        proposal_severity="NORMAL",
        description="",
        impact_scope="",
        risk_summary="",
        payload=None,
    ):
        action_type = str(action_type or "").strip().upper()
        if action_type in {"ROLLBACK_BRANCH", "HARD_FORK_ACCEPTANCE"}:
            raise PermissionError("rollback and hard-fork proposals require manager/security sponsor and cannot be filed through the public proposal endpoint")
        if action_type not in {"MARK_SCAM", "FREEZE_ADDRESS", "UNFREEZE_ADDRESS", "AUTO_BURN_POLICY"}:
            raise ValueError("unsupported public governance action")
        if action_type in {"MARK_SCAM", "FREEZE_ADDRESS", "UNFREEZE_ADDRESS"} and not str(target_address or "").strip():
            raise ValueError("target address required")
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            self._governance_begin_immediate(conn)
            proposal = self._create_governance_proposal_locked(
                conn,
                actor=actor,
                proposal_type=self._governance_legacy_type_for_action(action_type, conn=conn),
                governance_domain="PUBLIC_COMMON_INTEREST",
                action_type=action_type,
                title=title or {
                    "MARK_SCAM": "標記疑似詐騙地址",
                    "FREEZE_ADDRESS": "治理凍結地址",
                    "UNFREEZE_ADDRESS": "解除治理凍結地址",
                    "ROLLBACK_BRANCH": "建立緊急 recovery branch",
                    "AUTO_BURN_POLICY": "自動銷毀政策",
                    "HARD_FORK_ACCEPTANCE": "Hard fork 接受案",
                }.get(action_type, "公共治理提案"),
                description=description,
                reason=reason,
                reference=reference,
                target_wallet_address=target_address,
                target_address=target_address,
                target_branch=f"recovery:{incident_tx_hash}" if incident_tx_hash else "",
                incident_tx_hash=incident_tx_hash,
                evidence=evidence,
                payload=payload or {},
                impact_scope=impact_scope,
                risk_summary=risk_summary,
                proposal_severity=proposal_severity,
            )
            conn.commit()
            return {"ok": True, "proposal": proposal}
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def create_policy_governance_proposal(
        self,
        *,
        actor,
        action_type,
        title,
        reason,
        payload=None,
        reference="",
        proposal_severity="NORMAL",
        impact_scope="",
        risk_summary="",
    ):
        action_type = str(action_type or "").strip().upper()
        if action_type not in {"EMERGENCY_LOCKDOWN", "PARAMETER_CHANGE", "FEATURE_ACTIVATION", "AUTO_BURN_POLICY", "TREASURY_SIGNER_CHANGE"}:
            raise ValueError("unsupported policy governance action")
        domain = "OFFICIAL_TREASURY" if action_type == "TREASURY_SIGNER_CHANGE" else "EMERGENCY_SECURITY" if action_type == "EMERGENCY_LOCKDOWN" else (
            "PUBLIC_COMMON_INTEREST" if action_type == "AUTO_BURN_POLICY" else "PROTOCOL_PARAMETER"
        )
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            self._governance_begin_immediate(conn)
            proposal = self._create_governance_proposal_locked(
                conn,
                actor=actor,
                proposal_type=self._governance_legacy_type_for_action(action_type, conn=conn),
                governance_domain=domain,
                action_type=action_type,
                title=title or action_type,
                description=str((payload or {}).get("description") or "")[:4000],
                reason=reason,
                reference=reference,
                payload=payload or {},
                impact_scope=impact_scope,
                risk_summary=risk_summary,
                proposal_severity=proposal_severity,
            )
            conn.commit()
            return {"ok": True, "proposal": proposal}
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _ensure_transaction_dispute_schema(self, conn):
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS points_chain_transaction_disputes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dispute_uuid TEXT NOT NULL UNIQUE,
                tx_hash TEXT NOT NULL,
                reporter_user_id INTEGER NOT NULL,
                reporter_username TEXT NOT NULL DEFAULT '',
                victim_wallet_address TEXT NOT NULL DEFAULT '',
                claimed_amount_points INTEGER NOT NULL DEFAULT 0,
                loss_cause TEXT NOT NULL DEFAULT 'unknown',
                statement TEXT NOT NULL,
                evidence_json TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'pending_review',
                reviewed_by INTEGER,
                reviewed_at TEXT,
                review_note TEXT NOT NULL DEFAULT '',
                recommended_strategy TEXT NOT NULL DEFAULT '',
                governance_proposal_uuid TEXT NOT NULL DEFAULT '',
                suspect_wallet_address TEXT NOT NULL DEFAULT '',
                address_risk_proposal_uuid TEXT NOT NULL DEFAULT '',
                address_freeze_proposal_uuid TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                CHECK (status IN ('pending_review', 'approved', 'rejected', 'proposal_created', 'cancelled'))
            )
            """
        )
        cols = table_columns(conn, "points_chain_transaction_disputes")
        additions = {
            "suspect_wallet_address": "TEXT NOT NULL DEFAULT ''",
            "address_risk_proposal_uuid": "TEXT NOT NULL DEFAULT ''",
            "address_freeze_proposal_uuid": "TEXT NOT NULL DEFAULT ''",
            "from_wallet_address": "TEXT NOT NULL DEFAULT ''",
            "to_wallet_address": "TEXT NOT NULL DEFAULT ''",
            "chain_branch": "TEXT NOT NULL DEFAULT 'main'",
            "signature_runtime_mode": "TEXT NOT NULL DEFAULT ''",
            "signature_purpose": "TEXT NOT NULL DEFAULT ''",
            "statement_hash": "TEXT NOT NULL DEFAULT ''",
            "evidence_hash": "TEXT NOT NULL DEFAULT ''",
            "signature_nonce": "TEXT NOT NULL DEFAULT ''",
            "from_signature": "TEXT NOT NULL DEFAULT ''",
            "open_signed_payload_hash": "TEXT NOT NULL DEFAULT ''",
            "open_signature_hash": "TEXT NOT NULL DEFAULT ''",
            "from_public_key_jwk_json": "TEXT NOT NULL DEFAULT '{}'",
            "from_signature_verified": "INTEGER NOT NULL DEFAULT 0",
            "reply_statement": "TEXT NOT NULL DEFAULT ''",
            "reply_evidence_json": "TEXT NOT NULL DEFAULT '[]'",
            "reply_statement_hash": "TEXT NOT NULL DEFAULT ''",
            "reply_evidence_hash": "TEXT NOT NULL DEFAULT ''",
            "reply_nonce": "TEXT NOT NULL DEFAULT ''",
            "reply_signature": "TEXT NOT NULL DEFAULT ''",
            "reply_signed_payload_hash": "TEXT NOT NULL DEFAULT ''",
            "reply_signature_hash": "TEXT NOT NULL DEFAULT ''",
            "reply_public_key_jwk_json": "TEXT NOT NULL DEFAULT '{}'",
            "reply_signature_verified": "INTEGER NOT NULL DEFAULT 0",
            "reply_created_at": "TEXT",
            "initial_freeze_expires_at": "TEXT",
            "escalated_freeze_expires_at": "TEXT",
            "identity_redaction_model": "TEXT NOT NULL DEFAULT 'address_proven_anonymous_v1'",
            "dispute_bond_points": "INTEGER NOT NULL DEFAULT 0",
            "bond_status": "TEXT NOT NULL DEFAULT 'not_collected'",
        }
        for column, ddl in additions.items():
            if column not in cols:
                conn.execute(f"ALTER TABLE points_chain_transaction_disputes ADD COLUMN {column} {ddl}")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_points_chain_disputes_tx ON points_chain_transaction_disputes(tx_hash, created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_points_chain_disputes_reporter ON points_chain_transaction_disputes(reporter_user_id, created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_points_chain_disputes_from_address ON points_chain_transaction_disputes(from_wallet_address, created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_points_chain_disputes_to_address ON points_chain_transaction_disputes(to_wallet_address, created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_points_chain_disputes_open_sig_hash ON points_chain_transaction_disputes(open_signature_hash)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_points_chain_disputes_reply_sig_hash ON points_chain_transaction_disputes(reply_signature_hash)")

    def _dispute_suspect_address_from_tx(self, tx_hash, victim_wallet_address=""):
        tx = self.explorer_transaction(tx_hash)
        if not tx:
            return ""
        payload = tx.get("transaction") or {}
        flow = payload.get("wallet_flow") if isinstance(payload.get("wallet_flow"), dict) else {}
        source = str(payload.get("source_wallet_address") or flow.get("source_wallet_address") or "").strip().lower()
        destination = str(payload.get("destination_wallet_address") or flow.get("destination_wallet_address") or "").strip().lower()
        victim = str(victim_wallet_address or "").strip().lower()
        for candidate in (destination, source):
            if not WALLET_ADDRESS_RE.fullmatch(candidate):
                continue
            if victim and candidate == victim:
                continue
            if self._explorer_fund_key_for_address(candidate):
                continue
            return candidate
        return ""

    def _address_dispute_details_from_tx(self, tx_hash):
        tx = self.explorer_transaction(tx_hash)
        if not tx:
            raise ValueError("transaction not found")
        payload = tx.get("transaction") or {}
        flow = payload.get("wallet_flow") if isinstance(payload.get("wallet_flow"), dict) else {}
        source = str(payload.get("source_wallet_address") or flow.get("source_wallet_address") or "").strip().lower()
        destination = str(payload.get("destination_wallet_address") or flow.get("destination_wallet_address") or "").strip().lower()
        if not WALLET_ADDRESS_RE.fullmatch(source):
            raise ValueError("disputed transaction source address is not a wallet address")
        if not WALLET_ADDRESS_RE.fullmatch(destination):
            raise ValueError("disputed transaction destination address is not a wallet address")
        amount = int(payload.get("amount_points") if payload.get("amount_points") is not None else payload.get("amount") or 0)
        branch = str(payload.get("chain_branch") or tx.get("chain_branch") or "main").strip() or "main"
        return {
            "tx_hash": str(payload.get("transaction_hash") or payload.get("ledger_hash") or tx_hash).strip(),
            "from_wallet_address": source,
            "to_wallet_address": destination,
            "amount_points": max(0, amount),
            "chain_branch": branch,
            "payload": payload,
        }

    def _address_dispute_statement_hash(self, statement):
        return sha256_text(str(statement or ""))

    def _address_dispute_evidence_hash(self, evidence):
        return sha256_text(canonical_json(self._governance_evidence(evidence or [])))

    def _address_dispute_runtime_mode(self):
        mode = str(self._governance_mode() or "unknown").strip()
        return mode or "unknown"

    def _address_dispute_payload_hash(
        self,
        *,
        tx_hash,
        from_wallet_address,
        to_wallet_address,
        amount_points,
        statement_hash,
        evidence_hash,
        nonce,
        chain_branch,
        purpose,
        runtime_mode,
    ):
        payload = address_dispute_payload(
            tx_hash=tx_hash,
            from_wallet_address=from_wallet_address,
            to_wallet_address=to_wallet_address,
            amount_points=amount_points,
            statement_hash=statement_hash,
            evidence_hash=evidence_hash,
            nonce=nonce,
            chain_branch=chain_branch,
            purpose=purpose,
            runtime_mode=runtime_mode,
        )
        return sha256_text(canonical_json(payload))

    def _assert_address_dispute_signature_not_replayed_locked(self, conn, *, signed_payload_hash, signature_hash, exclude_dispute_uuid=""):
        signed_payload_hash = str(signed_payload_hash or "").strip()
        signature_hash = str(signature_hash or "").strip()
        if not signed_payload_hash or not signature_hash:
            raise ValueError("address dispute signature replay guard is missing")
        params = [signed_payload_hash, signature_hash, signed_payload_hash, signature_hash]
        exclude_clause = ""
        if str(exclude_dispute_uuid or "").strip():
            exclude_clause = " AND dispute_uuid<>?"
            params.append(str(exclude_dispute_uuid or "").strip())
        row = conn.execute(
            f"""
            SELECT dispute_uuid
            FROM points_chain_transaction_disputes
            WHERE (
                open_signed_payload_hash=?
                OR open_signature_hash=?
                OR reply_signed_payload_hash=?
                OR reply_signature_hash=?
            ){exclude_clause}
            LIMIT 1
            """,
            tuple(params),
        ).fetchone()
        if row:
            raise ValueError("address dispute signed payload/signature replay rejected")

    def _assert_dispute_reply_has_no_identity_leak(self, text):
        lowered = str(text or "").lower()
        blocked = [
            "user_id",
            "username",
            "email",
            "nickname",
            "暱稱",
            "用戶名",
            "會員",
            "帳號",
            "@",
        ]
        for token in blocked:
            if token in lowered:
                raise ValueError("address dispute text must not include account identity fields; use address-only evidence")

    def _active_dispute_count_for_from_address_locked(self, conn, from_wallet_address):
        cutoff = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat().replace("+00:00", "Z")
        row = conn.execute(
            """
            SELECT COUNT(*) AS c
            FROM points_chain_transaction_disputes
            WHERE from_wallet_address=?
              AND created_at>=?
              AND status IN ('pending_review', 'approved', 'proposal_created')
            """,
            (from_wallet_address, cutoff),
        ).fetchone()
        return int(row["c"] or 0) if row else 0

    def create_transaction_dispute(
        self,
        *,
        actor,
        tx_hash,
        statement,
        victim_wallet_address="",
        claimed_amount_points=0,
        loss_cause="unknown",
        evidence=None,
        public_key_jwk=None,
        signature="",
        signature_nonce="",
        from_wallet_address="",
        to_wallet_address="",
        chain_branch="",
    ):
        user_id = int(actor_value(actor, "id") or 0)
        if user_id <= 0:
            raise PermissionError("login required")
        tx_hash = str(tx_hash or "").strip()
        if not tx_hash:
            raise ValueError("transaction hash required")
        statement = str(statement or "").strip()
        if len(statement) < 12:
            raise ValueError("statement must be at least 12 characters")
        self._assert_dispute_reply_has_no_identity_leak(statement)
        evidence_list = self._governance_evidence(evidence or [])
        for item in evidence_list:
            self._assert_dispute_reply_has_no_identity_leak(str(item or ""))
        details = self._address_dispute_details_from_tx(tx_hash)
        from_address = str(from_wallet_address or details["from_wallet_address"]).strip().lower()
        to_address = str(to_wallet_address or details["to_wallet_address"]).strip().lower()
        if from_address != details["from_wallet_address"]:
            raise ValueError("dispute from address must match transaction source")
        if to_address != details["to_wallet_address"]:
            raise ValueError("dispute to address must match transaction destination")
        branch = str(chain_branch or details["chain_branch"] or "main").strip() or "main"
        if branch != details["chain_branch"]:
            raise ValueError("dispute chain branch must match transaction branch")
        amount = max(0, int(claimed_amount_points or details["amount_points"] or 0))
        if amount != int(details["amount_points"] or 0):
            raise ValueError("dispute amount must match transaction amount")
        statement_hash = self._address_dispute_statement_hash(statement)
        evidence_hash = self._address_dispute_evidence_hash(evidence_list)
        signature_nonce = str(signature_nonce or "").strip()
        if not public_key_jwk or not signature or not signature_nonce:
            raise ValueError("address-signed dispute proof is required")
        runtime_mode = self._address_dispute_runtime_mode()
        verify_wallet_address_dispute_signature(
            tx_hash=tx_hash,
            from_wallet_address=from_address,
            to_wallet_address=to_address,
            amount_points=amount,
            statement_hash=statement_hash,
            evidence_hash=evidence_hash,
            nonce=signature_nonce,
            chain_branch=branch,
            purpose="address_dispute_open",
            signer_wallet_address=from_address,
            public_key_jwk=public_key_jwk,
            signature=signature,
            runtime_mode=runtime_mode,
        )
        open_signed_payload_hash = self._address_dispute_payload_hash(
            tx_hash=tx_hash,
            from_wallet_address=from_address,
            to_wallet_address=to_address,
            amount_points=amount,
            statement_hash=statement_hash,
            evidence_hash=evidence_hash,
            nonce=signature_nonce,
            chain_branch=branch,
            purpose="address_dispute_open",
            runtime_mode=runtime_mode,
        )
        open_signature_hash = sha256_text(str(signature or "").strip())
        canonical_jwk = canonical_public_jwk(public_key_jwk)
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            self._ensure_transaction_dispute_schema(conn)
            self._assert_address_dispute_signature_not_replayed_locked(
                conn,
                signed_payload_hash=open_signed_payload_hash,
                signature_hash=open_signature_hash,
            )
            duplicate = conn.execute(
                """
                SELECT dispute_uuid FROM points_chain_transaction_disputes
                WHERE tx_hash=? AND status IN ('pending_review', 'approved', 'proposal_created')
                LIMIT 1
                """,
                (tx_hash,),
            ).fetchone()
            if duplicate:
                raise ValueError("active dispute already exists for this transaction")
            if self._active_dispute_count_for_from_address_locked(conn, from_address) >= DISPUTE_FROM_DAILY_LIMIT:
                raise ValueError("address dispute daily limit exceeded")
            now = utc_now()
            dispute_uuid = f"pcdispute:{uuid.uuid4()}"
            initial_freeze = self._create_provisional_address_freeze_locked(
                conn,
                wallet_address=to_address,
                reason=f"one-hour address-proven transaction dispute hold: {dispute_uuid}",
                evidence=[tx_hash, *evidence_list],
                source_dispute_uuid=dispute_uuid,
                actor=None,
                ttl_seconds=DISPUTE_INITIAL_FREEZE_SECONDS,
            )
            conn.execute(
                """
                INSERT INTO points_chain_transaction_disputes (
                    dispute_uuid, tx_hash, reporter_user_id, reporter_username,
                    victim_wallet_address, claimed_amount_points, loss_cause,
                    statement, evidence_json, status, suspect_wallet_address,
                    from_wallet_address, to_wallet_address, chain_branch,
                    signature_runtime_mode, signature_purpose, statement_hash, evidence_hash, signature_nonce,
                    from_signature, open_signed_payload_hash, open_signature_hash,
                    from_public_key_jwk_json, from_signature_verified,
                    initial_freeze_expires_at, identity_redaction_model,
                    created_at, updated_at
                ) VALUES (?, ?, 0, '', ?, ?, ?, ?, ?, 'pending_review', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, 'address_proven_anonymous_v1', ?, ?)
                """,
                (
                    dispute_uuid,
                    tx_hash,
                    from_address,
                    amount,
                    str(loss_cause or "unknown").strip().lower(),
                    statement[:4000],
                    _json_dumps(evidence_list),
                    to_address,
                    from_address,
                    to_address,
                    branch,
                    runtime_mode,
                    "address_dispute_open",
                    statement_hash,
                    evidence_hash,
                    signature_nonce[:120],
                    str(signature or ""),
                    open_signed_payload_hash,
                    open_signature_hash,
                    canonical_json(canonical_jwk),
                    initial_freeze.get("expires_at") if initial_freeze else None,
                    now,
                    now,
                ),
            )
            self._audit_log(
                conn,
                "POINTS_CHAIN_ADDRESS_DISPUTE_OPENED",
                "warning",
                "Address-proven transaction dispute opened",
                actor=None,
                metadata={
                    "dispute_uuid": dispute_uuid,
                    "tx_hash": tx_hash,
                    "from_wallet_address": from_address,
                    "to_wallet_address": to_address,
                    "chain_branch": branch,
                    "identity_redaction_model": "address_proven_anonymous_v1",
                    "initial_freeze_expires_at": initial_freeze.get("expires_at") if initial_freeze else None,
                },
            )
            conn.commit()
            return {"ok": True, "dispute": self._serialize_transaction_dispute(conn, dispute_uuid), "initial_provisional_freeze": initial_freeze}
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _serialize_transaction_dispute(self, conn, dispute_uuid):
        row = conn.execute("SELECT * FROM points_chain_transaction_disputes WHERE dispute_uuid=?", (dispute_uuid,)).fetchone()
        if not row:
            return None
        keys = set(row.keys())
        return {
            "dispute_uuid": row["dispute_uuid"],
            "tx_hash": row["tx_hash"],
            "victim_wallet_address": row["victim_wallet_address"],
            "from_wallet_address": row["from_wallet_address"] if "from_wallet_address" in keys else row["victim_wallet_address"],
            "to_wallet_address": row["to_wallet_address"] if "to_wallet_address" in keys else (row["suspect_wallet_address"] if "suspect_wallet_address" in keys else ""),
            "chain_branch": row["chain_branch"] if "chain_branch" in keys else "main",
            "claimed_amount_points": int(row["claimed_amount_points"] or 0),
            "loss_cause": row["loss_cause"],
            "statement": row["statement"],
            "evidence": _json_loads(row["evidence_json"], []),
            "status": row["status"],
            "reviewed_by": "governance_operator" if row["reviewed_by"] else None,
            "reviewed_at": row["reviewed_at"],
            "review_note": row["review_note"],
            "recommended_strategy": row["recommended_strategy"],
            "governance_proposal_uuid": row["governance_proposal_uuid"],
            "suspect_wallet_address": row["suspect_wallet_address"] if "suspect_wallet_address" in keys else "",
            "address_risk_proposal_uuid": row["address_risk_proposal_uuid"] if "address_risk_proposal_uuid" in keys else "",
            "address_freeze_proposal_uuid": row["address_freeze_proposal_uuid"] if "address_freeze_proposal_uuid" in keys else "",
            "signature_runtime_mode": row["signature_runtime_mode"] if "signature_runtime_mode" in keys else "",
            "signature_purpose": row["signature_purpose"] if "signature_purpose" in keys else "",
            "statement_hash": row["statement_hash"] if "statement_hash" in keys else "",
            "evidence_hash": row["evidence_hash"] if "evidence_hash" in keys else "",
            "signature_nonce": row["signature_nonce"] if "signature_nonce" in keys else "",
            "from_signature_verified": bool(row["from_signature_verified"]) if "from_signature_verified" in keys else False,
            "reply_statement": row["reply_statement"] if "reply_statement" in keys else "",
            "reply_evidence": _json_loads(row["reply_evidence_json"], []) if "reply_evidence_json" in keys else [],
            "reply_statement_hash": row["reply_statement_hash"] if "reply_statement_hash" in keys else "",
            "reply_evidence_hash": row["reply_evidence_hash"] if "reply_evidence_hash" in keys else "",
            "reply_signature_verified": bool(row["reply_signature_verified"]) if "reply_signature_verified" in keys else False,
            "reply_created_at": row["reply_created_at"] if "reply_created_at" in keys else None,
            "initial_freeze_expires_at": row["initial_freeze_expires_at"] if "initial_freeze_expires_at" in keys else None,
            "escalated_freeze_expires_at": row["escalated_freeze_expires_at"] if "escalated_freeze_expires_at" in keys else None,
            "identity_redaction_model": row["identity_redaction_model"] if "identity_redaction_model" in keys else "legacy_user_bound",
            "dispute_bond_points": int(row["dispute_bond_points"] or 0) if "dispute_bond_points" in keys else 0,
            "bond_status": row["bond_status"] if "bond_status" in keys else "not_collected",
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def list_transaction_disputes(self, *, actor, limit=50):
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            self._ensure_transaction_dispute_schema(conn)
            is_manager = self._governance_is_manager_actor(actor)
            if is_manager:
                rows = conn.execute(
                    "SELECT dispute_uuid FROM points_chain_transaction_disputes ORDER BY id DESC LIMIT ?",
                    (min(100, max(1, int(limit or 50))),),
                ).fetchall()
            else:
                user_id = int(actor_value(actor, "id") or 0)
                state = self._wallet_identity_state_for_user(conn, user_id) if user_id > 0 else {"addresses": set()}
                addresses = sorted(str(item or "").strip().lower() for item in (state.get("addresses") or set()) if item)
                params = [user_id]
                address_clause = ""
                if addresses:
                    placeholders = ", ".join("?" for _ in addresses)
                    address_clause = f" OR from_wallet_address IN ({placeholders}) OR to_wallet_address IN ({placeholders})"
                    params.extend(addresses)
                    params.extend(addresses)
                params.append(min(100, max(1, int(limit or 50))))
                rows = conn.execute(
                    f"""
                    SELECT dispute_uuid FROM points_chain_transaction_disputes
                    WHERE reporter_user_id=?{address_clause}
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    tuple(params),
                ).fetchall()
            return {"ok": True, "disputes": [self._serialize_transaction_dispute(conn, row["dispute_uuid"]) for row in rows]}
        finally:
            conn.close()

    def reply_transaction_dispute(self, *, actor, dispute_uuid, statement, evidence=None, public_key_jwk=None, signature="", signature_nonce=""):
        if int(actor_value(actor, "id") or 0) <= 0:
            raise PermissionError("login required")
        dispute_uuid = str(dispute_uuid or "").strip()
        if not dispute_uuid:
            raise ValueError("dispute uuid required")
        statement = str(statement or "").strip()
        if len(statement) < 12:
            raise ValueError("reply statement must be at least 12 characters")
        self._assert_dispute_reply_has_no_identity_leak(statement)
        evidence_list = self._governance_evidence(evidence or [])
        for item in evidence_list:
            self._assert_dispute_reply_has_no_identity_leak(str(item or ""))
        if not public_key_jwk or not signature or not str(signature_nonce or "").strip():
            raise ValueError("address-signed reply proof is required")
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            self._ensure_transaction_dispute_schema(conn)
            row = conn.execute("SELECT * FROM points_chain_transaction_disputes WHERE dispute_uuid=?", (dispute_uuid,)).fetchone()
            if not row:
                raise ValueError("dispute not found")
            if str(row["status"] or "") not in {"pending_review", "approved"}:
                raise ValueError("dispute no longer accepts address replies")
            if int(row["reply_signature_verified"] or 0):
                raise ValueError("address dispute reply already exists")
            to_address = str(row["to_wallet_address"] or row["suspect_wallet_address"] or "").strip().lower()
            from_address = str(row["from_wallet_address"] or row["victim_wallet_address"] or "").strip().lower()
            if not WALLET_ADDRESS_RE.fullmatch(to_address) or not WALLET_ADDRESS_RE.fullmatch(from_address):
                raise ValueError("dispute is missing address scope")
            statement_hash = self._address_dispute_statement_hash(statement)
            evidence_hash = self._address_dispute_evidence_hash(evidence_list)
            runtime_mode = str(row["signature_runtime_mode"] or self._address_dispute_runtime_mode()).strip() or self._address_dispute_runtime_mode()
            verify_wallet_address_dispute_signature(
                tx_hash=row["tx_hash"],
                from_wallet_address=from_address,
                to_wallet_address=to_address,
                amount_points=int(row["claimed_amount_points"] or 0),
                statement_hash=statement_hash,
                evidence_hash=evidence_hash,
                nonce=str(signature_nonce or "").strip(),
                chain_branch=row["chain_branch"] or "main",
                purpose="address_dispute_reply",
                signer_wallet_address=to_address,
                public_key_jwk=public_key_jwk,
                signature=signature,
                runtime_mode=runtime_mode,
            )
            reply_signed_payload_hash = self._address_dispute_payload_hash(
                tx_hash=row["tx_hash"],
                from_wallet_address=from_address,
                to_wallet_address=to_address,
                amount_points=int(row["claimed_amount_points"] or 0),
                statement_hash=statement_hash,
                evidence_hash=evidence_hash,
                nonce=str(signature_nonce or "").strip(),
                chain_branch=row["chain_branch"] or "main",
                purpose="address_dispute_reply",
                runtime_mode=runtime_mode,
            )
            reply_signature_hash = sha256_text(str(signature or "").strip())
            self._assert_address_dispute_signature_not_replayed_locked(
                conn,
                signed_payload_hash=reply_signed_payload_hash,
                signature_hash=reply_signature_hash,
                exclude_dispute_uuid=dispute_uuid,
            )
            canonical_jwk = canonical_public_jwk(public_key_jwk)
            now = utc_now()
            conn.execute(
                """
                UPDATE points_chain_transaction_disputes
                SET reply_statement=?, reply_evidence_json=?, reply_statement_hash=?,
                    reply_evidence_hash=?, reply_nonce=?, reply_signature=?,
                    reply_signed_payload_hash=?, reply_signature_hash=?,
                    reply_public_key_jwk_json=?, reply_signature_verified=1,
                    reply_created_at=?, updated_at=?
                WHERE dispute_uuid=?
                """,
                (
                    statement[:4000],
                    _json_dumps(evidence_list),
                    statement_hash,
                    evidence_hash,
                    str(signature_nonce or "").strip()[:120],
                    str(signature or ""),
                    reply_signed_payload_hash,
                    reply_signature_hash,
                    canonical_json(canonical_jwk),
                    now,
                    now,
                    dispute_uuid,
                ),
            )
            self._audit_log(
                conn,
                "POINTS_CHAIN_ADDRESS_DISPUTE_REPLY",
                "info",
                "Address-proven transaction dispute reply submitted",
                actor=None,
                metadata={
                    "dispute_uuid": dispute_uuid,
                    "tx_hash": row["tx_hash"],
                    "from_wallet_address": from_address,
                    "to_wallet_address": to_address,
                    "identity_redaction_model": "address_proven_anonymous_v1",
                },
            )
            conn.commit()
            return {"ok": True, "dispute": self._serialize_transaction_dispute(conn, dispute_uuid)}
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def review_transaction_dispute(self, *, actor, dispute_uuid, status, review_note="", recommended_strategy="", create_proposal=False):
        if not self._governance_is_manager_actor(actor):
            raise PermissionError("manager+ required")
        status = str(status or "").strip().lower()
        if status not in {"approved", "rejected", "cancelled"}:
            raise ValueError("review status must be approved, rejected, or cancelled")
        strategy = str(recommended_strategy or "tainted_remainder_return").strip().lower()
        if strategy not in {"treasury_compensation", "tainted_remainder_return", "exclude_tainted_descendants"}:
            raise ValueError("invalid recovery strategy")
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            self._ensure_transaction_dispute_schema(conn)
            now = utc_now()
            conn.execute(
                """
                UPDATE points_chain_transaction_disputes
                SET status=?, reviewed_by=?, reviewed_at=?, review_note=?, recommended_strategy=?, updated_at=?
                WHERE dispute_uuid=?
                """,
                (status, int(actor_value(actor, "id") or 0), now, str(review_note or "")[:1000], strategy, now, dispute_uuid),
            )
            row = self._serialize_transaction_dispute(conn, dispute_uuid)
            conn.commit()
            proposal = None
            address_risk_proposal = None
            address_freeze_proposal = None
            provisional_freeze = None
            provisional_release = None
            taint_exposure = None
            if status == "approved" and create_proposal and row:
                suspect_address = str(row.get("to_wallet_address") or row.get("suspect_wallet_address") or "").strip().lower()
                victim_address = str(row.get("from_wallet_address") or row.get("victim_wallet_address") or "").strip().lower()
                if not WALLET_ADDRESS_RE.fullmatch(suspect_address):
                    suspect_address = self._dispute_suspect_address_from_tx(row["tx_hash"], victim_address)
                taint_exposure = self._trading_product_exposure_for_addresses_locked(
                    conn,
                    [suspect_address] if suspect_address else [],
                )
                victim_claim = {
                    "claim_id": dispute_uuid,
                    "wallet_address": victim_address,
                    "claim_amount_points": row["claimed_amount_points"],
                    "statement": row["statement"],
                    "evidence_refs": row["evidence"],
                    "review_status": "approved",
                    "review_note": review_note,
                    "address_signature_verified": bool(row.get("from_signature_verified")),
                    "statement_hash": row.get("statement_hash") or "",
                    "evidence_hash": row.get("evidence_hash") or "",
                }
                counterparty_reply = {
                    "wallet_address": suspect_address,
                    "statement": row.get("reply_statement") or "",
                    "evidence_refs": row.get("reply_evidence") or [],
                    "address_signature_verified": bool(row.get("reply_signature_verified")),
                    "statement_hash": row.get("reply_statement_hash") or "",
                    "evidence_hash": row.get("reply_evidence_hash") or "",
                    "reply_created_at": row.get("reply_created_at"),
                } if row.get("reply_statement") else {}
                proposal = self.create_emergency_recovery_branch_proposal(
                    actor=actor,
                    incident_tx_hash=row["tx_hash"],
                    reason=review_note or f"disputed transaction review approved: {dispute_uuid}",
                    excluded_tx_hashes=[row["tx_hash"]],
                    recovery_strategy=strategy,
                    loss_cause=row["loss_cause"],
                    victim_statement=row["statement"],
                    victim_evidence_refs=row["evidence"],
                    victim_claims=[victim_claim] if victim_address and row["claimed_amount_points"] else [],
                    product_exposure=taint_exposure,
                    counterparty_reply=counterparty_reply,
                    reference=f"transaction_dispute:{dispute_uuid}",
                )
                if suspect_address:
                    address_risk_proposal = self.create_address_risk_proposal(
                        actor=actor,
                        wallet_address=suspect_address,
                        reason=f"disputed transaction approved: {dispute_uuid}; {review_note or row['statement']}",
                        evidence=[row["tx_hash"], *list(row["evidence"] or [])],
                        reference=f"transaction_dispute:{dispute_uuid}:address_risk",
                    )
                    address_freeze_proposal = self.create_wallet_freeze_proposal(
                        actor=actor,
                        wallet_address=suspect_address,
                        reason=f"freeze outgoing transfer pending public governance review for disputed transaction: {dispute_uuid}",
                        evidence=[row["tx_hash"], *list(row["evidence"] or [])],
                        reference=f"transaction_dispute:{dispute_uuid}:address_freeze",
                        release=False,
                    )
                conn2 = self.get_db()
                try:
                    self.ensure_schema(conn2)
                    self._ensure_transaction_dispute_schema(conn2)
                    freeze_proposal_uuid = (address_freeze_proposal.get("proposal") or {}).get("proposal_uuid") if address_freeze_proposal else ""
                    if suspect_address:
                        provisional_freeze = self._create_provisional_address_freeze_locked(
                            conn2,
                            wallet_address=suspect_address,
                            reason=f"temporary freeze during governance review for disputed transaction: {dispute_uuid}",
                            evidence=[row["tx_hash"], *list(row["evidence"] or [])],
                            source_dispute_uuid=dispute_uuid,
                            linked_proposal_uuid=freeze_proposal_uuid,
                            actor=actor,
                            ttl_seconds=DISPUTE_ESCALATED_FREEZE_SECONDS,
                        )
                    escalation_expires_at = provisional_freeze.get("expires_at") if provisional_freeze else None
                    voting_deadline = self._governance_time_after(DISPUTE_ESCALATED_FREEZE_SECONDS - DISPUTE_VOTING_GRACE_SECONDS)
                    if freeze_proposal_uuid:
                        conn2.execute(
                            """
                            UPDATE points_chain_governance_proposals
                            SET voting_ends_at=?, expires_at=?, updated_at=?
                            WHERE proposal_uuid=? AND status='voting'
                            """,
                            (voting_deadline, voting_deadline, utc_now(), freeze_proposal_uuid),
                        )
                    conn2.execute(
                        """
                        UPDATE points_chain_transaction_disputes
                        SET status='proposal_created', governance_proposal_uuid=?,
                            suspect_wallet_address=?, address_risk_proposal_uuid=?,
                            address_freeze_proposal_uuid=?, escalated_freeze_expires_at=?, updated_at=?
                        WHERE dispute_uuid=?
                        """,
                        (
                            (proposal.get("proposal") or {}).get("proposal_uuid") or "",
                            suspect_address,
                            (address_risk_proposal.get("proposal") or {}).get("proposal_uuid") if address_risk_proposal else "",
                            freeze_proposal_uuid,
                            escalation_expires_at,
                            utc_now(),
                            dispute_uuid,
                        ),
                    )
                    conn2.commit()
                    row = self._serialize_transaction_dispute(conn2, dispute_uuid)
                finally:
                    conn2.close()
            elif status in {"rejected", "cancelled"} and row:
                conn2 = self.get_db()
                try:
                    self.ensure_schema(conn2)
                    provisional_release = self._release_provisional_address_freeze_locked(
                        conn2,
                        source_dispute_uuid=dispute_uuid,
                        reason=f"transaction dispute {status}: {dispute_uuid}",
                    )
                    if provisional_release.get("released_count"):
                        self._audit_log(
                            conn2,
                            "POINTS_CHAIN_PROVISIONAL_FREEZE_RELEASED",
                            "warning",
                            f"Provisional address freeze released after dispute {status}",
                            actor=actor,
                            metadata={
                                "dispute_uuid": dispute_uuid,
                                "status": status,
                                "release": provisional_release,
                            },
                        )
                    conn2.commit()
                except Exception:
                    conn2.rollback()
                    raise
                finally:
                    conn2.close()
            return {
                "ok": True,
                "dispute": row,
                "proposal": (proposal or {}).get("proposal") if proposal else None,
                "address_risk_proposal": (address_risk_proposal or {}).get("proposal") if address_risk_proposal else None,
                "address_freeze_proposal": (address_freeze_proposal or {}).get("proposal") if address_freeze_proposal else None,
                "provisional_freeze": provisional_freeze,
                "provisional_release": provisional_release,
                "taint_exposure": taint_exposure,
            }
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def sponsor_governance_proposal(self, *, actor, proposal_uuid):
        if not self._governance_is_manager_actor(actor):
            raise PermissionError("manager+ required to sponsor governance proposal")
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            self._governance_begin_immediate(conn)
            row = self._refresh_governance_proposal_locked(conn, proposal_uuid)
            if not row:
                raise ValueError("proposal not found")
            if row["lifecycle_status"] != "REVIEW":
                raise ValueError(f"proposal is {row['lifecycle_status']} and cannot be sponsored")
            now = utc_now()
            audit = self._append_governance_audit_locked(
                conn,
                proposal_uuid=proposal_uuid,
                event_type="PROPOSAL_SPONSORED",
                actor=actor,
                payload_hash=row["execution_payload_hash"],
                metadata={"governance_domain": row["governance_domain"], "action_type": row["action_type"]},
            )
            conn.execute(
                """
                UPDATE points_chain_governance_proposals
                SET sponsor_user_id=?, sponsor_role=?, sponsored_at=?,
                    lifecycle_status='VOTING', voting_starts_at=COALESCE(voting_starts_at, ?),
                    prev_audit_hash=?, audit_hash=?, updated_at=?
                WHERE proposal_uuid=?
                """,
                (
                    int(actor_value(actor, "id")) if actor_value(actor, "id") else None,
                    self._governance_actor_role(actor),
                    now,
                    now,
                    audit["prev_audit_hash"],
                    audit["audit_hash"],
                    now,
                    proposal_uuid,
                ),
            )
            refreshed = conn.execute("SELECT * FROM points_chain_governance_proposals WHERE proposal_uuid=?", (proposal_uuid,)).fetchone()
            conn.commit()
            return {"ok": True, "proposal": self._serialize_governance_proposal(conn, refreshed, actor=actor)}
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _governance_multisig_status_locked(self, conn, row, *, actor=None):
        payload = _json_loads(row["payload_json"], {})
        policy = payload.get("official_multisig_policy") if isinstance(payload.get("official_multisig_policy"), dict) else {}
        actor_id = int(actor_value(actor, "id") or 0)
        current_signer_wallet_address = ""
        if actor_id:
            for signer in policy.get("signers") or []:
                if int(signer.get("user_id") or 0) == actor_id:
                    current_signer_wallet_address = str(signer.get("wallet_address") or "")
                    break
        public_policy = {
            "policy_version": policy.get("policy_version") or "",
            "fund_key": policy.get("fund_key") or "",
            "wallet_type": policy.get("wallet_type") or "official_treasury_multisig",
            "wallet_scope": policy.get("wallet_scope") or "official_treasury",
            "custody_mode": policy.get("custody_mode") or "multisig",
            "spend_capability": policy.get("spend_capability") or "enabled",
            "threshold": int(policy.get("threshold") or 0),
            "threshold_weight": int(policy.get("threshold_weight") or 0),
            "signer_count": int(policy.get("signer_count") or 0),
            "total_weight": int(policy.get("total_weight") or 0),
            "signer_addresses": [str(item or "") for item in (policy.get("signer_addresses") or [])],
            "signers": [
                {
                    "signer_id": item.get("signer_id") or "",
                    "wallet_address": item.get("wallet_address") or "",
                    "wallet_type": item.get("wallet_type") or "",
                    "custody_mode": item.get("custody_mode") or "",
                    "role": item.get("role") or "",
                    "weight": int(item.get("weight") or 0),
                    "device_id": item.get("device_id") or "",
                    "pubkey_fingerprint": item.get("pubkey_fingerprint") or "",
                    "signer_created_at": item.get("signer_created_at") or "",
                    "last_used_at": item.get("last_used_at") or "",
                    "revoked": bool(item.get("revoked")),
                }
                for item in (policy.get("signers") or [])
            ],
            "signature_required_after_governance": bool(policy.get("signature_required_after_governance")),
            "server_hot_attestation_allowed": bool(policy.get("server_hot_attestation_allowed")),
            "signer_identity_model": policy.get("signer_identity_model") or "",
            "signer_weight_model": policy.get("signer_weight_model") or "",
            "device_binding_model": policy.get("device_binding_model") or "",
        }
        if current_signer_wallet_address:
            public_policy["current_signer_wallet_address"] = current_signer_wallet_address
        threshold = int(policy.get("threshold") or 0)
        threshold_weight = int(policy.get("threshold_weight") or 0)
        signer_addresses = {str(item or "").strip().lower() for item in (policy.get("signer_addresses") or []) if str(item or "").strip()}
        signer_weight_by_address = {
            str(item.get("wallet_address") or "").strip().lower(): int(item.get("weight") or 0)
            for item in (policy.get("signers") or [])
        }
        active_signer_addresses = set()
        for address in signer_addresses:
            current_wallet = conn.execute(
                "SELECT status FROM points_wallet_identities WHERE address=? LIMIT 1",
                (address,),
            ).fetchone()
            if current_wallet and current_wallet["status"] in {"pending_backup", "active"}:
                active_signer_addresses.add(address)
        rows = conn.execute(
            """
            SELECT * FROM points_chain_governance_multisig_signatures
            WHERE proposal_uuid=?
            ORDER BY id ASC
            """,
            (row["proposal_uuid"],),
        ).fetchall()
        valid = []
        for sig in rows:
            address = str(sig["signer_wallet_address"] or "").strip().lower()
            if signer_addresses and address not in signer_addresses:
                continue
            if active_signer_addresses and address not in active_signer_addresses:
                continue
            if sig["signed_payload_hash"] != row["execution_payload_hash"]:
                continue
            valid.append(sig)
        signature_weight = sum(signer_weight_by_address.get(str(sig["signer_wallet_address"] or "").strip().lower(), 0) for sig in valid)
        return {
            "required": row["governance_domain"] == "OFFICIAL_TREASURY",
            "policy": public_policy,
            "threshold": threshold,
            "threshold_weight": threshold_weight,
            "signature_count": len(valid),
            "signature_weight": signature_weight,
            "ready": bool(threshold and len(valid) >= threshold and (not threshold_weight or signature_weight >= threshold_weight)),
            "signatures": [
                {
                    "signer_wallet_address": sig["signer_wallet_address"],
                    "signature_mode": sig["signature_mode"],
                    "signed_payload_hash": sig["signed_payload_hash"],
                    "created_at": sig["created_at"],
                }
                for sig in valid
            ],
        }

    def sign_governance_multisig(self, *, actor, proposal_uuid, signer_wallet_address, signature=""):
        if not self._governance_is_manager_actor(actor):
            raise PermissionError("manager+ required to sign official treasury multisig")
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            self._governance_begin_immediate(conn)
            row = self._refresh_governance_proposal_locked(conn, proposal_uuid)
            if not row:
                raise ValueError("proposal not found")
            if row["governance_domain"] != "OFFICIAL_TREASURY":
                raise PermissionError("multisig signing is only required for official treasury proposals")
            if row["status"] != "passed":
                raise ValueError(f"proposal is {row['status']}; multisig signing requires passed governance")
            if int(row["root_veto_used"] or 0):
                raise PermissionError("proposal was vetoed by root")
            if self._governance_execution_payload_hash_for_row(row) != row["execution_payload_hash"]:
                raise ValueError("governance execution payload hash mismatch")
            payload = _json_loads(row["payload_json"], {})
            policy = payload.get("official_multisig_policy") if isinstance(payload.get("official_multisig_policy"), dict) else {}
            signer_address = str(signer_wallet_address or "").strip().lower()
            if signer_address not in {str(item).strip().lower() for item in policy.get("signer_addresses", [])}:
                raise PermissionError("signer wallet is not in official multisig policy")
            status_row = conn.execute(
                "SELECT status FROM points_wallet_identities WHERE address=? LIMIT 1",
                (signer_address,),
            ).fetchone()
            if status_row and status_row["status"] not in {"pending_backup", "active"}:
                raise PermissionError("signer wallet is disabled or revoked")
            wallet = self._wallet_identity_owner_for_address(conn, signer_address)
            if not wallet or int(wallet["user_id"] or 0) != int(actor_value(actor, "id") or 0):
                raise PermissionError("signer wallet is not owned by current actor")
            signature_branch = str(payload.get("chain_branch") or self._canonical_branch_uuid(conn) or self._main_branch_uuid())
            signing_payload = self._governance_multisig_signing_payload(row)
            signing_payload_hash = sha256_text(canonical_json(signing_payload))
            signature_mode = "wallet_signature"
            if str(wallet["custody_mode"] or "") == "self_custody":
                verify_wallet_transaction_signature(
                    user_id=int(actor_value(actor, "id") or 0),
                    source_wallet_address=signer_address,
                    destination_wallet_address=row["target_wallet_address"] or signer_address,
                    amount_points=max(1, int(row["requested_amount"] or 0)),
                    fee_points=0,
                    request_uuid=row["proposal_uuid"],
                    memo=row["execution_payload_hash"],
                    public_key_jwk=_json_loads(wallet["public_key_jwk_json"], {}),
                    signature=signature,
                    chain_branch=signature_branch,
                    proposal_id=row["proposal_uuid"],
                    action_type="points_governance_multisig_sign",
                    payload_hash=row["execution_payload_hash"],
                    signer_key_id=str(wallet["public_key_hash"] or ""),
                )
                signature_hash = sha256_text(str(signature or ""))
            else:
                signature_mode = "server_attested"
                signature_hash = sha256_text(canonical_json({
                    "proposal_uuid": row["proposal_uuid"],
                    "signer_user_id": int(actor_value(actor, "id") or 0),
                    "signer_wallet_address": signer_address,
                    "payload_hash": signing_payload_hash,
                    "mode": signature_mode,
                }))
            now = utc_now()
            conn.execute(
                """
                INSERT INTO points_chain_governance_multisig_signatures (
                    proposal_uuid, signer_user_id, signer_wallet_address, signature_mode,
                    signature_hash, signed_payload_hash, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(proposal_uuid, signer_wallet_address)
                DO UPDATE SET signer_user_id=excluded.signer_user_id,
                              signature_mode=excluded.signature_mode,
                              signature_hash=excluded.signature_hash,
                              signed_payload_hash=excluded.signed_payload_hash,
                              created_at=excluded.created_at
                """,
                (
                    row["proposal_uuid"],
                    int(actor_value(actor, "id") or 0),
                    signer_address,
                    signature_mode,
                    signature_hash,
                    row["execution_payload_hash"],
                    now,
                ),
            )
            audit = self._append_governance_audit_locked(
                conn,
                proposal_uuid=row["proposal_uuid"],
                event_type="MULTISIG_SIGNATURE_COLLECTED",
                actor=actor,
                payload_hash=row["execution_payload_hash"],
                metadata={"signer_wallet_address": signer_address, "signature_mode": signature_mode},
            )
            conn.execute(
                "UPDATE points_chain_governance_proposals SET prev_audit_hash=?, audit_hash=?, updated_at=? WHERE proposal_uuid=?",
                (audit["prev_audit_hash"], audit["audit_hash"], now, row["proposal_uuid"]),
            )
            refreshed = conn.execute("SELECT * FROM points_chain_governance_proposals WHERE proposal_uuid=?", (row["proposal_uuid"],)).fetchone()
            status = self._governance_multisig_status_locked(conn, refreshed)
            conn.commit()
            return {"ok": True, "proposal": self._serialize_governance_proposal(conn, refreshed, actor=actor), "multisig": status}
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _refresh_governance_proposal_locked(self, conn, proposal_uuid):
        row = conn.execute(
            "SELECT * FROM points_chain_governance_proposals WHERE proposal_uuid=?",
            (proposal_uuid,),
        ).fetchone()
        if not row:
            return None
        votes = conn.execute(
            """
            SELECT vote, COUNT(*) AS c
            FROM points_chain_governance_votes
            WHERE proposal_uuid=?
            GROUP BY vote
            """,
            (proposal_uuid,),
        ).fetchall()
        counts = {"yes": 0, "no": 0, "abstain": 0}
        for vote in votes:
            counts[str(vote["vote"])] = int(vote["c"] or 0)
        status = row["status"]
        previous_status = status
        total_votes = sum(counts.values())
        decisive_votes = counts["yes"] + counts["no"]
        lifecycle_status = row["lifecycle_status"]
        if status in {"voting"} and lifecycle_status == "VOTING":
            expired_at = parse_utc_timestamp(row["expires_at"])
            if expired_at and expired_at <= datetime.now(timezone.utc):
                status = "expired"
                lifecycle_status = "EXPIRED"
            elif total_votes >= int(row["quorum_count"] or 0) and decisive_votes > 0:
                approval_units = (counts["yes"] * 10000) // decisive_votes
                differential_units = ((counts["yes"] - counts["no"]) * 10000) // max(1, int(row["eligible_voter_count"] or 0))
                if approval_units >= int(row[GOV_PASS_THRESHOLD_RATE_FIELD] or 0) and differential_units >= int(row[GOV_VOTE_DIFFERENTIAL_REQUIRED_RATE_FIELD] or 0):
                    status = "passed"
                    timelock_until = parse_utc_timestamp(row["timelock_until"])
                    lifecycle_status = "TIMELOCKED" if timelock_until and timelock_until > datetime.now(timezone.utc) else "QUEUED"
        now = utc_now()
        conn.execute(
            """
            UPDATE points_chain_governance_proposals
            SET yes_count=?, no_count=?, abstain_count=?, status=?, lifecycle_status=?, updated_at=?
            WHERE proposal_uuid=?
            """,
            (counts["yes"], counts["no"], counts["abstain"], status, lifecycle_status, now, proposal_uuid),
        )
        if (
            previous_status != "expired"
            and status == "expired"
            and str(row["action_type"] or "").strip().upper() == "FREEZE_ADDRESS"
        ):
            release = self._release_provisional_address_freeze_locked(
                conn,
                linked_proposal_uuid=proposal_uuid,
                reason=f"governance freeze proposal expired: {proposal_uuid}",
            )
            if release.get("released_count"):
                self._audit_log(
                    conn,
                    "POINTS_CHAIN_PROVISIONAL_FREEZE_RELEASED",
                    "warning",
                    "Provisional address freeze released after governance proposal expired",
                    actor=None,
                    metadata={
                        "proposal_uuid": proposal_uuid,
                        "release": release,
                    },
                )
        return conn.execute(
            "SELECT * FROM points_chain_governance_proposals WHERE proposal_uuid=?",
            (proposal_uuid,),
        ).fetchone()

    def cast_governance_vote(self, *, actor, proposal_uuid, vote, reason="", recovery_choice=None):
        voter_id = int(actor_value(actor, "id") or 0)
        if voter_id <= 0:
            raise PermissionError("login required")
        vote = str(vote or "").strip().lower()
        if vote not in {"yes", "no", "abstain"}:
            raise ValueError("vote must be yes, no, or abstain")
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            self._governance_begin_immediate(conn)
            row = self._refresh_governance_proposal_locked(conn, proposal_uuid)
            if not row:
                raise ValueError("proposal not found")
            if row["status"] != "voting" or row["lifecycle_status"] != "VOTING":
                raise ValueError(f"proposal is {row['lifecycle_status']} and does not accept votes")
            eligible = set(int(item) for item in _json_loads(row["eligible_voters_json"], []))
            if voter_id not in eligible:
                raise PermissionError("not eligible to vote on this proposal")
            stored_reason = str(reason or "").strip()[:500]
            choice = str(recovery_choice or "").strip().lower()
            if str(row["action_type"] or "").strip().upper() == "ROLLBACK_BRANCH" and vote == "yes":
                payload = _json_loads(row["payload_json"], {})
                options = payload.get("recovery_options") if isinstance(payload.get("recovery_options"), dict) else {}
                allowed = set(options.keys()) or {"treasury_compensation", "tainted_remainder_return", "exclude_tainted_descendants"}
                if not choice:
                    choice = str(payload.get("recovery_strategy") or "tainted_remainder_return").strip().lower()
                if choice not in allowed:
                    raise ValueError("invalid recovery option choice")
                stored_reason = _json_dumps({
                    "reason": stored_reason,
                    "recovery_choice": choice,
                })[:500]
            now = utc_now()
            conn.execute(
                """
                INSERT INTO points_chain_governance_votes (
                    proposal_uuid, voter_user_id, vote, reason, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(proposal_uuid, voter_user_id)
                DO UPDATE SET vote=excluded.vote, reason=excluded.reason, updated_at=excluded.updated_at
                """,
                (proposal_uuid, voter_id, vote, stored_reason, now, now),
            )
            refreshed = self._refresh_governance_proposal_locked(conn, proposal_uuid)
            self._audit_log(
                conn,
                "POINTS_CHAIN_GOVERNANCE_VOTE_CAST",
                "info",
                "PointsChain governance vote cast",
                actor=actor,
                metadata={"proposal_uuid": proposal_uuid, "vote": vote, "status": refreshed["status"], "recovery_choice": choice},
            )
            audit = self._append_governance_audit_locked(
                conn,
                proposal_uuid=proposal_uuid,
                event_type="VOTE_CAST",
                actor=actor,
                payload_hash=refreshed["execution_payload_hash"],
                metadata={"vote": vote, "status": refreshed["status"], "lifecycle_status": refreshed["lifecycle_status"], "recovery_choice": choice},
            )
            conn.execute(
                """
                UPDATE points_chain_governance_proposals
                SET prev_audit_hash=?, audit_hash=?
                WHERE proposal_uuid=?
                """,
                (audit["prev_audit_hash"], audit["audit_hash"], proposal_uuid),
            )
            conn.commit()
            return {"ok": True, "proposal": self._serialize_governance_proposal(conn, refreshed, actor=actor)}
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _address_risk_label_locked(self, conn, address):
        normalized = str(address or "").strip().lower()
        if not normalized:
            return None
        row = conn.execute(
            """
            SELECT * FROM points_chain_address_risk_labels
            WHERE wallet_address=? AND status='active'
            """,
            (normalized,),
        ).fetchone()
        if not row:
            return None
        return {
            "wallet_address": row["wallet_address"],
            "risk_level": row["risk_level"],
            "status": row["status"],
            "label": row["label"],
            "reason": row["reason"],
            "evidence": _json_loads(row["evidence_json"], []),
            "proposal_uuid": row["proposal_uuid"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _address_freeze_locked(self, conn, address):
        normalized = str(address or "").strip().lower()
        if not normalized:
            return None
        row = conn.execute(
            """
            SELECT * FROM points_chain_address_freezes
            WHERE wallet_address=? AND status='active'
            """,
            (normalized,),
        ).fetchone()
        if not row:
            return None
        return {
            "wallet_address": row["wallet_address"],
            "status": row["status"],
            "freeze_type": "governance",
            "reason": row["reason"],
            "evidence": _json_loads(row["evidence_json"], []),
            "freeze_proposal_uuid": row["freeze_proposal_uuid"],
            "release_proposal_uuid": row["release_proposal_uuid"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _address_provisional_freeze_locked(self, conn, address):
        normalized = str(address or "").strip().lower()
        if not normalized:
            return None
        row = conn.execute(
            """
            SELECT * FROM points_chain_address_provisional_freezes
            WHERE wallet_address=? AND status='active'
            """,
            (normalized,),
        ).fetchone()
        if not row:
            return None
        now = utc_now()
        if str(row["expires_at"] or "") <= now:
            conn.execute(
                """
                UPDATE points_chain_address_provisional_freezes
                SET status='expired', updated_at=?
                WHERE id=? AND status='active'
                """,
                (now, row["id"]),
            )
            self._audit_log(
                conn,
                "POINTS_CHAIN_PROVISIONAL_FREEZE_EXPIRED",
                "info",
                "Provisional address freeze expired automatically",
                actor=None,
                metadata={
                    "wallet_address": row["wallet_address"],
                    "source_dispute_uuid": row["source_dispute_uuid"],
                    "linked_proposal_uuid": row["linked_proposal_uuid"],
                    "expires_at": row["expires_at"],
                },
            )
            return None
        return {
            "wallet_address": row["wallet_address"],
            "status": row["status"],
            "freeze_type": "provisional",
            "reason": row["reason"],
            "evidence": _json_loads(row["evidence_json"], []),
            "source_dispute_uuid": row["source_dispute_uuid"],
            "linked_proposal_uuid": row["linked_proposal_uuid"],
            "reviewed_by": int(row["reviewed_by"] or 0) if row["reviewed_by"] else None,
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "expires_at": row["expires_at"],
        }

    def _assert_address_not_frozen_for_outgoing_locked(self, conn, address, *, action="wallet spend"):
        normalized = str(address or "").strip().lower()
        if not WALLET_ADDRESS_RE.fullmatch(normalized):
            return
        if self._address_freeze_locked(conn, normalized):
            raise PermissionError(f"{action}: source wallet address is frozen by governance vote")
        if self._address_provisional_freeze_locked(conn, normalized):
            raise PermissionError(f"{action}: source wallet address is temporarily frozen pending governance review")

    def _create_provisional_address_freeze_locked(
        self,
        conn,
        *,
        wallet_address,
        reason,
        evidence=None,
        source_dispute_uuid="",
        linked_proposal_uuid="",
        actor=None,
        ttl_seconds=PROVISIONAL_ADDRESS_FREEZE_SECONDS,
    ):
        normalized = str(wallet_address or "").strip().lower()
        if not WALLET_ADDRESS_RE.fullmatch(normalized):
            raise ValueError("wallet address format is invalid")
        now = utc_now()
        expires_at = self._governance_time_after(max(60, int(ttl_seconds or PROVISIONAL_ADDRESS_FREEZE_SECONDS)))
        conn.execute(
            """
            INSERT INTO points_chain_address_provisional_freezes (
                wallet_address, status, reason, evidence_json, source_dispute_uuid,
                linked_proposal_uuid, reviewed_by, created_at, updated_at, expires_at
            ) VALUES (?, 'active', ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(wallet_address)
            DO UPDATE SET status='active',
                          reason=excluded.reason,
                          evidence_json=excluded.evidence_json,
                          source_dispute_uuid=excluded.source_dispute_uuid,
                          linked_proposal_uuid=excluded.linked_proposal_uuid,
                          reviewed_by=excluded.reviewed_by,
                          updated_at=excluded.updated_at,
                          expires_at=excluded.expires_at,
                          released_at=NULL
            """,
            (
                normalized,
                str(reason or "")[:1000],
                _json_dumps(self._governance_evidence(evidence or [])),
                str(source_dispute_uuid or "")[:128],
                str(linked_proposal_uuid or "")[:128],
                int(actor_value(actor, "id") or 0) or None,
                now,
                now,
                expires_at,
            ),
        )
        return self._address_provisional_freeze_locked(conn, normalized)

    def _release_provisional_address_freeze_locked(self, conn, *, wallet_address="", source_dispute_uuid="", linked_proposal_uuid="", reason=""):
        now = utc_now()
        if wallet_address:
            normalized = str(wallet_address or "").strip().lower()
            if not WALLET_ADDRESS_RE.fullmatch(normalized):
                raise ValueError("wallet address format is invalid")
            cur = conn.execute(
                """
                UPDATE points_chain_address_provisional_freezes
                SET status='released', updated_at=?, released_at=?
                WHERE wallet_address=? AND status='active'
                """,
                (now, now, normalized),
            )
        elif source_dispute_uuid:
            cur = conn.execute(
                """
                UPDATE points_chain_address_provisional_freezes
                SET status='released', updated_at=?, released_at=?
                WHERE source_dispute_uuid=? AND status='active'
                """,
                (now, now, str(source_dispute_uuid or "")[:128]),
            )
        elif linked_proposal_uuid:
            cur = conn.execute(
                """
                UPDATE points_chain_address_provisional_freezes
                SET status='released', updated_at=?, released_at=?
                WHERE linked_proposal_uuid=? AND status='active'
                """,
                (now, now, str(linked_proposal_uuid or "")[:128]),
            )
        else:
            return {"released_count": 0, "reason": reason}
        return {"released_count": int(cur.rowcount or 0), "reason": reason, "released_at": now}

    def veto_governance_proposal(self, *, actor, proposal_uuid, reason=""):
        self._governance_require_root(actor)
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            self._governance_begin_immediate(conn)
            row = self._refresh_governance_proposal_locked(conn, proposal_uuid)
            if not row:
                raise ValueError("proposal not found")
            if not int(row["root_veto_allowed"] or 0):
                raise PermissionError("root veto is not allowed for this governance domain")
            if row["status"] in {"executed", "expired", "cancelled"} or row["lifecycle_status"] in {"EXECUTED", "EXPIRED", "CANCELLED", "VETOED"}:
                raise ValueError(f"proposal is {row['lifecycle_status']} and cannot be vetoed")
            now = utc_now()
            veto_reason = str(reason or "root veto").strip()[:1000] or "root veto"
            audit = self._append_governance_audit_locked(
                conn,
                proposal_uuid=proposal_uuid,
                event_type="ROOT_VETO",
                actor=actor,
                payload_hash=row["execution_payload_hash"],
                metadata={"reason": veto_reason, "governance_domain": row["governance_domain"], "action_type": row["action_type"]},
            )
            conn.execute(
                """
                UPDATE points_chain_governance_proposals
                SET root_veto_used=1, root_vetoed_by=?, root_vetoed_at=?, root_veto_reason=?,
                    status='cancelled', lifecycle_status='VETOED',
                    prev_audit_hash=?, audit_hash=?, updated_at=?
                WHERE proposal_uuid=?
                """,
                (
                    int(actor_value(actor, "id")) if actor_value(actor, "id") else None,
                    now,
                    veto_reason,
                    audit["prev_audit_hash"],
                    audit["audit_hash"],
                    now,
                    proposal_uuid,
                ),
            )
            self._audit_log(
                conn,
                "POINTS_CHAIN_GOVERNANCE_ROOT_VETO",
                "warning",
                "PointsChain governance proposal vetoed by root",
                actor=actor,
                metadata={"proposal_uuid": proposal_uuid, "reason": veto_reason},
            )
            refreshed = conn.execute("SELECT * FROM points_chain_governance_proposals WHERE proposal_uuid=?", (proposal_uuid,)).fetchone()
            conn.commit()
            return {"ok": True, "proposal": self._serialize_governance_proposal(conn, refreshed, actor=actor)}
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def cancel_governance_proposal(self, *, actor, proposal_uuid, reason=""):
        if not self._governance_is_manager_actor(actor):
            raise PermissionError("manager+ required")
        cancel_reason = str(reason or "proposal cancelled").strip()[:1000] or "proposal cancelled"
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            self._governance_begin_immediate(conn)
            row = self._refresh_governance_proposal_locked(conn, proposal_uuid)
            if not row:
                raise ValueError("proposal not found")
            if row["status"] in {"executed", "expired", "cancelled"} or row["lifecycle_status"] in {"EXECUTED", "EXPIRED", "CANCELLED", "VETOED"}:
                raise ValueError(f"proposal is {row['lifecycle_status']} and cannot be cancelled")
            now = utc_now()
            audit = self._append_governance_audit_locked(
                conn,
                proposal_uuid=proposal_uuid,
                event_type="PROPOSAL_CANCELLED",
                actor=actor,
                payload_hash=row["execution_payload_hash"],
                metadata={"reason": cancel_reason, "governance_domain": row["governance_domain"], "action_type": row["action_type"]},
            )
            conn.execute(
                """
                UPDATE points_chain_governance_proposals
                SET status='cancelled', lifecycle_status='CANCELLED',
                    prev_audit_hash=?, audit_hash=?, updated_at=?
                WHERE proposal_uuid=?
                """,
                (audit["prev_audit_hash"], audit["audit_hash"], now, proposal_uuid),
            )
            self._audit_log(
                conn,
                "POINTS_CHAIN_GOVERNANCE_PROPOSAL_CANCELLED",
                "warning",
                "PointsChain governance proposal cancelled",
                actor=actor,
                metadata={"proposal_uuid": proposal_uuid, "reason": cancel_reason},
            )
            refreshed = conn.execute("SELECT * FROM points_chain_governance_proposals WHERE proposal_uuid=?", (proposal_uuid,)).fetchone()
            conn.commit()
            return {"ok": True, "proposal": self._serialize_governance_proposal(conn, refreshed, actor=actor)}
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _activate_recovery_branch_locked(self, conn, *, row, proposal_uuid, now):
        branch_uuid = f"pcbranch:{uuid.uuid4()}"
        parent = conn.execute(
            """
            SELECT * FROM points_chain_governance_branches
            WHERE is_canonical=1 ORDER BY id DESC LIMIT 1
            """
        ).fetchone()
        parent_branch_uuid = parent["branch_uuid"] if parent else self._main_branch_uuid()
        payload = _json_loads(row["payload_json"], {})
        selected_strategy = self._selected_recovery_strategy_locked(conn, row)
        payload["selected_recovery_strategy"] = selected_strategy
        payload["recovery_strategy"] = selected_strategy
        if parent:
            conn.execute("UPDATE points_chain_governance_branches SET is_canonical=0, write_enabled=0, status='archived' WHERE is_canonical=1")
        else:
            conn.execute(
                """
                INSERT OR IGNORE INTO points_chain_governance_branches (
                    branch_uuid, proposal_uuid, parent_branch_uuid, branch_name,
                    base_block_number, base_block_hash, incident_tx_hash,
                    status, is_canonical, write_enabled, recovery_type, replay_plan_json, created_at, activated_at
                ) VALUES ('main', ?, '', 'main', NULL, '', ?, 'archived', 0, 0, 'pre_fork_main', ?, ?, ?)
                """,
                (
                    proposal_uuid,
                    row["incident_tx_hash"],
                    _json_dumps({
                        "asset_universe": "main",
                        "read_only_after_recovery_branch": True,
                        "ledger_mutation": "forbidden",
                    }),
                    now,
                    now,
                ),
            )
        conn.execute(
            """
            INSERT INTO points_chain_governance_branches (
                branch_uuid, proposal_uuid, parent_branch_uuid, branch_name,
                base_block_number, base_block_hash, incident_tx_hash,
                status, is_canonical, write_enabled, recovery_type, replay_plan_json, created_at, activated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'canonical_recovery', 1, 1, 'chain_fork_asset_universe_v1', ?, ?, ?)
            """,
            (
                branch_uuid,
                proposal_uuid,
                parent_branch_uuid,
                f"emergency-recovery-{row['id']}",
                row["base_block_number"],
                row["base_block_hash"],
                row["incident_tx_hash"],
                _json_dumps({
                    **payload,
                    "proposal_uuid": proposal_uuid,
                    "ledger_mutation": "forbidden",
                    "canonical_pointer_changed": True,
                    "asset_universe": branch_uuid,
                    "parent_asset_universe": parent_branch_uuid,
                    "old_branch_read_only": True,
                    "cross_branch_merge_forbidden": True,
                }),
                now,
                now,
            ),
        )
        system_fund_seed = self._seed_recovery_branch_system_funds_locked(
            conn,
            branch_uuid=branch_uuid,
            parent_branch_uuid=parent_branch_uuid,
            recovery_strategy=str(payload.get("recovery_strategy") or "treasury_compensation").strip().lower(),
            actor={"role": "system", "username": "system"},
        )
        recovery_seed = self._seed_recovery_branch_balances_locked(
            conn,
            branch_uuid=branch_uuid,
            parent_branch_uuid=parent_branch_uuid,
            proposal_row=row,
            override_payload=payload,
            actor={"role": "system", "username": "system"},
        )
        recovery_seed["system_funds"] = system_fund_seed
        return {
            "action": "canonical_recovery_branch_activated",
            "branch_uuid": branch_uuid,
            "parent_branch_uuid": parent_branch_uuid,
            "incident_tx_hash": row["incident_tx_hash"],
            "ledger_mutation": "forbidden",
            "asset_universe": branch_uuid,
            "old_branch_read_only": True,
            "cross_branch_merge_forbidden": True,
            "recovery_seed": recovery_seed,
        }

    def _seed_recovery_branch_system_funds_locked(self, conn, *, branch_uuid, parent_branch_uuid, recovery_strategy, actor=None):
        parent_branch = str(parent_branch_uuid or self._main_branch_uuid()).strip() or self._main_branch_uuid()
        branch_uuid = str(branch_uuid or "").strip()
        if not branch_uuid:
            raise ValueError("recovery branch uuid is required")
        parent_economy = replay_economy_events(
            conn,
            chain_secret=self.chain_secret,
            persist_cache=False,
            chain_branch=parent_branch,
        )
        created = []
        skipped = []
        for fund_key in ("burn", "official_treasury", "promo_fund", "exchange_fund"):
            idempotency_key = f"recovery_branch_system_fund_carry_forward:{branch_uuid}:{fund_key}"
            existing = conn.execute(
                "SELECT * FROM points_economy_events WHERE idempotency_key=?",
                (idempotency_key,),
            ).fetchone()
            if existing:
                created.append({
                    "fund_key": fund_key,
                    "amount_points": int(existing["amount"] or 0),
                    "event_uuid": existing["event_uuid"],
                    "created": False,
                    "source_branch_uuid": _json_loads(existing["metadata_json"], {}).get("source_branch_uuid") or parent_branch,
                })
                continue
            fund_source = self._recovery_branch_system_fund_source_locked(
                conn,
                parent_branch_uuid=parent_branch,
                fund_key=fund_key,
            )
            amount = int(fund_source.get("amount_points") or 0)
            if amount <= 0:
                skipped.append({"fund_key": fund_key, "reason": "zero_parent_balance", "source_branch_uuid": fund_source.get("source_branch_uuid") or parent_branch})
                continue
            event, was_created = append_economy_event(
                conn,
                chain_secret=self.chain_secret,
                event_type="recovery_branch_system_fund_carry_forward",
                transaction_type=f"recovery_branch_{fund_key}_carry_forward",
                source_fund_key="mint",
                destination_fund_key=fund_key,
                amount=amount,
                idempotency_key=idempotency_key,
                metadata={
                    "recovery_branch_uuid": branch_uuid,
                    "parent_branch_uuid": parent_branch,
                    "source_branch_uuid": fund_source.get("source_branch_uuid") or parent_branch,
                    "recovery_strategy": recovery_strategy,
                    "fund_key": fund_key,
                    "source": "parent_branch_system_fund_balance",
                    "branch_accounting": "system_fund_branch_scope_v1",
                    "used_ancestor_fallback": bool(fund_source.get("used_ancestor_fallback")),
                    "parent_exchange_receivable_principal": int(parent_economy.get("exchange_receivable_principal") or 0),
                    "parent_exchange_total_assets": int(parent_economy.get("exchange_total_assets") or 0),
                },
                actor=actor,
                chain_branch=branch_uuid,
            )
            created.append({
                "fund_key": fund_key,
                "amount_points": amount,
                "event_uuid": event["event_uuid"],
                "created": bool(was_created),
                "source_branch_uuid": fund_source.get("source_branch_uuid") or parent_branch,
                "used_ancestor_fallback": bool(fund_source.get("used_ancestor_fallback")),
            })
        return {
            "parent_branch_uuid": parent_branch,
            "branch_uuid": branch_uuid,
            "created": created,
            "created_count": len(created),
            "skipped": skipped,
            "skipped_count": len(skipped),
            "parent_health": parent_economy.get("health") or {},
            "parent_exchange_receivable_principal": int(parent_economy.get("exchange_receivable_principal") or 0),
            "parent_exchange_total_assets": int(parent_economy.get("exchange_total_assets") or 0),
            "model": "system_fund_branch_scope_v1",
        }

    def _recovery_branch_system_fund_source_locked(self, conn, *, parent_branch_uuid, fund_key):
        branch = str(parent_branch_uuid or self._main_branch_uuid()).strip() or self._main_branch_uuid()
        fund_key = str(fund_key or "").strip().lower()
        visited = set()
        first = True
        while branch and branch not in visited:
            visited.add(branch)
            replay = replay_economy_events(
                conn,
                chain_secret=self.chain_secret,
                persist_cache=False,
                chain_branch=branch,
            )
            amount = int(((replay.get("balances") or {}).get(fund_key) or {}).get("balance") or 0)
            has_seed = self._branch_has_system_fund_seed_locked(conn, branch_uuid=branch, fund_key=fund_key)
            if amount > 0 or branch == self._main_branch_uuid() or has_seed:
                return {
                    "source_branch_uuid": branch,
                    "amount_points": amount,
                    "used_ancestor_fallback": not first,
                    "source_branch_has_seed": bool(has_seed),
                }
            parent = conn.execute(
                """
                SELECT parent_branch_uuid FROM points_chain_governance_branches
                WHERE branch_uuid=? LIMIT 1
                """,
                (branch,),
            ).fetchone()
            branch = str(parent["parent_branch_uuid"] or self._main_branch_uuid()).strip() if parent else self._main_branch_uuid()
            first = False
        return {"source_branch_uuid": parent_branch_uuid, "amount_points": 0, "used_ancestor_fallback": False}

    def _branch_has_system_fund_seed_locked(self, conn, *, branch_uuid, fund_key):
        fund_key = str(fund_key or "").strip().lower()
        transaction_types = [f"recovery_branch_{fund_key}_carry_forward"]
        if fund_key == "official_treasury":
            transaction_types.append("recovery_branch_official_treasury_carry_forward")
        placeholders = ", ".join("?" for _ in transaction_types)
        row = conn.execute(
            f"""
            SELECT 1 FROM points_economy_events
            WHERE chain_branch=? AND transaction_type IN ({placeholders})
            LIMIT 1
            """,
            (branch_uuid, *transaction_types),
        ).fetchone()
        return bool(row)

    def _selected_recovery_strategy_locked(self, conn, row):
        payload = _json_loads(row["payload_json"], {})
        options = payload.get("recovery_options") if isinstance(payload.get("recovery_options"), dict) else {}
        allowed = set(options.keys()) or {"treasury_compensation", "tainted_remainder_return", "exclude_tainted_descendants"}
        default = str(payload.get("recovery_strategy") or "tainted_remainder_return").strip().lower()
        if default not in allowed:
            default = "tainted_remainder_return" if "tainted_remainder_return" in allowed else sorted(allowed)[0]
        rows = conn.execute(
            "SELECT reason FROM points_chain_governance_votes WHERE proposal_uuid=? AND vote='yes'",
            (row["proposal_uuid"],),
        ).fetchall()
        counts = {}
        for vote_row in rows:
            reason_payload = _json_loads(vote_row["reason"], {})
            choice = ""
            if isinstance(reason_payload, dict):
                choice = str(reason_payload.get("recovery_choice") or "").strip().lower()
            if not choice:
                choice = str(vote_row["reason"] or "").strip().lower()
            if choice in allowed:
                counts[choice] = int(counts.get(choice, 0)) + 1
        if not counts:
            return default
        ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
            raise ValueError("recovery option vote is tied; execution requires a clear option majority")
        return ranked[0][0]

    def _replay_branch_address_balances_locked(self, conn, *, branch_uuid, excluded_refs=None, exclude_tainted_descendants=True):
        branch = str(branch_uuid or self._main_branch_uuid())
        excluded = {str(item or "").strip() for item in (excluded_refs or []) if str(item or "").strip()}
        rows = conn.execute(
            """
            SELECT * FROM points_ledger
            WHERE status='confirmed' AND chain_branch=?
            ORDER BY id ASC
            """,
            (branch,),
        ).fetchall()

        def ledger_refs(ledger):
            return {
                str(ledger["ledger_uuid"] or ""),
                str(ledger["ledger_hash"] or ""),
                str(ledger["reference_id"] or ""),
            }

        auto_excluded = {}
        balances = {}
        skipped = 0
        iterations = 0
        for _index in range(len(rows) + 1):
            iterations += 1
            balances = {}
            skipped = 0
            added_exclusion = False
            for ledger in rows:
                refs = ledger_refs(ledger)
                if refs & excluded:
                    skipped += 1
                    continue
                flow = self._ledger_wallet_flow_for_read(conn, ledger)
                amount = int(ledger["amount"] or 0)
                direction = str(ledger["direction"] or "")
                source = str(flow.get("source_wallet_address") or "").strip().lower()
                destination = str(flow.get("destination_wallet_address") or "").strip().lower()
                if direction in {"credit", "transfer_in"} and destination:
                    balances[destination] = int(balances.get(destination, 0)) + amount
                    continue
                if direction in {"debit", "transfer_out", "reverse", "freeze"} and source:
                    balance_before = int(balances.get(source, 0))
                    balance_after = balance_before - amount
                    if exclude_tainted_descendants and balance_after < 0:
                        reference_id = str(ledger["reference_id"] or ledger["ledger_hash"] or ledger["ledger_uuid"])
                        new_refs = {ref for ref in refs if ref}
                        excluded.update(new_refs)
                        auto_excluded.setdefault(reference_id, {
                            "reference_id": reference_id,
                            "ledger_uuid": ledger["ledger_uuid"],
                            "ledger_hash": ledger["ledger_hash"],
                            "wallet_address": source,
                            "direction": direction,
                            "action_type": ledger["action_type"],
                            "amount": amount,
                            "balance_before": balance_before,
                            "balance_after": balance_after,
                            "reason": "dependent_transaction_would_overdraw_after_recovery_exclusions",
                        })
                        added_exclusion = True
                        break
                    balances[source] = balance_after
                    continue
                if direction == "unfreeze" and (source or destination):
                    address = source or destination
                    balances[address] = int(balances.get(address, 0)) + amount
            if not added_exclusion:
                break
        return {
            "balances": balances,
            "ledger_rows": len(rows),
            "excluded_rows": skipped,
            "excluded_refs": sorted(excluded),
            "auto_excluded_refs": sorted(auto_excluded.keys()),
            "auto_excluded": list(auto_excluded.values())[:100],
            "auto_excluded_count": len(auto_excluded),
            "exclusion_iterations": iterations,
        }

    def _recovery_compensation_policy(self, *, loss_cause, requested_rate_bps=None):
        cause = str(loss_cause or "protocol_fault").strip().lower()
        policies = {
            "protocol_fault": {"default_bps": 10000, "max_bps": 10000, "label": "protocol fault"},
            "chain_bug": {"default_bps": 10000, "max_bps": 10000, "label": "chain bug"},
            "exchange_bug": {"default_bps": 10000, "max_bps": 10000, "label": "exchange bug"},
            "treasury_hot_wallet_compromise": {"default_bps": 10000, "max_bps": 10000, "label": "treasury hot wallet compromise"},
            "admin_negligence": {"default_bps": 5000, "max_bps": 10000, "label": "admin negligence"},
            "user_phishing": {"default_bps": 0, "max_bps": 5000, "label": "user phishing"},
            "private_key_leak": {"default_bps": 0, "max_bps": 5000, "label": "private key leak"},
            "user_negligence": {"default_bps": 0, "max_bps": 5000, "label": "user negligence"},
            "unknown": {"default_bps": 0, "max_bps": 5000, "label": "unknown cause"},
        }
        if cause not in policies:
            raise ValueError("unsupported loss cause")
        policy = policies[cause]
        if requested_rate_bps is None or requested_rate_bps == "":
            rate = int(policy["default_bps"])
            override = False
        else:
            rate = max(0, min(10000, int(requested_rate_bps)))
            override = True
        if rate > int(policy["max_bps"]):
            raise ValueError("compensation rate exceeds loss-cause policy cap")
        return {
            "loss_cause": cause,
            "label": policy["label"],
            "compensation_rate_bps": rate,
            "max_compensation_rate_bps": int(policy["max_bps"]),
            "requested_override": override,
            "moral_hazard_control": "user-caused losses default to no compensation and are capped at partial compensation",
        }

    def _normalize_recovery_claims(self, *, victim_claims=None, default_statement="", default_evidence_refs=None):
        claims = victim_claims if isinstance(victim_claims, list) else []
        normalized = []
        for index, raw in enumerate(claims):
            if not isinstance(raw, dict):
                continue
            wallet_address = str(raw.get("wallet_address") or raw.get("victim_wallet_address") or "").strip().lower()
            if not WALLET_ADDRESS_RE.fullmatch(wallet_address):
                raise ValueError("victim claim wallet address format is invalid")
            amount = int(raw.get("claim_amount_points") or raw.get("amount_points") or raw.get("amount") or 0)
            if amount <= 0:
                raise ValueError("victim claim amount must be positive")
            review_status = str(raw.get("review_status") or raw.get("status") or "pending").strip().lower()
            if review_status not in {"pending", "approved", "rejected"}:
                raise ValueError("victim claim review status is invalid")
            normalized.append({
                "claim_id": str(raw.get("claim_id") or f"claim-{index + 1}")[:80],
                "wallet_address": wallet_address,
                "claim_amount_points": amount,
                "statement": str(raw.get("statement") or default_statement or "").strip()[:2000],
                "evidence_refs": self._governance_evidence(raw.get("evidence_refs") or default_evidence_refs or []),
                "review_status": review_status,
                "reviewed_by": str(raw.get("reviewed_by") or "").strip()[:80],
                "review_note": str(raw.get("review_note") or "").strip()[:500],
            })
        return normalized

    def _recovery_branch_compensation_plan_locked(self, conn, *, parent_branch_uuid, excluded_refs, replay_balances):
        return self._recovery_branch_compensation_plan_locked_with_rate(
            conn,
            parent_branch_uuid=parent_branch_uuid,
            excluded_refs=excluded_refs,
            replay_balances=replay_balances,
            compensation_rate_bps=10000,
        )

    def _recovery_branch_compensation_plan_locked_with_rate(self, conn, *, parent_branch_uuid, excluded_refs, replay_balances, compensation_rate_bps):
        rate_bps = max(0, min(10000, int(compensation_rate_bps or 0)))
        items = []
        gross_total = 0
        for address, balance in sorted((replay_balances or {}).items()):
            balance = int(balance or 0)
            if balance >= 0 or not WALLET_ADDRESS_RE.fullmatch(address):
                continue
            owner = self._wallet_identity_owner_for_address(conn, address)
            if not owner or not owner["user_id"]:
                continue
            gross = abs(balance)
            amount = (gross * rate_bps + 9999) // 10000 if rate_bps else 0
            gross_total += gross
            items.append({
                "wallet_address": address,
                "user_id": int(owner["user_id"]),
                "gross_shortfall_points": gross,
                "shortfall_points": amount,
                "compensation_rate_bps": rate_bps,
                "post_replay_balance_before_compensation": balance,
                "reason": "successor_transactions_preserved_after_incident_exclusion",
            })
        return {
            "strategy": "treasury_compensation",
            "gross_shortfall_total": gross_total,
            "required_total": sum(int(item["shortfall_points"]) for item in items),
            "item_count": len(items),
            "items": items,
            "excluded_transactions": sorted({str(item or "").strip() for item in (excluded_refs or []) if str(item or "").strip()}),
            "note": "successor transactions stay replayed; official treasury compensates incident sender shortfall",
        }

    def _recovery_branch_tainted_remainder_plan_locked(self, conn, *, parent_branch_uuid, incident_tx_hash="", incident_tx_hashes=None, replay_balances, victim_claims=None):
        incident_refs = {
            str(item or "").strip()
            for item in ([incident_tx_hash] + list(incident_tx_hashes or []))
            if str(item or "").strip()
        }
        if not incident_refs:
            return {"strategy": "tainted_remainder_return", "return_amount": 0, "items": [], "item_count": 0}
        rows = conn.execute(
            """
            SELECT * FROM points_ledger
            WHERE status='confirmed' AND chain_branch=?
            ORDER BY id ASC
            """,
            (str(parent_branch_uuid or self._main_branch_uuid()),),
        ).fetchall()
        incident_rows = [
            row for row in rows
            if incident_refs.intersection({
                str(row["ledger_uuid"] or ""),
                str(row["ledger_hash"] or ""),
                str(row["reference_id"] or ""),
            })
        ]
        incident_out_ids = set()
        tainted_remaining_by_wallet = {}
        stolen_by_victim = {}
        tainted_sources = []
        for row in incident_rows:
            flow = self._ledger_wallet_flow_for_read(conn, row)
            direction = str(row["direction"] or "")
            if direction == "transfer_out":
                source_address = str(flow.get("source_wallet_address") or "").strip().lower()
                destination_address = str(flow.get("destination_wallet_address") or "").strip().lower()
                amount = int(row["amount"] or 0)
                if source_address and destination_address and amount > 0:
                    incident_out_ids.add(int(row["id"] or 0))
                    stolen_by_victim[source_address] = int(stolen_by_victim.get(source_address, 0) or 0) + amount
                    tainted_remaining_by_wallet[destination_address] = int(tainted_remaining_by_wallet.get(destination_address, 0) or 0) + amount
                    tainted_sources.append({
                        "incident_tx_hash": str(row["ledger_hash"] or row["reference_id"] or row["ledger_uuid"] or ""),
                        "ledger_uuid": str(row["ledger_uuid"] or ""),
                        "victim_wallet_address": source_address,
                        "tainted_wallet_address": destination_address,
                        "stolen_amount_points": amount,
                        "ledger_row_id": int(row["id"] or 0),
                    })
        if not tainted_sources:
            return {
                "strategy": "tainted_remainder_return",
                "return_amount": 0,
                "items": [],
                "item_count": 0,
                "incident_tx_hashes": sorted(incident_refs),
                "reason": "incident transfer flow could not be identified",
            }
        payload_claims = self._normalize_recovery_claims(victim_claims=victim_claims or [])
        approved_claims = [claim for claim in payload_claims if claim.get("review_status") == "approved"]
        spent_by_tainted_wallet = {address: 0 for address in tainted_remaining_by_wallet.keys()}
        for row in rows:
            flow = self._ledger_wallet_flow_for_read(conn, row)
            direction = str(row["direction"] or "")
            if direction == "transfer_out" and int(row["id"] or 0) in incident_out_ids:
                continue
            source = str(flow.get("source_wallet_address") or "").strip().lower()
            if source not in tainted_remaining_by_wallet:
                continue
            if direction in {"transfer_out", "debit", "reverse", "freeze"}:
                spent = min(int(tainted_remaining_by_wallet.get(source, 0) or 0), int(row["amount"] or 0))
                tainted_remaining_by_wallet[source] = int(tainted_remaining_by_wallet.get(source, 0) or 0) - spent
                spent_by_tainted_wallet[source] = int(spent_by_tainted_wallet.get(source, 0) or 0) + spent
        return_sources = []
        for address, tainted_remaining in sorted(tainted_remaining_by_wallet.items()):
            wallet_balance = int((replay_balances or {}).get(address, 0) or 0)
            return_amount = max(0, min(int(tainted_remaining or 0), wallet_balance))
            if return_amount > 0:
                return_sources.append({
                    "wallet_address": address,
                    "tainted_remaining_points": int(tainted_remaining or 0),
                    "wallet_balance_points": wallet_balance,
                    "return_amount_points": return_amount,
                    "spent_after_incident_points": int(spent_by_tainted_wallet.get(address, 0) or 0),
                })
        return_amount = sum(int(item["return_amount_points"]) for item in return_sources)
        distribution = self._proportional_tainted_remainder_distribution(
            approved_claims=approved_claims,
            return_amount=return_amount,
        )
        stolen_total = sum(int(item["stolen_amount_points"]) for item in tainted_sources)
        item = {
            "incident_tx_hashes": sorted(incident_refs),
            "stolen_amount_points": stolen_total,
            "stolen_by_victim": [{"wallet_address": key, "amount_points": value} for key, value in sorted(stolen_by_victim.items())],
            "tainted_sources": tainted_sources,
            "tainted_wallets": return_sources,
            "return_amount_points": return_amount,
            "loss_absorbed_by_victim_points": max(0, stolen_total - return_amount),
            "successor_transactions_preserved": True,
            "official_treasury_compensation_points": 0,
            "taint_model": "account_level_taint_first_spend_v1",
            "claims_total_points": sum(int(claim["claim_amount_points"]) for claim in approved_claims),
            "approved_claims": approved_claims,
            "rejected_or_pending_claims": [claim for claim in payload_claims if claim.get("review_status") != "approved"],
            "distribution": distribution,
        }
        return {
            "strategy": "tainted_remainder_return",
            "return_amount": return_amount,
            "item_count": len(tainted_sources),
            "items": [item],
            "return_sources": return_sources,
            "distribution": distribution,
            "note": "user-caused losses only return tainted value still left in the attacker wallet; no treasury compensation and no clawback from downstream recipients",
        }

    def _proportional_tainted_remainder_distribution(self, *, approved_claims, return_amount):
        amount = max(0, int(return_amount or 0))
        if amount <= 0:
            return []
        total = sum(max(0, int(claim.get("claim_amount_points") or 0)) for claim in (approved_claims or []))
        if total <= 0:
            return []
        distribution = []
        allocated = 0
        for claim in approved_claims:
            claim_amount = max(0, int(claim.get("claim_amount_points") or 0))
            share = (amount * claim_amount) // total
            allocated += share
            distribution.append({
                "claim_id": claim.get("claim_id") or "",
                "wallet_address": claim.get("wallet_address") or "",
                "claim_amount_points": claim_amount,
                "allocated_points": share,
            })
        remainder = amount - allocated
        if remainder > 0 and distribution:
            order = sorted(
                range(len(distribution)),
                key=lambda idx: (
                    -((amount * int(distribution[idx]["claim_amount_points"])) % total),
                    distribution[idx]["wallet_address"],
                ),
            )
            for idx in order[:remainder]:
                distribution[idx]["allocated_points"] += 1
        return [item for item in distribution if int(item.get("allocated_points") or 0) > 0]

    def _trading_product_exposure_for_addresses_locked(self, conn, addresses):
        normalized = sorted({
            str(address or "").strip().lower()
            for address in (addresses or [])
            if WALLET_ADDRESS_RE.fullmatch(str(address or "").strip().lower())
        })
        if not normalized:
            return {"addresses": [], "orders": [], "spot_positions": [], "margin_positions": [], "bots": [], "summary": {}}
        placeholders = ", ".join("?" for _ in normalized)
        orders = []
        if table_columns(conn, "trading_orders"):
            try:
                orders = [
                    {
                        "order_uuid": row["order_uuid"],
                        "user_id": int(row["user_id"] or 0),
                        "market_symbol": row["market_symbol"],
                        "side": row["side"],
                        "status": row["status"],
                        "funding_mode": row["funding_mode"] if "funding_mode" in row.keys() else "",
                        "source_wallet_address": row["source_wallet_address"] if "source_wallet_address" in row.keys() else "",
                        "chain_frozen_points": int(row["chain_frozen_points"] or 0) if "chain_frozen_points" in row.keys() else 0,
                        "created_at": row["created_at"],
                    }
                    for row in conn.execute(
                        f"""
                        SELECT * FROM trading_orders
                        WHERE lower(source_wallet_address) IN ({placeholders})
                        ORDER BY id DESC LIMIT 100
                        """,
                        tuple(normalized),
                    ).fetchall()
                ]
            except Exception:
                orders = []
        spot_positions = []
        if table_columns(conn, "trading_spot_positions"):
            try:
                rows = conn.execute(
                    "SELECT * FROM trading_spot_positions ORDER BY user_id ASC, market_symbol ASC"
                ).fetchall()
                for row in rows:
                    source = str(row["source_wallet_address"] if "source_wallet_address" in row.keys() else "").strip().lower()
                    funding_sources = _json_loads(row["funding_sources_json"] if "funding_sources_json" in row.keys() else "[]", [])
                    matched_sources = []
                    for item in funding_sources if isinstance(funding_sources, list) else []:
                        if not isinstance(item, dict):
                            continue
                        address = str(item.get("wallet_address") or "").strip().lower()
                        if address in normalized:
                            matched_sources.append(item)
                    taint_status = str(row["taint_status"] if "taint_status" in row.keys() else "").strip().lower()
                    should_use_legacy_source = (
                        "funding_sources_json" not in row.keys()
                        or taint_status in {"source_traced", "under_review", "tainted"}
                    )
                    if source in normalized and not matched_sources and should_use_legacy_source:
                        matched_sources.append({"wallet_address": source, "legacy_position_source": True})
                    if not matched_sources:
                        continue
                    spot_positions.append({
                        "user_id": int(row["user_id"] or 0),
                        "market_symbol": row["market_symbol"],
                        "quantity_units": int(row["quantity_units"] or 0),
                        "locked_quantity_units": int(row["locked_quantity_units"] or 0),
                        "avg_cost_points": row["avg_cost_points"],
                        "source_wallet_address": source,
                        "taint_status": row["taint_status"] if "taint_status" in row.keys() else "unknown",
                        "taint_source_tx_hash": row["taint_source_tx_hash"] if "taint_source_tx_hash" in row.keys() else "",
                        "matched_funding_sources": matched_sources[:20],
                    })
            except Exception:
                spot_positions = []
        margin_refs = {}
        try:
            for row in conn.execute(
                f"""
                SELECT ledger_uuid, reference_id, action_type, amount, public_metadata_json
                FROM points_ledger
                WHERE status='confirmed'
                  AND reference_type='trading_margin_position'
                  AND action_type IN ('trading_margin_collateral_freeze', 'trading_margin_collateral_unfreeze')
                ORDER BY id DESC LIMIT 500
                """
            ).fetchall():
                public_metadata = _json_loads(row["public_metadata_json"], {})
                source = str(public_metadata.get("source_wallet_address") or "").strip().lower()
                if source in normalized and str(row["reference_id"] or ""):
                    margin_refs[str(row["reference_id"])] = {
                        "source_wallet_address": source,
                        "ledger_uuid": row["ledger_uuid"],
                        "action_type": row["action_type"],
                        "amount_points": int(row["amount"] or 0),
                    }
        except Exception:
            margin_refs = {}
        margin_positions = []
        if margin_refs and table_columns(conn, "trading_margin_positions"):
            try:
                ref_placeholders = ", ".join("?" for _ in margin_refs)
                for row in conn.execute(
                    f"""
                    SELECT * FROM trading_margin_positions
                    WHERE position_uuid IN ({ref_placeholders})
                    ORDER BY id DESC LIMIT 100
                    """,
                    tuple(margin_refs.keys()),
                ).fetchall():
                    margin_positions.append({
                        "position_uuid": row["position_uuid"],
                        "user_id": int(row["user_id"] or 0),
                        "market_symbol": row["market_symbol"],
                        "position_type": row["position_type"],
                        "status": row["status"],
                        "collateral_chain_points": int(row["collateral_chain_points"] or 0) if "collateral_chain_points" in row.keys() else 0,
                        "source_trace": margin_refs.get(str(row["position_uuid"] or ""), {}),
                    })
            except Exception:
                margin_positions = []
        bots = []
        if orders and table_columns(conn, "trading_bot_runs") and table_columns(conn, "trading_orders"):
            order_uuids = [item["order_uuid"] for item in orders if item.get("order_uuid")]
            try:
                order_placeholders = ", ".join("?" for _ in order_uuids)
                if order_uuids:
                    bots.extend([
                        {
                            "bot_kind": "trading_bot",
                            "bot_uuid": row["bot_uuid"],
                            "order_uuid": row["order_uuid"],
                            "user_id": int(row["user_id"] or 0),
                            "status": row["status"],
                            "created_at": row["created_at"],
                        }
                        for row in conn.execute(
                            f"""
                            SELECT b.bot_uuid, r.order_uuid, r.user_id, r.status, r.created_at
                            FROM trading_bot_runs r
                            JOIN trading_bots b ON b.id=r.bot_id
                            WHERE r.order_uuid IN ({order_placeholders})
                            ORDER BY r.id DESC LIMIT 100
                            """,
                            tuple(order_uuids),
                        ).fetchall()
                    ])
            except Exception:
                pass
        if orders and table_columns(conn, "trading_grid_orders"):
            order_uuids = [item["order_uuid"] for item in orders if item.get("order_uuid")]
            try:
                order_placeholders = ", ".join("?" for _ in order_uuids)
                if order_uuids:
                    bots.extend([
                        {
                            "bot_kind": "grid_bot",
                            "bot_uuid": row["bot_uuid"],
                            "order_uuid": row["trading_order_uuid"],
                            "grid_order_uuid": row["order_uuid"],
                            "user_id": int(row["user_id"] or 0),
                            "status": row["status"],
                            "created_at": row["created_at"],
                        }
                        for row in conn.execute(
                            f"""
                            SELECT gb.bot_uuid, go.order_uuid, go.trading_order_uuid, go.user_id, go.status, go.created_at
                            FROM trading_grid_orders go
                            JOIN trading_grid_bots gb ON gb.id=go.grid_bot_id
                            WHERE go.trading_order_uuid IN ({order_placeholders})
                            ORDER BY go.id DESC LIMIT 100
                            """,
                            tuple(order_uuids),
                        ).fetchall()
                    ])
            except Exception:
                pass
        return {
            "addresses": normalized,
            "orders": orders,
            "spot_positions": spot_positions,
            "margin_positions": margin_positions,
            "bots": bots,
            "summary": {
                "order_count": len(orders),
                "spot_position_count": len(spot_positions),
                "margin_position_count": len(margin_positions),
                "bot_trace_count": len(bots),
                "lineage_scope": "address_tx_order_position_bot",
            },
        }

    def _seed_recovery_branch_balances_locked(self, conn, *, branch_uuid, parent_branch_uuid, proposal_row, actor=None, override_payload=None):
        payload = override_payload if isinstance(override_payload, dict) else _json_loads(proposal_row["payload_json"], {})
        excluded = set(self._governance_evidence(payload.get("excluded_tx_hashes") or []))
        recovery_strategy = str(payload.get("recovery_strategy") or "treasury_compensation").strip().lower()
        incident_refs = set(self._governance_evidence([proposal_row["incident_tx_hash"], *(payload.get("incident_tx_hashes") or [])]))
        if recovery_strategy == "tainted_remainder_return":
            excluded.difference_update(incident_refs)
        if proposal_row["incident_tx_hash"] and recovery_strategy != "tainted_remainder_return":
            excluded.add(str(proposal_row["incident_tx_hash"]))
        exclude_tainted_descendants = recovery_strategy == "exclude_tainted_descendants"
        replay = self._replay_branch_address_balances_locked(
            conn,
            branch_uuid=parent_branch_uuid or self._main_branch_uuid(),
            excluded_refs=excluded,
            exclude_tainted_descendants=exclude_tainted_descendants,
        )
        replay_balances = dict(replay.get("balances") or {})
        tainted_remainder = {"strategy": recovery_strategy, "return_amount": 0, "items": [], "item_count": 0}
        if recovery_strategy == "tainted_remainder_return":
            tainted_remainder = self._recovery_branch_tainted_remainder_plan_locked(
                conn,
                parent_branch_uuid=parent_branch_uuid or self._main_branch_uuid(),
                incident_tx_hash=proposal_row["incident_tx_hash"],
                incident_tx_hashes=payload.get("incident_tx_hashes") or [],
                replay_balances=replay_balances,
                victim_claims=payload.get("victim_claims") or [],
            )
            for distribution in tainted_remainder.get("distribution") or []:
                source = str(distribution.get("wallet_address") or "").strip().lower()
                amount = int(distribution.get("allocated_points") or 0)
                if amount > 0 and source:
                    replay_balances[source] = int(replay_balances.get(source, 0) or 0) + amount
            for source in tainted_remainder.get("return_sources") or []:
                destination = str(source.get("wallet_address") or "").strip().lower()
                amount = int(source.get("return_amount_points") or 0)
                if amount > 0 and destination:
                    replay_balances[destination] = int(replay_balances.get(destination, 0) or 0) - amount
        compensation_policy = self._recovery_compensation_policy(
            loss_cause=payload.get("loss_cause") or "protocol_fault",
            requested_rate_bps=payload.get("compensation_rate_bps"),
        )
        compensation = self._recovery_branch_compensation_plan_locked_with_rate(
            conn,
            parent_branch_uuid=parent_branch_uuid or self._main_branch_uuid(),
            excluded_refs=excluded,
            replay_balances=replay_balances,
            compensation_rate_bps=compensation_policy["compensation_rate_bps"],
        ) if recovery_strategy == "treasury_compensation" else {
            "required_total": 0,
            "gross_shortfall_total": 0,
            "items": [],
            "item_count": 0,
            "strategy": recovery_strategy,
        }
        compensation["policy"] = compensation_policy
        created = []
        skipped = []
        for address, balance in sorted(replay_balances.items()):
            amount = int(balance or 0)
            if amount <= 0:
                if amount < 0:
                    skipped.append({"address": address, "reason": "negative_replay_balance", "balance": amount})
                continue
            if not WALLET_ADDRESS_RE.fullmatch(address):
                skipped.append({"address": address, "reason": "non_wallet_address", "balance": amount})
                continue
            owner = self._wallet_identity_owner_for_address(conn, address)
            if not owner or not owner["user_id"]:
                skipped.append({"address": address, "reason": "unowned_or_inactive_wallet", "balance": amount})
                continue
            ledger, was_created = self._record_transaction(
                conn,
                user_id=int(owner["user_id"]),
                currency_type=DISPLAY_CURRENCY,
                direction="credit",
                amount=amount,
                action_type="recovery_branch_genesis_credit",
                reference_type="recovery_branch",
                reference_id=branch_uuid,
                idempotency_key=f"recovery_branch_genesis:{branch_uuid}:{address}",
                reason="recovery branch genesis balance",
                    public_metadata={
                        "destination_wallet_address": address,
                        "recovery_branch_uuid": branch_uuid,
                        "parent_branch_uuid": parent_branch_uuid,
                        "excluded_tx_hashes": sorted(excluded),
                        "recovery_model": "branch_isolated_asset_universe_v1",
                        "recovery_strategy": recovery_strategy,
                        "tainted_remainder_return": tainted_remainder,
                    },
                actor=actor,
            )
            append_economy_event(
                conn,
                chain_secret=self.chain_secret,
                event_type="recovery_branch_genesis",
                transaction_type="recovery_branch_genesis_credit",
                source_fund_key="mint",
                destination_fund_key=None,
                destination_address=address,
                amount=amount,
                idempotency_key=f"recovery_branch_economy_genesis:{branch_uuid}:{address}",
                metadata={
                    "ledger_uuid": ledger["ledger_uuid"],
                    "recovery_branch_uuid": branch_uuid,
                    "parent_branch_uuid": parent_branch_uuid,
                    "excluded_tx_hashes": sorted(excluded),
                    "recovery_model": "branch_isolated_asset_universe_v1",
                    "recovery_strategy": recovery_strategy,
                    "tainted_remainder_return": tainted_remainder,
                },
                actor=actor,
                chain_branch=branch_uuid,
            )
            created.append({
                "wallet_address": address,
                "user_id": int(owner["user_id"]),
                "amount_points": amount,
                "ledger_uuid": ledger["ledger_uuid"],
                "created": bool(was_created),
            })
        compensation_created = []
        if recovery_strategy == "treasury_compensation":
            economy = replay_economy_events(
                conn,
                chain_secret=self.chain_secret,
                persist_cache=False,
                chain_branch=branch_uuid,
            )
            treasury_balance = int((economy.get("balances") or {}).get("official_treasury", {}).get("balance") or 0)
            if int(compensation.get("required_total") or 0) > treasury_balance:
                raise ValueError("official treasury balance is insufficient for recovery branch compensation")
            total_compensation = int(compensation.get("required_total") or 0)
            if total_compensation:
                append_economy_event(
                    conn,
                    chain_secret=self.chain_secret,
                    event_type="official_treasury_compensation",
                    transaction_type="recovery_branch_treasury_compensation",
                    source_fund_key="official_treasury",
                    destination_fund_key="burn",
                    amount=total_compensation,
                    idempotency_key=f"recovery_branch_treasury_compensation_event:{branch_uuid}",
                    metadata={
                        "recovery_branch_uuid": branch_uuid,
                        "parent_branch_uuid": parent_branch_uuid,
                        "excluded_tx_hashes": sorted(excluded),
                        "recovery_strategy": recovery_strategy,
                        "compensation_plan": compensation,
                        "settlement": "official_treasury_absorbs_negative_gap_created_by_preserving_successor_transactions",
                    },
                    actor=actor,
                    chain_branch=branch_uuid,
                )
                compensation_created.append({
                    "fund_key": "official_treasury",
                    "amount_points": total_compensation,
                    "destination": "burn",
                    "created": True,
                })
        return {
            "parent_branch_uuid": parent_branch_uuid,
            "branch_uuid": branch_uuid,
            "recovery_strategy": recovery_strategy,
            "excluded_refs": sorted(set(replay.get("excluded_refs") or sorted(excluded))),
            "requested_excluded_refs": sorted(excluded),
            "auto_excluded_refs": list(replay.get("auto_excluded_refs") or []),
            "auto_excluded": list(replay.get("auto_excluded") or []),
            "auto_excluded_count": int(replay.get("auto_excluded_count") or 0),
            "exclusion_iterations": int(replay.get("exclusion_iterations") or 0),
            "replayed_ledger_rows": int(replay.get("ledger_rows") or 0),
            "excluded_ledger_rows": int(replay.get("excluded_rows") or 0),
            "created_count": len(created),
            "created": created,
            "compensation": {
                **compensation,
                "created": compensation_created,
                "created_count": len(compensation_created),
            },
            "tainted_remainder_return": tainted_remainder,
            "skipped": skipped[:50],
            "skipped_count": len(skipped),
            "model": "branch_isolated_asset_universe_v1",
        }

    def execute_governance_proposal(self, *, actor, proposal_uuid):
        self._governance_require_executor(actor)
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            self._governance_begin_immediate(conn)
            row = self._refresh_governance_proposal_locked(conn, proposal_uuid)
            if not row:
                raise ValueError("proposal not found")
            if row["status"] != "passed":
                raise ValueError(f"proposal is {row['status']}; execution requires passed")
            if int(row["root_veto_used"] or 0):
                raise PermissionError("proposal was vetoed by root")
            timelock_until = parse_utc_timestamp(row["timelock_until"])
            if timelock_until and timelock_until > datetime.now(timezone.utc):
                raise ValueError(f"proposal timelock active until {row['timelock_until']}")
            expected_payload_hash = self._governance_execution_payload_hash_for_row(row)
            if row["execution_payload_hash"] != expected_payload_hash:
                raise ValueError("governance execution payload hash mismatch")
            multisig_status = self._governance_multisig_status_locked(conn, row)
            if row["governance_domain"] == "OFFICIAL_TREASURY" and not multisig_status.get("ready"):
                raise PermissionError(
                    f"official treasury multisig threshold not reached ({multisig_status.get('signature_count', 0)}/{multisig_status.get('threshold', 0)})"
                )
            now = utc_now()
            action_type = str(row["action_type"] or "").strip().upper()
            if action_type == "MARK_SCAM":
                address = row["target_wallet_address"]
                if not WALLET_ADDRESS_RE.fullmatch(address):
                    raise ValueError("proposal target wallet address invalid")
                payload = _json_loads(row["payload_json"], {})
                risk_level = str(payload.get("risk_level") or "confirmed_scam")
                label = str(payload.get("label") or "governance_confirmed_scam")
                conn.execute(
                    """
                    INSERT INTO points_chain_address_risk_labels (
                        wallet_address, risk_level, status, label, reason, evidence_json,
                        proposal_uuid, created_at, updated_at
                    ) VALUES (?, ?, 'active', ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(wallet_address)
                    DO UPDATE SET risk_level=excluded.risk_level, status='active',
                                  label=excluded.label, reason=excluded.reason,
                                  evidence_json=excluded.evidence_json,
                                  proposal_uuid=excluded.proposal_uuid,
                                  updated_at=excluded.updated_at, revoked_at=NULL
                    """,
                    (
                        address,
                        risk_level,
                        label[:80],
                        row["reason"],
                        row["evidence_json"],
                        proposal_uuid,
                        now,
                        now,
                    ),
                )
                result = {
                    "action": "address_risk_label_applied",
                    "wallet_address": address,
                    "risk_label": self._address_risk_label_locked(conn, address),
                }
            elif action_type in {"FREEZE_ADDRESS", "UNFREEZE_ADDRESS"}:
                address = row["target_wallet_address"]
                if not WALLET_ADDRESS_RE.fullmatch(address):
                    raise ValueError("proposal target wallet address invalid")
                release = action_type == "UNFREEZE_ADDRESS"
                if release:
                    conn.execute(
                        """
                        UPDATE points_chain_address_freezes
                        SET status='released', release_proposal_uuid=?, updated_at=?, released_at=?
                        WHERE wallet_address=? AND status='active'
                        """,
                        (proposal_uuid, now, now, address),
                    )
                    conn.execute(
                        """
                        UPDATE points_chain_address_provisional_freezes
                        SET status='released', updated_at=?, released_at=?
                        WHERE wallet_address=? AND status='active'
                        """,
                        (now, now, address),
                    )
                    result = {
                        "action": "wallet_address_unfrozen",
                        "wallet_address": address,
                        "ledger_mutation": "forbidden",
                    }
                else:
                    conn.execute(
                        """
                        INSERT INTO points_chain_address_freezes (
                            wallet_address, status, reason, evidence_json, freeze_proposal_uuid,
                            created_at, updated_at
                        ) VALUES (?, 'active', ?, ?, ?, ?, ?)
                        ON CONFLICT(wallet_address)
                        DO UPDATE SET status='active', reason=excluded.reason,
                                      evidence_json=excluded.evidence_json,
                                      freeze_proposal_uuid=excluded.freeze_proposal_uuid,
                                      release_proposal_uuid=NULL,
                                      updated_at=excluded.updated_at,
                                      released_at=NULL
                        """,
                        (address, row["reason"], row["evidence_json"], proposal_uuid, now, now),
                    )
                    conn.execute(
                        """
                        UPDATE points_chain_address_provisional_freezes
                        SET status='released', updated_at=?, released_at=?
                        WHERE wallet_address=? AND status='active'
                        """,
                        (now, now, address),
                    )
                    result = {
                        "action": "wallet_address_frozen",
                        "wallet_address": address,
                        "freeze": self._address_freeze_locked(conn, address),
                        "freeze_model": "block_outgoing_transfers_only",
                        "ledger_mutation": "forbidden",
                    }
            else:
                payload = _json_loads(row["payload_json"], {})
                if action_type in {"ROLLBACK_BRANCH", "HARD_FORK_ACCEPTANCE"}:
                    result = self._activate_recovery_branch_locked(conn, row=row, proposal_uuid=proposal_uuid, now=now)
                elif action_type in {"TREASURY_TRANSFER", "EXCHANGE_FUND_REPLENISH", "CONTEST_REWARD_PAYOUT"}:
                    transfer = self._official_wallet_grant_locked(
                        conn,
                        actor=actor,
                        destination_wallet_address=payload.get("destination_wallet_address") or row["target_wallet_address"],
                        amount=int(row["requested_amount"] or 0),
                        reason=payload.get("memo") or row["reason"],
                        request_uuid=f"governance:{proposal_uuid}:official_transfer",
                    )
                    result = {
                        "action": "official_treasury_transfer_submitted",
                        "transfer": {
                            "created": bool(transfer.get("created")),
                            "transaction_hash": transfer.get("transaction_hash"),
                            "destination_fund_key": transfer.get("destination_fund_key") or "",
                            "destination_unowned": bool(transfer.get("destination_unowned")),
                            "wallet": None,
                            "transaction": transfer.get("transaction"),
                            "warnings": transfer.get("warnings") or [],
                            "notifications": transfer.get("notifications") or {},
                        },
                    }
                elif action_type == "MINT_REQUEST":
                    destination_fund_key = str(payload.get("destination_fund_key") or "official_treasury").strip().lower()
                    if destination_fund_key not in {"official_treasury", "promo_fund", "exchange_fund"}:
                        raise ValueError("mint destination fund is unsupported")
                    event_branch = payload.get("chain_branch") or self._canonical_branch_uuid(conn)
                    policy = bootstrap_economy_layer(
                        conn,
                        chain_secret=self.chain_secret,
                        actor={"role": "system", "id": None},
                        chain_branch=event_branch,
                    )["policy"]
                    self._mint_request_precheck_locked(
                        conn,
                        amount=int(row["requested_amount"] or 0),
                        reference=row["reference"],
                        policy=policy,
                        chain_branch=event_branch,
                        exclude_proposal_uuid=proposal_uuid,
                    )
                    event, created = append_economy_event(
                        conn,
                        chain_secret=self.chain_secret,
                        event_type="mint",
                        transaction_type="governance_mint_request",
                        source_fund_key="mint",
                        destination_fund_key=destination_fund_key,
                        amount=int(row["requested_amount"] or 0),
                        idempotency_key=f"governance_mint_ref:{row['reference'] or proposal_uuid}",
                        metadata={"proposal_uuid": proposal_uuid, "reason": row["reason"], "reference": row["reference"]},
                        actor=actor,
                        chain_branch=event_branch,
                    )
                    result = {
                        "action": "mint_executed",
                        "created": bool(created),
                        "event_uuid": event["event_uuid"],
                        "destination_fund_key": destination_fund_key,
                    }
                elif action_type == "EMERGENCY_LOCKDOWN":
                    safe_mode = self._enter_safe_mode(
                        conn,
                        {
                            "ok": False,
                            "governance_lockdown": True,
                            "proposal_uuid": proposal_uuid,
                            "errors": [{"type": "governance_emergency_lockdown", "severity": "critical", "message": row["reason"]}],
                        },
                        "governance_emergency_lockdown",
                    )
                    result = {"action": "incident_lockdown_entered", "safe_mode": safe_mode}
                elif action_type == "AUTO_BURN_POLICY":
                    result = {
                        "action": "auto_burn_policy_approved",
                        "ledger_mutation": "forbidden",
                        "policy_payload": payload,
                    }
                elif action_type == "TREASURY_SIGNER_CHANGE":
                    result = {
                        "action": "treasury_signer_change_approved",
                        "ledger_mutation": "forbidden",
                        "signer_policy_payload": payload,
                        "note": "RC1 records governance approval and multisig consent; signer identity rotation is applied through wallet identity lifecycle controls.",
                    }
                elif action_type in {"PARAMETER_CHANGE", "FEATURE_ACTIVATION"}:
                    result = {
                        "action": "protocol_policy_approved",
                        "ledger_mutation": "forbidden",
                        "policy_payload": payload,
                    }
                else:
                    raise ValueError("unsupported governance action execution")
            audit = self._append_governance_audit_locked(
                conn,
                proposal_uuid=proposal_uuid,
                event_type="PROPOSAL_EXECUTED",
                actor=actor,
                payload_hash=row["execution_payload_hash"],
                metadata={"result": result, "action_type": action_type, "governance_domain": row["governance_domain"]},
            )
            conn.execute(
                """
                UPDATE points_chain_governance_proposals
                SET status='executed', lifecycle_status='EXECUTED',
                    executed_by=?, executed_at=?, execution_result_json=?,
                    prev_audit_hash=?, audit_hash=?, updated_at=?
                WHERE proposal_uuid=?
                """,
                (
                    int(actor_value(actor, "id")) if actor_value(actor, "id") else None,
                    now,
                    _json_dumps(result),
                    audit["prev_audit_hash"],
                    audit["audit_hash"],
                    now,
                    proposal_uuid,
                ),
            )
            self._audit_log(
                conn,
                "POINTS_CHAIN_GOVERNANCE_PROPOSAL_EXECUTED",
                "critical" if row["governance_domain"] == "EMERGENCY_SECURITY" or action_type in {"ROLLBACK_BRANCH", "HARD_FORK_ACCEPTANCE"} else "warning",
                f"PointsChain governance proposal executed: {action_type}",
                actor=actor,
                metadata={"proposal_uuid": proposal_uuid, "result": result},
            )
            refreshed = conn.execute(
                "SELECT * FROM points_chain_governance_proposals WHERE proposal_uuid=?",
                (proposal_uuid,),
            ).fetchone()
            conn.commit()
            return {"ok": True, "proposal": self._serialize_governance_proposal(conn, refreshed, actor=actor), "result": result}
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _serialize_governance_proposal(self, conn, row, *, actor=None):
        if not row:
            return None
        user_vote = None
        actor_id = int(actor_value(actor, "id") or 0)
        if actor_id:
            vote = conn.execute(
                """
                SELECT vote, reason, updated_at FROM points_chain_governance_votes
                WHERE proposal_uuid=? AND voter_user_id=?
                """,
                (row["proposal_uuid"], actor_id),
            ).fetchone()
            if vote:
                user_vote = {"vote": vote["vote"], "reason": vote["reason"], "updated_at": vote["updated_at"]}
        decisive = int(row["yes_count"] or 0) + int(row["no_count"] or 0)
        approval_units = ((int(row["yes_count"] or 0) * 10000) // decisive) if decisive else 0
        differential_units = ((int(row["yes_count"] or 0) - int(row["no_count"] or 0)) * 10000) // max(1, int(row["eligible_voter_count"] or 0))
        timelock_until = parse_utc_timestamp(row["timelock_until"])
        executable = row["status"] == "passed" and not int(row["root_veto_used"] or 0) and (not timelock_until or timelock_until <= datetime.now(timezone.utc))
        multisig_status = self._governance_multisig_status_locked(conn, row, actor=actor) if row["governance_domain"] == "OFFICIAL_TREASURY" else {"required": False, "ready": True}
        payload = _json_loads(row["payload_json"], {})
        payload_verified = self._governance_execution_payload_hash_for_row(row) == row["execution_payload_hash"]
        votes_cast = int(row["yes_count"] or 0) + int(row["no_count"] or 0) + int(row["abstain_count"] or 0)
        if isinstance(payload.get("official_multisig_policy"), dict):
            payload = {**payload, "official_multisig_policy": multisig_status.get("policy", {})}
        return public_currency_payload({
            "proposal_uuid": row["proposal_uuid"],
            "proposal_id": row["proposal_uuid"],
            "proposal_type": row["proposal_type"],
            "governance_domain": row["governance_domain"],
            "action_type": row["action_type"],
            "lifecycle_status": row["lifecycle_status"],
            "proposal_severity": row["proposal_severity"],
            "sponsor_required": bool(row["sponsor_required"]),
            "sponsor_user_id": row["sponsor_user_id"],
            "sponsor_role": row["sponsor_role"],
            "sponsored_at": row["sponsored_at"],
            "proposal_deposit_points": int(row["proposal_deposit_points"] or 0),
            "proposal_deposit_status": row["proposal_deposit_status"],
            "title": row["title"],
            "description": row["description"],
            "reason": row["reason"],
            "reference": row["reference"],
            "target_wallet_address": row["target_wallet_address"],
            "target_wallet": row["target_wallet_address"],
            "target_address": row["target_address"],
            "target_branch": row["target_branch"],
            "requested_amount": int(row["requested_amount"] or 0),
            "requested_asset": row["requested_asset"],
            "incident_tx_hash": row["incident_tx_hash"],
            "base_block_number": row["base_block_number"],
            "base_block_hash": row["base_block_hash"],
            "payload": payload,
            "evidence": _json_loads(row["evidence_json"], []),
            "evidence_refs": _json_loads(row["evidence_json"], []),
            "impact_scope": row["impact_scope"],
            "risk_summary": row["risk_summary"],
            "opposition_record": row["opposition_record"],
            "eligible_voter_count": int(row["eligible_voter_count"] or 0),
            "quorum_count": int(row["quorum_count"] or 0),
            "quorum_required": int(row["quorum_count"] or 0),
            GOV_QUORUM_RATE_FIELD: int(row[GOV_QUORUM_RATE_FIELD] or 0),
            GOV_PASS_THRESHOLD_RATE_FIELD: int(row[GOV_PASS_THRESHOLD_RATE_FIELD] or 0),
            "yes_threshold": int(row[GOV_YES_THRESHOLD_RATE_FIELD] or row[GOV_PASS_THRESHOLD_RATE_FIELD] or 0),
            GOV_YES_THRESHOLD_RATE_FIELD: int(row[GOV_YES_THRESHOLD_RATE_FIELD] or row[GOV_PASS_THRESHOLD_RATE_FIELD] or 0),
            "vote_differential_required": int(row[GOV_VOTE_DIFFERENTIAL_REQUIRED_RATE_FIELD] or 0),
            GOV_VOTE_DIFFERENTIAL_REQUIRED_RATE_FIELD: int(row[GOV_VOTE_DIFFERENTIAL_REQUIRED_RATE_FIELD] or 0),
            GOV_VOTE_DIFFERENTIAL_RATE_FIELD: differential_units,
            "yes_count": int(row["yes_count"] or 0),
            "no_count": int(row["no_count"] or 0),
            "abstain_count": int(row["abstain_count"] or 0),
            GOV_APPROVAL_RATE_FIELD: approval_units,
            "status": row["status"],
            "voting_starts_at": row["voting_starts_at"],
            "voting_ends_at": row["voting_ends_at"],
            "timelock_until": row["timelock_until"],
            "timelock_ends_at": row["timelock_ends_at"],
            "expires_at": row["expires_at"],
            "root_veto_allowed": bool(row["root_veto_allowed"]),
            "root_veto_used": bool(row["root_veto_used"]),
            "root_vetoed_at": row["root_vetoed_at"],
            "root_veto_reason": row["root_veto_reason"],
            "execution_payload_hash": row["execution_payload_hash"],
            "execution_bundle": {
                "action_type": row["action_type"],
                "governance_domain": row["governance_domain"],
                "target_wallet_address": row["target_wallet_address"],
                "target_address": row["target_address"],
                "target_branch": row["target_branch"],
                "requested_amount": int(row["requested_amount"] or 0),
                "requested_asset": row["requested_asset"],
                "payload_hash": row["execution_payload_hash"],
                "bundle_model": "frozen_execution_bundle_v1",
            },
            "governance_snapshot": {
                "eligible_voter_count": int(row["eligible_voter_count"] or 0),
                "quorum_count": int(row["quorum_count"] or 0),
                GOV_QUORUM_RATE_FIELD: int(row[GOV_QUORUM_RATE_FIELD] or 0),
                GOV_PASS_THRESHOLD_RATE_FIELD: int(row[GOV_PASS_THRESHOLD_RATE_FIELD] or 0),
                GOV_VOTE_DIFFERENTIAL_REQUIRED_RATE_FIELD: int(row[GOV_VOTE_DIFFERENTIAL_REQUIRED_RATE_FIELD] or 0),
                "snapshot_model": "proposal_creation_voter_and_policy_snapshot_v1",
            },
            "multisig": multisig_status,
            "execution_readiness": {
                "quorum_reached": votes_cast >= int(row["quorum_count"] or 0),
                "vote_succeeded": row["status"] == "passed",
                "timelock_finished": not timelock_until or timelock_until <= datetime.now(timezone.utc),
                "payload_verified": payload_verified,
                "root_veto_clear": not int(row["root_veto_used"] or 0),
                "multisig_ready": not multisig_status.get("required") or bool(multisig_status.get("ready")),
            },
            "executable": executable and payload_verified and (not multisig_status.get("required") or bool(multisig_status.get("ready"))),
            "execution_result": _json_loads(row["execution_result_json"], {}),
            "audit_hash": row["audit_hash"],
            "prev_audit_hash": row["prev_audit_hash"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "executed_at": row["executed_at"],
            "user_vote": user_vote,
        })

    def list_governance_proposals(self, *, actor=None, limit=50):
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            self._governance_begin_immediate(conn)
            rows = conn.execute(
                """
                SELECT proposal_uuid
                FROM points_chain_governance_proposals
                ORDER BY id DESC LIMIT ?
                """,
                (min(100, max(1, int(limit or 50))),),
            ).fetchall()
            proposals = []
            for row in rows:
                refreshed = self._refresh_governance_proposal_locked(conn, row["proposal_uuid"])
                proposals.append(self._serialize_governance_proposal(conn, refreshed, actor=actor))
            conn.commit()
            return {"ok": True, "proposals": proposals}
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def official_treasury_signer_center(self, *, actor=None, limit=50):
        if not self._governance_is_manager_actor(actor):
            raise PermissionError("manager+ required to view official treasury signer center")
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            self._governance_begin_immediate(conn)
            branch = self._canonical_branch_uuid(conn)
            layer = economy_layer_report(conn, chain_secret=self.chain_secret, actor=actor, chain_branch=branch)
            funds = layer.get("funds") or {}
            fund_addresses = {
                key: str((dict(value) if value and hasattr(value, "keys") else value or {}).get("address") or "")
                for key, value in funds.items()
                if key in {"mint", "official_treasury", "promo_fund", "exchange_fund", "burn"}
            }
            official_wallet = dict(funds.get("official_treasury") or {})
            official_wallet.update({
                "wallet_type": "official_treasury_multisig",
                "wallet_scope": "official_treasury",
                "custody_mode": "multisig",
                "spend_capability": "enabled",
                "control_model": "governance_vote_then_official_multisig_threshold_v1",
            })
            policy_error = ""
            try:
                policy = self._governance_multisig_policy_locked(conn, fund_key="official_treasury")
            except Exception as exc:
                policy = {
                    "policy_version": "OFFICIAL_TREASURY_MULTISIG_V1",
                    "fund_key": "official_treasury",
                    "threshold": 0,
                    "threshold_weight": 0,
                    "signer_count": 0,
                    "total_weight": 0,
                    "signers": [],
                    "signer_addresses": [],
                    "signature_required_after_governance": True,
                    "wallet_type": "official_treasury_multisig",
                    "wallet_scope": "official_treasury",
                }
                policy_error = str(exc)
            rows = conn.execute(
                """
                SELECT proposal_uuid
                FROM points_chain_governance_proposals
                WHERE governance_domain='OFFICIAL_TREASURY'
                  AND status NOT IN ('executed', 'cancelled', 'expired')
                ORDER BY id DESC
                LIMIT ?
                """,
                (min(100, max(1, int(limit or 50))),),
            ).fetchall()
            proposals = []
            signable = []
            for row in rows:
                refreshed = self._refresh_governance_proposal_locked(conn, row["proposal_uuid"])
                payload = self._serialize_governance_proposal(conn, refreshed, actor=actor)
                proposals.append(payload)
                multisig = payload.get("multisig") if isinstance(payload.get("multisig"), dict) else {}
                if multisig.get("required") and not multisig.get("ready") and payload.get("status") == "passed":
                    signer_address = (multisig.get("policy") or {}).get("current_signer_wallet_address") or ""
                    signable.append({
                        "proposal_uuid": payload.get("proposal_uuid") or "",
                        "action_type": payload.get("action_type") or "",
                        "target_wallet_address": payload.get("target_wallet_address") or "",
                        "requested_amount": int(payload.get("requested_amount") or 0),
                        "timelock_until": payload.get("timelock_until") or "",
                        "execution_payload_hash": payload.get("execution_payload_hash") or "",
                        "current_signer_wallet_address": signer_address,
                        "signature_count": int(multisig.get("signature_count") or 0),
                        "threshold": int(multisig.get("threshold") or 0),
                        "signature_weight": int(multisig.get("signature_weight") or 0),
                        "threshold_weight": int(multisig.get("threshold_weight") or 0),
                        "readiness": payload.get("execution_readiness") or {},
                    })
            conn.commit()
            return {
                "ok": True,
                "official_wallet": official_wallet,
                "fund_addresses": fund_addresses,
                "policy": policy,
                "policy_error": policy_error,
                "pending_proposals": proposals,
                "signable": signable,
                "canonical_branch": branch,
                "rc1_scope": "official_treasury_multisig_only",
                "user_multisig_policy": "receive_only_preview_no_transfer",
            }
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _governance_audit_verify_locked(self, conn, limit=None):
        sql = "SELECT * FROM points_chain_governance_audit_log ORDER BY id ASC"
        rows = conn.execute(sql).fetchall()
        errors = []
        previous = ""
        for row in rows:
            metadata = _json_loads(row["metadata_json"], {})
            payload = {
                "audit_uuid": row["audit_uuid"],
                "proposal_uuid": row["proposal_uuid"],
                "event_type": row["event_type"],
                "actor_user_id": row["actor_user_id"],
                "actor_role": row["actor_role"],
                "payload_hash": row["payload_hash"],
                "metadata": metadata,
                "prev_audit_hash": row["prev_audit_hash"],
                "created_at": row["created_at"],
            }
            expected = sha256_text(canonical_json(payload))
            if row["prev_audit_hash"] != previous:
                errors.append({"type": "governance_audit_previous_hash", "audit_uuid": row["audit_uuid"], "expected": previous, "actual": row["prev_audit_hash"]})
            if row["audit_hash"] != expected:
                errors.append({"type": "governance_audit_hash", "audit_uuid": row["audit_uuid"], "expected": expected, "actual": row["audit_hash"]})
            previous = row["audit_hash"]
            if limit and len(errors) >= int(limit):
                break
        return {"ok": not errors, "event_count": len(rows), "error_count": len(errors), "errors": errors[:100], "head_hash": previous}

    def verify_governance_audit(self):
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            return self._governance_audit_verify_locked(conn)
        finally:
            conn.close()

    def _governance_branch_tree_locked(self, conn, branch_rows):
        rows = list(branch_rows or [])
        active_branch = self._canonical_branch_uuid(conn)
        node_map = {}
        for row in rows:
            replay_plan = _json_loads(row["replay_plan_json"], {})
            branch_uuid = str(row["branch_uuid"] or self._main_branch_uuid())
            node_map[branch_uuid] = {
                "branch_uuid": branch_uuid,
                "proposal_uuid": row["proposal_uuid"],
                "parent_branch_uuid": row["parent_branch_uuid"],
                "branch_name": row["branch_name"],
                "base_block_number": row["base_block_number"],
                "base_block_hash": row["base_block_hash"],
                "incident_tx_hash": row["incident_tx_hash"],
                "status": row["status"],
                "is_canonical": bool(row["is_canonical"]),
                "write_enabled": bool(row["write_enabled"]) if "write_enabled" in row.keys() else bool(row["is_canonical"]),
                "recovery_type": row["recovery_type"] if "recovery_type" in row.keys() else "canonical_pointer_only",
                "replay_plan": replay_plan,
                "created_at": row["created_at"],
                "activated_at": row["activated_at"],
            }
        if self._main_branch_uuid() not in node_map:
            main_meta = self._branch_metadata(conn, self._main_branch_uuid())
            node_map[self._main_branch_uuid()] = {
                "branch_uuid": self._main_branch_uuid(),
                "proposal_uuid": "",
                "parent_branch_uuid": "",
                "branch_name": "main",
                "base_block_number": None,
                "base_block_hash": "",
                "incident_tx_hash": "",
                "status": main_meta.get("status") or ("canonical_main" if active_branch == self._main_branch_uuid() else "read_only_archived"),
                "is_canonical": active_branch == self._main_branch_uuid(),
                "write_enabled": bool(main_meta.get("write_enabled", active_branch == self._main_branch_uuid())),
                "recovery_type": main_meta.get("recovery_type") or "canonical_pointer_only",
                "replay_plan": {"asset_universe": "main"},
                "created_at": "",
                "activated_at": "",
            }

        ledger_stats = {
            row["chain_branch"]: dict(row)
            for row in conn.execute(
                """
                SELECT chain_branch,
                       COUNT(*) AS ledger_count,
                       COALESCE(SUM(CASE WHEN chain_block_id IS NULL THEN 1 ELSE 0 END), 0) AS unsealed_ledger_count,
                       COUNT(DISTINCT chain_block_id) AS sealed_block_count,
                       MIN(created_at) AS first_ledger_at,
                       MAX(created_at) AS latest_ledger_at
                FROM points_ledger
                WHERE status='confirmed'
                GROUP BY chain_branch
                """
            ).fetchall()
        }
        economy_stats = {
            row["chain_branch"]: dict(row)
            for row in conn.execute(
                """
                SELECT chain_branch,
                       COUNT(*) AS economy_event_count,
                       MIN(created_at) AS first_economy_event_at,
                       MAX(created_at) AS latest_economy_event_at
                FROM points_economy_events
                WHERE status='confirmed'
                GROUP BY chain_branch
                """
            ).fetchall()
        }
        child_map = {branch_uuid: [] for branch_uuid in node_map}
        for branch_uuid, node in node_map.items():
            parent = str(node.get("parent_branch_uuid") or "")
            if parent and parent in child_map and branch_uuid != parent:
                child_map[parent].append(branch_uuid)

        def depth_for(branch_uuid, seen=None):
            seen = set(seen or set())
            if branch_uuid in seen:
                return 0
            seen.add(branch_uuid)
            parent = str((node_map.get(branch_uuid) or {}).get("parent_branch_uuid") or "")
            if not parent or parent not in node_map:
                return 0
            return 1 + depth_for(parent, seen)

        nodes = []
        for branch_uuid, node in node_map.items():
            ledger = ledger_stats.get(branch_uuid) or {}
            economy = economy_stats.get(branch_uuid) or {}
            replay_plan = node.get("replay_plan") if isinstance(node.get("replay_plan"), dict) else {}
            status = str(node.get("status") or "")
            is_canonical = branch_uuid == active_branch or bool(node.get("is_canonical"))
            write_enabled = bool(node.get("write_enabled"))
            has_incident = bool(node.get("incident_tx_hash") or node.get("proposal_uuid") or replay_plan.get("selected_recovery_strategy") or replay_plan.get("recovery_strategy"))
            archived = not is_canonical and not write_enabled
            node_state = "canonical_write" if is_canonical and write_enabled else ("canonical_read_only" if is_canonical else ("archived" if archived else status or "branch"))
            children = sorted(child_map.get(branch_uuid) or [])
            nodes.append({
                **node,
                "is_canonical": is_canonical,
                "write_enabled": write_enabled,
                "depth": depth_for(branch_uuid),
                "node_state": node_state,
                "child_branch_uuids": children,
                "children_count": len(children),
                "ledger_count": int(ledger.get("ledger_count") or 0),
                "unsealed_ledger_count": int(ledger.get("unsealed_ledger_count") or 0),
                "sealed_block_count": int(ledger.get("sealed_block_count") or 0),
                "first_ledger_at": ledger.get("first_ledger_at") or "",
                "latest_ledger_at": ledger.get("latest_ledger_at") or "",
                "economy_event_count": int(economy.get("economy_event_count") or 0),
                "first_economy_event_at": economy.get("first_economy_event_at") or "",
                "latest_economy_event_at": economy.get("latest_economy_event_at") or "",
                "has_incident": has_incident,
                "auto_collapsed": bool(archived and not is_canonical),
            })
        nodes.sort(key=lambda item: (int(item.get("depth") or 0), item.get("created_at") or "", item["branch_uuid"]))
        return {
            "canonical_branch_uuid": active_branch,
            "root_branch_uuid": self._main_branch_uuid(),
            "node_count": len(nodes),
            "archived_count": sum(1 for item in nodes if not item.get("is_canonical")),
            "write_enabled_count": sum(1 for item in nodes if item.get("write_enabled")),
            "nodes": nodes,
        }

    def _governance_report_locked(self, conn):
        proposals = conn.execute(
            """
            SELECT * FROM points_chain_governance_proposals
            ORDER BY id DESC LIMIT 10
            """
        ).fetchall()
        labels = conn.execute(
            """
            SELECT * FROM points_chain_address_risk_labels
            WHERE status='active'
            ORDER BY updated_at DESC LIMIT 20
            """
        ).fetchall()
        freezes = conn.execute(
            """
            SELECT * FROM points_chain_address_freezes
            WHERE status='active'
            ORDER BY updated_at DESC LIMIT 20
            """
        ).fetchall()
        provisional_freezes = conn.execute(
            """
            SELECT * FROM points_chain_address_provisional_freezes
            WHERE status='active'
            ORDER BY updated_at DESC LIMIT 20
            """
        ).fetchall()
        branch_rows = conn.execute(
            """
            SELECT * FROM points_chain_governance_branches
            ORDER BY id ASC LIMIT 100
            """
        ).fetchall()
        branches = list(reversed(branch_rows[-10:]))
        audit_rows = conn.execute(
            """
            SELECT * FROM points_chain_governance_audit_log
            ORDER BY id DESC LIMIT 20
            """
        ).fetchall()
        return {
            "proposals": [self._serialize_governance_proposal(conn, row) for row in proposals],
            "active_risk_labels": [self._address_risk_label_locked(conn, row["wallet_address"]) for row in labels],
            "active_freezes": [self._address_freeze_locked(conn, row["wallet_address"]) for row in freezes],
            "active_provisional_freezes": [self._address_provisional_freeze_locked(conn, row["wallet_address"]) for row in provisional_freezes],
            "audit_verify": self._governance_audit_verify_locked(conn),
            "audit_events": [
                {
                    "audit_uuid": row["audit_uuid"],
                    "proposal_uuid": row["proposal_uuid"],
                    "event_type": row["event_type"],
                    "actor_user_id": row["actor_user_id"],
                    "actor_role": row["actor_role"],
                    "payload_hash": row["payload_hash"],
                    "prev_audit_hash": row["prev_audit_hash"],
                    "audit_hash": row["audit_hash"],
                    "created_at": row["created_at"],
                }
                for row in audit_rows
            ],
            "branches": [
                {
                    "branch_uuid": row["branch_uuid"],
                    "proposal_uuid": row["proposal_uuid"],
                    "parent_branch_uuid": row["parent_branch_uuid"],
                    "branch_name": row["branch_name"],
                    "base_block_number": row["base_block_number"],
                    "base_block_hash": row["base_block_hash"],
                    "incident_tx_hash": row["incident_tx_hash"],
                    "status": row["status"],
                    "is_canonical": bool(row["is_canonical"]),
                    "write_enabled": bool(row["write_enabled"]) if "write_enabled" in row.keys() else bool(row["is_canonical"]),
                    "recovery_type": row["recovery_type"] if "recovery_type" in row.keys() else "canonical_pointer_only",
                    "replay_plan": _json_loads(row["replay_plan_json"], {}),
                    "created_at": row["created_at"],
                    "activated_at": row["activated_at"],
                }
                for row in branches
            ],
            "branch_tree": self._governance_branch_tree_locked(conn, branch_rows),
        }

    def ensure_wallet(self, conn, user_id):
        user_id = int(user_id)
        row = conn.execute("SELECT * FROM points_wallets WHERE user_id=?", (user_id,)).fetchone()
        if row:
            return row
        now = utc_now()
        with self._wallet_lock:
            row = conn.execute("SELECT * FROM points_wallets WHERE user_id=?", (user_id,)).fetchone()
            if row:
                return row
            conn.execute(
                """
                INSERT OR IGNORE INTO points_wallets (user_id, created_at, updated_at)
                VALUES (?, ?, ?)
                """,
                (user_id, now, now),
            )
            return conn.execute("SELECT * FROM points_wallets WHERE user_id=?", (user_id,)).fetchone()

    def wallet_payload_for_read(self, conn, user_id):
        user_id = int(user_id)
        row = conn.execute("SELECT * FROM points_wallets WHERE user_id=?", (user_id,)).fetchone()
        if row:
            payload = self.serialize_wallet(row)
        else:
            payload = {
                "user_id": user_id,
                "public_account_id": self._public_account_id(user_id),
                "currency_type": DISPLAY_CURRENCY,
                "points_balance": 0,
                "points_frozen": 0,
                "total_points_earned": 0,
                "total_points_spent": 0,
                "soft_balance": 0,
                "hard_balance": 0,
                "soft_frozen": 0,
                "hard_frozen": 0,
                "wallet_status": "active",
                "risk_level": "normal",
                "created_at": None,
                "updated_at": None,
            }
        statement = self._wallet_statement_totals_for_user(conn, user_id)
        active_branch = self._canonical_branch_uuid(conn)
        payload["chain_branch"] = active_branch
        payload["branch"] = self._branch_metadata(conn, active_branch)
        payload["total_points_earned"] = int(statement["earned"])
        payload["total_points_spent"] = int(statement["spent"])
        payload["total_soft_earned"] = int(statement["earned"])
        payload["total_soft_spent"] = int(statement["spent"])
        payload["total_hard_earned"] = 0
        payload["total_hard_spent"] = 0
        identity_balances = self._wallet_identity_balances_for_user(conn, user_id)
        payload["account_points_balance"] = int(payload.get("points_balance") or 0)
        payload["account_points_frozen"] = int(payload.get("points_frozen") or 0)
        payload["active_wallet_address"] = identity_balances.get("primary_address") or ""
        payload["wallet_identity_source"] = "legacy_account"
        if identity_balances.get("has_identity"):
            active_address = identity_balances.get("primary_address") or ""
            active = (identity_balances.get("balances") or {}).get(active_address, {"balance": 0, "frozen": 0})
            active_balance = int(active.get("balance") or 0)
            active_frozen = int(active.get("frozen") or 0)
            account_balance = sum(int(item.get("balance") or 0) for item in (identity_balances.get("balances") or {}).values())
            account_frozen = sum(int(item.get("frozen") or 0) for item in (identity_balances.get("balances") or {}).values())
            payload["account_points_balance"] = account_balance
            payload["account_points_frozen"] = account_frozen
            payload["points_balance"] = active_balance
            payload["points_frozen"] = active_frozen
            payload["soft_balance"] = active_balance
            payload["soft_frozen"] = active_frozen
            payload["hard_balance"] = 0
            payload["hard_frozen"] = 0
            payload["wallet_identity_source"] = "active_wallet" if active_address else "no_active_wallet"
            payload["wallet_identity_balances"] = {
                address: {
                    "points_balance": int(item.get("balance") or 0),
                    "points_frozen": int(item.get("frozen") or 0),
                    "pending_outgoing_points": int(item.get("pending_outgoing") or 0),
                }
                for address, item in sorted((identity_balances.get("balances") or {}).items())
            }
        return payload

    def get_wallet(self, user_id):
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            wallet = self.ensure_wallet(conn, user_id)
            conn.commit()
            return self.wallet_payload_for_read(conn, user_id)
        finally:
            conn.close()

    def wallet_creation_fee_quote_for_count(self, wallet_count):
        count = max(0, int(wallet_count or 0))
        if count <= 0:
            amount = 0
        else:
            amount = WALLET_CREATION_FEE_BASE_POINTS * (WALLET_CREATION_FEE_MULTIPLIER ** (count - 1))
            amount = min(amount, WALLET_CREATION_FEE_MAX_POINTS)
        next_wallet_number = count + 1
        return {
            "item_key": "wallet_creation_fee",
            "amount_points": int(amount),
            "currency_type": DISPLAY_CURRENCY,
            "existing_wallet_count": count,
            "next_wallet_number": next_wallet_number,
            "base_points": WALLET_CREATION_FEE_BASE_POINTS,
            "multiplier": WALLET_CREATION_FEE_MULTIPLIER,
            "max_points": WALLET_CREATION_FEE_MAX_POINTS,
            "destination_fund_key": "official_treasury",
            "reference_type": "wallet_identity",
            "reference_id": f"wallet_identity:create:{next_wallet_number}",
            "formula": "first wallet free; nth paid wallet = min(base * multiplier^(existing_wallet_count - 1), max)",
        }

    def wallet_creation_fee_quote(self, conn, user_id):
        row = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM points_wallet_identities
            WHERE user_id=? AND status IN ('pending_backup', 'active')
            """,
            (int(user_id),),
        ).fetchone()
        return self.wallet_creation_fee_quote_for_count(int((row["count"] if row else 0) or 0))

    def charge_wallet_creation_fee_locked(
        self,
        conn,
        *,
        user_id,
        source_wallet_address,
        request_uuid,
        signature="",
        wallet_count_before,
        amount_points=None,
        mode="wallet",
        actor=None,
    ):
        quote = self.wallet_creation_fee_quote_for_count(wallet_count_before)
        expected_amount = int(quote["amount_points"])
        if expected_amount <= 0:
            return {"charged": False, "amount_points": 0, "quote": quote, "ledger": None}
        if amount_points is not None and int(amount_points) != expected_amount:
            raise ValueError("wallet creation fee quote changed; refresh wallet management before retrying")
        source_address = str(source_wallet_address or "").strip().lower()
        if not source_address:
            raise ValueError("creating a second or later wallet requires a fee source wallet")
        if not request_uuid:
            raise ValueError("wallet creation fee request_uuid is required")
        source_wallet = self._wallet_identity_row_for_user_address(conn, user_id, source_address, active_only=True)
        if not source_wallet:
            raise ValueError("fee source wallet does not belong to current user or is inactive")
        self._assert_wallet_identity_can_spend(source_wallet, context="wallet creation fee")
        custody_mode = str(source_wallet["custody_mode"] or "")
        if custody_mode == "multisig":
            raise PermissionError("multisig fee source requires a multisig payment flow; choose a hot or self-custody wallet")
        if custody_mode == "self_custody":
            self._verify_service_fee_wallet_signature(
                conn=conn,
                user_id=user_id,
                source_wallet_address=source_address,
                item_key=quote["item_key"],
                quantity=1,
                amount_points=expected_amount,
                request_uuid=request_uuid,
                reference_type=quote["reference_type"],
                reference_id=quote["reference_id"],
                signature=signature,
            )
        available = self._wallet_identity_available_for_address(conn, user_id=int(user_id), address=source_address)
        if available < expected_amount:
            raise ValueError("insufficient balance for wallet creation fee")
        row, created = self._record_transaction(
            conn,
            user_id=user_id,
            currency_type=DISPLAY_CURRENCY,
            direction="debit",
            amount=expected_amount,
            action_type="wallet_creation_fee",
            reference_type=quote["reference_type"],
            reference_id=quote["reference_id"],
            idempotency_key=f"wallet_creation_fee:{request_uuid}",
            reason=f"wallet creation fee for {mode}",
            public_metadata={
                "source_wallet_address": source_address,
                "wallet_creation_fee": True,
                "creation_mode": str(mode or "wallet"),
                "existing_wallet_count": int(wallet_count_before or 0),
                "next_wallet_number": int(quote["next_wallet_number"]),
                "destination_fund_key": "official_treasury",
            },
            actor=actor,
        )
        return {
            "charged": bool(created),
            "amount_points": expected_amount,
            "quote": quote,
            "ledger": self.serialize_ledger(row),
        }

    def serialize_wallet(self, row):
        if not row:
            return None
        points_balance = int(row["soft_balance"] or 0) + int(row["hard_balance"] or 0)
        points_frozen = int(row["soft_frozen"] or 0) + int(row["hard_frozen"] or 0)
        total_points_earned = int(row["total_soft_earned"] or 0) + int(row["total_hard_earned"] or 0)
        total_points_spent = int(row["total_soft_spent"] or 0) + int(row["total_hard_spent"] or 0)
        return {
            "user_id": row["user_id"],
            "public_account_id": self._public_account_id(row["user_id"]),
            "currency_type": DISPLAY_CURRENCY,
            "points_balance": points_balance,
            "points_frozen": points_frozen,
            "total_points_earned": total_points_earned,
            "total_points_spent": total_points_spent,
            "soft_balance": points_balance,
            "hard_balance": 0,
            "soft_frozen": points_frozen,
            "hard_frozen": 0,
            "total_soft_earned": total_points_earned,
            "total_hard_earned": 0,
            "total_soft_spent": total_points_spent,
            "total_hard_spent": 0,
            "wallet_status": row["wallet_status"],
            "risk_level": row["risk_level"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def serialize_ledger(self, row, *, include_user_id=False):
        data = {
            "id": row["id"],
            "ledger_uuid": row["ledger_uuid"],
            "chain_branch": row["chain_branch"] if "chain_branch" in row.keys() else "main",
            "public_account_id": row["public_account_id"],
            "currency_type": display_currency_type(row["currency_type"]),
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

    def _primary_wallet_address_for_read(self, conn, user_id):
        try:
            row = conn.execute(
                """
                SELECT address FROM points_wallet_identities
                WHERE user_id=? AND is_primary=1 AND status IN ('pending_backup', 'active')
                ORDER BY id DESC
                LIMIT 1
                """,
                (int(user_id),),
            ).fetchone()
            return row["address"] if row else ""
        except Exception:
            return ""

    def _active_wallet_identity_for_user(self, conn, user_id):
        try:
            return conn.execute(
                """
                SELECT * FROM points_wallet_identities
                WHERE user_id=? AND is_primary=1 AND status='active'
                ORDER BY id DESC
                LIMIT 1
                """,
                (int(user_id),),
            ).fetchone()
        except Exception:
            return None

    def _initial_grant_entitlement_for_user(self, conn, user_id):
        cols = table_columns(conn, "users")
        if "id" not in cols or "username" not in cols or "role" not in cols:
            return None
        status_expr = "COALESCE(status, 'active')" if "status" in cols else "'active'"
        row = conn.execute(
            f"""
            SELECT id, username, role, {status_expr} AS status
            FROM users
            WHERE id=?
            LIMIT 1
            """,
            (int(user_id),),
        ).fetchone()
        if not row or str(row["status"] or "active") != "active" or str(row["username"] or "") == "root":
            return None
        role = str(row["role"] or "user")
        if role in {"manager", "super_admin"}:
            return {
                "grant": "admin_initial",
                "action_type": "admin_initial_grant",
                "amount": ADMIN_INITIAL_POINTS,
                "reference_type": "genesis_admin_allocation",
                "reason": "admin genesis allocation",
                "public_metadata": {"grant": "admin_initial", "amount": ADMIN_INITIAL_POINTS},
            }
        return {
            "grant": "user_initial",
            "action_type": "user_initial_grant",
            "amount": USER_INITIAL_POINTS,
            "reference_type": "genesis_user_allocation",
            "reason": "user genesis allocation",
            "public_metadata": {"grant": "user_initial", "amount": USER_INITIAL_POINTS},
        }

    def wallet_initial_grant_status(self, conn, user_id):
        entitlement = self._initial_grant_entitlement_for_user(conn, user_id)
        if not entitlement:
            return {
                "required": False,
                "granted": False,
                "deferred_until_wallet": False,
                "grant": "",
                "action_type": "",
                "amount": 0,
                "active_wallet_address": "",
                "ledger_uuid": "",
                "ledger_hash": "",
            }
        existing = conn.execute(
            """
            SELECT ledger_uuid, ledger_hash, created_at
            FROM points_ledger
            WHERE user_id=? AND action_type=?
            ORDER BY id ASC
            LIMIT 1
            """,
            (int(user_id), entitlement["action_type"]),
        ).fetchone()
        active_wallet = self._active_wallet_identity_for_user(conn, user_id)
        granted = bool(existing)
        return {
            "required": not granted,
            "granted": granted,
            "deferred_until_wallet": (not granted and not bool(active_wallet)),
            "grant": entitlement["grant"],
            "action_type": entitlement["action_type"],
            "amount": int(entitlement["amount"]),
            "active_wallet_address": active_wallet["address"] if active_wallet else "",
            "ledger_uuid": existing["ledger_uuid"] if existing else "",
            "ledger_hash": existing["ledger_hash"] if existing else "",
            "created_at": existing["created_at"] if existing else "",
        }

    def _deferred_initial_grant_result(self, conn, user_id, status):
        return {
            "ok": True,
            "created": False,
            "deferred": True,
            "reason": "wallet_required",
            "initial_grant": status,
            "ledger": None,
            "wallet": self.wallet_payload_for_read(conn, user_id),
        }

    def _initial_grant_ready_or_deferred(self, *, user_id, expected_action_type, require_wallet=True):
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            status = self.wallet_initial_grant_status(conn, user_id)
            if status.get("action_type") != expected_action_type:
                return {
                    "ok": True,
                    "created": False,
                    "deferred": False,
                    "not_applicable": True,
                    "initial_grant": status,
                    "ledger": None,
                    "wallet": self.wallet_payload_for_read(conn, user_id),
                }
            if require_wallet and status.get("deferred_until_wallet"):
                return self._deferred_initial_grant_result(conn, user_id, status)
            return None
        finally:
            conn.close()

    def _wallet_identity_row_for_user_address(self, conn, user_id, address, *, active_only=True):
        address = str(address or "").strip().lower()
        if not address:
            return None
        status_filter = "AND status IN ('pending_backup', 'active')" if active_only else ""
        try:
            return conn.execute(
                f"""
                SELECT * FROM points_wallet_identities
                WHERE user_id=? AND address=?
                {status_filter}
                LIMIT 1
                """,
                (int(user_id), address),
            ).fetchone()
        except Exception:
            return None

    def _wallet_address_for_user_flow(self, conn, user_id, preferred_address=None):
        preferred = self._wallet_identity_row_for_user_address(conn, user_id, preferred_address, active_only=True)
        if preferred_address and not preferred:
            raise ValueError("wallet address does not belong to user or is inactive")
        address = preferred["address"] if preferred else self._primary_wallet_address_for_read(conn, user_id)
        legacy_account = self._public_account_id(user_id)
        return address or legacy_account, ("用戶模擬鏈錢包" if address else "Legacy 帳本身份"), address, legacy_account

    def _wallet_identity_state_for_user(self, conn, user_id):
        try:
            rows = conn.execute(
                """
                SELECT * FROM points_wallet_identities
                WHERE user_id=?
                ORDER BY id ASC
                """,
                (int(user_id),),
            ).fetchall()
        except Exception:
            return {"has_identity": False, "primary": None, "addresses": set()}
        has_identity_history = bool(rows)
        if not has_identity_history:
            try:
                has_identity_history = bool(conn.execute(
                    """
                    SELECT 1 FROM points_wallet_onboarding_events
                    WHERE user_id=?
                    LIMIT 1
                    """,
                    (int(user_id),),
                ).fetchone())
            except Exception:
                has_identity_history = False
        primary = None
        addresses = set()
        for row in rows:
            status = str(row["status"] or "")
            address = str(row["address"] or "")
            if address and status in {"pending_backup", "active"}:
                addresses.add(address)
            if int(row["is_primary"] or 0) and status in {"pending_backup", "active"}:
                primary = row
        return {"has_identity": has_identity_history, "primary": primary, "addresses": addresses}

    def _legacy_counterparty_account(self, value):
        try:
            return self._public_account_id(int(value))
        except Exception:
            return ""

    def _legacy_ledger_wallet_flow_descriptor(self, conn, row, public_metadata=None):
        public_metadata = public_metadata if isinstance(public_metadata, dict) else {}
        direction = str(row["direction"] or "")
        action_type = str(row["action_type"] or "")
        user_address = row["public_account_id"] or self._public_account_id(row["user_id"])
        user_label = "Legacy 帳本身份"
        legacy_account = user_address
        if direction in {"credit", "transfer_in"}:
            source_address = ""
            source_label = ""
            source_fund_key = self._points_ledger_credit_source_fund(action_type)
            if action_type == "video_tip_credit":
                source_address = self._legacy_counterparty_account(public_metadata.get("from_user_id"))
                source_label = "打賞付款帳本身份"
                source_fund_key = None
            elif action_type == "video_tip_platform_fee":
                source_address = self._legacy_counterparty_account(public_metadata.get("from_user_id"))
                source_label = "平台費付款帳本身份"
                source_fund_key = None
            if source_fund_key:
                source_label, source_address = self._economy_fund_flow_ref(source_fund_key)
            walletized = bool(source_fund_key or source_address)
            return {
                "source_fund_key": source_fund_key,
                "destination_fund_key": None,
                "source_label": source_label or "來源帳本身份",
                "source_wallet_address": source_address,
                "destination_label": user_label,
                "destination_wallet_address": user_address,
                "target_wallet_address": "",
                "legacy_public_account_id": legacy_account,
                "walletized": walletized,
                "walletization_note": "legacy row without immutable wallet-flow snapshot",
            }
        if direction in {"debit", "transfer_out", "reverse"}:
            destination_address = ""
            destination_label = ""
            destination_fund_key = self._points_ledger_debit_destination_fund(action_type)
            if action_type == "video_tip_debit":
                destination_address = self._legacy_counterparty_account(public_metadata.get("to_user_id"))
                destination_label = "打賞收款帳本身份"
            if destination_fund_key:
                destination_label, destination_address = self._economy_fund_flow_ref(destination_fund_key)
            walletized = bool(destination_fund_key or destination_address)
            return {
                "source_fund_key": None,
                "destination_fund_key": destination_fund_key,
                "source_label": user_label,
                "source_wallet_address": user_address,
                "destination_label": destination_label or "目的帳本身份",
                "destination_wallet_address": destination_address,
                "target_wallet_address": "",
                "legacy_public_account_id": legacy_account,
                "walletized": walletized,
                "walletization_note": "legacy row without immutable wallet-flow snapshot",
            }
        if direction in {"freeze", "unfreeze"}:
            return {
                "source_fund_key": None,
                "destination_fund_key": None,
                "source_label": user_label,
                "source_wallet_address": user_address,
                "destination_label": user_label,
                "destination_wallet_address": user_address,
                "target_wallet_address": "",
                "legacy_public_account_id": legacy_account,
                "internal_movement": True,
                "walletized": True,
                "walletization_note": "legacy row without immutable wallet-flow snapshot",
            }
        return {
            "source_fund_key": None,
            "destination_fund_key": None,
            "target_wallet_address": "",
            "legacy_public_account_id": legacy_account,
            "walletized": False,
            "walletization_note": "legacy row without immutable wallet-flow snapshot",
        }

    def _economy_fund_flow_ref(self, fund_key):
        labels = {
            "mint": "MINT 發行錢包",
            "burn": "BURN 銷毀錢包",
            "official_treasury": "官方 Treasury 錢包",
            "promo_fund": "PROMO 獎勵基金",
            "exchange_fund": "EXCHANGE 交易所基金",
        }
        return labels.get(fund_key, fund_key or "-"), economy_fund_address(self.chain_secret, fund_key)

    def _counterparty_user_address(self, conn, value):
        try:
            user_id = int(value)
        except Exception:
            return ""
        address, _label, _target, legacy = self._wallet_address_for_user_flow(conn, user_id)
        return address or legacy

    def _points_ledger_credit_source_fund(self, action_type):
        action = str(action_type or "")
        promo_actions = {
            "daily_login",
            "forum_post_reward",
            "forum_comment_reward",
            "content_like_reward",
            "quality_post_bonus",
            "bug_bounty_low",
            "bug_bounty_medium",
            "bug_bounty_high",
            "new_user_signup_bonus",
            "user_initial_grant",
            "admin_initial_grant",
            "birthday_gift",
            "game_daily_quest",
            "game_daily_challenge_reward",
            "game_weekly_leaderboard_reward",
            "trading_bot_weekly_competition_reward",
            "reward_thread_author",
        }
        official_actions = {
            "admin_adjust_credit",
            "admin_weekly_salary",
            "official_wallet_grant",
        }
        if action in promo_actions or action.startswith("reward_"):
            return "promo_fund"
        if action in official_actions:
            return "official_treasury"
        return None

    def _is_configured_auto_distribution_action(self, action_type):
        action = str(action_type or "")
        configured_auto_actions = {
            "daily_login",
            "forum_post_reward",
            "forum_comment_reward",
            "content_like_reward",
            "quality_post_bonus",
            "bug_bounty_low",
            "bug_bounty_medium",
            "bug_bounty_high",
            "new_user_signup_bonus",
            "user_initial_grant",
            "admin_initial_grant",
            "birthday_gift",
            "game_daily_quest",
            "game_daily_challenge_reward",
            "game_weekly_leaderboard_reward",
            "trading_bot_weekly_competition_reward",
            "reward_thread_author",
            "admin_weekly_salary",
        }
        return action in configured_auto_actions or action.startswith("reward_")

    def _explorer_chain_fee_policy(self, row):
        action_type = str(row["action_type"] or "")
        try:
            raw_public_metadata = row["public_metadata_json"]
        except Exception:
            raw_public_metadata = row.get("public_metadata_json") if hasattr(row, "get") else None
        if raw_public_metadata is None and hasattr(row, "get"):
            raw_public_metadata = row.get("public_metadata")
        public_metadata = raw_public_metadata if isinstance(raw_public_metadata, dict) else _json_loads(raw_public_metadata, {})
        service_fee_layer = (
            public_metadata.get("settlement_layer") == "service_fee_subledger"
            or action_type.startswith("service_fee_reserve:")
            or action_type in {"service_fee_batch_unfreeze", "service_fee_batch_debit"}
        )
        if service_fee_layer:
            return {
                "base_fee_exempt": True,
                "base_fee_destination_fund_key": "burn",
                "base_fee_destination_label": "BURN 銷毀錢包",
                "acceleration_allowed": False,
                "exemption_reason": "站內小額服務費採凍結小帳本與批次鏈上扣款，單筆免鏈上費用",
                "manual_official_wallet_ops_are_auto": False,
            }
        if action_type == "wallet_creation_fee":
            return {
                "base_fee_exempt": True,
                "base_fee_destination_fund_key": "burn",
                "base_fee_destination_label": "BURN 銷毀錢包",
                "acceleration_allowed": False,
                "exemption_reason": "錢包建立功能服務費已入官方 Treasury，單筆不再收鏈上 fee",
                "manual_official_wallet_ops_are_auto": False,
            }
        fee_exempt = self._is_configured_auto_distribution_action(action_type)
        return {
            "base_fee_exempt": fee_exempt,
            "base_fee_destination_fund_key": "burn",
            "base_fee_destination_label": "BURN 銷毀錢包",
            "acceleration_allowed": not fee_exempt,
            "exemption_reason": "設定自動發放交易免鏈上費用" if fee_exempt else "",
            "manual_official_wallet_ops_are_auto": False,
        }

    def _points_ledger_debit_destination_fund(self, action_type):
        action = str(action_type or "")
        if action in {"video_tip_debit"}:
            return None
        if action in {"wallet_transfer_fee"}:
            return "burn"
        if action in {"wallet_creation_fee"}:
            return "official_treasury"
        if action.startswith("spend:") or action in {"service_fee_batch_debit", "video_boost_debit", "admin_adjust_debit", "chain_acceleration_fee"}:
            return "burn"
        if action.startswith("rollback:"):
            return "burn"
        return None

    def _ledger_wallet_flow_descriptor(self, conn, *, user_id, direction, action_type, public_metadata=None):
        public_metadata = public_metadata if isinstance(public_metadata, dict) else {}
        source_override = str(public_metadata.get("source_wallet_address") or "").strip().lower()
        destination_override = str(public_metadata.get("destination_wallet_address") or "").strip().lower()
        preferred_user_address = destination_override if direction in {"credit", "transfer_in"} else source_override
        user_address, user_label, target_address, legacy_account = self._wallet_address_for_user_flow(conn, user_id, preferred_user_address)
        direction = str(direction or "")
        action_type = str(action_type or "")
        if direction in {"credit", "transfer_in"}:
            source_address = ""
            source_label = ""
            source_fund_key = self._points_ledger_credit_source_fund(action_type)
            if action_type == "video_tip_credit":
                source_address = self._counterparty_user_address(conn, public_metadata.get("from_user_id"))
                source_label = "打賞付款錢包"
                source_fund_key = None
            elif action_type == "video_tip_platform_fee":
                source_address = self._counterparty_user_address(conn, public_metadata.get("from_user_id"))
                source_label = "平台費付款錢包"
                source_fund_key = None
            elif action_type == "wallet_transfer_in":
                source_address = source_override
                source_label = "轉帳付款錢包"
                source_fund_key = None
            if source_fund_key:
                source_label, source_address = self._economy_fund_flow_ref(source_fund_key)
            walletized = bool(source_fund_key or source_address)
            return {
                "source_fund_key": source_fund_key,
                "destination_fund_key": None,
                "source_label": source_label or "來源錢包",
                "source_wallet_address": source_address,
                "destination_label": user_label,
                "destination_wallet_address": user_address,
                "target_wallet_address": target_address,
                "legacy_public_account_id": legacy_account,
                "walletized": walletized,
                "walletization_note": "" if walletized else "未分類舊帳本收入不再自動套用基金來源",
            }
        if direction in {"debit", "transfer_out", "reverse"}:
            destination_address = ""
            destination_label = ""
            destination_fund_key = self._points_ledger_debit_destination_fund(action_type)
            if action_type == "video_tip_debit":
                destination_address = self._counterparty_user_address(conn, public_metadata.get("to_user_id"))
                destination_label = "打賞收款錢包"
            elif action_type == "wallet_transfer_out":
                destination_address = destination_override
                destination_label = "轉帳收款錢包"
            if destination_fund_key:
                destination_label, destination_address = self._economy_fund_flow_ref(destination_fund_key)
            walletized = bool(destination_fund_key or destination_address)
            return {
                "source_fund_key": None,
                "destination_fund_key": destination_fund_key,
                "source_label": user_label,
                "source_wallet_address": user_address,
                "destination_label": destination_label or "目的錢包",
                "destination_wallet_address": destination_address,
                "target_wallet_address": target_address,
                "legacy_public_account_id": legacy_account,
                "walletized": walletized,
                "walletization_note": "" if walletized else "未分類舊帳本支出不再自動套用基金目的地",
            }
        if direction in {"freeze", "unfreeze"}:
            return {
                "source_fund_key": None,
                "destination_fund_key": None,
                "source_label": user_label,
                "source_wallet_address": user_address,
                "destination_label": user_label,
                "destination_wallet_address": user_address,
                "target_wallet_address": target_address,
                "legacy_public_account_id": legacy_account,
                "internal_movement": True,
                "walletized": True,
            }
        return {
            "source_fund_key": None,
            "destination_fund_key": None,
            "target_wallet_address": target_address,
            "legacy_public_account_id": legacy_account,
            "walletized": False,
        }

    def _wallet_flow_snapshot_for_ledger_write(self, conn, *, user_id, direction, action_type, public_metadata=None):
        flow = self._ledger_wallet_flow_descriptor(
            conn,
            user_id=user_id,
            direction=direction,
            action_type=action_type,
            public_metadata=public_metadata or {},
        )
        snapshot = {key: value for key, value in flow.items() if isinstance(value, (str, int, float, bool)) or value is None}
        snapshot["snapshot_source"] = "ledger_write"
        snapshot["snapshot_version"] = 1
        return snapshot

    def _ledger_metadata_with_wallet_flow_snapshot(self, conn, *, user_id, direction, action_type, public_metadata=None):
        metadata = dict(public_metadata or {})
        metadata.pop("wallet_flow_snapshot", None)
        snapshot = self._wallet_flow_snapshot_for_ledger_write(
            conn,
            user_id=user_id,
            direction=direction,
            action_type=action_type,
            public_metadata=metadata,
        )
        metadata["wallet_flow_snapshot"] = snapshot
        return metadata, snapshot

    def _pending_transfer_outgoing_by_address(self, conn, addresses, *, exclude_request_uuid=None, branch_uuid=None):
        normalized = sorted({str(address or "").strip().lower() for address in addresses or [] if address})
        if not normalized:
            return {}
        branch = str(branch_uuid or self._canonical_branch_uuid(conn) or self._main_branch_uuid())
        placeholders = ", ".join("?" for _ in normalized)
        sql = f"""
            SELECT source_wallet_address, COALESCE(SUM(amount_points + fee_points), 0) AS pending_total
            FROM points_chain_transfer_requests
            WHERE status='pending' AND chain_branch=? AND source_wallet_address IN ({placeholders})
        """
        params = [branch, *normalized]
        if exclude_request_uuid:
            sql += " AND request_uuid<>?"
            params.append(str(exclude_request_uuid))
        sql += " GROUP BY source_wallet_address"
        try:
            rows = conn.execute(sql, tuple(params)).fetchall()
        except Exception:
            return {}
        return {str(row["source_wallet_address"] or ""): int(row["pending_total"] or 0) for row in rows}

    def _wallet_identity_balances_for_user(self, conn, user_id, *, include_pending=True, exclude_request_uuid=None, branch_uuid=None):
        state = self._wallet_identity_state_for_user(conn, user_id)
        branch = str(branch_uuid or self._canonical_branch_uuid(conn) or self._main_branch_uuid())
        balances = {}
        if not state["has_identity"]:
            return {"has_identity": False, "primary_address": "", "balances": balances}
        for address in state["addresses"]:
            balances[address] = {"balance": 0, "frozen": 0, "pending_outgoing": 0}
        rows = conn.execute(
            """
            SELECT * FROM points_ledger
            WHERE status='confirmed' AND chain_branch=?
            ORDER BY id ASC
            """,
            (branch,),
        ).fetchall()
        for row in rows:
            flow = self._ledger_wallet_flow_for_read(conn, row)
            amount = int(row["amount"] or 0)
            direction = str(row["direction"] or "")
            if direction in {"credit", "transfer_in"}:
                address = str(flow.get("destination_wallet_address") or "")
                if address in balances:
                    balances[address]["balance"] += amount
            elif direction in {"debit", "transfer_out", "reverse"}:
                address = str(flow.get("source_wallet_address") or "")
                if address in balances:
                    balances[address]["balance"] -= amount
            elif direction == "freeze":
                address = str(flow.get("source_wallet_address") or "")
                if address in balances:
                    balances[address]["balance"] -= amount
                    balances[address]["frozen"] += amount
            elif direction == "unfreeze":
                address = str(flow.get("source_wallet_address") or flow.get("destination_wallet_address") or "")
                if address in balances:
                    balances[address]["balance"] += amount
                    balances[address]["frozen"] -= amount
        if balances:
            placeholders = ", ".join("?" for _ in balances)
            transfer_rows = conn.execute(
                f"""
                SELECT destination_wallet_address, COALESCE(SUM(amount_points), 0) AS received
                FROM points_chain_transfer_requests
                WHERE status='confirmed'
                  AND chain_branch=?
                  AND destination_wallet_address IN ({placeholders})
                  AND (transfer_in_ledger_uuid IS NULL OR transfer_in_ledger_uuid='')
                GROUP BY destination_wallet_address
                """,
                (branch, *tuple(balances.keys())),
            ).fetchall()
            for row in transfer_rows:
                address = str(row["destination_wallet_address"] or "")
                if address in balances:
                    balances[address]["balance"] += int(row["received"] or 0)
        if include_pending:
            pending_by_address = self._pending_transfer_outgoing_by_address(
                conn,
                balances.keys(),
                exclude_request_uuid=exclude_request_uuid,
                branch_uuid=branch,
            )
            for address, pending in pending_by_address.items():
                if address in balances and pending > 0:
                    balances[address]["balance"] -= pending
                    balances[address]["frozen"] += pending
                    balances[address]["pending_outgoing"] = pending
        primary = state["primary"]
        return {
            "has_identity": True,
            "primary_address": primary["address"] if primary else "",
            "balances": balances,
        }

    def _economy_external_address_balance(self, conn, address, *, chain_branch=None):
        address = str(address or "").strip()
        if not address:
            return 0
        branch = str(chain_branch or self._canonical_branch_uuid(conn) or self._main_branch_uuid())
        rows = conn.execute(
            """
            SELECT source_fund_key, source_address, destination_fund_key, destination_address, amount
            FROM points_economy_events
            WHERE status='confirmed' AND chain_branch=?
            ORDER BY id ASC
            """
            ,
            (branch,),
        ).fetchall()
        balance = 0
        for row in rows:
            amount = int(row["amount"] or 0)
            if not row["destination_fund_key"] and str(row["destination_address"] or "") == address:
                balance += amount
            if not row["source_fund_key"] and str(row["source_address"] or "") == address:
                balance -= amount
        return balance

    def _append_walletized_economy_event(self, conn, *, ledger_row, public_metadata=None, actor=None):
        public_metadata = public_metadata if isinstance(public_metadata, dict) else {}
        if str(ledger_row["action_type"] or "") == "wallet_transfer_in":
            return None, False
        snapshot = public_metadata.get("wallet_flow_snapshot")
        flow = dict(snapshot) if isinstance(snapshot, dict) else self._legacy_ledger_wallet_flow_descriptor(
            conn,
            ledger_row,
            public_metadata=public_metadata,
        )
        if flow.get("internal_movement"):
            return None, False
        if not flow.get("walletized"):
            return None, False
        source_fund_key = flow.get("source_fund_key")
        destination_fund_key = flow.get("destination_fund_key")
        source_address = "" if source_fund_key else flow.get("source_wallet_address")
        destination_address = "" if destination_fund_key else flow.get("destination_wallet_address")
        if not source_fund_key and not source_address:
            return None, False
        if not destination_fund_key and not destination_address:
            return None, False
        branch = str(ledger_row["chain_branch"] if "chain_branch" in ledger_row.keys() else self._canonical_branch_uuid(conn))
        bootstrap_economy_layer(conn, chain_secret=self.chain_secret, actor={"role": "system", "id": None}, chain_branch=branch)
        return append_economy_event(
            conn,
            chain_secret=self.chain_secret,
            event_type="legacy_walletized_flow",
            transaction_type=str(ledger_row["action_type"] or "points_ledger"),
            source_fund_key=source_fund_key,
            source_address=source_address,
            destination_fund_key=destination_fund_key,
            destination_address=destination_address,
            amount=int(ledger_row["amount"]),
            idempotency_key=f"walletized_ledger:{ledger_row['ledger_uuid']}",
            metadata={
                "legacy_ledger_uuid": ledger_row["ledger_uuid"],
                "legacy_action_type": ledger_row["action_type"],
                "legacy_direction": ledger_row["direction"],
                "legacy_user_id": int(ledger_row["user_id"]),
                "legacy_reference_type": ledger_row["reference_type"],
                "legacy_reference_id": ledger_row["reference_id"],
                "walletization_phase": "1B",
            },
            actor=actor,
            chain_branch=branch,
        )

    def _wallet_identity_owner_for_address(self, conn, address):
        address = str(address or "").strip().lower()
        if not WALLET_ADDRESS_RE.fullmatch(address):
            raise ValueError("wallet address format is invalid")
        return conn.execute(
            """
            SELECT * FROM points_wallet_identities
            WHERE address=? AND status IN ('pending_backup', 'active')
            LIMIT 1
            """,
            (address,),
        ).fetchone()

    def _assert_wallet_identity_can_spend(self, wallet, *, context="wallet transaction"):
        if not wallet:
            raise PermissionError("source wallet does not exist")
        keys = set(wallet.keys())
        custody_mode = str(wallet["custody_mode"] or "")
        wallet_scope = str(wallet["wallet_scope"] if "wallet_scope" in keys else "user")
        spend_capability = str(wallet["spend_capability"] if "spend_capability" in keys else "enabled")
        wallet_type = str(wallet["wallet_type"] or "")
        if custody_mode == "multisig" and wallet_scope != "official_treasury":
            raise PermissionError("user_multisig_receive_only_rc1: 一般用戶多簽目前僅支援收款/觀察，不支援轉出")
        if custody_mode == "multisig" and wallet_scope == "official_treasury" and wallet_type != "official_treasury_multisig":
            raise PermissionError("official treasury multisig spend requires official_treasury_multisig wallet type")
        if spend_capability != "enabled":
            raise PermissionError(f"{context} source wallet is {spend_capability}")

    def _transfer_request_payload_hash(self, payload):
        return sha256_text(canonical_json(payload))

    def _transfer_request_ledgers(self, conn, request_uuid):
        req = conn.execute(
            "SELECT * FROM points_chain_transfer_requests WHERE request_uuid=?",
            (request_uuid,),
        ).fetchone()
        if not req:
            return None
        ledgers = {}
        for key, column in (
            ("transfer_out_ledger", "transfer_out_ledger_uuid"),
            ("transfer_in_ledger", "transfer_in_ledger_uuid"),
            ("fee_ledger", "fee_ledger_uuid"),
        ):
            ledger_uuid = req[column]
            if ledger_uuid:
                row = conn.execute("SELECT * FROM points_ledger WHERE ledger_uuid=?", (ledger_uuid,)).fetchone()
                ledgers[key] = self._explorer_public_ledger(conn, row) if row else None
            else:
                ledgers[key] = None
        return {"request": dict(req), **ledgers}

    def _explorer_find_transfer_request(self, conn, ref):
        ref = str(ref or "").strip()
        if not ref:
            return None
        return conn.execute(
            """
            SELECT *
            FROM points_chain_transfer_requests
            WHERE request_uuid=?
               OR tx_group_hash=?
               OR transfer_out_ledger_uuid=?
               OR transfer_in_ledger_uuid=?
               OR fee_ledger_uuid=?
            LIMIT 1
            """,
            (ref, ref, ref, ref, ref),
        ).fetchone()

    def _pending_transfer_outgoing_for_address(self, conn, address, *, exclude_request_uuid=None, branch_uuid=None):
        address = str(address or "").strip().lower()
        if not address:
            return 0
        branch = str(branch_uuid or self._canonical_branch_uuid(conn) or self._main_branch_uuid())
        sql = """
            SELECT COALESCE(SUM(amount_points + fee_points), 0) AS pending_total
            FROM points_chain_transfer_requests
            WHERE source_wallet_address=? AND chain_branch=? AND status='pending'
        """
        params = [address, branch]
        if exclude_request_uuid:
            sql += " AND request_uuid<>?"
            params.append(str(exclude_request_uuid))
        row = conn.execute(sql, tuple(params)).fetchone()
        return int((row["pending_total"] if row else 0) or 0)

    def _wallet_identity_balance_for_address(self, conn, *, user_id, address):
        state = self._wallet_identity_balances_for_user(conn, int(user_id), include_pending=False)
        balances = state.get("balances") or {}
        payload = balances.get(str(address or "").strip().lower())
        return int((payload or {}).get("balance") or 0)

    def _wallet_identity_available_for_address(self, conn, *, user_id, address, exclude_request_uuid=None):
        state = self._wallet_identity_balances_for_user(
            conn,
            int(user_id),
            include_pending=True,
            exclude_request_uuid=exclude_request_uuid,
        )
        balances = state.get("balances") or {}
        payload = balances.get(str(address or "").strip().lower())
        return int((payload or {}).get("balance") or 0)

    def _transfer_request_public_payload(self, conn, req):
        req = dict(req)
        fee = int(req.get("fee_points") or 0)
        acceleration = self._explorer_acceleration_summary(conn, req["request_uuid"])
        acceleration_fee = int(acceleration.get("total_fee_points") or 0)
        transaction_type = str(req.get("transaction_type") or "wallet_transfer")
        source_fund_key = str(req.get("source_fund_key") or "")
        official_grant = transaction_type == "official_wallet_grant" or source_fund_key == "official_treasury"
        destination_fund_key = self._explorer_fund_key_for_address(req.get("destination_wallet_address") or "")
        destination_unowned = self._transfer_request_destination_unowned(req)
        official_fund_transfer = bool(official_grant and destination_fund_key)
        estimate = self._explorer_finality_estimate(fee + acceleration_fee, conn=conn)
        pseudo_ledger = {
            "ledger_uuid": req["request_uuid"],
            "ledger_hash": req["tx_group_hash"],
            "created_at": req["created_at"],
        }
        schedule = self._explorer_finality_schedule(pseudo_ledger, estimate)
        finality = self._explorer_finality_from_created(
            created_at=req["created_at"],
            estimate=estimate,
            schedule=schedule,
            sealed=False,
            fee_policy={
                "base_fee_exempt": False,
                "base_fee_destination_fund_key": "burn",
                "base_fee_destination_label": "BURN 銷毀錢包",
                "acceleration_allowed": str(req.get("status") or "pending") == "pending",
                "exemption_reason": "",
                "manual_official_wallet_ops_are_auto": False,
            },
            acceleration_fee_points=fee + acceleration_fee,
        )
        finality.update({
            "base_transaction_fee_points": fee,
            "acceleration_request_count": int(acceleration.get("count") or 0),
            "acceleration_fee_paid_points": acceleration_fee,
            "acceleration_fee_destination_fund_key": "burn" if acceleration_fee else "",
            "acceleration_fee_destination_label": "BURN 銷毀錢包" if acceleration_fee else "",
            "latest_acceleration_request": acceleration.get("latest_request"),
        })
        status = str(req.get("status") or "pending")
        if status == "confirmed" and finality["finality_status"] == "pending":
            finality.update({
                "proved_count": EXPLORER_FINALITY_PROVED_COUNT,
                "proved_remaining": 0,
                "finality_status": "proved",
                "eta_seconds": 0,
                "next_proof_eta_seconds": 0,
            })
        elif status.startswith("failed"):
            finality.update({
                "finality_status": "failed",
                "block_status": "failed",
                "eta_seconds": 0,
                "next_proof_eta_seconds": 0,
            })
        out_row = conn.execute("SELECT * FROM points_ledger WHERE ledger_uuid=?", (req.get("transfer_out_ledger_uuid") or "",)).fetchone()
        in_row = conn.execute("SELECT * FROM points_ledger WHERE ledger_uuid=?", (req.get("transfer_in_ledger_uuid") or "",)).fetchone()
        fee_row = conn.execute("SELECT * FROM points_ledger WHERE ledger_uuid=?", (req.get("fee_ledger_uuid") or "",)).fetchone()
        block = None
        block_source = out_row or in_row or fee_row
        if block_source and block_source["chain_block_id"]:
            block_row = conn.execute("SELECT * FROM points_chain_blocks WHERE id=?", (block_source["chain_block_id"],)).fetchone()
            if block_row:
                block = {
                    "block_number": int(block_row["block_number"]),
                    "block_hash": block_row["block_hash"],
                    "sealed_at": block_row["sealed_at"],
                    "ledger_count": int(block_row["ledger_count"]),
                }
                finality["block_status"] = "sealed"
        input_data = {"memo": req.get("memo") or "", "request_uuid": req["request_uuid"]}
        input_data["transaction_type"] = transaction_type
        source_label = "官方 Treasury 錢包" if official_grant else "From"
        destination_label = destination_fund_key.replace("_", " ").title() if destination_fund_key else "To"
        reason = (
            "official treasury fund transfer"
            if official_fund_transfer
            else "official treasury wallet grant"
            if official_grant
            else "wallet transfer"
        )
        return {
            "ledger_uuid": req["request_uuid"],
            "chain_branch": req.get("chain_branch") or self._main_branch_uuid(),
            "branch": self._branch_metadata(conn, req.get("chain_branch") or self._main_branch_uuid()),
            "ledger_hash": req["tx_group_hash"],
            "transaction_hash": req["tx_group_hash"],
            "previous_ledger_hash": "",
            "public_account_id": "",
            "currency_type": DISPLAY_CURRENCY,
            "direction": "transfer_out" if official_fund_transfer else ("credit" if official_grant else "transfer_out"),
            "amount": int(req.get("amount_points") or 0),
            "action_type": transaction_type,
            "reference_type": transaction_type,
            "reference_id": req["tx_group_hash"],
            "reason": reason,
            "input_data": input_data,
            "status": status,
            "created_at": req["created_at"],
            "chain_block_id": block_source["chain_block_id"] if block_source else None,
            "wallet_flow": {
                "source_fund_key": source_fund_key or None,
                "destination_fund_key": destination_fund_key or None,
                "source_label": source_label,
                "source_wallet_address": req["source_wallet_address"],
                "destination_label": destination_label,
                "destination_wallet_address": req["destination_wallet_address"],
                "destination_unowned": destination_unowned,
                "destination_owner_known": not destination_unowned,
                "target_wallet_address": "",
                "walletized": True,
                "walletization_note": "pending requests do not credit the recipient until 20/20 Proved",
            },
            "block": block,
            "finality": finality,
            "transfer_ledgers": {
                "transfer_out_ledger_uuid": req.get("transfer_out_ledger_uuid") or "",
                "transfer_in_ledger_uuid": req.get("transfer_in_ledger_uuid") or "",
                "fee_ledger_uuid": req.get("fee_ledger_uuid") or "",
            },
        }

    def _transfer_request_member_summary(self, conn, req, *, user_id, root_view=False, viewer_addresses=None):
        req = dict(req)
        payload = self._transfer_request_public_payload(conn, req)
        sender_id = int(req["sender_user_id"] or 0)
        recipient_id = self._transfer_request_recipient_user_id(req)
        viewer_id = int(user_id)
        viewer_addresses = {str(item or "").strip().lower() for item in (viewer_addresses or []) if item}
        source_address = str(req["source_wallet_address"] or "").strip().lower()
        destination_address = str(req["destination_wallet_address"] or "").strip().lower()
        destination_unowned = self._transfer_request_destination_unowned(req)
        source_is_viewer = sender_id == viewer_id or source_address in viewer_addresses
        destination_is_viewer = destination_address in viewer_addresses or (recipient_id == viewer_id and not destination_unowned)
        transaction_type = str(req.get("transaction_type") or "wallet_transfer")
        source_fund_key = str(req.get("source_fund_key") or "")
        destination_fund_key = self._explorer_fund_key_for_address(req.get("destination_wallet_address") or "")
        if root_view and source_fund_key == "official_treasury" and destination_fund_key:
            direction = "official_fund_transfer"
            counterparty = req["destination_wallet_address"]
        elif root_view and (transaction_type == "official_wallet_grant" or source_fund_key == "official_treasury"):
            direction = "official_outgoing"
            counterparty = req["destination_wallet_address"]
        elif root_view:
            direction = "observed"
            counterparty = req["destination_wallet_address"]
        elif source_is_viewer and destination_is_viewer:
            direction = "self"
            counterparty = req["destination_wallet_address"]
        elif source_is_viewer:
            direction = "outgoing"
            counterparty = req["destination_wallet_address"]
        else:
            direction = "incoming"
            counterparty = req["source_wallet_address"]
        status = str(req["status"] or "pending")
        return {
            "request_uuid": req["request_uuid"],
            "tx_group_hash": req["tx_group_hash"],
            "transaction_hash": req["tx_group_hash"],
            "transaction_type": transaction_type,
            "source_fund_key": source_fund_key,
            "direction": direction,
            "status": status,
            "amount_points": int(req["amount_points"] or 0),
            "fee_points": int(req["fee_points"] or 0),
            "source_wallet_address": req["source_wallet_address"],
            "destination_wallet_address": req["destination_wallet_address"],
            "counterparty_wallet_address": counterparty,
            "memo": req["memo"] or "",
            "created_at": req["created_at"],
            "finality": payload["finality"],
            "wallet_flow": payload["wallet_flow"],
            "transfer_ledgers": payload["transfer_ledgers"],
            "balance_effect": (
                "confirmed"
                if status == "confirmed"
                else "pending_no_recipient_credit"
                if status == "pending"
                else "failed_no_balance_change"
            ),
        }

    def _notify_wallet_transfer_once(self, conn, *, user_id, notification_type, title, body, tx_group_hash):
        try:
            from services.system.notifications import create_notification_once_if_enabled
            create_notification_once_if_enabled(
                conn,
                user_id=int(user_id),
                type=notification_type,
                title=title,
                body=body,
                link=f"/#economy-explorer:{tx_group_hash}",
            )
        except Exception as exc:
            try:
                self._audit_log(
                    conn,
                    "POINTS_CHAIN_NOTIFICATION_FAILED",
                    "warning",
                    f"{notification_type} notification failed for user {user_id}",
                    target_user_id=int(user_id),
                    metadata={
                        "notification_type": notification_type,
                        "transaction_hash": tx_group_hash,
                        "error": str(exc)[:240],
                    },
                )
            except Exception:
                pass
            return False
        return True

    def _transfer_request_is_official_grant(self, req):
        req = dict(req)
        return (
            str(req.get("transaction_type") or "wallet_transfer") == "official_wallet_grant"
            or str(req.get("source_fund_key") or "") == "official_treasury"
        )

    def _transfer_request_destination_unowned(self, req):
        try:
            return bool(int(dict(req).get("destination_unowned") or 0))
        except Exception:
            return False

    def _transfer_request_recipient_user_id(self, req):
        try:
            return int(dict(req).get("recipient_user_id") or 0)
        except Exception:
            return 0

    def _notify_wallet_transfer_pending(self, conn, req):
        req = dict(req)
        amount = int(req["amount_points"] or 0)
        fee = int(req["fee_points"] or 0)
        tx_hash = req["tx_group_hash"]
        destination_unowned = self._transfer_request_destination_unowned(req)
        if self._transfer_request_is_official_grant(req):
            destination_fund_key = self._explorer_fund_key_for_address(req.get("destination_wallet_address") or "")
            if destination_fund_key:
                sender_sent = self._notify_wallet_transfer_once(
                    conn,
                    user_id=req["sender_user_id"],
                    notification_type="points_chain_official_fund_transfer_pending",
                    title="官方基金調撥交易已送出",
                    body=f"交易 {tx_hash} 正在等待 20/20 Proved；官方 Treasury 將調撥 {amount} 點到 {destination_fund_key}。成交前基金不會入帳。",
                    tx_group_hash=tx_hash,
                )
                return {
                    "event": "pending",
                    "sender": sender_sent,
                    "recipient": True,
                    "system_recipient": destination_fund_key,
                    "all_sent": bool(sender_sent),
                }
            sender_sent = self._notify_wallet_transfer_once(
                conn,
                user_id=req["sender_user_id"],
                notification_type="points_chain_official_grant_pending",
                title="官方發點交易已送出",
                body=f"交易 {tx_hash} 正在等待 20/20 Proved；官方 Treasury 發點 {amount} 點。成交前目的地址不會入帳。",
                tx_group_hash=tx_hash,
            )
            if destination_unowned:
                return {
                    "event": "pending",
                    "sender": sender_sent,
                    "recipient": None,
                    "unowned_recipient": True,
                    "all_sent": bool(sender_sent),
                }
            recipient_sent = self._notify_wallet_transfer_once(
                conn,
                user_id=req["recipient_user_id"],
                notification_type="points_chain_official_grant_pending",
                title="收到待確認官方發點",
                body=f"交易 {tx_hash} 正在等待 20/20 Proved；Value {amount} 點。成交前不會入帳。",
                tx_group_hash=tx_hash,
            )
            return {"event": "pending", "sender": sender_sent, "recipient": recipient_sent, "all_sent": bool(sender_sent and recipient_sent)}
        sender_sent = self._notify_wallet_transfer_once(
            conn,
            user_id=req["sender_user_id"],
            notification_type="points_chain_transfer_pending",
            title="鏈上交易已送出",
            body=f"交易 {tx_hash} 正在等待 20/20 Proved；Value {amount} 點，Fee {fee} 點。成交前收款方不會入帳。",
            tx_group_hash=tx_hash,
        )
        if destination_unowned:
            return {
                "event": "pending",
                "sender": sender_sent,
                "recipient": None,
                "unowned_recipient": True,
                "all_sent": bool(sender_sent),
            }
        recipient_sent = self._notify_wallet_transfer_once(
            conn,
            user_id=req["recipient_user_id"],
            notification_type="points_chain_transfer_pending",
            title="收到待確認鏈上交易",
            body=f"交易 {tx_hash} 正在等待 20/20 Proved；Value {amount} 點。成交前不會入帳。",
            tx_group_hash=tx_hash,
        )
        return {"event": "pending", "sender": sender_sent, "recipient": recipient_sent, "all_sent": bool(sender_sent and recipient_sent)}

    def _notify_wallet_transfer_completed(self, conn, req):
        req = dict(req)
        amount = int(req["amount_points"] or 0)
        fee = int(req["fee_points"] or 0)
        tx_hash = req["tx_group_hash"]
        destination_unowned = self._transfer_request_destination_unowned(req)
        if self._transfer_request_is_official_grant(req):
            destination_fund_key = self._explorer_fund_key_for_address(req.get("destination_wallet_address") or "")
            if destination_fund_key:
                sender_sent = self._notify_wallet_transfer_once(
                    conn,
                    user_id=req["sender_user_id"],
                    notification_type="points_chain_official_fund_transfer_completed",
                    title="官方基金調撥交易已成交",
                    body=f"交易 {tx_hash} 已達 20/20 Proved；官方 Treasury 已調撥 {amount} 點到 {destination_fund_key}。",
                    tx_group_hash=tx_hash,
                )
                return {
                    "event": "completed",
                    "sender": sender_sent,
                    "recipient": True,
                    "system_recipient": destination_fund_key,
                    "all_sent": bool(sender_sent),
                }
            sender_sent = self._notify_wallet_transfer_once(
                conn,
                user_id=req["sender_user_id"],
                notification_type="points_chain_official_grant_completed",
                title="官方發點交易已成交",
                body=f"交易 {tx_hash} 已達 20/20 Proved；官方 Treasury 已發出 {amount} 點。",
                tx_group_hash=tx_hash,
            )
            if destination_unowned:
                return {
                    "event": "completed",
                    "sender": sender_sent,
                    "recipient": None,
                    "unowned_recipient": True,
                    "all_sent": bool(sender_sent),
                }
            recipient_sent = self._notify_wallet_transfer_once(
                conn,
                user_id=req["recipient_user_id"],
                notification_type="points_chain_official_grant_completed",
                title="官方發點已入帳",
                body=f"交易 {tx_hash} 已達 20/20 Proved；已入帳 {amount} 點。",
                tx_group_hash=tx_hash,
            )
            return {"event": "completed", "sender": sender_sent, "recipient": recipient_sent, "all_sent": bool(sender_sent and recipient_sent)}
        sender_sent = self._notify_wallet_transfer_once(
            conn,
            user_id=req["sender_user_id"],
            notification_type="points_chain_transfer_completed",
            title="鏈上交易已成交",
            body=f"交易 {tx_hash} 已達 20/20 Proved；已扣除 Value {amount} 點與 Fee {fee} 點。",
            tx_group_hash=tx_hash,
        )
        if destination_unowned:
            return {
                "event": "completed",
                "sender": sender_sent,
                "recipient": None,
                "unowned_recipient": True,
                "all_sent": bool(sender_sent),
            }
        recipient_sent = self._notify_wallet_transfer_once(
            conn,
            user_id=req["recipient_user_id"],
            notification_type="points_chain_transfer_completed",
            title="鏈上交易已入帳",
            body=f"交易 {tx_hash} 已達 20/20 Proved；已入帳 {amount} 點。",
            tx_group_hash=tx_hash,
        )
        return {"event": "completed", "sender": sender_sent, "recipient": recipient_sent, "all_sent": bool(sender_sent and recipient_sent)}

    def _notify_wallet_transfer_failed(self, conn, req, reason):
        req = dict(req)
        tx_hash = req["tx_group_hash"]
        body = f"交易 {tx_hash} 未成交：{public_currency_text(reason or '交易失敗')}"
        sender_sent = self._notify_wallet_transfer_once(
            conn,
            user_id=req["sender_user_id"],
            notification_type="points_chain_transfer_failed",
            title="鏈上交易未成交",
            body=body,
            tx_group_hash=tx_hash,
        )
        if self._transfer_request_destination_unowned(req):
            return {
                "event": "failed",
                "sender": sender_sent,
                "recipient": None,
                "unowned_recipient": True,
                "all_sent": bool(sender_sent),
            }
        recipient_sent = self._notify_wallet_transfer_once(
            conn,
            user_id=req["recipient_user_id"],
            notification_type="points_chain_transfer_failed",
            title="鏈上交易未成交",
            body=body,
            tx_group_hash=tx_hash,
        )
        return {"event": "failed", "sender": sender_sent, "recipient": recipient_sent, "all_sent": bool(sender_sent and recipient_sent)}

    def _fail_transfer_request_locked(self, conn, req, *, status, reason):
        status_text = str(status or "failed").strip() or "failed"
        if not status_text.startswith("failed"):
            status_text = f"failed_{status_text}"
        conn.execute(
            "UPDATE points_chain_transfer_requests SET status=? WHERE request_uuid=? AND status='pending'",
            (status_text[:80], req["request_uuid"]),
        )
        failed = conn.execute(
            "SELECT * FROM points_chain_transfer_requests WHERE request_uuid=?",
            (req["request_uuid"],),
        ).fetchone()
        self._notify_wallet_transfer_failed(conn, failed, reason)
        return failed

    def _maybe_finalize_transfer_request_locked(self, conn, req, *, actor=None):
        req = dict(req)
        if str(req.get("status") or "") != "pending":
            return conn.execute(
                "SELECT * FROM points_chain_transfer_requests WHERE request_uuid=?",
                (req["request_uuid"],),
            ).fetchone()
        req_branch = str(req.get("chain_branch") or self._main_branch_uuid())
        canonical_branch = self._canonical_branch_uuid(conn)
        if req_branch != canonical_branch:
            return self._fail_transfer_request_locked(
                conn,
                req,
                status="failed_non_canonical_branch",
                reason="transaction belongs to a non-canonical branch after governance recovery fork",
            )
        payload = self._transfer_request_public_payload(conn, req)
        if payload["finality"]["finality_status"] != "proved":
            return conn.execute(
                "SELECT * FROM points_chain_transfer_requests WHERE request_uuid=?",
                (req["request_uuid"],),
            ).fetchone()
        if self._transfer_request_is_official_grant(req):
            destination_fund_key = self._explorer_fund_key_for_address(req["destination_wallet_address"])
            if destination_fund_key:
                try:
                    destination_fund_key = self._official_transfer_destination_fund_key(req["destination_wallet_address"])
                except ValueError as exc:
                    return self._fail_transfer_request_locked(
                        conn,
                        req,
                        status="failed_unsupported_system_fund",
                        reason=str(exc),
                    )
                bootstrap_economy_layer(conn, chain_secret=self.chain_secret, actor={"role": "system", "id": None}, chain_branch=req_branch)
                append_economy_event(
                    conn,
                    chain_secret=self.chain_secret,
                    event_type="official_fund_transfer",
                    transaction_type="official_fund_transfer",
                    source_fund_key="official_treasury",
                    destination_fund_key=destination_fund_key,
                    amount=int(req["amount_points"]),
                    idempotency_key=f"official_fund_transfer:{req['request_uuid']}",
                    metadata={
                        "request_uuid": req["request_uuid"],
                        "tx_group_hash": req["tx_group_hash"],
                        "source_wallet_address": req["source_wallet_address"],
                        "destination_wallet_address": req["destination_wallet_address"],
                        "destination_fund_key": destination_fund_key,
                        "memo": req["memo"] or "",
                        "walletization_phase": "1B",
                        "financial_source_of_truth": "points_economy_events",
                    },
                    actor=actor,
                    chain_branch=req_branch,
                )
                if destination_fund_key == "exchange_fund":
                    self._sync_exchange_fund_transfer_to_trading_reserve_pool(
                        conn,
                        req=req,
                        amount=int(req["amount_points"]),
                        actor=actor,
                    )
                conn.execute(
                    """
                    UPDATE points_chain_transfer_requests
                    SET status='confirmed'
                    WHERE request_uuid=? AND status='pending'
                    """,
                    (req["request_uuid"],),
                )
                finalized = conn.execute(
                    "SELECT * FROM points_chain_transfer_requests WHERE request_uuid=?",
                    (req["request_uuid"],),
                ).fetchone()
                self._audit_log(
                    conn,
                    "OFFICIAL_FUND_TRANSFER",
                    "info",
                    f"official treasury transfer {int(req['amount_points'])} {DISPLAY_CURRENCY} to {destination_fund_key}",
                    actor=actor,
                    target_user_id=int(req["recipient_user_id"]),
                    metadata={
                        "destination_fund_key": destination_fund_key,
                        "destination_wallet_address": req["destination_wallet_address"],
                        "transaction_hash": req["tx_group_hash"],
                        "request_uuid": req["request_uuid"],
                        "finalized": True,
                    },
                )
                self._notify_wallet_transfer_completed(conn, finalized)
                return finalized
            destination_wallet = self._wallet_identity_owner_for_address(conn, req["destination_wallet_address"])
            if destination_wallet and destination_wallet["user_id"]:
                recipient_user_id = int(destination_wallet["user_id"])
                if recipient_user_id != self._transfer_request_recipient_user_id(req) or self._transfer_request_destination_unowned(req):
                    conn.execute(
                        """
                        UPDATE points_chain_transfer_requests
                        SET recipient_user_id=?, destination_unowned=0
                        WHERE request_uuid=?
                        """,
                        (recipient_user_id, req["request_uuid"]),
                    )
                    req = dict(conn.execute(
                        "SELECT * FROM points_chain_transfer_requests WHERE request_uuid=?",
                        (req["request_uuid"],),
                    ).fetchone())
            else:
                recipient_user_id = self._transfer_request_recipient_user_id(req)
            common = {
                "source_fund_key": "official_treasury",
                "source_wallet_address": req["source_wallet_address"],
                "destination_wallet_address": req["destination_wallet_address"],
                "request_uuid": req["request_uuid"],
                "tx_group_hash": req["tx_group_hash"],
                "memo": req["memo"] or "",
            }
            in_row = None
            if destination_wallet and destination_wallet["user_id"]:
                in_row, _ = self._record_transaction(
                    conn,
                    user_id=recipient_user_id,
                    currency_type=DISPLAY_CURRENCY,
                    direction="credit",
                    amount=int(req["amount_points"]),
                    action_type="official_wallet_grant",
                    reference_type="official_wallet_grant",
                    reference_id=req["tx_group_hash"],
                    idempotency_key=f"official_wallet_grant:{req['request_uuid']}",
                    reason=public_currency_text(req["memo"] or "official wallet grant")[:240],
                    public_metadata=common,
                    actor=actor,
                )
            else:
                bootstrap_economy_layer(conn, chain_secret=self.chain_secret, actor={"role": "system", "id": None}, chain_branch=req_branch)
                append_economy_event(
                    conn,
                    chain_secret=self.chain_secret,
                    event_type="official_wallet_grant",
                    transaction_type="official_wallet_grant",
                    source_fund_key="official_treasury",
                    destination_fund_key=None,
                    destination_address=req["destination_wallet_address"],
                    amount=int(req["amount_points"]),
                    idempotency_key=f"official_wallet_grant:{req['request_uuid']}:unowned_destination",
                    metadata={
                        **common,
                        "destination_unowned": True,
                        "walletization_phase": "1B",
                        "financial_source_of_truth": "points_economy_events",
                    },
                    actor=actor,
                    chain_branch=req_branch,
                )
                conn.execute(
                    """
                    UPDATE points_chain_transfer_requests
                    SET destination_unowned=1
                    WHERE request_uuid=?
                    """,
                    (req["request_uuid"],),
                )
            conn.execute(
                """
                UPDATE points_chain_transfer_requests
                SET transfer_in_ledger_uuid=?, status='confirmed'
                WHERE request_uuid=? AND status='pending'
                """,
                (in_row["ledger_uuid"] if in_row else None, req["request_uuid"]),
            )
            finalized = conn.execute(
                "SELECT * FROM points_chain_transfer_requests WHERE request_uuid=?",
                (req["request_uuid"],),
            ).fetchone()
            self._audit_log(
                conn,
                "OFFICIAL_WALLET_GRANT",
                "info",
                f"official treasury grant {int(req['amount_points'])} {DISPLAY_CURRENCY}",
                actor=actor,
                target_user_id=recipient_user_id if destination_wallet and destination_wallet["user_id"] else None,
                ledger_id=in_row["id"] if in_row else None,
                metadata={
                    "destination_wallet_address": req["destination_wallet_address"],
                    "transaction_hash": req["tx_group_hash"],
                    "ledger_hash": in_row["ledger_hash"] if in_row else "",
                    "request_uuid": req["request_uuid"],
                    "destination_unowned": not bool(destination_wallet and destination_wallet["user_id"]),
                    "finalized": True,
                },
            )
            self._notify_wallet_transfer_completed(conn, finalized)
            return finalized
        source_wallet = self._wallet_identity_row_for_user_address(
            conn,
            int(req["sender_user_id"]),
            req["source_wallet_address"],
            active_only=True,
        )
        destination_wallet = self._wallet_identity_row_for_user_address(
            conn,
            self._transfer_request_recipient_user_id(req),
            req["destination_wallet_address"],
            active_only=True,
        )
        if not source_wallet:
            return self._fail_transfer_request_locked(
                conn,
                req,
                status="failed_inactive_wallet",
                reason="sender wallet is inactive at finality",
            )
        current_destination_owner = self._wallet_identity_owner_for_address(conn, req["destination_wallet_address"])
        if current_destination_owner and current_destination_owner["user_id"]:
            recipient_user_id = int(current_destination_owner["user_id"])
            destination_wallet = current_destination_owner
            if recipient_user_id != self._transfer_request_recipient_user_id(req) or self._transfer_request_destination_unowned(req):
                conn.execute(
                    """
                    UPDATE points_chain_transfer_requests
                    SET recipient_user_id=?, destination_unowned=0
                    WHERE request_uuid=?
                    """,
                    (recipient_user_id, req["request_uuid"]),
                )
                req = dict(conn.execute(
                    "SELECT * FROM points_chain_transfer_requests WHERE request_uuid=?",
                    (req["request_uuid"],),
                ).fetchone())
        else:
            recipient_user_id = self._transfer_request_recipient_user_id(req)
            destination_wallet = None
            conn.execute(
                """
                UPDATE points_chain_transfer_requests
                SET destination_unowned=1
                WHERE request_uuid=?
                """,
                (req["request_uuid"],),
            )
        total_required = int(req["amount_points"] or 0) + int(req["fee_points"] or 0)
        available = self._wallet_identity_available_for_address(
            conn,
            user_id=int(req["sender_user_id"]),
            address=req["source_wallet_address"],
            exclude_request_uuid=req["request_uuid"],
        )
        if available < total_required:
            return self._fail_transfer_request_locked(
                conn,
                req,
                status="failed_insufficient_balance",
                reason="sender wallet has insufficient balance at finality",
            )
        common = {
            "pending_request_uuid": req["request_uuid"],
            "tx_group_hash": req["tx_group_hash"],
            "source_wallet_address": req["source_wallet_address"],
            "destination_wallet_address": req["destination_wallet_address"],
            "memo": req["memo"] or "",
        }
        out_row, _ = self._record_transaction(
            conn,
            user_id=int(req["sender_user_id"]),
            currency_type=DISPLAY_CURRENCY,
            direction="transfer_out",
            amount=int(req["amount_points"]),
            action_type="wallet_transfer_out",
            reference_type="wallet_transfer",
            reference_id=req["tx_group_hash"],
            idempotency_key=f"wallet_transfer:{req['request_uuid']}:out",
            reason="wallet transfer",
            public_metadata={**common, "to_wallet_address": req["destination_wallet_address"]},
            actor=actor,
        )
        in_row = None
        if destination_wallet and destination_wallet["user_id"]:
            in_row, _ = self._record_transaction(
                conn,
                user_id=recipient_user_id,
                currency_type=DISPLAY_CURRENCY,
                direction="transfer_in",
                amount=int(req["amount_points"]),
                action_type="wallet_transfer_in",
                reference_type="wallet_transfer",
                reference_id=req["tx_group_hash"],
                idempotency_key=f"wallet_transfer:{req['request_uuid']}:in",
                reason="wallet transfer",
                public_metadata={**common, "from_wallet_address": req["source_wallet_address"]},
                actor=actor,
            )
        fee_row = None
        if int(req["fee_points"] or 0):
            fee_row, _ = self._record_transaction(
                conn,
                user_id=int(req["sender_user_id"]),
                currency_type=DISPLAY_CURRENCY,
                direction="debit",
                amount=int(req["fee_points"]),
                action_type="wallet_transfer_fee",
                reference_type="wallet_transfer",
                reference_id=req["tx_group_hash"],
                idempotency_key=f"wallet_transfer:{req['request_uuid']}:fee",
                reason="wallet transfer fee",
                public_metadata={**common, "fee_destination_fund_key": "burn"},
                actor=actor,
            )
        conn.execute(
            """
            UPDATE points_chain_transfer_requests
            SET transfer_out_ledger_uuid=?, transfer_in_ledger_uuid=?, fee_ledger_uuid=?, status='confirmed'
            WHERE request_uuid=? AND status='pending'
            """,
            (
                out_row["ledger_uuid"],
                in_row["ledger_uuid"] if in_row else None,
                fee_row["ledger_uuid"] if fee_row else None,
                req["request_uuid"],
            ),
        )
        finalized = conn.execute(
            "SELECT * FROM points_chain_transfer_requests WHERE request_uuid=?",
            (req["request_uuid"],),
        ).fetchone()
        self._notify_wallet_transfer_completed(conn, finalized)
        return finalized

    def _finalize_proved_pending_transfer_requests_locked(self, conn, *, actor=None, limit=1000):
        limit = min(5000, max(1, int(limit or 1000)))
        rows = conn.execute(
            """
            SELECT *
            FROM points_chain_transfer_requests
            WHERE status='pending'
            ORDER BY id ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        finalized_count = 0
        confirmed_count = 0
        failed_count = 0
        finalization_errors = []
        for row in rows:
            before = str(row["status"] or "")
            current = self._maybe_finalize_transfer_request_or_mark_failed_locked(
                conn,
                row,
                actor=actor,
                finalization_errors=finalization_errors,
            )
            after = str(current["status"] or "") if current else before
            if before == "pending" and after != "pending":
                finalized_count += 1
                if after == "confirmed":
                    confirmed_count += 1
                elif after.startswith("failed"):
                    failed_count += 1
        return {
            "checked_count": len(rows),
            "finalized_count": finalized_count,
            "confirmed_count": confirmed_count,
            "failed_count": failed_count,
            "finalization_errors": finalization_errors,
            "finalization_error_count": len(finalization_errors),
        }

    def _maybe_finalize_transfer_request_or_mark_failed_locked(self, conn, req, *, actor=None, finalization_errors=None):
        savepoint = f"sp_finalize_transfer_{uuid.uuid4().hex}"
        conn.execute(f"SAVEPOINT {savepoint}")
        try:
            current = self._maybe_finalize_transfer_request_locked(conn, req, actor=actor)
            conn.execute(f"RELEASE {savepoint}")
            return current
        except ValueError as exc:
            reason = str(exc)
            try:
                conn.execute(f"ROLLBACK TO {savepoint}")
            finally:
                conn.execute(f"RELEASE {savepoint}")
            if reason != "source fund balance is insufficient":
                raise
            failed = self._fail_transfer_request_locked(
                conn,
                req,
                status="failed_source_fund_insufficient",
                reason=reason,
            )
            item = {
                "request_uuid": req["request_uuid"],
                "tx_group_hash": req["tx_group_hash"],
                "chain_branch": req["chain_branch"] if "chain_branch" in req.keys() else self._main_branch_uuid(),
                "reason": reason,
                "status": failed["status"] if failed else "failed_source_fund_insufficient",
            }
            if isinstance(finalization_errors, list):
                finalization_errors.append(item)
            self._audit_log(
                conn,
                "POINTS_TRANSFER_FINALIZATION_FAILED",
                "warning",
                "pending PointsChain transfer failed during proved finalization",
                actor=actor,
                metadata=item,
            )
            return failed
        except Exception:
            try:
                conn.execute(f"ROLLBACK TO {savepoint}")
            finally:
                conn.execute(f"RELEASE {savepoint}")
            raise

    def submit_wallet_transaction(
        self,
        *,
        actor,
        source_wallet_address,
        destination_wallet_address,
        amount_points,
        fee_points=None,
        request_uuid=None,
        memo="",
        signature=None,
    ):
        actor_id = int(actor_value(actor, "id") or 0)
        if actor_id <= 0:
            raise PermissionError("login required")
        amount = int(amount_points or 0)
        if amount <= 0:
            raise ValueError("amount_points must be positive")
        fee = int(fee_points if fee_points not in (None, "") else max(1, amount // 1000))
        if fee < 0:
            raise ValueError("fee_points must be >= 0")
        source = str(source_wallet_address or "").strip().lower()
        destination = str(destination_wallet_address or "").strip().lower()
        if source == destination:
            raise ValueError("source and destination wallets must differ")
        request_uuid = str(request_uuid or uuid.uuid4()).strip()[:120]
        if not request_uuid:
            raise ValueError("request_uuid required")
        payload = {
            "source_wallet_address": source,
            "destination_wallet_address": destination,
            "amount_points": amount,
            "fee_points": fee,
            "memo": str(memo or "")[:240],
            "transaction_type": "wallet_transfer",
        }
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            conn.commit()
            conn.execute("BEGIN IMMEDIATE")
            active_branch = self._canonical_branch_uuid(conn)
            self._assert_canonical_write_branch(conn, active_branch)
            payload["chain_branch"] = active_branch
            request_hash = self._transfer_request_payload_hash(payload)
            tx_group_hash = sha256_text(f"points-chain-transfer:{active_branch}:{request_uuid}:{request_hash}")
            existing = conn.execute(
                "SELECT * FROM points_chain_transfer_requests WHERE request_uuid=?",
                (request_uuid,),
            ).fetchone()
            if existing:
                if str(existing["chain_branch"] if "chain_branch" in existing.keys() else "main") != active_branch:
                    raise ValueError("transaction idempotency key belongs to a non-canonical branch")
                if existing["request_hash"] != request_hash:
                    raise ValueError("transaction idempotency key conflict")
                existing = self._maybe_finalize_transfer_request_locked(conn, existing, actor=actor)
                conn.commit()
                return {
                    "ok": True,
                    "created": False,
                    "tx_group_hash": existing["tx_group_hash"],
                    "transaction_hash": existing["tx_group_hash"],
                    "transaction": self._transfer_request_public_payload(conn, existing),
                    **self._transfer_request_ledgers(conn, request_uuid),
                }
            source_wallet = self._wallet_identity_owner_for_address(conn, source)
            destination_wallet = self._wallet_identity_owner_for_address(conn, destination)
            if not source_wallet or int(source_wallet["user_id"] or 0) != actor_id:
                raise PermissionError("source wallet does not belong to current user")
            if source_wallet["wallet_type"] in {"mint", "burn"} or source_wallet["custody_mode"] == "system":
                raise PermissionError("system wallets cannot be spent by user transaction")
            self._assert_wallet_identity_can_spend(source_wallet, context="wallet transfer")
            source_freeze = self._address_freeze_locked(conn, source)
            if source_freeze:
                raise PermissionError("source wallet is frozen by governance vote")
            provisional_freeze = self._address_provisional_freeze_locked(conn, source)
            if provisional_freeze:
                raise PermissionError("source wallet is temporarily frozen pending governance review")
            if source_wallet["custody_mode"] == "self_custody":
                if not str(signature or "").strip():
                    raise PermissionError("self-custody wallet transaction signature required")
                verify_wallet_transaction_signature(
                    user_id=actor_id,
                    source_wallet_address=source,
                    destination_wallet_address=destination,
                    amount_points=amount,
                    fee_points=fee,
                    request_uuid=request_uuid,
                    memo=str(memo or "")[:240],
                    public_key_jwk=_json_loads(source_wallet["public_key_jwk_json"], {}),
                    signature=str(signature or ""),
                    chain_branch=active_branch,
                    action_type="points_wallet_transfer",
                    signer_key_id=str(source_wallet["public_key_hash"] or ""),
                )
            destination_unowned = 0
            recipient_user_id = actor_id
            if destination_wallet and destination_wallet["user_id"]:
                recipient_user_id = int(destination_wallet["user_id"])
            else:
                destination_unowned = 1
            if destination_wallet and int(destination_wallet["user_id"] or 0) == actor_id and source == destination:
                raise ValueError("source and destination wallets must differ")
            source_available = self._wallet_identity_available_for_address(conn, user_id=actor_id, address=source)
            if source_available < amount + fee:
                raise ValueError("insufficient balance for pending wallet transaction")
            conn.execute(
                """
                INSERT INTO points_chain_transfer_requests (
                    request_uuid, chain_branch, request_hash, tx_group_hash, sender_user_id, recipient_user_id,
                    source_wallet_address, destination_wallet_address, destination_unowned, amount_points, fee_points,
                    transaction_type, source_fund_key, memo,
                    transfer_out_ledger_uuid, transfer_in_ledger_uuid, fee_ledger_uuid, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'wallet_transfer', '', ?, NULL, NULL, NULL, 'pending', ?)
                """,
                (
                    request_uuid,
                    active_branch,
                    request_hash,
                    tx_group_hash,
                    actor_id,
                    recipient_user_id,
                    source,
                    destination,
                    destination_unowned,
                    amount,
                    fee,
                    str(memo or "")[:240],
                    utc_now(),
                ),
            )
            req = conn.execute(
                "SELECT * FROM points_chain_transfer_requests WHERE request_uuid=?",
                (request_uuid,),
            ).fetchone()
            notification_status = self._notify_wallet_transfer_pending(conn, req)
            warnings = [] if notification_status.get("all_sent") else ["notification_delivery_failed"]
            conn.commit()
            return {
                "ok": True,
                "created": True,
                "warnings": warnings,
                "notifications": {"pending": notification_status},
                "tx_group_hash": tx_group_hash,
                "transaction_hash": tx_group_hash,
                "transaction": self._transfer_request_public_payload(conn, req),
                **self._transfer_request_ledgers(conn, request_uuid),
            }
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def list_wallet_transactions(self, *, user_id, limit=50, actor=None):
        viewer_id = int(user_id)
        limit = min(100, max(1, int(limit or 50)))
        root_view = actor_value(actor, "username") == "root"
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            safe_mode = self._safe_mode_status(conn)
            finalization_paused = bool(safe_mode.get("safe_mode"))
            conn.commit()
            conn.execute("BEGIN IMMEDIATE")
            sweep = {"checked_count": 0, "finalized_count": 0, "confirmed_count": 0, "failed_count": 0}
            if root_view and not finalization_paused:
                sweep = self._finalize_proved_pending_transfer_requests_locked(conn, actor=actor, limit=1000)
            if root_view:
                rows = conn.execute(
                    """
                    SELECT *
                    FROM points_chain_transfer_requests
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            else:
                identity_state = self._wallet_identity_state_for_user(conn, viewer_id)
                viewer_addresses = sorted(str(item or "").strip().lower() for item in (identity_state.get("addresses") or set()) if item)
                wallet_clause = ""
                params = [viewer_id, viewer_id]
                if viewer_addresses:
                    placeholders = ", ".join("?" for _ in viewer_addresses)
                    wallet_clause = f" OR source_wallet_address IN ({placeholders}) OR destination_wallet_address IN ({placeholders})"
                    params.extend(viewer_addresses)
                    params.extend(viewer_addresses)
                params.append(limit)
                rows = conn.execute(
                    f"""
                    SELECT *
                    FROM points_chain_transfer_requests
                    WHERE sender_user_id=? OR recipient_user_id=?{wallet_clause}
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    tuple(params),
                ).fetchall()
            finalized_count = 0
            refreshed = []
            row_finalization_errors = []
            for row in rows:
                before = str(row["status"] or "")
                current = row if finalization_paused else self._maybe_finalize_transfer_request_or_mark_failed_locked(
                    conn,
                    row,
                    actor=actor,
                    finalization_errors=row_finalization_errors,
                )
                if before == "pending" and str(current["status"] or "") != "pending":
                    finalized_count += 1
                refreshed.append(current)
            conn.commit()
            transactions = [
                self._transfer_request_member_summary(
                    conn,
                    row,
                    user_id=viewer_id,
                    root_view=root_view,
                    viewer_addresses=viewer_addresses if not root_view else None,
                )
                for row in refreshed
            ]
            if root_view:
                pending_incoming = 0
                pending_outgoing = sum(
                    int(item["amount_points"] or 0) + int(item["fee_points"] or 0)
                    for item in transactions
                    if item["status"] == "pending"
                )
            else:
                pending_incoming = sum(
                    int(item["amount_points"] or 0)
                    for item in transactions
                    if item["direction"] in {"incoming", "self"} and item["status"] == "pending"
                )
                pending_outgoing = sum(
                    int(item["amount_points"] or 0) + int(item["fee_points"] or 0)
                    for item in transactions
                    if item["direction"] in {"outgoing", "self"} and item["status"] == "pending"
                )
            payload = {
                "ok": True,
                "transactions": transactions,
                "summary": {
                    "count": len(transactions),
                    "pending_count": sum(1 for item in transactions if item["status"] == "pending"),
                    "confirmed_count": sum(1 for item in transactions if item["status"] == "confirmed"),
                    "failed_count": sum(1 for item in transactions if str(item["status"]).startswith("failed")),
                    "pending_incoming_points": pending_incoming,
                    "pending_outgoing_points": pending_outgoing,
                    "finalized_count": finalized_count + int(sweep.get("finalized_count") or 0),
                    "batch_checked_count": int(sweep.get("checked_count") or 0),
                    "batch_finalized_count": int(sweep.get("finalized_count") or 0),
                    "batch_confirmed_count": int(sweep.get("confirmed_count") or 0),
                    "batch_failed_count": int(sweep.get("failed_count") or 0),
                    "finalization_error_count": int(sweep.get("finalization_error_count") or 0) + len(row_finalization_errors),
                },
            }
            finalization_errors = list(sweep.get("finalization_errors") or []) + row_finalization_errors
            if finalization_errors:
                payload["warnings"] = [
                    {
                        "code": "transfer_finalization_failed",
                        "message": "部分 proved pending 交易因官方來源基金不足已標記失敗；交易列表仍可載入。",
                        "items": finalization_errors[:20],
                    }
                ]
            if finalization_paused:
                payload["warnings"] = [*list(payload.get("warnings") or []), "chain_safe_mode_active_finalization_paused"]
                payload["recovery"] = safe_mode
            return payload
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def append_trading_reserve_economy_event(
        self,
        conn,
        *,
        reserve_event_uuid,
        delta,
        event_type,
        reason="",
        actor=None,
        source_user_id=None,
        order_id=None,
        fill_id=None,
        points_ledger_uuid=None,
    ):
        delta = int(delta or 0)
        if delta == 0:
            return None, False
        reserve_event_uuid = str(reserve_event_uuid or "").strip()
        if not reserve_event_uuid:
            raise ValueError("reserve event uuid is required")
        event_type = str(event_type or "").strip()
        ignored = {"initial_funding", "walletized_exchange_fund_alignment"}
        if event_type in ignored:
            return None, False
        amount = abs(delta)
        counterparty_address = self._counterparty_user_address(conn, source_user_id) if source_user_id else ""
        if not counterparty_address:
            counterparty_address = f"trading_reserve_event:{reserve_event_uuid}"
        active_branch = self._canonical_branch_uuid(conn)
        bootstrap_economy_layer(conn, chain_secret=self.chain_secret, actor={"role": "system", "id": None}, chain_branch=active_branch)
        metadata = {
            "trading_reserve_event_uuid": reserve_event_uuid,
            "trading_reserve_event_type": event_type,
            "trading_reserve_reason": str(reason or ""),
            "source_user_id": int(source_user_id) if source_user_id else None,
            "order_id": int(order_id) if order_id else None,
            "fill_id": int(fill_id) if fill_id else None,
            "points_ledger_uuid": points_ledger_uuid,
            "walletization_phase": "1B",
            "financial_source_of_truth": "trading_reserve_pool_events",
        }
        if delta > 0:
            if source_user_id and self._economy_external_address_balance(conn, counterparty_address, chain_branch=active_branch) < amount:
                return None, False
            return append_economy_event(
                conn,
                chain_secret=self.chain_secret,
                event_type="trading_reserve_pool_flow",
                transaction_type=event_type,
                source_fund_key=None,
                source_address=counterparty_address,
                destination_fund_key="exchange_fund",
                destination_address=None,
                amount=amount,
                idempotency_key=f"trading_reserve_pool_event:{reserve_event_uuid}",
                metadata=metadata,
                actor=actor,
                chain_branch=active_branch,
            )
        return append_economy_event(
            conn,
            chain_secret=self.chain_secret,
            event_type="trading_reserve_pool_flow",
            transaction_type=event_type,
            source_fund_key="exchange_fund",
            source_address=None,
            destination_fund_key=None,
            destination_address=counterparty_address,
            amount=amount,
            idempotency_key=f"trading_reserve_pool_event:{reserve_event_uuid}",
            metadata=metadata,
            actor=actor,
            chain_branch=active_branch,
        )

    def _sync_exchange_fund_transfer_to_trading_reserve_pool(self, conn, *, req, amount, actor=None):
        if not table_columns(conn, "trading_reserve_pool") or not table_columns(conn, "trading_reserve_pool_events"):
            return None
        event_uuid = f"pointschain_exchange_fund_transfer:{req['request_uuid']}"
        existing = conn.execute(
            "SELECT * FROM trading_reserve_pool_events WHERE event_uuid=?",
            (event_uuid,),
        ).fetchone()
        if existing:
            return existing
        now = utc_now()
        row = conn.execute("SELECT * FROM trading_reserve_pool WHERE id=1").fetchone()
        if not row:
            conn.execute(
                "INSERT INTO trading_reserve_pool (id, balance_points, updated_at, updated_by) VALUES (1, 0, ?, ?)",
                (now, int(actor_value(actor, "id")) if actor_value(actor, "id") else None),
            )
            balance = 0
        else:
            balance = int(row["balance_points"] or 0)
        next_balance = balance + int(amount or 0)
        conn.execute(
            "UPDATE trading_reserve_pool SET balance_points=?, updated_at=?, updated_by=? WHERE id=1",
            (next_balance, now, int(actor_value(actor, "id")) if actor_value(actor, "id") else None),
        )
        conn.execute(
            """
            INSERT INTO trading_reserve_pool_events (
                event_uuid, delta_points, balance_after, event_type, reason,
                actor_user_id, source_user_id, order_id, fill_id, points_ledger_uuid, created_at
            ) VALUES (?, ?, ?, 'official_exchange_fund_replenishment', 'POINTSCHAIN_EXCHANGE_FUND_REPLENISHMENT', ?, NULL, NULL, NULL, NULL, ?)
            """,
            (
                event_uuid,
                int(amount or 0),
                next_balance,
                int(actor_value(actor, "id")) if actor_value(actor, "id") else None,
                now,
            ),
        )
        return conn.execute(
            "SELECT * FROM trading_reserve_pool_events WHERE event_uuid=?",
            (event_uuid,),
        ).fetchone()

    def _backfill_walletized_ledger_events(self, conn, *, limit=1000):
        self.ensure_schema(conn)
        bootstrap_economy_layer(conn, chain_secret=self.chain_secret, actor={"role": "system", "id": None})
        rows = conn.execute(
            """
            SELECT l.*
            FROM points_ledger l
            WHERE l.status='confirmed'
              AND NOT EXISTS (
                SELECT 1 FROM points_economy_events e
                WHERE e.idempotency_key='walletized_ledger:' || l.ledger_uuid
              )
            ORDER BY l.id ASC
            LIMIT ?
            """,
            (max(1, int(limit or 1000)),),
        ).fetchall()
        created = 0
        skipped = 0
        for row in rows:
            event, was_created = self._append_walletized_economy_event(
                conn,
                ledger_row=row,
                public_metadata=_json_loads(row["public_metadata_json"], {}),
                actor={"role": "system", "id": None},
            )
            if event and was_created:
                created += 1
            else:
                skipped += 1
        return {"checked": len(rows), "created": created, "skipped": skipped, "complete": len(rows) < max(1, int(limit or 1000))}

    def _ledger_wallet_flow_for_read(self, conn, row):
        public_metadata = _json_loads(row["public_metadata_json"], {})
        snapshot = public_metadata.get("wallet_flow_snapshot") if isinstance(public_metadata, dict) else None
        if isinstance(snapshot, dict):
            return dict(snapshot)
        return self._legacy_ledger_wallet_flow_descriptor(conn, row, public_metadata=public_metadata)

    def _serialize_ledger_for_read(self, conn, row, *, include_user_id=False):
        data = self.serialize_ledger(row, include_user_id=include_user_id)
        data["wallet_flow"] = self._ledger_wallet_flow_for_read(conn, row)
        return data

    def _balance_column(self, currency_type):
        normalize_currency_type(currency_type)
        return "soft_balance"

    def _frozen_column(self, currency_type):
        normalize_currency_type(currency_type)
        return "soft_frozen"

    def _earned_column(self, currency_type):
        normalize_currency_type(currency_type)
        return "total_soft_earned"

    def _spent_column(self, currency_type):
        normalize_currency_type(currency_type)
        return "total_soft_spent"

    def _wallet_statement_deltas(self, *, direction, amount, action_type, public_metadata=None):
        """Return display/reporting income and expense deltas for a ledger row.

        Balance replay still uses the full ledger amount. These deltas drive
        "累計收支", where spot-trade principal is an asset swap and should not
        be counted as user spending/income.
        """
        direction = str(direction or "")
        action = str(action_type or "")
        amount = int(amount or 0)
        metadata = public_metadata if isinstance(public_metadata, dict) else {}

        def meta_int(*keys, default=None):
            for key in keys:
                if key not in metadata or metadata.get(key) is None:
                    continue
                try:
                    return int(metadata.get(key) or 0)
                except Exception:
                    continue
            return default

        if action == "trading_spot_buy":
            return 0, max(0, meta_int("statement_spent_points", "actual_expense_points", default=0) or 0)

        if action == "trading_spot_sell":
            earned = meta_int("statement_earned_points", default=None)
            spent = meta_int("statement_spent_points", default=None)
            if earned is not None or spent is not None:
                return max(0, earned or 0), max(0, spent or 0)
            realized_pnl = meta_int("realized_pnl_points", "net_pnl_points", default=None)
            if realized_pnl is not None:
                return max(0, realized_pnl), max(0, -realized_pnl)
            return 0, 0

        if direction in {"credit", "transfer_in"}:
            return amount, 0
        if direction in {"debit", "transfer_out", "reverse"}:
            return 0, amount
        return 0, 0

    def _last_ledger_hash(self, conn, *, branch_uuid=None):
        branch = str(branch_uuid or self._canonical_branch_uuid(conn) or self._main_branch_uuid())
        row = conn.execute("SELECT ledger_hash FROM points_ledger WHERE chain_branch=? ORDER BY id DESC LIMIT 1", (branch,)).fetchone()
        return row["ledger_hash"] if row else None

    def _existing_idempotent(self, conn, idempotency_key):
        if not idempotency_key:
            return None
        return conn.execute("SELECT * FROM points_ledger WHERE idempotency_key=?", (idempotency_key,)).fetchone()

    def _admin_account_rows(self, conn):
        cols = table_columns(conn, "users")
        if "id" not in cols or "username" not in cols or "role" not in cols:
            return []
        status_filter = "AND COALESCE(status, 'active')='active'" if "status" in cols else ""
        return conn.execute(
            f"""
            SELECT id, username, role FROM users
            WHERE username<>'root'
              AND role IN ('manager', 'super_admin')
              {status_filter}
            ORDER BY id ASC
            """
        ).fetchall()

    def _genesis_user_account_rows(self, conn, *, default_only=False):
        cols = table_columns(conn, "users")
        if "id" not in cols or "username" not in cols or "role" not in cols:
            return []
        status_filter = "AND COALESCE(status, 'active')='active'" if "status" in cols else ""
        default_filter = "AND username='test'" if default_only else ""
        return conn.execute(
            f"""
            SELECT id, username, role FROM users
            WHERE username<>'root'
              AND role NOT IN ('manager', 'super_admin')
              {default_filter}
              {status_filter}
            ORDER BY id ASC
            """
        ).fetchall()

    def award_signup_bonus(self, *, user_id, actor=None):
        return self.record_transaction(
            user_id=user_id,
            currency_type=DISPLAY_CURRENCY,
            direction="credit",
            amount=SIGNUP_BONUS_POINTS,
            action_type="new_user_signup_bonus",
            reference_type="user_registration",
            reference_id=str(user_id),
            idempotency_key=f"new_user_signup_bonus:{int(user_id)}",
            reason="new user signup bonus",
            public_metadata={"grant": "signup_bonus", "amount": SIGNUP_BONUS_POINTS},
            actor=actor,
        )

    def award_birthday_gift(self, *, user_id, birthday_year, birthday_date=None, actor=None):
        year = int(birthday_year)
        return self.record_transaction(
            user_id=user_id,
            currency_type=DISPLAY_CURRENCY,
            direction="credit",
            amount=BIRTHDAY_GIFT_POINTS,
            action_type="birthday_gift",
            reference_type="birthday_year",
            reference_id=str(year),
            idempotency_key=f"birthday_gift:{year}:{int(user_id)}",
            reason=f"birthday gift {year}",
            public_metadata={
                "grant": "birthday_gift",
                "birthday_year": year,
                "birthday_date": str(birthday_date or ""),
                "amount": BIRTHDAY_GIFT_POINTS,
            },
            actor=actor,
        )

    def award_admin_initial_grant(self, *, user_id, actor=None, require_wallet=True):
        deferred = self._initial_grant_ready_or_deferred(
            user_id=user_id,
            expected_action_type="admin_initial_grant",
            require_wallet=require_wallet,
        )
        if deferred:
            return deferred
        return self.record_transaction(
            user_id=user_id,
            currency_type=DISPLAY_CURRENCY,
            direction="credit",
            amount=ADMIN_INITIAL_POINTS,
            action_type="admin_initial_grant",
            reference_type="genesis_admin_allocation",
            reference_id=str(user_id),
            idempotency_key=f"admin_initial_grant:{int(user_id)}",
            reason="admin genesis allocation",
            public_metadata={"grant": "admin_initial", "amount": ADMIN_INITIAL_POINTS},
            actor=actor,
        )

    def award_user_initial_grant(self, *, user_id, actor=None, require_wallet=True):
        deferred = self._initial_grant_ready_or_deferred(
            user_id=user_id,
            expected_action_type="user_initial_grant",
            require_wallet=require_wallet,
        )
        if deferred:
            return deferred
        return self.record_transaction(
            user_id=user_id,
            currency_type=DISPLAY_CURRENCY,
            direction="credit",
            amount=USER_INITIAL_POINTS,
            action_type="user_initial_grant",
            reference_type="genesis_user_allocation",
            reference_id=str(user_id),
            idempotency_key=f"user_initial_grant:{int(user_id)}",
            reason="user genesis allocation",
            public_metadata={"grant": "user_initial", "amount": USER_INITIAL_POINTS},
            actor=actor,
        )

    def award_initial_grants_after_wallet_onboarding(self, *, user_id, actor=None):
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            status = self.wallet_initial_grant_status(conn, user_id)
        finally:
            conn.close()
        if not status.get("required"):
            return {"ok": True, "created": [], "created_count": 0, "deferred": False, "initial_grant": status}
        if status.get("deferred_until_wallet"):
            return {"ok": True, "created": [], "created_count": 0, "deferred": True, "initial_grant": status}
        if status.get("action_type") == "admin_initial_grant":
            result = self.award_admin_initial_grant(user_id=user_id, actor=actor)
        elif status.get("action_type") == "user_initial_grant":
            result = self.award_user_initial_grant(user_id=user_id, actor=actor)
        else:
            return {"ok": True, "created": [], "created_count": 0, "deferred": False, "initial_grant": status}
        created = [{
            "user_id": int(user_id),
            "grant": status.get("grant") or "",
            "amount": int(status.get("amount") or 0),
            "ledger_hash": (result.get("ledger") or {}).get("ledger_hash", ""),
        }] if result.get("created") else []
        return {
            "ok": True,
            "created": created,
            "created_count": len(created),
            "deferred": bool(result.get("deferred")),
            "initial_grant": (result.get("initial_grant") or status),
            "ledger": result.get("ledger"),
            "wallet": result.get("wallet"),
        }

    def current_salary_week(self):
        year, week, _weekday = datetime.now(timezone.utc).isocalendar()
        return f"{int(year)}-W{int(week):02d}"

    def award_admin_weekly_salary(self, *, user_id, salary_week=None, actor=None):
        week = salary_week or self.current_salary_week()
        return self.record_transaction(
            user_id=user_id,
            currency_type=DISPLAY_CURRENCY,
            direction="credit",
            amount=ADMIN_WEEKLY_SALARY_POINTS,
            action_type="admin_weekly_salary",
            reference_type="admin_salary",
            reference_id=week,
            idempotency_key=f"admin_weekly_salary:{week}:{int(user_id)}",
            reason=f"admin weekly salary {week}",
            public_metadata={"grant": "admin_weekly_salary", "salary_week": week, "amount": ADMIN_WEEKLY_SALARY_POINTS},
            actor=actor,
        )

    def bootstrap_admin_initial_grants(self, *, actor=None, seal_genesis=True, require_wallet=True):
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            admins = [dict(row) for row in self._admin_account_rows(conn)]
            has_blocks = conn.execute("SELECT 1 FROM points_chain_blocks LIMIT 1").fetchone() is not None
            users = [
                dict(row)
                for row in self._genesis_user_account_rows(conn, default_only=has_blocks)
            ]
        finally:
            conn.close()
        created = []
        deferred = []
        for admin in admins:
            result = self.award_admin_initial_grant(user_id=admin["id"], actor=actor, require_wallet=require_wallet)
            if result.get("created"):
                created.append({"user_id": admin["id"], "username": admin["username"], "role": admin["role"], "grant": "admin_initial", "amount": ADMIN_INITIAL_POINTS})
            elif result.get("deferred"):
                deferred.append({"user_id": admin["id"], "username": admin["username"], "role": admin["role"], "grant": "admin_initial", "amount": ADMIN_INITIAL_POINTS, "reason": "wallet_required"})
        for user in users:
            result = self.award_user_initial_grant(user_id=user["id"], actor=actor, require_wallet=require_wallet)
            if result.get("created"):
                created.append({"user_id": user["id"], "username": user["username"], "role": user["role"], "grant": "user_initial", "amount": USER_INITIAL_POINTS})
            elif result.get("deferred"):
                deferred.append({"user_id": user["id"], "username": user["username"], "role": user["role"], "grant": "user_initial", "amount": USER_INITIAL_POINTS, "reason": "wallet_required"})
        sealed = None
        if seal_genesis and created and not has_blocks:
            sealed = self.seal_block(actor=actor, limit=500)
        return {"ok": True, "created": created, "created_count": len(created), "deferred": deferred, "deferred_count": len(deferred), "sealed": sealed}

    def award_admin_weekly_salaries(self, *, salary_week=None, actor=None):
        week = salary_week or self.current_salary_week()
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            admins = [dict(row) for row in self._admin_account_rows(conn)]
        finally:
            conn.close()
        created = []
        for admin in admins:
            result = self.award_admin_weekly_salary(user_id=admin["id"], salary_week=week, actor=actor)
            if result.get("created"):
                created.append({"user_id": admin["id"], "username": admin["username"], "role": admin["role"]})
        return {"ok": True, "salary_week": week, "created": created, "created_count": len(created)}

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
        self._assert_chain_writable(conn, "ledger transaction")
        currency_type = normalize_currency_type(currency_type)
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
        if wallet["wallet_status"] == "frozen" and direction in {"credit", "debit", "freeze"}:
            raise ValueError("wallet is frozen")
        if wallet["wallet_status"] == "limited" and direction in {"debit", "transfer_out"}:
            raise ValueError("wallet is limited")

        balance_col = self._balance_column(currency_type)
        frozen_col = self._frozen_column(currency_type)
        earned_col = self._earned_column(currency_type)
        spent_col = self._spent_column(currency_type)
        public_metadata, wallet_flow_snapshot = self._ledger_metadata_with_wallet_flow_snapshot(
            conn,
            user_id=user_id,
            direction=direction,
            action_type=action_type,
            public_metadata=public_metadata or {},
        )
        account_balance_before = int(wallet[balance_col])
        account_frozen_before = int(wallet[frozen_col])
        exclude_pending_request_uuid = ""
        if action_type in {"wallet_transfer_out", "wallet_transfer_fee"} and isinstance(public_metadata, dict):
            exclude_pending_request_uuid = str(
                public_metadata.get("pending_request_uuid") or public_metadata.get("request_uuid") or ""
            ).strip()
        active_branch = self._canonical_branch_uuid(conn)
        identity_balances = self._wallet_identity_balances_for_user(
            conn,
            user_id,
            include_pending=direction != "unfreeze",
            exclude_request_uuid=exclude_pending_request_uuid or None,
            branch_uuid=active_branch,
        )
        if identity_balances.get("has_identity"):
            identity_balance_map = identity_balances.get("balances") or {}
            account_balance_before = sum(int(item.get("balance") or 0) for item in identity_balance_map.values())
            account_frozen_before = sum(int(item.get("frozen") or 0) for item in identity_balance_map.values())
            ledger_address = ""
            if direction in {"credit", "transfer_in"}:
                ledger_address = str(wallet_flow_snapshot.get("destination_wallet_address") or "")
            elif direction in {"debit", "transfer_out", "reverse", "freeze"}:
                ledger_address = str(wallet_flow_snapshot.get("source_wallet_address") or "")
            elif direction == "unfreeze":
                ledger_address = str(wallet_flow_snapshot.get("source_wallet_address") or wallet_flow_snapshot.get("destination_wallet_address") or "")
            if ledger_address not in identity_balance_map:
                ledger_address = str(identity_balances.get("primary_address") or "")
            if not ledger_address:
                raise ValueError("active wallet identity is required")
            if direction in {"debit", "transfer_out", "reverse", "freeze"}:
                self._assert_address_not_frozen_for_outgoing_locked(
                    conn,
                    ledger_address,
                    action=action_type or "ledger outgoing write",
                )
            active = identity_balance_map.get(ledger_address, {"balance": 0, "frozen": 0})
            balance_before = int(active.get("balance") or 0)
            frozen_before = int(active.get("frozen") or 0)
        else:
            balance_before = account_balance_before
            frozen_before = account_frozen_before
        balance_after = balance_before
        frozen_after = frozen_before
        account_balance_after = account_balance_before
        account_frozen_after = account_frozen_before
        earned_delta = 0
        spent_delta = 0

        if direction in {"credit", "transfer_in"}:
            balance_after += amount
            account_balance_after += amount
        elif direction in {"debit", "transfer_out", "reverse"}:
            if balance_before < amount:
                raise ValueError("insufficient balance")
            balance_after -= amount
            account_balance_after -= amount
        elif direction == "freeze":
            if balance_before < amount:
                raise ValueError("insufficient balance")
            balance_after -= amount
            frozen_after += amount
            account_balance_after -= amount
            account_frozen_after += amount
        elif direction == "unfreeze":
            if frozen_before < amount:
                raise ValueError("insufficient frozen balance")
            balance_after += amount
            frozen_after -= amount
            account_balance_after += amount
            account_frozen_after -= amount

        earned_delta, spent_delta = self._wallet_statement_deltas(
            direction=direction,
            amount=amount,
            action_type=action_type,
            public_metadata=public_metadata,
        )
        public_json = _metadata_json_checked(public_metadata, label="public_metadata")
        private_json = _metadata_json_checked(private_metadata or {}, label="private_metadata")
        meta_hash = metadata_hash(public_metadata, private_metadata or {}, sensitive_metadata_encrypted or "")
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
            "chain_branch": active_branch,
            "previous_ledger_hash": self._last_ledger_hash(conn, branch_uuid=active_branch),
            "created_at": now,
        }
        ledger_hash = compute_ledger_hash(ledger_data)
        cur = conn.execute(
            """
            INSERT INTO points_ledger (
                ledger_uuid, chain_branch, user_id, public_account_id, currency_type, direction, amount,
                balance_before, balance_after, action_type, reference_type, reference_id,
                idempotency_key, reason, public_metadata_json, private_metadata_json,
                sensitive_metadata_encrypted, metadata_hash, previous_ledger_hash, ledger_hash,
                risk_flag, risk_score, created_by, created_by_role, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'confirmed', ?)
            """,
            (
                ledger_uuid,
                ledger_data["chain_branch"],
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
                int(actor_value(actor, "id")) if actor_value(actor, "id") else None,
                actor_value(actor, "role"),
                now,
            ),
        )
        conn.execute(
            f"""
            UPDATE points_wallets
            SET {balance_col}=?, {frozen_col}=?, {earned_col}={earned_col}+?, {spent_col}={spent_col}+?, updated_at=?
            WHERE user_id=?
            """,
            (account_balance_after, account_frozen_after, earned_delta, spent_delta, now, int(user_id)),
        )
        row = conn.execute("SELECT * FROM points_ledger WHERE id=?", (cur.lastrowid,)).fetchone()
        economy_event, economy_created = self._append_walletized_economy_event(
            conn,
            ledger_row=row,
            public_metadata=public_metadata,
            actor=actor,
        )
        self._audit_log(
            conn,
            "LEDGER_APPEND",
            "info",
            f"{direction} {amount} {DISPLAY_CURRENCY} for user {user_id}",
            actor=actor,
            target_user_id=int(user_id),
            ledger_id=row["id"],
            metadata={
                "currency_type": DISPLAY_CURRENCY,
                "action_type": action_type,
                "reference_type": reference_type,
                "reference_id": reference_id,
                "walletized_economy_event_uuid": economy_event["event_uuid"] if economy_event else "",
                "walletized_economy_event_created": bool(economy_created),
                "wallet_flow_snapshot": wallet_flow_snapshot,
            },
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

    def sanction_wallet(
        self,
        *,
        actor,
        user_id,
        wallet_status=None,
        risk_level=None,
        reason="",
        freeze_amount=0,
        unfreeze_amount=0,
    ):
        raise PermissionError("blockchain_permission_model: direct wallet sanctions are disabled; use governance-voted address freeze, scam label, or emergency branch instead")

    def _rule_for_key(self, conn, rule_key):
        return conn.execute("SELECT * FROM points_rules WHERE rule_key=? AND enabled=1", (rule_key,)).fetchone()

    def earn_points(self, *, user_id, rule_key, reference_type=None, reference_id=None, idempotency_key=None, metadata=None, actor=None):
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            conn.commit()
            conn.execute("BEGIN IMMEDIATE")
            self._assert_chain_writable(conn, "earn points")
            rule = self._rule_for_key(conn, rule_key)
            if not rule:
                raise ValueError("points rule not found or disabled")
            if rule["direction"] != "credit":
                raise ValueError("rule is not a credit rule")
            if rule["requires_admin_review"]:
                raise PermissionError("blockchain_permission_model: pending reward review is disabled")
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

    def _serialize_service_fee_charge(self, row):
        if not row:
            return None
        return {
            "id": int(row["id"]),
            "charge_uuid": row["charge_uuid"],
            "chain_branch": row["chain_branch"] if "chain_branch" in row.keys() else self._main_branch_uuid(),
            "user_id": int(row["user_id"]),
            "item_key": row["item_key"],
            "quantity": int(row["quantity"] or 0),
            "amount_points": int(row["amount_points"] or 0),
            "currency_type": display_currency_type(row["currency_type"]),
            "source_wallet_address": row["source_wallet_address"] or "",
            "status": row["status"],
            "idempotency_key": row["idempotency_key"] or "",
            "freeze_ledger_uuid": row["freeze_ledger_uuid"] or "",
            "unfreeze_ledger_uuid": row["unfreeze_ledger_uuid"] or "",
            "debit_ledger_uuid": row["debit_ledger_uuid"] or "",
            "batch_uuid": row["batch_uuid"] or "",
            "reference_type": row["reference_type"] or "",
            "reference_id": row["reference_id"] or "",
            "metadata": _json_loads(row["metadata_json"], {}),
            "created_at": row["created_at"],
            "settled_at": row["settled_at"],
            "cancelled_at": row["cancelled_at"],
        }

    def _service_fee_charge_by_idempotency(self, conn, idempotency_key):
        key = str(idempotency_key or "").strip()
        if not key:
            return None
        return conn.execute(
            "SELECT * FROM points_service_fee_charges WHERE idempotency_key=?",
            (key,),
        ).fetchone()

    def _service_fee_charge_by_uuid(self, conn, charge_uuid):
        charge_uuid = str(charge_uuid or "").strip()
        if not charge_uuid:
            return None
        return conn.execute(
            "SELECT * FROM points_service_fee_charges WHERE charge_uuid=?",
            (charge_uuid,),
        ).fetchone()

    def _service_fee_reserved_rows(self, conn, *, user_id, source_wallet_address=None, chain_branch=None):
        source_address = str(source_wallet_address or "").strip().lower()
        branch = str(chain_branch or self._canonical_branch_uuid(conn) or self._main_branch_uuid())
        return conn.execute(
            """
            SELECT * FROM points_service_fee_charges
            WHERE user_id=? AND source_wallet_address=? AND status='reserved' AND chain_branch=?
            ORDER BY id ASC
            """,
            (int(user_id), source_address, branch),
        ).fetchall()

    def _service_fee_reserved_total(self, conn, *, user_id, source_wallet_address=None, chain_branch=None):
        source_address = str(source_wallet_address or "").strip().lower()
        branch = str(chain_branch or self._canonical_branch_uuid(conn) or self._main_branch_uuid())
        row = conn.execute(
            """
            SELECT COALESCE(SUM(amount_points), 0) AS total
            FROM points_service_fee_charges
            WHERE user_id=? AND source_wallet_address=? AND status='reserved' AND chain_branch=?
            """,
            (int(user_id), source_address, branch),
        ).fetchone()
        return int((row["total"] if row else 0) or 0)

    def _service_fee_existing_response(self, conn, *, charge_row, item=None):
        freeze_row = conn.execute(
            "SELECT * FROM points_ledger WHERE ledger_uuid=?",
            (charge_row["freeze_ledger_uuid"] or "",),
        ).fetchone()
        unfreeze_row = conn.execute(
            "SELECT * FROM points_ledger WHERE ledger_uuid=?",
            (charge_row["unfreeze_ledger_uuid"] or "",),
        ).fetchone()
        debit_row = conn.execute(
            "SELECT * FROM points_ledger WHERE ledger_uuid=?",
            (charge_row["debit_ledger_uuid"] or "",),
        ).fetchone()
        reserved_total = self._service_fee_reserved_total(
            conn,
            user_id=int(charge_row["user_id"]),
            source_wallet_address=charge_row["source_wallet_address"] or "",
            chain_branch=charge_row["chain_branch"] if "chain_branch" in charge_row.keys() else None,
        )
        return {
            "ok": True,
            "created": False,
            "settlement_layer": "service_fee_subledger",
            "settlement_policy": "freeze_then_batch_debit",
            "batch_threshold_points": SERVICE_BATCH_SETTLEMENT_MIN_POINTS,
            "charge": self._serialize_service_fee_charge(charge_row),
            "ledger": self.serialize_ledger(freeze_row) if freeze_row else None,
            "settlement": {
                "created": False,
                "status": charge_row["status"],
                "batch_uuid": charge_row["batch_uuid"] or "",
                "reserved_total_points": reserved_total,
                "settled_amount_points": int(charge_row["amount_points"] or 0) if charge_row["status"] == "settled" else 0,
                "unfreeze_ledger": self.serialize_ledger(unfreeze_row) if unfreeze_row else None,
                "debit_ledger": self.serialize_ledger(debit_row) if debit_row else None,
            },
            "wallet": self.wallet_payload_for_read(conn, int(charge_row["user_id"])),
            "item": dict(item) if item else None,
        }

    def _verify_service_fee_wallet_signature(self, *, conn, user_id, source_wallet_address, item_key, quantity, amount_points, request_uuid, reference_type, reference_id, signature, chain_branch=None):
        source_address = str(source_wallet_address or "").strip().lower()
        if not source_address:
            return False
        wallet = self._wallet_identity_row_for_user_address(conn, user_id, source_address, active_only=True)
        if not wallet:
            return False
        if str(wallet["custody_mode"] or "") != "self_custody":
            return False
        if not str(signature or "").strip():
            raise PermissionError("self-custody wallet service fee signature required")
        verify_wallet_service_fee_signature(
            user_id=user_id,
            source_wallet_address=source_address,
            item_key=item_key,
            quantity=quantity,
            amount_points=amount_points,
            request_uuid=request_uuid,
            reference_type=reference_type or "",
            reference_id=reference_id or "",
            public_key_jwk=_json_loads(wallet["public_key_jwk_json"], {}),
            signature=signature,
            chain_branch=chain_branch or self._canonical_branch_uuid(conn),
            action_type="points_service_fee_reserve",
            signer_key_id=str(wallet["public_key_hash"] or ""),
        )
        return True

    def _settle_service_fee_charges_locked(self, conn, *, user_id, source_wallet_address=None, force=False, actor=None, reason="threshold"):
        source_address = str(source_wallet_address or "").strip().lower()
        active_branch = self._canonical_branch_uuid(conn)
        rows = self._service_fee_reserved_rows(conn, user_id=user_id, source_wallet_address=source_address, chain_branch=active_branch)
        total = sum(int(row["amount_points"] or 0) for row in rows)
        if total <= 0:
            return {
                "created": False,
                "status": "none",
                "reserved_total_points": 0,
                "threshold_points": SERVICE_BATCH_SETTLEMENT_MIN_POINTS,
                "reason": "no_reserved_charges",
            }
        if not force and total < SERVICE_BATCH_SETTLEMENT_MIN_POINTS:
            return {
                "created": False,
                "status": "reserved",
                "reserved_total_points": total,
                "threshold_points": SERVICE_BATCH_SETTLEMENT_MIN_POINTS,
                "reason": "below_threshold",
            }
        batch_uuid = str(uuid.uuid4())
        charge_uuids = [row["charge_uuid"] for row in rows]
        metadata = {
            "settlement_layer": "service_fee_subledger",
            "settlement_policy": "freeze_then_batch_debit",
            "batch_uuid": batch_uuid,
            "batch_reason": str(reason or "threshold")[:80],
            "charge_count": len(rows),
            "charge_uuid_hash": sha256_text(canonical_json(charge_uuids)),
            "charge_uuids_sample": charge_uuids[:20],
            "source_wallet_address": source_address,
            "chain_branch": active_branch,
            "chain_fee_policy": "batched_l1_debit_no_per_service_fee",
            "batch_threshold_points": SERVICE_BATCH_SETTLEMENT_MIN_POINTS,
        }
        unfreeze_row, _unfreeze_created = self._record_transaction(
            conn,
            user_id=user_id,
            currency_type=DISPLAY_CURRENCY,
            direction="unfreeze",
            amount=total,
            action_type="service_fee_batch_unfreeze",
            reference_type="service_fee_batch",
            reference_id=batch_uuid,
            idempotency_key=f"service_fee_batch:{batch_uuid}:unfreeze",
            reason="service fee batch settlement unfreeze",
            public_metadata=metadata,
            actor=actor,
        )
        debit_row, _debit_created = self._record_transaction(
            conn,
            user_id=user_id,
            currency_type=DISPLAY_CURRENCY,
            direction="debit",
            amount=total,
            action_type="service_fee_batch_debit",
            reference_type="service_fee_batch",
            reference_id=batch_uuid,
            idempotency_key=f"service_fee_batch:{batch_uuid}:debit",
            reason="service fee batch settlement debit",
            public_metadata=metadata,
            actor=actor,
        )
        settled_at = utc_now()
        conn.execute(
            f"""
            UPDATE points_service_fee_charges
            SET status='settled', batch_uuid=?, unfreeze_ledger_uuid=?, debit_ledger_uuid=?, settled_at=?
            WHERE id IN ({", ".join("?" for _ in rows)}) AND status='reserved'
            """,
            (
                batch_uuid,
                unfreeze_row["ledger_uuid"],
                debit_row["ledger_uuid"],
                settled_at,
                *[int(row["id"]) for row in rows],
            ),
        )
        return {
            "created": True,
            "status": "settled",
            "batch_uuid": batch_uuid,
            "settled_amount_points": total,
            "reserved_total_points": 0,
            "threshold_points": SERVICE_BATCH_SETTLEMENT_MIN_POINTS,
            "charge_count": len(rows),
            "charge_uuid_hash": metadata["charge_uuid_hash"],
            "unfreeze_ledger": self.serialize_ledger(unfreeze_row),
            "debit_ledger": self.serialize_ledger(debit_row),
        }

    def spend_points(self, *, user_id, item_key, quantity=1, reference_type=None, reference_id=None, idempotency_key=None, metadata=None, actor=None, override_amount=None, source_wallet_address=None, request_uuid=None, signature=None, chain_enabled=True):
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            conn.commit()
            conn.execute("BEGIN IMMEDIATE")
            self._assert_chain_writable(conn, "spend points")
            active_branch = self._canonical_branch_uuid(conn)
            self._assert_canonical_write_branch(conn, active_branch)
            item = conn.execute("SELECT * FROM economy_price_catalog WHERE item_key=? AND enabled=1", (item_key,)).fetchone()
            if not item:
                raise ValueError("price catalog item not found or disabled")
            quantity = max(1, int(quantity or 1))
            if override_amount is not None:
                amount = int(override_amount)
            else:
                amount = int(item["base_price"]) * quantity
            if amount <= 0:
                raise ValueError("amount must be positive")
            metadata = dict(metadata or {})
            source_address = str(source_wallet_address or metadata.get("source_wallet_address") or "").strip().lower()
            if chain_enabled:
                if source_address:
                    source_wallet = self._wallet_identity_row_for_user_address(conn, user_id, source_address, active_only=True)
                    if not source_wallet:
                        raise ValueError("source wallet does not belong to current user")
                    self._assert_wallet_identity_can_spend(source_wallet, context="service fee")
                    available = self._wallet_identity_available_for_address(conn, user_id=int(user_id), address=source_address)
                    if available < amount:
                        raise ValueError("insufficient balance")
                    metadata["source_wallet_address"] = source_address
                else:
                    primary_address = self._primary_wallet_address_for_read(conn, user_id)
                    if primary_address:
                        source_address = str(primary_address or "").strip().lower()
                        primary_wallet = self._wallet_identity_row_for_user_address(conn, user_id, source_address, active_only=True)
                        if primary_wallet:
                            self._assert_wallet_identity_can_spend(primary_wallet, context="service fee")
                        metadata["source_wallet_address"] = source_address
            else:
                source_address = ""
                metadata.pop("source_wallet_address", None)
                metadata["points_chain_enabled"] = False
            spend_bucket = datetime.now(timezone.utc).strftime("%Y%m%d%H%M")
            effective_idempotency_key = idempotency_key or f"spend:{user_id}:{item_key}:{quantity}:{spend_bucket}"
            existing_charge = self._service_fee_charge_by_idempotency(conn, effective_idempotency_key)
            if existing_charge:
                if str(existing_charge["chain_branch"] if "chain_branch" in existing_charge.keys() else self._main_branch_uuid()) != active_branch:
                    raise ValueError("service fee idempotency key belongs to a non-canonical branch")
                conn.commit()
                return self._service_fee_existing_response(conn, charge_row=existing_charge, item=item)
            charge_uuid = str(request_uuid or uuid.uuid4()).strip()[:120]
            if not charge_uuid:
                raise ValueError("request_uuid is required")
            existing_uuid = self._service_fee_charge_by_uuid(conn, charge_uuid)
            if existing_uuid:
                if str(existing_uuid["chain_branch"] if "chain_branch" in existing_uuid.keys() else self._main_branch_uuid()) != active_branch:
                    raise ValueError("service fee request_uuid belongs to a non-canonical branch")
                if existing_uuid["idempotency_key"] == effective_idempotency_key:
                    conn.commit()
                    return self._service_fee_existing_response(conn, charge_row=existing_uuid, item=item)
                raise ValueError("service fee request_uuid conflict")
            reference_type = reference_type or "price_catalog"
            reference_id = reference_id or item_key
            if chain_enabled:
                self._verify_service_fee_wallet_signature(
                    conn=conn,
                    user_id=user_id,
                    source_wallet_address=source_address,
                    item_key=item_key,
                    quantity=quantity,
                    amount_points=amount,
                    request_uuid=charge_uuid,
                    reference_type=reference_type,
                    reference_id=reference_id,
                    signature=signature,
                    chain_branch=active_branch,
                )
            public_metadata = {
                "item_key": item_key,
                "quantity": quantity,
                "settlement_layer": "service_fee_subledger",
                "settlement_policy": "freeze_then_batch_debit",
                "batch_threshold_points": SERVICE_BATCH_SETTLEMENT_MIN_POINTS,
                "chain_fee_policy": "batched_l1_debit_no_per_service_fee",
                "service_fee_charge_uuid": charge_uuid,
                **metadata,
            }
            row, created = self._record_transaction(
                conn,
                user_id=user_id,
                currency_type=item["currency_type"],
                direction="freeze",
                amount=amount,
                action_type=f"service_fee_reserve:{item_key}",
                reference_type=reference_type,
                reference_id=reference_id,
                idempotency_key=f"service_fee_reserve:{charge_uuid}",
                reason=f"reserve service fee:{item['item_name']}",
                public_metadata=public_metadata,
                actor=actor,
            )
            conn.execute(
                """
                INSERT INTO points_service_fee_charges (
                    charge_uuid, chain_branch, user_id, item_key, quantity, amount_points, currency_type,
                    source_wallet_address, status, idempotency_key, freeze_ledger_uuid,
                    reference_type, reference_id, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'reserved', ?, ?, ?, ?, ?, ?)
                """,
                (
                    charge_uuid,
                    active_branch,
                    int(user_id),
                    item_key,
                    quantity,
                    amount,
                    normalize_currency_type(item["currency_type"]),
                    source_address,
                    effective_idempotency_key,
                    row["ledger_uuid"],
                    reference_type,
                    str(reference_id or ""),
                    _metadata_json_checked(metadata, label="service fee metadata"),
                    utc_now(),
                ),
            )
            charge_row = self._service_fee_charge_by_uuid(conn, charge_uuid)
            settlement = self._settle_service_fee_charges_locked(
                conn,
                user_id=user_id,
                source_wallet_address=source_address,
                actor=actor,
                reason="threshold",
            )
            charge_row = self._service_fee_charge_by_uuid(conn, charge_uuid)
            conn.commit()
            return {
                "ok": True,
                "created": created,
                "settlement_layer": "service_fee_subledger",
                "settlement_policy": "freeze_then_batch_debit",
                "batch_threshold_points": SERVICE_BATCH_SETTLEMENT_MIN_POINTS,
                "charge": self._serialize_service_fee_charge(charge_row),
                "ledger": self.serialize_ledger(row),
                "settlement": settlement,
                "wallet": self.get_wallet(user_id),
                "item": dict(item),
            }
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def admin_adjust(self, *, actor, user_id, currency_type, direction, amount, reason, reference_id=None, idempotency_key=None):
        raise PermissionError("blockchain_permission_model: manual points adjustment is disabled; use official_wallet_grant to a public wallet address")

    def _official_wallet_grant_locked(self, conn, *, actor, destination_wallet_address, amount, reason="", request_uuid=None):
        amount = int(amount or 0)
        if amount <= 0:
            raise ValueError("amount must be positive")
        destination = str(destination_wallet_address or "").strip().lower()
        if not destination:
            raise ValueError("destination wallet address required")
        if not WALLET_ADDRESS_RE.fullmatch(destination):
            raise ValueError("destination wallet address format is invalid")
        reason_text = public_currency_text(str(reason or "official wallet grant").strip() or "official wallet grant")[:240]
        request_uuid = str(request_uuid or uuid.uuid4()).strip()[:120]
        if not request_uuid:
            raise ValueError("request_uuid required")
        self._assert_chain_writable(conn, "official wallet grant")
        sender_user_id = int(actor_value(actor, "id") or 0)
        if sender_user_id <= 0:
            root_row = conn.execute("SELECT id FROM users WHERE username='root' LIMIT 1").fetchone()
            sender_user_id = int(root_row["id"] or 0) if root_row else 0
        if sender_user_id <= 0:
            raise PermissionError("root actor id required")
        destination_fund_key = self._official_transfer_destination_fund_key(destination)
        destination_wallet = self._wallet_identity_owner_for_address(conn, destination)
        destination_unowned = 0
        if destination_fund_key:
            recipient_user_id = sender_user_id
            transaction_type = "official_fund_transfer"
        elif destination_wallet and destination_wallet["user_id"]:
            recipient_user_id = int(destination_wallet["user_id"])
            transaction_type = "official_wallet_grant"
        else:
            recipient_user_id = sender_user_id
            transaction_type = "official_wallet_grant"
            destination_unowned = 1
        source_address = economy_fund_address(self.chain_secret, "official_treasury")
        active_branch = self._canonical_branch_uuid(conn)
        self._assert_canonical_write_branch(conn, active_branch)
        payload = {
            "chain_branch": active_branch,
            "source_wallet_address": source_address,
            "destination_wallet_address": destination,
            "amount_points": amount,
            "fee_points": 0,
            "memo": reason_text,
            "transaction_type": transaction_type,
            "source_fund_key": "official_treasury",
        }
        request_hash = self._transfer_request_payload_hash(payload)
        tx_group_hash = sha256_text(f"points-chain-{transaction_type}:{active_branch}:{request_uuid}:{request_hash}")
        existing = conn.execute(
            "SELECT * FROM points_chain_transfer_requests WHERE request_uuid=?",
            (request_uuid,),
        ).fetchone()
        if existing:
            if str(existing["chain_branch"] if "chain_branch" in existing.keys() else "main") != active_branch:
                raise ValueError("transaction idempotency key belongs to a non-canonical branch")
            if existing["request_hash"] != request_hash:
                raise ValueError("transaction idempotency key conflict")
            existing = self._maybe_finalize_transfer_request_locked(conn, existing, actor=actor)
            return {
                "ok": True,
                "created": False,
                "tx_group_hash": existing["tx_group_hash"],
                "transaction_hash": existing["tx_group_hash"],
                "transaction": self._transfer_request_public_payload(conn, existing),
                "wallet": None if self._explorer_fund_key_for_address(existing["destination_wallet_address"]) or self._transfer_request_destination_unowned(existing) else self.wallet_payload_for_read(conn, int(existing["recipient_user_id"])),
                "destination_fund_key": self._explorer_fund_key_for_address(existing["destination_wallet_address"]) or "",
                "destination_unowned": self._transfer_request_destination_unowned(existing),
                **self._transfer_request_ledgers(conn, request_uuid),
            }
        conn.execute(
            """
            INSERT INTO points_chain_transfer_requests (
                request_uuid, chain_branch, request_hash, tx_group_hash, sender_user_id, recipient_user_id,
                source_wallet_address, destination_wallet_address, destination_unowned, amount_points, fee_points,
                transaction_type, source_fund_key, memo,
                transfer_out_ledger_uuid, transfer_in_ledger_uuid, fee_ledger_uuid, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, 'official_treasury', ?, NULL, NULL, NULL, 'pending', ?)
            """,
            (
                request_uuid,
                active_branch,
                request_hash,
                tx_group_hash,
                sender_user_id,
                recipient_user_id,
                source_address,
                destination,
                destination_unowned,
                amount,
                transaction_type,
                reason_text,
                utc_now(),
            ),
        )
        req = conn.execute(
            "SELECT * FROM points_chain_transfer_requests WHERE request_uuid=?",
            (request_uuid,),
        ).fetchone()
        notification_status = self._notify_wallet_transfer_pending(conn, req)
        warnings = [] if notification_status.get("all_sent") else ["notification_delivery_failed"]
        return {
            "ok": True,
            "created": True,
            "warnings": warnings,
            "notifications": {"pending": notification_status},
            "tx_group_hash": tx_group_hash,
            "transaction_hash": tx_group_hash,
            "transaction": self._transfer_request_public_payload(conn, req),
            "wallet": None if destination_fund_key or destination_unowned else self.wallet_payload_for_read(conn, int(recipient_user_id)),
            "destination_fund_key": destination_fund_key or "",
            "destination_unowned": bool(destination_unowned),
            **self._transfer_request_ledgers(conn, request_uuid),
        }

    def official_wallet_grant(self, *, actor, destination_wallet_address, amount, reason="", request_uuid=None, governance_proposal_uuid=None):
        if not governance_proposal_uuid:
            raise PermissionError("official treasury transfer requires executed governance proposal")
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            conn.commit()
            conn.execute("BEGIN IMMEDIATE")
            proposal = self._refresh_governance_proposal_locked(conn, governance_proposal_uuid)
            if not proposal or proposal["lifecycle_status"] != "EXECUTED":
                raise PermissionError("official treasury transfer requires executed governance proposal")
            if str(proposal["action_type"] or "").strip().upper() not in {"TREASURY_TRANSFER", "EXCHANGE_FUND_REPLENISH", "CONTEST_REWARD_PAYOUT"}:
                raise PermissionError("governance proposal is not an official treasury transfer")
            if self._governance_execution_payload_hash_for_row(proposal) != proposal["execution_payload_hash"]:
                raise ValueError("governance execution payload hash mismatch")
            if str(destination_wallet_address or "").strip().lower() != str(proposal["target_wallet_address"] or "").strip().lower():
                raise PermissionError("official treasury transfer payload does not match governance proposal destination")
            if int(amount or 0) != int(proposal["requested_amount"] or 0):
                raise PermissionError("official treasury transfer payload does not match governance proposal amount")
            result = self._official_wallet_grant_locked(
                conn,
                actor=actor,
                destination_wallet_address=destination_wallet_address,
                amount=amount,
                reason=reason,
                request_uuid=request_uuid,
            )
            conn.commit()
            return result
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _create_pending_reward(self, conn, *, user_id, currency_type, amount, action_type, reference_type=None, reference_id=None, metadata=None, submitted_by=None):
        currency_type = normalize_currency_type(currency_type)
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
        raise PermissionError("blockchain_permission_model: pending rewards are disabled; use official wallet or governance-approved on-chain rules")

    def review_pending_reward(self, *, actor, pending_reward_id, decision, review_note=""):
        raise PermissionError("blockchain_permission_model: pending reward review is disabled")

    def compensate_ledger(self, *, actor, ledger_uuid, reason):
        reason = str(reason or "").strip()
        if not reason:
            raise ValueError("reason is required")
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            conn.commit()
            conn.execute("BEGIN IMMEDIATE")
            self._assert_chain_writable(conn, "ledger compensation")
            original = conn.execute("SELECT * FROM points_ledger WHERE ledger_uuid=?", (str(ledger_uuid or ""),)).fetchone()
            if not original:
                raise ValueError("ledger not found")
            if original["ledger_hash"] != compute_ledger_hash(original):
                raise ValueError("ledger is tampered; repair or restore it before compensation")
            if str(original["action_type"] or "").startswith(("compensation:", "rollback:")):
                raise ValueError("compensation ledger cannot be compensated again")
            reverse_map = {
                "credit": "reverse",
                "transfer_in": "transfer_out",
                "debit": "credit",
                "transfer_out": "transfer_in",
                "freeze": "unfreeze",
                "unfreeze": "freeze",
            }
            reverse_direction = reverse_map.get(original["direction"])
            if not reverse_direction:
                raise ValueError("unsupported compensation direction")
            compensation_row, created = self._record_transaction(
                conn,
                user_id=original["user_id"],
                currency_type=original["currency_type"],
                direction=reverse_direction,
                amount=original["amount"],
                action_type=f"compensation:{original['action_type']}",
                reference_type="ledger_compensation",
                reference_id=original["ledger_uuid"],
                idempotency_key=f"compensation:{original['ledger_uuid']}",
                reason=reason,
                public_metadata={
                    "compensation_of": original["ledger_uuid"],
                    "original_direction": original["direction"],
                    "original_action_type": original["action_type"],
                },
                actor=actor,
                risk_flag="compensation",
                risk_score=20,
            )
            self._audit_log(
                conn,
                "LEDGER_COMPENSATION",
                "warning",
                f"compensate ledger {original['ledger_uuid']}",
                actor=actor,
                target_user_id=original["user_id"],
                ledger_id=compensation_row["id"],
                metadata={"original_ledger_uuid": original["ledger_uuid"], "reason": reason, "created": created},
            )
            conn.commit()
            return {
                "ok": True,
                "created": created,
                "original_ledger": self._explorer_public_ledger(conn, original),
                "compensation_ledger": self._explorer_public_ledger(conn, compensation_row),
                "wallet": self.get_wallet(original["user_id"]),
            }
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def rollback_ledger(self, *, actor, ledger_uuid, reason):
        raise PermissionError("blockchain_permission_model: rollback is disabled; append a compensation transaction instead")

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
            return [self._serialize_ledger_for_read(conn, row, include_user_id=include_user_id) for row in rows]
        finally:
            conn.close()

    def list_rules(self):
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            rows = conn.execute("SELECT * FROM points_rules ORDER BY rule_key").fetchall()
            return [{**dict(row), "currency_type": DISPLAY_CURRENCY} for row in rows]
        finally:
            conn.close()

    def list_catalog(self, *, include_disabled=False, category=None):
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            clauses = []
            params = []
            if not include_disabled:
                clauses.append("enabled=1")
            if category:
                clauses.append("category=?")
                params.append(str(category))
            where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
            rows = conn.execute(
                f"SELECT * FROM economy_price_catalog{where} ORDER BY category, enabled DESC, base_price, item_key",
                tuple(params),
            ).fetchall()
            return [{**dict(row), "currency_type": DISPLAY_CURRENCY, "metadata": _json_loads(row["metadata_json"], {})} for row in rows]
        finally:
            conn.close()

    def upsert_catalog_item(
        self,
        *,
        actor,
        item_key,
        item_name,
        category,
        base_price,
        dynamic_pricing=0,
        min_price=None,
        max_price=None,
        enabled=True,
        metadata=None,
    ):
        key = str(item_key or "").strip().lower()
        if not PRICE_ITEM_KEY_RE.fullmatch(key):
            raise ValueError("item_key must be 2-80 chars: lowercase letters, numbers, _, :, -")
        item_name = str(item_name or "").strip()
        if not item_name:
            raise ValueError("item_name required")
        category = str(category or "").strip().lower()
        if not PRICE_CATEGORY_RE.fullmatch(category):
            raise ValueError("category must be 2-80 chars: lowercase letters, numbers, _, :, -")
        try:
            base_price = int(base_price)
        except Exception as exc:
            raise ValueError("base_price must be an integer") from exc
        if base_price < 1 or base_price > 1_000_000_000:
            raise ValueError("base_price must be 1-1000000000")
        dynamic_pricing = 1 if dynamic_pricing else 0
        min_price = None if min_price in (None, "") else int(min_price)
        max_price = None if max_price in (None, "") else int(max_price)
        if min_price is not None and min_price < 1:
            raise ValueError("min_price must be positive")
        if max_price is not None and max_price < 1:
            raise ValueError("max_price must be positive")
        if min_price is not None and max_price is not None and min_price > max_price:
            raise ValueError("min_price cannot exceed max_price")
        if min_price is not None and base_price < min_price:
            raise ValueError("base_price cannot be lower than min_price")
        if max_price is not None and base_price > max_price:
            raise ValueError("base_price cannot exceed max_price")

        metadata = metadata if isinstance(metadata, dict) else {}
        cleaned_metadata = {}
        for meta_key, meta_value in metadata.items():
            if isinstance(meta_key, str) and len(meta_key) <= 80:
                cleaned_metadata[meta_key] = meta_value
        if category == "cloud_drive":
            try:
                storage_bytes = int(cleaned_metadata.get("storage_bytes") or 0)
                duration_days = int(cleaned_metadata.get("duration_days") or 0)
            except Exception as exc:
                raise ValueError("cloud_drive metadata requires integer storage_bytes and duration_days") from exc
            if storage_bytes < 1:
                raise ValueError("cloud_drive storage_bytes must be positive")
            if duration_days < 1 or duration_days > 3650:
                raise ValueError("cloud_drive duration_days must be 1-3650")
            cleaned_metadata["storage_bytes"] = storage_bytes
            cleaned_metadata["duration_days"] = duration_days
            cleaned_metadata["label"] = str(cleaned_metadata.get("label") or item_name).strip()[:120]

        now = utc_now()
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            conn.execute(
                """
                INSERT INTO economy_price_catalog (
                    item_key, item_name, category, currency_type, base_price,
                    dynamic_pricing, min_price, max_price, enabled, metadata_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(item_key) DO UPDATE SET
                    item_name=excluded.item_name,
                    category=excluded.category,
                    currency_type=excluded.currency_type,
                    base_price=excluded.base_price,
                    dynamic_pricing=excluded.dynamic_pricing,
                    min_price=excluded.min_price,
                    max_price=excluded.max_price,
                    enabled=excluded.enabled,
                    metadata_json=excluded.metadata_json,
                    updated_at=excluded.updated_at
                """,
                (
                    key,
                    item_name,
                    category,
                    INTERNAL_CURRENCY,
                    base_price,
                    dynamic_pricing,
                    min_price,
                    max_price,
                    1 if enabled else 0,
                    _json_dumps(cleaned_metadata),
                    now,
                    now,
                ),
            )
            self._audit_log(
                conn,
                "price_catalog_upsert",
                "info",
                f"updated price catalog item {key}",
                actor=actor,
                metadata={
                    "item_key": key,
                    "item_name": item_name,
                    "category": category,
                    "base_price": base_price,
                    "enabled": bool(enabled),
                },
            )
            conn.commit()
            row = conn.execute("SELECT * FROM economy_price_catalog WHERE item_key=?", (key,)).fetchone()
            return {**dict(row), "currency_type": DISPLAY_CURRENCY, "metadata": _json_loads(row["metadata_json"], {})}
        except Exception:
            conn.rollback()
            raise
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
            return [{**dict(row), "currency_type": DISPLAY_CURRENCY} for row in rows]
        finally:
            conn.close()

    def list_admin_adjustments(self, *, limit=100):
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            rows = conn.execute(
                """
                SELECT l.*, target.username AS target_username, actor.username AS actor_username
                FROM points_ledger l
                LEFT JOIN users target ON target.id=l.user_id
                LEFT JOIN users actor ON actor.id=l.created_by
                WHERE l.action_type LIKE 'admin_adjust_%'
                   OR l.action_type LIKE 'rollback:%'
                   OR l.action_type IN (
                       'admin_initial_grant',
                       'admin_weekly_salary',
                       'birthday_gift',
                       'game_daily_challenge_reward',
                       'game_weekly_leaderboard_reward',
                       'trading_bot_weekly_competition_reward',
                       'new_user_signup_bonus',
                       'user_initial_grant'
                   )
                ORDER BY l.id DESC LIMIT ?
                """,
                (min(200, max(1, int(limit or 100))),),
            ).fetchall()
            adjustments = []
            for row in rows:
                item = self.serialize_ledger(row, include_user_id=True)
                item["target_username"] = row["target_username"] or f"user:{row['user_id']}"
                item["actor_username"] = row["actor_username"] or (f"user:{row['created_by']}" if row["created_by"] else "system")
                item["signed_amount"] = int(row["amount"]) if row["direction"] in {"credit", "transfer_in"} else -int(row["amount"])
                adjustments.append(item)
            return adjustments
        finally:
            conn.close()

    def seal_block(self, *, actor=None, limit=100):
        # Phase 7 mode guard. Runs BEFORE we open a write transaction
        # so disallowed modes never even reach the chain INSERT path.
        self._assert_production_mode("seal_block")
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            conn.commit()
            conn.execute("BEGIN IMMEDIATE")
            self._assert_chain_writable(conn, "block seal")
            branch = self._canonical_branch_uuid(conn)
            rows = conn.execute(
                """
                SELECT * FROM points_ledger
                WHERE status='confirmed' AND chain_block_id IS NULL AND chain_branch=?
                ORDER BY id ASC LIMIT ?
                """,
                (branch, min(500, max(1, int(limit or 100)))),
            ).fetchall()
            if not rows:
                conn.commit()
                return {"ok": True, "sealed": False, "msg": "沒有可封存的帳本紀錄"}
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
                    actor_value(actor, "id"),
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
            self._audit_log(conn, "POINTS_BLOCK_SEALED", "info", f"sealed points block {block_number}", actor=actor, block_id=block_id, metadata={"ledger_count": len(rows), "chain_branch": branch})
            block = conn.execute("SELECT * FROM points_chain_blocks WHERE id=?", (block_id,)).fetchone()
            self._ensure_local_node(conn)
            conn.execute(
                """
                INSERT OR REPLACE INTO points_chain_block_signatures (
                    block_id, node_id, signature_algorithm, public_key_fingerprint, signature, signed_at
                ) VALUES (?, 'single-node', 'hmac-sha256', ?, ?, ?)
                """,
                (block_id, self._node_fingerprint(), self._sign_block(block), sealed_at),
            )
            backup = self._create_ledger_backup(conn, reason="block_sealed", kind="block_sealed")
            conn.commit()
            return {"ok": True, "sealed": True, "block": dict(block), "backup": backup}
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def seal_due_block(self, *, actor=None, ledger_threshold=DEFAULT_BLOCK_LEDGER_THRESHOLD, max_interval_seconds=DEFAULT_BLOCK_MAX_INTERVAL_SECONDS, limit=100):
        schedule = self.block_schedule(
            ledger_threshold=ledger_threshold,
            max_interval_seconds=max_interval_seconds,
            verify=False,
        )
        if not schedule.get("due"):
            return {"ok": True, "sealed": False, "msg": schedule.get("message") or "not due", "schedule": schedule}
        verification = self.verify_chain()
        if verification.get("ok") is not True:
            return {
                "ok": False,
                "sealed": False,
                "msg": "PointsChain 驗證失敗",
                "schedule": self.block_schedule(
                    ledger_threshold=ledger_threshold,
                    max_interval_seconds=max_interval_seconds,
                    verification=verification,
                ),
                "verification": verification,
            }
        schedule = self.block_schedule(
            ledger_threshold=ledger_threshold,
            max_interval_seconds=max_interval_seconds,
            verification=verification,
        )
        if not schedule.get("due"):
            return {"ok": True, "sealed": False, "msg": schedule.get("message") or "not due", "schedule": schedule}
        result = self.seal_block(actor=actor, limit=limit)
        result["schedule"] = schedule
        return result

    def force_seal_block(self, *, actor=None, reason="", limit=500):
        # Phase 7: chain writes require production or dev_ready. When mode-
        # switch / snapshot / restore flows call us from disallowed modes
        # (e.g. switching to internal_test, where the chain SHOULD NOT
        # be touched), we degrade gracefully to a no-op rather than
        # raising — the violation event is still recorded by the guard.
        try:
            self._assert_production_mode("force_seal_block")
        except ChainModeViolation as exc:
            return {
                "ok": True,
                "sealed": False,
                "skipped": True,
                "reason": str(reason or ""),
                "msg": f"skipped: chain writes require production/dev_ready (mode={exc.mode!r})",
            }
        verification = self.verify_chain()
        if verification.get("ok") is not True:
            return {"ok": False, "sealed": False, "msg": "PointsChain 驗證失敗", "verification": verification}
        result = self.seal_block(actor=actor, limit=limit)
        result["forced"] = True
        result["reason"] = str(reason or "")
        return result

    def _verify_chain_on_conn(self, conn, *, mark_safe_mode=True):
        self.ensure_schema(conn)
        self._ensure_local_node(conn)
        errors = []
        previous_by_branch = {}
        previous_ledger_by_branch = {}
        for row in conn.execute("SELECT * FROM points_ledger ORDER BY id ASC").fetchall():
                branch = str(row["chain_branch"] if "chain_branch" in row.keys() else self._main_branch_uuid())
                previous = previous_by_branch.get(branch)
                previous_ledger = previous_ledger_by_branch.get(branch)
                if row["previous_ledger_hash"] != previous:
                    errors.append({
                        "type": "ledger_previous_hash",
                        "severity": "critical",
                        "message": f"ledger #{row['id']} previous hash mismatch on branch {branch}",
                        "chain_branch": branch,
                        "ledger_id": row["id"],
                        "ledger_uuid": row["ledger_uuid"],
                        "expected_previous_ledger_hash": previous,
                        "actual_previous_ledger_hash": row["previous_ledger_hash"],
                        "previous_ledger_id": previous_ledger["id"] if previous_ledger else None,
                        "previous_ledger_uuid": previous_ledger["ledger_uuid"] if previous_ledger else None,
                        "ledger": self.serialize_ledger(row, include_user_id=True),
                    })
                expected = compute_ledger_hash(row)
                if row["ledger_hash"] != expected:
                    errors.append({
                        "type": "ledger_hash",
                        "severity": "critical",
                        "message": f"ledger #{row['id']} content hash mismatch",
                        "ledger_id": row["id"],
                        "ledger_uuid": row["ledger_uuid"],
                        "expected_ledger_hash": expected,
                        "actual_ledger_hash": row["ledger_hash"],
                        "ledger": self.serialize_ledger(row, include_user_id=True),
                    })
                previous_by_branch[branch] = row["ledger_hash"]
                previous_ledger_by_branch[branch] = row
        previous_block = None
        for block in conn.execute("SELECT * FROM points_chain_blocks ORDER BY block_number ASC").fetchall():
                if block["previous_block_hash"] != previous_block:
                    errors.append({
                        "type": "block_previous_hash",
                        "severity": "critical",
                        "message": f"block #{block['block_number']} previous hash mismatch",
                        "block_id": block["id"],
                        "block_number": block["block_number"],
                        "expected_previous_block_hash": previous_block,
                        "actual_previous_block_hash": block["previous_block_hash"],
                    })
                ledgers = conn.execute(
                    "SELECT id, ledger_uuid, ledger_hash FROM points_ledger WHERE id BETWEEN ? AND ? ORDER BY id ASC",
                    (block["first_ledger_id"], block["last_ledger_id"]),
                ).fetchall()
                hashes = [row["ledger_hash"] for row in ledgers]
                if len(hashes) != int(block["ledger_count"]):
                    errors.append({
                        "type": "block_ledger_count",
                        "severity": "critical",
                        "message": f"block #{block['block_number']} ledger count mismatch",
                        "block_id": block["id"],
                        "block_number": block["block_number"],
                        "expected_ledger_count": int(block["ledger_count"]),
                        "actual_ledger_count": len(hashes),
                        "first_ledger_id": block["first_ledger_id"],
                        "last_ledger_id": block["last_ledger_id"],
                    })
                expected_merkle_root = merkle_root(hashes)
                if expected_merkle_root != block["merkle_root"]:
                    errors.append({
                        "type": "block_merkle_root",
                        "severity": "critical",
                        "message": f"block #{block['block_number']} merkle root mismatch",
                        "block_id": block["id"],
                        "block_number": block["block_number"],
                        "expected_merkle_root": expected_merkle_root,
                        "actual_merkle_root": block["merkle_root"],
                        "first_ledger_id": block["first_ledger_id"],
                        "last_ledger_id": block["last_ledger_id"],
                        "ledger_uuids": [ledger["ledger_uuid"] for ledger in ledgers],
                    })
                expected_block_hash = compute_block_hash(block)
                if expected_block_hash != block["block_hash"]:
                    errors.append({
                        "type": "block_hash",
                        "severity": "critical",
                        "message": f"block #{block['block_number']} block hash mismatch",
                        "block_id": block["id"],
                        "block_number": block["block_number"],
                        "expected_block_hash": expected_block_hash,
                        "actual_block_hash": block["block_hash"],
                    })
                signature = conn.execute(
                    """
                    SELECT * FROM points_chain_block_signatures
                    WHERE block_id=? AND node_id='single-node'
                    """,
                    (block["id"],),
                ).fetchone()
                if not signature:
                    errors.append({
                        "type": "block_signature_missing",
                        "severity": "high",
                        "message": f"block #{block['block_number']} signature missing",
                        "block_id": block["id"],
                        "block_number": block["block_number"],
                    })
                elif signature["signature_algorithm"] != "hmac-sha256" or signature["public_key_fingerprint"] != self._node_fingerprint() or signature["signature"] != self._sign_block(block):
                    errors.append({
                        "type": "block_signature_invalid",
                        "severity": "critical",
                        "message": f"block #{block['block_number']} signature invalid",
                        "block_id": block["id"],
                        "block_number": block["block_number"],
                        "signature_algorithm": signature["signature_algorithm"],
                        "public_key_fingerprint": signature["public_key_fingerprint"],
                        "expected_public_key_fingerprint": self._node_fingerprint(),
                    })
                previous_block = block["block_hash"]
        repairs = []
        if not errors:
            wallet_errors = self._verify_wallets_against_ledger(conn)
            if wallet_errors and all(err.get("repairable_derived_cache") for err in wallet_errors):
                rebuild = self._rebuild_wallets_from_ledger(conn)
                wallet_errors_after_rebuild = self._verify_wallets_against_ledger(conn)
                if wallet_errors_after_rebuild:
                    errors.extend(wallet_errors_after_rebuild)
                else:
                    repairs.append({
                        "type": "wallet_identity_cache_rebuilt",
                        "wallet_errors_repaired": len(wallet_errors),
                        "wallet_rebuild": rebuild,
                    })
                    self._audit_log(
                        conn,
                        "POINTS_CHAIN_WALLET_CACHE_REBUILT",
                        "info",
                        "Wallet aggregate cache rebuilt from wallet identity ledger replay",
                        metadata={"wallet_errors": wallet_errors, "wallet_rebuild": rebuild},
                    )
            else:
                errors.extend(wallet_errors)
        counts = {
            "ledger_entries": conn.execute("SELECT COUNT(*) AS c FROM points_ledger").fetchone()["c"],
            "sealed_blocks": conn.execute("SELECT COUNT(*) AS c FROM points_chain_blocks").fetchone()["c"],
            "unsealed_entries": conn.execute("SELECT COUNT(*) AS c FROM points_ledger WHERE chain_block_id IS NULL").fetchone()["c"],
            "audit_events": conn.execute("SELECT COUNT(*) AS c FROM points_chain_audit_logs").fetchone()["c"],
            "wallets": conn.execute("SELECT COUNT(*) AS c FROM points_wallets").fetchone()["c"],
        }
        result = {"ok": not errors, "errors": errors[:100], "error_count": len(errors), "counts": counts}
        if repairs:
            result["repairs"] = repairs
        if mark_safe_mode and errors:
            result["safe_mode"] = self._enter_safe_mode(conn, result, "chain_verification_failed")
        elif mark_safe_mode:
            state = self._safe_mode_status(conn)
            if state.get("safe_mode"):
                now = utc_now()
                plan = state.get("restore_plan") if isinstance(state.get("restore_plan"), dict) else {}
                conn.execute(
                    """
                    UPDATE points_chain_recovery_state
                    SET safe_mode=0, restored_at=COALESCE(restored_at, ?), updated_at=?, restore_plan_json=?
                    WHERE id=1
                    """,
                    (
                        now,
                        now,
                        _json_dumps({
                            **plan,
                            "auto_cleared_after_clean_verify": True,
                            "verification_ok": True,
                            "verification_counts": counts,
                            "cleared_at": now,
                        }),
                    ),
                )
                self._audit_log(
                    conn,
                    "POINTS_CHAIN_SAFE_MODE_CLEARED",
                    "info",
                    "PointsChain safe mode cleared after clean verification",
                    metadata={"verification": result},
                )
                result["safe_mode"] = self._safe_mode_status(conn)
        return result

    def verify_chain(self):
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            result = self._verify_chain_on_conn(conn)
            conn.commit()
            return result
        finally:
            conn.close()

    def _explorer_acceleration_summary(self, conn, ledger_uuid):
        rows = conn.execute(
            """
            SELECT *
            FROM points_chain_acceleration_requests
            WHERE ledger_uuid=? AND status='accepted'
            ORDER BY id ASC
            """,
            (str(ledger_uuid or ""),),
        ).fetchall()
        total_fee = sum(int(row["fee_points"] or 0) for row in rows)
        latest = dict(rows[-1]) if rows else None
        return {
            "count": len(rows),
            "total_fee_points": total_fee,
            "latest_request": latest,
        }

    def _explorer_network_fee_state(self, conn):
        if not conn:
            congestion = 0.0
            return {
                "congestion_ratio": congestion,
                "congestion_label": "idle",
                "pending_transfer_count": 0,
                "unsealed_ledger_count": 0,
                "recent_ledger_count": 0,
                "base_fee_points": 1,
                "suggested_priority_fee_points": EXPLORER_ACCELERATION_REFERENCE_FEE_POINTS,
                "suggested_total_fee_points": 1 + EXPLORER_ACCELERATION_REFERENCE_FEE_POINTS,
            }
        cutoff = datetime.fromtimestamp(time.time() - 5 * 60, timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        pending = 0
        unsealed = 0
        recent = 0
        branch = self._main_branch_uuid()
        try:
            branch = self._canonical_branch_uuid(conn)
            if table_columns(conn, "points_chain_transfer_requests"):
                pending = int(conn.execute(
                    "SELECT COUNT(*) FROM points_chain_transfer_requests WHERE status='pending' AND chain_branch=?",
                    (branch,),
                ).fetchone()[0] or 0)
            if table_columns(conn, "points_ledger"):
                unsealed = int(conn.execute(
                    "SELECT COUNT(*) FROM points_ledger WHERE chain_block_id IS NULL AND chain_branch=?",
                    (branch,),
                ).fetchone()[0] or 0)
                recent = int(conn.execute(
                    "SELECT COUNT(*) FROM points_ledger WHERE created_at>=? AND chain_branch=?",
                    (cutoff, branch),
                ).fetchone()[0] or 0)
        except Exception:
            pending = unsealed = recent = 0
        pending_pressure = min(1.0, pending / 50.0)
        unsealed_pressure = min(1.0, max(0, unsealed - 25) / 200.0)
        recent_pressure = min(1.0, max(0, recent - 100) / 500.0)
        congestion = round(max(pending_pressure, unsealed_pressure, recent_pressure), 4)
        if congestion >= 0.75:
            label = "congested"
        elif congestion >= 0.35:
            label = "busy"
        elif congestion > 0:
            label = "normal"
        else:
            label = "idle"
        base_fee = max(1, int(round(1 + congestion * 9)))
        priority_fee = max(
            EXPLORER_ACCELERATION_REFERENCE_FEE_POINTS,
            int(round(EXPLORER_ACCELERATION_REFERENCE_FEE_POINTS * (1 + congestion * 4))),
        )
        return {
            "congestion_ratio": congestion,
            "chain_branch": branch,
            "congestion_label": label,
            "pending_transfer_count": pending,
            "unsealed_ledger_count": unsealed,
            "recent_ledger_count": recent,
            "base_fee_points": base_fee,
            "suggested_priority_fee_points": priority_fee,
            "suggested_total_fee_points": base_fee + priority_fee,
        }

    def _explorer_finality_estimate(self, fee_points=0, *, conn=None, network_state=None):
        fee = max(0, min(EXPLORER_MAX_ACCELERATION_FEE_POINTS, int(fee_points or 0)))
        network = network_state or self._explorer_network_fee_state(conn)
        congestion = max(0.0, min(1.0, float(network.get("congestion_ratio") or 0.0)))
        base_min = round(EXPLORER_BASE_FINALITY_MIN_SECONDS * (1 + congestion * 1.5))
        base_max = round(EXPLORER_BASE_FINALITY_MAX_SECONDS * (1 + congestion * 1.5))
        reference_fee = max(
            1,
            int(network.get("suggested_priority_fee_points") or EXPLORER_ACCELERATION_REFERENCE_FEE_POINTS),
        )
        # Simulate common fee-market behavior: higher priority fee moves a
        # transaction toward faster inclusion, but with diminishing returns.
        speedup_ratio = fee / (fee + reference_fee) if fee > 0 else 0.0
        min_seconds = round(
            base_min
            - (base_min - EXPLORER_ACCELERATED_FINALITY_MIN_SECONDS) * speedup_ratio
        )
        max_seconds = round(
            base_max
            - (base_max - EXPLORER_ACCELERATED_FINALITY_MAX_SECONDS) * speedup_ratio
        )
        if max_seconds < min_seconds + 15:
            max_seconds = min_seconds + 15
        return {
            "target_proved_count": EXPLORER_FINALITY_PROVED_COUNT,
            "base_seconds_min": EXPLORER_BASE_FINALITY_MIN_SECONDS,
            "base_seconds_max": EXPLORER_BASE_FINALITY_MAX_SECONDS,
            "network_base_seconds_min": base_min,
            "network_base_seconds_max": base_max,
            "minimum_seconds_min": EXPLORER_ACCELERATED_FINALITY_MIN_SECONDS,
            "minimum_seconds_max": EXPLORER_ACCELERATED_FINALITY_MAX_SECONDS,
            "fee_points": fee,
            "fee_model": "priority_fee_diminishing_ratio_v2",
            "fee_reference_points": reference_fee,
            "speedup_ratio": round(speedup_ratio, 4),
            "network_fee_state": network,
            "estimated_seconds_min": min_seconds,
            "estimated_seconds_max": max_seconds,
        }

    def _explorer_finality_schedule(self, ledger, estimate):
        target = EXPLORER_FINALITY_PROVED_COUNT
        min_seconds = max(1, int(estimate.get("estimated_seconds_min") or EXPLORER_BASE_FINALITY_MIN_SECONDS))
        max_seconds = max(min_seconds, int(estimate.get("estimated_seconds_max") or EXPLORER_BASE_FINALITY_MAX_SECONDS))
        seed = sha256_text(f"{ledger['ledger_uuid']}:{ledger['ledger_hash']}:{ledger['created_at']}")
        span = max(0, max_seconds - min_seconds)
        settlement_seconds = min_seconds + (int(seed[:8], 16) % (span + 1 if span else 1))
        first_proof = 4 + (int(seed[8:10], 16) % 9)
        first_proof = min(first_proof, max(1, settlement_seconds // 3))
        remaining = max(target - 1, settlement_seconds - first_proof)
        weights = []
        for index in range(target - 1):
            offset = 10 + (index * 2)
            weights.append(70 + (int(seed[offset:offset + 2] or seed[:2], 16) % 61))
        total_weight = max(1, sum(weights))
        marks = [first_proof]
        elapsed = float(first_proof)
        for weight in weights:
            elapsed += remaining * weight / total_weight
            marks.append(int(round(elapsed)))
        marks[-1] = settlement_seconds
        for index in range(1, len(marks)):
            if marks[index] <= marks[index - 1]:
                marks[index] = marks[index - 1] + 1
        if marks[-1] > settlement_seconds:
            overflow = marks[-1] - settlement_seconds
            marks = [max(1, mark - round(overflow * (index / max(1, target - 1)))) for index, mark in enumerate(marks)]
            marks[-1] = settlement_seconds
        return {
            "settlement_seconds": settlement_seconds,
            "first_proof_seconds": first_proof,
            "proof_marks": marks,
        }

    def _explorer_finality_from_created(self, *, created_at, estimate, schedule, sealed=False, fee_policy=None, acceleration_fee_points=0):
        fee_policy = fee_policy or {}
        created = parse_utc_timestamp(created_at)
        elapsed = 0
        if created:
            elapsed = max(0, int((datetime.now(timezone.utc) - created).total_seconds()))
        if sealed:
            proved_count = EXPLORER_FINALITY_PROVED_COUNT
            finality_status = "sealed"
            eta_seconds = 0
            next_proof_eta_seconds = 0
        else:
            marks = schedule["proof_marks"]
            proved_count = sum(1 for mark in marks if elapsed >= mark)
            finality_status = "proved" if proved_count >= EXPLORER_FINALITY_PROVED_COUNT else "pending"
            eta_seconds = max(0, schedule["settlement_seconds"] - elapsed)
            next_mark = next((mark for mark in marks if mark > elapsed), schedule["settlement_seconds"])
            next_proof_eta_seconds = max(0, next_mark - elapsed)
        return {
            **estimate,
            "proved_count": proved_count,
            "proved_remaining": max(0, EXPLORER_FINALITY_PROVED_COUNT - proved_count),
            "finality_status": finality_status,
            "block_status": "sealed" if sealed else "unsealed",
            "elapsed_seconds": elapsed,
            "eta_seconds": eta_seconds,
            "next_proof_eta_seconds": next_proof_eta_seconds,
            "settlement_seconds": schedule["settlement_seconds"],
            "first_proof_seconds": schedule["first_proof_seconds"],
            "finality_simulation": "deterministic_proved_schedule_v1",
            "transaction_fee_points": 0 if fee_policy.get("base_fee_exempt") else int(acceleration_fee_points or 0),
            "gas_price_points_per_proved": (
                0
                if fee_policy.get("base_fee_exempt")
                else round((int(acceleration_fee_points or 0) or 1) / EXPLORER_FINALITY_PROVED_COUNT, 4)
            ),
            "chain_fee_policy": fee_policy,
            "human_rule": "20 Proved；ETA 依鏈上忙碌度與 priority fee 動態估算",
        }

    def _explorer_finality_for_ledger(self, conn, ledger):
        accel = self._explorer_acceleration_summary(conn, ledger["ledger_uuid"])
        estimate = self._explorer_finality_estimate(accel["total_fee_points"], conn=conn)
        fee_policy = self._explorer_chain_fee_policy(ledger)
        schedule = self._explorer_finality_schedule(ledger, estimate)
        finality = self._explorer_finality_from_created(
            created_at=ledger["created_at"],
            estimate=estimate,
            schedule=schedule,
            sealed=bool(ledger["chain_block_id"]),
            fee_policy=fee_policy,
            acceleration_fee_points=accel["total_fee_points"],
        )
        return {
            **finality,
            "accelerated": accel["count"] > 0,
            "acceleration_request_count": accel["count"],
            "acceleration_fee_paid_points": accel["total_fee_points"],
            "acceleration_fee_destination_fund_key": "burn" if accel["total_fee_points"] else "",
            "acceleration_fee_destination_label": "BURN 銷毀錢包" if accel["total_fee_points"] else "",
            "latest_acceleration_request": accel["latest_request"],
        }

    def _explorer_find_ledger(self, conn, ref):
        ref = str(ref or "").strip()
        if not ref:
            return None
        return conn.execute(
            """
            SELECT *
            FROM points_ledger
            WHERE ledger_uuid=? OR ledger_hash=?
            LIMIT 1
            """,
            (ref, ref),
        ).fetchone()

    def _explorer_find_economy_event(self, conn, ref):
        ref = str(ref or "").strip()
        if not ref:
            return None
        return conn.execute(
            """
            SELECT *
            FROM points_economy_events
            WHERE event_uuid=? OR event_hash=? OR request_hash=? OR idempotency_key=?
            LIMIT 1
            """,
            (ref, ref, ref, ref),
        ).fetchone()

    def _explorer_economy_event_flow(self, row):
        source_fund = str(row["source_fund_key"] or "")
        destination_fund = str(row["destination_fund_key"] or "")
        source_label = self._economy_fund_flow_ref(source_fund)[0] if source_fund else ""
        destination_label = self._economy_fund_flow_ref(destination_fund)[0] if destination_fund else ""
        return {
            "walletized": True,
            "system_fund_event": True,
            "source_fund_key": source_fund,
            "source_wallet_address": str(row["source_address"] or ""),
            "source_label": source_label,
            "destination_fund_key": destination_fund,
            "destination_wallet_address": str(row["destination_address"] or ""),
            "destination_label": destination_label,
        }

    def _economy_event_is_genesis_allocation(self, row):
        if str(row["source_fund_key"] or "") != "mint":
            return False
        if str(row["transaction_type"] or "") in {"treasury_allocation", "promo_allocation", "exchange_allocation"}:
            return True
        metadata = _json_loads(row["metadata_json"], {})
        return bool(isinstance(metadata, dict) and metadata.get("bootstrap"))

    def _explorer_economy_genesis_rows(self, conn, *, branch_uuid=None):
        branch = str(branch_uuid or self._canonical_branch_uuid(conn) or self._main_branch_uuid())
        rows = conn.execute(
            """
            SELECT *
            FROM points_economy_events
            WHERE status='confirmed' AND chain_branch=? AND source_fund_key='mint'
            ORDER BY id ASC
            """,
            (branch,),
        ).fetchall()
        return [row for row in rows if self._economy_event_is_genesis_allocation(row)]

    def _explorer_economy_genesis_block_summary(self, conn, *, branch_uuid=None):
        rows = self._explorer_economy_genesis_rows(conn, branch_uuid=branch_uuid)
        branch = str(branch_uuid or self._canonical_branch_uuid(conn) or self._main_branch_uuid())
        event_hashes = [str(row["event_hash"] or "") for row in rows]
        block_hash = sha256_text(canonical_json({
            "block_type": "economy_genesis",
            "chain_branch": branch,
            "event_hashes": event_hashes,
        }))
        merkle_root = sha256_text(canonical_json(event_hashes))
        sealed_at = rows[0]["created_at"] if rows else ""
        return {
            "block_number": 0,
            "block_height": 0,
            "block_hash": block_hash,
            "previous_block_hash": "",
            "merkle_root": merkle_root,
            "ledger_count": len(rows),
            "transaction_count": len(rows),
            "first_ledger_id": 0,
            "last_ledger_id": 0,
            "sealed_at": sealed_at,
            "timestamp": sealed_at,
            "seal_status": "virtual_economy_genesis",
            "anchor_status": "economy_event_log",
        }

    def _explorer_economy_event_block(self, conn, row):
        if not self._economy_event_is_genesis_allocation(row):
            return None
        return self._explorer_economy_genesis_block_summary(
            conn,
            branch_uuid=row["chain_branch"] if "chain_branch" in row.keys() else self._main_branch_uuid(),
        )

    def _explorer_finality_for_economy_event(self, conn, row):
        estimate = self._explorer_finality_estimate(0, conn=conn)
        return {
            **estimate,
            "proved_count": EXPLORER_FINALITY_PROVED_COUNT,
            "proved_remaining": 0,
            "finality_status": "sealed" if self._economy_event_is_genesis_allocation(row) else "proved",
            "block_status": "economy_event_log",
            "elapsed_seconds": 0,
            "eta_seconds": 0,
            "next_proof_eta_seconds": 0,
            "settlement_seconds": 0,
            "first_proof_seconds": 0,
            "finality_simulation": "append_only_economy_event_log_v1",
            "transaction_fee_points": 0,
            "gas_price_points_per_proved": 0,
            "chain_fee_policy": {
                "base_fee_exempt": True,
                "base_fee_destination_fund_key": "burn",
                "base_fee_destination_label": "BURN 銷毀錢包",
                "acceleration_allowed": False,
                "exemption_reason": "system fund mint/economy events are protocol accounting entries",
                "manual_official_wallet_ops_are_auto": True,
            },
            "human_rule": "系統 fund event 為 append-only economy event；MINT/genesis allocation 以 virtual genesis block 呈現",
        }

    def _explorer_public_economy_event(self, conn, row):
        metadata = _json_loads(row["metadata_json"], {})
        source_address = str(row["source_address"] or "")
        destination_address = str(row["destination_address"] or "")
        return {
            "event_uuid": row["event_uuid"],
            "ledger_uuid": row["event_uuid"],
            "chain_branch": row["chain_branch"] if "chain_branch" in row.keys() else "main",
            "branch": self._branch_metadata(conn, row["chain_branch"] if "chain_branch" in row.keys() else "main"),
            "event_hash": row["event_hash"],
            "ledger_hash": row["event_hash"],
            "previous_event_hash": row["previous_event_hash"],
            "previous_ledger_hash": row["previous_event_hash"],
            "public_account_id": source_address,
            "currency_type": DISPLAY_CURRENCY,
            "direction": "transfer_out",
            "amount": int(row["amount"] or 0),
            "action_type": row["transaction_type"],
            "reference_type": "points_economy_event",
            "reference_id": row["event_uuid"],
            "reason": public_currency_text(metadata.get("reason") or row["transaction_type"] or ""),
            "input_data": metadata,
            "status": row["status"],
            "created_at": row["created_at"],
            "chain_block_id": None,
            "wallet_flow": self._explorer_economy_event_flow(row),
            "source_wallet_address": source_address,
            "destination_wallet_address": destination_address,
            "block": self._explorer_economy_event_block(conn, row),
            "finality": self._explorer_finality_for_economy_event(conn, row),
        }

    def _explorer_public_ledger(self, conn, row):
        flow = self._ledger_wallet_flow_for_read(conn, row)
        public_metadata = _json_loads(row["public_metadata_json"], {})
        input_data = {
            key: value
            for key, value in public_metadata.items()
            if key not in {"wallet_flow_snapshot"}
        } if isinstance(public_metadata, dict) else {}
        block = None
        if row["chain_block_id"]:
            block_row = conn.execute("SELECT * FROM points_chain_blocks WHERE id=?", (row["chain_block_id"],)).fetchone()
            if block_row:
                block = {
                    "block_number": int(block_row["block_number"]),
                    "block_hash": block_row["block_hash"],
                    "sealed_at": block_row["sealed_at"],
                    "ledger_count": int(block_row["ledger_count"]),
                }
        return {
            "ledger_uuid": row["ledger_uuid"],
            "chain_branch": row["chain_branch"] if "chain_branch" in row.keys() else "main",
            "branch": self._branch_metadata(conn, row["chain_branch"] if "chain_branch" in row.keys() else "main"),
            "ledger_hash": row["ledger_hash"],
            "previous_ledger_hash": row["previous_ledger_hash"],
            "public_account_id": row["public_account_id"],
            "currency_type": DISPLAY_CURRENCY,
            "direction": row["direction"],
            "amount": int(row["amount"] or 0),
            "action_type": row["action_type"],
            "reference_type": row["reference_type"],
            "reference_id": row["reference_id"],
            "reason": public_currency_text(row["reason"] or ""),
            "input_data": input_data,
            "status": row["status"],
            "created_at": row["created_at"],
            "chain_block_id": row["chain_block_id"],
            "wallet_flow": flow,
            "block": block,
            "finality": self._explorer_finality_for_ledger(conn, row),
        }

    def explorer_transaction(self, ref):
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            row = self._explorer_find_ledger(conn, ref)
            if row:
                return {"kind": "transaction", "transaction": self._explorer_public_ledger(conn, row)}
            event = self._explorer_find_economy_event(conn, ref)
            if event:
                return {"kind": "transaction", "transaction": self._explorer_public_economy_event(conn, event)}
            req = self._explorer_find_transfer_request(conn, ref)
            if not req:
                return None
            if str(req["status"] or "") == "pending":
                conn.commit()
                conn.execute("BEGIN IMMEDIATE")
                req = self._explorer_find_transfer_request(conn, ref)
                req = self._maybe_finalize_transfer_request_locked(
                    conn,
                    req,
                    actor={"role": "system", "username": "pointschain", "id": None},
                )
                conn.commit()
            return {"kind": "transaction", "transaction": self._transfer_request_public_payload(conn, req)}
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _explorer_fund_key_for_address(self, address):
        for fund_key in ("mint", "official_treasury", "promo_fund", "exchange_fund", "burn"):
            if economy_fund_address(self.chain_secret, fund_key) == address:
                return fund_key
        return ""

    def _official_transfer_destination_fund_key(self, address):
        fund_key = self._explorer_fund_key_for_address(str(address or "").strip().lower())
        if not fund_key:
            return ""
        if fund_key not in {"exchange_fund", "promo_fund", "burn"}:
            raise ValueError("official Treasury can only transfer to exchange, promo, or burn system funds")
        return fund_key

    def _explorer_address_balance_from_ledger(self, conn, address, *, limit=25, branch_uuid=None):
        branch = str(branch_uuid or self._canonical_branch_uuid(conn) or self._main_branch_uuid())
        like = f"%{address}%"
        rows = conn.execute(
            """
            SELECT *
            FROM points_ledger
            WHERE status='confirmed'
              AND chain_branch=?
              AND (public_account_id=? OR public_metadata_json LIKE ?)
            ORDER BY id ASC
            """,
            (branch, address, like),
        ).fetchall()
        balance = 0
        frozen = 0
        recent = []
        received_count = 0
        sent_count = 0
        total_received = 0
        total_sent = 0
        fees_paid = 0
        first_seen = None
        latest_seen = None
        fund_key = self._explorer_fund_key_for_address(address)
        for row in rows:
            flow = self._ledger_wallet_flow_for_read(conn, row)
            amount = int(row["amount"] or 0)
            direction = str(row["direction"] or "")
            source_address = str(flow.get("source_wallet_address") or "")
            destination_address = str(flow.get("destination_wallet_address") or "")
            affected = False
            if direction in {"credit", "transfer_in"} and destination_address == address:
                balance += amount
                received_count += 1
                total_received += amount
                affected = True
            elif direction in {"debit", "transfer_out", "reverse"} and source_address == address:
                balance -= amount
                sent_count += 1
                total_sent += amount
                if str(row["action_type"] or "") in {"wallet_transfer_fee", "chain_acceleration_fee"}:
                    fees_paid += amount
                affected = True
            elif direction == "freeze" and source_address == address:
                balance -= amount
                frozen += amount
                affected = True
            elif direction == "unfreeze" and (source_address == address or destination_address == address):
                balance += amount
                frozen -= amount
                affected = True
            elif row["public_account_id"] == address and not source_address and not destination_address:
                if direction in {"credit", "transfer_in"}:
                    balance += amount
                    received_count += 1
                    total_received += amount
                    affected = True
                elif direction in {"debit", "transfer_out", "reverse"}:
                    balance -= amount
                    sent_count += 1
                    total_sent += amount
                    affected = True
            if not affected:
                continue
            public_tx = self._explorer_public_ledger(conn, row)
            recent.append(public_tx)
            first_seen = first_seen or public_tx
            latest_seen = public_tx
        if fund_key:
            economy_rows = conn.execute(
                """
                SELECT *
                FROM points_economy_events
                WHERE status='confirmed'
                  AND chain_branch=?
                  AND (source_address=? OR destination_address=?)
                ORDER BY id ASC
                """,
                (branch, address, address),
            ).fetchall()
            for row in economy_rows:
                amount = int(row["amount"] or 0)
                source_address = str(row["source_address"] or "")
                destination_address = str(row["destination_address"] or "")
                affected = False
                if destination_address == address:
                    balance += amount
                    received_count += 1
                    total_received += amount
                    affected = True
                if source_address == address:
                    if str(row["source_fund_key"] or "") != "mint":
                        balance -= amount
                    sent_count += 1
                    total_sent += amount
                    affected = True
                if not affected:
                    continue
                public_tx = self._explorer_public_economy_event(conn, row)
                recent.append(public_tx)
                first_seen = first_seen or public_tx
                latest_seen = public_tx
        request_rows = conn.execute(
            """
            SELECT *
            FROM points_chain_transfer_requests
            WHERE status='confirmed'
              AND chain_branch=?
              AND destination_wallet_address=?
              AND (transfer_in_ledger_uuid IS NULL OR transfer_in_ledger_uuid='')
            ORDER BY id ASC
            """,
            (branch, address),
        ).fetchall()
        for req in request_rows:
            amount = int(req["amount_points"] or 0)
            balance += amount
            received_count += 1
            total_received += amount
            public_tx = self._transfer_request_public_payload(conn, req)
            recent.append(public_tx)
            first_seen = first_seen or public_tx
            latest_seen = public_tx
        pending_outgoing = self._pending_transfer_outgoing_for_address(conn, address, branch_uuid=branch)
        if pending_outgoing > 0:
            balance -= pending_outgoing
            frozen += pending_outgoing
        return {
            "points_balance": balance,
            "chain_branch": branch,
            "branch": self._branch_metadata(conn, branch),
            "points_frozen": max(0, frozen),
            "pending_outgoing_points": pending_outgoing,
            "transaction_count": len(recent),
            "received_tx_count": received_count,
            "sent_tx_count": sent_count,
            "total_received_points": total_received,
            "total_sent_points": total_sent,
            "fees_paid_points": fees_paid,
            "first_transaction": first_seen,
            "latest_transaction": latest_seen,
            "token_holdings": [
                {
                    "token": "POINTS",
                    "name": "PointsChain Points",
                    "balance": balance,
                    "frozen": max(0, frozen),
                    "pending_outgoing": pending_outgoing,
                }
            ],
            "recent_transactions": list(reversed(recent[-min(100, max(1, int(limit or 25))):])),
        }

    def explorer_wallet(self, address, *, limit=25):
        address = str(address or "").strip().lower()
        legacy_account = bool(re.fullmatch(r"[a-f0-9]{64}", address))
        if not legacy_account and not WALLET_ADDRESS_RE.fullmatch(address):
            raise ValueError("wallet address format is invalid")
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            identity = conn.execute(
                """
                SELECT address, wallet_type, custody_mode, key_algorithm, status, label, created_at
                FROM points_wallet_identities
                WHERE address=?
                LIMIT 1
                """,
                (address,),
            ).fetchone()
            fund_key = self._explorer_fund_key_for_address(address) if not legacy_account else ""
            balance_payload = self._explorer_address_balance_from_ledger(conn, address, limit=limit)
            if fund_key:
                report = economy_layer_report(
                    conn,
                    chain_secret=self.chain_secret,
                    actor={"role": "system", "id": None},
                    chain_branch=balance_payload.get("chain_branch") or self._canonical_branch_uuid(conn),
                )
                fund = (report.get("funds") or {}).get(fund_key) or {}
                if fund_key == "mint":
                    supply = report.get("supply") or {}
                    balance_payload["points_balance"] = int(supply.get("mint_remaining") or 0)
                else:
                    balance_payload["points_balance"] = int(fund.get("balance") or 0)
                balance_payload["points_frozen"] = 0
            risk_label = self._address_risk_label_locked(conn, address) if not legacy_account else None
            freeze = self._address_freeze_locked(conn, address) if not legacy_account else None
            provisional_freeze = self._address_provisional_freeze_locked(conn, address) if not legacy_account else None
            return {
                "kind": "wallet",
                "wallet": {
                    "address": address,
                    "legacy_account": legacy_account,
                    "fund_key": fund_key,
                    "label": fund_key.replace("_", " ").title() if fund_key else "",
                    "address_type": "system_fund" if fund_key else ("legacy_account" if legacy_account else "wallet"),
                    "wallet_type": fund_key or ("legacy_account" if legacy_account else "address"),
                    "custody_mode": "system" if fund_key else "",
                    "status": "active" if fund_key else "",
                    "chain_branch": balance_payload.get("chain_branch") or self._canonical_branch_uuid(conn),
                    "branch": balance_payload.get("branch") or {},
                    "points_balance": balance_payload["points_balance"],
                    "points_frozen": balance_payload["points_frozen"],
                    "pending_outgoing_points": balance_payload.get("pending_outgoing_points", 0),
                    "transaction_count": balance_payload["transaction_count"],
                    "received_tx_count": balance_payload["received_tx_count"],
                    "sent_tx_count": balance_payload["sent_tx_count"],
                    "total_received_points": balance_payload["total_received_points"],
                    "total_sent_points": balance_payload["total_sent_points"],
                    "fees_paid_points": balance_payload["fees_paid_points"],
                    "token_holdings": balance_payload["token_holdings"],
                    "first_transaction": balance_payload["first_transaction"],
                    "latest_transaction": balance_payload["latest_transaction"],
                    "recent_transactions": balance_payload["recent_transactions"],
                    "finality_rule": self._explorer_finality_estimate(0, conn=conn),
                    "human_rule": "20 Proved；ETA 依鏈上忙碌度與 priority fee 動態估算",
                    "risk_label": risk_label,
                    "governance_freeze": freeze or provisional_freeze,
                    "provisional_freeze": provisional_freeze,
                },
            }
        finally:
            conn.close()

    def _explorer_block_payload(self, conn, block):
        rows = conn.execute(
            """
            SELECT *
            FROM points_ledger
            WHERE chain_block_id=?
            ORDER BY id ASC
            LIMIT 100
            """,
            (block["id"],),
        ).fetchall()
        transactions = [self._explorer_public_ledger(conn, row) for row in rows]
        total_fees = sum(
            int(tx.get("amount") or 0)
            for tx in transactions
            if str(tx.get("action_type") or "") in {"wallet_transfer_fee", "chain_acceleration_fee"}
        )
        gas_used = int(block["ledger_count"] or 0) * 21_000
        gas_limit = max(21_000, gas_used + 21_000)
        signatures = [
            dict(row)
            for row in conn.execute(
                """
                SELECT node_id, signature_algorithm, public_key_fingerprint, signature, signed_at
                FROM points_chain_block_signatures
                WHERE block_id=?
                ORDER BY id ASC
                """,
                (block["id"],),
            ).fetchall()
        ]
        return {
            "block_number": int(block["block_number"]),
            "block_height": int(block["block_number"]),
            "block_hash": block["block_hash"],
            "previous_block_hash": block["previous_block_hash"],
            "merkle_root": block["merkle_root"],
            "ledger_count": int(block["ledger_count"]),
            "transaction_count": int(block["ledger_count"]),
            "first_ledger_id": int(block["first_ledger_id"]),
            "last_ledger_id": int(block["last_ledger_id"]),
            "sealed_at": block["sealed_at"],
            "timestamp": block["sealed_at"],
            "seal_status": block["seal_status"],
            "anchor_status": block["anchor_status"],
            "fee_recipient": economy_fund_address(self.chain_secret, "burn"),
            "gas_used": gas_used,
            "gas_limit": gas_limit,
            "gas_used_percent": round((gas_used / gas_limit) * 100, 2) if gas_limit else 0,
            "base_fee_per_gas": "1 point/proved",
            "total_transaction_fees_points": total_fees,
            "signatures": signatures,
            "transactions": transactions,
        }

    def explorer_block(self, ref):
        ref = str(ref or "").strip()
        if not ref:
            return None
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            if ref.isdigit():
                if int(ref) == 0:
                    summary = self._explorer_economy_genesis_block_summary(conn)
                    if summary["transaction_count"] <= 0:
                        return None
                    transactions = [
                        self._explorer_public_economy_event(conn, row)
                        for row in self._explorer_economy_genesis_rows(conn)
                    ]
                    return {
                        "kind": "block",
                        "block": {
                            **summary,
                            "fee_recipient": economy_fund_address(self.chain_secret, "burn"),
                            "gas_used": len(transactions) * 21_000,
                            "gas_limit": max(21_000, len(transactions) * 21_000 + 21_000),
                            "gas_used_percent": round((len(transactions) * 21_000 / max(21_000, len(transactions) * 21_000 + 21_000)) * 100, 2),
                            "base_fee_per_gas": "0 points/system genesis",
                            "total_transaction_fees_points": 0,
                            "signatures": [],
                            "transactions": transactions,
                        },
                    }
                block = conn.execute("SELECT * FROM points_chain_blocks WHERE block_number=?", (int(ref),)).fetchone()
            else:
                block = conn.execute("SELECT * FROM points_chain_blocks WHERE block_hash=?", (ref,)).fetchone()
                if not block:
                    summary = self._explorer_economy_genesis_block_summary(conn)
                    if summary["transaction_count"] > 0 and ref == summary["block_hash"]:
                        transactions = [
                            self._explorer_public_economy_event(conn, row)
                            for row in self._explorer_economy_genesis_rows(conn)
                        ]
                        return {
                            "kind": "block",
                            "block": {
                                **summary,
                                "fee_recipient": economy_fund_address(self.chain_secret, "burn"),
                                "gas_used": len(transactions) * 21_000,
                                "gas_limit": max(21_000, len(transactions) * 21_000 + 21_000),
                                "gas_used_percent": round((len(transactions) * 21_000 / max(21_000, len(transactions) * 21_000 + 21_000)) * 100, 2),
                                "base_fee_per_gas": "0 points/system genesis",
                                "total_transaction_fees_points": 0,
                                "signatures": [],
                                "transactions": transactions,
                            },
                        }
            if not block:
                return None
            return {"kind": "block", "block": self._explorer_block_payload(conn, block)}
        finally:
            conn.close()

    def explorer_lookup(self, query, *, limit=25):
        query = str(query or "").strip()
        if not query:
            raise ValueError("query required")
        tx = self.explorer_transaction(query)
        if tx:
            return tx
        block = self.explorer_block(query)
        if block:
            return block
        normalized = query.lower()
        if WALLET_ADDRESS_RE.fullmatch(normalized) or re.fullmatch(r"[a-f0-9]{64}", normalized):
            return self.explorer_wallet(normalized, limit=limit)
        return None

    def explorer_fee_estimate(self, *, fee_points=0):
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            return self._explorer_finality_estimate(fee_points, conn=conn)
        finally:
            conn.close()

    def _explorer_actor_can_accelerate(self, conn, *, actor, ledger):
        role = actor_value(actor, "role", "user")
        username = actor_value(actor, "username", "")
        if username == "root" or role in {"manager", "super_admin"}:
            return True
        actor_id = int(actor_value(actor, "id") or 0)
        if actor_id and int(ledger["user_id"]) == actor_id:
            return True
        flow = self._ledger_wallet_flow_for_read(conn, ledger)
        addresses = {self._public_account_id(actor_id)}
        state = self._wallet_identity_state_for_user(conn, actor_id)
        addresses.update(state.get("addresses") or set())
        return any(str(flow.get(key) or "") in addresses for key in ("source_wallet_address", "destination_wallet_address", "target_wallet_address"))

    def _transfer_request_actor_can_accelerate(self, conn, *, actor, req):
        role = actor_value(actor, "role", "user")
        username = actor_value(actor, "username", "")
        if username == "root" or role in {"manager", "super_admin"}:
            return True
        actor_id = int(actor_value(actor, "id") or 0)
        if actor_id <= 0:
            return False
        if int(req["sender_user_id"] or 0) == actor_id or self._transfer_request_recipient_user_id(req) == actor_id:
            return True
        state = self._wallet_identity_state_for_user(conn, actor_id)
        addresses = {str(item or "").strip().lower() for item in (state.get("addresses") or set()) if item}
        return (
            str(req["source_wallet_address"] or "").strip().lower() in addresses
            or str(req["destination_wallet_address"] or "").strip().lower() in addresses
        )

    def accelerate_explorer_transaction(self, *, actor, ledger_ref, fee_points, request_uuid=None):
        actor_id = int(actor_value(actor, "id") or 0)
        if actor_id <= 0:
            raise PermissionError("login required")
        fee = int(fee_points or 0)
        if fee <= 0:
            raise ValueError("fee_points must be positive")
        if fee > EXPLORER_MAX_ACCELERATION_FEE_POINTS:
            raise ValueError(f"fee_points must be <= {EXPLORER_MAX_ACCELERATION_FEE_POINTS}")
        request_uuid = str(request_uuid or uuid.uuid4()).strip()[:120]
        if not request_uuid:
            raise ValueError("request_uuid required")
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            conn.commit()
            conn.execute("BEGIN IMMEDIATE")
            ledger = self._explorer_find_ledger(conn, ledger_ref)
            transfer_req = None
            if not ledger:
                transfer_req = self._explorer_find_transfer_request(conn, ledger_ref)
            if not ledger and not transfer_req:
                raise ValueError("ledger not found")
            if transfer_req and str(transfer_req["status"] or "") != "pending":
                raise ValueError("only pending transfer requests can be accelerated")
            active_branch = self._canonical_branch_uuid(conn)
            target_branch = str(
                (ledger["chain_branch"] if ledger and "chain_branch" in ledger.keys() else "")
                or (transfer_req["chain_branch"] if transfer_req and "chain_branch" in transfer_req.keys() else "")
                or self._main_branch_uuid()
            )
            if target_branch != active_branch:
                raise PermissionError("cannot accelerate a non-canonical branch transaction")
            fee_policy = self._explorer_chain_fee_policy(ledger) if ledger else {
                "base_fee_exempt": False,
                "base_fee_destination_fund_key": "burn",
                "base_fee_destination_label": "BURN 銷毀錢包",
                "acceleration_allowed": True,
                "exemption_reason": "",
                "manual_official_wallet_ops_are_auto": False,
            }
            if not fee_policy["acceleration_allowed"]:
                raise ValueError(fee_policy["exemption_reason"] or "this transaction is chain-fee exempt")
            if ledger and not self._explorer_actor_can_accelerate(conn, actor=actor, ledger=ledger):
                raise PermissionError("permission denied")
            if transfer_req and not self._transfer_request_actor_can_accelerate(conn, actor=actor, req=transfer_req):
                raise PermissionError("permission denied")
            target_ref = ledger["ledger_uuid"] if ledger else transfer_req["request_uuid"]
            existing = conn.execute(
                "SELECT * FROM points_chain_acceleration_requests WHERE request_uuid=?",
                (request_uuid,),
            ).fetchone()
            if existing:
                if existing["ledger_uuid"] != target_ref or int(existing["fee_points"] or 0) != fee:
                    raise ValueError("acceleration idempotency key conflict")
                conn.commit()
                if ledger:
                    refreshed = conn.execute("SELECT * FROM points_ledger WHERE ledger_uuid=?", (ledger["ledger_uuid"],)).fetchone()
                    result = {"kind": "transaction", "transaction": self._explorer_public_ledger(conn, refreshed)}
                else:
                    refreshed = conn.execute("SELECT * FROM points_chain_transfer_requests WHERE request_uuid=?", (target_ref,)).fetchone()
                    result = {"kind": "transaction", "transaction": self._transfer_request_public_payload(conn, refreshed)}
                return {
                    "ok": True,
                    "created": False,
                    "acceleration": dict(existing),
                    "result": result,
                }
            estimate = self._explorer_finality_estimate(fee, conn=conn)
            fee_ledger, _created = self._record_transaction(
                conn,
                user_id=actor_id,
                currency_type=DISPLAY_CURRENCY,
                direction="debit",
                amount=fee,
                action_type="chain_acceleration_fee",
                reference_type="points_chain_explorer",
                reference_id=target_ref,
                idempotency_key=f"points_chain_acceleration:{request_uuid}",
                reason="鏈上交易加速費用",
                public_metadata={
                    "accelerated_ledger_uuid": target_ref,
                    "accelerated_ledger_hash": ledger["ledger_hash"] if ledger else transfer_req["tx_group_hash"],
                    "accelerated_transfer_request_uuid": transfer_req["request_uuid"] if transfer_req else "",
                    "target_proved_count": EXPLORER_FINALITY_PROVED_COUNT,
                },
                actor=actor,
            )
            now = utc_now()
            conn.execute(
                """
                INSERT INTO points_chain_acceleration_requests (
                    request_uuid, ledger_uuid, payer_user_id, fee_points, target_proved_count,
                    estimated_seconds_min, estimated_seconds_max, fee_ledger_uuid, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'accepted', ?)
                """,
                (
                    request_uuid,
                    target_ref,
                    actor_id,
                    fee,
                    EXPLORER_FINALITY_PROVED_COUNT,
                    estimate["estimated_seconds_min"],
                    estimate["estimated_seconds_max"],
                    fee_ledger["ledger_uuid"],
                    now,
                ),
            )
            conn.commit()
            if ledger:
                refreshed = conn.execute("SELECT * FROM points_ledger WHERE ledger_uuid=?", (ledger["ledger_uuid"],)).fetchone()
                result = {"kind": "transaction", "transaction": self._explorer_public_ledger(conn, refreshed)}
            else:
                refreshed = conn.execute("SELECT * FROM points_chain_transfer_requests WHERE request_uuid=?", (target_ref,)).fetchone()
                result = {"kind": "transaction", "transaction": self._transfer_request_public_payload(conn, refreshed)}
            created_row = conn.execute("SELECT * FROM points_chain_acceleration_requests WHERE request_uuid=?", (request_uuid,)).fetchone()
            return {
                "ok": True,
                "created": True,
                "acceleration": dict(created_row),
                "fee_ledger": self._explorer_public_ledger(conn, fee_ledger),
                "result": result,
            }
        except Exception:
            conn.rollback()
            raise
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
                return {"sealed": False, "ledger": self._serialize_ledger_for_read(conn, ledger), "ledger_hash": ledger["ledger_hash"]}
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
                "wallet_flow": self._ledger_wallet_flow_for_read(conn, ledger),
                "ledger_hash": ledger["ledger_hash"],
                "block_number": block["block_number"],
                "merkle_root": block["merkle_root"],
                "merkle_path": merkle_proof(hashes, index),
                "block_hash": block["block_hash"],
            }
        finally:
            conn.close()

    def economy_stats(self, *, verification=None):
        chain = verification if verification is not None else self.verify_chain()
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            wallet = conn.execute(
                """
                SELECT COALESCE(SUM(soft_balance + hard_balance), 0) AS points_balance,
                       COALESCE(SUM(soft_frozen + hard_frozen), 0) AS points_frozen,
                       COUNT(*) AS wallets
                FROM points_wallets
                """
            ).fetchone()
            ledger = conn.execute(
                """
                SELECT
                    COALESCE(SUM(CASE WHEN direction IN ('credit','transfer_in') THEN amount ELSE 0 END), 0) AS points_issued,
                    COALESCE(SUM(CASE WHEN direction IN ('debit','transfer_out','reverse') THEN amount ELSE 0 END), 0) AS points_spent,
                    COUNT(*) AS ledger_entries
                FROM points_ledger
                WHERE status='confirmed'
                """
            ).fetchone()
            wallet_data = dict(wallet)
            ledger_data = dict(ledger)
            wallet_balance = int(wallet_data.get("points_balance") or 0)
            wallet_frozen = int(wallet_data.get("points_frozen") or 0)
            ledger_issued = int(ledger_data.get("points_issued") or 0)
            ledger_spent = int(ledger_data.get("points_spent") or 0)
            ledger_net = ledger_issued - ledger_spent
            ledger_data["ledger_net_points"] = ledger_net

            user_cols = {row["name"] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
            member_wallet_balance = wallet_balance
            member_wallet_frozen = wallet_frozen
            member_wallet_count = int(wallet_data.get("wallets") or 0)
            member_ledger_issued = ledger_issued
            member_ledger_spent = ledger_spent
            if "username" in user_cols:
                member_wallet = conn.execute(
                    """
                    SELECT COALESCE(SUM(w.soft_balance + w.hard_balance), 0) AS points_balance,
                           COALESCE(SUM(w.soft_frozen + w.hard_frozen), 0) AS points_frozen,
                           COUNT(*) AS wallets
                    FROM points_wallets w
                    LEFT JOIN users u ON u.id=w.user_id
                    WHERE COALESCE(LOWER(u.username), '') != 'root'
                    """
                ).fetchone()
                member_ledger = conn.execute(
                    """
                    SELECT
                        COALESCE(SUM(CASE WHEN l.direction IN ('credit','transfer_in') THEN l.amount ELSE 0 END), 0) AS points_issued,
                        COALESCE(SUM(CASE WHEN l.direction IN ('debit','transfer_out','reverse') THEN l.amount ELSE 0 END), 0) AS points_spent,
                        COUNT(*) AS ledger_entries
                    FROM points_ledger l
                    LEFT JOIN users u ON u.id=l.user_id
                    WHERE l.status='confirmed'
                      AND COALESCE(LOWER(u.username), '') != 'root'
                    """
                ).fetchone()
                member_wallet_balance = int(member_wallet["points_balance"] or 0)
                member_wallet_frozen = int(member_wallet["points_frozen"] or 0)
                member_wallet_count = int(member_wallet["wallets"] or 0)
                member_ledger_issued = int(member_ledger["points_issued"] or 0)
                member_ledger_spent = int(member_ledger["points_spent"] or 0)

            sealed = conn.execute(
                """
                SELECT
                    COALESCE(SUM(CASE WHEN chain_block_id IS NOT NULL THEN 1 ELSE 0 END), 0) AS sealed_ledger_entries,
                    COALESCE(SUM(CASE WHEN chain_block_id IS NULL THEN 1 ELSE 0 END), 0) AS unsealed_ledger_entries,
                    COUNT(*) AS confirmed_ledger_entries
                FROM points_ledger
                WHERE status='confirmed'
                """
            ).fetchone()
            latest = conn.execute(
                """
                SELECT
                    (SELECT created_at FROM points_ledger ORDER BY id DESC LIMIT 1) AS latest_ledger_at,
                    (SELECT updated_at FROM points_wallets ORDER BY updated_at DESC LIMIT 1) AS latest_wallet_at
                """
            ).fetchone()
            outstanding = wallet_balance + wallet_frozen
            member_outstanding = member_wallet_balance + member_wallet_frozen
            member_ledger_net = member_ledger_issued - member_ledger_spent
            confirmed_count = int(sealed["confirmed_ledger_entries"] or 0)
            sealed_count = int(sealed["sealed_ledger_entries"] or 0)
            circulation = {
                "available_points": wallet_balance,
                "frozen_points": wallet_frozen,
                "outstanding_points": outstanding,
                "member_available_points": member_wallet_balance,
                "member_frozen_points": member_wallet_frozen,
                "member_outstanding_points": member_outstanding,
                "root_outstanding_points": outstanding - member_outstanding,
                "confirmed_issued_points": ledger_issued,
                "confirmed_spent_points": ledger_spent,
                "ledger_net_points": ledger_net,
                "member_confirmed_issued_points": member_ledger_issued,
                "member_confirmed_spent_points": member_ledger_spent,
                "member_ledger_net_points": member_ledger_net,
                "supply_gap_points": outstanding - ledger_net,
                "member_supply_gap_points": member_outstanding - member_ledger_net,
                "wallet_count": int(wallet_data.get("wallets") or 0),
                "member_wallet_count": member_wallet_count,
                "root_wallet_count": max(0, int(wallet_data.get("wallets") or 0) - member_wallet_count),
                "confirmed_ledger_entries": confirmed_count,
                "sealed_ledger_entries": sealed_count,
                "unsealed_ledger_entries": int(sealed["unsealed_ledger_entries"] or 0),
                "sealed_coverage_percent": round((sealed_count / confirmed_count) * 100, 4) if confirmed_count else 0,
                "latest_ledger_at": latest["latest_ledger_at"] if latest else None,
                "latest_wallet_at": latest["latest_wallet_at"] if latest else None,
            }
            economy_layer = economy_layer_report(
                conn,
                chain_secret=self.chain_secret,
                actor={"role": "system", "id": None},
                circulation=circulation,
                chain_branch=self._canonical_branch_uuid(conn),
            )
            if not economy_layer.get("legacy_bridge", {}).get("bridged_supply_equation_balanced"):
                backfill = self._backfill_walletized_ledger_events(conn)
                if backfill.get("created"):
                    economy_layer = economy_layer_report(
                        conn,
                        chain_secret=self.chain_secret,
                        actor={"role": "system", "id": None},
                        circulation=circulation,
                        chain_branch=self._canonical_branch_uuid(conn),
                    )
                    economy_layer["walletization_backfill"] = backfill
            conn.commit()
            return {
                "wallets": wallet_data,
                "ledger": ledger_data,
                "chain": chain,
                "circulation": circulation,
                "economy_layer": economy_layer,
                "currency_type": DISPLAY_CURRENCY,
            }
        finally:
            conn.close()

    def block_schedule(self, *, ledger_threshold=DEFAULT_BLOCK_LEDGER_THRESHOLD, max_interval_seconds=DEFAULT_BLOCK_MAX_INTERVAL_SECONDS, verification=None, verify=True):
        if verification is None and verify:
            verification = self.verify_chain()
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            ledger_threshold = max(1, int(ledger_threshold or DEFAULT_BLOCK_LEDGER_THRESHOLD))
            max_interval_seconds = max(60, int(max_interval_seconds or DEFAULT_BLOCK_MAX_INTERVAL_SECONDS))
            first_unsealed = conn.execute(
                "SELECT created_at FROM points_ledger WHERE chain_block_id IS NULL ORDER BY id ASC LIMIT 1"
            ).fetchone()
            if verification is None:
                safe_mode = self._safe_mode_status(conn)
                unsealed_count = conn.execute(
                    "SELECT COUNT(*) AS c FROM points_ledger WHERE chain_block_id IS NULL"
                ).fetchone()["c"]
                verification = {
                    "ok": not bool(safe_mode.get("safe_mode")),
                    "counts": {"unsealed_entries": int(unsealed_count or 0)},
                    "safe_mode": safe_mode,
                    "verification_mode": "schedule_snapshot",
                }
            anchor_at = parse_utc_timestamp(first_unsealed["created_at"]) if first_unsealed else None
            next_at = anchor_at.timestamp() + max_interval_seconds if anchor_at else None
            now_ts = datetime.now(timezone.utc).timestamp()
            seconds_remaining = int(max(0, next_at - now_ts)) if next_at else None
            unsealed = int((verification.get("counts") or {}).get("unsealed_entries") or 0)
            chain_ok = verification.get("ok") is True
            entries_remaining = max(0, ledger_threshold - unsealed)
            count_due = unsealed >= ledger_threshold
            time_due = bool(unsealed and seconds_remaining == 0)
            due_reason = "count" if count_due else ("time" if time_due else None)
            return {
                "mode": "hybrid",
                "ledger_threshold": ledger_threshold,
                "entries_remaining": entries_remaining,
                "max_interval_seconds": max_interval_seconds,
                "max_interval_minutes": max_interval_seconds // 60,
                "interval_seconds": max_interval_seconds,
                "interval_minutes": max_interval_seconds // 60,
                "next_seal_at": datetime.fromtimestamp(next_at, timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z") if next_at else None,
                "seconds_remaining": seconds_remaining,
                "unsealed_entries": unsealed,
                "chain_ok": chain_ok,
                "due": bool(chain_ok and (count_due or time_due)),
                "due_reason": due_reason,
                "message": "全鏈驗證異常，暫停自動封塊" if not chain_ok else ("目前沒有未封 ledger" if not unsealed else (f"已累積 {unsealed}/{ledger_threshold} 筆，可封塊" if count_due else ("已到達最長等待時間，可封塊" if time_due else f"已累積 {unsealed}/{ledger_threshold} 筆，尚需 {entries_remaining} 筆或等待時間到"))),
            }
        finally:
            conn.close()

    def _root_recent_unsealed_transactions(self, conn, *, limit=50):
        limit = max(1, min(100, int(limit or 50)))
        pending_requests = conn.execute(
            """
            SELECT *
            FROM points_chain_transfer_requests
            WHERE status='pending'
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        unsealed_ledgers = conn.execute(
            """
            SELECT *
            FROM points_ledger
            WHERE chain_block_id IS NULL
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        rows = []
        for req in pending_requests:
            payload = self._transfer_request_public_payload(conn, req)
            rows.append({
                "source": "pending_transfer",
                "transaction_hash": payload.get("transaction_hash") or payload.get("ledger_hash") or "",
                "ledger_uuid": payload.get("ledger_uuid") or "",
                "ledger_hash": payload.get("ledger_hash") or "",
                "action_type": payload.get("action_type") or "wallet_transfer",
                "amount": int(payload.get("amount") or 0),
                "status": payload.get("status") or "pending",
                "created_at": payload.get("created_at") or "",
                "finality": payload.get("finality") or {},
                "wallet_flow": payload.get("wallet_flow") or {},
            })
        for ledger in unsealed_ledgers:
            payload = self._explorer_public_ledger(conn, ledger)
            rows.append({
                "source": "unsealed_ledger",
                "transaction_hash": payload.get("ledger_hash") or payload.get("transaction_hash") or "",
                "ledger_uuid": payload.get("ledger_uuid") or "",
                "ledger_hash": payload.get("ledger_hash") or "",
                "action_type": payload.get("action_type") or "",
                "amount": int(payload.get("amount") or 0),
                "status": payload.get("status") or "confirmed",
                "created_at": payload.get("created_at") or "",
                "finality": payload.get("finality") or {},
                "wallet_flow": payload.get("wallet_flow") or {},
            })
        rows.sort(key=lambda row: str(row.get("created_at") or ""), reverse=True)
        return rows[:limit]

    def root_report(self):
        verification = self.verify_chain()
        scheduled_backup = None
        if verification.get("ok"):
            scheduled_backup = self.create_scheduled_backup_if_due()
        stats = self.economy_stats(verification=verification)
        audit_logs = self.list_chain_audit_logs(limit=50)
        block_schedule = self.block_schedule(verification=verification)
        backups = self.list_ledger_backups(limit=30)
        recovery = self.safe_mode_status()
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            blocks = conn.execute(
                """
                SELECT b.*, s.signature_algorithm, s.public_key_fingerprint, s.signed_at
                FROM points_chain_blocks b
                LEFT JOIN points_chain_block_signatures s ON s.block_id=b.id AND s.node_id='single-node'
                ORDER BY b.block_number DESC LIMIT 10
                """
            ).fetchall()
            high_risk = conn.execute(
                """
                SELECT * FROM points_ledger
                WHERE risk_flag != 'none' OR status != 'confirmed'
                ORDER BY id DESC LIMIT 20
                """
            ).fetchall()
            high_risk_by_id = {int(row["id"]): self.serialize_ledger(row, include_user_id=False) for row in high_risk}
            for error in verification.get("errors") or []:
                ledger = error.get("ledger") if isinstance(error, dict) else None
                ledger_id = int(error.get("ledger_id") or 0) if isinstance(error, dict) else 0
                if not ledger_id:
                    continue
                if not ledger:
                    row = conn.execute("SELECT * FROM points_ledger WHERE id=?", (ledger_id,)).fetchone()
                    ledger = self.serialize_ledger(row, include_user_id=False) if row else None
                if not ledger:
                    continue
                existing = high_risk_by_id.get(ledger_id) or dict(ledger)
                issues = list(existing.get("verification_errors") or [])
                issues.append({
                    "type": error.get("type"),
                    "message": error.get("message"),
                    "expected_ledger_hash": error.get("expected_ledger_hash"),
                    "actual_ledger_hash": error.get("actual_ledger_hash"),
                    "expected_previous_ledger_hash": error.get("expected_previous_ledger_hash"),
                    "actual_previous_ledger_hash": error.get("actual_previous_ledger_hash"),
                })
                existing["verification_errors"] = issues
                existing["verification_status"] = "tampered"
                high_risk_by_id[ledger_id] = existing
            high_risk_ledger = sorted(high_risk_by_id.values(), key=lambda row: int(row.get("id") or 0), reverse=True)[:20]
            return {
                "verification": verification,
                "stats": stats,
                "blocks": [dict(row) for row in blocks],
                "high_risk_ledger": high_risk_ledger,
                "audit_logs": audit_logs,
                "unsealed_transactions": self._root_recent_unsealed_transactions(conn, limit=50),
                "block_schedule": block_schedule,
                "ledger_backups": backups,
                "recovery": recovery,
                "scheduled_backup": scheduled_backup,
                "governance": self._governance_report_locked(conn),
            }
        finally:
            conn.close()


from . import backup_recovery as _backup_recovery

for _name in ('_backup_payload', '_chain_head_summary', '_verify_backup_payload', '_write_json_private', 'create_ledger_backup', '_create_ledger_backup', '_load_backup_from_catalog', '_healthy_backups', 'list_ledger_backups', '_prune_ledger_backups', '_scheduled_backup_due', 'create_scheduled_backup_if_due', '_create_forensic_bundle', '_build_restore_plan', '_enter_safe_mode'):
    setattr(PointsLedgerService, _name, getattr(_backup_recovery, _name))

del _backup_recovery
del _name
