import hashlib
import json
import os
import re
import secrets
import shutil
import sqlite3
import tarfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from services.bootstrap import CURRENT_SCHEMA_VERSION
from services.release_info import APP_RELEASE_ID
from services.settings import MANAGEMENT_ONLY_RESET_SETTINGS

SNAPSHOT_ID_RE = re.compile(r"^snap_\d{8}_\d{6}_[a-f0-9]{6}$")
SNAPSHOT_TYPES = {"manual", "before_superweak", "scheduled", "pre_restore", "pre_reset", "pre_migration", "emergency"}
RESTORE_MODES = {"full", "db_only", "files_only", "config_only", "dry_run"}
SERVER_MODES = {"production", "preprod", "internal_test", "test", "superweak"}
PORTABLE_SNAPSHOT_FILES = ("metadata.json", "checksums.sha256", "db.sqlite3.backup", "uploads.tar.gz", "config.tar.gz", "manifest.json")
DEFAULT_ACCOUNT_NAMES = ("root", "admin", "test")
TEST_ACCOUNT_NAMES = ("test",)
BUILTIN_SECURITY_PROFILES = {
    "production": {
        "label": "production（上線）",
        "description": "正式上線設定檔：安全機制全開、停用測試帳戶，並要求預設帳戶重新設定強密碼。",
        "settings": {
            "maintenance_mode": False,
            "allow_register": False,
            "server_ssl_enabled": True,
            "audit_chain_enabled": True,
            "ip_blocking_enabled": True,
            "login_violation_enabled": True,
            "rate_limit_violation_enabled": True,
            "root_ip_whitelist_enabled": False,
            "root_ip_whitelist": "",
            "browser_only_mode_enabled": True,
            "integrity_guard_enabled": True,
            "integrity_guard_strict_mode": True,
            "feature_account_security_enabled": True,
            "feature_advanced_security_enabled": True,
            "feature_identity_governance_enabled": True,
            "feature_member_governance_enabled": True,
            "feature_server_modes_enabled": True,
            "feature_snapshot_restore_enabled": True,
            "feature_audit_log_enabled": True,
            "feature_economy_enabled": True,
            "feature_violation_center_enabled": True,
            "feature_health_center_enabled": True,
            "captcha_mode": "math",
        },
        "thresholds": {
            "security_pending_chat_reports_threshold": 5,
            "security_pending_appeals_threshold": 5,
            "security_pending_moderation_proposals_threshold": 5,
            "security_quarantined_files_threshold": 0,
            "security_unknown_encrypted_files_threshold": 0,
        },
    },
    "preprod": {
        "label": "preprod（準上線）",
        "description": "接近正式部署的安全設定檔，要求完整性檢查通過。",
        "settings": {
            "maintenance_mode": False,
            "server_ssl_enabled": True,
            "audit_chain_enabled": True,
            "ip_blocking_enabled": True,
            "login_violation_enabled": True,
            "rate_limit_violation_enabled": True,
            "root_ip_whitelist_enabled": False,
            "root_ip_whitelist": "",
            "browser_only_mode_enabled": True,
            "integrity_guard_enabled": True,
            "integrity_guard_strict_mode": True,
            "feature_audit_log_enabled": True,
            "feature_economy_enabled": True,
        },
        "thresholds": {
            "security_pending_chat_reports_threshold": 10,
            "security_pending_appeals_threshold": 10,
            "security_pending_moderation_proposals_threshold": 10,
            "security_quarantined_files_threshold": 0,
            "security_unknown_encrypted_files_threshold": 50,
        },
    },
    "internal_test": {
        "label": "internal test（內測）",
        "description": "內測模式：只有 root 可直接登入；其他帳號必須提供 root 發出的內測登入 token。",
        "settings": {
            "maintenance_mode": False,
            "allow_register": False,
            "server_ssl_enabled": True,
            "audit_chain_enabled": True,
            "ip_blocking_enabled": True,
            "login_violation_enabled": True,
            "rate_limit_violation_enabled": True,
            "root_ip_whitelist_enabled": False,
            "root_ip_whitelist": "",
            "browser_only_mode_enabled": True,
            "integrity_guard_enabled": True,
            "integrity_guard_strict_mode": True,
            "feature_account_security_enabled": True,
            "feature_server_modes_enabled": True,
            "feature_audit_log_enabled": True,
            "feature_economy_enabled": True,
        },
        "thresholds": {
            "security_pending_chat_reports_threshold": 10,
            "security_pending_appeals_threshold": 10,
            "security_pending_moderation_proposals_threshold": 10,
            "security_quarantined_files_threshold": 0,
            "security_unknown_encrypted_files_threshold": 25,
        },
    },
    "test": {
        "label": "test（測試）",
        "description": "一般測試設定檔，保留主要安全紀錄但降低啟動阻擋。",
        "settings": {
            "maintenance_mode": False,
            "server_ssl_enabled": True,
            "audit_chain_enabled": True,
            "ip_blocking_enabled": True,
            "login_violation_enabled": True,
            "rate_limit_violation_enabled": True,
            "root_ip_whitelist_enabled": False,
            "root_ip_whitelist": "",
            "browser_only_mode_enabled": False,
            "integrity_guard_enabled": True,
            "integrity_guard_strict_mode": False,
            "feature_audit_log_enabled": True,
            "feature_economy_enabled": True,
        },
        "thresholds": {
            "security_pending_chat_reports_threshold": 20,
            "security_pending_appeals_threshold": 20,
            "security_pending_moderation_proposals_threshold": 20,
            "security_quarantined_files_threshold": 0,
            "security_unknown_encrypted_files_threshold": 100,
        },
    },
    "superweak": {
        "label": "superweak（弱化測試）",
        "description": "高風險弱化測試模式，進入前會建立 before_superweak snapshot，並關閉主要安全機制。",
        "settings": {
            "maintenance_mode": False,
            "server_ssl_enabled": False,
            "audit_chain_enabled": False,
            "ip_blocking_enabled": False,
            "login_violation_enabled": False,
            "rate_limit_violation_enabled": False,
            "root_ip_whitelist_enabled": False,
            "root_ip_whitelist": "",
            "browser_only_mode_enabled": False,
            "integrity_guard_enabled": False,
            "integrity_guard_strict_mode": False,
            "feature_audit_log_enabled": False,
            "feature_economy_enabled": False,
            "captcha_mode": "none",
        },
        "thresholds": {
            "security_pending_chat_reports_threshold": 50,
            "security_pending_appeals_threshold": 50,
            "security_pending_moderation_proposals_threshold": 50,
            "security_quarantined_files_threshold": 10,
            "security_unknown_encrypted_files_threshold": 250,
        },
    },
}
PROFILE_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{1,31}$")
RESETTABLE_TABLES = {
    "appeals",
    "chat_message_reports",
    "chat_messages",
    "comments",
    "direct_messages",
    "dm_threads",
    "encrypted_file_keys",
    "file_access_logs",
    "file_scan_results",
    "cloud_file_refs",
    "file_access_grants",
    "forum_boards",
    "forum_categories",
    "forum_post_reactions",
    "forum_thread_reactions",
    "forum_posts",
    "forum_threads",
    "announcements",
    "announcement_attachment_requests",
    "album_files",
    "albums",
    "messages",
    "moderation_proposals",
    "moderation_votes",
    "notifications",
    "posts",
    "reports",
    "storage_folders",
    "storage_files",
    "storage_quota_log",
    "storage_share_links",
    "trading_audit_events",
    "trading_fills",
    "trading_futures_positions",
    "trading_margin_positions",
    "trading_markets",
    "trading_orders",
    "trading_pending_profit",
    "trading_reserve_pool",
    "trading_reserve_pool_events",
    "trading_state",
    "trading_spot_realized_pnl",
    "trading_spot_positions",
    "uploaded_files",
    "user_storage",
    "user_mod_notes",
    "violations",
}


@dataclass
class SnapshotResult:
    ok: bool
    snapshot_id: str = ""
    status: str = ""
    error: str = ""
    metadata: dict | None = None


def ensure_snapshot_schema(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS snapshots (
            id                  TEXT PRIMARY KEY,
            type                TEXT NOT NULL,
            status              TEXT NOT NULL,
            created_by          INTEGER NOT NULL,
            created_at          TEXT NOT NULL,
            completed_at        TEXT,
            app_version         TEXT,
            schema_version      TEXT,
            source_mode         TEXT,
            includes_json       TEXT NOT NULL,
            storage_path        TEXT NOT NULL,
            db_dump_path        TEXT,
            files_archive_path  TEXT,
            config_archive_path TEXT,
            checksum            TEXT,
            size_bytes          INTEGER,
            notes               TEXT,
            error_message       TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS snapshot_restore_events (
            id                      TEXT PRIMARY KEY,
            snapshot_id             TEXT NOT NULL,
            restored_by             INTEGER NOT NULL,
            started_at              TEXT NOT NULL,
            completed_at            TEXT,
            status                  TEXT NOT NULL,
            restore_mode            TEXT NOT NULL,
            pre_restore_snapshot_id TEXT,
            checksum_verified       INTEGER NOT NULL DEFAULT 0,
            dry_run                 INTEGER NOT NULL DEFAULT 0,
            error_message           TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS server_modes (
            id                 INTEGER PRIMARY KEY CHECK (id = 1),
            current_mode       TEXT NOT NULL,
            previous_mode      TEXT,
            active_snapshot_id TEXT,
            mode_changed_by    INTEGER,
            mode_changed_at    TEXT,
            notes              TEXT
        )
        """
    )
    conn.execute(
        "INSERT OR IGNORE INTO server_modes "
        "(id, current_mode, previous_mode, active_snapshot_id, mode_changed_by, mode_changed_at, notes) "
        "VALUES (1, 'test', NULL, NULL, NULL, ?, '')",
        (datetime.now().isoformat(),),
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS security_profiles (
            name            TEXT PRIMARY KEY,
            label           TEXT NOT NULL,
            description     TEXT NOT NULL DEFAULT '',
            settings_json   TEXT NOT NULL DEFAULT '{}',
            thresholds_json TEXT NOT NULL DEFAULT '{}',
            is_builtin      INTEGER NOT NULL DEFAULT 0,
            created_by      INTEGER,
            updated_by      INTEGER,
            created_at      TEXT NOT NULL,
            updated_at      TEXT NOT NULL
        )
        """
    )
    now = datetime.now().isoformat()
    for name, profile in BUILTIN_SECURITY_PROFILES.items():
        conn.execute(
            """
            INSERT OR IGNORE INTO security_profiles
            (name, label, description, settings_json, thresholds_json, is_builtin, created_by, updated_by, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 1, NULL, NULL, ?, ?)
            """,
            (
                name,
                profile["label"],
                profile["description"],
                json.dumps(profile["settings"], ensure_ascii=False, sort_keys=True),
                json.dumps(profile["thresholds"], ensure_ascii=False, sort_keys=True),
                now,
                now,
            ),
        )
        conn.execute(
            """
            UPDATE security_profiles
            SET label=?,
                description=?,
                settings_json=?,
                thresholds_json=?,
                is_builtin=1,
                updated_at=?
            WHERE name=? AND is_builtin=1
            """,
            (
                profile["label"],
                profile["description"],
                json.dumps(profile["settings"], ensure_ascii=False, sort_keys=True),
                json.dumps(profile["thresholds"], ensure_ascii=False, sort_keys=True),
                now,
                name,
            ),
        )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_type_status ON snapshots(type, status, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_snapshot_restore_events_snapshot ON snapshot_restore_events(snapshot_id)")


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _safe_snapshot_id(snapshot_id):
    return isinstance(snapshot_id, str) and SNAPSHOT_ID_RE.fullmatch(snapshot_id) is not None


def _safe_relative_tarinfo(tarinfo):
    name = tarinfo.name
    if not name or name.startswith("/") or ".." in Path(name).parts:
        return False
    if tarinfo.issym() or tarinfo.islnk() or tarinfo.isdev():
        return False
    return True


def _safe_extract_tar(archive_path, target_dir):
    target = Path(target_dir).resolve()
    with tarfile.open(archive_path, "r:gz") as tar:
        for member in tar.getmembers():
            if not _safe_relative_tarinfo(member):
                raise ValueError(f"unsafe archive member: {member.name}")
            final = (target / member.name).resolve()
            if target not in final.parents and final != target:
                raise ValueError(f"archive member escapes target: {member.name}")
        tar.extractall(target)


def _parse_daily_snapshot_time(value):
    text = str(value or "03:00").strip()
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", text)
    if not match:
        return 3, 0, "03:00"
    hour = int(match.group(1))
    minute = int(match.group(2))
    if hour > 23 or minute > 59:
        return 3, 0, "03:00"
    return hour, minute, f"{hour:02d}:{minute:02d}"


class SnapshotService:
    def __init__(
        self,
        *,
        get_db,
        db_path,
        base_dir,
        storage_root,
        audit,
        file_roots=None,
        config_files=None,
        runtime_secret_files=None,
        reset_points_chain=None,
        reset_audit_chain=None,
        post_restore_validators=None,
    ):
        self.get_db = get_db
        self.db_path = Path(db_path)
        self.base_dir = Path(base_dir)
        self.storage_root = Path(storage_root)
        self.snapshots_root = self.storage_root / "snapshots"
        self.imports_root = self.snapshots_root / ".imports"
        self.audit = audit
        self.reset_points_chain = reset_points_chain
        self.reset_audit_chain = reset_audit_chain
        self.post_restore_validators = list(post_restore_validators or [])
        self.file_roots = [Path(p) for p in (file_roots or []) if p]
        self.config_files = [Path(p) for p in (config_files or []) if p]
        self.runtime_secret_files = [Path(p) for p in (runtime_secret_files or []) if p]

    def set_post_restore_validators(self, validators):
        self.post_restore_validators = list(validators or [])

    def _run_post_restore_validators(self):
        results = []
        errors = []
        for name, validator in self.post_restore_validators:
            try:
                result = validator()
            except Exception as exc:
                result = {"ok": False, "error": str(exc)}
            if not isinstance(result, dict):
                result = {"ok": bool(result), "result": result}
            item = {"name": name, **result}
            results.append(item)
            if item.get("ok") is not True:
                errors.append(item)
        return {"ok": not errors, "results": results, "errors": errors}

    def ensure_schema(self, conn):
        ensure_snapshot_schema(conn)

    def _snapshot_id(self):
        return f"snap_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(3)}"

    def _snapshot_dir(self, snapshot_id):
        if not _safe_snapshot_id(snapshot_id):
            raise ValueError("snapshot_id 格式錯誤")
        root = self.snapshots_root.resolve()
        path = (root / snapshot_id).resolve()
        if root not in path.parents:
            raise ValueError("snapshot path traversal blocked")
        return path

    def _portable_archive_path(self, snapshot_id):
        return self._snapshot_dir(snapshot_id) / f"{snapshot_id}.snapshot.tar.gz"

    def _local_snapshot_record(self, snapshot_id, *, actor_id=0, notes=None):
        snapshot_dir = self._snapshot_dir(snapshot_id)
        metadata_path = snapshot_dir / "metadata.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {}
        size_bytes = sum(p.stat().st_size for p in snapshot_dir.rglob("*") if p.is_file())
        snapshot_type = metadata.get("type") if metadata.get("type") in SNAPSHOT_TYPES else "manual"
        includes = metadata.get("includes") if isinstance(metadata.get("includes"), dict) else {"database": True, "uploads": True, "config": True}
        now = datetime.now().isoformat()
        return {
            "id": snapshot_id,
            "type": snapshot_type,
            "status": "ready",
            "created_by": int(actor_id or 0),
            "created_at": metadata.get("created_at") or now,
            "completed_at": now,
            "app_version": metadata.get("app_version") or "",
            "schema_version": str(metadata.get("schema_version") or ""),
            "source_mode": metadata.get("source_mode") or "imported",
            "includes_json": json.dumps(includes, ensure_ascii=False, sort_keys=True),
            "storage_path": str(snapshot_dir),
            "db_dump_path": str(snapshot_dir / "db.sqlite3.backup"),
            "files_archive_path": str(snapshot_dir / "uploads.tar.gz"),
            "config_archive_path": str(snapshot_dir / "config.tar.gz"),
            "checksum": metadata.get("checksum") or "",
            "size_bytes": size_bytes,
            "notes": notes if notes is not None else metadata.get("notes", ""),
        }

    def _upsert_local_snapshot_record(self, conn, snapshot_id, *, actor_id=0, notes=None):
        self.ensure_schema(conn)
        record = self._local_snapshot_record(snapshot_id, actor_id=actor_id, notes=notes)
        current = conn.execute("SELECT id FROM snapshots WHERE id=?", (snapshot_id,)).fetchone()
        if current:
            conn.execute(
                "UPDATE snapshots SET status=?, storage_path=?, db_dump_path=?, files_archive_path=?, "
                "config_archive_path=?, checksum=?, size_bytes=?, completed_at=? WHERE id=?",
                (
                    record["status"],
                    record["storage_path"],
                    record["db_dump_path"],
                    record["files_archive_path"],
                    record["config_archive_path"],
                    record["checksum"],
                    record["size_bytes"],
                    record["completed_at"],
                    snapshot_id,
                ),
            )
            return record
        conn.execute(
            "INSERT INTO snapshots "
            "(id, type, status, created_by, created_at, completed_at, app_version, schema_version, source_mode, "
            "includes_json, storage_path, db_dump_path, files_archive_path, config_archive_path, checksum, size_bytes, notes) "
            "VALUES (:id, :type, :status, :created_by, :created_at, :completed_at, :app_version, :schema_version, "
            ":source_mode, :includes_json, :storage_path, :db_dump_path, :files_archive_path, :config_archive_path, "
            ":checksum, :size_bytes, :notes)",
            record,
        )
        return record

    def _current_mode(self, conn):
        self.ensure_schema(conn)
        row = conn.execute("SELECT current_mode FROM server_modes WHERE id=1").fetchone()
        return row["current_mode"] if row else "test"

    def _actor_id(self, actor):
        return int(dict(actor or {}).get("id") or 0)

    def _actor_name(self, actor):
        return dict(actor or {}).get("username") or "system"

    def _write_db_backup(self, dest):
        src = sqlite3.connect(str(self.db_path))
        dst = sqlite3.connect(str(dest))
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()

    def _iter_files(self):
        snapshot_root = self.snapshots_root.resolve()
        for root in self.file_roots:
            if not root.exists() or not root.is_dir():
                continue
            root_resolved = root.resolve()
            if snapshot_root == root_resolved or snapshot_root in root_resolved.parents:
                continue
            for path in root_resolved.rglob("*"):
                if path.is_file() and not path.is_symlink() and "__pycache__" not in path.parts:
                    rel = path.relative_to(self.base_dir.resolve()) if self.base_dir.resolve() in path.resolve().parents else Path(root.name) / path.relative_to(root_resolved)
                    yield path, rel

    def _write_files_archive(self, archive_path):
        manifest = {"files": []}
        with tarfile.open(archive_path, "w:gz") as tar:
            for path, rel in self._iter_files():
                rel_text = str(rel)
                tar.add(path, arcname=rel_text)
                manifest["files"].append({"path": rel_text, "size": path.stat().st_size, "sha256": _sha256_file(path)})
        return manifest

    def _write_config_archive(self, archive_path):
        with tarfile.open(archive_path, "w:gz") as tar:
            for cfg in self.config_files:
                if not cfg.exists() or not cfg.is_file():
                    continue
                if cfg.name == ".env":
                    redacted = cfg.parent / ".env.snapshot.redacted"
                    with open(cfg, "r", encoding="utf-8", errors="ignore") as src, open(redacted, "w", encoding="utf-8") as out:
                        for line in src:
                            key = line.split("=", 1)[0].strip()
                            if key and not key.startswith("#"):
                                out.write(f"{key}=<redacted>\n")
                    tar.add(redacted, arcname=".env.snapshot.redacted")
                    try:
                        redacted.unlink()
                    except Exception:
                        pass
                    continue
                arcname = str(cfg.relative_to(self.base_dir)) if self.base_dir in cfg.resolve().parents else cfg.name
                tar.add(cfg, arcname=arcname)

    def create_snapshot(self, *, snapshot_type, actor, notes=None):
        if snapshot_type not in SNAPSHOT_TYPES:
            return SnapshotResult(False, error="snapshot type 錯誤")
        actor_id = self._actor_id(actor)
        actor_name = self._actor_name(actor)
        snapshot_id = self._snapshot_id()
        snapshot_dir = self._snapshot_dir(snapshot_id)
        created_at = datetime.now().isoformat()
        includes = {"database": True, "uploads": True, "config": True, "audit_checkpoint": True}
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            source_mode = self._current_mode(conn)
            snapshot_dir.mkdir(parents=True, exist_ok=False)
            conn.execute(
                "INSERT INTO snapshots "
                "(id, type, status, created_by, created_at, app_version, schema_version, source_mode, includes_json, storage_path, notes) "
                "VALUES (?, ?, 'creating', ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    snapshot_id,
                    snapshot_type,
                    actor_id,
                    created_at,
                    APP_RELEASE_ID,
                    str(CURRENT_SCHEMA_VERSION),
                    source_mode,
                    json.dumps(includes, sort_keys=True),
                    str(snapshot_dir),
                    notes or "",
                ),
            )
            conn.commit()
            self.audit("SNAPSHOT_CREATE_STARTED", "-", user=actor_name, success=True, detail=f"snapshot_id={snapshot_id},type={snapshot_type}")

            db_dump = snapshot_dir / "db.sqlite3.backup"
            files_archive = snapshot_dir / "uploads.tar.gz"
            config_archive = snapshot_dir / "config.tar.gz"
            manifest_path = snapshot_dir / "manifest.json"
            checksums_path = snapshot_dir / "checksums.sha256"
            metadata_path = snapshot_dir / "metadata.json"

            self._write_db_backup(db_dump)
            manifest = self._write_files_archive(files_archive)
            self._write_config_archive(config_archive)
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

            checksums = {}
            for path in (db_dump, files_archive, config_archive, manifest_path):
                checksums[path.name] = _sha256_file(path)
            checksums_text = "".join(f"{digest}  {name}\n" for name, digest in sorted(checksums.items()))
            checksums_path.write_text(checksums_text, encoding="utf-8")
            overall_checksum = hashlib.sha256(checksums_text.encode("utf-8")).hexdigest()
            metadata = {
                "snapshot_id": snapshot_id,
                "type": snapshot_type,
                "created_by": actor_name,
                "created_at": created_at,
                "app_version": APP_RELEASE_ID,
                "schema_version": str(CURRENT_SCHEMA_VERSION),
                "source_mode": source_mode,
                "includes": includes,
                "secrets_excluded": True,
                "checksum_algorithm": "sha256",
                "checksum": overall_checksum,
                "notes": notes or "",
            }
            metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
            size_bytes = sum(p.stat().st_size for p in snapshot_dir.rglob("*") if p.is_file())
            conn.execute(
                "UPDATE snapshots SET status='ready', completed_at=?, db_dump_path=?, files_archive_path=?, "
                "config_archive_path=?, checksum=?, size_bytes=? WHERE id=?",
                (datetime.now().isoformat(), str(db_dump), str(files_archive), str(config_archive), overall_checksum, size_bytes, snapshot_id),
            )
            conn.commit()
            self.audit("SNAPSHOT_CREATE_READY", "-", user=actor_name, success=True, detail=f"snapshot_id={snapshot_id},size={size_bytes}")
            return SnapshotResult(True, snapshot_id=snapshot_id, status="ready", metadata=metadata)
        except Exception as exc:
            try:
                if snapshot_dir.exists():
                    shutil.rmtree(snapshot_dir)
                conn.execute("UPDATE snapshots SET status='failed', error_message=? WHERE id=?", (str(exc), snapshot_id))
                conn.commit()
            except Exception:
                pass
            self.audit("SNAPSHOT_CREATE_FAILED", "-", user=actor_name, success=False, detail=f"snapshot_id={snapshot_id},error={exc}")
            return SnapshotResult(False, snapshot_id=snapshot_id, status="failed", error=str(exc))
        finally:
            conn.close()

    def list_snapshots(self, *, actor):
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            rows = conn.execute(
                "SELECT s.id, s.type, s.status, s.created_at, u.username AS created_by, s.size_bytes, s.source_mode, s.notes, s.checksum "
                "FROM snapshots s LEFT JOIN users u ON u.id=s.created_by ORDER BY s.created_at DESC LIMIT 100"
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def get_snapshot(self, *, snapshot_id, actor=None):
        path = self._snapshot_dir(snapshot_id)
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            row = conn.execute("SELECT * FROM snapshots WHERE id=?", (snapshot_id,)).fetchone()
            if not row:
                return None
            data = dict(row)
            metadata_path = path / "metadata.json"
            data["metadata"] = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else None
            return data
        finally:
            conn.close()

    def _verify_snapshot_dir(self, path):
        path = Path(path)
        metadata_path = path / "metadata.json"
        checksums_path = path / "checksums.sha256"
        required = [path / name for name in PORTABLE_SNAPSHOT_FILES]
        missing = [p.name for p in required if not p.exists()]
        if missing:
            return {"ok": False, "msg": "snapshot 檔案缺失", "missing": missing}
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        checksums = {}
        for line in checksums_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            digest, name = line.split(None, 1)
            checksums[name.strip()] = digest
        for name, digest in checksums.items():
            target = path / name
            if not target.exists() or _sha256_file(target) != digest:
                return {"ok": False, "msg": "checksum mismatch", "file": name}
        overall = hashlib.sha256(checksums_path.read_text(encoding="utf-8").encode("utf-8")).hexdigest()
        if metadata.get("checksum") != overall:
            return {"ok": False, "msg": "metadata checksum mismatch"}
        conn = sqlite3.connect(str(path / "db.sqlite3.backup"))
        try:
            conn.execute("PRAGMA integrity_check").fetchone()
        finally:
            conn.close()
        for archive in (path / "uploads.tar.gz", path / "config.tar.gz"):
            with tarfile.open(archive, "r:gz") as tar:
                for member in tar.getmembers():
                    if not _safe_relative_tarinfo(member):
                        return {"ok": False, "msg": "unsafe tar member", "file": member.name}
        return {"ok": True, "msg": "snapshot verified", "metadata": metadata}

    def verify_snapshot(self, *, snapshot_id):
        return self._verify_snapshot_dir(self._snapshot_dir(snapshot_id))

    def export_snapshot_archive(self, *, snapshot_id, actor=None):
        actor_name = self._actor_name(actor)
        snapshot = self.get_snapshot(snapshot_id=snapshot_id, actor=actor)
        if not snapshot:
            return {"ok": False, "msg": "找不到 snapshot"}
        if snapshot.get("status") != "ready":
            return {"ok": False, "msg": "snapshot 尚未 ready"}
        verification = self.verify_snapshot(snapshot_id=snapshot_id)
        if not verification["ok"]:
            self.audit("SNAPSHOT_EXPORT_VERIFY_FAILED", "-", user=actor_name, success=False, detail=f"snapshot_id={snapshot_id},reason={verification}")
            return {"ok": False, "msg": verification["msg"], "verification": verification}

        snapshot_dir = self._snapshot_dir(snapshot_id)
        archive_path = self._portable_archive_path(snapshot_id)
        tmp_path = archive_path.with_suffix(archive_path.suffix + ".tmp")
        with tarfile.open(tmp_path, "w:gz") as tar:
            for name in PORTABLE_SNAPSHOT_FILES:
                tar.add(snapshot_dir / name, arcname=f"{snapshot_id}/{name}")
        os.replace(tmp_path, archive_path)
        size_bytes = archive_path.stat().st_size
        self.audit("SNAPSHOT_EXPORTED", "-", user=actor_name, success=True, detail=f"snapshot_id={snapshot_id},size={size_bytes}")
        return {
            "ok": True,
            "snapshot_id": snapshot_id,
            "path": str(archive_path),
            "filename": archive_path.name,
            "size_bytes": size_bytes,
            "verification": verification,
        }

    def _copy_archive_input(self, *, archive_path=None, file_storage=None, dest=None):
        if archive_path:
            shutil.copyfile(archive_path, dest)
            return
        stream = getattr(file_storage, "stream", file_storage)
        if hasattr(stream, "seek"):
            stream.seek(0)
        with open(dest, "wb") as out:
            shutil.copyfileobj(stream, out)

    def _locate_imported_snapshot_dir(self, import_dir):
        direct = [import_dir / name for name in PORTABLE_SNAPSHOT_FILES]
        if all(path.exists() for path in direct):
            return import_dir
        children = [path for path in import_dir.iterdir() if path.is_dir()]
        matches = [path for path in children if all((path / name).exists() for name in PORTABLE_SNAPSHOT_FILES)]
        if len(matches) != 1:
            raise ValueError("snapshot 封包格式錯誤")
        return matches[0]

    def import_snapshot_archive(self, *, actor, archive_path=None, file_storage=None, notes=None):
        if not archive_path and file_storage is None:
            return {"ok": False, "msg": "缺少 snapshot 檔案"}
        actor_id = self._actor_id(actor)
        actor_name = self._actor_name(actor)
        self.imports_root.mkdir(parents=True, exist_ok=True)
        import_id = f"import_{secrets.token_hex(8)}"
        import_dir = self.imports_root / import_id
        package_path = self.imports_root / f"{import_id}.tar.gz"
        try:
            import_dir.mkdir(parents=True, exist_ok=False)
            self._copy_archive_input(archive_path=archive_path, file_storage=file_storage, dest=package_path)
            if not package_path.exists() or package_path.stat().st_size <= 0:
                raise ValueError("snapshot 檔案為空")
            _safe_extract_tar(package_path, import_dir)
            imported_dir = self._locate_imported_snapshot_dir(import_dir)
            verification = self._verify_snapshot_dir(imported_dir)
            if not verification["ok"]:
                return {"ok": False, "msg": verification["msg"], "verification": verification}
            metadata = verification.get("metadata") or {}
            snapshot_id = metadata.get("snapshot_id")
            if not _safe_snapshot_id(snapshot_id):
                return {"ok": False, "msg": "snapshot metadata id 格式錯誤"}
            target_dir = self._snapshot_dir(snapshot_id)
            if target_dir.exists():
                return {"ok": False, "msg": "本機已存在相同 snapshot_id", "snapshot_id": snapshot_id}
            target_dir.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(imported_dir), str(target_dir))
            conn = self.get_db()
            try:
                record = self._upsert_local_snapshot_record(
                    conn,
                    snapshot_id,
                    actor_id=actor_id,
                    notes=f"imported portable snapshot; {notes or ''}".strip(),
                )
                conn.commit()
            finally:
                conn.close()
            self.audit("SNAPSHOT_IMPORTED", "-", user=actor_name, success=True, detail=f"snapshot_id={snapshot_id},size={record['size_bytes']}")
            return {"ok": True, "snapshot_id": snapshot_id, "snapshot": self.get_snapshot(snapshot_id=snapshot_id, actor=actor), "verification": verification}
        except Exception as exc:
            self.audit("SNAPSHOT_IMPORT_FAILED", "-", user=actor_name, success=False, detail=f"error={exc}")
            return {"ok": False, "msg": "snapshot 匯入失敗", "error": str(exc)}
        finally:
            try:
                if import_dir.exists():
                    shutil.rmtree(import_dir)
                if package_path.exists():
                    package_path.unlink()
            except Exception:
                pass

    def restore_snapshot_archive(self, *, actor, archive_path=None, file_storage=None, reason="", dry_run=False):
        imported = self.import_snapshot_archive(actor=actor, archive_path=archive_path, file_storage=file_storage, notes=reason)
        if not imported.get("ok"):
            return imported
        result = self.restore_snapshot(
            snapshot_id=imported["snapshot_id"],
            actor=actor,
            reason=reason or "restore from uploaded portable snapshot",
            dry_run=dry_run,
        )
        return {**result, "imported_snapshot_id": imported["snapshot_id"], "import": imported}

    def _restore_db(self, snapshot_dir):
        src = sqlite3.connect(str(snapshot_dir / "db.sqlite3.backup"))
        dst = sqlite3.connect(str(self.db_path))
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()

    def _clear_file_roots(self):
        for root in self.file_roots:
            if root.exists() and root.is_dir():
                for child in root.iterdir():
                    if child.is_symlink():
                        child.unlink()
                    elif child.is_dir():
                        shutil.rmtree(child)
                    else:
                        child.unlink()
            root.mkdir(parents=True, exist_ok=True)

    def _rel_to_base_text(self, path):
        try:
            return str(Path(path).resolve(strict=False).relative_to(self.base_dir.resolve(strict=False)))
        except Exception:
            return str(path)

    def _remove_runtime_secret_files(self):
        removed = []
        skipped = []
        base = self.base_dir.resolve(strict=False)
        for raw_path in self.runtime_secret_files:
            path = raw_path if raw_path.is_absolute() else self.base_dir / raw_path
            rel_text = self._rel_to_base_text(path)
            try:
                resolved = path.resolve(strict=False)
                if resolved != base and base not in resolved.parents:
                    skipped.append({"path": str(path), "reason": "outside_base_dir"})
                    continue
                if not path.exists() and not path.is_symlink():
                    continue
                if path.is_dir():
                    skipped.append({"path": rel_text, "reason": "is_directory"})
                    continue
                path.unlink()
                removed.append(rel_text)
            except Exception as exc:
                skipped.append({"path": rel_text, "reason": str(exc)})
        return {"removed": removed, "skipped": skipped}

    def _existing_resettable_tables(self, conn):
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        existing = {row["name"] if isinstance(row, sqlite3.Row) else row[0] for row in rows}
        reset_tables = existing & RESETTABLE_TABLES
        priority = {
            "forum_post_reactions": 10,
            "forum_thread_reactions": 11,
            "forum_posts": 12,
            "forum_threads": 13,
            "forum_boards": 14,
            "forum_categories": 15,
            "album_files": 20,
            "albums": 21,
            "storage_share_links": 30,
            "file_access_grants": 31,
            "encrypted_file_keys": 32,
            "cloud_file_refs": 33,
            "storage_files": 34,
            "storage_folders": 35,
            "uploaded_files": 36,
            "direct_messages": 40,
            "dm_threads": 41,
            "chat_message_reports": 42,
            "chat_messages": 43,
            "trading_spot_realized_pnl": 50,
            "trading_fills": 51,
            "trading_orders": 52,
            "trading_spot_positions": 53,
            "trading_futures_positions": 54,
            "trading_margin_positions": 55,
            "trading_pending_profit": 56,
            "trading_reserve_pool_events": 57,
            "trading_audit_events": 58,
            "trading_reserve_pool": 59,
            "trading_state": 60,
            "trading_markets": 61,
        }
        return sorted(reset_tables, key=lambda name: (priority.get(name, 100), name))

    def _apply_management_only_settings(self, conn, *, actor_name, reset_at):
        applied = {}
        for key, value in MANAGEMENT_ONLY_RESET_SETTINGS.items():
            conn.execute(
                "INSERT OR REPLACE INTO system_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                (key, str(bool(value)), reset_at, actor_name or "system_reset"),
            )
            applied[key] = bool(value)
        row = conn.execute("SELECT current_mode FROM server_modes WHERE id=1").fetchone()
        previous_mode = row["current_mode"] if row else None
        conn.execute(
            """
            INSERT INTO server_modes
            (id, current_mode, previous_mode, active_snapshot_id, mode_changed_by, mode_changed_at, notes)
            VALUES (1, 'test', ?, NULL, NULL, ?, 'runtime reset default')
            ON CONFLICT(id) DO UPDATE SET
                previous_mode=excluded.previous_mode,
                current_mode='test',
                active_snapshot_id=NULL,
                mode_changed_by=NULL,
                mode_changed_at=excluded.mode_changed_at,
                notes=excluded.notes
            """,
            (previous_mode, reset_at),
        )
        return applied

    def daily_snapshot_status(self, *, settings, now=None):
        now = now or datetime.now()
        settings = dict(settings or {})
        enabled_raw = settings.get("snapshot_daily_auto_enabled", False)
        enabled = enabled_raw if isinstance(enabled_raw, bool) else str(enabled_raw).strip().lower() in {"1", "true", "yes", "on"}
        hour, minute, normalized_time = _parse_daily_snapshot_time(settings.get("snapshot_daily_time"))
        today = now.date().isoformat()
        last_date = str(settings.get("snapshot_daily_last_date") or "")
        due_at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        due = enabled and last_date != today and now >= due_at
        reason = "due"
        if not enabled:
            reason = "disabled"
        elif last_date == today:
            reason = "already_created_today"
        elif now < due_at:
            reason = "before_scheduled_time"
        return {
            "enabled": enabled,
            "configured_time": normalized_time,
            "today": today,
            "last_date": last_date,
            "due": due,
            "reason": reason,
            "due_at": due_at.isoformat(),
            "checked_at": now.isoformat(),
        }

    def create_daily_snapshot_if_due(self, *, actor, settings, save_settings=None, now=None, force=False, notes=None):
        now = now or datetime.now()
        status = self.daily_snapshot_status(settings=settings, now=now)
        if not force and not status["due"]:
            return {"ok": True, "created": False, "status": status}

        result = self.create_snapshot(
            snapshot_type="scheduled",
            actor=actor,
            notes=notes or f"daily auto snapshot {status['today']}",
        )
        if not result.ok:
            return {
                "ok": False,
                "created": False,
                "msg": "daily snapshot 建立失敗",
                "error": result.error,
                "status": status,
            }
        if save_settings:
            save_settings({"snapshot_daily_last_date": status["today"]})
        return {
            "ok": True,
            "created": True,
            "snapshot_id": result.snapshot_id,
            "status": {**status, "last_date": status["today"], "due": False, "reason": "created"},
        }

    def reset_runtime_state(self, *, actor, confirm, reason):
        if confirm != "RESET_RUNTIME_STATE":
            return {"ok": False, "msg": "confirm 必須等於 RESET_RUNTIME_STATE"}

        actor_id = self._actor_id(actor)
        actor_name = self._actor_name(actor)
        pre = self.create_snapshot(snapshot_type="pre_reset", actor=actor, notes=f"Before runtime reset: {reason or ''}")
        if not pre.ok:
            return {"ok": False, "msg": "pre_reset snapshot failed", "error": pre.error}

        reset_at = datetime.now().isoformat()
        conn = self.get_db()
        cleared_tables = []
        try:
            self.ensure_schema(conn)
            for table in self._existing_resettable_tables(conn):
                conn.execute(f"DELETE FROM {table}")
                cleared_tables.append(table)
            if cleared_tables:
                try:
                    placeholders = ",".join("?" for _ in cleared_tables)
                    conn.execute(f"DELETE FROM sqlite_sequence WHERE name IN ({placeholders})", cleared_tables)
                except Exception:
                    pass
            management_settings = self._apply_management_only_settings(conn, actor_name=actor_name, reset_at=reset_at)
            conn.commit()
        finally:
            conn.close()

        self._clear_file_roots()
        points_result = None
        if self.reset_points_chain:
            points_result = self.reset_points_chain(
                actor=actor,
                reason=reason or "",
                pre_reset_snapshot_id=pre.snapshot_id,
            )
        secret_result = self._remove_runtime_secret_files()
        audit_detail = (
            f"actor_id={actor_id},pre_reset_snapshot={pre.snapshot_id},tables={','.join(cleared_tables)},"
            f"points_chain_reset={bool(points_result and points_result.get('ok'))},"
            f"server_mode=test,"
            f"runtime_secret_files_removed={','.join(secret_result['removed'])},"
            f"runtime_secret_files_skipped={json.dumps(secret_result['skipped'], ensure_ascii=False, sort_keys=True)},"
            f"management_only_settings={','.join(k for k, v in management_settings.items() if v)},"
            f"disabled_settings={','.join(k for k, v in management_settings.items() if not v)},"
            f"reason={reason or ''},reset_at={reset_at}"
        )
        audit_result = None
        if self.reset_audit_chain:
            try:
                audit_result = self.reset_audit_chain(
                    "SYSTEM_RUNTIME_RESET",
                    "-",
                    user=actor_name,
                    success=True,
                    detail=audit_detail,
                    write_event=False,
                )
            except TypeError:
                audit_result = self.reset_audit_chain(
                    "SYSTEM_RUNTIME_RESET",
                    "-",
                    user=actor_name,
                    success=True,
                    detail=audit_detail,
                )
        else:
            self.audit("SYSTEM_RUNTIME_RESET", "-", user=actor_name, success=True, detail=audit_detail)
        return {
            "ok": True,
            "msg": "runtime state reset",
            "pre_reset_snapshot_id": pre.snapshot_id,
            "cleared_tables": cleared_tables,
            "points_chain_reset": points_result,
            "audit_chain_reset": audit_result,
            "server_mode": "test",
            "management_only_settings": management_settings,
            "runtime_secret_files_removed": secret_result["removed"],
            "runtime_secret_files_skipped": secret_result["skipped"],
            "requires_restart": True,
            "reset_at": reset_at,
        }

    def restore_snapshot(self, *, snapshot_id, actor, reason, dry_run=False):
        actor_id = self._actor_id(actor)
        actor_name = self._actor_name(actor)
        verification = self.verify_snapshot(snapshot_id=snapshot_id)
        if not verification["ok"]:
            self.audit("SNAPSHOT_VERIFY_FAILED", "-", user=actor_name, success=False, detail=f"snapshot_id={snapshot_id},reason={verification}")
            return {"ok": False, "msg": verification["msg"], "verification": verification}
        self.audit("SNAPSHOT_VERIFY_OK", "-", user=actor_name, success=True, detail=f"snapshot_id={snapshot_id}")
        if dry_run:
            event_id = f"restore_{secrets.token_hex(8)}"
            conn = self.get_db()
            try:
                self.ensure_schema(conn)
                conn.execute(
                    "INSERT INTO snapshot_restore_events "
                    "(id, snapshot_id, restored_by, started_at, completed_at, status, restore_mode, checksum_verified, dry_run, error_message) "
                    "VALUES (?, ?, ?, ?, ?, 'verified', 'dry_run', 1, 1, NULL)",
                    (event_id, snapshot_id, actor_id, datetime.now().isoformat(), datetime.now().isoformat()),
                )
                conn.commit()
            finally:
                conn.close()
            return {"ok": True, "msg": "dry-run verified", "event_id": event_id, "verification": verification}

        pre = self.create_snapshot(snapshot_type="pre_restore", actor=actor, notes=f"Before restore {snapshot_id}: {reason}")
        if not pre.ok:
            return {"ok": False, "msg": "pre_restore snapshot failed", "error": pre.error}
        event_id = f"restore_{secrets.token_hex(8)}"
        started_at = datetime.now().isoformat()
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            try:
                conn.execute("UPDATE system_settings SET value='true', value_type='bool', updated_at=? WHERE key='maintenance_mode'", (started_at,))
            except Exception:
                pass
            conn.execute(
                "INSERT INTO snapshot_restore_events "
                "(id, snapshot_id, restored_by, started_at, status, restore_mode, pre_restore_snapshot_id, checksum_verified, dry_run) "
                "VALUES (?, ?, ?, ?, 'restoring', 'full', ?, 1, 0)",
                (event_id, snapshot_id, actor_id, started_at, pre.snapshot_id),
            )
            conn.commit()
        finally:
            conn.close()

        try:
            snapshot_dir = self._snapshot_dir(snapshot_id)
            self.audit("SNAPSHOT_RESTORE_STARTED", "-", user=actor_name, success=True, detail=f"snapshot_id={snapshot_id},pre_restore={pre.snapshot_id},reason={reason}")
            self._restore_db(snapshot_dir)
            self._clear_file_roots()
            _safe_extract_tar(snapshot_dir / "uploads.tar.gz", self.base_dir)
            completed_at = datetime.now().isoformat()
            conn = self.get_db()
            try:
                self.ensure_schema(conn)
                self._upsert_local_snapshot_record(conn, snapshot_id, actor_id=actor_id)
                conn.execute(
                    "INSERT OR REPLACE INTO snapshot_restore_events "
                    "(id, snapshot_id, restored_by, started_at, completed_at, status, restore_mode, pre_restore_snapshot_id, checksum_verified, dry_run) "
                    "VALUES (?, ?, ?, ?, ?, 'completed', 'full', ?, 1, 0)",
                    (event_id, snapshot_id, actor_id, started_at, completed_at, pre.snapshot_id),
                )
                conn.commit()
            finally:
                conn.close()
            post_restore_validation = self._run_post_restore_validators()
            if not post_restore_validation["ok"]:
                conn = self.get_db()
                try:
                    self.ensure_schema(conn)
                    conn.execute(
                        "INSERT OR REPLACE INTO snapshot_restore_events "
                        "(id, snapshot_id, restored_by, started_at, completed_at, status, restore_mode, pre_restore_snapshot_id, checksum_verified, dry_run, error_message) "
                        "VALUES (?, ?, ?, ?, ?, 'failed', 'full', ?, 1, 0, ?)",
                        (
                            event_id,
                            snapshot_id,
                            actor_id,
                            started_at,
                            datetime.now().isoformat(),
                            pre.snapshot_id,
                            json.dumps(post_restore_validation, ensure_ascii=False, sort_keys=True),
                        ),
                    )
                    conn.commit()
                finally:
                    conn.close()
                self.audit("SNAPSHOT_RESTORE_VALIDATION_FAILED", "-", user=actor_name, success=False, detail=f"snapshot_id={snapshot_id},validation={post_restore_validation}")
                return {
                    "ok": False,
                    "msg": "post-restore validation failed",
                    "event_id": event_id,
                    "pre_restore_snapshot_id": pre.snapshot_id,
                    "post_restore_validation": post_restore_validation,
                }
            self.audit("SNAPSHOT_RESTORE_COMPLETED", "-", user=actor_name, success=True, detail=f"snapshot_id={snapshot_id},pre_restore={pre.snapshot_id},reason={reason}")
            return {"ok": True, "msg": "snapshot restored", "event_id": event_id, "pre_restore_snapshot_id": pre.snapshot_id, "post_restore_validation": post_restore_validation}
        except Exception as exc:
            conn = self.get_db()
            try:
                self.ensure_schema(conn)
                conn.execute(
                    "INSERT OR REPLACE INTO snapshot_restore_events "
                    "(id, snapshot_id, restored_by, started_at, completed_at, status, restore_mode, pre_restore_snapshot_id, checksum_verified, dry_run, error_message) "
                    "VALUES (?, ?, ?, ?, ?, 'failed', 'full', ?, 1, 0, ?)",
                    (event_id, snapshot_id, actor_id, started_at, datetime.now().isoformat(), pre.snapshot_id, str(exc)),
                )
                conn.commit()
            finally:
                conn.close()
            self.audit("SNAPSHOT_RESTORE_FAILED", "-", user=actor_name, success=False, detail=f"snapshot_id={snapshot_id},error={exc}")
            return {"ok": False, "msg": "restore failed", "error": str(exc), "pre_restore_snapshot_id": pre.snapshot_id}

    def delete_snapshot(self, *, snapshot_id, actor, reason):
        path = self._snapshot_dir(snapshot_id)
        actor_name = self._actor_name(actor)
        if path.exists():
            shutil.rmtree(path)
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            conn.execute("UPDATE snapshots SET status='deleted', error_message=? WHERE id=?", (reason or "", snapshot_id))
            conn.commit()
        finally:
            conn.close()
        self.audit("SNAPSHOT_DELETE", "-", user=actor_name, success=True, detail=f"snapshot_id={snapshot_id},reason={reason}")
        return {"ok": True, "msg": "snapshot deleted"}


class ServerModeService:
    def __init__(self, *, snapshot_service, get_db, audit, integrity_guard=None, save_settings=None):
        self.snapshot_service = snapshot_service
        self.get_db = get_db
        self.audit = audit
        self.integrity_guard = integrity_guard
        self.save_settings = save_settings

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
        return data

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
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            row = conn.execute("SELECT * FROM security_profiles WHERE name=?", (str(name or ""),)).fetchone()
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

    def _apply_production_upload_policy(self, conn):
        try:
            from services.upload_security import ensure_upload_security_schema, update_cloud_drive_security_policy
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
        target_mode = str(target_mode or "").strip().lower()
        profile = self.get_profile(target_mode)
        if not profile:
            return {"ok": False, "msg": "server mode 錯誤"}
        if target_mode == "production" and confirm != "GO_LIVE":
            return {"ok": False, "msg": "進入 production 上線模式必須在確認欄輸入 GO_LIVE"}
        if target_mode in {"preprod", "production"} and self.integrity_guard:
            allowed, high_risk_count = self.integrity_guard.can_enter_preprod()
            if not allowed:
                return {
                    "ok": False,
                    "msg": "存在 pending/rejected high risk Integrity Guard finding，不允許進入準上線或上線模式",
                    "high_risk_count": high_risk_count,
                }
        if target_mode == "superweak":
            return self.enter_superweak(actor=actor, confirm=confirm, notes=notes)
        applied_settings = {}
        if self.save_settings:
            updates = {}
            updates.update(profile.get("settings") or {})
            updates.update(profile.get("thresholds") or {})
            applied_settings = self.save_settings(updates) if updates else {}
        production_result = None
        if target_mode == "production":
            production_result = self._apply_production_hardening(actor=actor)
            if not production_result.get("ok"):
                return production_result
        internal_test_result = None
        if target_mode == "internal_test":
            internal_test_result = self._apply_internal_test_hardening()
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            current = conn.execute("SELECT current_mode FROM server_modes WHERE id=1").fetchone()["current_mode"]
            conn.execute(
                "UPDATE server_modes SET previous_mode=?, current_mode=?, active_snapshot_id=NULL, mode_changed_by=?, mode_changed_at=?, notes=? WHERE id=1",
                (current, target_mode, int(actor["id"]), datetime.now().isoformat(), notes or ""),
            )
            conn.commit()
            self.audit("SERVER_MODE_CHANGE", "-", user=actor["username"], success=True, detail=f"old_value={current},new_value={target_mode},profile={profile['name']},settings={applied_settings},production={production_result or {}},internal_test={internal_test_result or {}},reason={notes or ''}")
            return {"ok": True, "mode": self.get_current_mode(), "profile": profile, "applied_settings": applied_settings, "production": production_result, "internal_test": internal_test_result}
        finally:
            conn.close()

    def enter_superweak(self, *, actor, confirm, notes=None):
        if confirm != "ENABLE_SUPERWEAK":
            return {"ok": False, "msg": "confirm 必須等於 ENABLE_SUPERWEAK"}
        current = self.get_current_mode()
        if current["current_mode"] == "superweak":
            return {"ok": False, "msg": "目前已是 superweak 模式"}
        snap = self.snapshot_service.create_snapshot(snapshot_type="before_superweak", actor=actor, notes=notes or "Before enabling superweak")
        if not snap.ok:
            return {"ok": False, "msg": "before_superweak snapshot 建立失敗", "error": snap.error}
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            conn.execute(
                "UPDATE server_modes SET previous_mode=?, current_mode='superweak', active_snapshot_id=?, mode_changed_by=?, mode_changed_at=?, notes=? WHERE id=1",
                (current["current_mode"], snap.snapshot_id, int(actor["id"]), datetime.now().isoformat(), notes or ""),
            )
            conn.commit()
            self.audit("SUPERWEAK_ENTER", "-", user=actor["username"], success=True, detail=f"snapshot_id={snap.snapshot_id},old_value={current['current_mode']},new_value=superweak")
            return {"ok": True, "mode": self.get_current_mode(), "snapshot_id": snap.snapshot_id}
        finally:
            conn.close()

    def exit_superweak(self, *, actor, action, confirm, reason):
        current = self.get_current_mode()
        if current["current_mode"] != "superweak":
            return {"ok": False, "msg": "目前不是 superweak 模式"}
        if action == "restore":
            if confirm != "RESTORE_BEFORE_SUPERWEAK":
                return {"ok": False, "msg": "confirm 必須等於 RESTORE_BEFORE_SUPERWEAK"}
            snapshot_id = current["active_snapshot_id"]
            result = self.snapshot_service.restore_snapshot(snapshot_id=snapshot_id, actor=actor, reason=reason or "exit superweak", dry_run=False)
            if not result.get("ok"):
                return result
            previous = current["previous_mode"] or "preprod"
            conn = self.get_db()
            try:
                self.ensure_schema(conn)
                conn.execute(
                    "UPDATE server_modes SET current_mode=?, previous_mode='superweak', active_snapshot_id=NULL, mode_changed_by=?, mode_changed_at=?, notes=? WHERE id=1",
                    (previous, int(actor["id"]), datetime.now().isoformat(), reason or ""),
                )
                conn.commit()
            finally:
                conn.close()
            self.audit("SUPERWEAK_EXIT_RESTORE", "-", user=actor["username"], success=True, detail=f"restored_snapshot={snapshot_id},new_value={previous},reason={reason}")
            return {"ok": True, "mode": self.get_current_mode(), **result}
        if action == "keep_dirty_state":
            if confirm != "KEEP_DIRTY_SUPERWEAK_STATE":
                return {"ok": False, "msg": "confirm 必須等於 KEEP_DIRTY_SUPERWEAK_STATE"}
            previous = current["previous_mode"] or "preprod"
            conn = self.get_db()
            try:
                self.ensure_schema(conn)
                conn.execute(
                    "UPDATE server_modes SET current_mode=?, previous_mode='superweak', active_snapshot_id=NULL, mode_changed_by=?, mode_changed_at=?, notes=? WHERE id=1",
                    (previous, int(actor["id"]), datetime.now().isoformat(), reason or ""),
                )
                conn.commit()
            finally:
                conn.close()
            self.audit("SUPERWEAK_EXIT_KEEP_DIRTY_STATE", "-", user=actor["username"], success=True, detail=f"warning=dirty_state_kept,reason={reason}")
            return {"ok": True, "warning": "已保留 superweak 期間的 dirty state；此操作具高風險", "mode": self.get_current_mode()}
        return {"ok": False, "msg": "action 錯誤"}
