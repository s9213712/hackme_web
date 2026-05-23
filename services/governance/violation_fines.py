import json
import uuid
from datetime import datetime, timedelta


VIOLATION_FINE_TRIGGER_POINTS = 3
VIOLATION_FINE_BASE_AMOUNT = 300
VIOLATION_FINE_STEP_AMOUNT = 100
VIOLATION_FINE_DUE_HOURS = 72
VIOLATION_FINE_INTEREST_PERIOD_HOURS = 24
VIOLATION_FINE_INTEREST_RATE_PER_10000 = 500
VIOLATION_FINE_INTEREST_MIN_POINTS = 10
VIOLATION_FINE_INTEREST_CAP_RATE_PER_10000 = 5000
VIOLATION_FINE_POLICY_KEY = "three_strikes_unlock"
VIOLATION_FINE_ITEM_KEY = "violation_fine"
VIOLATION_FINE_DEFAULT_RESTRICTIONS = (
    "community_post",
    "community_comment",
    "chat_dm",
    "cloud_upload",
    "video_publish",
    "trading_order",
    "service_spend",
)

FEATURE_LABELS = {
    "community_post": "討論區發文",
    "community_comment": "留言 / 回覆",
    "chat_dm": "私訊",
    "chat_send": "聊天發言",
    "cloud_upload": "雲端上傳",
    "video_publish": "影音發布",
    "trading_order": "交易所下單",
    "service_spend": "站內付費功能",
    "wallet_transfer": "錢包轉出",
}


def _now():
    return datetime.now().replace(microsecond=0)


def _now_text():
    return _now().isoformat()


def _parse_dt(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


def _json_dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_loads(value, default):
    try:
        parsed = json.loads(value or "")
        return parsed if parsed is not None else default
    except Exception:
        return default


def normalize_feature_key(value):
    key = str(value or "").strip().lower().replace("-", "_")
    return key if key in FEATURE_LABELS else ""


def normalize_restriction_features(values):
    if isinstance(values, str):
        raw = [item.strip() for item in values.split(",")]
    elif isinstance(values, (list, tuple, set)):
        raw = list(values)
    else:
        raw = []
    features = []
    for item in raw:
        key = normalize_feature_key(item)
        if key and key not in features:
            features.append(key)
    return features or list(VIOLATION_FINE_DEFAULT_RESTRICTIONS)


def ensure_violation_fine_schema(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS violation_fines (
            id                         INTEGER PRIMARY KEY AUTOINCREMENT,
            fine_uuid                  TEXT NOT NULL UNIQUE,
            policy_key                 TEXT NOT NULL DEFAULT 'manual',
            violation_id               INTEGER,
            user_id                    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            username                   TEXT NOT NULL,
            amount_points              INTEGER NOT NULL CHECK (amount_points > 0),
            reason                     TEXT NOT NULL,
            status                     TEXT NOT NULL DEFAULT 'pending',
            due_at                     TEXT NOT NULL,
            created_by                 TEXT NOT NULL,
            created_at                 TEXT NOT NULL,
            updated_at                 TEXT NOT NULL,
            paid_at                    TEXT,
            waived_at                  TEXT,
            cancelled_at               TEXT,
            payment_ledger_uuid        TEXT,
            payment_charge_uuid        TEXT,
            payment_source_wallet_address TEXT,
            restriction_features_json  TEXT NOT NULL DEFAULT '[]',
            metadata_json              TEXT,
            CHECK (status IN ('pending', 'overdue', 'paid', 'waived', 'cancelled'))
        )
        """
    )
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(violation_fines)").fetchall()}
    additions = {
        "policy_key": "TEXT NOT NULL DEFAULT 'manual'",
        "overdue_interest_points": "INTEGER NOT NULL DEFAULT 0",
        "interest_updated_at": "TEXT",
        "payment_source_wallet_address": "TEXT",
        "restriction_features_json": "TEXT NOT NULL DEFAULT '[]'",
        "metadata_json": "TEXT",
    }
    for name, ddl in additions.items():
        if name not in cols:
            conn.execute(f"ALTER TABLE violation_fines ADD COLUMN {name} {ddl}")
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_violation_fines_violation
        ON violation_fines(violation_id)
        WHERE violation_id IS NOT NULL
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_violation_fines_user_status ON violation_fines(user_id, status, due_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_violation_fines_policy ON violation_fines(policy_key, status)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS user_feature_restrictions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            restriction_uuid TEXT NOT NULL UNIQUE,
            user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            feature_key     TEXT NOT NULL,
            status          TEXT NOT NULL DEFAULT 'active',
            source_type     TEXT NOT NULL,
            source_ref      TEXT NOT NULL,
            reason          TEXT NOT NULL,
            starts_at       TEXT NOT NULL,
            expires_at      TEXT,
            created_by      TEXT NOT NULL,
            created_at      TEXT NOT NULL,
            released_at     TEXT,
            release_reason  TEXT,
            metadata_json   TEXT,
            CHECK (status IN ('active', 'released', 'cancelled', 'expired'))
        )
        """
    )
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_user_feature_restrictions_source
        ON user_feature_restrictions(user_id, feature_key, source_type, source_ref)
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_user_feature_restrictions_user_status ON user_feature_restrictions(user_id, status, feature_key)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS violation_fine_appeals (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            fine_uuid       TEXT NOT NULL,
            user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            username        TEXT NOT NULL,
            reason          TEXT NOT NULL,
            status          TEXT NOT NULL DEFAULT 'pending',
            reviewed_by     TEXT,
            reviewed_at     TEXT,
            review_note     TEXT,
            created_at      TEXT NOT NULL,
            updated_at      TEXT NOT NULL,
            CHECK (status IN ('pending', 'approved', 'rejected')),
            UNIQUE(fine_uuid, user_id)
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_violation_fine_appeals_status ON violation_fine_appeals(status, created_at)")


def serialize_feature_restriction(row):
    if not row:
        return None
    data = dict(row)
    data["feature_label"] = FEATURE_LABELS.get(data.get("feature_key"), data.get("feature_key") or "")
    data["metadata"] = _json_loads(data.get("metadata_json"), {})
    return data


def serialize_violation_fine(row):
    if not row:
        return None
    data = dict(row)
    data["amount_points"] = int(data.get("amount_points") or 0)
    data["overdue_interest_points"] = int(data.get("overdue_interest_points") or 0)
    data["amount_due_points"] = data["amount_points"] + data["overdue_interest_points"]
    data["restriction_features"] = normalize_restriction_features(_json_loads(data.get("restriction_features_json"), []))
    data["restriction_feature_labels"] = [FEATURE_LABELS.get(key, key) for key in data["restriction_features"]]
    data["metadata"] = _json_loads(data.get("metadata_json"), {})
    due_at = _parse_dt(data.get("due_at"))
    data["is_overdue"] = bool(data.get("status") == "overdue" or (data.get("status") == "pending" and due_at and due_at <= _now()))
    data["is_payable"] = data.get("status") in {"pending", "overdue"}
    data["interest_policy"] = {
        "period_hours": VIOLATION_FINE_INTEREST_PERIOD_HOURS,
        "rate_per_10000": VIOLATION_FINE_INTEREST_RATE_PER_10000,
        "min_points": VIOLATION_FINE_INTEREST_MIN_POINTS,
        "cap_rate_per_10000": VIOLATION_FINE_INTEREST_CAP_RATE_PER_10000,
        "destination": "burn",
    }
    return data


def _calculate_overdue_interest_points(row, now_dt):
    due_at = _parse_dt(row["due_at"])
    if not due_at or now_dt <= due_at:
        return 0
    amount = int(row["amount_points"] or 0)
    if amount <= 0:
        return 0
    overdue_seconds = max(0, int((now_dt - due_at).total_seconds()))
    periods = overdue_seconds // (VIOLATION_FINE_INTEREST_PERIOD_HOURS * 3600)
    if periods <= 0:
        return 0
    raw = (amount * VIOLATION_FINE_INTEREST_RATE_PER_10000 * periods + 9999) // 10000
    interest = max(VIOLATION_FINE_INTEREST_MIN_POINTS, raw)
    cap = (amount * VIOLATION_FINE_INTEREST_CAP_RATE_PER_10000 + 9999) // 10000
    return min(interest, max(0, cap))


def _notify_user(conn, *, user_id, title, body, fine_uuid="", severity="warning"):
    try:
        from services.system.notifications import create_notification

        create_notification(
            conn,
            user_id=int(user_id),
            type="violation_fine",
            title=title,
            body=body,
            link="/#appeals",
            severity=severity,
            source_module="violation_fines",
            source_ref=fine_uuid or None,
        )
    except Exception:
        pass


def create_violation_fine(
    conn,
    *,
    user_id,
    username,
    amount_points,
    reason,
    created_by,
    violation_id=None,
    due_hours=VIOLATION_FINE_DUE_HOURS,
    restriction_features=None,
    policy_key="manual",
    metadata=None,
):
    ensure_violation_fine_schema(conn)
    if violation_id not in (None, ""):
        existing = conn.execute("SELECT * FROM violation_fines WHERE violation_id=?", (int(violation_id),)).fetchone()
        if existing:
            return serialize_violation_fine(existing), False
    amount = int(amount_points)
    if amount <= 0:
        raise ValueError("fine amount must be positive")
    due = _now() + timedelta(hours=max(1, int(due_hours or VIOLATION_FINE_DUE_HOURS)))
    features = normalize_restriction_features(restriction_features)
    fine_uuid = "pcfine:" + str(uuid.uuid4())
    now = _now_text()
    conn.execute(
        """
        INSERT INTO violation_fines (
            fine_uuid, policy_key, violation_id, user_id, username, amount_points, reason,
            status, due_at, created_by, created_at, updated_at, restriction_features_json,
            metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?)
        """,
        (
            fine_uuid,
            str(policy_key or "manual")[:80],
            int(violation_id) if violation_id not in (None, "") else None,
            int(user_id),
            str(username or "")[:80],
            amount,
            str(reason or "違規罰款")[:1000],
            due.isoformat(),
            str(created_by or "system")[:80],
            now,
            now,
            _json_dumps(features),
            _json_dumps(metadata or {}),
        ),
    )
    row = conn.execute("SELECT * FROM violation_fines WHERE fine_uuid=?", (fine_uuid,)).fetchone()
    _notify_user(
        conn,
        user_id=user_id,
        fine_uuid=fine_uuid,
        title="違規罰款待繳",
        body=f"你的違規計點已達罰款門檻，需於 {due.isoformat()} 前繳納 {amount} 點；逾期將限制指定功能。",
    )
    return serialize_violation_fine(row), True


def maybe_create_three_strike_fine(conn, *, user_id, username, role, violation_id, violation_count, reason, actor_username):
    ensure_violation_fine_schema(conn)
    if str(username or "") == "root":
        return None, False
    if str(role or "user") != "user":
        return None, False
    count = int(violation_count or 0)
    if count < VIOLATION_FINE_TRIGGER_POINTS:
        return None, False
    existing = conn.execute(
        """
        SELECT * FROM violation_fines
        WHERE user_id=? AND policy_key=? AND status IN ('pending', 'overdue')
        ORDER BY id DESC LIMIT 1
        """,
        (int(user_id), VIOLATION_FINE_POLICY_KEY),
    ).fetchone()
    if existing:
        return serialize_violation_fine(existing), False
    amount = VIOLATION_FINE_BASE_AMOUNT + max(0, count - VIOLATION_FINE_TRIGGER_POINTS) * VIOLATION_FINE_STEP_AMOUNT
    return create_violation_fine(
        conn,
        user_id=user_id,
        username=username,
        amount_points=amount,
        reason=f"違規計點達 {count} 點，需繳納罰款後解除逾期功能限制。來源：{reason or '違規計點'}",
        created_by=actor_username or "system",
        violation_id=violation_id,
        due_hours=VIOLATION_FINE_DUE_HOURS,
        restriction_features=VIOLATION_FINE_DEFAULT_RESTRICTIONS,
        policy_key=VIOLATION_FINE_POLICY_KEY,
        metadata={"trigger_violation_count": count},
    )


def create_user_feature_restriction(
    conn,
    *,
    user_id,
    feature_key,
    source_type,
    source_ref,
    reason,
    created_by,
    starts_at=None,
    expires_at=None,
    metadata=None,
):
    ensure_violation_fine_schema(conn)
    feature = normalize_feature_key(feature_key)
    if not feature:
        raise ValueError("unknown feature restriction")
    now = _now_text()
    starts = starts_at or now
    restriction_uuid = "pcrestrict:" + str(uuid.uuid4())
    conn.execute(
        """
        INSERT OR IGNORE INTO user_feature_restrictions (
            restriction_uuid, user_id, feature_key, status, source_type, source_ref, reason,
            starts_at, expires_at, created_by, created_at, metadata_json
        ) VALUES (?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            restriction_uuid,
            int(user_id),
            feature,
            str(source_type or "manual")[:80],
            str(source_ref or "")[:160],
            str(reason or "功能限制")[:1000],
            str(starts)[:80],
            str(expires_at or "")[:80] or None,
            str(created_by or "system")[:80],
            now,
            _json_dumps(metadata or {}),
        ),
    )
    row = conn.execute(
        """
        SELECT * FROM user_feature_restrictions
        WHERE user_id=? AND feature_key=? AND source_type=? AND source_ref=?
        """,
        (int(user_id), feature, str(source_type or "manual")[:80], str(source_ref or "")[:160]),
    ).fetchone()
    return serialize_feature_restriction(row)


def release_feature_restrictions_for_source(conn, *, user_id, source_type, source_ref, release_reason):
    ensure_violation_fine_schema(conn)
    now = _now_text()
    conn.execute(
        """
        UPDATE user_feature_restrictions
        SET status='released', released_at=?, release_reason=?
        WHERE user_id=? AND source_type=? AND source_ref=? AND status='active'
        """,
        (now, str(release_reason or "released")[:300], int(user_id), str(source_type or ""), str(source_ref or "")),
    )


def refresh_overdue_violation_fines(conn, *, user_id=None, now=None):
    ensure_violation_fine_schema(conn)
    now_dt = now or _now()
    params = [now_dt.isoformat()]
    where = "status='pending' AND due_at<=?"
    if user_id is not None:
        where += " AND user_id=?"
        params.append(int(user_id))
    rows = conn.execute(f"SELECT * FROM violation_fines WHERE {where}", tuple(params)).fetchall()
    changed = []
    for row in rows:
        fine = serialize_violation_fine(row)
        interest = _calculate_overdue_interest_points(row, now_dt)
        conn.execute(
            """
            UPDATE violation_fines
            SET status='overdue', overdue_interest_points=?, interest_updated_at=?, updated_at=?
            WHERE id=? AND status='pending'
            """,
            (interest, now_dt.isoformat(), _now_text(), row["id"]),
        )
        for feature in fine["restriction_features"]:
            create_user_feature_restriction(
                conn,
                user_id=row["user_id"],
                feature_key=feature,
                source_type="violation_fine",
                source_ref=row["fine_uuid"],
                reason=f"違規罰款逾期未繳：{row['reason']}",
                created_by="system",
                metadata={"fine_uuid": row["fine_uuid"], "due_at": row["due_at"]},
            )
        _notify_user(
            conn,
            user_id=row["user_id"],
            fine_uuid=row["fine_uuid"],
            title="違規罰款逾期",
            body=f"違規罰款 {row['amount_points']} 點已逾期，已限制指定功能；繳清或經管理員豁免後會解除。",
            severity="error",
        )
        changed.append(fine)
    interest_rows = conn.execute(
        "SELECT * FROM violation_fines WHERE status='overdue'" + (" AND user_id=?" if user_id is not None else ""),
        (int(user_id),) if user_id is not None else (),
    ).fetchall()
    for row in interest_rows:
        interest = _calculate_overdue_interest_points(row, now_dt)
        if interest != int(row["overdue_interest_points"] or 0):
            conn.execute(
                "UPDATE violation_fines SET overdue_interest_points=?, interest_updated_at=?, updated_at=? WHERE id=? AND status='overdue'",
                (interest, now_dt.isoformat(), _now_text(), row["id"]),
            )
    return changed


def list_violation_fines(conn, *, user_id=None, username=None, status=None, limit=50, offset=0):
    ensure_violation_fine_schema(conn)
    if user_id is not None:
        refresh_overdue_violation_fines(conn, user_id=int(user_id))
    else:
        refresh_overdue_violation_fines(conn)
    where = "WHERE 1=1"
    params = []
    if user_id is not None:
        where += " AND user_id=?"
        params.append(int(user_id))
    if username:
        where += " AND username=?"
        params.append(str(username))
    if status in {"pending", "overdue", "paid", "waived", "cancelled"}:
        where += " AND status=?"
        params.append(status)
    rows = conn.execute(
        f"SELECT * FROM violation_fines {where} ORDER BY id DESC LIMIT ? OFFSET ?",
        tuple(params + [max(1, min(int(limit or 50), 200)), max(0, int(offset or 0))]),
    ).fetchall()
    total = conn.execute(f"SELECT COUNT(*) AS c FROM violation_fines {where}", tuple(params)).fetchone()["c"]
    return [serialize_violation_fine(row) for row in rows], int(total or 0)


def active_feature_restrictions(conn, *, user_id, feature_key=None):
    ensure_violation_fine_schema(conn)
    refresh_overdue_violation_fines(conn, user_id=int(user_id))
    now = _now_text()
    conn.execute(
        """
        UPDATE user_feature_restrictions
        SET status='expired', released_at=?, release_reason='restriction expired'
        WHERE user_id=? AND status='active' AND expires_at IS NOT NULL AND expires_at<>'' AND expires_at<=?
        """,
        (now, int(user_id), now),
    )
    where = "WHERE user_id=? AND status='active'"
    params = [int(user_id)]
    feature = normalize_feature_key(feature_key)
    if feature:
        where += " AND feature_key=?"
        params.append(feature)
    rows = conn.execute(f"SELECT * FROM user_feature_restrictions {where} ORDER BY id DESC", tuple(params)).fetchall()
    return [serialize_feature_restriction(row) for row in rows]


def assert_user_feature_allowed(conn, *, user_id, feature_key):
    feature = normalize_feature_key(feature_key)
    if not feature:
        return True, "", []
    rows = active_feature_restrictions(conn, user_id=int(user_id), feature_key=feature)
    if not rows:
        return True, "", []
    labels = ", ".join(FEATURE_LABELS.get(row["feature_key"], row["feature_key"]) for row in rows)
    return False, f"功能已暫停：{labels}。原因是違規罰款逾期或管理限制，請到申覆 / 罰款中心處理。", rows


def mark_violation_fine_paid(
    conn,
    *,
    fine_uuid,
    payment_ledger_uuid,
    payment_charge_uuid,
    payment_source_wallet_address,
):
    ensure_violation_fine_schema(conn)
    row = conn.execute("SELECT * FROM violation_fines WHERE fine_uuid=?", (str(fine_uuid or ""),)).fetchone()
    if not row:
        raise ValueError("fine not found")
    if row["status"] not in {"pending", "overdue"}:
        raise ValueError("fine is not payable")
    now = _now_text()
    conn.execute(
        """
        UPDATE violation_fines
        SET status='paid', paid_at=?, updated_at=?, payment_ledger_uuid=?,
            payment_charge_uuid=?, payment_source_wallet_address=?
        WHERE fine_uuid=? AND status IN ('pending', 'overdue')
        """,
        (
            now,
            now,
            str(payment_ledger_uuid or "")[:120],
            str(payment_charge_uuid or "")[:120],
            str(payment_source_wallet_address or "")[:120],
            str(fine_uuid or ""),
        ),
    )
    release_feature_restrictions_for_source(
        conn,
        user_id=row["user_id"],
        source_type="violation_fine",
        source_ref=row["fine_uuid"],
        release_reason="violation fine paid",
    )
    _notify_user(
        conn,
        user_id=row["user_id"],
        fine_uuid=row["fine_uuid"],
        title="違規罰款已繳清",
        body="罰款已完成鏈上扣款，相關逾期功能限制已解除。",
        severity="success",
    )
    updated = conn.execute("SELECT * FROM violation_fines WHERE fine_uuid=?", (str(fine_uuid or ""),)).fetchone()
    return serialize_violation_fine(updated)


def waive_violation_fine(conn, *, fine_uuid, actor_username, reason):
    ensure_violation_fine_schema(conn)
    row = conn.execute("SELECT * FROM violation_fines WHERE fine_uuid=?", (str(fine_uuid or ""),)).fetchone()
    if not row:
        raise ValueError("fine not found")
    if row["status"] not in {"pending", "overdue"}:
        raise ValueError("fine is already closed")
    now = _now_text()
    metadata = _json_loads(row["metadata_json"], {})
    metadata["waive_reason"] = str(reason or "")[:500]
    metadata["waived_by"] = str(actor_username or "admin")[:80]
    conn.execute(
        "UPDATE violation_fines SET status='waived', waived_at=?, updated_at=?, metadata_json=? WHERE fine_uuid=?",
        (now, now, _json_dumps(metadata), str(fine_uuid or "")),
    )
    release_feature_restrictions_for_source(
        conn,
        user_id=row["user_id"],
        source_type="violation_fine",
        source_ref=row["fine_uuid"],
        release_reason=f"fine waived: {reason or '-'}",
    )
    _notify_user(
        conn,
        user_id=row["user_id"],
        fine_uuid=row["fine_uuid"],
        title="違規罰款已豁免",
        body=f"管理員已豁免罰款；原因：{reason or '-'}。相關功能限制已解除。",
        severity="success",
    )
    updated = conn.execute("SELECT * FROM violation_fines WHERE fine_uuid=?", (str(fine_uuid or ""),)).fetchone()
    return serialize_violation_fine(updated)


def serialize_violation_fine_appeal(row):
    if not row:
        return None
    return dict(row)


def submit_violation_fine_appeal(conn, *, fine_uuid, user_id, username, reason):
    ensure_violation_fine_schema(conn)
    fine = conn.execute(
        "SELECT * FROM violation_fines WHERE fine_uuid=? AND user_id=?",
        (str(fine_uuid or ""), int(user_id)),
    ).fetchone()
    if not fine:
        raise ValueError("fine not found")
    if fine["status"] not in {"pending", "overdue"}:
        raise ValueError("fine is already closed")
    clean_reason = str(reason or "").strip()
    if not clean_reason:
        raise ValueError("appeal reason required")
    if len(clean_reason) > 500:
        raise ValueError("appeal reason must be <= 500 chars")
    existing = conn.execute(
        "SELECT * FROM violation_fine_appeals WHERE fine_uuid=? AND user_id=?",
        (fine["fine_uuid"], int(user_id)),
    ).fetchone()
    if existing:
        if existing["status"] == "pending":
            raise ValueError("fine appeal already pending")
        return serialize_violation_fine_appeal(existing), False
    now = _now_text()
    cur = conn.execute(
        """
        INSERT INTO violation_fine_appeals (
            fine_uuid, user_id, username, reason, status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, 'pending', ?, ?)
        """,
        (fine["fine_uuid"], int(user_id), str(username or fine["username"])[:80], clean_reason[:500], now, now),
    )
    _notify_user(
        conn,
        user_id=user_id,
        fine_uuid=fine["fine_uuid"],
        title="罰單申覆已送出",
        body="罰單申覆已送出，等待管理員審核；審核前仍需注意到期限制。",
        severity="info",
    )
    row = conn.execute("SELECT * FROM violation_fine_appeals WHERE id=?", (cur.lastrowid,)).fetchone()
    return serialize_violation_fine_appeal(row), True


def list_violation_fine_appeals(conn, *, user_id=None, status=None, limit=50, offset=0):
    ensure_violation_fine_schema(conn)
    where = "WHERE 1=1"
    params = []
    if user_id is not None:
        where += " AND a.user_id=?"
        params.append(int(user_id))
    if status in {"pending", "approved", "rejected"}:
        where += " AND a.status=?"
        params.append(status)
    rows = conn.execute(
        f"""
        SELECT a.*, f.amount_points, f.status AS fine_status, f.due_at, f.reason AS fine_reason
        FROM violation_fine_appeals a
        LEFT JOIN violation_fines f ON f.fine_uuid=a.fine_uuid
        {where}
        ORDER BY a.id DESC LIMIT ? OFFSET ?
        """,
        tuple(params + [max(1, min(int(limit or 50), 200)), max(0, int(offset or 0))]),
    ).fetchall()
    total = conn.execute(
        f"SELECT COUNT(*) AS c FROM violation_fine_appeals a {where}",
        tuple(params),
    ).fetchone()["c"]
    return [serialize_violation_fine_appeal(row) for row in rows], int(total or 0)


def review_violation_fine_appeal(conn, *, appeal_id, actor_username, action, note):
    ensure_violation_fine_schema(conn)
    appeal = conn.execute("SELECT * FROM violation_fine_appeals WHERE id=?", (int(appeal_id),)).fetchone()
    if not appeal:
        raise ValueError("fine appeal not found")
    if appeal["status"] != "pending":
        raise ValueError("fine appeal already reviewed")
    action = str(action or "").strip().lower()
    if action not in {"approve", "reject"}:
        raise ValueError("action must be approve or reject")
    status = "approved" if action == "approve" else "rejected"
    now = _now_text()
    conn.execute(
        """
        UPDATE violation_fine_appeals
        SET status=?, reviewed_by=?, reviewed_at=?, review_note=?, updated_at=?
        WHERE id=? AND status='pending'
        """,
        (status, str(actor_username or "admin")[:80], now, str(note or "")[:500], now, int(appeal_id)),
    )
    fine = None
    if status == "approved":
        fine = waive_violation_fine(
            conn,
            fine_uuid=appeal["fine_uuid"],
            actor_username=actor_username,
            reason=f"罰單申覆核准：{note or appeal['reason']}",
        )
    else:
        _notify_user(
            conn,
            user_id=appeal["user_id"],
            fine_uuid=appeal["fine_uuid"],
            title="罰單申覆未通過",
            body=f"管理員維持罰單；備註：{note or '-'}",
            severity="warning",
        )
    updated = conn.execute("SELECT * FROM violation_fine_appeals WHERE id=?", (int(appeal_id),)).fetchone()
    return serialize_violation_fine_appeal(updated), fine
