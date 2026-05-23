import json
import sqlite3

from services.system.notifications import create_notification, ensure_notifications_schema, serialize_notification


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
