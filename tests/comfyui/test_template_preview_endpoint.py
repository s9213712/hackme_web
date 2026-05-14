"""§8 preview endpoint regression — POST /api/comfyui/templates/preview."""

import io
import json

import pytest
from flask import Flask, request as flask_request

from routes.comfyui_sections.template_routes import register_comfyui_template_routes
from services.comfyui.template.capability import reset_object_info_cache
from services.comfyui.template.preview_store import (
    InMemoryPreviewStore,
)


@pytest.fixture(autouse=True)
def _isolate_object_info_cache():
    reset_object_info_cache()
    yield
    reset_object_info_cache()


# Reused minimal txt2img workflow.
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
        {
            "id": 39,
            "type": "Note",
            "inputs": [],
            "outputs": [],
            "widgets_values": ["skip me"],
        },
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


def _stub_client(*, classes, models=None, samplers=None):
    info = {cls: {"input": {"required": {}}} for cls in classes}
    if "CheckpointLoaderSimple" in info and models is not None:
        info["CheckpointLoaderSimple"]["input"]["required"]["ckpt_name"] = [list(models)]
    for class_type in ("KSampler", "KSamplerAdvanced"):
        if class_type in info:
            info[class_type]["input"]["required"]["sampler_name"] = [list(samplers or ["euler", "dpmpp_2m"])]
            info[class_type]["input"]["required"]["scheduler"] = [["normal", "karras"]]

    class _Stub:
        base_url = "http://stub"
        def get_object_info(self):
            return info
    return _Stub()


_SENTINEL = object()


def _build_app(*, actor=_SENTINEL, client=None, store=None):
    """Build a minimal Flask app with the template routes wired up."""
    app = Flask(__name__)

    if actor is _SENTINEL:
        actor = {"id": 1, "username": "alice"}
    actor_box = {"actor": actor}

    def _actor_or_401():
        if actor_box["actor"] is None:
            resp = app.response_class(
                response=json.dumps({"ok": False, "msg": "未登入"}, ensure_ascii=False),
                status=401,
                mimetype="application/json",
            )
            return None, resp
        return dict(actor_box["actor"]), None

    audit_log: list[dict] = []
    def _audit(action, ip, *, user="-", success=True, ua="", detail=""):
        audit_log.append({"action": action, "user": user, "success": success, "detail": detail})

    # `store or InMemoryPreviewStore()` would be wrong here too — see
    # template_routes.py for the empty-__len__ falsy gotcha.
    actual_store = store if store is not None else InMemoryPreviewStore()
    register_comfyui_template_routes(app, {
        "request": flask_request,
        "actor_or_401": _actor_or_401,
        "json_resp": lambda payload: app.response_class(
            response=json.dumps(payload, ensure_ascii=False),
            mimetype="application/json",
        ),
        "require_csrf": lambda f: f,  # tests skip CSRF
        "get_client_ip": lambda: "127.0.0.1",
        "get_ua": lambda: "test-agent",
        "audit": _audit,
        "comfyui_binding": lambda actor: "http://stub" if client is not None else None,
        "client_for_url": lambda binding: client,
        "preview_store": actual_store,
    })
    app.config.update({"actor_box": actor_box, "audit_log": audit_log})
    return app


def test_preview_returns_token_for_valid_workflow():
    store = InMemoryPreviewStore()
    client = _stub_client(
        classes={"CheckpointLoaderSimple", "EmptyLatentImage", "CLIPTextEncode", "KSampler", "VAEDecode", "SaveImage"},
        models=["v1-5.safetensors"],
    )
    app = _build_app(client=client, store=store)
    with app.test_client() as c:
        rv = c.post("/api/comfyui/templates/preview", json={"workflow": TXT2IMG})
    assert rv.status_code == 200
    body = rv.get_json()
    assert body["ok"] is True
    assert body["preview_token"].startswith("tkn_")
    assert body["capability"]["overall"] == "SUPPORTED"
    assert body["preview_token_ttl_seconds"] == 30 * 60
    # Token is in the store, owned by actor 1
    assert store.get(token=body["preview_token"], user_id=1) is not None


def test_preview_accepts_workflow_text_string():
    store = InMemoryPreviewStore()
    client = _stub_client(
        classes={"CheckpointLoaderSimple", "EmptyLatentImage", "CLIPTextEncode", "KSampler", "VAEDecode", "SaveImage"},
        models=["v1-5.safetensors"],
    )
    app = _build_app(client=client, store=store)
    with app.test_client() as c:
        rv = c.post(
            "/api/comfyui/templates/preview",
            json={"workflow_text": json.dumps(TXT2IMG)},
        )
    assert rv.status_code == 200


def test_preview_accepts_non_digit_string_node_ids():
    store = InMemoryPreviewStore()
    client = _stub_client(
        classes={"CheckpointLoaderSimple", "EmptyLatentImage", "CLIPTextEncode", "KSampler", "VAEDecode", "SaveImage"},
        models=["v1-5.safetensors"],
    )
    app = _build_app(client=client, store=store)
    with app.test_client() as c:
        rv = c.post("/api/comfyui/templates/preview", json={"workflow": TXT2IMG_NON_DIGIT_IDS})
    assert rv.status_code == 200
    assert rv.get_json()["ok"] is True


def test_preview_accepts_multipart_upload():
    store = InMemoryPreviewStore()
    client = _stub_client(
        classes={"CheckpointLoaderSimple", "EmptyLatentImage", "CLIPTextEncode", "KSampler", "VAEDecode", "SaveImage"},
        models=["v1-5.safetensors"],
    )
    app = _build_app(client=client, store=store)
    with app.test_client() as c:
        data = {
            "workflow": (
                io.BytesIO(json.dumps(TXT2IMG).encode("utf-8")),
                "workflow.json",
                "application/json",
            ),
        }
        rv = c.post("/api/comfyui/templates/preview", data=data, content_type="multipart/form-data")
    assert rv.status_code == 200
    assert rv.get_json()["ok"] is True


def test_preview_accepts_ui_graph_format_and_converts_to_api_workflow():
    store = InMemoryPreviewStore()
    app = _build_app(
        client=_stub_client(
            classes={"CheckpointLoaderSimple", "EmptyLatentImage", "CLIPTextEncode", "KSamplerAdvanced", "VAEDecode", "SaveImage"},
            models=["sd_xl_base_1.0.safetensors"],
        ),
        store=store,
    )
    with app.test_client() as c:
        rv = c.post("/api/comfyui/templates/preview", json={"workflow": UI_GRAPH_TXT2IMG_ADV})
    assert rv.status_code == 200
    body = rv.get_json()
    assert body["ok"] is True
    stored = store.get(token=body["preview_token"], user_id=1)
    assert stored is not None
    workflow = stored.payload["workflow"]
    assert workflow["6"]["class_type"] == "CLIPTextEncode"
    assert workflow["6"]["inputs"]["text"] == "a happy cat"
    assert workflow["7"]["inputs"]["text"] == "low quality"
    assert workflow["10"]["class_type"] == "KSamplerAdvanced"
    assert workflow["10"]["inputs"]["noise_seed"] == 123456789
    assert workflow["10"]["inputs"]["steps"] == 30
    assert workflow["10"]["inputs"]["cfg"] == 6.5
    assert workflow["10"]["inputs"]["sampler_name"] == "euler"
    assert workflow["10"]["inputs"]["return_with_leftover_noise"] == "disable"
    assert "39" not in workflow
    assert "50" not in workflow
    assert "51" not in workflow


def test_preview_rejects_explicitly_denied_class():
    store = InMemoryPreviewStore()
    app = _build_app(client=_stub_client(classes={"KSampler", "ReActorFaceSwap"}), store=store)
    bad = {**TXT2IMG, "10": {"class_type": "ReActorFaceSwap", "inputs": {"image": ["8", 0]}}}
    with app.test_client() as c:
        rv = c.post("/api/comfyui/templates/preview", json={"workflow": bad})
    assert rv.status_code == 400
    body = rv.get_json()
    assert body["stage"] == "allowlist"
    assert "ReActorFaceSwap" in body["denied_classes"]


def test_preview_unauthenticated_returns_401():
    app = _build_app(actor=None, store=InMemoryPreviewStore())
    with app.test_client() as c:
        rv = c.post("/api/comfyui/templates/preview", json={"workflow": TXT2IMG})
    assert rv.status_code == 401


def test_preview_capability_unsupported_when_client_missing():
    """No ComfyUI binding → capability=UNSUPPORTED, but preview still returns
    a token so the UI can render the analysis panels and tell the user to
    connect ComfyUI first."""
    store = InMemoryPreviewStore()
    app = _build_app(client=None, store=store)
    with app.test_client() as c:
        rv = c.post("/api/comfyui/templates/preview", json={"workflow": TXT2IMG})
    assert rv.status_code == 200
    body = rv.get_json()
    assert body["capability"]["overall"] == "UNSUPPORTED"
    assert any("ComfyUI" in b for b in body["capability"]["blockers"])


def test_preview_unparseable_json_string_returns_parse_error():
    store = InMemoryPreviewStore()
    app = _build_app(client=_stub_client(classes={"KSampler"}), store=store)
    with app.test_client() as c:
        rv = c.post(
            "/api/comfyui/templates/preview",
            json={"workflow_text": "not json"},
        )
    assert rv.status_code == 400
    body = rv.get_json()
    assert body["stage"] == "parse"


def test_preview_oversized_multipart_rejected():
    store = InMemoryPreviewStore()
    app = _build_app(client=_stub_client(classes={"KSampler"}), store=store)
    blob = b"{" + (b"x" * (260 * 1024)) + b"}"  # 260KB > WORKFLOW_MAX_JSON_BYTES
    data = {"workflow": (io.BytesIO(blob), "workflow.json", "application/json")}
    with app.test_client() as c:
        rv = c.post("/api/comfyui/templates/preview", data=data, content_type="multipart/form-data")
    assert rv.status_code == 400
    body = rv.get_json()
    assert body["stage"] == "parse"
    assert "上限" in body["msg"]


def test_preview_audits_pass_and_fail_paths():
    store = InMemoryPreviewStore()
    client = _stub_client(
        classes={"CheckpointLoaderSimple", "EmptyLatentImage", "CLIPTextEncode", "KSampler", "VAEDecode", "SaveImage"},
        models=["v1-5.safetensors"],
    )
    app = _build_app(client=client, store=store)
    with app.test_client() as c:
        c.post("/api/comfyui/templates/preview", json={"workflow": TXT2IMG})
        c.post("/api/comfyui/templates/preview", json={"workflow_text": "garbage"})
    log = app.config["audit_log"]
    actions = [(e["action"], e["success"]) for e in log]
    assert ("COMFYUI_TEMPLATE_PREVIEW_PASS", True) in actions
    assert ("COMFYUI_TEMPLATE_PREVIEW_FAIL", False) in actions
