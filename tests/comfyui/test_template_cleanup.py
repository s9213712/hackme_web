"""§10.3.2 cleanup + 24h sweeper regression."""

import pytest

from services.comfyui.template.cleanup import (
    COMFYUI_RUN_TTL_SECONDS,
    cleanup_run_temp_files,
    list_active_run_dirs,
    register_run_dir,
    registry_size,
    reset_registry,
    sweep_orphaned_run_dirs,
)


@pytest.fixture(autouse=True)
def _isolate_registry():
    reset_registry()
    yield
    reset_registry()


class _FakeClock:
    def __init__(self, t=0.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, secs):
        self.t += secs


def test_register_run_dir_persists_to_registry():
    register_run_dir(run_id="abc123", user_id=7)
    assert registry_size() == 1
    [entry] = list_active_run_dirs()
    assert entry.run_id == "abc123"
    assert entry.user_id == 7


def test_register_run_dir_is_idempotent_on_same_run_id():
    clock = _FakeClock()
    register_run_dir(run_id="abc", user_id=7, clock=clock)
    first_ts = list_active_run_dirs()[0].created_at
    clock.advance(60)
    register_run_dir(run_id="abc", user_id=7, clock=clock)
    # Only one entry; original timestamp preserved
    assert registry_size() == 1
    assert list_active_run_dirs()[0].created_at == first_ts


def test_register_run_dir_strips_unsafe_run_id_chars():
    register_run_dir(run_id="abc/../etc", user_id=1)
    [entry] = list_active_run_dirs()
    assert "/" not in entry.run_id
    assert entry.run_id == "abcetc"


def test_cleanup_run_temp_files_calls_callback_and_marks_purged():
    register_run_dir(run_id="abc", user_id=7)
    calls = []

    def _cb(*, run_id, user_id):
        calls.append((run_id, user_id))
        return True

    ok = cleanup_run_temp_files(
        run_id="abc",
        user_id=7,
        cleanup_callback=_cb,
        audit=None,
    )
    assert ok is True
    assert calls == [("abc", 7)]
    # Registry entry now marked purged → not in active list
    assert registry_size() == 1
    assert list_active_run_dirs() == []


def test_cleanup_run_temp_files_audit_emitted_on_success():
    register_run_dir(run_id="abc", user_id=7)
    audit_calls = []

    def _audit(action, ip, **kwargs):
        audit_calls.append((action, kwargs))

    cleanup_run_temp_files(
        run_id="abc",
        user_id=7,
        cleanup_callback=lambda **_: True,
        audit=_audit,
        audit_user="alice",
    )
    actions = [c[0] for c in audit_calls]
    assert "COMFYUI_TEMPLATE_RUN_INPUT_CLEANUP" in actions


def test_cleanup_run_temp_files_audit_emitted_on_failure():
    register_run_dir(run_id="abc", user_id=7)
    audit_calls = []

    def _audit(action, ip, **kwargs):
        audit_calls.append((action, kwargs))

    ok = cleanup_run_temp_files(
        run_id="abc",
        user_id=7,
        cleanup_callback=lambda **_: False,
        audit=_audit,
        audit_user="alice",
    )
    assert ok is False
    success_flags = [c[1].get("success") for c in audit_calls]
    assert False in success_flags


def test_cleanup_run_temp_files_callback_exception_does_not_propagate():
    register_run_dir(run_id="abc", user_id=7)

    def _bad_cb(**_):
        raise RuntimeError("comfyui down")

    audit_calls = []
    ok = cleanup_run_temp_files(
        run_id="abc",
        user_id=7,
        cleanup_callback=_bad_cb,
        audit=lambda *a, **k: audit_calls.append(k),
    )
    assert ok is False
    # Audit log records the failure
    assert audit_calls
    assert audit_calls[0]["success"] is False
    assert "callback_raised" in audit_calls[0]["detail"]


def test_sweeper_reaps_only_entries_past_ttl():
    clock = _FakeClock()
    register_run_dir(run_id="old", user_id=1, clock=clock)
    clock.advance(COMFYUI_RUN_TTL_SECONDS - 100)
    register_run_dir(run_id="young", user_id=2, clock=clock)
    clock.advance(150)  # old=now ~24h+50s; young=now 150s

    purged = []

    def _cb(*, run_id, user_id):
        purged.append(run_id)
        return True

    summary = sweep_orphaned_run_dirs(
        cleanup_callback=_cb,
        ttl_seconds=COMFYUI_RUN_TTL_SECONDS,
        clock=clock,
    )
    assert summary["candidates"] == 1
    assert summary["reaped"] == 1
    assert summary["failed"] == 0
    assert purged == ["old"]
    # young entry remains active
    remaining_ids = {e.run_id for e in list_active_run_dirs()}
    assert remaining_ids == {"young"}


def test_sweeper_skips_already_purged_entries():
    clock = _FakeClock()
    register_run_dir(run_id="abc", user_id=1, clock=clock)
    cleanup_run_temp_files(
        run_id="abc", user_id=1, cleanup_callback=lambda **_: True
    )
    clock.advance(COMFYUI_RUN_TTL_SECONDS + 1)

    calls = []
    sweep_orphaned_run_dirs(
        cleanup_callback=lambda **kw: (calls.append(kw), True)[1],
        ttl_seconds=COMFYUI_RUN_TTL_SECONDS,
        clock=clock,
    )
    # Already-purged entry never reaches the cleanup_callback again.
    assert calls == []


def test_sweeper_reports_failed_count_when_callback_returns_false():
    clock = _FakeClock()
    register_run_dir(run_id="dead", user_id=1, clock=clock)
    clock.advance(COMFYUI_RUN_TTL_SECONDS + 1)

    summary = sweep_orphaned_run_dirs(
        cleanup_callback=lambda **_: False,
        ttl_seconds=COMFYUI_RUN_TTL_SECONDS,
        clock=clock,
    )
    assert summary["candidates"] == 1
    assert summary["reaped"] == 0
    assert summary["failed"] == 1


def test_default_ttl_matches_spec():
    """§10.3.2: 24h reap window."""
    assert COMFYUI_RUN_TTL_SECONDS == 24 * 60 * 60
