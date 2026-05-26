import json
import sqlite3

from services.system.notifications import (
    create_notification,
    ensure_notifications_schema,
    serialize_notification,
    serialize_notification_timestamp,
)


def test_notification_center_extended_fields_are_backward_compatible():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY)")
    conn.execute("INSERT INTO users (id) VALUES (1)")
    ensure_notifications_schema(conn)

    created = create_notification(
        conn,
        user_id=1,
        type="job.failed",
        title="任務失敗",
        body="影音轉碼失敗",
        severity="error",
        source_module="videos",
        source_ref="job-1",
        metadata_json=json.dumps({"action": "retry_job", "job_id": "job-1"}),
    )
    assert created is True
    row = conn.execute("SELECT * FROM notifications").fetchone()
    payload = serialize_notification(row)
    assert payload["severity"] == "error"
    assert payload["source_module"] == "videos"
    assert payload["dismissed_at"] is None
    assert payload["metadata"] == {"action": "retry_job", "job_id": "job-1"}


def test_notification_serialization_marks_legacy_naive_timestamp_as_local_time():
    value = serialize_notification_timestamp("2026-05-25T14:54:13.351757")

    assert value.startswith("2026-05-25T14:54:13.351757")
    assert value != "2026-05-25T14:54:13.351757"
    assert value.endswith("Z") is False


def test_notification_serialization_preserves_explicit_utc_timestamp():
    assert serialize_notification_timestamp("2026-05-25T06:54:13Z") == "2026-05-25T06:54:13Z"
