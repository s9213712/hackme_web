import sqlite3
import zipfile

import pytest

from services.upload_security import (
    check_magic_mime_safety,
    check_office_macro_safety,
    check_zip_archive_safety,
    create_uploaded_file_record,
    ensure_upload_security_schema,
    evaluate_upload_policy,
    get_cloud_drive_safety_summary,
    get_cloud_drive_security_policy,
    get_user_cloud_drive_usage,
    reencode_image_strip_metadata,
    safe_public_filename,
    safe_public_mime_type,
    scan_archive_members,
    update_cloud_drive_security_policy,
)
from services.storage_quota_overrides import set_storage_quota_override
from services.points_chain import ensure_points_economy_schema
from services.storage_quota_purchases import (
    ensure_storage_upgrade_price_catalog,
    enrich_storage_upgrade_catalog,
    list_storage_upgrade_price_catalog,
    record_storage_quota_purchase,
    storage_upgrade_product_from_catalog,
)
from services.storage_capacity_audit import audit_storage_capacity, can_allocate_storage_bytes


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT)")
    conn.execute("INSERT INTO users (id, username) VALUES (1, 'alice'), (2, 'bob')")
    ensure_upload_security_schema(conn)
    return conn


def test_upload_security_schema_seeds_file_type_policies():
    conn = _conn()
    try:
        rows = conn.execute("SELECT category, default_risk_level FROM file_type_policies").fetchall()
        policies = {row["category"]: row["default_risk_level"] for row in rows}
        assert policies["executable"] == "high"
        assert policies["archive"] == "medium"
        assert policies["default"] == "low"
    finally:
        conn.close()


def test_upload_security_schema_migrates_old_file_type_policy_columns():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT)")
        conn.execute(
            """
            CREATE TABLE file_type_policies (
                category TEXT PRIMARY KEY,
                extensions_json TEXT NOT NULL,
                public_allowed INTEGER NOT NULL,
                private_scannable_allowed INTEGER NOT NULL,
                e2ee_allowed INTEGER NOT NULL,
                default_risk_level TEXT NOT NULL,
                allow_public_share INTEGER NOT NULL,
                requires_scan INTEGER NOT NULL,
                warn_on_download INTEGER NOT NULL,
                notes TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            INSERT INTO file_type_policies (
                category, extensions_json, public_allowed, private_scannable_allowed,
                e2ee_allowed, default_risk_level, allow_public_share, requires_scan,
                warn_on_download, notes, created_at, updated_at
            ) VALUES ('default', '[]', 1, 0, 1, 'low', 1, 1, 0, '', '2026-01-01', '2026-01-01')
            """
        )
        ensure_upload_security_schema(conn)
        row = conn.execute("SELECT * FROM file_type_policies WHERE category='default'").fetchone()
        assert row["server_readable_allowed"] == 0
        decision = evaluate_upload_policy(conn, filename="note.txt", privacy_mode="server_encrypted", user={"effective_level": "vip"})
        assert decision.allowed is False
    finally:
        conn.close()


def test_cloud_drive_security_policy_defaults_are_safe():
    conn = _conn()
    try:
        policy = get_cloud_drive_security_policy(conn)
        assert policy["block_unclean_downloads"] is True
        assert policy["warn_high_risk_downloads"] is True
        assert policy["e2ee_server_scan_claim_allowed"] is False
        assert policy["scanner_enabled"] is True
        assert policy["scanner_backend"] == "clamav"
        assert policy["fail_closed_on_scanner_error"] is True
        assert policy["max_archive_files"] == 200
        assert policy["deep_archive_scan_enabled"] is True
        assert policy["max_archive_depth"] == 2
        assert policy["office_macro_scan_enabled"] is True
        assert policy["image_reencode_enabled"] is True
        assert policy["image_reencode_max_pixels"] == 25_000_000
        assert policy["yara_enabled"] is False
    finally:
        conn.close()


def test_update_cloud_drive_security_policy_validates_and_serializes():
    conn = _conn()
    try:
        policy, err = update_cloud_drive_security_policy(
            conn,
            {
                "block_unclean_downloads": False,
                "max_archive_files": 12,
                "scanner_backend": "disabled",
                "scanner_timeout_seconds": 10,
                "scanner_enabled": False,
                "deep_archive_scan_enabled": True,
                "max_archive_depth": 3,
                "office_macro_scan_enabled": True,
                "image_reencode_enabled": False,
                "image_reencode_max_pixels": 12345,
                "yara_enabled": True,
                "yara_command": "yara",
                "max_daily_downloads": 40,
                "notes": "root tuned policy",
            },
        )
        assert err is None
        assert policy["block_unclean_downloads"] is False
        assert policy["scanner_backend"] == "disabled"
        assert policy["scanner_timeout_seconds"] == 10
        assert policy["scanner_enabled"] is False
        assert policy["max_archive_files"] == 12
        assert policy["max_archive_depth"] == 3
        assert policy["image_reencode_enabled"] is False
        assert policy["image_reencode_max_pixels"] == 12345
        assert policy["yara_enabled"] is True
        assert policy["yara_command"] == "yara"
        assert policy["max_daily_downloads"] == 40
        assert policy["notes"] == "root tuned policy"

        policy, err = update_cloud_drive_security_policy(conn, {"max_daily_downloads": -1})
        assert policy is None
        assert err == "max_daily_downloads 不可小於 0"

        policy, err = update_cloud_drive_security_policy(conn, {"scanner_backend": "cloud_api"})
        assert policy is None
        assert "scanner_backend" in err

        policy, err = update_cloud_drive_security_policy(conn, {"scanner_command": "/bin/sh -c id"})
        assert policy is None
        assert "scanner_command" in err

        policy, err = update_cloud_drive_security_policy(conn, {"yara_command": "/usr/bin/yara"})
        assert policy is None
        assert "yara_command" in err
    finally:
        conn.close()


def test_executable_public_upload_is_blocked():
    conn = _conn()
    try:
        decision = evaluate_upload_policy(
            conn,
            filename="tool.exe",
            privacy_mode="standard_plain",
            user={"effective_level": "vip"},
        )
        assert decision.allowed is False
        assert decision.risk_level == "blocked"
        assert decision.scan_status == "quarantined"
    finally:
        conn.close()


def test_newbie_cannot_upload_archive_even_when_archive_policy_allows_others():
    conn = _conn()
    try:
        decision = evaluate_upload_policy(
            conn,
            filename="backup.zip",
            privacy_mode="standard_plain",
            user={"effective_level": "newbie"},
        )
        assert decision.allowed is False
        assert "newbie" in decision.reason
    finally:
        conn.close()


def test_e2ee_record_preserves_display_filename_but_not_file_key():
    conn = _conn()
    try:
        result = create_uploaded_file_record(
            conn,
            owner_user_id=1,
            storage_path="storage/e2ee/blob.bin",
            privacy_mode="e2ee",
            size_bytes=12,
            original_filename="secret-tax.pdf",
            encrypted_metadata="sealed:metadata",
            encrypted_file_key="sealed:file-key",
            ciphertext_sha256="c" * 64,
            user={"effective_level": "vip"},
        )
        row = conn.execute("SELECT * FROM uploaded_files WHERE id=?", (result["file_id"],)).fetchone()
        key_row = conn.execute("SELECT * FROM encrypted_file_keys WHERE file_id=?", (result["file_id"],)).fetchone()
        assert row["risk_level"] == "unknown_encrypted"
        assert row["scan_status"] == "unknown_encrypted"
        assert row["original_filename_plain_for_public"] == "secret-tax.pdf"
        assert row["plaintext_sha256"] is None
        assert key_row["encrypted_file_key"] == "sealed:file-key"
        assert "sealed:file-key" not in str(dict(row))
    finally:
        conn.close()


def test_public_mime_type_uses_server_safe_guess_not_client_header():
    assert safe_public_mime_type("photo.png", "text/html") == "image/png"
    assert safe_public_mime_type("pwn.html", "text/html") == "application/octet-stream"
    assert safe_public_mime_type("vector.svg", "image/svg+xml") == "application/octet-stream"
    assert safe_public_mime_type("note.txt", "text/html") == "text/plain"
    assert safe_public_mime_type("song.mp3", "text/html") == "audio/mpeg"
    assert safe_public_mime_type("voice.wav", "text/html") in {"audio/wav", "audio/x-wav"}


def test_uploaded_file_record_stores_safe_public_mime_type():
    conn = _conn()
    try:
        result = create_uploaded_file_record(
            conn,
            owner_user_id=1,
            storage_path="storage/public/blob",
            privacy_mode="standard_plain",
            size_bytes=10,
            original_filename="pwn.html",
            mime_type="text/html",
            user={"effective_level": "vip"},
        )
        row = conn.execute(
            "SELECT mime_type_plain_for_public FROM uploaded_files WHERE id=?",
            (result["file_id"],),
        ).fetchone()
        assert row["mime_type_plain_for_public"] == "application/octet-stream"
    finally:
        conn.close()


def test_cloud_drive_usage_reports_used_and_remaining_quota():
    conn = _conn()
    try:
        create_uploaded_file_record(
            conn,
            owner_user_id=1,
            storage_path="storage/public/a.txt",
            privacy_mode="standard_plain",
            size_bytes=256,
            original_filename="a.txt",
            user={"effective_level": "trusted"},
        )
        create_uploaded_file_record(
            conn,
            owner_user_id=1,
            storage_path="storage/e2ee/blob.bin",
            privacy_mode="e2ee",
            size_bytes=512,
            encrypted_metadata="sealed",
            encrypted_file_key="sealed-key",
            user={"effective_level": "vip"},
        )
        usage = get_user_cloud_drive_usage(
            conn,
            {"id": 1, "role": "user", "effective_level": "trusted", "sanction_status": "none"},
            member_rule={"can_upload_attachment": True, "attachment_quota_mb": 1, "max_attachment_size_mb": 1, "upload_rate_limit_per_day": 10},
        )
        assert usage["used_bytes"] == 768
        assert usage["total_bytes"] == 1024 * 1024
        assert usage["remaining_bytes"] == 1024 * 1024 - 768
        assert usage["by_privacy_mode"]["standard_plain"]["count"] == 1
        assert usage["by_privacy_mode"]["e2ee"]["count"] == 1
    finally:
        conn.close()


def test_cloud_drive_safety_summary_restricted_user_cannot_upload():
    conn = _conn()
    try:
        summary = get_cloud_drive_safety_summary(
            conn,
            {"id": 1, "role": "user", "effective_level": "restricted", "sanction_status": "restricted"},
            member_rule={"can_upload_attachment": True, "attachment_quota_mb": 10, "max_attachment_size_mb": 1},
        )
        assert summary["usage"]["can_upload"] is False
        assert any("restricted" in item for item in summary["restrictions"])
    finally:
        conn.close()


def test_root_role_uses_disk_backed_quota(tmp_path, monkeypatch):
    class FakeDiskUsage:
        total = 20_000
        used = 10_000
        free = 10_000

    monkeypatch.setattr("services.upload_security.shutil.disk_usage", lambda path: FakeDiskUsage())
    conn = _conn()
    try:
        admin = {"id": 1, "username": "root", "role": "super_admin", "effective_level": "suspended", "sanction_status": "suspended"}
        usage = get_user_cloud_drive_usage(
            conn,
            admin,
            member_rule={"can_upload_attachment": False, "attachment_quota_mb": 0, "max_attachment_size_mb": 0, "upload_rate_limit_per_day": 0},
            storage_root=tmp_path,
        )
        assert usage["can_upload"] is True
        assert usage["total_bytes"] == 9_000
        assert usage["max_file_size_bytes"] == 9_000
        assert usage["upload_rate_limit_per_day"] is None
        assert usage["quota_source"] == "root_disk_available_90_percent"
        assert usage["warning_threshold_percent"] == 80
        assert usage["warning_active"] is False

        create_uploaded_file_record(
            conn,
            owner_user_id=1,
            storage_path="storage/admin/large.txt",
            privacy_mode="standard_plain",
            size_bytes=7_300,
            original_filename="large.txt",
            user=admin,
        )
        summary = get_cloud_drive_safety_summary(conn, admin, member_rule={"can_upload_attachment": False}, storage_root=tmp_path)
        assert not any("restricted/suspended" in item for item in summary["restrictions"])
        assert summary["usage"]["warning_active"] is True
        assert any("80%" in item for item in summary["restrictions"])

        decision = evaluate_upload_policy(
            conn,
            filename="backup.zip",
            privacy_mode="standard_plain",
            user={"id": 1, "username": "admin", "role": "manager", "effective_level": "newbie"},
        )
        assert decision.allowed is True
    finally:
        conn.close()


def test_manager_role_uses_fixed_1gb_cloud_drive_quota(tmp_path, monkeypatch):
    class FakeDiskUsage:
        total = 20_000
        used = 10_000
        free = 10_000

    monkeypatch.setattr("services.upload_security.shutil.disk_usage", lambda path: FakeDiskUsage())
    conn = _conn()
    try:
        manager = {"id": 1, "username": "admin", "role": "manager", "effective_level": "suspended", "sanction_status": "suspended"}
        usage = get_user_cloud_drive_usage(
            conn,
            manager,
            member_rule={"can_upload_attachment": False, "attachment_quota_mb": 0, "max_attachment_size_mb": 0, "upload_rate_limit_per_day": 0},
            storage_root=tmp_path,
        )
        assert usage["can_upload"] is True
        assert usage["total_bytes"] == 1024 * 1024 * 1024
        assert usage["max_file_size_bytes"] == 1024 * 1024 * 1024
        assert usage["upload_rate_limit_per_day"] is None
        assert usage["quota_source"] == "manager_role_fixed_1gb"
        assert usage["disk"] is None
        assert usage["warning_threshold_percent"] is None
    finally:
        conn.close()


def test_purchased_storage_adds_to_non_root_cloud_drive_quota(tmp_path):
    conn = _conn()
    try:
        record_storage_quota_purchase(
            conn,
            user_id=1,
            item_key="cloud_storage_1gb_30d",
            quantity=2,
            points_spent=200,
            ledger_uuid="ledger-storage-test",
        )
        user = {"id": 1, "username": "alice", "role": "user", "effective_level": "trusted", "sanction_status": "none"}
        usage = get_user_cloud_drive_usage(
            conn,
            user,
            member_rule={"can_upload_attachment": True, "attachment_quota_mb": 1, "max_attachment_size_mb": 1, "upload_rate_limit_per_day": 10},
            storage_root=tmp_path,
        )
        assert usage["base_quota_bytes"] == 1024 * 1024
        assert usage["purchased_extra_bytes"] == 2 * 1024 * 1024 * 1024
        assert usage["total_bytes"] == 1024 * 1024 + 2 * 1024 * 1024 * 1024
        assert usage["purchased_storage"]["active_purchase_count"] == 1
        assert usage["quota_source"].endswith("+storage_purchase")
    finally:
        conn.close()


def test_storage_upgrade_price_catalog_backfills_missing_items():
    conn = _conn()
    try:
        ensure_points_economy_schema(conn)
        conn.execute("DELETE FROM economy_price_catalog WHERE item_key LIKE 'cloud_storage_%'")
        ensure_storage_upgrade_price_catalog(conn)
        rows = conn.execute(
            "SELECT * FROM economy_price_catalog WHERE item_key LIKE 'cloud_storage_%' AND enabled=1 ORDER BY item_key"
        ).fetchall()
        catalog = enrich_storage_upgrade_catalog([dict(row) for row in rows])
        assert [item["item_key"] for item in catalog] == ["cloud_storage_1gb_30d"]
        assert catalog[0]["storage_bytes"] == 1024 * 1024 * 1024
    finally:
        conn.close()


def test_storage_upgrade_catalog_supports_root_defined_plans():
    conn = _conn()
    try:
        ensure_points_economy_schema(conn)
        conn.execute(
            """
            INSERT INTO economy_price_catalog (
                item_key, item_name, category, currency_type, base_price,
                dynamic_pricing, min_price, max_price, enabled, metadata_json,
                created_at, updated_at
            ) VALUES (?, ?, 'cloud_drive', 'soft', 25, 0, 10, 100, 1, ?, 'now', 'now')
            """,
            (
                "cloud_storage_2gb_7d",
                "雲端容量 2GB / 7 天",
                '{"storage_bytes":2147483648,"duration_days":7,"label":"雲端容量 2GB / 7 天"}',
            ),
        )
        rows = list_storage_upgrade_price_catalog(conn)
        custom = next(row for row in rows if row["item_key"] == "cloud_storage_2gb_7d")
        assert custom["storage_bytes"] == 2 * 1024 * 1024 * 1024
        assert custom["duration_days"] == 7
        assert storage_upgrade_product_from_catalog(conn, "cloud_storage_2gb_7d")["storage_bytes"] == 2 * 1024 * 1024 * 1024
    finally:
        conn.close()


def test_root_storage_quota_ignores_purchased_storage(tmp_path, monkeypatch):
    class FakeDiskUsage:
        total = 20_000
        used = 10_000
        free = 10_000

    monkeypatch.setattr("services.upload_security.shutil.disk_usage", lambda path: FakeDiskUsage())
    conn = _conn()
    try:
        record_storage_quota_purchase(
            conn,
            user_id=1,
            item_key="cloud_storage_1gb_30d",
            quantity=2,
            points_spent=200,
            ledger_uuid="ledger-root-ignore",
        )
        root = {"id": 1, "username": "root", "role": "super_admin", "effective_level": "vip", "sanction_status": "none"}
        usage = get_user_cloud_drive_usage(conn, root, member_rule={"can_upload_attachment": True}, storage_root=tmp_path)
        assert usage["total_bytes"] == 9_000
        assert usage["purchased_extra_bytes"] == 0
        assert usage["quota_source"] == "root_disk_available_90_percent"
    finally:
        conn.close()


def test_root_storage_override_takes_priority_over_role_quota(tmp_path):
    conn = _conn()
    try:
        manager = {"id": 1, "username": "admin", "role": "manager", "effective_level": "suspended", "sanction_status": "suspended"}
        set_storage_quota_override(
            conn,
            1,
            quota_bytes=256 * 1024 * 1024,
            max_file_size_bytes=12 * 1024 * 1024,
            upload_rate_limit_per_day=3,
            can_upload_override=False,
            reason="root direct quota test",
            actor_user_id=2,
        )
        usage = get_user_cloud_drive_usage(
            conn,
            manager,
            member_rule={"can_upload_attachment": False, "attachment_quota_mb": 0, "max_attachment_size_mb": 0, "upload_rate_limit_per_day": 0},
            storage_root=tmp_path,
        )
        assert usage["quota_source"] == "root_user_override"
        assert usage["total_bytes"] == 256 * 1024 * 1024
        assert usage["max_file_size_bytes"] == 12 * 1024 * 1024
        assert usage["upload_rate_limit_per_day"] == 3
        assert usage["can_upload"] is False
        assert usage["root_override"]["reason"] == "root direct quota test"
    finally:
        conn.close()


def test_storage_capacity_audit_detects_host_overcommit(tmp_path, monkeypatch):
    class FakeDiskUsage:
        total = 1_000
        used = 500
        free = 500

    monkeypatch.setattr("services.storage_capacity_audit.shutil.disk_usage", lambda path: FakeDiskUsage())
    conn = _conn()
    try:
        set_storage_quota_override(conn, 1, quota_bytes=0, reason="baseline", actor_user_id=2)
        set_storage_quota_override(conn, 2, quota_bytes=0, reason="baseline", actor_user_id=2)
        audit = audit_storage_capacity(conn, tmp_path)
        assert audit["status"] == "ok"
        assert audit["allocatable_cloud_capacity_bytes"] == 450
        assert audit["available_cloud_capacity_bytes"] == 450

        set_storage_quota_override(
            conn,
            1,
            quota_bytes=800,
            reason="overcommit test",
            actor_user_id=2,
        )
        audit = audit_storage_capacity(conn, tmp_path)
        assert audit["status"] == "critical"
        assert audit["total_overcommitted_by_bytes"] > 0
        assert audit["total_commitment_over_available_by_bytes"] > 0
        assert "host_storage_total_commitment_exceeds_available" in audit["reasons"]
        assert "host_storage_overcommitted" in audit["reasons"]
    finally:
        conn.close()


def test_storage_capacity_guard_blocks_new_quota_when_host_is_full(tmp_path, monkeypatch):
    class FakeDiskUsage:
        total = 1_000
        used = 900
        free = 100

    monkeypatch.setattr("services.storage_capacity_audit.shutil.disk_usage", lambda path: FakeDiskUsage())
    conn = _conn()
    try:
        ok, msg, projected = can_allocate_storage_bytes(conn, tmp_path, 200)
        assert ok is False
        assert "Host" in msg
        assert projected["projected_total_commitment_over_available_by_bytes"] > 0
        assert projected["projected_total_overcommitted_by_bytes"] > 0
    finally:
        conn.close()


def test_e2ee_upload_requires_encrypted_file_key():
    conn = _conn()
    try:
        with pytest.raises(ValueError):
            create_uploaded_file_record(
                conn,
                owner_user_id=1,
                storage_path="storage/e2ee/blob.bin",
                privacy_mode="e2ee",
                size_bytes=12,
                encrypted_metadata="sealed:metadata",
                user={"effective_level": "vip"},
            )
    finally:
        conn.close()


def test_zip_archive_path_traversal_is_rejected(tmp_path):
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("../escape.txt", "bad")

    result = check_zip_archive_safety(archive)
    assert result["ok"] is False
    assert result["reason"] == "path_traversal"


def test_recursive_zip_archive_detects_nested_path_traversal(tmp_path):
    nested = tmp_path / "nested.zip"
    with zipfile.ZipFile(nested, "w") as zf:
        zf.writestr("../escape.txt", "bad")
    outer = tmp_path / "outer.zip"
    with zipfile.ZipFile(outer, "w") as zf:
        zf.write(nested, "nested.zip")

    result = check_zip_archive_safety(outer, recursive=True, max_depth=2)
    assert result["ok"] is False
    assert result["reason"] == "path_traversal"


def test_office_macro_scan_detects_vba_project_in_docx(tmp_path):
    doc = tmp_path / "macro.docx"
    with zipfile.ZipFile(doc, "w") as zf:
        zf.writestr("word/document.xml", "<w:document/>")
        zf.writestr("word/vbaProject.bin", b"macro")

    result = check_office_macro_safety(doc, filename="macro.docx")
    assert result["ok"] is False
    assert result["reason"] == "macro_detected"
    assert "vbaproject.bin" in result["macro_indicators"]


def test_archive_member_scan_detects_disguised_executable(tmp_path):
    archive = tmp_path / "payload.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("avatar.png", b"MZ" + b"\x00" * 16)

    result = scan_archive_members(
        archive,
        policy={
            "deep_archive_scan_enabled": True,
            "max_archive_files": 10,
            "max_archive_uncompressed_bytes": 1024 * 1024,
            "max_archive_depth": 1,
            "yara_enabled": False,
            "scanner_enabled": False,
            "scanner_backend": "disabled",
            "fail_closed_on_scanner_error": False,
        },
    )
    assert result["ok"] is False
    assert result["reason"] == "member_magic_mismatch"


def test_magic_mime_rejects_executable_disguised_as_image(tmp_path):
    disguised = tmp_path / "avatar.png"
    disguised.write_bytes(b"MZ" + b"\x00" * 32)

    result = check_magic_mime_safety(disguised, filename="avatar.png", declared_mime="image/png")
    assert result["ok"] is False
    assert result["reason"] == "executable_magic_mismatch"


def test_image_reencode_strips_jpeg_exif_metadata(tmp_path):
    pytest.importorskip("PIL")
    from PIL import Image

    image_path = tmp_path / "avatar.jpg"
    image = Image.new("RGB", (16, 16), color=(20, 40, 60))
    exif = Image.Exif()
    exif[270] = "private camera note"
    image.save(image_path, format="JPEG", exif=exif)

    before = Image.open(image_path)
    assert before.getexif().get(270) == "private camera note"
    before.close()

    result = reencode_image_strip_metadata(image_path, filename="avatar.jpg")
    assert result["ok"] is True
    assert result["result"] == "clean"

    after = Image.open(image_path)
    try:
        assert after.getexif().get(270) is None
    finally:
        after.close()


def test_scan_uploaded_file_records_image_reencode_result(tmp_path):
    pytest.importorskip("PIL")
    from PIL import Image

    conn = _conn()
    image_path = tmp_path / "avatar.jpg"
    Image.new("RGB", (8, 8), color=(10, 20, 30)).save(image_path, format="JPEG")
    update_cloud_drive_security_policy(conn, {"scanner_enabled": False, "scanner_backend": "disabled"})
    try:
        result = create_uploaded_file_record(
            conn,
            owner_user_id=1,
            storage_path=str(image_path),
            privacy_mode="standard_plain",
            size_bytes=image_path.stat().st_size,
            original_filename="avatar.jpg",
            mime_type="image/jpeg",
            user={"effective_level": "trusted"},
            scan_now=True,
        )
        scanner = conn.execute(
            "SELECT result, details_json FROM file_scan_results WHERE file_id=? AND scanner_name='image-reencode'",
            (result["file_id"],),
        ).fetchone()
        row = conn.execute("SELECT size_bytes, plaintext_sha256 FROM uploaded_files WHERE id=?", (result["file_id"],)).fetchone()
        assert scanner["result"] == "clean"
        assert row["size_bytes"] == image_path.stat().st_size
        assert row["plaintext_sha256"]
    finally:
        conn.close()


def test_scan_uploaded_file_records_clean_clamav_result(tmp_path, monkeypatch):
    conn = _conn()
    sample = tmp_path / "note.txt"
    sample.write_text("hello", encoding="utf-8")

    def fake_clamav(path, *, policy):
        return {"result": "clean", "malware_name": None, "details": {"fake": True}}

    monkeypatch.setattr("services.upload_security.run_clamav_scan", fake_clamav)
    try:
        result = create_uploaded_file_record(
            conn,
            owner_user_id=1,
            storage_path=str(sample),
            privacy_mode="standard_plain",
            size_bytes=sample.stat().st_size,
            original_filename="note.txt",
            mime_type="text/plain",
            user={"effective_level": "trusted"},
            scan_now=True,
        )
        row = conn.execute("SELECT scan_status, risk_level FROM uploaded_files WHERE id=?", (result["file_id"],)).fetchone()
        scanners = [r["scanner_name"] for r in conn.execute("SELECT scanner_name FROM file_scan_results WHERE file_id=? ORDER BY created_at", (result["file_id"],)).fetchall()]
        assert result["scan_status"] == "clean"
        assert row["scan_status"] == "clean"
        assert row["risk_level"] == "low"
        assert "magic-mime" in scanners
        assert "clamav" in scanners
    finally:
        conn.close()


def test_scan_uploaded_file_quarantines_infected_clamav_result(tmp_path, monkeypatch):
    conn = _conn()
    sample = tmp_path / "payload.txt"
    sample.write_text("EICAR marker", encoding="utf-8")

    def fake_clamav(path, *, policy):
        return {"result": "infected", "malware_name": "Eicar-Test-Signature", "details": {"fake": True}}

    monkeypatch.setattr("services.upload_security.run_clamav_scan", fake_clamav)
    try:
        result = create_uploaded_file_record(
            conn,
            owner_user_id=1,
            storage_path=str(sample),
            privacy_mode="standard_plain",
            size_bytes=sample.stat().st_size,
            original_filename="payload.txt",
            user={"effective_level": "trusted"},
            scan_now=True,
        )
        scan_row = conn.execute("SELECT result, malware_name FROM file_scan_results WHERE file_id=? AND scanner_name='clamav'", (result["file_id"],)).fetchone()
        row = conn.execute("SELECT scan_status, risk_level FROM uploaded_files WHERE id=?", (result["file_id"],)).fetchone()
        assert result["scan_status"] == "quarantined"
        assert row["scan_status"] == "quarantined"
        assert row["risk_level"] == "high"
        assert scan_row["result"] == "infected"
        assert scan_row["malware_name"] == "Eicar-Test-Signature"
    finally:
        conn.close()


def test_scan_uploaded_file_soft_skips_when_clamav_missing(tmp_path, monkeypatch):
    conn = _conn()
    sample = tmp_path / "note.txt"
    sample.write_text("hello", encoding="utf-8")
    monkeypatch.setattr("services.upload_security._resolve_clamav_command", lambda policy: None)
    try:
        result = create_uploaded_file_record(
            conn,
            owner_user_id=1,
            storage_path=str(sample),
            privacy_mode="standard_plain",
            size_bytes=sample.stat().st_size,
            original_filename="note.txt",
            user={"effective_level": "trusted"},
            scan_now=True,
        )
        row = conn.execute("SELECT scan_status, risk_level FROM uploaded_files WHERE id=?", (result["file_id"],)).fetchone()
        assert result["scan_status"] == "not_required"
        assert row["scan_status"] == "not_required"
        assert row["risk_level"] == "low"
    finally:
        conn.close()


def test_safe_public_filename_strips_paths_and_control_chars():
    assert safe_public_filename("../../a/bad<script>.png") == "bad_script_.png"
