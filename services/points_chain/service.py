"""PointsChain ledger, wallet, and verification service."""

from . import schema as _schema

globals().update({name: value for name, value in _schema.__dict__.items() if not name.startswith("__")})


class PointsLedgerService:
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
        ensure_points_economy_schema(conn)

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

    def _backup_payload(self, conn):
        def rows(sql):
            return [dict(row) for row in conn.execute(sql).fetchall()]

        return {
            "schema_version": POINTS_CHAIN_SCHEMA_VERSION,
            "points_ledger": rows("SELECT * FROM points_ledger ORDER BY id ASC"),
            "points_chain_blocks": rows("SELECT * FROM points_chain_blocks ORDER BY block_number ASC"),
            "points_chain_block_signatures": rows("SELECT * FROM points_chain_block_signatures ORDER BY block_id ASC, node_id ASC"),
            "points_chain_audit_logs": rows("SELECT * FROM points_chain_audit_logs ORDER BY id ASC"),
            "points_wallets_snapshot": rows("SELECT * FROM points_wallets ORDER BY user_id ASC"),
        }

    def _chain_head_summary(self, conn):
        latest = conn.execute("SELECT * FROM points_chain_blocks ORDER BY block_number DESC LIMIT 1").fetchone()
        ledger_count = conn.execute("SELECT COUNT(*) AS c FROM points_ledger").fetchone()["c"]
        wallet_count = conn.execute("SELECT COUNT(*) AS c FROM points_wallets").fetchone()["c"]
        return {
            "chain_height": int(latest["block_number"]) if latest else 0,
            "latest_block_hash": latest["block_hash"] if latest else None,
            "ledger_row_count": int(ledger_count or 0),
            "wallet_count": int(wallet_count or 0),
        }

    def _verify_backup_payload(self, payload, manifest):
        errors = []
        ledgers = payload.get("points_ledger") or []
        blocks = payload.get("points_chain_blocks") or []
        signatures = payload.get("points_chain_block_signatures") or []
        files_hash = sha256_text(canonical_json(payload))
        if files_hash != manifest.get("files_hash"):
            errors.append({"type": "backup_files_hash", "message": "backup data hash mismatch"})
        signature = manifest.get("signature")
        core = {key: value for key, value in manifest.items() if key != "signature"}
        if signature != self._sign_backup_manifest(core):
            errors.append({"type": "backup_signature", "message": "backup manifest HMAC mismatch"})

        previous = None
        for row in ledgers:
            if row.get("previous_ledger_hash") != previous:
                errors.append({"type": "ledger_previous_hash", "ledger_id": row.get("id")})
            expected = compute_ledger_hash(row)
            if row.get("ledger_hash") != expected:
                errors.append({"type": "ledger_hash", "ledger_id": row.get("id"), "expected": expected, "actual": row.get("ledger_hash")})
            previous = row.get("ledger_hash")

        sig_by_block = {(int(row.get("block_id") or 0), row.get("node_id")): row for row in signatures}
        ledger_by_id = {int(row.get("id") or 0): row for row in ledgers}
        previous_block = None
        for block in blocks:
            if block.get("previous_block_hash") != previous_block:
                errors.append({"type": "block_previous_hash", "block_number": block.get("block_number")})
            selected = [
                ledger_by_id[idx]
                for idx in range(int(block.get("first_ledger_id") or 0), int(block.get("last_ledger_id") or 0) + 1)
                if idx in ledger_by_id
            ]
            hashes = [row["ledger_hash"] for row in selected]
            if len(hashes) != int(block.get("ledger_count") or 0):
                errors.append({"type": "block_ledger_count", "block_number": block.get("block_number")})
            expected_merkle = merkle_root(hashes)
            if expected_merkle != block.get("merkle_root"):
                errors.append({"type": "block_merkle_root", "block_number": block.get("block_number")})
            expected_block_hash = compute_block_hash(block)
            if expected_block_hash != block.get("block_hash"):
                errors.append({"type": "block_hash", "block_number": block.get("block_number")})
            sig = sig_by_block.get((int(block.get("id") or 0), "single-node"))
            if not sig:
                errors.append({"type": "block_signature_missing", "block_number": block.get("block_number")})
            elif sig.get("signature") != self._sign_block(block):
                errors.append({"type": "block_signature_invalid", "block_number": block.get("block_number")})
            previous_block = block.get("block_hash")
        return {"ok": not errors, "errors": errors[:100], "error_count": len(errors)}

    def _write_json_private(self, path, payload):
        path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
        try:
            os.chmod(path, 0o600)
        except Exception:
            pass

    def create_ledger_backup(self, *, reason="manual", kind="manual"):
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            result = self._create_ledger_backup(conn, reason=reason, kind=kind)
            conn.commit()
            return result
        finally:
            conn.close()

    def _create_ledger_backup(self, conn, *, reason="manual", kind="manual"):
        root = self._backup_root()
        created_at = utc_now()
        summary = self._chain_head_summary(conn)
        backup_id = f"pcb-{created_at.replace(':', '').replace('-', '').replace('Z', '')}-{uuid.uuid4().hex[:8]}"
        backup_path = root / "backups" / backup_id
        backup_path.mkdir(parents=True, exist_ok=False)
        try:
            os.chmod(backup_path, 0o700)
        except Exception:
            pass
        payload = self._backup_payload(conn)
        files_hash = sha256_text(canonical_json(payload))
        manifest_core = {
            "backup_id": backup_id,
            "kind": kind,
            "created_at": created_at,
            "chain_height": summary["chain_height"],
            "latest_block_hash": summary["latest_block_hash"],
            "ledger_row_count": summary["ledger_row_count"],
            "wallet_count": summary["wallet_count"],
            "schema_version": POINTS_CHAIN_SCHEMA_VERSION,
            "files_hash": files_hash,
            "reason": reason,
        }
        manifest = {**manifest_core, "signature": self._sign_backup_manifest(manifest_core)}
        self._write_json_private(backup_path / "data.json", payload)
        self._write_json_private(backup_path / "manifest.json", manifest)
        verification = self._verify_backup_payload(payload, manifest)
        conn.execute(
            """
            INSERT OR REPLACE INTO points_chain_backup_catalog (
                backup_id, kind, created_at, chain_height, latest_block_hash,
                ledger_row_count, wallet_count, schema_version, backup_path,
                manifest_path, files_hash, signature, verified, verification_json, reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                backup_id,
                kind,
                created_at,
                summary["chain_height"],
                summary["latest_block_hash"],
                summary["ledger_row_count"],
                summary["wallet_count"],
                POINTS_CHAIN_SCHEMA_VERSION,
                str(backup_path),
                str(backup_path / "manifest.json"),
                files_hash,
                manifest["signature"],
                1 if verification["ok"] else 0,
                _json_dumps(verification),
                reason,
            ),
        )
        self._audit_log(
            conn,
            "POINTS_LEDGER_BACKUP_CREATED",
            "info" if verification["ok"] else "critical",
            f"ledger backup {backup_id} created",
            metadata={"backup_id": backup_id, "kind": kind, "verification": verification},
        )
        self._prune_ledger_backups(conn)
        return {"ok": verification["ok"], "backup_id": backup_id, "manifest": manifest, "verification": verification}

    def _load_backup_from_catalog(self, conn, backup_id):
        row = conn.execute("SELECT * FROM points_chain_backup_catalog WHERE backup_id=?", (str(backup_id or ""),)).fetchone()
        if not row:
            return None, None, None
        backup_path = Path(row["backup_path"])
        manifest = json.loads((backup_path / "manifest.json").read_text(encoding="utf-8"))
        payload = json.loads((backup_path / "data.json").read_text(encoding="utf-8"))
        return row, payload, manifest

    def _healthy_backups(self, conn, *, limit=50):
        rows = conn.execute(
            """
            SELECT * FROM points_chain_backup_catalog
            WHERE verified=1
            ORDER BY chain_height DESC, created_at DESC LIMIT ?
            """,
            (min(200, max(1, int(limit or 50))),),
        ).fetchall()
        healthy = []
        for row in rows:
            try:
                _catalog, payload, manifest = self._load_backup_from_catalog(conn, row["backup_id"])
                verification = self._verify_backup_payload(payload, manifest)
                if verification["ok"]:
                    healthy.append(dict(row))
            except Exception:
                continue
        return healthy

    def list_ledger_backups(self, *, limit=100):
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            rows = conn.execute(
                "SELECT * FROM points_chain_backup_catalog ORDER BY created_at DESC LIMIT ?",
                (min(200, max(1, int(limit or 100))),),
            ).fetchall()
            return [{**dict(row), "verification": _json_loads(row["verification_json"], {})} for row in rows]
        finally:
            conn.close()

    def _prune_ledger_backups(self, conn):
        rows = [dict(row) for row in conn.execute("SELECT * FROM points_chain_backup_catalog ORDER BY created_at DESC").fetchall()]
        keep = set()
        daily = {}
        weekly = {}
        for row in rows:
            parsed = parse_utc_timestamp(row["created_at"])
            if not parsed:
                continue
            day = parsed.date().isoformat()
            week = f"{parsed.isocalendar().year}-W{parsed.isocalendar().week:02d}"
            daily.setdefault(day, row["backup_id"])
            weekly.setdefault(week, row["backup_id"])
        keep.update(row["backup_id"] for row in rows[:DEFAULT_BACKUP_KEEP_RECENT])
        keep.update(list(daily.values())[:DEFAULT_BACKUP_KEEP_DAILY])
        keep.update(list(weekly.values())[:DEFAULT_BACKUP_KEEP_WEEKLY])
        for row in rows:
            if row["backup_id"] in keep:
                continue
            try:
                shutil.rmtree(row["backup_path"])
            except Exception:
                pass
            conn.execute("DELETE FROM points_chain_backup_catalog WHERE backup_id=?", (row["backup_id"],))

    def _scheduled_backup_due(self, conn, interval_minutes=DEFAULT_BACKUP_INTERVAL_MINUTES):
        last = conn.execute(
            "SELECT created_at FROM points_chain_backup_catalog ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        if not last:
            return True
        parsed = parse_utc_timestamp(last["created_at"])
        if not parsed:
            return True
        return (datetime.now(timezone.utc) - parsed).total_seconds() >= int(interval_minutes or DEFAULT_BACKUP_INTERVAL_MINUTES) * 60

    def create_scheduled_backup_if_due(self):
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            ledger_count = int(conn.execute("SELECT COUNT(*) FROM points_ledger").fetchone()[0])
            block_count = int(conn.execute("SELECT COUNT(*) FROM points_chain_blocks").fetchone()[0])
            if ledger_count == 0 and block_count == 0:
                return {"ok": True, "created": False, "msg": "empty chain has no scheduled backup"}
            if not self._scheduled_backup_due(conn):
                return {"ok": True, "created": False, "msg": "backup interval not due"}
            result = self._create_ledger_backup(conn, reason="scheduled_interval", kind="scheduled")
            conn.commit()
            result["created"] = True
            return result
        finally:
            conn.close()

    def _create_forensic_bundle(self, conn, verification, reason):
        root = self._backup_root()
        created_at = utc_now()
        bundle_id = f"pcf-{created_at.replace(':', '').replace('-', '').replace('Z', '')}-{uuid.uuid4().hex[:8]}"
        bundle_path = root / "forensics" / bundle_id
        bundle_path.mkdir(parents=True, exist_ok=False)
        try:
            os.chmod(bundle_path, 0o700)
        except Exception:
            pass
        payload = {
            "bundle_id": bundle_id,
            "created_at": created_at,
            "reason": reason,
            "verification": verification,
            "current_ledger": [dict(row) for row in conn.execute("SELECT * FROM points_ledger ORDER BY id ASC").fetchall()],
            "recent_blocks": [dict(row) for row in conn.execute("SELECT * FROM points_chain_blocks ORDER BY block_number DESC LIMIT 20").fetchall()],
            "recent_ledger": [dict(row) for row in conn.execute("SELECT * FROM points_ledger ORDER BY id DESC LIMIT 100").fetchall()],
            "audit_logs": [dict(row) for row in conn.execute("SELECT * FROM points_chain_audit_logs ORDER BY id DESC LIMIT 100").fetchall()],
            "available_backups": [dict(row) for row in conn.execute("SELECT * FROM points_chain_backup_catalog ORDER BY created_at DESC LIMIT 50").fetchall()],
        }
        self._write_json_private(bundle_path / "bundle.json", payload)
        return {"bundle_id": bundle_id, "path": str(bundle_path / "bundle.json"), "created_at": created_at}

    def _build_restore_plan(self, conn, verification, backup):
        current = self._chain_head_summary(conn)
        backup_height = int(backup.get("chain_height") or 0) if backup else 0
        backup_latest_hash = backup.get("latest_block_hash") if backup else None
        lost = []
        if backup:
            backup_row_count = int(backup.get("ledger_row_count") or 0)
            rows = conn.execute(
                "SELECT id, ledger_uuid, user_id, direction, amount, action_type, created_at FROM points_ledger WHERE id>? ORDER BY id ASC",
                (backup_row_count,),
            ).fetchall()
            lost = [dict(row) for row in rows]
        return {
            "mode": "root_confirmed_restore",
            "auto_apply": False,
            "recommended_backup_id": backup.get("backup_id") if backup else None,
            "current_chain_height": current["chain_height"],
            "current_latest_block_hash": current["latest_block_hash"],
            "backup_chain_height": backup_height,
            "backup_latest_block_hash": backup_latest_hash,
            "lost_ledger_range": {
                "from_id": lost[0]["id"] if lost else None,
                "to_id": lost[-1]["id"] if lost else None,
                "count": len(lost),
            },
            "lost_transactions": lost[:100],
            "wallet_rebuild_source": "points_ledger",
            "verification_errors": verification.get("errors", [])[:50],
        }

    def _enter_safe_mode(self, conn, verification, reason):
        row = self._safe_mode_row(conn)
        if row and int(row["safe_mode"] or 0):
            return self._safe_mode_status(conn)
        bundle = self._create_forensic_bundle(conn, verification, reason)
        healthy = self._healthy_backups(conn, limit=50)
        plan = self._build_restore_plan(conn, verification, healthy[0] if healthy else None)
        now = utc_now()
        conn.execute(
            """
            INSERT INTO points_chain_recovery_state (
                id, safe_mode, reason, verification_json, forensic_bundle_id,
                restore_plan_json, created_at, updated_at
            ) VALUES (1, 1, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                safe_mode=1,
                reason=excluded.reason,
                verification_json=excluded.verification_json,
                forensic_bundle_id=excluded.forensic_bundle_id,
                restore_plan_json=excluded.restore_plan_json,
                updated_at=excluded.updated_at
            """,
            (reason, _json_dumps(verification), bundle["bundle_id"], _json_dumps(plan), now, now),
        )
        self._audit_log(
            conn,
            "POINTS_CHAIN_SAFE_MODE_ENTERED",
            "critical",
            "PointsChain tamper detected; writers paused and restore plan prepared",
            metadata={"reason": reason, "forensic_bundle": bundle, "restore_plan": plan},
        )
        return self._safe_mode_status(conn)

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
            if direction in {"credit", "transfer_in"}:
                item["balance"] += amount
                item["earned"] += amount
            elif direction in {"debit", "transfer_out", "reverse"}:
                item["balance"] -= amount
                item["spent"] += amount
            elif direction == "freeze":
                item["balance"] -= amount
                item["frozen"] += amount
            elif direction == "unfreeze":
                item["balance"] += amount
                item["frozen"] -= amount
            if item["balance"] < 0 or item["frozen"] < 0:
                raise ValueError(f"ledger replay would create negative wallet for user {user_id}")
        return totals

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
                "msg": "PointsChain restored and verified",
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

    def _genesis_user_account_rows(self, conn):
        cols = table_columns(conn, "users")
        if "id" not in cols or "username" not in cols or "role" not in cols:
            return []
        status_filter = "AND COALESCE(status, 'active')='active'" if "status" in cols else ""
        return conn.execute(
            f"""
            SELECT id, username, role FROM users
            WHERE username<>'root'
              AND role NOT IN ('manager', 'super_admin')
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
            users = [dict(row) for row in self._genesis_user_account_rows(conn)] if not has_blocks else []
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

        public_json = _metadata_json_checked(public_metadata or {}, label="public_metadata")
        private_json = _metadata_json_checked(private_metadata or {}, label="private_metadata")
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
            (balance_after, frozen_after, earned_delta, spent_delta, now, int(user_id)),
        )
        row = conn.execute("SELECT * FROM points_ledger WHERE id=?", (cur.lastrowid,)).fetchone()
        self._audit_log(
            conn,
            "LEDGER_APPEND",
            "info",
            f"{direction} {amount} {DISPLAY_CURRENCY} for user {user_id}",
            actor=actor,
            target_user_id=int(user_id),
            ledger_id=row["id"],
            metadata={"currency_type": DISPLAY_CURRENCY, "action_type": action_type, "reference_type": reference_type, "reference_id": reference_id},
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
            return [self.serialize_ledger(row, include_user_id=include_user_id) for row in rows]
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
                   OR l.action_type IN ('admin_initial_grant', 'user_initial_grant', 'admin_weekly_salary', 'new_user_signup_bonus')
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
        schedule = self.block_schedule(ledger_threshold=ledger_threshold, max_interval_seconds=max_interval_seconds)
        if not schedule.get("chain_ok", True):
            return {"ok": False, "sealed": False, "msg": "points chain verification failed", "schedule": schedule}
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
            return {"ok": False, "sealed": False, "msg": "points chain verification failed", "verification": verification}
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
        chain = self.verify_chain()
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
            return {"wallets": wallet_data, "ledger": ledger_data, "chain": chain, "currency_type": DISPLAY_CURRENCY}
        finally:
            conn.close()

    def block_schedule(self, *, ledger_threshold=DEFAULT_BLOCK_LEDGER_THRESHOLD, max_interval_seconds=DEFAULT_BLOCK_MAX_INTERVAL_SECONDS):
        verification = self.verify_chain()
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            ledger_threshold = max(1, int(ledger_threshold or DEFAULT_BLOCK_LEDGER_THRESHOLD))
            max_interval_seconds = max(60, int(max_interval_seconds or DEFAULT_BLOCK_MAX_INTERVAL_SECONDS))
            first_unsealed = conn.execute(
                "SELECT created_at FROM points_ledger WHERE chain_block_id IS NULL ORDER BY id ASC LIMIT 1"
            ).fetchone()
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
        stats = self.economy_stats()
        audit_logs = self.list_chain_audit_logs(limit=50)
        adjustments = self.list_admin_adjustments(limit=100)
        block_schedule = self.block_schedule()
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
