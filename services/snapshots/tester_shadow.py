"""Tester token and shadow-state method slice for ServerModeService."""

from . import schema as _schema

globals().update(
    {
        name: value
        for name, value in _schema.__dict__.items()
        if not name.startswith("__")
    }
)

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
        ensure_snapshot_schema(conn)
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
        ensure_snapshot_schema(conn)
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
        ensure_snapshot_schema(conn)
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
        ensure_snapshot_schema(conn)
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
        ensure_snapshot_schema(conn)
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
        ensure_snapshot_schema(conn)
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
        ensure_snapshot_schema(conn)
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

