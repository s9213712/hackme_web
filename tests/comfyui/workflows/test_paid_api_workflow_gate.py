import json
import sqlite3
import time

from tests.comfyui._integration_suite import FakeComfyUIClient, _build_app, _import_workflow_preset, _init_db


class PaidApiWorkflowClient(FakeComfyUIClient):
    last_extra_data = None

    def get_capabilities(self):
        data = super().get_capabilities()
        data["available_nodes"] = list(data["available_nodes"]) + ["FluxProUltraImageNode"]
        return data

    def generate_from_workflow(self, workflow, *, timeout_seconds=180, expected_count=1, progress_callback=None, extra_data=None):
        PaidApiWorkflowClient.last_extra_data = dict(extra_data or {})
        return super().generate_from_workflow(
            workflow,
            timeout_seconds=timeout_seconds,
            expected_count=expected_count,
            progress_callback=progress_callback,
        )


def _paid_workflow():
    return {
        "1": {"class_type": "FluxProUltraImageNode", "inputs": {"prompt": "paid api test"}},
        "2": {"class_type": "SaveImage", "inputs": {"images": ["1", 0], "filename_prefix": "paid-api"}},
    }


def _client(tmp_path, *, settings=None):
    db_path = tmp_path / "comfyui.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    app = _build_app(
        db_path,
        storage_root,
        settings=settings or {},
        comfyui_client=PaidApiWorkflowClient(),
    )
    return app.test_client(), db_path


def test_paid_api_workflow_run_requires_feature_flag(tmp_path):
    client, _ = _client(tmp_path)
    preset = _import_workflow_preset(client, _paid_workflow(), title="Paid API Flow")

    response = client.post(f"/api/comfyui/workflows/{preset['id']}/run", json={"confirm_paid_api_nodes": True})

    assert response.status_code == 409
    payload = response.get_json()
    assert payload["stage"] == "paid_api_nodes_disabled"
    assert payload["paid_api_nodes"]["nodes"][0]["class_type"] == "FluxProUltraImageNode"


def test_paid_api_workflow_run_requires_key_and_confirmation(tmp_path):
    client, _ = _client(tmp_path, settings={"comfyui_paid_api_nodes_enabled": True})
    preset = _import_workflow_preset(client, _paid_workflow(), title="Paid API Flow")

    missing_key = client.post(f"/api/comfyui/workflows/{preset['id']}/run", json={"confirm_paid_api_nodes": True})
    assert missing_key.status_code == 409
    assert missing_key.get_json()["stage"] == "paid_api_key_missing"

    confirmed_root = tmp_path / "confirmed"
    confirmed_root.mkdir()
    client, _ = _client(
        confirmed_root,
        settings={"comfyui_paid_api_nodes_enabled": True, "comfyui_account_api_key": "comfyui-test-key"},
    )
    preset = _import_workflow_preset(client, _paid_workflow(), title="Paid API Flow")
    needs_confirm = client.post(f"/api/comfyui/workflows/{preset['id']}/run", json={})
    assert needs_confirm.status_code == 409
    assert needs_confirm.get_json()["stage"] == "paid_api_confirmation_required"


def test_paid_api_workflow_run_injects_comfyui_account_key_after_confirmation(tmp_path):
    PaidApiWorkflowClient.last_extra_data = None
    client, db_path = _client(
        tmp_path,
        settings={"comfyui_paid_api_nodes_enabled": True, "comfyui_account_api_key": "comfyui-test-key"},
    )
    preset = _import_workflow_preset(client, _paid_workflow(), title="Paid API Flow")

    response = client.post(f"/api/comfyui/workflows/{preset['id']}/run", json={"confirm_paid_api_nodes": True})

    assert response.status_code == 200, response.get_json()
    job_id = response.get_json()["job"]["job_id"]
    body = client.get(f"/api/comfyui/jobs/{job_id}").get_json()
    for _ in range(40):
        if body["job"]["status"] == "completed":
            break
        time.sleep(0.05)
        body = client.get(f"/api/comfyui/jobs/{job_id}").get_json()
    assert body["job"]["status"] == "completed"
    assert PaidApiWorkflowClient.last_extra_data == {"api_key_comfy_org": "comfyui-test-key"}

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT workflow_json FROM comfyui_workflow_runs ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    assert row is not None
    assert "comfyui-test-key" not in json.dumps(json.loads(row["workflow_json"]))
