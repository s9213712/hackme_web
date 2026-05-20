"""Wallet Service Facade contract for Phase 1.

This module is intentionally not wired into product routes yet.  It defines the
idempotency and append-only write contract that later Phase 1 migrations will
use, without changing existing ComfyUI, trading, video, storage, or game flows.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Callable

from .schema import canonical_json, compute_ledger_hash, sha256_text, utc_now


class WalletFacadeConflict(ValueError):
    """Raised when an idempotency key is reused with a different request."""

    def __init__(self, *, actor_user_id, operation, idempotency_key):
        self.actor_user_id = int(actor_user_id)
        self.operation = str(operation)
        self.idempotency_key = str(idempotency_key)
        super().__init__("idempotency key conflicts with a different request payload")


class WalletFacadeInProgress(RuntimeError):
    """Raised when a prior idempotent operation has no completed result yet."""


class WalletServiceFacade:
    """Contract layer for future walletized product flows.

    The facade stores one idempotency row per actor + operation + key using a
    database-level UNIQUE constraint.  Existing runtime flows do not call this
    class yet; Phase 1 migrations can move one domain at a time behind it.
    """

    IDEMPOTENCY_TABLE = "wallet_facade_idempotency"
    REFUND_DIRECTION_BY_ORIGINAL = {
        "debit": "credit",
        "transfer_out": "transfer_in",
        "reverse": "credit",
    }
    ROLLBACK_DIRECTION_BY_ORIGINAL = {
        "credit": "reverse",
        "transfer_in": "transfer_out",
        "debit": "credit",
        "transfer_out": "transfer_in",
        "freeze": "unfreeze",
        "unfreeze": "freeze",
    }

    def __init__(self, *, points_service):
        self.points_service = points_service
        self.get_db = points_service.get_db

    def ensure_schema(self, conn):
        if hasattr(self.points_service, "ensure_schema"):
            self.points_service.ensure_schema(conn)
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {self.IDEMPOTENCY_TABLE} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                actor_user_id INTEGER NOT NULL,
                operation TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,
                request_hash TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'started',
                result_json TEXT,
                result_ledger_ids_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                expires_at TEXT,
                CHECK (status IN ('started', 'completed', 'failed')),
                UNIQUE(actor_user_id, operation, idempotency_key)
            )
            """
        )
        conn.execute(
            f"""
            CREATE INDEX IF NOT EXISTS idx_{self.IDEMPOTENCY_TABLE}_status
            ON {self.IDEMPOTENCY_TABLE}(status, updated_at)
            """
        )

    def request_hash(self, request_payload):
        return sha256_text(canonical_json(request_payload if request_payload is not None else {}))

    def _assert_write_allowed(self, conn, *, wallet_user_id, operation):
        if hasattr(self.points_service, "_assert_chain_writable"):
            self.points_service._assert_chain_writable(conn, f"wallet facade {operation}")
        if wallet_user_id is None:
            return
        wallet = self.points_service.ensure_wallet(conn, int(wallet_user_id))
        status = str(wallet["wallet_status"] or "active")
        if status == "closed":
            raise ValueError("wallet is closed")
        if status == "frozen":
            raise ValueError("wallet is frozen")

    def _load_idempotency_row(self, conn, *, actor_user_id, operation, idempotency_key):
        return conn.execute(
            f"""
            SELECT * FROM {self.IDEMPOTENCY_TABLE}
            WHERE actor_user_id=? AND operation=? AND idempotency_key=?
            """,
            (int(actor_user_id), str(operation), str(idempotency_key)),
        ).fetchone()

    def _start_idempotency_row(self, conn, *, actor_user_id, operation, idempotency_key, request_hash, expires_at):
        now = utc_now()
        try:
            cur = conn.execute(
                f"""
                INSERT INTO {self.IDEMPOTENCY_TABLE} (
                    actor_user_id, operation, idempotency_key, request_hash,
                    status, created_at, updated_at, expires_at
                ) VALUES (?, ?, ?, ?, 'started', ?, ?, ?)
                """,
                (int(actor_user_id), str(operation), str(idempotency_key), request_hash, now, now, expires_at),
            )
            return conn.execute(f"SELECT * FROM {self.IDEMPOTENCY_TABLE} WHERE id=?", (cur.lastrowid,)).fetchone(), True
        except sqlite3.IntegrityError:
            row = self._load_idempotency_row(
                conn,
                actor_user_id=actor_user_id,
                operation=operation,
                idempotency_key=idempotency_key,
            )
            if not row:
                raise
            return row, False

    def _result_ledger_ids(self, result):
        ledger_ids = result.get("ledger_ids") if isinstance(result, dict) else None
        if ledger_ids is not None:
            return ledger_ids
        if isinstance(result, dict) and isinstance(result.get("ledger"), dict):
            ledger = result["ledger"]
            ledger_id = ledger.get("ledger_uuid") or ledger.get("id")
            return [ledger_id] if ledger_id else []
        return []

    def _completed_payload(self, row):
        try:
            result = json.loads(row["result_json"] or "{}")
        except Exception:
            result = {}
        return {
            "ok": True,
            "created": False,
            "replayed": True,
            "idempotency": {
                "id": row["id"],
                "operation": row["operation"],
                "idempotency_key": row["idempotency_key"],
                "request_hash": row["request_hash"],
                "status": row["status"],
            },
            "result": result,
        }

    def _complete_idempotency_row(self, conn, *, row_id, result):
        result_json = canonical_json(result)
        ledger_ids_json = canonical_json(self._result_ledger_ids(result))
        now = utc_now()
        conn.execute(
            f"""
            UPDATE {self.IDEMPOTENCY_TABLE}
            SET status='completed', result_json=?, result_ledger_ids_json=?, updated_at=?
            WHERE id=?
            """,
            (result_json, ledger_ids_json, now, row_id),
        )
        return conn.execute(f"SELECT * FROM {self.IDEMPOTENCY_TABLE} WHERE id=?", (row_id,)).fetchone()

    def _resolve_wallet_user_id(self, conn, *, wallet_user_id, actor_user_id):
        if callable(wallet_user_id):
            wallet_user_id = wallet_user_id(conn)
        if wallet_user_id is None:
            wallet_user_id = actor_user_id
        return int(wallet_user_id)

    def execute_idempotent(
        self,
        *,
        actor_user_id,
        operation,
        idempotency_key,
        request_payload,
        effect: Callable,
        wallet_user_id=None,
        expires_at=None,
        preflight_replay: Callable | None = None,
    ):
        operation = str(operation or "").strip()
        idempotency_key = str(idempotency_key or "").strip()
        if not operation:
            raise ValueError("operation required")
        if not idempotency_key:
            raise ValueError("idempotency_key required")
        request_hash = self.request_hash(request_payload)
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            conn.commit()
            conn.execute("BEGIN IMMEDIATE")
            row, created = self._start_idempotency_row(
                conn,
                actor_user_id=actor_user_id,
                operation=operation,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                expires_at=expires_at,
            )
            if not created:
                if row["request_hash"] != request_hash:
                    raise WalletFacadeConflict(
                        actor_user_id=actor_user_id,
                        operation=operation,
                        idempotency_key=idempotency_key,
                    )
                if row["status"] != "completed":
                    raise WalletFacadeInProgress("idempotent wallet operation is not completed yet")
                conn.commit()
                return self._completed_payload(row)

            if preflight_replay is not None:
                existing_result = preflight_replay(conn)
                if existing_result is not None:
                    if not isinstance(existing_result, dict):
                        raise ValueError("wallet facade preflight replay must return a dict")
                    completed = self._complete_idempotency_row(conn, row_id=row["id"], result=existing_result)
                    conn.commit()
                    payload = self._completed_payload(completed)
                    payload["deduplicated"] = True
                    return payload

            self._assert_write_allowed(
                conn,
                wallet_user_id=self._resolve_wallet_user_id(conn, wallet_user_id=wallet_user_id, actor_user_id=actor_user_id),
                operation=operation,
            )
            result = effect(conn)
            if result is None:
                result = {}
            if not isinstance(result, dict):
                raise ValueError("wallet facade effect must return a dict")
            completed = self._complete_idempotency_row(conn, row_id=row["id"], result=result)
            conn.commit()
            payload = self._completed_payload(completed)
            payload["created"] = True
            payload["replayed"] = False
            return payload
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _ledger_by_uuid(self, conn, ledger_uuid):
        row = conn.execute("SELECT * FROM points_ledger WHERE ledger_uuid=?", (str(ledger_uuid or ""),)).fetchone()
        if not row:
            raise ValueError("ledger not found")
        if row["ledger_hash"] != compute_ledger_hash(row):
            raise ValueError("ledger is tampered; repair or restore it before wallet facade compensation")
        return row

    def _compensation_by_original(self, conn, *, reference_type, original_ledger_uuid):
        row = conn.execute(
            """
            SELECT * FROM points_ledger
            WHERE reference_type=? AND reference_id=?
            ORDER BY id ASC
            LIMIT 1
            """,
            (reference_type, str(original_ledger_uuid)),
        ).fetchone()
        if row and row["ledger_hash"] != compute_ledger_hash(row):
            raise ValueError("existing compensation ledger is tampered; repair or restore it before replay")
        return row

    def refund(self, *, actor, original_ledger_uuid, reason, idempotency_key):
        """Append a normal business refund for a completed debit-like ledger."""

        actor_user_id = int(actor.get("id") if hasattr(actor, "get") else actor["id"])
        reason = str(reason or "").strip()
        if not reason:
            raise ValueError("reason required")

        def load_original(conn):
            original = self._ledger_by_uuid(conn, original_ledger_uuid)
            direction = self.REFUND_DIRECTION_BY_ORIGINAL.get(original["direction"])
            if not direction:
                raise ValueError("only debit-like ledgers can be refunded")
            return original, direction

        def preflight_replay(conn):
            original, _direction = load_original(conn)
            existing = self._compensation_by_original(
                conn,
                reference_type="ledger_refund",
                original_ledger_uuid=original["ledger_uuid"],
            )
            if existing:
                return {"ledger": self.points_service.serialize_ledger(existing, include_user_id=True)}
            return None

        def effect(conn):
            original, direction = load_original(conn)
            row, _created = self.points_service._record_transaction(
                conn,
                user_id=original["user_id"],
                currency_type=original["currency_type"],
                direction=direction,
                amount=original["amount"],
                action_type=f"refund:{original['action_type']}",
                reference_type="ledger_refund",
                reference_id=original["ledger_uuid"],
                idempotency_key=f"wallet_facade_refund:{original['ledger_uuid']}:{idempotency_key}",
                reason=reason,
                public_metadata={"refund_of": original["ledger_uuid"], "original_action_type": original["action_type"]},
                actor=actor,
            )
            return {"ledger": self.points_service.serialize_ledger(row, include_user_id=True)}

        request = {"original_ledger_uuid": str(original_ledger_uuid), "reason": reason}
        return self.execute_idempotent(
            actor_user_id=actor_user_id,
            operation="refund",
            idempotency_key=idempotency_key,
            request_payload=request,
            effect=effect,
            wallet_user_id=lambda conn: load_original(conn)[0]["user_id"],
            preflight_replay=preflight_replay,
        )

    def rollback(self, *, actor, original_ledger_uuid, reason, idempotency_key):
        """Append an administrative compensation ledger without mutating the original row."""

        actor_user_id = int(actor.get("id") if hasattr(actor, "get") else actor["id"])
        reason = str(reason or "").strip()
        if not reason:
            raise ValueError("reason required")

        def load_original(conn):
            original = self._ledger_by_uuid(conn, original_ledger_uuid)
            direction = self.ROLLBACK_DIRECTION_BY_ORIGINAL.get(original["direction"])
            if not direction:
                raise ValueError("unsupported rollback direction")
            return original, direction

        def preflight_replay(conn):
            original, _direction = load_original(conn)
            existing = self._compensation_by_original(
                conn,
                reference_type="ledger_rollback",
                original_ledger_uuid=original["ledger_uuid"],
            )
            if existing:
                return {"ledger": self.points_service.serialize_ledger(existing, include_user_id=True)}
            return None

        def effect(conn):
            original, direction = load_original(conn)
            row, _created = self.points_service._record_transaction(
                conn,
                user_id=original["user_id"],
                currency_type=original["currency_type"],
                direction=direction,
                amount=original["amount"],
                action_type=f"rollback:{original['action_type']}",
                reference_type="ledger_rollback",
                reference_id=original["ledger_uuid"],
                idempotency_key=f"wallet_facade_rollback:{original['ledger_uuid']}:{idempotency_key}",
                reason=reason,
                public_metadata={"rollback_of": original["ledger_uuid"], "original_action_type": original["action_type"]},
                actor=actor,
                risk_flag="wallet_facade_rollback",
                risk_score=100,
            )
            return {"ledger": self.points_service.serialize_ledger(row, include_user_id=True)}

        request = {"original_ledger_uuid": str(original_ledger_uuid), "reason": reason}
        return self.execute_idempotent(
            actor_user_id=actor_user_id,
            operation="rollback",
            idempotency_key=idempotency_key,
            request_payload=request,
            effect=effect,
            wallet_user_id=lambda conn: load_original(conn)[0]["user_id"],
            preflight_replay=preflight_replay,
        )
