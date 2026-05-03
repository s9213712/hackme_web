import importlib.util
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SMOKE_SUITE_PATH = ROOT / "tests" / "smoke_suite.py"


def _load_smoke_suite_module():
    spec = importlib.util.spec_from_file_location("hackme_web_smoke_suite", SMOKE_SUITE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_smoke_suite_defaults_match_pentest_passwords(monkeypatch):
    monkeypatch.delenv("ROOT_PASSWORD", raising=False)
    monkeypatch.delenv("MANAGER_PASSWORD", raising=False)
    monkeypatch.delenv("TEST_PASSWORD", raising=False)

    smoke_suite = _load_smoke_suite_module()

    assert smoke_suite.SMOKE_ROOT_PASSWORD == "RootSmoke123!"
    assert smoke_suite.SMOKE_ADMIN_PASSWORD == "ManagerSmoke123!"
    assert smoke_suite.SMOKE_USER_PASSWORD == "TestSmoke123!"


def test_smoke_suite_feature_snapshot_and_restore_roundtrip():
    smoke_suite = _load_smoke_suite_module()

    class FakeClient:
        def __init__(self):
            self.calls = []

        def fetch_csrf(self):
            self.calls.append(("fetch_csrf",))
            return "csrf-token"

        def request(self, method, path, *, body=None, headers=None):
            self.calls.append((method, path, body, headers))
            if method == "GET":
                return {
                    "status": 200,
                    "json": {
                        "ok": True,
                        "features": {
                            "feature_chat_enabled": True,
                            "feature_games_enabled": False,
                        },
                    },
                }
            return {"status": 200, "json": {"ok": True}}

    client = FakeClient()
    snapshot = smoke_suite.snapshot_feature_settings(client)
    smoke_suite.restore_feature_settings(client, snapshot)

    assert snapshot == {
        "feature_chat_enabled": True,
        "feature_games_enabled": False,
    }
    assert ("GET", "/api/admin/features", None, {"X-CSRF-Token": "csrf-token"}) in client.calls
    assert (
        "PUT",
        "/api/admin/features",
        snapshot,
        {"X-CSRF-Token": "csrf-token"},
    ) in client.calls
