import json
from pathlib import Path

from scripts.testing.points_chain_destructive_stress import chain_seed_path
from scripts.testing.system_stress_probe import OperationBudget, Stats, resolve_session_pool_size, run_operation


ROOT = Path(__file__).resolve().parents[3]


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


def test_defensive_latency_is_separated_from_ordinary_latency():
    stats = Stats()

    stats.record("bad_login", status=401, elapsed_ms=10_000.0, ok=True)
    stats.record("drive_list", status=200, elapsed_ms=120.0, ok=True)
    summary = stats.summary()

    assert summary["overall_latency"]["p99_ms"] == 10000.0
    assert summary["ordinary_latency"]["p99_ms"] == 120.0
    assert "bad_login" in summary["ordinary_latency"]["excluded_ops"]


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


def test_long_needle_probe_orchestrates_economy_private_chain_and_full_feature():
    script = (ROOT / "scripts" / "testing" / "long_needle_simulation_probe.py").read_text(encoding="utf-8")
    index = (ROOT / "scripts" / "INDEX.md").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "long-needle-simulation.yml").read_text(encoding="utf-8")
    workflow_template = (ROOT / "scripts" / "testing" / "long-needle-simulation.workflow.yml").read_text(encoding="utf-8")

    assert "points_chain_destructive_stress.py" in script
    assert "system_stress_probe.py" in script
    assert "economy_private_chain" in script
    assert "full_feature" in script
    assert "--direct-transfer-ops" in script
    assert "--allow-server-busy" in script
    assert "long_needle_simulation" in script
    assert "scripts/testing/long_needle_simulation_probe.py" in index
    assert workflow == workflow_template
    assert "schedule:" in workflow
    assert "PROFILE=\"medium\"" in workflow
    assert "python scripts/testing/long_needle_simulation_probe.py" in workflow
    assert "actions/upload-artifact@v4" in workflow


def test_points_chain_stress_uses_explicit_finality_sweep_job():
    script = (ROOT / "scripts" / "testing" / "points_chain_destructive_stress.py").read_text(encoding="utf-8")

    assert "def run_finality_sweep_job" in script
    assert '"/api/root/points/finality-sweep"' in script
    assert "root_finalize_transfers" in script
    assert "root_observe_transfers_after_finality_sweep" in script
    assert "compact=1&sweep=0" in script


def test_points_chain_stress_finds_chain_seed_under_runtime_secrets(tmp_path):
    secret_dir = tmp_path / "secrets"
    secret_dir.mkdir()
    expected = secret_dir / ".chain_seed"
    expected.write_text("seed", encoding="utf-8")

    assert chain_seed_path(str(tmp_path)) == expected


def test_bad_login_operation_treats_auth_rejection_as_expected():
    class FakeLoginClient:
        base_url = "https://127.0.0.1:0"
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
