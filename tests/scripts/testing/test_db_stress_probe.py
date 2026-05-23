import time

from scripts.testing import db_stress_probe


def test_db_stress_probe_keeps_secure_audit_chain_pristine(tmp_path):
    paths = db_stress_probe.configure_env(
        tmp_path / "runtime",
        backend="file",
        flush_interval=1.0,
        event_flush_interval=1.0,
    )
    db_stress_probe.init_schemas(paths, user_count=2)

    recorder = db_stress_probe.Recorder()
    db_stress_probe.audit_writer(paths, recorder, time.monotonic() + 0.05, 0)

    audit = db_stress_probe.get_audit_db(str(paths["audit"]))
    try:
        secure_audit_rows = int(audit.execute("SELECT COUNT(*) AS c FROM secure_audit").fetchone()["c"])
        stress_rows = int(audit.execute("SELECT COUNT(*) AS c FROM db_stress_audit_events").fetchone()["c"])
    finally:
        audit.close()

    assert recorder.summary()["error_count"] == 0
    assert secure_audit_rows == 0
    assert stress_rows > 0


def test_db_stress_probe_source_does_not_directly_insert_secure_audit():
    source = db_stress_probe.Path(db_stress_probe.__file__).read_text(encoding="utf-8")

    assert "INSERT INTO secure_audit" not in source
    assert "db_stress_audit_events" in source
