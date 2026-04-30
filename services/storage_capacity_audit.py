import shutil
from pathlib import Path

from services.member_levels import get_member_level_rule
from services.upload_security import get_user_cloud_drive_usage


STORAGE_CAPACITY_SAFETY_RATIO = 0.9
STORAGE_CAPACITY_WARNING_RATIO = 0.8


def _table_exists(conn, table_name):
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    return bool(row)


def storage_disk_usage(storage_root):
    path = Path(storage_root or ".").expanduser()
    probe = path
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    usage = shutil.disk_usage(str(probe))
    return {
        "path": str(path),
        "probe_path": str(probe),
        "total_bytes": int(usage.total),
        "used_bytes": int(usage.used),
        "free_bytes": int(usage.free),
        "safe_free_bytes": int(usage.free * STORAGE_CAPACITY_SAFETY_RATIO),
        "safety_ratio": STORAGE_CAPACITY_SAFETY_RATIO,
        "warning_ratio": STORAGE_CAPACITY_WARNING_RATIO,
    }


def _cloud_used_bytes(conn):
    if not _table_exists(conn, "uploaded_files"):
        return 0
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(uploaded_files)").fetchall()}
    if "size_bytes" not in cols:
        return 0
    row = conn.execute(
        "SELECT COALESCE(SUM(size_bytes), 0) AS bytes FROM uploaded_files WHERE deleted_at IS NULL"
    ).fetchone()
    return int(row["bytes"] if row and row["bytes"] is not None else 0)


def audit_storage_capacity(conn, storage_root):
    disk = storage_disk_usage(storage_root)
    cloud_used = _cloud_used_bytes(conn)
    allocatable = int(cloud_used + disk["safe_free_bytes"])

    users = []
    committed_total = 0
    committed_remaining = 0
    unbounded_users = []
    if _table_exists(conn, "users"):
        rows = conn.execute("SELECT * FROM users ORDER BY id ASC").fetchall()
        for row in rows:
            data = dict(row)
            if data.get("username") == "root":
                continue
            level = data.get("effective_level") or data.get("member_level") or data.get("base_level") or "normal"
            rule = get_member_level_rule(conn, level)
            usage = get_user_cloud_drive_usage(conn, data, member_rule=rule, storage_root=storage_root)
            total = usage.get("total_bytes")
            remaining = usage.get("remaining_bytes")
            user_entry = {
                "user_id": int(data.get("id") or 0),
                "username": data.get("username") or "",
                "role": data.get("role") or "user",
                "quota_source": usage.get("quota_source"),
                "total_bytes": total,
                "used_bytes": int(usage.get("used_bytes") or 0),
                "remaining_bytes": remaining,
            }
            users.append(user_entry)
            if total is None:
                unbounded_users.append(user_entry)
                continue
            committed_total += int(total or 0)
            committed_remaining += int(remaining or 0)

    total_over_by = max(0, committed_total - allocatable)
    remaining_over_by = max(0, committed_remaining - disk["safe_free_bytes"])
    percent_committed = 0.0
    if allocatable > 0:
        percent_committed = round((committed_total / allocatable) * 100, 2)
    elif committed_total > 0:
        percent_committed = 100.0

    status = "ok"
    reasons = []
    if unbounded_users:
        status = "critical"
        reasons.append("non_root_unbounded_quota")
    if total_over_by > 0 or remaining_over_by > 0:
        status = "critical"
        reasons.append("host_storage_overcommitted")
    elif percent_committed >= STORAGE_CAPACITY_WARNING_RATIO * 100:
        status = "warning"
        reasons.append("host_storage_near_capacity")

    return {
        "ok": status == "ok",
        "status": status,
        "reasons": reasons,
        "disk": disk,
        "cloud_used_bytes": cloud_used,
        "allocatable_cloud_capacity_bytes": allocatable,
        "committed_total_bytes": int(committed_total),
        "committed_remaining_bytes": int(committed_remaining),
        "total_overcommitted_by_bytes": int(total_over_by),
        "remaining_overcommitted_by_bytes": int(remaining_over_by),
        "percent_committed": percent_committed,
        "user_count": len(users),
        "unbounded_users": unbounded_users,
        "users": users,
    }


def can_allocate_storage_bytes(conn, storage_root, additional_bytes):
    additional = max(0, int(additional_bytes or 0))
    audit = audit_storage_capacity(conn, storage_root)
    projected_total = int(audit["committed_total_bytes"]) + additional
    projected_remaining = int(audit["committed_remaining_bytes"]) + additional
    total_over_by = max(0, projected_total - int(audit["allocatable_cloud_capacity_bytes"]))
    remaining_over_by = max(0, projected_remaining - int(audit["disk"]["safe_free_bytes"]))
    allowed = (
        not audit.get("unbounded_users")
        and total_over_by == 0
        and remaining_over_by == 0
    )
    projected = {
        **audit,
        "projected_committed_total_bytes": projected_total,
        "projected_committed_remaining_bytes": projected_remaining,
        "projected_total_overcommitted_by_bytes": total_over_by,
        "projected_remaining_overcommitted_by_bytes": remaining_over_by,
    }
    if allowed:
        return True, "", projected
    return False, "Host 磁碟可承諾容量不足，不能再增加會員雲端硬碟配額", projected
