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
    scan_archive_members,
    update_cloud_drive_security_policy,
)
from services.storage_quota_overrides import set_storage_quota_override
from services.points_chain import ensure_points_economy_schema
from services.storage_quota_purchases import (
    ensure_storage_upgrade_price_catalog,
    enrich_storage_upgrade_catalog,
    record_storage_quota_purchase,
)


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
                "yara_command": "/usr/bin/yara",
                "yara_rules_path": "/etc/yara/rules",
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
        assert policy["yara_command"] == "/usr/bin/yara"
        assert policy["yara_rules_path"] == "/etc/yara/rules"
        assert policy["max_daily_downloads"] == 40
        assert policy["notes"] == "root tuned policy"

        policy, err = update_cloud_drive_security_policy(conn, {"max_daily_downloads": -1})
        assert policy is None
        assert err == "max_daily_downloads 不可小於 0"

        policy, err = update_cloud_drive_security_policy(conn, {"scanner_backend": "cloud_api"})
        assert policy is None
        assert "scanner_backend" in err
    finally:
        conn.close()


def test_executable_public_upload_is_blocked():
    conn = _conn()
    try:
        decision = evaluate_upload_policy(
            conn,
            filename="tool.exe",
            privacy_mode="public_attachment",
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
            privacy_mode="public_attachment",
            user={"effective_level": "newbie"},
        )
        assert decision.allowed is False
        assert "newbie" in decision.reason
    finally:
        conn.close()


def test_e2ee_record_does_not_store_plaintext_filename_or_file_key():
    conn = _conn()
    try:
        result = create_uploaded_file_record(
            conn,
            owner_user_id=1,
            storage_path="storage/e2ee/blob.bin",
            privacy_mode="e2ee_vault",
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
        assert row["original_filename_plain_for_public"] is None
        assert row["plaintext_sha256"] is None
        assert key_row["encrypted_file_key"] == "sealed:file-key"
        assert "secret-tax.pdf" not in str(dict(row))
    finally:
        conn.close()


def test_cloud_drive_usage_reports_used_and_remaining_quota():
    conn = _conn()
    try:
        create_uploaded_file_record(
            conn,
            owner_user_id=1,
            storage_path="storage/public/a.txt",
            privacy_mode="public_attachment",
            size_bytes=256,
            original_filename="a.txt",
            user={"effective_level": "trusted"},
        )
        create_uploaded_file_record(
            conn,
            owner_user_id=1,
            storage_path="storage/e2ee/blob.bin",
            privacy_mode="e2ee_vault",
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
        assert usage["by_privacy_mode"]["public_attachment"]["count"] == 1
        assert usage["by_privacy_mode"]["e2ee_vault"]["count"] == 1
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
            privacy_mode="public_attachment",
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
            privacy_mode="public_attachment",
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
        assert [item["item_key"] for item in catalog] == ["cloud_storage_10gb_30d", "cloud_storage_1gb_30d"]
        assert catalog[0]["storage_bytes"] == 10 * 1024 * 1024 * 1024
        assert catalog[1]["storage_bytes"] == 1024 * 1024 * 1024
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


def test_e2ee_upload_requires_encrypted_file_key():
    conn = _conn()
    try:
        with pytest.raises(ValueError):
            create_uploaded_file_record(
                conn,
                owner_user_id=1,
                storage_path="storage/e2ee/blob.bin",
                privacy_mode="e2ee_vault",
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
            privacy_mode="public_attachment",
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
            privacy_mode="public_attachment",
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
            privacy_mode="public_attachment",
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
            privacy_mode="public_attachment",
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
