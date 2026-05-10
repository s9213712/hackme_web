from services.comfyui.api_nodes import (
    COMFYUI_ACCOUNT_EXTRA_DATA_KEY,
    build_comfyui_account_extra_data,
    detect_paid_api_nodes,
)
from services.comfyui.execution import queue_prompt_with_client_id


class _FakeClient:
    timeout = 1

    def __init__(self):
        self.calls = []

    def _json_request(self, path, *, method="GET", payload=None, timeout=None, allow_non_json=False):
        self.calls.append({"path": path, "method": method, "payload": payload})
        return {"prompt_id": "prompt-1"}


def test_detect_paid_api_nodes_by_known_api_class():
    workflow = {
        "1": {"class_type": "FluxProUltraImageNode", "inputs": {"prompt": "cat"}},
        "2": {"class_type": "SaveImage", "inputs": {"images": ["1", 0]}},
    }

    result = detect_paid_api_nodes(workflow)

    assert result["required"] is True
    assert result["nodes"][0]["node_id"] == "1"
    assert result["nodes"][0]["class_type"] == "FluxProUltraImageNode"


def test_detect_paid_api_nodes_by_object_info_category():
    workflow = {"10": {"class_type": "PartnerRenderNode", "inputs": {"prompt": "cat"}}}
    object_info = {"PartnerRenderNode": {"category": "api nodes/partner", "display_name": "Partner Render"}}

    result = detect_paid_api_nodes(workflow, object_info=object_info)

    assert result["required"] is True
    assert result["nodes"][0]["title"] == "Partner Render"


def test_build_comfyui_account_extra_data_only_when_key_present():
    assert build_comfyui_account_extra_data("") == {}
    assert build_comfyui_account_extra_data("  comfyui-test-key  ") == {
        COMFYUI_ACCOUNT_EXTRA_DATA_KEY: "comfyui-test-key"
    }


def test_queue_prompt_includes_extra_data_only_when_provided():
    client = _FakeClient()

    queued = queue_prompt_with_client_id(
        client,
        {"1": {"class_type": "SaveImage", "inputs": {}}},
        client_id="client-1",
        extra_data={COMFYUI_ACCOUNT_EXTRA_DATA_KEY: "comfyui-test-key"},
        error_cls=RuntimeError,
    )

    assert queued["prompt_id"] == "prompt-1"
    assert client.calls[0]["payload"] == {
        "prompt": {"1": {"class_type": "SaveImage", "inputs": {}}},
        "client_id": "client-1",
        "extra_data": {COMFYUI_ACCOUNT_EXTRA_DATA_KEY: "comfyui-test-key"},
    }

    client = _FakeClient()
    queue_prompt_with_client_id(
        client,
        {"1": {"class_type": "SaveImage", "inputs": {}}},
        client_id="client-2",
        extra_data={},
        error_cls=RuntimeError,
    )
    assert "extra_data" not in client.calls[0]["payload"]
