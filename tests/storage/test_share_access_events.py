import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from services.share_access_events import log_share_access_event, list_share_access_events


def test_share_access_events_record_open_time_and_source_ip():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    try:
        event = log_share_access_event(
            conn,
            share_type="file",
            share_id="share-1",
            ip="203.0.113.10",
            user_agent="pytest-browser",
        )
        conn.commit()

        rows = list_share_access_events(conn, share_type="file", share_id="share-1")

        assert event["created_at"]
        assert rows == [
            {
                "event_type": "opened",
                "ip": "203.0.113.10",
                "user_agent": "pytest-browser",
                "created_at": event["created_at"],
            }
        ]
    finally:
        conn.close()
