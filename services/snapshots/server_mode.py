"""Server mode profile, audit, and checkpoint service."""

from . import schema as _schema

globals().update(
    {
        name: value
        for name, value in _schema.__dict__.items()
        if not name.startswith("__")
    }
)


class ServerModeService:
    def __init__(self, *, snapshot_service, get_db, audit, integrity_guard=None, save_settings=None):
        self.snapshot_service = snapshot_service
        self.get_db = get_db
        self.audit = audit
        self.integrity_guard = integrity_guard
        self.save_settings = save_settings
        if snapshot_service:
            self.runtime_base_dir = Path(snapshot_service.runtime_base_dir)
        elif integrity_guard and getattr(integrity_guard, "base_dir", None):
            self.runtime_base_dir = Path(integrity_guard.base_dir) / "runtime"
        else:
            self.runtime_base_dir = _default_runtime_base_dir()
        self.audit_export_dir = self.runtime_base_dir / "reports" / "server_mode_audit"

    def ensure_schema(self, conn):
        ensure_snapshot_schema(conn)

    def _decode_profile(self, row):
        if not row:
            return None
        data = dict(row)
        for key in ("settings_json", "thresholds_json"):
            try:
                data[key.replace("_json", "")] = json.loads(data.get(key) or "{}")
            except Exception:
                data[key.replace("_json", "")] = {}
            data.pop(key, None)
        data["is_builtin"] = bool(data.get("is_builtin"))
        data["color"] = BUILTIN_SECURITY_PROFILES.get(data.get("name"), {}).get("color", "")
        return data

    def _normalize_mode(self, mode):
        value = str(mode or "").strip().lower()
        if value == "preprod":
            return "dev_ready"
        return value

    def _actor_id(self, actor):
        try:
            return int(actor.get("id") if hasattr(actor, "get") else actor["id"])
        except Exception:
            return 0

    def _actor_name(self, actor):
        try:
            return str(actor.get("username") if hasattr(actor, "get") else actor["username"])
        except Exception:
            return "unknown"

    def _actor_role(self, actor):
        try:
            return str(actor.get("role") if hasattr(actor, "get") else actor["role"])
        except Exception:
            return "unknown"

    def _current_mode_for_keys(self):
        try:
            return self._normalize_mode(self.get_current_mode().get("current_mode"))
        except Exception:
            return "test"

    def _record_security_key(self, *, purpose, key_version, status):
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            conn.execute(
                """
                INSERT INTO security_keys (purpose, key_version, created_at, status)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(purpose, key_version) DO UPDATE SET status=excluded.status
                """,
                (purpose, key_version, datetime.now().isoformat(), status),
            )
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
        finally:
            conn.close()

    def _record_security_key_on_conn(self, conn, *, purpose, key_version, status):
        conn.execute(
            """
            INSERT INTO security_keys (purpose, key_version, created_at, status)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(purpose, key_version) DO UPDATE SET status=excluded.status
            """,
            (purpose, key_version, datetime.now().isoformat(), status),
        )

    def _local_hmac_key_path(self, purpose):
        filename = ".server_mode_log_hmac_key" if purpose == "server_mode_log" else f".{purpose}_hmac_key"
        return self.runtime_base_dir / filename

    def _hmac_key(self, purpose="server_mode_log", current_mode=None):
        purpose_env = {
            "server_mode_log": ("SERVER_MODE_LOG_HMAC_KEY", "SERVER_MODE_LOG_HMAC_KEY_VERSION"),
            "server_mode_token": ("SERVER_MODE_TOKEN_HMAC_KEY", "SERVER_MODE_TOKEN_HMAC_KEY_VERSION"),
            "server_mode_report": ("SERVER_MODE_REPORT_HMAC_KEY", "SERVER_MODE_REPORT_HMAC_KEY_VERSION"),
        }
        env_name, version_env = purpose_env.get(purpose, ("SERVER_MODE_TOKEN_HMAC_KEY", "SERVER_MODE_TOKEN_HMAC_KEY_VERSION"))
        key = os.environ.get(env_name, "").strip()
        version = os.environ.get(version_env, "env-v1").strip() or "env-v1"
        if key:
            return key, version
        mode_for_key_policy = self._normalize_mode(current_mode) if current_mode else self._current_mode_for_keys()
        production_key_required = (
            os.environ.get("HTML_LEARNING_REQUIRE_EXTERNAL_HMAC_KEYS")
            or os.environ.get("HTML_LEARNING_ENV", "").lower() in {"prod", "production"}
        )
        if mode_for_key_policy == "production" and production_key_required and not os.environ.get("HTML_LEARNING_ALLOW_LOCAL_SERVER_MODE_KEYS"):
            raise RuntimeError(f"{env_name} is required in production")
        path = self._local_hmac_key_path(purpose)
        if path.exists():
            key = path.read_text(encoding="utf-8").strip()
        else:
            key = secrets.token_urlsafe(48)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(key + "\n", encoding="utf-8")
            try:
                path.chmod(0o600)
            except Exception:
                pass
        version = "local-dev-v1"
        return key, version

    def _sign_mode_log(self, row):
        key, version = self._hmac_key("server_mode_log")
        payload = {**row, "key_version": version}
        return _hmac_sha256(key, _mode_switch_signature_payload(payload)), version

    def _verify_mode_log_signature(self, row):
        signature = str(row.get("hmac_signature") or "")
        if not signature:
            return {"ok": False, "reason": "missing_signature", "key_version": row.get("key_version") or ""}
        try:
            key, _ = self._hmac_key("server_mode_log")
        except Exception as exc:
            return {"ok": False, "reason": str(exc), "key_version": row.get("key_version") or ""}
        expected = _hmac_sha256(key, _mode_switch_signature_payload(row))
        ok = hmac.compare_digest(signature, expected)
        return {"ok": ok, "reason": "" if ok else "signature_mismatch", "key_version": row.get("key_version") or ""}

    def _export_mode_log_event(self, row):
        self.audit_export_dir.mkdir(parents=True, exist_ok=True)
        event_uuid = row.get("event_uuid") or row.get("id")
        timestamp = str(row.get("created_at") or datetime.now().isoformat()).replace(":", "").replace("-", "")
        payload = {
            "event": row,
            "row_hash": row.get("row_hash"),
            "prev_hash": row.get("prev_hash"),
            "hmac_signature": row.get("hmac_signature"),
            "key_version": row.get("key_version"),
        }
        event_path = self.audit_export_dir / f"{timestamp}_{event_uuid}.json"
        event_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        day = datetime.now().strftime("%Y%m%d")
        bundle = self.audit_export_dir / f"server_mode_audit_{day}.jsonl"
        with bundle.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
        digest = hashlib.sha256(bundle.read_bytes()).hexdigest()
        (self.audit_export_dir / f"server_mode_audit_{day}.sha256").write_text(f"{digest}  {bundle.name}\n", encoding="utf-8")
        return {"event_path": str(event_path), "bundle": str(bundle), "sha256": digest}

    def _prepare_production_report_attestation(
        self,
        *,
        report_type,
        raw_report,
        target_commit="",
        target_branch="",
        server_mode="",
        test_result="",
        passed=False,
        critical_findings_count=0,
        high_findings_count=0,
        unresolved_findings=None,
        tester="",
        report_source="manual_signed_upload",
    ):
        if raw_report is None:
            return {"ok": False, "reason": "missing_raw_report"}
        raw_report_json = _canonical_json_text(raw_report)
        report_hash = f"sha256:{hashlib.sha256(raw_report_json.encode('utf-8')).hexdigest()}"
        key, key_version = self._hmac_key("server_mode_report")
        unresolved_json = _canonical_json_text(list(unresolved_findings or []))
        payload = {
            "report_type": str(report_type or "").strip(),
            "report_hash": report_hash,
            "target_commit": str(target_commit or "").strip(),
            "target_branch": str(target_branch or "").strip(),
            "server_mode": str(server_mode or "").strip(),
            "test_result": str(test_result or "").strip().lower(),
            "pass": 1 if passed else 0,
            "critical_findings_count": int(critical_findings_count or 0),
            "high_findings_count": int(high_findings_count or 0),
            "unresolved_findings_json": unresolved_json,
            "tester": str(tester or "").strip(),
            "raw_report_json": raw_report_json,
            "report_source": str(report_source or "manual_signed_upload").strip() or "manual_signed_upload",
            "key_version": key_version,
        }
        signature = f"hmac_sha256:{_hmac_sha256(key, _production_report_signature_payload(payload))}"
        return {
            "ok": True,
            "report_hash": report_hash,
            "signature": signature,
            "key_version": key_version,
            "raw_report_json": raw_report_json,
            "payload": payload,
        }

    def _verify_production_report_signature(self, row):
        raw_report_json = str(row.get("raw_report_json") or "").strip()
        if not raw_report_json:
            return {"ok": False, "reason": "missing_raw_report_json"}
        try:
            raw_report = json.loads(raw_report_json)
        except Exception:
            return {"ok": False, "reason": "invalid_raw_report_json"}
        normalized_raw_report_json = _canonical_json_text(raw_report)
        expected_hash = f"sha256:{hashlib.sha256(normalized_raw_report_json.encode('utf-8')).hexdigest()}"
        if str(row.get("report_hash") or "").strip() != expected_hash:
            return {"ok": False, "reason": "report_hash_mismatch"}
        signature = str(row.get("signature") or "").strip()
        if not signature:
            return {"ok": False, "reason": "missing_signature"}
        if not signature.startswith("hmac_sha256:"):
            return {"ok": False, "reason": "unsupported_signature_scheme"}
        try:
            key, key_version = self._hmac_key("server_mode_report")
        except Exception as exc:
            return {"ok": False, "reason": str(exc)}
        stored_key_version = str(row.get("key_version") or "").strip()
        if stored_key_version and stored_key_version != key_version:
            return {"ok": False, "reason": "key_version_mismatch", "expected_key_version": key_version}
        payload = {
            "report_type": str(row.get("report_type") or "").strip(),
            "report_hash": expected_hash,
            "target_commit": str(row.get("target_commit") or "").strip(),
            "target_branch": str(row.get("target_branch") or "").strip(),
            "server_mode": str(row.get("server_mode") or "").strip(),
            "test_result": str(row.get("test_result") or "").strip().lower(),
            "pass": int(row.get("pass") or 0),
            "critical_findings_count": int(row.get("critical_findings_count") or 0),
            "high_findings_count": int(row.get("high_findings_count") or 0),
            "unresolved_findings_json": str(row.get("unresolved_findings_json") or "[]"),
            "tester": str(row.get("tester") or "").strip(),
            "raw_report_json": normalized_raw_report_json,
            "report_source": str(row.get("report_source") or "manual_signed_upload").strip() or "manual_signed_upload",
            "key_version": stored_key_version or key_version,
        }
        expected_signature = f"hmac_sha256:{_hmac_sha256(key, _production_report_signature_payload(payload))}"
        return {"ok": hmac.compare_digest(signature, expected_signature), "reason": "" if hmac.compare_digest(signature, expected_signature) else "signature_mismatch", "key_version": stored_key_version or key_version}

    def _stable_hash(self, payload):
        return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()

    def _table_exists(self, conn, table):
        row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
        return bool(row)

    def _settings_snapshot(self, conn):
        if not self._table_exists(conn, "system_settings"):
            return {}
        rows = conn.execute("SELECT key, value FROM system_settings ORDER BY key").fetchall()
        return {row["key"]: row["value"] for row in rows}

    def _points_chain_checkpoint(self, conn):
        payload = {"ledger_count": 0, "block_count": 0, "latest_block_hash": "", "latest_ledger_hash": ""}
        if self._table_exists(conn, "points_ledger"):
            try:
                row = conn.execute("SELECT COUNT(*) AS c FROM points_ledger").fetchone()
                payload["ledger_count"] = int(row["c"] or 0)
                cols = {r["name"] for r in conn.execute("PRAGMA table_info(points_ledger)").fetchall()}
                if "entry_hash" in cols:
                    latest = conn.execute("SELECT entry_hash FROM points_ledger ORDER BY id DESC LIMIT 1").fetchone()
                    payload["latest_ledger_hash"] = latest["entry_hash"] if latest else ""
            except Exception as exc:
                payload["ledger_error"] = str(exc)
        if self._table_exists(conn, "points_chain_blocks"):
            try:
                row = conn.execute("SELECT COUNT(*) AS c FROM points_chain_blocks").fetchone()
                payload["block_count"] = int(row["c"] or 0)
                cols = {r["name"] for r in conn.execute("PRAGMA table_info(points_chain_blocks)").fetchall()}
                hash_col = "block_hash" if "block_hash" in cols else ("hash" if "hash" in cols else "")
                if hash_col:
                    latest = conn.execute(f"SELECT {hash_col} AS h FROM points_chain_blocks ORDER BY id DESC LIMIT 1").fetchone()
                    payload["latest_block_hash"] = latest["h"] if latest else ""
            except Exception as exc:
                payload["block_error"] = str(exc)
        payload["hash"] = self._stable_hash(payload)
        return payload

    def _cloud_drive_metadata_checkpoint(self, conn):
        tables = ["storage_files", "storage_folders", "storage_share_links", "cloud_file_refs", "uploaded_files", "videos"]
        payload = {}
        for table in tables:
            if not self._table_exists(conn, table):
                payload[table] = {"exists": False, "count": 0}
                continue
            try:
                count = conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()["c"]
                payload[table] = {"exists": True, "count": int(count or 0)}
            except Exception as exc:
                payload[table] = {"exists": True, "error": str(exc)}
        payload["hash"] = self._stable_hash(payload)
        return payload

    def _integrity_manifest_hash(self):
        path = getattr(self.integrity_guard, "manifest_path", None) if self.integrity_guard else None
        if not path:
            return ""
        try:
            path_obj = Path(path)
            return _sha256_file(path_obj) if path_obj.is_file() else ""
        except Exception:
            return ""

    def _config_diff(self, current_settings, target_settings):
        diff = {}
        for key, after in (target_settings or {}).items():
            before = current_settings.get(key)
            if str(before) != str(after):
                diff[key] = {"before": before, "after": after}
        return diff

    def _record_mode_switch(
        self,
        conn,
        *,
        from_mode,
        to_mode,
        actor,
        reason="",
        checkpoint_id=None,
        snapshot_id=None,
        success=False,
        error_message="",
        config_diff=None,
        restore_result=None,
        source_ip="",
        user_agent="",
        request_id="",
    ):
        log_id = f"mode_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(4)}"
        event_uuid = secrets.token_hex(16)
        created_at = datetime.now().isoformat()
        prev_row = conn.execute(
            "SELECT row_hash FROM mode_switch_logs ORDER BY created_at DESC, id DESC LIMIT 1"
        ).fetchone()
        prev_hash = (prev_row["row_hash"] if prev_row and prev_row["row_hash"] else "") if prev_row else ""
        row_payload = {
            "id": log_id,
            "event_uuid": event_uuid,
            "from_mode": from_mode,
            "to_mode": to_mode,
            "actor_user_id": self._actor_id(actor),
            "actor_id": self._actor_id(actor),
            "actor_role": self._actor_role(actor),
            "source_ip": source_ip or "",
            "user_agent": user_agent or "",
            "request_id": request_id or "",
            "reason": reason or "",
            "checkpoint_id": checkpoint_id,
            "snapshot_id": snapshot_id,
            "success": 1 if success else 0,
            "error_message": error_message or "",
            "config_diff_json": json.dumps(config_diff or {}, ensure_ascii=False, sort_keys=True),
            "restore_result_json": json.dumps(restore_result or {}, ensure_ascii=False, sort_keys=True),
            "created_at": created_at,
            "server_boot_id": SERVER_BOOT_ID,
        }
        hmac_key, key_version = self._hmac_key("server_mode_log", current_mode=to_mode)
        row_payload["key_version"] = key_version
        row_hash = _mode_switch_log_hash(row_payload, prev_hash)
        row_payload["prev_hash"] = prev_hash
        row_payload["row_hash"] = row_hash
        hmac_signature = _hmac_sha256(hmac_key, _mode_switch_signature_payload(row_payload))
        row_payload["hmac_signature"] = hmac_signature
        self._record_security_key_on_conn(
            conn,
            purpose="server_mode_log",
            key_version=key_version,
            status="active",
        )
        conn.execute(
            """
            INSERT INTO mode_switch_logs
            (id, event_uuid, from_mode, to_mode, actor_user_id, actor_id, actor_role, source_ip, user_agent, request_id,
             reason, checkpoint_id, snapshot_id, success, error_message, config_diff_json, restore_result_json,
             created_at, prev_hash, row_hash, server_boot_id, hmac_signature, key_version)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                log_id,
                event_uuid,
                from_mode,
                to_mode,
                row_payload["actor_user_id"],
                row_payload["actor_id"],
                row_payload["actor_role"],
                row_payload["source_ip"],
                row_payload["user_agent"],
                row_payload["request_id"],
                reason or "",
                checkpoint_id,
                snapshot_id,
                1 if success else 0,
                error_message or "",
                row_payload["config_diff_json"],
                row_payload["restore_result_json"],
                created_at,
                prev_hash,
                row_hash,
                SERVER_BOOT_ID,
                hmac_signature,
                key_version,
            ),
        )
        try:
            export = self._export_mode_log_event(row_payload)
            if not export.get("event_path"):
                raise RuntimeError("empty export path")
        except Exception as exc:
            if self._normalize_mode(to_mode) in {"production", "dev_ready"}:
                raise RuntimeError(f"mode switch audit export failed: {exc}") from exc
        return log_id

    def _enter_incident_lockdown_on_conn(self, conn, *, actor, trigger_type, reason, verification=None):
        now = datetime.now().isoformat()
        current_row = conn.execute("SELECT current_mode FROM server_modes WHERE id=1").fetchone()
        current = current_row["current_mode"] if current_row else None
        incident_id = f"incident_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(4)}"
        conn.execute(
            """
            INSERT INTO incident_reports
            (id, status, trigger_type, reason, entered_by, entered_at, verification_json)
            VALUES (?, 'open', ?, ?, ?, ?, ?)
            """,
            (
                incident_id,
                str(trigger_type or "manual"),
                str(reason or ""),
                self._actor_id(actor),
                now,
                json.dumps(verification or {}, ensure_ascii=False, sort_keys=True),
            ),
        )
        profile = BUILTIN_SECURITY_PROFILES["incident_lockdown"]
        now_updated_by = f"server_mode:{self._actor_name(actor)}"
        if self._table_exists(conn, "system_settings"):
            try:
                epoch_row = conn.execute("SELECT value FROM system_settings WHERE key='server_security_epoch'").fetchone()
                next_epoch = int((epoch_row["value"] if epoch_row else 0) or 0) + 1
            except Exception:
                next_epoch = 1
            conn.execute(
                "INSERT OR REPLACE INTO system_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                ("server_security_epoch", str(next_epoch), now, now_updated_by),
            )
            for key, value in (profile.get("settings") or {}).items():
                conn.execute(
                    "INSERT OR REPLACE INTO system_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                    (key, str(value), now, now_updated_by),
                )
        if self._table_exists(conn, "tester_tokens"):
            conn.execute(
                "UPDATE tester_tokens SET revoked_at=? WHERE revoked_at IS NULL",
                (now,),
            )
        conn.execute(
            """
            UPDATE server_modes
            SET previous_mode=?, current_mode='incident_lockdown', checkpoint_id=NULL, active_snapshot_id=NULL,
                mode_changed_by=?, mode_changed_at=?, notes=?, reason=?, config_json=?
            WHERE id=1
            """,
            (
                current,
                self._actor_id(actor),
                now,
                reason or "",
                reason or "",
                json.dumps(profile, ensure_ascii=False, sort_keys=True),
            ),
        )
        self._record_mode_switch(
            conn,
            from_mode=current,
            to_mode="incident_lockdown",
            actor=actor,
            reason=reason or trigger_type or "",
            success=True,
            config_diff={"trigger_type": trigger_type, "verification": verification or {}},
        )
        return incident_id

    def create_mode_checkpoint(self, *, actor, target_mode, reason="", snapshot_type="mode_checkpoint", from_mode=None):
        target_mode = self._normalize_mode(target_mode)
        if target_mode not in SERVER_MODES and not self.get_profile(target_mode):
            return {"ok": False, "msg": "server mode 錯誤"}
        if not self.snapshot_service:
            return {"ok": False, "msg": "snapshot service unavailable"}
        snapshot = self.snapshot_service.create_snapshot(
            snapshot_type=snapshot_type,
            actor=actor,
            notes=f"server mode checkpoint before {target_mode}: {reason or ''}",
        )
        checkpoint_id = f"chk_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(4)}"
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            current_settings = self._settings_snapshot(conn)
            security_settings = {
                key: current_settings.get(key)
                for key in sorted(current_settings)
                if key.startswith("feature_")
                or key in {
                    "audit_chain_enabled",
                    "ip_blocking_enabled",
                    "login_violation_enabled",
                    "rate_limit_violation_enabled",
                    "integrity_guard_enabled",
                    "integrity_guard_strict_mode",
                    "maintenance_mode",
                    "captcha_mode",
                }
            }
            points = self._points_chain_checkpoint(conn)
            cloud = self._cloud_drive_metadata_checkpoint(conn)
            integrity_hash = self._integrity_manifest_hash()
            db_hash = ""
            try:
                if snapshot.ok and snapshot.snapshot_id:
                    snapshot_row = conn.execute(
                        "SELECT db_dump_path FROM snapshots WHERE id=?",
                        (snapshot.snapshot_id,),
                    ).fetchone()
                    db_dump_path = Path(snapshot_row["db_dump_path"] if snapshot_row else "")
                    if db_dump_path.is_file():
                        db_hash = _sha256_file(db_dump_path)
            except Exception:
                db_hash = ""
            components = {
                "db_snapshot": {"snapshot_id": snapshot.snapshot_id, "hash": db_hash},
                "config": current_settings,
                "security_settings": security_settings,
                "points_chain": points,
                "cloud_drive_metadata": cloud,
                "integrity_manifest": {"hash": integrity_hash},
            }
            conn.execute(
                """
                INSERT INTO server_checkpoints
                (id, snapshot_id, checkpoint_type, from_mode, target_mode, created_by, created_at, status,
                 db_snapshot_hash, config_hash, security_settings_hash, points_chain_hash,
                 cloud_drive_metadata_hash, integrity_manifest_hash, components_json, error_message)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    checkpoint_id,
                    snapshot.snapshot_id,
                    snapshot_type,
                    from_mode,
                    target_mode,
                    self._actor_id(actor),
                    datetime.now().isoformat(),
                    "ready" if snapshot.ok else "failed",
                    db_hash,
                    self._stable_hash(current_settings),
                    self._stable_hash(security_settings),
                    points.get("hash", ""),
                    cloud.get("hash", ""),
                    integrity_hash,
                    json.dumps(components, ensure_ascii=False, sort_keys=True),
                    snapshot.error if not snapshot.ok else "",
                ),
            )
            conn.commit()
        finally:
            conn.close()
        if not snapshot.ok:
            return {"ok": False, "msg": "mode checkpoint snapshot 建立失敗", "checkpoint_id": checkpoint_id, "error": snapshot.error}
        return {
            "ok": True,
            "checkpoint_id": checkpoint_id,
            "snapshot_id": snapshot.snapshot_id,
            "components": components,
        }

    def _checkpoint_record(self, conn, checkpoint_id):
        row = conn.execute("SELECT * FROM server_checkpoints WHERE id=?", (checkpoint_id,)).fetchone()
        return dict(row) if row else None

    def validate_checkpoint_restore(self, *, checkpoint_id, expected_checkpoint=None):
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            checkpoint = expected_checkpoint or self._checkpoint_record(conn, checkpoint_id)
            if not checkpoint:
                return {"ok": False, "msg": "找不到 checkpoint", "checkpoint_id": checkpoint_id}
            try:
                components = json.loads(checkpoint.get("components_json") or "{}")
            except Exception:
                components = {}
            snapshot_id = checkpoint.get("snapshot_id")
            snapshot_verification = {"ok": False, "msg": "snapshot unavailable"}
            if snapshot_id:
                try:
                    snapshot_verification = self.snapshot_service.verify_snapshot(snapshot_id=snapshot_id)
                except Exception as exc:
                    snapshot_verification = {"ok": False, "msg": str(exc)}

            current_settings = self._settings_snapshot(conn)
            security_settings = {
                key: current_settings.get(key)
                for key in sorted(current_settings)
                if key.startswith("feature_")
                or key in {
                    "audit_chain_enabled",
                    "ip_blocking_enabled",
                    "login_violation_enabled",
                    "rate_limit_violation_enabled",
                    "integrity_guard_enabled",
                    "integrity_guard_strict_mode",
                    "maintenance_mode",
                    "captcha_mode",
                }
            }
            current = {
                "config_hash": self._stable_hash(current_settings),
                "security_settings_hash": self._stable_hash(security_settings),
                "points_chain_hash": self._points_chain_checkpoint(conn).get("hash", ""),
                "cloud_drive_metadata_hash": self._cloud_drive_metadata_checkpoint(conn).get("hash", ""),
                "integrity_manifest_hash": self._integrity_manifest_hash(),
            }
            checks = {
                "snapshot_verified": bool(snapshot_verification.get("ok")),
                "config": current["config_hash"] == checkpoint.get("config_hash"),
                "security_settings": current["security_settings_hash"] == checkpoint.get("security_settings_hash"),
                "points_chain": current["points_chain_hash"] == checkpoint.get("points_chain_hash"),
                "cloud_drive_metadata": current["cloud_drive_metadata_hash"] == checkpoint.get("cloud_drive_metadata_hash"),
                "integrity_manifest": current["integrity_manifest_hash"] == (checkpoint.get("integrity_manifest_hash") or ""),
            }
            mismatches = [name for name, ok in checks.items() if not ok]
            return {
                "ok": not mismatches,
                "checkpoint_id": checkpoint_id,
                "snapshot_id": snapshot_id,
                "checks": checks,
                "mismatches": mismatches,
                "snapshot_verification": snapshot_verification,
                "expected": {
                    "config_hash": checkpoint.get("config_hash"),
                    "security_settings_hash": checkpoint.get("security_settings_hash"),
                    "points_chain_hash": checkpoint.get("points_chain_hash"),
                    "cloud_drive_metadata_hash": checkpoint.get("cloud_drive_metadata_hash"),
                    "integrity_manifest_hash": checkpoint.get("integrity_manifest_hash"),
                    "components": components,
                },
                "current": current,
            }
        finally:
            conn.close()

    def list_profiles(self):
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            rows = conn.execute(
                "SELECT * FROM security_profiles ORDER BY is_builtin DESC, name"
            ).fetchall()
            return [self._decode_profile(row) for row in rows]
        finally:
            conn.close()

    def get_profile(self, name):
        profile_name = self._normalize_mode(name)
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            row = conn.execute("SELECT * FROM security_profiles WHERE name=?", (profile_name,)).fetchone()
            return self._decode_profile(row)
        finally:
            conn.close()

    def save_profile(self, *, name, label, description="", settings=None, thresholds=None, actor=None):
        profile_name = str(name or "").strip().lower()
        if not PROFILE_NAME_RE.fullmatch(profile_name):
            return {"ok": False, "msg": "profile name 必須是 2-32 字元的小寫英數、底線或連字號，且以英文字母開頭"}
        if profile_name in SERVER_MODES:
            return {"ok": False, "msg": "內建模式不可覆寫，請使用自定義名稱"}
        settings = settings if isinstance(settings, dict) else {}
        thresholds = thresholds if isinstance(thresholds, dict) else {}
        try:
            actor_id = int(actor["id"] if actor else 0)
        except Exception:
            actor_id = int(actor.get("id") or 0) if hasattr(actor, "get") else 0
        now = datetime.now().isoformat()
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            conn.execute(
                """
                INSERT INTO security_profiles
                (name, label, description, settings_json, thresholds_json, is_builtin, created_by, updated_by, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    label=excluded.label,
                    description=excluded.description,
                    settings_json=excluded.settings_json,
                    thresholds_json=excluded.thresholds_json,
                    updated_by=excluded.updated_by,
                    updated_at=excluded.updated_at
                """,
                (
                    profile_name,
                    str(label or profile_name)[:80],
                    str(description or "")[:500],
                    json.dumps(settings, ensure_ascii=False, sort_keys=True),
                    json.dumps(thresholds, ensure_ascii=False, sort_keys=True),
                    actor_id,
                    actor_id,
                    now,
                    now,
                ),
            )
            conn.commit()
            profile = conn.execute("SELECT * FROM security_profiles WHERE name=?", (profile_name,)).fetchone()
            return {"ok": True, "profile": self._decode_profile(profile)}
        finally:
            conn.close()

    def get_current_mode(self):
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            row = conn.execute("SELECT * FROM server_modes WHERE id=1").fetchone()
            return dict(row)
        finally:
            conn.close()

    def mode_switch_logs(self, *, limit=50):
        limit = max(1, min(int(limit or 50), 200))
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            rows = conn.execute(
                "SELECT * FROM mode_switch_logs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def verify_mode_switch_logs(self):
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            chain = verify_mode_switch_log_hash_chain(conn)
            rows = conn.execute(
                "SELECT * FROM mode_switch_logs ORDER BY created_at ASC, id ASC"
            ).fetchall()
            invalid = []
            for row in rows:
                item = dict(row)
                sig = self._verify_mode_log_signature(item)
                if not sig.get("ok"):
                    invalid.append({"id": item.get("id"), "event_uuid": item.get("event_uuid"), **sig})
            return {
                **chain,
                "chain_length": chain.get("count", 0),
                "broken_links": len(chain.get("mismatches") or []),
                "invalid_signatures": invalid,
                "first_hash": rows[0]["row_hash"] if rows else "",
                "last_hash": chain.get("latest_hash") or "",
                "result": "PASS" if chain.get("ok") and not invalid else "FAIL",
                "ok": bool(chain.get("ok") and not invalid),
            }
        finally:
            conn.close()

    def production_requirements(self):
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            reports = {}
            for report_type in PRODUCTION_REQUIRED_REPORT_TYPES:
                row = conn.execute(
                    """
                    SELECT * FROM production_entry_reports
                    WHERE report_type=?
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (report_type,),
                ).fetchone()
                if row:
                    item = dict(row)
                    sig = self._verify_production_report_signature(item)
                    item["signature_valid"] = bool(sig.get("ok"))
                    item["verification_reason"] = sig.get("reason") or ""
                    item["trust_level"] = str(item.get("trust_level") or ("verified" if sig.get("ok") else "unverified"))
                    reports[report_type] = item
                else:
                    reports[report_type] = None
            missing = [key for key, row in reports.items() if not row]
            failed = [
                key
                for key, row in reports.items()
                if row
                and (
                    not bool(row["pass"])
                    or int(row["critical_findings_count"] or 0) > 0
                    or int(row["high_findings_count"] or 0) > 0
                    or not row["report_hash"]
                    or str(row.get("trust_level") or "").strip() != "verified"
                    or not bool(row.get("signature_valid"))
                )
            ]
            return {
                "ok": not missing and not failed,
                "required": list(PRODUCTION_REQUIRED_REPORT_TYPES),
                "missing": missing,
                "failed": failed,
                "reports": reports,
            }
        finally:
            conn.close()

    def upload_production_report(
        self,
        *,
        actor,
        report_type,
        report_hash,
        target_commit="",
        target_branch="",
        server_mode="",
        test_result="",
        passed=False,
        critical_findings_count=0,
        high_findings_count=0,
        unresolved_findings=None,
        tester="",
        signature="",
        raw_report=None,
        key_version="",
        report_source="manual_signed_upload",
    ):
        report_type = str(report_type or "").strip()
        if report_type not in PRODUCTION_REQUIRED_REPORT_TYPES:
            return {"ok": False, "msg": "report_type 不在 production gate 清單"}
        target_commit = str(target_commit or "").strip()
        target_branch = str(target_branch or "").strip()
        server_mode = str(server_mode or "").strip()
        test_result = str(test_result or "").strip().lower()
        tester = str(tester or self._actor_name(actor) or "").strip()
        signature = str(signature or "").strip()
        if not target_commit or not target_branch or not server_mode or not test_result or not tester or not signature:
            return {"ok": False, "msg": "production report 缺少 target_commit/target_branch/server_mode/test_result/tester/signature"}
        if test_result not in {"pass", "passed"} or not passed:
            return {"ok": False, "msg": "production report 必須明確 pass"}
        if int(critical_findings_count or 0) != 0 or int(high_findings_count or 0) != 0:
            return {"ok": False, "msg": "production report 不允許 critical/high finding"}
        if unresolved_findings:
            return {"ok": False, "msg": "production report 不允許 unresolved finding"}
        attestation = self._prepare_production_report_attestation(
            report_type=report_type,
            raw_report=raw_report,
            target_commit=target_commit,
            target_branch=target_branch,
            server_mode=server_mode,
            test_result=test_result,
            passed=passed,
            critical_findings_count=critical_findings_count,
            high_findings_count=high_findings_count,
            unresolved_findings=unresolved_findings,
            tester=tester,
            report_source=report_source,
        )
        if not attestation.get("ok"):
            return {"ok": False, "msg": "production report 需要 raw_report，伺服器必須重算 hash 並驗證簽章", "reason": attestation.get("reason") or "missing_raw_report"}
        report_hash = str(report_hash or "").strip()
        if not SHA256_REPORT_HASH_RE.fullmatch(report_hash):
            return {"ok": False, "msg": "report_hash 必須是 sha256:<64 hex>"}
        if report_hash != attestation["report_hash"]:
            return {"ok": False, "msg": "report_hash 與 raw_report 內容不一致", "expected_report_hash": attestation["report_hash"]}
        provided_key_version = str(key_version or "").strip()
        if provided_key_version and provided_key_version != attestation["key_version"]:
            return {"ok": False, "msg": "key_version 與伺服器可驗證金鑰不一致", "expected_key_version": attestation["key_version"]}
        if signature != attestation["signature"]:
            return {"ok": False, "msg": "signature 驗證失敗，請確認使用伺服器可驗證的正式報告簽章", "expected_key_version": attestation["key_version"]}
        report_id = f"prodrep_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(4)}"
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            self._record_security_key_on_conn(conn, purpose="server_mode_report", key_version=attestation["key_version"], status="active")
            replay = conn.execute(
                """
                SELECT id FROM production_entry_reports
                WHERE report_type=? AND report_hash=? AND target_commit=?
                LIMIT 1
                """,
                (report_type, report_hash, target_commit),
            ).fetchone()
            if replay:
                return {"ok": False, "msg": "production report replay detected", "existing_report_id": replay["id"]}
            conn.execute(
                """
                INSERT INTO production_entry_reports
                (id, report_type, report_hash, target_commit, target_branch, server_mode, test_result,
                 pass, critical_findings_count, high_findings_count, unresolved_findings_json, tester, signature,
                 raw_report_json, report_source, trust_level, key_version, verified_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    report_id,
                    report_type,
                    report_hash,
                    target_commit,
                    target_branch,
                    server_mode,
                    test_result,
                    1 if passed else 0,
                    int(critical_findings_count or 0),
                    int(high_findings_count or 0),
                    json.dumps(unresolved_findings or [], ensure_ascii=False, sort_keys=True),
                    tester,
                    signature,
                    attestation["raw_report_json"],
                    str(report_source or "manual_signed_upload").strip() or "manual_signed_upload",
                    "verified",
                    attestation["key_version"],
                    datetime.now().isoformat(),
                    datetime.now().isoformat(),
                ),
            )
            conn.commit()
            return {
                "ok": True,
                "report_id": report_id,
                "trust_level": "verified",
                "signature_valid": True,
                "key_version": attestation["key_version"],
                "requirements": self.production_requirements(),
            }
        finally:
            conn.close()

    def create_tester_token(
        self,
        *,
        actor,
        tester_user_id,
        allowed_features=None,
        allowed_routes=None,
        expires_at,
        max_requests_per_minute=60,
        can_modify_own_role=False,
        can_modify_own_points=False,
        can_run_security_tests=False,
    ):
        try:
            tester_user_id = int(tester_user_id)
        except Exception:
            return {"ok": False, "msg": "tester_user_id 必須是數字"}
        expires_at = str(expires_at or "").strip()
        if not expires_at:
            return {"ok": False, "msg": "expires_at 必填"}
        try:
            expires_at_dt = datetime.fromisoformat(expires_at)
        except Exception:
            return {"ok": False, "msg": "expires_at 格式錯誤，請使用本地時間 ISO 8601，例如 2026-05-07T18:30:00"}
        if expires_at_dt.tzinfo is not None:
            return {"ok": False, "msg": "expires_at 目前只接受不含時區的本地時間 ISO 8601，例如 2026-05-07T18:30:00"}
        if expires_at_dt <= datetime.now():
            return {"ok": False, "msg": "expires_at 必須是未來時間，請使用本地時間 ISO 8601"}
        token = f"hmt_{secrets.token_urlsafe(32)}"
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        token_id = f"tester_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(4)}"
        rpm = max(1, min(int(max_requests_per_minute or 60), 600))
        issued_at = datetime.now().isoformat()
        nonce = secrets.token_urlsafe(18)
        mode_scope = ["test", "internal_test"]
        method_scope = ["GET", "POST", "PUT", "PATCH", "DELETE"]
        route_scope = allowed_routes or []
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            key, key_version = self._hmac_key("server_mode_token")
            token_payload = {
                "id": token_id,
                "token_hash": token_hash,
                "tester_user_id": tester_user_id,
                "mode_scope_json": json.dumps(mode_scope, ensure_ascii=False, sort_keys=True),
                "route_scope_json": json.dumps(route_scope, ensure_ascii=False, sort_keys=True),
                "method_scope_json": json.dumps(method_scope, ensure_ascii=False, sort_keys=True),
                "expires_at": expires_at,
                "issued_at": issued_at,
                "nonce": nonce,
                "max_requests_per_minute": rpm,
                "key_version": key_version,
            }
            signature = _hmac_sha256(key, _tester_token_signature_payload(token_payload))
            self._record_security_key_on_conn(
                conn,
                purpose="server_mode_token",
                key_version=key_version,
                status="active",
            )
            conn.execute(
                """
                INSERT INTO tester_tokens
                (id, token_hash, tester_user_id, mode_scope_json, route_scope_json, method_scope_json,
                 allowed_features_json, allowed_routes_json, expires_at, issued_at, nonce,
                 max_requests_per_minute, can_modify_own_role, can_modify_own_points, can_run_security_tests,
                 created_by, created_at, hmac_signature, key_version)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    token_id,
                    token_hash,
                    tester_user_id,
                    token_payload["mode_scope_json"],
                    token_payload["route_scope_json"],
                    token_payload["method_scope_json"],
                    json.dumps(allowed_features or [], ensure_ascii=False, sort_keys=True),
                    json.dumps(route_scope, ensure_ascii=False, sort_keys=True),
                    expires_at,
                    issued_at,
                    nonce,
                    rpm,
                    1 if can_modify_own_role else 0,
                    1 if can_modify_own_points else 0,
                    1 if can_run_security_tests else 0,
                    self._actor_id(actor),
                    issued_at,
                    signature,
                    key_version,
                ),
            )
            conn.commit()
            return {
                "ok": True,
                "token_id": token_id,
                "token": token,
                "expires_at": expires_at,
                "max_requests_per_minute": rpm,
                "warning": "token 只會回傳一次，請交給測試員後妥善保存",
            }
        finally:
            conn.close()

    def revoke_tester_token(self, *, actor, token_id, reason=""):
        token_id = str(token_id or "").strip()
        if not token_id:
            return {"ok": False, "msg": "token_id 必填"}
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            cur = conn.execute(
                "UPDATE tester_tokens SET revoked_at=? WHERE id=? AND revoked_at IS NULL",
                (datetime.now().isoformat(), token_id),
            )
            conn.commit()
            return {"ok": bool(cur.rowcount), "token_id": token_id, "reason": reason or ""}
        finally:
            conn.close()

    def list_tester_tokens(self):
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            rows = conn.execute(
                """
                SELECT id, tester_user_id, mode_scope_json, route_scope_json, method_scope_json,
                       allowed_features_json, allowed_routes_json, expires_at,
                       max_requests_per_minute, can_modify_own_role, can_modify_own_points,
                       can_run_security_tests, created_by, created_at, issued_at, nonce, revoked_at,
                       key_version
                FROM tester_tokens
                ORDER BY created_at DESC
                LIMIT 200
                """
            ).fetchall()
            tokens = []
            for row in rows:
                item = dict(row)
                for key in ("allowed_features_json", "allowed_routes_json", "mode_scope_json", "route_scope_json", "method_scope_json"):
                    try:
                        item[key.replace("_json", "")] = json.loads(item.pop(key) or "[]")
                    except Exception:
                        item[key.replace("_json", "")] = []
                for key in ("can_modify_own_role", "can_modify_own_points", "can_run_security_tests"):
                    item[key] = bool(item.get(key))
                tokens.append(item)
            return tokens
        finally:
            conn.close()

    def _write_tester_token_audit(self, conn, *, token_id="", route="", normalized_route="", method="", allowed=False, reason="", ip_address=""):
        try:
            conn.execute(
                """
                INSERT INTO tester_token_audit
                (token_id, route, normalized_route, method, allowed, reason, source_ip, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (token_id or "", route or "", normalized_route or "", method or "", 1 if allowed else 0, reason or "", ip_address or "", datetime.now().isoformat()),
            )
        except Exception:
            pass

    def active_tester_token(self, *, token, route="", ip_address="", method="", log_request=False):
        token = str(token or "").strip()
        if not token:
            return {"ok": False, "msg": "tester token required"}
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            method = str(method or "GET").upper()
            mode_row = conn.execute("SELECT current_mode FROM server_modes WHERE id=1").fetchone()
            current_mode = self._normalize_mode(mode_row["current_mode"] if mode_row else "dev_ready")
            if current_mode not in {"test", "internal_test"}:
                self._write_tester_token_audit(conn, route=route, method=method, allowed=False, reason="mode_not_allowed", ip_address=ip_address)
                conn.commit()
                return {"ok": False, "msg": "tester token 只能在 test / internal_test 模式使用"}
            row = conn.execute(
                """
                SELECT t.*, u.username, u.role, u.status
                FROM tester_tokens t
                JOIN users u ON u.id=t.tester_user_id
                WHERE t.token_hash=?
                  AND t.revoked_at IS NULL
                  AND t.expires_at>?
                  AND u.status='active'
                LIMIT 1
                """,
                (token_hash, datetime.now().isoformat()),
            ).fetchone()
            if not row:
                self._write_tester_token_audit(conn, route=route, method=method, allowed=False, reason="invalid_expired_or_revoked", ip_address=ip_address)
                conn.commit()
                return {"ok": False, "msg": "tester token 無效、過期或已撤銷"}
            token_row = dict(row)
            try:
                mode_scope = json.loads(token_row.get("mode_scope_json") or '["test","internal_test"]')
            except Exception:
                mode_scope = ["test", "internal_test"]
            if current_mode not in {self._normalize_mode(item) for item in mode_scope}:
                self._write_tester_token_audit(conn, token_id=row["id"], route=route, method=method, allowed=False, reason="mode_scope_denied", ip_address=ip_address)
                conn.commit()
                return {"ok": False, "msg": "tester token 不允許在目前 server mode 使用"}
            try:
                method_scope = {str(item).upper() for item in json.loads(token_row.get("method_scope_json") or "[]")}
            except Exception:
                method_scope = set()
            if method_scope and method not in method_scope:
                self._write_tester_token_audit(conn, token_id=row["id"], route=route, method=method, allowed=False, reason="method_scope_denied", ip_address=ip_address)
                conn.commit()
                return {"ok": False, "msg": "tester token 不允許使用此 HTTP method"}
            signature = token_row.get("hmac_signature") or ""
            if not signature:
                self._write_tester_token_audit(conn, token_id=row["id"], route=route, method=method, allowed=False, reason="missing_token_signature", ip_address=ip_address)
                conn.commit()
                return {"ok": False, "msg": "tester token 缺少簽章，請重新發行"}
            try:
                key, _ = self._hmac_key("server_mode_token", current_mode=current_mode)
                expected_signature = _hmac_sha256(key, _tester_token_signature_payload(token_row))
                signature_ok = hmac.compare_digest(signature, expected_signature)
            except Exception:
                signature_ok = False
            if not signature_ok:
                self._write_tester_token_audit(conn, token_id=row["id"], route=route, method=method, allowed=False, reason="invalid_token_signature", ip_address=ip_address)
                conn.commit()
                return {"ok": False, "msg": "tester token 簽章無效"}
            path = str(route or "")
            normalized_path, route_error = _normalize_mode_route(path)
            if route_error:
                self._write_tester_token_audit(conn, token_id=row["id"], route=path, normalized_route=normalized_path or "", method=method, allowed=False, reason=route_error, ip_address=ip_address)
                conn.commit()
                return {"ok": False, "msg": "tester token 路由包含可疑 traversal 或 encoded bypass"}
            forbidden_prefixes = ("/api/root", "/api/admin", "/api/server-mode", "/api/admin/server-mode", "/api/admin/snapshots", "/api/admin/integrity", "/api/audit")
            if any(normalized_path == prefix or normalized_path.startswith(prefix.rstrip("/") + "/") for prefix in forbidden_prefixes):
                self._write_tester_token_audit(conn, token_id=row["id"], route=path, normalized_route=normalized_path, method=method, allowed=False, reason="forbidden_sensitive_api", ip_address=ip_address)
                conn.commit()
                return {"ok": False, "msg": "tester token 不允許操作 root API"}
            try:
                allowed_routes = json.loads(row["route_scope_json"] or row["allowed_routes_json"] or "[]")
            except Exception:
                allowed_routes = []
            normalized_allowed = []
            for allowed_route in allowed_routes:
                norm, err = _normalize_mode_route(str(allowed_route))
                if norm and not err:
                    normalized_allowed.append(norm)
            if normalized_allowed and normalized_path and not any(normalized_path == route or normalized_path.startswith(str(route).rstrip("/") + "/") for route in normalized_allowed):
                self._write_tester_token_audit(conn, token_id=row["id"], route=path, normalized_route=normalized_path, method=method, allowed=False, reason="route_not_allowed", ip_address=ip_address)
                conn.commit()
                return {"ok": False, "msg": "tester token 不允許操作此路由"}
            window_start = (datetime.now().replace(microsecond=0)).isoformat()
            # keep the window simple and deterministic: compare to one minute ago
            try:
                from datetime import timedelta
                window_start = (datetime.now() - timedelta(seconds=60)).isoformat()
            except Exception:
                pass
            recent = conn.execute(
                "SELECT COUNT(*) AS c FROM tester_token_request_log WHERE token_id=? AND created_at>?",
                (row["id"], window_start),
            ).fetchone()
            max_rpm = max(1, int(row["max_requests_per_minute"] or 60))
            if int(recent["c"] or 0) >= max_rpm:
                self._write_tester_token_audit(conn, token_id=row["id"], route=path, normalized_route=normalized_path, method=method, allowed=False, reason="rate_limited", ip_address=ip_address)
                conn.commit()
                return {"ok": False, "msg": "tester token 已超過每分鐘請求上限"}
            if log_request and path:
                conn.execute(
                    "INSERT INTO tester_token_request_log (token_id, route, ip_address, created_at) VALUES (?, ?, ?, ?)",
                    (row["id"], path, ip_address or "", datetime.now().isoformat()),
                )
            self._write_tester_token_audit(conn, token_id=row["id"], route=path, normalized_route=normalized_path, method=method, allowed=True, reason="allowed", ip_address=ip_address)
            conn.commit()
            item = dict(row)
            for key in ("allowed_features_json", "allowed_routes_json", "mode_scope_json", "route_scope_json", "method_scope_json"):
                try:
                    item[key.replace("_json", "")] = json.loads(item.pop(key) or "[]")
                except Exception:
                    item[key.replace("_json", "")] = []
            for key in ("can_modify_own_role", "can_modify_own_points", "can_run_security_tests"):
                item[key] = bool(item.get(key))
            item.pop("token_hash", None)
            return {"ok": True, "token": item, "mode": current_mode}
        finally:
            conn.close()

    def tester_shadow_state(self, *, actor, token, route="", ip_address=""):
        token_result = self.active_tester_token(token=token, route=route, ip_address=ip_address, log_request=True)
        if not token_result.get("ok"):
            return token_result
        token_row = token_result["token"]
        tester_user_id = int(token_row["tester_user_id"])
        if tester_user_id != self._actor_id(actor):
            return {"ok": False, "msg": "tester token 與目前帳號不一致"}
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            role_row = conn.execute(
                "SELECT * FROM test_shadow_roles WHERE tester_user_id=? ORDER BY id DESC LIMIT 1",
                (tester_user_id,),
            ).fetchone()
            wallet_row = conn.execute(
                "SELECT * FROM test_shadow_wallets WHERE tester_user_id=?",
                (tester_user_id,),
            ).fetchone()
            tx_rows = conn.execute(
                "SELECT * FROM test_shadow_transactions WHERE tester_user_id=? ORDER BY created_at DESC LIMIT 100",
                (tester_user_id,),
            ).fetchall()
            chain_rows = conn.execute(
                "SELECT id, prev_hash, block_hash, created_at FROM test_chain_blocks ORDER BY created_at DESC LIMIT 20"
            ).fetchall()
            return {
                "ok": True,
                "mode": token_result.get("mode"),
                "token": {
                    "id": token_row["id"],
                    "expires_at": token_row["expires_at"],
                    "can_modify_own_role": bool(token_row["can_modify_own_role"]),
                    "can_modify_own_points": bool(token_row["can_modify_own_points"]),
                    "can_run_security_tests": bool(token_row["can_run_security_tests"]),
                },
                "shadow_role": dict(role_row) if role_row else None,
                "shadow_wallet": dict(wallet_row) if wallet_row else {"tester_user_id": tester_user_id, "balance_points": 0},
                "shadow_transactions": [dict(row) for row in tx_rows],
                "test_chain": [dict(row) for row in chain_rows],
            }
        finally:
            conn.close()

    def set_tester_shadow_role(self, *, actor, token, shadow_role, route="", ip_address=""):
        token_result = self.active_tester_token(token=token, route=route, ip_address=ip_address, log_request=True)
        if not token_result.get("ok"):
            return token_result
        token_row = token_result["token"]
        tester_user_id = int(token_row["tester_user_id"])
        if tester_user_id != self._actor_id(actor):
            return {"ok": False, "msg": "tester token 與目前帳號不一致"}
        if not token_row.get("can_modify_own_role"):
            return {"ok": False, "msg": "此 tester token 未允許修改自己的 shadow role"}
        shadow_role = str(shadow_role or "").strip()
        if shadow_role not in {"user", "manager"}:
            return {"ok": False, "msg": "shadow_role 只能是 user 或 manager；tester 不可升成 root"}
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            user = conn.execute("SELECT role FROM users WHERE id=?", (tester_user_id,)).fetchone()
            if not user:
                return {"ok": False, "msg": "找不到 tester user"}
            conn.execute(
                """
                INSERT INTO test_shadow_roles
                (tester_user_id, original_role, shadow_role, token_id, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (tester_user_id, user["role"], shadow_role, token_row["id"], datetime.now().isoformat()),
            )
            conn.commit()
            return {"ok": True, "shadow_role": shadow_role, "original_role": user["role"], "formal_users_table_changed": False}
        finally:
            conn.close()

    def adjust_tester_shadow_wallet(self, *, actor, token, delta_points, reason="", route="", ip_address=""):
        token_result = self.active_tester_token(token=token, route=route, ip_address=ip_address, log_request=True)
        if not token_result.get("ok"):
            return token_result
        token_row = token_result["token"]
        tester_user_id = int(token_row["tester_user_id"])
        if tester_user_id != self._actor_id(actor):
            return {"ok": False, "msg": "tester token 與目前帳號不一致"}
        if not token_row.get("can_modify_own_points"):
            return {"ok": False, "msg": "此 tester token 未允許修改自己的 shadow points"}
        try:
            delta = int(delta_points)
        except Exception:
            return {"ok": False, "msg": "delta_points 必須是整數"}
        if delta == 0:
            return {"ok": False, "msg": "delta_points 不可為 0"}
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            row = conn.execute(
                "SELECT * FROM test_shadow_wallets WHERE tester_user_id=?",
                (tester_user_id,),
            ).fetchone()
            current = int(row["balance_points"] or 0) if row else 0
            next_balance = current + delta
            if next_balance < 0:
                return {"ok": False, "msg": "shadow wallet 不可變成負數"}
            now = datetime.now().isoformat()
            if row:
                conn.execute(
                    "UPDATE test_shadow_wallets SET balance_points=?, token_id=?, updated_at=? WHERE tester_user_id=?",
                    (next_balance, token_row["id"], now, tester_user_id),
                )
            else:
                conn.execute(
                    "INSERT INTO test_shadow_wallets (tester_user_id, balance_points, token_id, updated_at) VALUES (?, ?, ?, ?)",
                    (tester_user_id, next_balance, token_row["id"], now),
                )
            tx_id = f"shadow_tx_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(4)}"
            conn.execute(
                """
                INSERT INTO test_shadow_transactions
                (id, tester_user_id, delta_points, reason, token_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (tx_id, tester_user_id, delta, str(reason or "")[:500], token_row["id"], now),
            )
            prev = conn.execute(
                "SELECT block_hash FROM test_chain_blocks ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            prev_hash = prev["block_hash"] if prev else "GENESIS"
            block_id = f"testblk_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(4)}"
            tx_payload = {
                "tx_id": tx_id,
                "tester_user_id": tester_user_id,
                "delta_points": delta,
                "balance_after": next_balance,
                "reason": reason or "",
            }
            block_hash = self._stable_hash({"id": block_id, "prev_hash": prev_hash, "tx": tx_payload, "created_at": now})
            conn.execute(
                """
                INSERT INTO test_chain_blocks
                (id, prev_hash, block_hash, transactions_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (block_id, prev_hash, block_hash, json.dumps([tx_payload], ensure_ascii=False, sort_keys=True), now),
            )
            conn.commit()
            return {
                "ok": True,
                "transaction_id": tx_id,
                "test_block_id": block_id,
                "balance_points": next_balance,
                "formal_points_chain_changed": False,
            }
        finally:
            conn.close()

    def enter_incident_lockdown(self, *, actor, trigger_type, reason, verification=None):
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            incident_id = self._enter_incident_lockdown_on_conn(
                conn,
                actor=actor,
                trigger_type=trigger_type,
                reason=reason,
                verification=verification or {},
            )
            conn.commit()
            self.audit("SERVER_MODE_INCIDENT_LOCKDOWN_ENTER", "-", user=self._actor_name(actor), success=True, detail=f"incident_id={incident_id},trigger={trigger_type},reason={reason}")
            return {"ok": True, "incident_id": incident_id, "mode": self.get_current_mode()}
        finally:
            conn.close()

    def incident_status(self):
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            row = conn.execute("SELECT * FROM incident_reports WHERE status='open' ORDER BY entered_at DESC LIMIT 1").fetchone()
            mode_row = conn.execute("SELECT * FROM server_modes WHERE id=1").fetchone()
            return {"ok": True, "incident": dict(row) if row else None, "mode": dict(mode_row) if mode_row else None}
        finally:
            conn.close()

    def resolve_incident(self, *, actor, confirm, notes="", verification=None):
        if confirm != "RESOLVE_INCIDENT":
            return {"ok": False, "msg": "confirm 必須等於 RESOLVE_INCIDENT"}
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            row = conn.execute("SELECT * FROM incident_reports WHERE status='open' ORDER BY entered_at DESC LIMIT 1").fetchone()
            if not row:
                return {"ok": False, "msg": "目前沒有 open incident"}
            now = datetime.now().isoformat()
            conn.execute(
                """
                UPDATE incident_reports
                SET status='resolved', resolved_by=?, resolved_at=?, resolution_notes=?, verification_json=?
                WHERE id=?
                """,
                (
                    self._actor_id(actor),
                    now,
                    notes or "",
                    json.dumps(verification or {}, ensure_ascii=False, sort_keys=True),
                    row["id"],
                ),
            )
            conn.commit()
            return {"ok": True, "incident_id": row["id"], "resolved_at": now}
        finally:
            conn.close()

    def _apply_production_upload_policy(self, conn):
        try:
            from services.security.upload_security import ensure_upload_security_schema, update_cloud_drive_security_policy
        except Exception:
            return {"ok": False, "msg": "upload security policy unavailable"}
        ensure_upload_security_schema(conn)
        policy, msg = update_cloud_drive_security_policy(conn, {
            "require_scan_before_download": True,
            "block_unclean_downloads": True,
            "warn_high_risk_downloads": True,
            "allow_inline_preview_for_high_risk": False,
            "e2ee_server_scan_claim_allowed": False,
            "revoke_shares_on_suspension": True,
            "scanner_enabled": True,
            "scanner_backend": "clamav",
            "scanner_timeout_seconds": 60,
            "fail_closed_on_scanner_error": True,
            "quarantine_on_infected": True,
            "validate_magic_mime": True,
            "deep_archive_scan_enabled": True,
            "max_archive_depth": 2,
            "office_macro_scan_enabled": True,
            "image_reencode_enabled": True,
            "image_reencode_max_pixels": 25_000_000,
            "yara_enabled": True,
            "max_archive_files": 200,
            "max_archive_uncompressed_bytes": 50 * 1024 * 1024,
            "max_daily_downloads": 500,
            "notes": "production mode: strict scan, fail-closed download, quarantine and content validation enabled",
        })
        if msg:
            return {"ok": False, "msg": msg}
        return {"ok": True, "policy": policy}

    def _apply_production_account_policy(self, conn, *, actor):
        user_cols = {row["name"] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
        if "username" not in user_cols or "id" not in user_cols:
            return {"default_password_reset_required": 0, "test_accounts_disabled": 0, "sessions_revoked": 0}
        now = datetime.now().isoformat()

        default_where = ["username IN ({})".format(",".join("?" for _ in DEFAULT_ACCOUNT_NAMES))]
        default_params = list(DEFAULT_ACCOUNT_NAMES)
        if "is_default_password" in user_cols:
            default_where.append("COALESCE(is_default_password, 0)=1")
        default_rows = conn.execute(
            f"SELECT id FROM users WHERE {' OR '.join(default_where)}",
            tuple(default_params),
        ).fetchall()
        default_ids = [int(row["id"]) for row in default_rows]
        default_updates = []
        if "must_change_password" in user_cols:
            default_updates.append("must_change_password=1")
        if "is_default_password" in user_cols:
            default_updates.append("is_default_password=1")
        if "updated_at" in user_cols:
            default_updates.append("updated_at=?")
        if default_ids and default_updates:
            params = []
            if "updated_at" in user_cols:
                params.append(now)
            placeholders = ",".join("?" for _ in default_ids)
            conn.execute(
                f"UPDATE users SET {', '.join(default_updates)} WHERE id IN ({placeholders})",
                tuple(params + default_ids),
            )

        test_rows = conn.execute(
            "SELECT id FROM users WHERE username IN ({})".format(",".join("?" for _ in TEST_ACCOUNT_NAMES)),
            tuple(TEST_ACCOUNT_NAMES),
        ).fetchall()
        test_ids = [int(row["id"]) for row in test_rows]
        if test_ids and "status" in user_cols:
            updates = ["status='inactive'"]
            if "updated_at" in user_cols:
                updates.append("updated_at=?")
            params = [now] if "updated_at" in user_cols else []
            placeholders = ",".join("?" for _ in test_ids)
            conn.execute(
                f"UPDATE users SET {', '.join(updates)} WHERE id IN ({placeholders})",
                tuple(params + test_ids),
            )

        sessions_revoked = 0
        session_cols = set()
        try:
            session_cols = {row["name"] for row in conn.execute("PRAGMA table_info(sessions)").fetchall()}
        except Exception:
            session_cols = set()
        if test_ids and {"user_id", "is_revoked"}.issubset(session_cols):
            placeholders = ",".join("?" for _ in test_ids)
            updates = ["is_revoked=1"]
            params = []
            if "revoked_at" in session_cols:
                updates.append("revoked_at=?")
                params.append(now)
            cur = conn.execute(
                f"UPDATE sessions SET {', '.join(updates)} WHERE user_id IN ({placeholders}) AND COALESCE(is_revoked, 0)=0",
                tuple(params + test_ids),
            )
            sessions_revoked = int(cur.rowcount or 0)

        return {
            "default_password_reset_required": len(default_ids),
            "test_accounts_disabled": len(test_ids),
            "sessions_revoked": sessions_revoked,
            "password_policy": "forced reset uses the account password-strength policy",
            "actor": actor.get("username") if hasattr(actor, "get") else None,
        }

    def _apply_production_hardening(self, *, actor):
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            account_result = self._apply_production_account_policy(conn, actor=actor)
            upload_policy = self._apply_production_upload_policy(conn)
            if not upload_policy.get("ok"):
                conn.rollback()
                return {"ok": False, "msg": upload_policy.get("msg") or "production upload policy failed"}
            conn.commit()
            return {"ok": True, "accounts": account_result, "cloud_drive_policy": upload_policy.get("policy")}
        finally:
            conn.close()

    def _apply_internal_test_hardening(self):
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            now = datetime.now().isoformat()
            session_cols = set()
            try:
                session_cols = {row["name"] for row in conn.execute("PRAGMA table_info(sessions)").fetchall()}
            except Exception:
                session_cols = set()
            revoked = 0
            if {"user_id", "is_revoked"}.issubset(session_cols):
                updates = ["is_revoked=1"]
                params = []
                if "revoked_at" in session_cols:
                    updates.append("revoked_at=?")
                    params.append(now)
                cur = conn.execute(
                    f"""
                    UPDATE sessions
                    SET {', '.join(updates)}
                    WHERE COALESCE(is_revoked, 0)=0
                          AND user_id IN (
                              SELECT id FROM users
                              WHERE username<>'root'
                          )
                    """,
                    tuple(params),
                )
                revoked = int(cur.rowcount or 0)
            conn.commit()
            return {"ok": True, "sessions_revoked": revoked}
        finally:
            conn.close()

    def switch_mode(self, *, target_mode, actor, confirm, notes=None):
        original_target = str(target_mode or "").strip().lower()
        target_mode = self._normalize_mode(original_target)
        profile = self.get_profile(target_mode)
        if not profile:
            return {"ok": False, "msg": "server mode 錯誤"}
        expected_confirm = MODE_CONFIRM_PHRASES.get(target_mode, "SWITCH_CUSTOM_MODE")
        if confirm != expected_confirm:
            return {"ok": False, "msg": f"confirm 必須等於 {expected_confirm}"}
        if target_mode == "production":
            requirements = self.production_requirements()
            if not requirements.get("ok"):
                return {
                    "ok": False,
                    "msg": "production gate 未通過，缺少報告或仍有 critical/high finding",
                    "requirements": requirements,
                }
            if self.integrity_guard:
                try:
                    allowed, high_risk_count = self.integrity_guard.can_enter_preprod()
                except Exception:
                    allowed, high_risk_count = False, 1
                if not allowed:
                    conn = self.get_db()
                    try:
                        self.ensure_schema(conn)
                        current_row = conn.execute("SELECT current_mode FROM server_modes WHERE id=1").fetchone()
                        self._record_mode_switch(
                            conn,
                            from_mode=(current_row["current_mode"] if current_row else "test"),
                            to_mode="production",
                            actor=actor,
                            reason=notes or "",
                            success=False,
                            error_message="integrity guard high risk finding",
                            config_diff={"high_risk_count": high_risk_count},
                        )
                        self._enter_incident_lockdown_on_conn(
                            conn,
                            actor=actor,
                            trigger_type="integrity_high_risk",
                            reason="production entry blocked by high risk Integrity Guard finding",
                            verification={"high_risk_count": high_risk_count},
                        )
                        conn.commit()
                    finally:
                        conn.close()
                    return {
                        "ok": False,
                        "msg": "Integrity Guard 存在高風險異常，不允許進入 production，已進入 incident_lockdown",
                        "high_risk_count": high_risk_count,
                        "incident_lockdown": True,
                    }
        applied_settings = {}
        production_result = None
        internal_test_result = None
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            current_row = conn.execute("SELECT current_mode FROM server_modes WHERE id=1").fetchone()
            current = self._normalize_mode(current_row["current_mode"] if current_row else "test")
            if current == "incident_lockdown" and target_mode == "superweak":
                self._record_mode_switch(
                    conn,
                    from_mode=current,
                    to_mode=target_mode,
                    actor=actor,
                    reason=notes or "",
                    success=False,
                    error_message="incident_lockdown 不允許切換到 superweak",
                )
                conn.commit()
                return {"ok": False, "msg": "incident_lockdown 不允許切換到 superweak"}
            current_settings = self._settings_snapshot(conn)
            config_diff = self._config_diff(current_settings, {**(profile.get("settings") or {}), **(profile.get("thresholds") or {})})
        finally:
            conn.close()

        checkpoint = self.create_mode_checkpoint(
            actor=actor,
            target_mode=target_mode,
            reason=notes or "",
            snapshot_type="before_superweak" if target_mode == "superweak" else "mode_checkpoint",
            from_mode=current,
        )
        if not checkpoint.get("ok"):
            conn = self.get_db()
            try:
                self.ensure_schema(conn)
                self._record_mode_switch(
                    conn,
                    from_mode=current,
                    to_mode=target_mode,
                    actor=actor,
                    reason=notes or "",
                    success=False,
                    error_message=checkpoint.get("msg") or checkpoint.get("error") or "checkpoint failed",
                )
                self._enter_incident_lockdown_on_conn(
                    conn,
                    actor=actor,
                    trigger_type="mode_switch_failed",
                    reason=f"checkpoint before {target_mode} failed",
                    verification=checkpoint,
                )
                conn.commit()
            finally:
                conn.close()
            return {**checkpoint, "msg": checkpoint.get("msg") or "checkpoint 建立失敗，已進入 incident_lockdown", "incident_lockdown": True}

        try:
            if self.save_settings:
                updates = {}
                updates.update(profile.get("settings") or {})
                updates.update(profile.get("thresholds") or {})
                applied_settings = self.save_settings(updates) if updates else {}
            if target_mode == "production":
                production_result = self._apply_production_hardening(actor=actor)
                if not production_result.get("ok"):
                    raise RuntimeError(production_result.get("msg") or "production hardening failed")
            if target_mode == "internal_test":
                internal_test_result = self._apply_internal_test_hardening()
        except Exception as exc:
            conn = self.get_db()
            try:
                self.ensure_schema(conn)
                self._record_mode_switch(
                    conn,
                    from_mode=current,
                    to_mode=target_mode,
                    actor=actor,
                    reason=notes or "",
                    checkpoint_id=checkpoint.get("checkpoint_id"),
                    snapshot_id=checkpoint.get("snapshot_id"),
                    success=False,
                    error_message=str(exc),
                    config_diff=config_diff,
                )
                self._enter_incident_lockdown_on_conn(
                    conn,
                    actor=actor,
                    trigger_type="mode_switch_failed",
                    reason=f"mode switch to {target_mode} failed: {exc}",
                    verification={"checkpoint": checkpoint, "target_mode": target_mode},
                )
                conn.commit()
            finally:
                conn.close()
            return {"ok": False, "msg": "模式切換套用設定失敗，已進入 incident_lockdown", "error": str(exc), "checkpoint": checkpoint}

        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            now = datetime.now().isoformat()
            conn.execute(
                """
                UPDATE server_modes
                SET previous_mode=?, current_mode=?, active_snapshot_id=?, checkpoint_id=?,
                    mode_changed_by=?, mode_changed_at=?, notes=?, reason=?, config_json=?
                WHERE id=1
                """,
                (
                    current,
                    target_mode,
                    checkpoint.get("snapshot_id") if target_mode == "superweak" else None,
                    checkpoint.get("checkpoint_id"),
                    self._actor_id(actor),
                    now,
                    notes or "",
                    notes or "",
                    json.dumps(profile, ensure_ascii=False, sort_keys=True),
                ),
            )
            self._record_mode_switch(
                conn,
                from_mode=current,
                to_mode=target_mode,
                actor=actor,
                reason=notes or "",
                checkpoint_id=checkpoint.get("checkpoint_id"),
                snapshot_id=checkpoint.get("snapshot_id"),
                success=True,
                config_diff=config_diff,
                restore_result={},
            )
            chain = verify_mode_switch_log_hash_chain(conn)
            if not chain.get("ok"):
                self._enter_incident_lockdown_on_conn(
                    conn,
                    actor=actor,
                    trigger_type="mode_switch_log_chain_broken",
                    reason=f"mode switch log hash chain failed after switching to {target_mode}",
                    verification=chain,
                )
                conn.commit()
                return {"ok": False, "msg": "mode switch log chain broken; incident_lockdown entered", "chain": chain, "incident_lockdown": True}
            conn.commit()
            event = "SUPERWEAK_ENTER" if target_mode == "superweak" else "SERVER_MODE_CHANGE"
            self.audit(event, "-", user=self._actor_name(actor), success=True, detail=f"old_value={current},new_value={target_mode},profile={profile['name']},checkpoint={checkpoint.get('checkpoint_id')},snapshot={checkpoint.get('snapshot_id')},settings={applied_settings},production={production_result or {}},internal_test={internal_test_result or {}},reason={notes or ''}")
            return {"ok": True, "mode": self.get_current_mode(), "profile": profile, "applied_settings": applied_settings, "production": production_result, "internal_test": internal_test_result, "checkpoint": checkpoint}
        finally:
            conn.close()

    def enter_superweak(self, *, actor, confirm, notes=None):
        current = self.get_current_mode()
        if self._normalize_mode(current.get("current_mode")) == "superweak":
            return {"ok": False, "msg": "目前已是 superweak 模式"}
        return self.switch_mode(target_mode="superweak", actor=actor, confirm=confirm, notes=notes)

    def exit_superweak(self, *, actor, action, confirm, reason):
        current = self.get_current_mode()
        if self._normalize_mode(current.get("current_mode")) != "superweak":
            return {"ok": False, "msg": "目前不是 superweak 模式"}
        if action == "keep_dirty_state":
            return {"ok": False, "msg": "Server Mode v2 禁止保留 superweak dirty state；離開 superweak 必須還原 checkpoint"}
        if action == "restore":
            if confirm != "RESTORE_BEFORE_SUPERWEAK":
                return {"ok": False, "msg": "confirm 必須等於 RESTORE_BEFORE_SUPERWEAK"}
            snapshot_id = current["active_snapshot_id"]
            checkpoint_id = current.get("checkpoint_id")
            expected_checkpoint = None
            if checkpoint_id:
                conn = self.get_db()
                try:
                    self.ensure_schema(conn)
                    expected_checkpoint = self._checkpoint_record(conn, checkpoint_id)
                finally:
                    conn.close()
            result = self.snapshot_service.restore_snapshot(snapshot_id=snapshot_id, actor=actor, reason=reason or "exit superweak", dry_run=False)
            if not result.get("ok"):
                conn = self.get_db()
                try:
                    self.ensure_schema(conn)
                    self._record_mode_switch(
                        conn,
                        from_mode="superweak",
                        to_mode=current["previous_mode"] or "test",
                        actor=actor,
                        reason=reason or "",
                        checkpoint_id=checkpoint_id,
                        snapshot_id=snapshot_id,
                        success=False,
                        error_message=result.get("msg") or result.get("error") or "restore failed",
                        restore_result=result,
                    )
                    self._enter_incident_lockdown_on_conn(
                        conn,
                        actor=actor,
                        trigger_type="restore_validation_failed",
                        reason="exit superweak restore failed",
                        verification=result,
                    )
                    conn.commit()
                finally:
                    conn.close()
                return {**result, "incident_lockdown": True}
            validation = self.validate_checkpoint_restore(checkpoint_id=checkpoint_id, expected_checkpoint=expected_checkpoint) if checkpoint_id else {"ok": False, "msg": "missing checkpoint_id"}
            if not validation.get("ok"):
                conn = self.get_db()
                try:
                    self.ensure_schema(conn)
                    self._record_mode_switch(
                        conn,
                        from_mode="superweak",
                        to_mode=current["previous_mode"] or "test",
                        actor=actor,
                        reason=reason or "",
                        checkpoint_id=checkpoint_id,
                        snapshot_id=snapshot_id,
                        success=False,
                        error_message="checkpoint restore validation failed",
                        restore_result=validation,
                    )
                    self._enter_incident_lockdown_on_conn(
                        conn,
                        actor=actor,
                        trigger_type="restore_validation_failed",
                        reason="superweak checkpoint restore validation failed",
                        verification=validation,
                    )
                    conn.commit()
                finally:
                    conn.close()
                return {"ok": False, "msg": "superweak 還原驗證失敗，已進入 incident_lockdown", "restore": result, "validation": validation, "incident_lockdown": True}
            previous = self._normalize_mode(current["previous_mode"] or "test")
            conn = self.get_db()
            try:
                self.ensure_schema(conn)
                conn.execute(
                    """
                    UPDATE server_modes
                    SET current_mode=?, previous_mode='superweak', active_snapshot_id=NULL, checkpoint_id=NULL,
                        mode_changed_by=?, mode_changed_at=?, notes=?, reason=?
                    WHERE id=1
                    """,
                    (previous, self._actor_id(actor), datetime.now().isoformat(), reason or "", reason or ""),
                )
                self._record_mode_switch(
                    conn,
                    from_mode="superweak",
                    to_mode=previous,
                    actor=actor,
                    reason=reason or "",
                    checkpoint_id=checkpoint_id,
                    snapshot_id=snapshot_id,
                    success=True,
                    restore_result={"restore": result, "validation": validation},
                )
                conn.commit()
            finally:
                conn.close()
            self.audit("SUPERWEAK_EXIT_RESTORE", "-", user=self._actor_name(actor), success=True, detail=f"restored_snapshot={snapshot_id},checkpoint={checkpoint_id},new_value={previous},reason={reason}")
            return {"ok": True, "mode": self.get_current_mode(), "validation": validation, **result}
        return {"ok": False, "msg": "action 錯誤"}

    def recover_superweak_on_startup(self, *, actor=None):
        actor = actor or {"id": 0, "username": "system-startup", "role": "system"}
        current = self.get_current_mode()
        if self._normalize_mode(current.get("current_mode")) != "superweak":
            return {"ok": True, "recovered": False, "mode": current}
        snapshot_id = current.get("active_snapshot_id")
        checkpoint_id = current.get("checkpoint_id")
        if not snapshot_id or not checkpoint_id:
            conn = self.get_db()
            try:
                self.ensure_schema(conn)
                self._record_mode_switch(
                    conn,
                    from_mode="superweak",
                    to_mode="incident_lockdown",
                    actor=actor,
                    reason="startup superweak recovery failed: missing checkpoint/snapshot",
                    success=False,
                    error_message="missing active_snapshot_id or checkpoint_id",
                )
                self._enter_incident_lockdown_on_conn(
                    conn,
                    actor=actor,
                    trigger_type="superweak_recovery_failed",
                    reason="startup found superweak without active checkpoint",
                    verification={"mode": current},
                )
                conn.commit()
            finally:
                conn.close()
            return {"ok": False, "recovered": False, "incident_lockdown": True, "msg": "superweak startup recovery missing checkpoint"}
        expected_checkpoint = None
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            expected_checkpoint = self._checkpoint_record(conn, checkpoint_id)
        finally:
            conn.close()
        result = self.snapshot_service.restore_snapshot(
            snapshot_id=snapshot_id,
            actor=actor,
            reason="startup recovery after superweak crash",
            dry_run=False,
        )
        validation = self.validate_checkpoint_restore(checkpoint_id=checkpoint_id, expected_checkpoint=expected_checkpoint)
        previous = self._normalize_mode(current.get("previous_mode") or "test")
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            if result.get("ok") and validation.get("ok"):
                conn.execute(
                    """
                    UPDATE server_modes
                    SET current_mode=?, previous_mode='superweak', active_snapshot_id=NULL, checkpoint_id=NULL,
                        mode_changed_by=?, mode_changed_at=?, notes=?, reason=?
                    WHERE id=1
                    """,
                    (
                        previous,
                        self._actor_id(actor),
                        datetime.now().isoformat(),
                        "startup recovered superweak dirty state",
                        "startup recovered superweak dirty state",
                    ),
                )
                self._record_mode_switch(
                    conn,
                    from_mode="superweak",
                    to_mode=previous,
                    actor=actor,
                    reason="startup recovered superweak dirty state",
                    checkpoint_id=checkpoint_id,
                    snapshot_id=snapshot_id,
                    success=True,
                    restore_result={"restore": result, "validation": validation},
                )
                conn.commit()
                self.audit("SUPERWEAK_STARTUP_RECOVERY", "-", user=self._actor_name(actor), success=True, detail=f"snapshot={snapshot_id},checkpoint={checkpoint_id},new_value={previous}")
                return {"ok": True, "recovered": True, "mode": self.get_current_mode(), "restore": result, "validation": validation}
            self._record_mode_switch(
                conn,
                from_mode="superweak",
                to_mode="incident_lockdown",
                actor=actor,
                reason="startup superweak recovery validation failed",
                checkpoint_id=checkpoint_id,
                snapshot_id=snapshot_id,
                success=False,
                error_message="restore or validation failed",
                restore_result={"restore": result, "validation": validation},
            )
            self._enter_incident_lockdown_on_conn(
                conn,
                actor=actor,
                trigger_type="superweak_recovery_failed",
                reason="startup superweak restore validation failed",
                verification={"restore": result, "validation": validation},
            )
            conn.commit()
            return {"ok": False, "recovered": False, "incident_lockdown": True, "restore": result, "validation": validation}
        finally:
            conn.close()
