import json

from scripts.testing.system_stress_probe import OperationBudget, Stats, resolve_session_pool_size, run_operation


def test_expected_503_does_not_count_as_server_busy():
    stats = Stats()

    stats.record("optional_api", status=503, elapsed_ms=1.0, ok=True, body_sample="")
    summary = stats.summary()

    assert summary["server_busy_503"] == 0
    assert summary["transport_or_5xx_failures"] == 0
    assert summary["ops"]["optional_api"]["expected_503"] == 1


def test_feature_disabled_503_does_not_count_as_server_failure():
    stats = Stats()
    body = json.dumps({"ok": False, "feature": "video", "feature_label": "影音"})

    stats.record("video_watch", status=503, elapsed_ms=1.0, ok=False, error=body, body_sample=body)
    summary = stats.summary()

    assert summary["server_busy_503"] == 0
    assert summary["transport_or_5xx_failures"] == 0
    assert summary["ops"]["video_watch"]["feature_disabled_503"] == 1


def test_truncated_feature_disabled_503_does_not_count_as_server_failure():
    stats = Stats()
    body = '{"feature":"feature_videos_enabled","feature_description":"影音若搭配雲端硬碟'

    stats.record("video_list", status=503, elapsed_ms=1.0, ok=False, error=body, body_sample=body)
    summary = stats.summary()

    assert summary["server_busy_503"] == 0
    assert summary["transport_or_5xx_failures"] == 0
    assert summary["ops"]["video_list"]["feature_disabled_503"] == 1


def test_server_busy_503_counts_as_server_failure():
    stats = Stats()
    body = json.dumps({"ok": False, "code": "server_busy"})

    stats.record("upload", status=503, elapsed_ms=1.0, ok=False, error=body, body_sample=body)
    summary = stats.summary()

    assert summary["server_busy_503"] == 1
    assert summary["transport_or_5xx_failures"] == 1
    assert summary["ops"]["upload"]["server_busy_503"] == 1


def test_bt_reject_uses_rejected_torrent_url_instead_of_creating_magnet_task():
    calls = []

    class FakeClient:
        def request(self, *args, **kwargs):
            calls.append((args, kwargs))
            return {"ok": True, "status": 400, "elapsed_ms": 1.0, "op": args[0]}

    result = run_operation(
        "bt_reject",
        FakeClient(),
        {},
        OperationBudget({"bt_reject": 1}),
        1,
    )

    assert result["ok"] is True
    args, kwargs = calls[0]
    assert args[:3] == ("bt_reject", "POST", "/api/cloud-drive/remote-download/tasks")
    assert kwargs["json"] == {"url": "http://127.0.0.1/blocked.torrent", "download_mode": "bt"}
    assert 202 not in kwargs["expected"]


def test_auto_login_session_pool_is_capped_to_account_count():
    size, mode = resolve_session_pool_size(
        requested=0,
        session_mode="login",
        account_count=3,
        concurrency=24,
        logical_users=100,
    )

    assert size == 3
    assert mode == "auto_login_account_capped"


def test_explicit_session_pool_is_respected_for_login_limit_probes():
    size, mode = resolve_session_pool_size(
        requested=96,
        session_mode="login",
        account_count=3,
        concurrency=24,
        logical_users=100,
    )

    assert size == 96
    assert mode == "explicit"


def test_bad_login_operation_treats_auth_rejection_as_expected():
    class FakeLoginClient:
        base_url = "https://127.0.0.1:5000"
        timeout = 1

        def __init__(self, *_args, **_kwargs):
            pass

        def login(self, *, name="login", expected=None):
            return {"ok": 401 in set(expected or []), "status": 401, "elapsed_ms": 1.0, "op": name}

    import scripts.testing.system_stress_probe as probe

    original_client = probe.Client
    try:
        probe.Client = FakeLoginClient
        result = run_operation(
            "bad_login",
            FakeLoginClient(),
            {},
            OperationBudget({"bad_login": 1}),
            1,
        )
    finally:
        probe.Client = original_client

    assert result["op"] == "bad_login"
    assert result["status"] == 401
    assert result["ok"] is True
