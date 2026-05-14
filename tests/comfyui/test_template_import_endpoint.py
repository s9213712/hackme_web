"""§8 import endpoint regression — POST /api/comfyui/templates/import."""

import json
from pathlib import Path

import pytest
from flask import Flask, request as flask_request

import routes.comfyui_sections.template_routes as template_routes_module
from routes.comfyui_sections.template_routes import register_comfyui_template_routes
from services.comfyui.template.capability import reset_object_info_cache
from services.comfyui.template.preview_store import InMemoryPreviewStore


@pytest.fixture(autouse=True)
def _isolate_object_info_cache():
    reset_object_info_cache()
    yield
    reset_object_info_cache()


@pytest.fixture(autouse=True)
def _isolate_template_bundle_materialization(tmp_path, monkeypatch):
    monkeypatch.setattr(template_routes_module, "REPO_SOURCE_DIR", tmp_path / "repo_workflows")
    monkeypatch.setattr(template_routes_module, "runtime_comfyui_dir", lambda: tmp_path / "runtime_workflows")


TXT2IMG = {
    "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "v1-5.safetensors"}},
    "5": {"class_type": "EmptyLatentImage", "inputs": {"width": 512, "height": 512, "batch_size": 1}},
    "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "cat", "clip": ["4", 1]}},
    "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "low quality", "clip": ["4", 1]}},
    "3": {
        "class_type": "KSampler",
        "inputs": {
            "seed": 0, "steps": 20, "cfg": 7.5, "denoise": 1.0,
            "sampler_name": "euler", "scheduler": "normal",
            "model": ["4", 0], "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["5", 0],
        },
    },
    "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
    "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "ComfyUI", "images": ["8", 0]}},
}

TXT2IMG_NON_DIGIT_IDS = {
    "ckpt_main": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "v1-5.safetensors"}},
    "latent_base": {"class_type": "EmptyLatentImage", "inputs": {"width": 512, "height": 512, "batch_size": 1}},
    "prompt_pos": {"class_type": "CLIPTextEncode", "inputs": {"text": "cat", "clip": ["ckpt_main", 1]}},
    "prompt_neg": {"class_type": "CLIPTextEncode", "inputs": {"text": "low quality", "clip": ["ckpt_main", 1]}},
    "ksampler_main": {
        "class_type": "KSampler",
        "inputs": {
            "seed": 0, "steps": 20, "cfg": 7.5, "denoise": 1.0,
            "sampler_name": "euler", "scheduler": "normal",
            "model": ["ckpt_main", 0], "positive": ["prompt_pos", 0], "negative": ["prompt_neg", 0], "latent_image": ["latent_base", 0],
        },
    },
    "vae_decode": {"class_type": "VAEDecode", "inputs": {"samples": ["ksampler_main", 0], "vae": ["ckpt_main", 2]}},
    "save_image": {"class_type": "SaveImage", "inputs": {"filename_prefix": "ComfyUI", "images": ["vae_decode", 0]}},
}

UI_GRAPH_TXT2IMG_ADV = {
    "id": "demo-ui-graph",
    "revision": 0,
    "last_node_id": 19,
    "last_link_id": 50,
    "nodes": [
        {
            "id": 17,
            "type": "VAEDecode",
            "inputs": [
                {"name": "samples", "type": "LATENT", "link": 49},
                {"name": "vae", "type": "VAE", "link": 50},
            ],
            "outputs": [{"name": "IMAGE", "type": "IMAGE", "slot_index": 0, "links": [28]}],
            "widgets_values": [],
        },
        {
            "id": 7,
            "type": "CLIPTextEncode",
            "inputs": [
                {"name": "clip", "type": "CLIP", "link": 5},
                {"name": "text", "type": "STRING", "widget": {"name": "text"}, "link": 46},
            ],
            "outputs": [{"name": "CONDITIONING", "type": "CONDITIONING", "slot_index": 0, "links": [12]}],
            "widgets_values": ["low quality"],
        },
        {"id": 39, "type": "Note", "inputs": [], "outputs": [], "widgets_values": ["skip me"]},
        {
            "id": 50,
            "type": "PrimitiveNode",
            "inputs": [],
            "outputs": [{"name": "STRING", "type": "STRING", "widget": {"name": "text"}, "slot_index": 0, "links": [46]}],
            "widgets_values": ["low quality"],
        },
        {
            "id": 4,
            "type": "CheckpointLoaderSimple",
            "inputs": [{"name": "ckpt_name", "type": "COMBO", "widget": {"name": "ckpt_name"}, "link": None}],
            "outputs": [
                {"name": "MODEL", "type": "MODEL", "slot_index": 0, "links": [10]},
                {"name": "CLIP", "type": "CLIP", "slot_index": 1, "links": [3, 5]},
                {"name": "VAE", "type": "VAE", "slot_index": 2, "links": [50]},
            ],
            "widgets_values": ["sd_xl_base_1.0.safetensors"],
        },
        {
            "id": 6,
            "type": "CLIPTextEncode",
            "inputs": [
                {"name": "clip", "type": "CLIP", "link": 3},
                {"name": "text", "type": "STRING", "widget": {"name": "text"}, "link": 45},
            ],
            "outputs": [{"name": "CONDITIONING", "type": "CONDITIONING", "slot_index": 0, "links": [11]}],
            "widgets_values": ["a happy cat"],
        },
        {
            "id": 19,
            "type": "SaveImage",
            "inputs": [
                {"name": "images", "type": "IMAGE", "link": 28},
                {"name": "filename_prefix", "type": "STRING", "widget": {"name": "filename_prefix"}, "link": None},
            ],
            "outputs": [],
            "widgets_values": ["ComfyUI"],
        },
        {
            "id": 5,
            "type": "EmptyLatentImage",
            "inputs": [
                {"name": "width", "type": "INT", "widget": {"name": "width"}, "link": None},
                {"name": "height", "type": "INT", "widget": {"name": "height"}, "link": None},
                {"name": "batch_size", "type": "INT", "widget": {"name": "batch_size"}, "link": None},
            ],
            "outputs": [{"name": "LATENT", "type": "LATENT", "slot_index": 0, "links": [27]}],
            "widgets_values": [1024, 1024, 1],
        },
        {
            "id": 10,
            "type": "KSamplerAdvanced",
            "inputs": [
                {"name": "model", "type": "MODEL", "link": 10},
                {"name": "positive", "type": "CONDITIONING", "link": 11},
                {"name": "negative", "type": "CONDITIONING", "link": 12},
                {"name": "latent_image", "type": "LATENT", "link": 27},
                {"name": "add_noise", "type": "COMBO", "widget": {"name": "add_noise"}, "link": None},
                {"name": "noise_seed", "type": "INT", "widget": {"name": "noise_seed"}, "link": None},
                {"name": "steps", "type": "INT", "widget": {"name": "steps"}, "link": None},
                {"name": "cfg", "type": "FLOAT", "widget": {"name": "cfg"}, "link": None},
                {"name": "sampler_name", "type": "COMBO", "widget": {"name": "sampler_name"}, "link": None},
                {"name": "scheduler", "type": "COMBO", "widget": {"name": "scheduler"}, "link": None},
                {"name": "start_at_step", "type": "INT", "widget": {"name": "start_at_step"}, "link": None},
                {"name": "end_at_step", "type": "INT", "widget": {"name": "end_at_step"}, "link": None},
                {"name": "return_with_leftover_noise", "type": "COMBO", "widget": {"name": "return_with_leftover_noise"}, "link": None},
            ],
            "outputs": [{"name": "LATENT", "type": "LATENT", "slot_index": 0, "links": [49]}],
            "widgets_values": ["enable", 123456789, "randomize", 30, 6.5, "euler", "normal", 0, 30, "disable"],
        },
        {
            "id": 51,
            "type": "PrimitiveNode",
            "inputs": [],
            "outputs": [{"name": "STRING", "type": "STRING", "widget": {"name": "text"}, "slot_index": 0, "links": [45]}],
            "widgets_values": ["a happy cat"],
        },
    ],
    "links": [
        [3, 4, 1, 6, 0, "CLIP"],
        [5, 4, 1, 7, 0, "CLIP"],
        [10, 4, 0, 10, 0, "MODEL"],
        [11, 6, 0, 10, 1, "CONDITIONING"],
        [12, 7, 0, 10, 2, "CONDITIONING"],
        [27, 5, 0, 10, 3, "LATENT"],
        [28, 17, 0, 19, 0, "IMAGE"],
        [45, 51, 0, 6, 1, "STRING"],
        [46, 50, 0, 7, 1, "STRING"],
        [49, 10, 0, 17, 0, "LATENT"],
        [50, 4, 2, 17, 1, "VAE"],
    ],
}


def _stub_client(*, classes, models=None):
    info = {cls: {"input": {"required": {}}} for cls in classes}
    if "CheckpointLoaderSimple" in info and models is not None:
        info["CheckpointLoaderSimple"]["input"]["required"]["ckpt_name"] = [list(models)]
    for class_type in ("KSampler", "KSamplerAdvanced"):
        if class_type in info:
            info[class_type]["input"]["required"]["sampler_name"] = [["euler"]]
            info[class_type]["input"]["required"]["scheduler"] = [["normal"]]

    class _Stub:
        base_url = "http://stub"
        def get_object_info(self):
            return info
    return _Stub()


_SENTINEL = object()


def _build_app(*, actor=_SENTINEL, client=None, store=None, presets=None):
    app = Flask(__name__)
    if actor is _SENTINEL:
        actor = {"id": 1, "username": "alice"}
    actor_box = {"actor": actor}
    audit_log = []
    presets_state = presets if presets is not None else {"by_id": {}, "next_id": 1}

    def _actor_or_401():
        if actor_box["actor"] is None:
            resp = app.response_class(
                response=json.dumps({"ok": False, "msg": "未登入"}),
                status=401, mimetype="application/json",
            )
            return None, resp
        return dict(actor_box["actor"]), None

    def _audit(action, ip, *, user="-", success=True, ua="", detail=""):
        audit_log.append({"action": action, "user": user, "success": success, "detail": detail})

    def _actor_value(actor, key):
        return (actor or {}).get(key)

    class _StubConn:
        def __init__(self, presets_state):
            self.presets_state = presets_state
        def execute(self, *args, **kwargs):
            return None
        def commit(self):
            pass
        def close(self):
            pass

    def _get_db():
        return _StubConn(presets_state)

    def _upsert_workflow_preset(conn, *, preset_id=None, actor, title, description,
                                 visibility, workflow_payload, default_params,
                                 is_official=False, published_by_user_id=None):
        new_id = presets_state["next_id"]
        presets_state["next_id"] += 1
        presets_state["by_id"][new_id] = {
            "id": new_id,
            "owner_user_id": _actor_value(actor, "id"),
            "title": title,
            "description": description,
            "visibility": visibility,
            "workflow_json": workflow_payload["workflow_json"],
            "workflow_hash": workflow_payload["workflow_hash"],
            "default_params": default_params,
        }
        return new_id

    def _load_workflow_preset_row(conn, *, preset_id):
        return presets_state["by_id"].get(preset_id)

    def _workflow_preset_summary(row, *, actor=None, **kwargs):
        if row is None:
            return None
        return {
            "id": row["id"],
            "title": row["title"],
            "visibility": row["visibility"],
        }

    actual_store = store if store is not None else InMemoryPreviewStore()
    register_comfyui_template_routes(app, {
        "request": flask_request,
        "actor_or_401": _actor_or_401,
        "actor_value": _actor_value,
        "json_resp": lambda payload: app.response_class(
            response=json.dumps(payload, ensure_ascii=False),
            mimetype="application/json",
        ),
        "require_csrf": lambda f: f,
        "get_client_ip": lambda: "127.0.0.1",
        "get_ua": lambda: "test-agent",
        "audit": _audit,
        "comfyui_binding": lambda a: "http://stub" if client is not None else None,
        "client_for_url": lambda b: client,
        "preview_store": actual_store,
        "get_db": _get_db,
        "upsert_workflow_preset": _upsert_workflow_preset,
        "load_workflow_preset_row": _load_workflow_preset_row,
        "workflow_preset_summary": _workflow_preset_summary,
    })
    app.config.update({
        "actor_box": actor_box,
        "audit_log": audit_log,
        "presets_state": presets_state,
    })
    return app


def _preview_then(client_test, body):
    """Helper: hit /preview, return preview_token."""
    rv = client_test.post("/api/comfyui/templates/preview", json={"workflow": body})
    assert rv.status_code == 200, rv.get_data(as_text=True)
    return rv.get_json()["preview_token"]


def test_import_creates_preset_with_valid_token():
    store = InMemoryPreviewStore()
    client = _stub_client(
        classes={"CheckpointLoaderSimple", "EmptyLatentImage", "CLIPTextEncode",
                 "KSampler", "VAEDecode", "SaveImage"},
        models=["v1-5.safetensors"],
    )
    app = _build_app(client=client, store=store)
    with app.test_client() as c:
        token = _preview_then(c, TXT2IMG)
        rv = c.post(
            "/api/comfyui/templates/import",
            json={"preview_token": token, "title": "My txt2img", "visibility": "private"},
        )
    assert rv.status_code == 200
    body = rv.get_json()
    assert body["ok"] is True
    assert body["preset_id"] >= 1
    assert body["preset"]["title"] == "My txt2img"


def test_import_materializes_bundle_files(tmp_path, monkeypatch):
    store = InMemoryPreviewStore()
    client = _stub_client(
        classes={"CheckpointLoaderSimple", "EmptyLatentImage", "CLIPTextEncode",
                 "KSampler", "VAEDecode", "SaveImage"},
        models=["v1-5.safetensors"],
    )
    repo_root = tmp_path / "repo_workflows"
    runtime_root = tmp_path / "runtime_workflows"
    monkeypatch.setattr(template_routes_module, "REPO_SOURCE_DIR", repo_root)
    monkeypatch.setattr(template_routes_module, "runtime_comfyui_dir", lambda: runtime_root)
    app = _build_app(client=client, store=store)
    with app.test_client() as c:
        token = _preview_then(c, TXT2IMG)
        rv = c.post(
            "/api/comfyui/templates/import",
            json={"preview_token": token, "title": "My txt2img", "visibility": "private"},
        )
    assert rv.status_code == 200
    body = rv.get_json()
    bundle = body["bundle"]
    bundle_id = bundle["id"]
    runtime_dir = Path(bundle["runtime_dir"])
    assert bundle_id.startswith("imported_")
    assert "repo_dir" not in bundle, (
        "imported bundles must NOT expose a repo_dir — they are runtime-only "
        "artifacts; writing to REPO_SOURCE_DIR would pollute workflows/comfyui/"
    )
    assert runtime_dir == runtime_root / bundle_id
    assert (runtime_dir / "workflow.json").is_file()
    assert (runtime_dir / "manifest.json").is_file()
    assert (runtime_dir / "README.md").is_file()
    # The repo source dir must remain untouched by user imports.
    if repo_root.exists():
        assert not (repo_root / bundle_id).exists(), (
            "import wrote to REPO_SOURCE_DIR; this pollutes workflows/comfyui/"
        )
    manifest = json.loads((runtime_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["id"] == bundle_id
    assert manifest["workflow_file"] == "workflow.json"
    assert manifest["source"] == "imported"
    assert manifest["preset_id"] == body["preset_id"]
    assert manifest["ui"]["panels"]


def test_import_accepts_non_digit_string_node_ids(tmp_path, monkeypatch):
    store = InMemoryPreviewStore()
    client = _stub_client(
        classes={"CheckpointLoaderSimple", "EmptyLatentImage", "CLIPTextEncode",
                 "KSampler", "VAEDecode", "SaveImage"},
        models=["v1-5.safetensors"],
    )
    repo_root = tmp_path / "repo_workflows"
    runtime_root = tmp_path / "runtime_workflows"
    monkeypatch.setattr(template_routes_module, "REPO_SOURCE_DIR", repo_root)
    monkeypatch.setattr(template_routes_module, "runtime_comfyui_dir", lambda: runtime_root)
    app = _build_app(client=client, store=store)
    with app.test_client() as c:
        token = _preview_then(c, TXT2IMG_NON_DIGIT_IDS)
        rv = c.post(
            "/api/comfyui/templates/import",
            json={"preview_token": token, "title": "String node ids", "visibility": "private"},
        )
    assert rv.status_code == 200
    body = rv.get_json()
    assert body["ok"] is True
    assert body["bundle"]["id"].startswith("imported_")


def test_import_accepts_ui_graph_and_materializes_api_workflow(tmp_path, monkeypatch):
    store = InMemoryPreviewStore()
    client = _stub_client(
        classes={"CheckpointLoaderSimple", "EmptyLatentImage", "CLIPTextEncode",
                 "KSamplerAdvanced", "VAEDecode", "SaveImage"},
        models=["sd_xl_base_1.0.safetensors"],
    )
    repo_root = tmp_path / "repo_workflows"
    runtime_root = tmp_path / "runtime_workflows"
    monkeypatch.setattr(template_routes_module, "REPO_SOURCE_DIR", repo_root)
    monkeypatch.setattr(template_routes_module, "runtime_comfyui_dir", lambda: runtime_root)
    app = _build_app(client=client, store=store)
    with app.test_client() as c:
        token = _preview_then(c, UI_GRAPH_TXT2IMG_ADV)
        rv = c.post(
            "/api/comfyui/templates/import",
            json={"preview_token": token, "title": "UI graph", "visibility": "private"},
        )
    assert rv.status_code == 200
    body = rv.get_json()
    workflow_json = json.loads((Path(body["bundle"]["runtime_dir"]) / "workflow.json").read_text(encoding="utf-8"))
    assert "39" not in workflow_json
    assert "50" not in workflow_json
    assert "51" not in workflow_json
    assert workflow_json["6"]["inputs"]["text"] == "a happy cat"
    assert workflow_json["7"]["inputs"]["text"] == "low quality"
    assert workflow_json["10"]["class_type"] == "KSamplerAdvanced"
    assert workflow_json["10"]["inputs"]["noise_seed"] == 123456789
    assert workflow_json["10"]["inputs"]["steps"] == 30
    assert workflow_json["10"]["inputs"]["cfg"] == 6.5
    assert workflow_json["10"]["inputs"]["sampler_name"] == "euler"


def test_import_rejects_missing_token():
    app = _build_app()
    with app.test_client() as c:
        rv = c.post("/api/comfyui/templates/import", json={"title": "x"})
    assert rv.status_code == 400
    assert rv.get_json()["stage"] == "token"


def test_import_rejects_unknown_token():
    app = _build_app()
    with app.test_client() as c:
        rv = c.post(
            "/api/comfyui/templates/import",
            json={"preview_token": "tkn_doesnotexist", "title": "x"},
        )
    assert rv.status_code == 400
    assert rv.get_json()["stage"] == "token_invalid"


def test_import_rejects_blank_title():
    store = InMemoryPreviewStore()
    client = _stub_client(
        classes={"CheckpointLoaderSimple", "EmptyLatentImage", "CLIPTextEncode",
                 "KSampler", "VAEDecode", "SaveImage"},
        models=["v1-5.safetensors"],
    )
    app = _build_app(client=client, store=store)
    with app.test_client() as c:
        token = _preview_then(c, TXT2IMG)
        rv = c.post(
            "/api/comfyui/templates/import",
            json={"preview_token": token, "title": "  "},
        )
    assert rv.status_code == 400
    assert rv.get_json()["stage"] == "title"


def test_import_token_is_single_use():
    store = InMemoryPreviewStore()
    client = _stub_client(
        classes={"CheckpointLoaderSimple", "EmptyLatentImage", "CLIPTextEncode",
                 "KSampler", "VAEDecode", "SaveImage"},
        models=["v1-5.safetensors"],
    )
    app = _build_app(client=client, store=store)
    with app.test_client() as c:
        token = _preview_then(c, TXT2IMG)
        rv1 = c.post(
            "/api/comfyui/templates/import",
            json={"preview_token": token, "title": "first"},
        )
        rv2 = c.post(
            "/api/comfyui/templates/import",
            json={"preview_token": token, "title": "second"},
        )
    assert rv1.status_code == 200
    assert rv2.status_code == 400
    assert rv2.get_json()["stage"] == "token_invalid"


def test_import_rejects_when_capability_unsupported():
    """No ComfyUI client → capability=UNSUPPORTED → import blocked."""
    store = InMemoryPreviewStore()
    app = _build_app(client=None, store=store)  # no ComfyUI bound
    with app.test_client() as c:
        token = _preview_then(c, TXT2IMG)
        rv = c.post(
            "/api/comfyui/templates/import",
            json={"preview_token": token, "title": "blocked"},
        )
    assert rv.status_code == 400
    body = rv.get_json()
    assert body["stage"] == "capability"
    assert body["unsupported"]


def test_import_audits_pass_and_fail_paths():
    store = InMemoryPreviewStore()
    client = _stub_client(
        classes={"CheckpointLoaderSimple", "EmptyLatentImage", "CLIPTextEncode",
                 "KSampler", "VAEDecode", "SaveImage"},
        models=["v1-5.safetensors"],
    )
    app = _build_app(client=client, store=store)
    with app.test_client() as c:
        token = _preview_then(c, TXT2IMG)
        c.post("/api/comfyui/templates/import",
               json={"preview_token": token, "title": "ok"})  # PASS
        c.post("/api/comfyui/templates/import",
               json={"preview_token": "tkn_bad", "title": "fail"})  # FAIL token_invalid
    actions = [(e["action"], e["success"]) for e in app.config["audit_log"]]
    assert ("COMFYUI_TEMPLATE_IMPORT_PASS", True) in actions
    assert ("COMFYUI_TEMPLATE_IMPORT_FAIL", False) in actions


def test_import_unauthenticated_returns_401():
    app = _build_app(actor=None)
    with app.test_client() as c:
        rv = c.post(
            "/api/comfyui/templates/import",
            json={"preview_token": "tkn_x", "title": "x"},
        )
    assert rv.status_code == 401


def test_import_endpoint_skipped_without_preset_helpers():
    """If route ctx omits preset helpers, /import isn't registered (preview-only mode)."""
    app = Flask(__name__)
    register_comfyui_template_routes(app, {
        "request": flask_request,
        "actor_or_401": lambda: ({"id": 1}, None),
        "json_resp": lambda p: app.response_class(
            response=json.dumps(p), mimetype="application/json"
        ),
        "require_csrf": lambda f: f,
        "get_client_ip": lambda: "127.0.0.1",
        "get_ua": lambda: "test",
        "audit": lambda *a, **k: None,
        "comfyui_binding": lambda a: None,
        "client_for_url": lambda b: None,
        # NO get_db / upsert_workflow_preset / etc.
    })
    with app.test_client() as c:
        rv = c.post("/api/comfyui/templates/import", json={"preview_token": "tkn_x", "title": "x"})
    assert rv.status_code == 404
