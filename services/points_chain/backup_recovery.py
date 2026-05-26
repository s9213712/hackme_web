"""Forensic recovery method slice for PointsLedgerService.

PointsChain deliberately does not support ledger backup restore. Recovery must
preserve history through safe mode, forensic bundles, branches, governance, and
ledger replay instead of overwriting the append-only ledger from a backup.
"""

from . import schema as _schema

globals().update({name: value for name, value in _schema.__dict__.items() if not name.startswith("__")})

POINTS_CHAIN_BACKUP_RESTORE_DISABLED_MSG = (
    "PointsChain ledger backup/restore is disabled. Use safe mode, forensic "
    "bundles, recovery branches, emergency governance, and append-only "
    "correction transactions instead of overwriting ledger history."
)

def _backup_payload(self, conn):
    def rows(sql):
        return [dict(row) for row in conn.execute(sql).fetchall()]
    def table_rows(table, order="id ASC"):
        if not table_columns(conn, table):
            return []
        return rows(f"SELECT * FROM {table} ORDER BY {order}")

    return {
        "schema_version": POINTS_CHAIN_SCHEMA_VERSION,
        "points_ledger": rows("SELECT * FROM points_ledger ORDER BY id ASC"),
        "points_chain_blocks": rows("SELECT * FROM points_chain_blocks ORDER BY block_number ASC"),
        "points_chain_block_signatures": rows("SELECT * FROM points_chain_block_signatures ORDER BY block_id ASC, node_id ASC"),
        "points_chain_audit_logs": rows("SELECT * FROM points_chain_audit_logs ORDER BY id ASC"),
        "points_wallets_snapshot": rows("SELECT * FROM points_wallets ORDER BY user_id ASC"),
        "points_wallet_identities": table_rows("points_wallet_identities"),
        "points_wallet_identity_bindings": table_rows("points_wallet_identity_bindings"),
        "points_chain_transfer_requests": table_rows("points_chain_transfer_requests"),
        "points_service_fee_charges": table_rows("points_service_fee_charges"),
        "points_economy_fund_wallets": table_rows("points_economy_fund_wallets", "fund_key ASC"),
        "points_economy_events": table_rows("points_economy_events"),
        "points_economy_derived_balances": table_rows("points_economy_derived_balances", "fund_key ASC"),
        "points_economy_snapshots": table_rows("points_economy_snapshots"),
        "points_economy_incidents": table_rows("points_economy_incidents"),
        "points_chain_governance_proposals": table_rows("points_chain_governance_proposals"),
        "points_chain_governance_votes": table_rows("points_chain_governance_votes"),
        "points_chain_governance_multisig_signatures": table_rows("points_chain_governance_multisig_signatures"),
        "points_chain_governance_audit_log": table_rows("points_chain_governance_audit_log"),
        "points_chain_governance_branches": table_rows("points_chain_governance_branches"),
        "points_chain_address_risk_labels": table_rows("points_chain_address_risk_labels"),
        "points_chain_address_freezes": table_rows("points_chain_address_freezes"),
        "points_chain_address_provisional_freezes": table_rows("points_chain_address_provisional_freezes"),
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

    previous_by_branch = {}
    for row in ledgers:
        branch = str(row.get("chain_branch") or "main")
        previous = previous_by_branch.get(branch)
        if row.get("previous_ledger_hash") != previous:
            errors.append({"type": "ledger_previous_hash", "ledger_id": row.get("id")})
        expected = compute_ledger_hash(row)
        if row.get("ledger_hash") != expected:
            errors.append({"type": "ledger_hash", "ledger_id": row.get("id"), "expected": expected, "actual": row.get("ledger_hash")})
        previous_by_branch[branch] = row.get("ledger_hash")
    branches = payload.get("points_chain_governance_branches") or []
    canonical = [row for row in branches if int(row.get("is_canonical") or 0) == 1 and int(row.get("write_enabled") or 0) == 1]
    ledger_branches = {str(row.get("chain_branch") or "main") for row in ledgers}
    if branches and len(canonical) != 1:
        errors.append({"type": "canonical_branch_count", "count": len(canonical)})
    if any(branch != "main" for branch in ledger_branches) and not branches:
        errors.append({"type": "branch_metadata_missing", "ledger_branches": sorted(ledger_branches)})

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
    return {
        "ok": False,
        "created": False,
        "disabled": True,
        "msg": POINTS_CHAIN_BACKUP_RESTORE_DISABLED_MSG,
        "reason": reason,
        "kind": kind,
    }

def _create_ledger_backup(self, conn, *, reason="manual", kind="manual"):
    raise RuntimeError(POINTS_CHAIN_BACKUP_RESTORE_DISABLED_MSG)

def _load_backup_from_catalog(self, conn, backup_id):
    row = conn.execute("SELECT * FROM points_chain_backup_catalog WHERE backup_id=?", (str(backup_id or ""),)).fetchone()
    if not row:
        return None, None, None
    backup_path = Path(row["backup_path"])
    manifest = json.loads((backup_path / "manifest.json").read_text(encoding="utf-8"))
    payload = json.loads((backup_path / "data.json").read_text(encoding="utf-8"))
    return row, payload, manifest

def _healthy_backups(self, conn, *, limit=50):
    return []

def list_ledger_backups(self, *, limit=100):
    return []

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
    return False

def create_scheduled_backup_if_due(self):
    return {
        "ok": True,
        "created": False,
        "disabled": True,
        "msg": POINTS_CHAIN_BACKUP_RESTORE_DISABLED_MSG,
    }

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
        "available_backups": [],
        "backup_restore_disabled": True,
    }
    self._write_json_private(bundle_path / "bundle.json", payload)
    return {"bundle_id": bundle_id, "path": str(bundle_path / "bundle.json"), "created_at": created_at}

def _build_restore_plan(self, conn, verification, backup=None):
    current = self._chain_head_summary(conn)
    return {
        "mode": "branch_governance_recovery",
        "auto_apply": False,
        "backup_restore_disabled": True,
        "recommended_backup_id": None,
        "current_chain_height": current["chain_height"],
        "current_latest_block_hash": current["latest_block_hash"],
        "backup_chain_height": None,
        "backup_latest_block_hash": None,
        "lost_ledger_range": {
            "from_id": None,
            "to_id": None,
            "count": 0,
        },
        "lost_transactions": [],
        "wallet_rebuild_source": "disabled_backup_restore",
        "verification_errors": verification.get("errors", [])[:50],
        "next_steps": [
            "keep_safe_mode_enabled",
            "review_forensic_bundle",
            "open_recovery_branch_if_history_needs_correction",
            "use_emergency_governance_for_corrective_entries",
            "verify_chain_and_financial_invariants_after_resolution",
        ],
    }

def _enter_safe_mode(self, conn, verification, reason):
    row = self._safe_mode_row(conn)
    if row and int(row["safe_mode"] or 0):
        return self._safe_mode_status(conn)
    bundle = self._create_forensic_bundle(conn, verification, reason)
    plan = self._build_restore_plan(conn, verification)
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
        "PointsChain tamper detected; writers paused and branch/governance recovery plan prepared",
        metadata={"reason": reason, "forensic_bundle": bundle, "restore_plan": plan},
    )
    return self._safe_mode_status(conn)
