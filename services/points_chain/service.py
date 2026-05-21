"""PointsChain ledger, wallet, and verification service."""

import threading

from . import schema as _schema
from .economy_layer import (
    append_economy_event,
    bootstrap_economy_layer,
    economy_fund_address,
    ensure_economy_layer_schema,
    economy_layer_report,
)
from .wallet_identity import WALLET_ADDRESS_RE, ensure_wallet_identity_schema

globals().update({name: value for name, value in _schema.__dict__.items() if not name.startswith("__")})

EXPLORER_FINALITY_PROVED_COUNT = 20
EXPLORER_BASE_FINALITY_MIN_SECONDS = 120
EXPLORER_BASE_FINALITY_MAX_SECONDS = 180
EXPLORER_MAX_ACCELERATION_FEE_POINTS = 10000


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
        """Phase 7 guard. Raise ChainModeViolation unless mode == 'production'.

        Reads the mode every call (no caching) so a switch out of
        production immediately blocks subsequent writes. If the mode
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
        if mode != "production":
            try:
                self._security_event_recorder(
                    "chain_mode_violation",
                    target_user="-",
                    detail=f"action={action},mode={mode!r}",
                )
            except Exception:
                pass
            raise ChainModeViolation(mode, action=action)

    def _wallet_totals_from_ledger(self, rows):
        totals = {}
        for row in rows:
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
        rows = conn.execute(
            """
            SELECT * FROM points_ledger
            WHERE user_id=?
            ORDER BY id ASC
            """,
            (int(user_id),),
        ).fetchall()
        return self._wallet_totals_from_ledger(rows).get(int(user_id), {
            "balance": 0,
            "frozen": 0,
            "earned": 0,
            "spent": 0,
        })

    def _rebuild_wallets_from_ledger(self, conn):
        started_transaction = False
        if not conn.in_transaction:
            conn.execute("BEGIN IMMEDIATE")
            started_transaction = True
        try:
            rows = conn.execute("SELECT * FROM points_ledger ORDER BY id ASC").fetchall()
            totals = self._wallet_totals_from_ledger(rows)
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
        rows = conn.execute("SELECT * FROM points_ledger ORDER BY id ASC").fetchall()
        totals = self._wallet_totals_from_ledger(rows)
        wallet_rows = {
            int(row["user_id"]): row
            for row in conn.execute("SELECT * FROM points_wallets ORDER BY user_id ASC").fetchall()
        }
        user_ids = set(wallet_rows.keys())
        user_ids.update(totals.keys())
        errors = []
        for user_id in sorted(user_ids):
            wallet = wallet_rows.get(user_id)
            expected = totals.get(user_id, {"balance": 0, "frozen": 0, "earned": 0, "spent": 0})
            if not wallet:
                if any(int(expected[key]) for key in ("balance", "frozen", "earned", "spent")):
                    errors.append({
                        "type": "wallet_missing",
                        "severity": "critical",
                        "message": f"wallet for user #{user_id} is missing but ledger has balance data",
                        "user_id": user_id,
                        "expected": expected,
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
                errors.append({
                    "type": "wallet_ledger_mismatch",
                    "severity": "critical",
                    "message": f"wallet for user #{user_id} does not match ledger replay",
                    "user_id": user_id,
                    "mismatches": mismatches,
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
            rebuild = self._rebuild_wallets_from_ledger(conn)
            post = self._verify_chain_on_conn(conn, mark_safe_mode=False)
            if not post["ok"]:
                raise ValueError("restored chain verification failed")
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
                item["metadata"] = public_currency_payload(_json_loads(row["metadata_json"], {}))
                logs.append(item)
            return logs
        finally:
            conn.close()

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
            payload["points_balance"] = active_balance
            payload["points_frozen"] = active_frozen
            payload["soft_balance"] = active_balance
            payload["soft_frozen"] = active_frozen
            payload["hard_balance"] = 0
            payload["hard_frozen"] = 0
            payload["wallet_identity_source"] = "active_wallet" if active_address else "no_active_wallet"
            payload["wallet_identity_balances"] = {
                address: {"points_balance": int(item.get("balance") or 0), "points_frozen": int(item.get("frozen") or 0)}
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
        preferred = self._wallet_identity_row_for_user_address(conn, user_id, preferred_address, active_only=False)
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
        primary = None
        addresses = set()
        for row in rows:
            address = str(row["address"] or "")
            if address:
                addresses.add(address)
            if int(row["is_primary"] or 0) and row["status"] in {"pending_backup", "active"}:
                primary = row
        return {"has_identity": bool(rows), "primary": primary, "addresses": addresses}

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
        fee_exempt = self._is_configured_auto_distribution_action(row["action_type"])
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
            return "official_treasury"
        if action.startswith("spend:") or action in {"video_boost_debit", "admin_adjust_debit", "chain_acceleration_fee"}:
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

    def _wallet_identity_balances_for_user(self, conn, user_id):
        state = self._wallet_identity_state_for_user(conn, user_id)
        balances = {}
        if not state["has_identity"]:
            return {"has_identity": False, "primary_address": "", "balances": balances}
        for address in state["addresses"]:
            balances[address] = {"balance": 0, "frozen": 0}
        rows = conn.execute(
            """
            SELECT * FROM points_ledger
            WHERE user_id=? AND status='confirmed'
            ORDER BY id ASC
            """,
            (int(user_id),),
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
        primary = state["primary"]
        return {
            "has_identity": True,
            "primary_address": primary["address"] if primary else "",
            "balances": balances,
        }

    def _economy_external_address_balance(self, conn, address):
        address = str(address or "").strip()
        if not address:
            return 0
        rows = conn.execute(
            """
            SELECT source_fund_key, source_address, destination_fund_key, destination_address, amount
            FROM points_economy_events
            WHERE status='confirmed'
            ORDER BY id ASC
            """
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
        bootstrap_economy_layer(conn, chain_secret=self.chain_secret, actor={"role": "system", "id": None})
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

    def _pending_transfer_outgoing_for_address(self, conn, address, *, exclude_request_uuid=None):
        address = str(address or "").strip().lower()
        if not address:
            return 0
        sql = """
            SELECT COALESCE(SUM(amount_points + fee_points), 0) AS pending_total
            FROM points_chain_transfer_requests
            WHERE source_wallet_address=? AND status='pending'
        """
        params = [address]
        if exclude_request_uuid:
            sql += " AND request_uuid<>?"
            params.append(str(exclude_request_uuid))
        row = conn.execute(sql, tuple(params)).fetchone()
        return int((row["pending_total"] if row else 0) or 0)

    def _wallet_identity_balance_for_address(self, conn, *, user_id, address):
        state = self._wallet_identity_balances_for_user(conn, int(user_id))
        balances = state.get("balances") or {}
        payload = balances.get(str(address or "").strip().lower())
        return int((payload or {}).get("balance") or 0)

    def _transfer_request_public_payload(self, conn, req):
        req = dict(req)
        fee = int(req.get("fee_points") or 0)
        estimate = self._explorer_finality_estimate(fee)
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
                "base_fee_destination_fund_key": "official_treasury",
                "base_fee_destination_label": "官方 Treasury 錢包",
                "acceleration_allowed": False,
                "exemption_reason": "",
                "manual_official_wallet_ops_are_auto": False,
            },
            acceleration_fee_points=fee,
        )
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
        return {
            "ledger_uuid": req["request_uuid"],
            "ledger_hash": req["tx_group_hash"],
            "transaction_hash": req["tx_group_hash"],
            "previous_ledger_hash": "",
            "public_account_id": "",
            "currency_type": DISPLAY_CURRENCY,
            "direction": "transfer_out",
            "amount": int(req.get("amount_points") or 0),
            "action_type": "wallet_transfer",
            "reference_type": "wallet_transfer",
            "reference_id": req["tx_group_hash"],
            "reason": "wallet transfer",
            "input_data": input_data,
            "status": status,
            "created_at": req["created_at"],
            "chain_block_id": block_source["chain_block_id"] if block_source else None,
            "wallet_flow": {
                "source_fund_key": None,
                "destination_fund_key": None,
                "source_label": "From",
                "source_wallet_address": req["source_wallet_address"],
                "destination_label": "To",
                "destination_wallet_address": req["destination_wallet_address"],
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
        except Exception:
            return False
        return True

    def _notify_wallet_transfer_pending(self, conn, req):
        amount = int(req["amount_points"] or 0)
        fee = int(req["fee_points"] or 0)
        tx_hash = req["tx_group_hash"]
        self._notify_wallet_transfer_once(
            conn,
            user_id=req["sender_user_id"],
            notification_type="points_chain_transfer_pending",
            title="鏈上交易已送出",
            body=f"交易 {tx_hash} 正在等待 20/20 Proved；Value {amount} 點，Fee {fee} 點。成交前收款方不會入帳。",
            tx_group_hash=tx_hash,
        )
        self._notify_wallet_transfer_once(
            conn,
            user_id=req["recipient_user_id"],
            notification_type="points_chain_transfer_pending",
            title="收到待確認鏈上交易",
            body=f"交易 {tx_hash} 正在等待 20/20 Proved；Value {amount} 點。成交前不會入帳。",
            tx_group_hash=tx_hash,
        )

    def _notify_wallet_transfer_completed(self, conn, req):
        amount = int(req["amount_points"] or 0)
        fee = int(req["fee_points"] or 0)
        tx_hash = req["tx_group_hash"]
        self._notify_wallet_transfer_once(
            conn,
            user_id=req["sender_user_id"],
            notification_type="points_chain_transfer_completed",
            title="鏈上交易已成交",
            body=f"交易 {tx_hash} 已達 20/20 Proved；已扣除 Value {amount} 點與 Fee {fee} 點。",
            tx_group_hash=tx_hash,
        )
        self._notify_wallet_transfer_once(
            conn,
            user_id=req["recipient_user_id"],
            notification_type="points_chain_transfer_completed",
            title="鏈上交易已入帳",
            body=f"交易 {tx_hash} 已達 20/20 Proved；已入帳 {amount} 點。",
            tx_group_hash=tx_hash,
        )

    def _notify_wallet_transfer_failed(self, conn, req, reason):
        tx_hash = req["tx_group_hash"]
        body = f"交易 {tx_hash} 未成交：{public_currency_text(reason or '交易失敗')}"
        self._notify_wallet_transfer_once(
            conn,
            user_id=req["sender_user_id"],
            notification_type="points_chain_transfer_failed",
            title="鏈上交易未成交",
            body=body,
            tx_group_hash=tx_hash,
        )
        self._notify_wallet_transfer_once(
            conn,
            user_id=req["recipient_user_id"],
            notification_type="points_chain_transfer_failed",
            title="鏈上交易未成交",
            body=body,
            tx_group_hash=tx_hash,
        )

    def _maybe_finalize_transfer_request_locked(self, conn, req, *, actor=None):
        req = dict(req)
        if str(req.get("status") or "") != "pending":
            return conn.execute(
                "SELECT * FROM points_chain_transfer_requests WHERE request_uuid=?",
                (req["request_uuid"],),
            ).fetchone()
        payload = self._transfer_request_public_payload(conn, req)
        if payload["finality"]["finality_status"] != "proved":
            return conn.execute(
                "SELECT * FROM points_chain_transfer_requests WHERE request_uuid=?",
                (req["request_uuid"],),
            ).fetchone()
        total_required = int(req["amount_points"] or 0) + int(req["fee_points"] or 0)
        available = self._wallet_identity_balance_for_address(
            conn,
            user_id=int(req["sender_user_id"]),
            address=req["source_wallet_address"],
        )
        if available < total_required:
            conn.execute(
                "UPDATE points_chain_transfer_requests SET status='failed_insufficient_balance' WHERE request_uuid=? AND status='pending'",
                (req["request_uuid"],),
            )
            failed = conn.execute(
                "SELECT * FROM points_chain_transfer_requests WHERE request_uuid=?",
                (req["request_uuid"],),
            ).fetchone()
            self._notify_wallet_transfer_failed(conn, failed, "sender wallet has insufficient balance at finality")
            return failed
        common = {
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
        in_row, _ = self._record_transaction(
            conn,
            user_id=int(req["recipient_user_id"]),
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
                public_metadata={**common, "fee_destination_fund_key": "official_treasury"},
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
                in_row["ledger_uuid"],
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
        request_hash = self._transfer_request_payload_hash(payload)
        tx_group_hash = sha256_text(f"points-chain-transfer:{request_uuid}:{request_hash}")
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            conn.commit()
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT * FROM points_chain_transfer_requests WHERE request_uuid=?",
                (request_uuid,),
            ).fetchone()
            if existing:
                if existing["request_hash"] != request_hash:
                    raise ValueError("transaction idempotency key conflict")
                existing = self._maybe_finalize_transfer_request_locked(conn, existing, actor=actor)
                conn.commit()
                return {
                    "ok": True,
                    "created": False,
                    "tx_group_hash": existing["tx_group_hash"],
                    "transaction": self._transfer_request_public_payload(conn, existing),
                    **self._transfer_request_ledgers(conn, request_uuid),
                }
            source_wallet = self._wallet_identity_owner_for_address(conn, source)
            destination_wallet = self._wallet_identity_owner_for_address(conn, destination)
            if not source_wallet or int(source_wallet["user_id"] or 0) != actor_id:
                raise PermissionError("source wallet does not belong to current user")
            if source_wallet["wallet_type"] in {"mint", "burn"} or source_wallet["custody_mode"] == "system":
                raise PermissionError("system wallets cannot be spent by user transaction")
            if not destination_wallet or not destination_wallet["user_id"]:
                raise ValueError("destination wallet is not a known user wallet")
            if int(destination_wallet["user_id"]) == actor_id and source == destination:
                raise ValueError("source and destination wallets must differ")
            source_balance = self._wallet_identity_balance_for_address(conn, user_id=actor_id, address=source)
            pending_outgoing = self._pending_transfer_outgoing_for_address(conn, source)
            if source_balance - pending_outgoing < amount + fee:
                raise ValueError("insufficient balance for pending wallet transaction")
            conn.execute(
                """
                INSERT INTO points_chain_transfer_requests (
                    request_uuid, request_hash, tx_group_hash, sender_user_id, recipient_user_id,
                    source_wallet_address, destination_wallet_address, amount_points, fee_points,
                    memo, transfer_out_ledger_uuid, transfer_in_ledger_uuid, fee_ledger_uuid, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, 'pending', ?)
                """,
                (
                    request_uuid,
                    request_hash,
                    tx_group_hash,
                    actor_id,
                    int(destination_wallet["user_id"]),
                    source,
                    destination,
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
            self._notify_wallet_transfer_pending(conn, req)
            conn.commit()
            return {
                "ok": True,
                "created": True,
                "tx_group_hash": tx_group_hash,
                "transaction": self._transfer_request_public_payload(conn, req),
                **self._transfer_request_ledgers(conn, request_uuid),
            }
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
        bootstrap_economy_layer(conn, chain_secret=self.chain_secret, actor={"role": "system", "id": None})
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
            if source_user_id and self._economy_external_address_balance(conn, counterparty_address) < amount:
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
        )

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

    def _last_ledger_hash(self, conn):
        row = conn.execute("SELECT ledger_hash FROM points_ledger ORDER BY id DESC LIMIT 1").fetchone()
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

    def award_admin_initial_grant(self, *, user_id, actor=None):
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

    def award_user_initial_grant(self, *, user_id, actor=None):
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

    def bootstrap_admin_initial_grants(self, *, actor=None, seal_genesis=True):
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
        for admin in admins:
            result = self.award_admin_initial_grant(user_id=admin["id"], actor=actor)
            if result.get("created"):
                created.append({"user_id": admin["id"], "username": admin["username"], "role": admin["role"], "grant": "admin_initial", "amount": ADMIN_INITIAL_POINTS})
        for user in users:
            result = self.award_user_initial_grant(user_id=user["id"], actor=actor)
            if result.get("created"):
                created.append({"user_id": user["id"], "username": user["username"], "role": user["role"], "grant": "user_initial", "amount": USER_INITIAL_POINTS})
        sealed = None
        if seal_genesis and created and not has_blocks:
            sealed = self.seal_block(actor=actor, limit=500)
        return {"ok": True, "created": created, "created_count": len(created), "sealed": sealed}

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
        identity_balances = self._wallet_identity_balances_for_user(conn, user_id)
        if identity_balances.get("has_identity"):
            ledger_address = ""
            if direction in {"credit", "transfer_in"}:
                ledger_address = str(wallet_flow_snapshot.get("destination_wallet_address") or "")
            elif direction in {"debit", "transfer_out", "reverse", "freeze"}:
                ledger_address = str(wallet_flow_snapshot.get("source_wallet_address") or "")
            elif direction == "unfreeze":
                ledger_address = str(wallet_flow_snapshot.get("source_wallet_address") or wallet_flow_snapshot.get("destination_wallet_address") or "")
            if ledger_address not in (identity_balances.get("balances") or {}):
                ledger_address = str(identity_balances.get("primary_address") or "")
            if not ledger_address:
                raise ValueError("active wallet identity is required")
            active = (identity_balances.get("balances") or {}).get(ledger_address, {"balance": 0, "frozen": 0})
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
        status = str(wallet_status or "").strip().lower()
        if status and status not in WALLET_STATUSES:
            raise ValueError("unsupported wallet status")
        risk = str(risk_level or "").strip().lower()
        allowed_risk = {"normal", "watch", "high", "blocked"}
        if risk and risk not in allowed_risk:
            raise ValueError("unsupported wallet risk level")
        reason_text = str(reason or "").strip()
        if not reason_text:
            raise ValueError("reason required")
        freeze_amount = int(freeze_amount or 0)
        unfreeze_amount = int(unfreeze_amount or 0)
        if freeze_amount < 0 or unfreeze_amount < 0:
            raise ValueError("freeze amount must not be negative")
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            conn.commit()
            conn.execute("BEGIN IMMEDIATE")
            self._assert_chain_writable(conn, "wallet sanction")
            target = conn.execute("SELECT id, username, role FROM users WHERE id=?", (int(user_id),)).fetchone()
            if target and (target["username"] == "root" or target["role"] == "super_admin"):
                raise ValueError("root wallet cannot be sanctioned")
            wallet = self.ensure_wallet(conn, user_id)
            ledger_rows = []
            if unfreeze_amount:
                row, _created = self._record_transaction(
                    conn,
                    user_id=user_id,
                    currency_type=DISPLAY_CURRENCY,
                    direction="unfreeze",
                    amount=unfreeze_amount,
                    action_type="root_wallet_unfreeze",
                    reference_type="wallet_sanction",
                    reference_id=str(user_id),
                    reason=reason_text,
                    public_metadata={"wallet_sanction": True, "requested_status": status or wallet["wallet_status"]},
                    actor=actor,
                    risk_flag="root_action",
                    risk_score=0,
                )
                ledger_rows.append(row)
                wallet = conn.execute("SELECT * FROM points_wallets WHERE user_id=?", (int(user_id),)).fetchone()
            if freeze_amount:
                row, _created = self._record_transaction(
                    conn,
                    user_id=user_id,
                    currency_type=DISPLAY_CURRENCY,
                    direction="freeze",
                    amount=freeze_amount,
                    action_type="root_wallet_freeze",
                    reference_type="wallet_sanction",
                    reference_id=str(user_id),
                    reason=reason_text,
                    public_metadata={"wallet_sanction": True, "requested_status": status or wallet["wallet_status"]},
                    actor=actor,
                    risk_flag="root_action",
                    risk_score=0,
                )
                ledger_rows.append(row)
                wallet = conn.execute("SELECT * FROM points_wallets WHERE user_id=?", (int(user_id),)).fetchone()
            next_status = status or wallet["wallet_status"]
            next_risk = risk or wallet["risk_level"]
            now = utc_now()
            conn.execute(
                "UPDATE points_wallets SET wallet_status=?, risk_level=?, updated_at=? WHERE user_id=?",
                (next_status, next_risk, now, int(user_id)),
            )
            self._audit_log(
                conn,
                "WALLET_SANCTION",
                "warning" if next_status in {"frozen", "closed"} or next_risk in {"high", "blocked"} else "info",
                f"wallet sanction user {int(user_id)} status={next_status} risk={next_risk}",
                actor=actor,
                target_user_id=int(user_id),
                metadata={
                    "wallet_status": next_status,
                    "risk_level": next_risk,
                    "reason": reason_text,
                    "freeze_amount": freeze_amount,
                    "unfreeze_amount": unfreeze_amount,
                    "ledger_uuids": [row["ledger_uuid"] for row in ledger_rows],
                },
            )
            conn.commit()
            wallet = conn.execute("SELECT * FROM points_wallets WHERE user_id=?", (int(user_id),)).fetchone()
            result = {
                "ok": True,
                "wallet": self.serialize_wallet(wallet),
                "ledgers": [self.serialize_ledger(row, include_user_id=True) for row in ledger_rows],
            }
            if ledger_rows:
                result["forced_block"] = self.force_seal_block(actor=actor, reason="wallet_sanction")
            return result
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
            self._assert_chain_writable(conn, "earn points")
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
                    submitted_by=actor_value(actor, "id", user_id),
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

    def spend_points(self, *, user_id, item_key, quantity=1, reference_type=None, reference_id=None, idempotency_key=None, metadata=None, actor=None, override_amount=None):
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            conn.commit()
            conn.execute("BEGIN IMMEDIATE")
            self._assert_chain_writable(conn, "spend points")
            item = conn.execute("SELECT * FROM economy_price_catalog WHERE item_key=? AND enabled=1", (item_key,)).fetchone()
            if not item:
                raise ValueError("price catalog item not found or disabled")
            quantity = max(1, int(quantity or 1))
            if override_amount is not None:
                amount = int(override_amount)
            else:
                amount = int(item["base_price"]) * quantity
            spend_bucket = datetime.now(timezone.utc).strftime("%Y%m%d%H%M")
            row, created = self._record_transaction(
                conn,
                user_id=user_id,
                currency_type=item["currency_type"],
                direction="debit",
                amount=amount,
                action_type=f"spend:{item_key}",
                reference_type=reference_type or "price_catalog",
                reference_id=reference_id or item_key,
                idempotency_key=idempotency_key or f"spend:{user_id}:{item_key}:{quantity}:{spend_bucket}",
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

    def admin_adjust(self, *, actor, user_id, currency_type, direction, amount, reason, reference_id=None, idempotency_key=None):
        if direction not in {"credit", "debit"}:
            raise ValueError("direction must be credit or debit")
        if not str(reason or "").strip():
            raise ValueError("reason is required")
        client_reference_id = str(reference_id or "").strip()
        if idempotency_key:
            idem_key = f"admin_adjust:client:{str(idempotency_key).strip()[:120]}"
        elif client_reference_id:
            idem_key = f"admin_adjust:ref:{sha256_text(client_reference_id)}:{direction}"
        else:
            actor_id = actor_value(actor, "id")
            minute_window = int(time.time() // 60)
            reason_hash = sha256_text(str(reason or "").strip())[:16]
            idem_key = f"admin_adjust:auto:{actor_id}:{user_id}:{direction}:{int(amount)}:{reason_hash}:{minute_window}"
        reference_id = client_reference_id or f"actor:{actor_value(actor, 'id')}:target:{user_id}:{utc_now()}"
        result = self.record_transaction(
            user_id=user_id,
            currency_type=currency_type,
            direction=direction,
            amount=amount,
            action_type=f"admin_adjust_{direction}",
            reference_type="admin_adjustment",
            reference_id=reference_id,
            idempotency_key=idem_key,
            reason=reason,
            public_metadata={"admin_action": True},
            private_metadata={"actor_username": actor_value(actor, "username")},
            actor=actor,
        )
        result["forced_block"] = self.force_seal_block(actor=actor, reason="admin_adjust")
        return result

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
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            conn.commit()
            conn.execute("BEGIN IMMEDIATE")
            self._assert_chain_writable(conn, "pending reward creation")
            row = self._create_pending_reward(
                conn,
                user_id=user_id,
                currency_type=currency_type,
                amount=amount,
                action_type=action_type,
                reference_type=reference_type,
                reference_id=reference_id,
                metadata=metadata,
                submitted_by=actor_value(actor, "id"),
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
            self._assert_chain_writable(conn, "pending reward review")
            row = conn.execute("SELECT * FROM points_pending_rewards WHERE id=?", (int(pending_reward_id),)).fetchone()
            if not row:
                raise ValueError("pending reward not found")
            if row["status"] != "pending":
                raise ValueError("pending reward already reviewed")
            if row["submitted_by"] is not None and int(row["submitted_by"]) == int(actor_value(actor, "id") or 0):
                raise ValueError("cannot review your own pending reward")
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
                (status, actor_value(actor, "id"), review_note or "", utc_now(), int(pending_reward_id)),
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

    def rollback_ledger(self, *, actor, ledger_uuid, reason):
        reason = str(reason or "").strip()
        if not reason:
            raise ValueError("reason is required")
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            conn.commit()
            conn.execute("BEGIN IMMEDIATE")
            self._assert_chain_writable(conn, "ledger rollback")
            original = conn.execute("SELECT * FROM points_ledger WHERE ledger_uuid=?", (str(ledger_uuid or ""),)).fetchone()
            if not original:
                raise ValueError("ledger not found")
            if original["ledger_hash"] != compute_ledger_hash(original):
                raise ValueError("ledger is tampered; repair or restore it before rollback")
            if original["status"] == "reversed":
                raise ValueError("ledger already reversed")
            if str(original["action_type"] or "").startswith("rollback:"):
                raise ValueError("rollback ledger cannot be rolled back again")
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
                raise ValueError("unsupported rollback direction")
            rollback_row, created = self._record_transaction(
                conn,
                user_id=original["user_id"],
                currency_type=original["currency_type"],
                direction=reverse_direction,
                amount=original["amount"],
                action_type=f"rollback:{original['action_type']}",
                reference_type="ledger_rollback",
                reference_id=original["ledger_uuid"],
                idempotency_key=f"rollback:{original['ledger_uuid']}",
                reason=reason,
                public_metadata={
                    "rollback_of": original["ledger_uuid"],
                    "original_direction": original["direction"],
                    "original_action_type": original["action_type"],
                },
                private_metadata={"actor_username": actor_value(actor, "username", "")},
                actor=actor,
                risk_flag="emergency_rollback",
                risk_score=100,
            )
            conn.execute("UPDATE points_ledger SET status='reversed' WHERE id=?", (original["id"],))
            self._audit_log(
                conn,
                "LEDGER_ROLLBACK",
                "critical",
                f"rollback ledger {original['ledger_uuid']}",
                actor=actor,
                target_user_id=original["user_id"],
                ledger_id=rollback_row["id"],
                metadata={"original_ledger_uuid": original["ledger_uuid"], "reason": reason, "created": created},
            )
            conn.commit()
            result = {
                "ok": True,
                "created": created,
                "original_ledger": self.serialize_ledger(original, include_user_id=True),
                "rollback_ledger": self.serialize_ledger(rollback_row, include_user_id=True),
                "wallet": self.get_wallet(original["user_id"]),
            }
            result["forced_block"] = self.force_seal_block(actor=actor, reason="ledger_rollback")
            return result
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
        # Phase 7 production-only guard. Runs BEFORE we open a write
        # transaction so a non-production caller never even reaches
        # the chain INSERT path.
        self._assert_production_mode("seal_block")
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            conn.commit()
            conn.execute("BEGIN IMMEDIATE")
            self._assert_chain_writable(conn, "block seal")
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
            self._audit_log(conn, "POINTS_BLOCK_SEALED", "info", f"sealed points block {block_number}", actor=actor, block_id=block_id, metadata={"ledger_count": len(rows)})
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
        # Phase 7: chain writes require mode == 'production'. When mode-
        # switch / snapshot / restore flows call us from non-production
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
                "msg": f"skipped: chain writes are production-only (mode={exc.mode!r})",
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
        self._backfill_missing_block_signatures(conn)
        errors = []
        previous = None
        previous_ledger = None
        for row in conn.execute("SELECT * FROM points_ledger ORDER BY id ASC").fetchall():
                if row["previous_ledger_hash"] != previous:
                    errors.append({
                        "type": "ledger_previous_hash",
                        "severity": "critical",
                        "message": f"ledger #{row['id']} previous hash mismatch",
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
                previous = row["ledger_hash"]
                previous_ledger = row
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
        if not errors:
            errors.extend(self._verify_wallets_against_ledger(conn))
        counts = {
            "ledger_entries": conn.execute("SELECT COUNT(*) AS c FROM points_ledger").fetchone()["c"],
            "sealed_blocks": conn.execute("SELECT COUNT(*) AS c FROM points_chain_blocks").fetchone()["c"],
            "unsealed_entries": conn.execute("SELECT COUNT(*) AS c FROM points_ledger WHERE chain_block_id IS NULL").fetchone()["c"],
            "audit_events": conn.execute("SELECT COUNT(*) AS c FROM points_chain_audit_logs").fetchone()["c"],
            "wallets": conn.execute("SELECT COUNT(*) AS c FROM points_wallets").fetchone()["c"],
        }
        result = {"ok": not errors, "errors": errors[:100], "error_count": len(errors), "counts": counts}
        if mark_safe_mode and errors:
            result["safe_mode"] = self._enter_safe_mode(conn, result, "chain_verification_failed")
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

    def _explorer_finality_estimate(self, fee_points=0):
        fee = max(0, min(EXPLORER_MAX_ACCELERATION_FEE_POINTS, int(fee_points or 0)))
        reduction = min(90, (fee // 10) * 5)
        min_seconds = max(30, EXPLORER_BASE_FINALITY_MIN_SECONDS - reduction)
        max_seconds = max(45, EXPLORER_BASE_FINALITY_MAX_SECONDS - reduction)
        if max_seconds < min_seconds + 15:
            max_seconds = min_seconds + 15
        return {
            "target_proved_count": EXPLORER_FINALITY_PROVED_COUNT,
            "base_seconds_min": EXPLORER_BASE_FINALITY_MIN_SECONDS,
            "base_seconds_max": EXPLORER_BASE_FINALITY_MAX_SECONDS,
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
            "human_rule": "20 Proved 約 2-3 分鐘成交",
        }

    def _explorer_finality_for_ledger(self, conn, ledger):
        accel = self._explorer_acceleration_summary(conn, ledger["ledger_uuid"])
        estimate = self._explorer_finality_estimate(accel["total_fee_points"])
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

    def _explorer_address_balance_from_ledger(self, conn, address, *, limit=25):
        like = f"%{address}%"
        rows = conn.execute(
            """
            SELECT *
            FROM points_ledger
            WHERE status='confirmed'
              AND (public_account_id=? OR public_metadata_json LIKE ?)
            ORDER BY id ASC
            """,
            (address, like),
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
        for row in rows:
            flow = self._ledger_wallet_flow_for_read(conn, row)
            amount = int(row["amount"] or 0)
            direction = str(row["direction"] or "")
            source_address = str(flow.get("source_wallet_address") or "")
            destination_address = str(flow.get("destination_wallet_address") or "")
            matched = source_address == address or destination_address == address or row["public_account_id"] == address
            if not matched:
                continue
            if direction in {"credit", "transfer_in"} and destination_address == address:
                balance += amount
                received_count += 1
                total_received += amount
            elif direction in {"debit", "transfer_out", "reverse"} and source_address == address:
                balance -= amount
                sent_count += 1
                total_sent += amount
                if str(row["action_type"] or "") in {"wallet_transfer_fee", "chain_acceleration_fee"}:
                    fees_paid += amount
            elif direction == "freeze" and source_address == address:
                balance -= amount
                frozen += amount
            elif direction == "unfreeze" and (source_address == address or destination_address == address):
                balance += amount
                frozen -= amount
            public_tx = self._explorer_public_ledger(conn, row)
            recent.append(public_tx)
            first_seen = first_seen or public_tx
            latest_seen = public_tx
        return {
            "points_balance": balance,
            "points_frozen": max(0, frozen),
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
                report = economy_layer_report(conn, chain_secret=self.chain_secret, actor={"role": "system", "id": None})
                fund = (report.get("funds") or {}).get(fund_key) or {}
                balance_payload["points_balance"] = int(fund.get("balance") or 0)
                balance_payload["points_frozen"] = 0
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
                    "points_balance": balance_payload["points_balance"],
                    "points_frozen": balance_payload["points_frozen"],
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
                    "finality_rule": self._explorer_finality_estimate(0),
                    "human_rule": "20 Proved 約 2-3 分鐘成交",
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
            "fee_recipient": economy_fund_address(self.chain_secret, "official_treasury"),
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
                block = conn.execute("SELECT * FROM points_chain_blocks WHERE block_number=?", (int(ref),)).fetchone()
            else:
                block = conn.execute("SELECT * FROM points_chain_blocks WHERE block_hash=?", (ref,)).fetchone()
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
            if not ledger:
                raise ValueError("ledger not found")
            fee_policy = self._explorer_chain_fee_policy(ledger)
            if not fee_policy["acceleration_allowed"]:
                raise ValueError(fee_policy["exemption_reason"] or "this transaction is chain-fee exempt")
            if not self._explorer_actor_can_accelerate(conn, actor=actor, ledger=ledger):
                raise PermissionError("permission denied")
            existing = conn.execute(
                "SELECT * FROM points_chain_acceleration_requests WHERE request_uuid=?",
                (request_uuid,),
            ).fetchone()
            if existing:
                if existing["ledger_uuid"] != ledger["ledger_uuid"] or int(existing["fee_points"] or 0) != fee:
                    raise ValueError("acceleration idempotency key conflict")
                conn.commit()
                refreshed = conn.execute("SELECT * FROM points_ledger WHERE ledger_uuid=?", (ledger["ledger_uuid"],)).fetchone()
                return {
                    "ok": True,
                    "created": False,
                    "acceleration": dict(existing),
                    "result": {"kind": "transaction", "transaction": self._explorer_public_ledger(conn, refreshed)},
                }
            estimate = self._explorer_finality_estimate(fee)
            fee_ledger, _created = self._record_transaction(
                conn,
                user_id=actor_id,
                currency_type=DISPLAY_CURRENCY,
                direction="debit",
                amount=fee,
                action_type="chain_acceleration_fee",
                reference_type="points_chain_explorer",
                reference_id=ledger["ledger_uuid"],
                idempotency_key=f"points_chain_acceleration:{request_uuid}",
                reason="鏈上交易加速費用",
                public_metadata={
                    "accelerated_ledger_uuid": ledger["ledger_uuid"],
                    "accelerated_ledger_hash": ledger["ledger_hash"],
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
                    ledger["ledger_uuid"],
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
            refreshed = conn.execute("SELECT * FROM points_ledger WHERE ledger_uuid=?", (ledger["ledger_uuid"],)).fetchone()
            created_row = conn.execute("SELECT * FROM points_chain_acceleration_requests WHERE request_uuid=?", (request_uuid,)).fetchone()
            return {
                "ok": True,
                "created": True,
                "acceleration": dict(created_row),
                "fee_ledger": self._explorer_public_ledger(conn, fee_ledger),
                "result": {"kind": "transaction", "transaction": self._explorer_public_ledger(conn, refreshed)},
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
            )
            if not economy_layer.get("legacy_bridge", {}).get("bridged_supply_equation_balanced"):
                backfill = self._backfill_walletized_ledger_events(conn)
                if backfill.get("created"):
                    economy_layer = economy_layer_report(
                        conn,
                        chain_secret=self.chain_secret,
                        actor={"role": "system", "id": None},
                        circulation=circulation,
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

    def root_report(self):
        verification = self.verify_chain()
        scheduled_backup = None
        if verification.get("ok"):
            scheduled_backup = self.create_scheduled_backup_if_due()
        stats = self.economy_stats(verification=verification)
        audit_logs = self.list_chain_audit_logs(limit=50)
        adjustments = self.list_admin_adjustments(limit=100)
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
            high_risk_by_id = {int(row["id"]): self.serialize_ledger(row, include_user_id=True) for row in high_risk}
            for error in verification.get("errors") or []:
                ledger = error.get("ledger") if isinstance(error, dict) else None
                ledger_id = int(error.get("ledger_id") or 0) if isinstance(error, dict) else 0
                if not ledger_id:
                    continue
                if not ledger:
                    row = conn.execute("SELECT * FROM points_ledger WHERE id=?", (ledger_id,)).fetchone()
                    ledger = self.serialize_ledger(row, include_user_id=True) if row else None
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
                "adjustments": adjustments,
                "block_schedule": block_schedule,
                "ledger_backups": backups,
                "recovery": recovery,
                "scheduled_backup": scheduled_backup,
            }
        finally:
            conn.close()


from . import backup_recovery as _backup_recovery

for _name in ('_backup_payload', '_chain_head_summary', '_verify_backup_payload', '_write_json_private', 'create_ledger_backup', '_create_ledger_backup', '_load_backup_from_catalog', '_healthy_backups', 'list_ledger_backups', '_prune_ledger_backups', '_scheduled_backup_due', 'create_scheduled_backup_if_due', '_create_forensic_bundle', '_build_restore_plan', '_enter_safe_mode'):
    setattr(PointsLedgerService, _name, getattr(_backup_recovery, _name))

del _backup_recovery
del _name
