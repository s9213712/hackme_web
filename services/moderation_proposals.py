import json
from datetime import datetime, timedelta

ACTION_TYPES = {
    "warn",
    "mute",
    "restrict",
    "suspend",
    "delete",
    "downgrade_level",
    "force_password_reset",
}
PROPOSAL_STATUSES = {"pending", "approved", "rejected", "expired", "cancelled", "executed"}
VOTES = {"approve", "reject"}


def ensure_moderation_proposals_schema(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS moderation_proposals (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            target_user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            action_type         TEXT NOT NULL,
            action_value        TEXT,
            proposed_by_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            reason              TEXT NOT NULL,
            status              TEXT NOT NULL DEFAULT 'pending',
            required_votes      INTEGER NOT NULL DEFAULT 2,
            approve_count       INTEGER NOT NULL DEFAULT 0,
            reject_count        INTEGER NOT NULL DEFAULT 0,
            expires_at          TEXT NOT NULL,
            executed_at         TEXT,
            created_at          TEXT NOT NULL,
            updated_at          TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS moderation_votes (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            proposal_id    INTEGER NOT NULL REFERENCES moderation_proposals(id) ON DELETE CASCADE,
            voter_user_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            vote           TEXT NOT NULL,
            comment        TEXT,
            created_at     TEXT NOT NULL,
            UNIQUE(proposal_id, voter_user_id)
        )
        """
    )
    proposal_cols = {row["name"] for row in conn.execute("PRAGMA table_info(moderation_proposals)").fetchall()}
    if "action_value" not in proposal_cols:
        conn.execute("ALTER TABLE moderation_proposals ADD COLUMN action_value TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_moderation_proposals_status ON moderation_proposals(status, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_moderation_proposals_target ON moderation_proposals(target_user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_moderation_votes_proposal ON moderation_votes(proposal_id)")


def proposal_row_to_dict(row):
    if not row:
        return None
    data = dict(row)
    for key in ("required_votes", "approve_count", "reject_count"):
        data[key] = int(data.get(key) or 0)
    return data


def validate_action_payload(action_type, action_value):
    if action_type not in ACTION_TYPES:
        return False, "不支援的提案動作"
    if action_type == "downgrade_level" and action_value not in {"newbie", "normal", "restricted", "suspended"}:
        return False, "downgrade_level 需指定 newbie/normal/restricted/suspended"
    return True, ""


def create_moderation_proposal(conn, *, target_user_id, action_type, action_value, proposed_by_user_id, reason, required_votes=2, ttl_hours=72):
    ensure_moderation_proposals_schema(conn)
    ok, msg = validate_action_payload(action_type, action_value)
    if not ok:
        return None, msg
    try:
        required_votes = max(1, int(required_votes))
    except Exception:
        return None, "required_votes 格式錯誤"
    reason = (reason or "").strip()
    if not reason:
        return None, "提案原因不可為空"
    now = datetime.now()
    expires_at = (now + timedelta(hours=max(1, int(ttl_hours or 72)))).isoformat()
    cur = conn.execute(
        "INSERT INTO moderation_proposals "
        "(target_user_id, action_type, action_value, proposed_by_user_id, reason, status, required_votes, "
        "approve_count, reject_count, expires_at, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, 'pending', ?, 0, 0, ?, ?, ?)",
        (
            int(target_user_id),
            action_type,
            action_value,
            int(proposed_by_user_id),
            reason[:1000],
            required_votes,
            expires_at,
            now.isoformat(),
            now.isoformat(),
        ),
    )
    row = conn.execute("SELECT * FROM moderation_proposals WHERE id=?", (cur.lastrowid,)).fetchone()
    return proposal_row_to_dict(row), None


def refresh_proposal_vote_counts(conn, proposal_id):
    counts = conn.execute(
        "SELECT "
        "SUM(CASE WHEN vote='approve' THEN 1 ELSE 0 END) AS approve_count, "
        "SUM(CASE WHEN vote='reject' THEN 1 ELSE 0 END) AS reject_count "
        "FROM moderation_votes WHERE proposal_id=?",
        (proposal_id,),
    ).fetchone()
    approve_count = int(counts["approve_count"] or 0)
    reject_count = int(counts["reject_count"] or 0)
    proposal = conn.execute("SELECT * FROM moderation_proposals WHERE id=?", (proposal_id,)).fetchone()
    if not proposal:
        return None
    status = proposal["status"]
    now = datetime.now()
    if status == "pending" and proposal["expires_at"] <= now.isoformat():
        status = "expired"
    elif status == "pending" and approve_count >= int(proposal["required_votes"]):
        status = "approved"
    elif status == "pending" and reject_count >= int(proposal["required_votes"]):
        status = "rejected"
    conn.execute(
        "UPDATE moderation_proposals SET approve_count=?, reject_count=?, status=?, updated_at=? WHERE id=?",
        (approve_count, reject_count, status, now.isoformat(), proposal_id),
    )
    row = conn.execute("SELECT * FROM moderation_proposals WHERE id=?", (proposal_id,)).fetchone()
    return proposal_row_to_dict(row)


def cast_action_value(value):
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value).strip() or None
