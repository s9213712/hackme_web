from tests.comfyui._integration_suite import _build_app, _init_db
from services.comfyui.client import ComfyUIError
from services.comfyui.node_catalog import build_node_catalog


OBJECT_INFO = {
    "CheckpointLoaderSimple": {
        "display_name": "Load Checkpoint",
        "category": "loaders",
        "input": {
            "required": {
                "ckpt_name": [["dream.safetensors", "photo.ckpt"]],
            },
        },
        "output": ["MODEL", "CLIP", "VAE"],
    },
    "FluxProUltraImageNode": {
        "display_name": "Flux Pro Ultra",
        "category": "api nodes/partner",
        "input": {
            "required": {
                "prompt": ["STRING", {"multiline": True}],
                "model": ["MODEL"],
            },
            "optional": {
                "steps": ["INT", {"default": 20, "step": 1}],
            },
        },
        "output": ["IMAGE"],
    },
}


class CatalogClient:
    base_url = "http://fake-comfyui"

    def get_object_info(self):
        return OBJECT_INFO


class OfflineModelsClient(CatalogClient):
    def get_models(self):
        raise ComfyUIError("ComfyUI 連線失敗：offline")


def test_build_node_catalog_compacts_object_info_for_editor():
    catalog = build_node_catalog(OBJECT_INFO)

    assert catalog["count"] == 2
    checkpoint = next(node for node in catalog["nodes"] if node["class_type"] == "CheckpointLoaderSimple")
    assert checkpoint["inputs"]["ckpt_name"]["type"] == "select"
    assert checkpoint["inputs"]["ckpt_name"]["options"] == ["dream.safetensors", "photo.ckpt"]
    paid = next(node for node in catalog["nodes"] if node["class_type"] == "FluxProUltraImageNode")
    assert paid["paid_api_required"] is True
    assert paid["inputs"]["model"]["type"] == "link"
    assert paid["inputs"]["prompt"]["type"] == "textarea"
    assert paid["outputs"] == ["IMAGE"]


def test_comfyui_node_catalog_endpoint_returns_safe_summary(tmp_path):
    db_path = tmp_path / "comfyui.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    app = _build_app(db_path, storage_root, comfyui_client=CatalogClient())

    response = app.test_client().get("/api/comfyui/node-catalog")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["count"] == 2
    assert payload["nodes"][0]["class_type"]
    assert any(node["paid_api_required"] for node in payload["nodes"])
    assert "input" not in payload["nodes"][0]


def test_comfyui_models_endpoint_returns_degraded_payload_when_offline(tmp_path):
    db_path = tmp_path / "comfyui.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    app = _build_app(db_path, storage_root, comfyui_client=OfflineModelsClient())

    response = app.test_client().get("/api/comfyui/models")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["available"] is False
    assert payload["models"] == []
    assert payload["samplers"]
