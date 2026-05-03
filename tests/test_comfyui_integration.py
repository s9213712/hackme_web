import io
import json
import sqlite3
import time
from pathlib import Path

from flask import Flask, jsonify, make_response

from routes import comfyui as comfyui_routes
from routes.comfyui import register_comfyui_routes
from services.cloud_drive import ensure_cloud_drive_attachment_schema
from services.comfyui_client import ComfyUIClient, ComfyUIImage
from services.member_levels import ensure_member_level_rules_schema
from services.storage_albums import (
    create_album,
    create_storage_file_entry,
    create_storage_folder,
    ensure_output_album,
    ensure_storage_album_schema,
    move_storage_file,
)
from services.upload_security import create_uploaded_file_record
from services.upload_security import ensure_upload_security_schema, update_cloud_drive_security_policy


ROOT = Path(__file__).resolve().parents[1]


class FakeComfyUIClient:
    base_url = "http://fake-comfyui"
    last_timeout_seconds = None
    last_params = {}
    discarded = []
    interrupted = 0
    generated_count = 0

    def health_check(self, *, timeout=3):
        return {"ok": True, "system": {"os": "test"}}

    def get_models(self):
        return ["dream.safetensors", "photo.ckpt"]

    def get_loras(self):
        return ["detail.safetensors", "anime-style.safetensors"]

    def get_sampler_options(self):
        return {"samplers": ["euler", "dpmpp_2m"], "schedulers": ["normal", "karras"]}

    def generate_image(self, params, *, timeout_seconds=180, progress_callback=None):
        FakeComfyUIClient.generated_count += 1
        FakeComfyUIClient.last_timeout_seconds = timeout_seconds
        FakeComfyUIClient.last_params = dict(params)
        if progress_callback:
            progress_callback({
                "phase": "running",
                "percent": 50,
                "current": 10,
                "max": 20,
                "current_node": "3",
                "detail": "節點 3：10/20",
                "queue_remaining": 0,
            })
        batch_size = int(params.get("batch_size") or 1)
        images = []
        for index in range(batch_size):
            images.append({
                "image_ref": {"filename": f"hackme_web_{index + 1:05d}_.png", "subfolder": "", "type": "output"},
                "mime_type": "image/png",
                "data": f"fake-png-bytes-{index + 1}".encode("utf-8"),
            })
        return {
            "prompt_id": "prompt-1",
            "image_ref": images[0]["image_ref"],
            "mime_type": images[0]["mime_type"],
            "data": images[0]["data"],
            "images": images,
        }

    def fetch_image(self, image_ref):
        return ComfyUIImage(
            filename=image_ref.get("filename") or "hackme_web_00001_.png",
            subfolder=image_ref.get("subfolder") or "",
            type=image_ref.get("type") or "output",
            mime_type="image/png",
            data=b"fake-png-bytes",
        )

    def discard_image(self, image_ref, *, prompt_id=None, **kwargs):
        FakeComfyUIClient.discarded.append({"image_ref": dict(image_ref), "prompt_id": prompt_id, **kwargs})
        return {"file_deleted": True, "file_missing": False, "file_delete_supported": True, "history_deleted": bool(prompt_id)}

    def interrupt(self):
        FakeComfyUIClient.interrupted += 1
        return {"interrupted": True}


class FailingComfyUIClient(FakeComfyUIClient):
    def generate_image(self, params, *, timeout_seconds=180, progress_callback=None):
        from services.comfyui_client import ComfyUIError

        raise ComfyUIError("ComfyUI 產圖失敗")


class FakePointsService:
    def __init__(self, balance=100, fail_spend=False):
        self.balance = int(balance)
        self.fail_spend = fail_spend
        self.spends = []

    def list_catalog(self):
        return [{
            "item_key": "comfyui_txt2img_basic",
            "item_name": "基礎生圖一次",
            "category": "comfyui",
            "currency_type": "points",
            "base_price": 5,
            "enabled": 1,
            "metadata": {},
        }]

    def get_wallet(self, user_id):
        return {"user_id": user_id, "points_balance": self.balance}

    def spend_points(self, *, user_id, item_key, quantity=1, reference_type=None,
                     reference_id=None, idempotency_key=None, metadata=None, actor=None, override_amount=None):
        if self.fail_spend:
            raise ValueError("billing failed")
        amount = int(override_amount) if override_amount is not None else 5 * int(quantity or 1)
        if self.balance < amount:
            raise ValueError("insufficient balance")
        self.balance -= amount
        spend = {
            "user_id": user_id,
            "item_key": item_key,
            "quantity": int(quantity or 1),
            "reference_type": reference_type,
            "reference_id": reference_id,
            "metadata": metadata or {},
            "amount": amount,
        }
        self.spends.append(spend)
        return {
            "ok": True,
            "ledger": {"ledger_uuid": f"ledger-{len(self.spends)}", "amount": amount},
            "wallet": self.get_wallet(user_id),
            "item": {"base_price": 5},
        }


class _FakeHeaders(dict):
    def get_content_charset(self):
        return "utf-8"


class _FakeResponse:
    def __init__(self, *, url, body, headers=None, final_url=None):
        self._url = final_url or url
        self._buffer = io.BytesIO(body if isinstance(body, bytes) else body.encode("utf-8"))
        self.headers = _FakeHeaders(headers or {})

    def read(self, amt=-1):
        return self._buffer.read(amt)

    def geturl(self):
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def _json_resp(payload, status=200):
    return make_response(jsonify(payload), status)


def _passthrough(fn):
    return fn


def _actor():
    return {
        "id": 1,
        "username": "alice",
        "role": "user",
        "member_level": "trusted",
        "effective_level": "trusted",
        "sanction_status": "none",
    }


def _generate_preview(client):
    generated = client.post(
        "/api/comfyui/generate",
        json={
            "model": "dream.safetensors",
            "prompt": "a quiet test image",
            "width": 512,
            "height": 512,
            "steps": 12,
            "cfg": 6.5,
            "sampler_name": "euler",
            "scheduler": "normal",
            "seed": 123,
            "batch_size": 1,
            "confirm_billing": True,
        },
    )
    assert generated.status_code == 200
    return generated.get_json()["image"]


class OfflineComfyUIClient:
    base_url = "http://fake-offline"

    def health_check(self, *, timeout=3):
        from services.comfyui_client import ComfyUIError

        raise ComfyUIError("ComfyUI 連線失敗：refused")


class RecoveringComfyUIClient:
    def __init__(self, state):
        self.state = state
        self.base_url = "http://localhost:8192"

    def health_check(self, *, timeout=3):
        from services.comfyui_client import ComfyUIError

        if not self.state.get("ready"):
            raise ComfyUIError("ComfyUI 連線失敗：refused")
        return {"ok": True, "system": {"os": "test"}}


def _init_db(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            username TEXT NOT NULL,
            role TEXT NOT NULL
        );
        INSERT INTO users (id, username, role) VALUES (1, 'alice', 'user');
        """
    )
    ensure_member_level_rules_schema(conn)
    ensure_upload_security_schema(conn)
    ensure_cloud_drive_attachment_schema(conn)
    ensure_storage_album_schema(conn)
    update_cloud_drive_security_policy(conn, {"scanner_enabled": False})
    conn.commit()
    conn.close()


def _build_app(db_path, storage_root, settings=None, comfyui_client=None, actor=None, points_service=None, extra_deps=None):
    app = Flask(__name__)
    app.testing = True

    def get_db():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    deps = {
        "STORAGE_DIR": str(storage_root),
        "audit": lambda *args, **kwargs: None,
        "get_client_ip": lambda: "127.0.0.1",
        "get_current_user_ctx": actor or _actor,
        "get_db": get_db,
        "get_system_settings": lambda: {"feature_comfyui_enabled": True, **(settings or {})},
        "get_member_level_rule": lambda conn, level: {
            "can_upload_attachment": True,
            "attachment_quota_mb": 10,
            "max_attachment_size_mb": 10,
            "upload_rate_limit_per_day": 10,
        },
        "get_ua": lambda: "test-agent",
        "json_resp": _json_resp,
        "require_csrf": _passthrough,
        "require_csrf_safe": _passthrough,
        "comfyui_client": comfyui_client or FakeComfyUIClient(),
        "points_service": points_service or FakePointsService(),
    }
    if extra_deps:
        deps.update(extra_deps)
    register_comfyui_routes(app, deps)
    return app


def test_comfyui_models_and_generate_routes(tmp_path):
    db_path = tmp_path / "comfyui.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    client = _build_app(db_path, storage_root).test_client()

    models = client.get("/api/comfyui/models")
    assert models.status_code == 200
    assert models.get_json()["models"] == ["dream.safetensors", "photo.ckpt"]
    assert models.get_json()["loras"] == ["detail.safetensors", "anime-style.safetensors"]
    assert models.get_json()["max_batch_size"] == 1
    assert models.get_json()["default_width"] == 1024
    assert models.get_json()["default_height"] == 1024

    status = client.get("/api/comfyui/status")
    assert status.status_code == 200
    assert status.get_json()["available"] is True
    assert status.get_json()["max_batch_size"] == 1
    assert status.get_json()["default_width"] == 1024
    assert status.get_json()["default_height"] == 1024

    generated = client.post(
        "/api/comfyui/generate",
        json={
            "model": "dream.safetensors",
            "prompt": "a quiet test image",
            "width": 512,
            "height": 512,
            "steps": 12,
            "cfg": 6.5,
            "sampler_name": "euler",
            "scheduler": "normal",
            "seed": 123,
            "batch_size": 3,
            "loras": [{"name": "detail.safetensors", "strength_model": 0.8, "strength_clip": 0.7}],
            "confirm_billing": True,
        },
    )
    assert generated.status_code == 200
    body = generated.get_json()
    assert body["image"]["prompt_id"] == "prompt-1"
    assert body["image"]["data_url"].startswith("data:image/png;base64,")
    assert body["image"]["seed"] == 123
    assert body["image"]["batch_size"] == 1
    assert len(body["images"]) == 1
    assert body["images"][0]["image_ref"]["filename"] == "hackme_web_00001_.png"
    assert FakeComfyUIClient.last_timeout_seconds == 600
    assert FakeComfyUIClient.last_params["loras"] == [{"name": "detail.safetensors", "strength_model": 0.8, "strength_clip": 0.7}]


def test_comfyui_generate_async_job_reports_progress_and_result(tmp_path):
    db_path = tmp_path / "comfyui.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    client = _build_app(db_path, storage_root).test_client()

    started = client.post(
        "/api/comfyui/generate",
        json={
            "model": "dream.safetensors",
            "prompt": "a quiet test image",
            "width": 512,
            "height": 512,
            "steps": 12,
            "cfg": 6.5,
            "sampler_name": "euler",
            "scheduler": "normal",
            "seed": 123,
            "batch_size": 1,
            "confirm_billing": True,
            "async_progress": True,
        },
    )

    assert started.status_code == 200
    start_body = started.get_json()
    assert start_body["ok"] is True
    assert start_body["async"] is True
    job_id = start_body["job"]["job_id"]

    final_body = None
    for _ in range(40):
        polled = client.get(f"/api/comfyui/jobs/{job_id}")
        assert polled.status_code == 200
        final_body = polled.get_json()
        assert final_body["ok"] is True
        assert "percent" in (final_body["job"]["progress"] or {})
        if final_body["job"]["status"] == "completed":
            break
        time.sleep(0.05)

    assert final_body is not None
    assert final_body["job"]["status"] == "completed"
    assert final_body["job"]["progress"]["percent"] == 100
    assert final_body["job"]["result"]["image"]["image_ref"]["filename"] == "hackme_web_00001_.png"


def test_comfyui_batch_limit_is_root_configurable(tmp_path):
    db_path = tmp_path / "comfyui.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    points = FakePointsService(balance=100)
    client = _build_app(db_path, storage_root, settings={"comfyui_max_batch_size": 3}, points_service=points).test_client()

    generated = client.post(
        "/api/comfyui/generate",
        json={
            "model": "dream.safetensors",
            "prompt": "a quiet test image",
            "seed": 123,
            "batch_size": 3,
            "confirm_billing": True,
        },
    )
    assert generated.status_code == 200
    body = generated.get_json()
    assert body["image"]["batch_size"] == 3
    assert len(body["images"]) == 3
    assert body["images"][2]["image_ref"]["filename"] == "hackme_web_00003_.png"
    assert body["billing"]["charged"] is True
    assert body["billing"]["total_price"] == 15
    assert points.spends == [{
        "user_id": 1,
        "item_key": "comfyui_txt2img_basic",
        "quantity": 3,
        "reference_type": "comfyui_generation",
        "reference_id": "prompt-1",
        "metadata": {
            "charged_after_success": True,
            "unit_price": 5,
            "quantity": 3,
            "lora_count": 0,
            "lora_extra_unit_price": 1,
            "lora_extra_price": 0,
            "total_price": 15,
        },
        "amount": 15,
    }]


def test_comfyui_default_dimensions_are_root_configurable(tmp_path):
    db_path = tmp_path / "comfyui.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    client = _build_app(
        db_path,
        storage_root,
        settings={"comfyui_default_width": 768, "comfyui_default_height": 1024},
    ).test_client()

    models = client.get("/api/comfyui/models")
    status = client.get("/api/comfyui/status")
    generated = client.post(
        "/api/comfyui/generate",
        json={"model": "dream.safetensors", "prompt": "use configured size", "seed": 123, "confirm_billing": True},
    )

    assert models.get_json()["default_width"] == 768
    assert models.get_json()["default_height"] == 1024
    assert status.get_json()["default_width"] == 768
    assert status.get_json()["default_height"] == 1024
    assert generated.status_code == 200
    assert FakeComfyUIClient.last_params["width"] == 768
    assert FakeComfyUIClient.last_params["height"] == 1024


def test_comfyui_generation_failure_does_not_charge_points(tmp_path):
    db_path = tmp_path / "comfyui.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    points = FakePointsService(balance=100)
    client = _build_app(db_path, storage_root, comfyui_client=FailingComfyUIClient(), points_service=points).test_client()

    generated = client.post(
        "/api/comfyui/generate",
        json={"model": "dream.safetensors", "prompt": "this will fail", "seed": 123, "confirm_billing": True},
    )

    assert generated.status_code == 503
    assert points.spends == []
    assert points.balance == 100


def test_comfyui_generation_rejects_when_points_are_insufficient_before_work(tmp_path):
    db_path = tmp_path / "comfyui.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    points = FakePointsService(balance=4)
    client = _build_app(db_path, storage_root, points_service=points).test_client()

    generated = client.post(
        "/api/comfyui/generate",
        json={"model": "dream.safetensors", "prompt": "too expensive", "seed": 123},
    )

    assert generated.status_code == 409
    assert "積分不足" in generated.get_json()["msg"]
    assert points.spends == []


def test_comfyui_billing_quote_rejects_total_run_cost_before_work(tmp_path):
    db_path = tmp_path / "comfyui.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    points = FakePointsService(balance=45)
    FakeComfyUIClient.generated_count = 0
    client = _build_app(db_path, storage_root, points_service=points).test_client()

    quoted = client.post(
        "/api/comfyui/billing-quote",
        json={
            "model": "dream.safetensors",
            "prompt": "ten images",
            "seed": 123,
            "batch_size": 1,
            "run_count": 10,
        },
    )

    body = quoted.get_json()
    assert quoted.status_code == 409
    assert "積分不足" in body["msg"]
    assert body["billing"]["quantity"] == 10
    assert body["billing"]["total_price"] == 50
    assert body["billing"]["run_count"] == 10
    assert points.spends == []
    assert FakeComfyUIClient.generated_count == 0


def test_comfyui_lora_billing_quote_adds_one_point_per_lora_per_image(tmp_path):
    db_path = tmp_path / "comfyui.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    points = FakePointsService(balance=100)
    client = _build_app(db_path, storage_root, points_service=points).test_client()

    quoted = client.post(
        "/api/comfyui/billing-quote",
        json={
            "model": "dream.safetensors",
            "prompt": "lora quote",
            "seed": 123,
            "batch_size": 1,
            "run_count": 2,
            "loras": [{"name": "detail.safetensors"}, {"name": "anime-style.safetensors"}],
        },
    )

    assert quoted.status_code == 200
    billing = quoted.get_json()["billing"]
    assert billing["quantity"] == 2
    assert billing["lora_count"] == 2
    assert billing["base_price_total"] == 10
    assert billing["lora_extra_price"] == 4
    assert billing["total_price"] == 14


def test_comfyui_generation_requires_billing_confirmation_for_non_root(tmp_path):
    db_path = tmp_path / "comfyui.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    points = FakePointsService(balance=100)
    FakeComfyUIClient.generated_count = 0
    client = _build_app(db_path, storage_root, points_service=points).test_client()

    generated = client.post(
        "/api/comfyui/generate",
        json={"model": "dream.safetensors", "prompt": "needs confirmation", "seed": 123},
    )

    body = generated.get_json()
    assert generated.status_code == 409
    assert body["ok"] is False
    assert "請先確認扣點" in body["msg"]
    assert body["billing"]["confirmation_required"] is True
    assert points.spends == []
    assert points.balance == 100
    assert FakeComfyUIClient.generated_count == 0


def test_comfyui_generation_does_not_charge_root(tmp_path):
    db_path = tmp_path / "comfyui.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    points = FakePointsService(balance=0)
    root_actor = {
        "id": 1,
        "username": "root",
        "role": "super_admin",
        "member_level": "trusted",
        "effective_level": "trusted",
        "sanction_status": "none",
    }
    client = _build_app(db_path, storage_root, actor=lambda: root_actor, points_service=points).test_client()

    generated = client.post(
        "/api/comfyui/generate",
        json={"model": "dream.safetensors", "prompt": "root free", "seed": 123},
    )

    assert generated.status_code == 200
    body = generated.get_json()
    assert body["billing"] == {"charged": False, "exempt": "root"}
    assert points.spends == []


def test_comfyui_workflow_uses_requested_batch_size():
    workflow = ComfyUIClient("http://fake-comfyui").build_text_to_image_workflow({
        "model": "dream.safetensors",
        "prompt": "batch test",
        "negative_prompt": "",
        "width": 512,
        "height": 512,
        "steps": 12,
        "cfg": 6.5,
        "sampler_name": "euler",
        "scheduler": "normal",
        "seed": 123,
        "batch_size": 4,
        "filename_prefix": "hackme_web",
    })

    assert workflow["5"]["inputs"]["batch_size"] == 4


def test_comfyui_workflow_chains_loras_between_checkpoint_and_sampler():
    workflow = ComfyUIClient("http://fake-comfyui").build_text_to_image_workflow({
        "model": "dream.safetensors",
        "prompt": "lora test",
        "negative_prompt": "",
        "width": 512,
        "height": 512,
        "steps": 12,
        "cfg": 6.5,
        "sampler_name": "euler",
        "scheduler": "normal",
        "seed": 123,
        "batch_size": 1,
        "filename_prefix": "hackme_web",
        "loras": [
            {"name": "detail.safetensors", "strength_model": 0.8, "strength_clip": 0.7},
            {"name": "anime-style.safetensors", "strength_model": 1.0, "strength_clip": 1.0},
        ],
    })

    assert workflow["10"]["class_type"] == "LoraLoader"
    assert workflow["10"]["inputs"]["model"] == ["4", 0]
    assert workflow["10"]["inputs"]["clip"] == ["4", 1]
    assert workflow["10"]["inputs"]["lora_name"] == "detail.safetensors"
    assert workflow["11"]["inputs"]["model"] == ["10", 0]
    assert workflow["11"]["inputs"]["clip"] == ["10", 1]
    assert workflow["3"]["inputs"]["model"] == ["11", 0]
    assert workflow["6"]["inputs"]["clip"] == ["11", 1]
    assert workflow["7"]["inputs"]["clip"] == ["11", 1]


def test_comfyui_status_reports_offline_backend(tmp_path):
    db_path = tmp_path / "comfyui.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    app = Flask(__name__)
    app.testing = True

    def get_db():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    register_comfyui_routes(app, {
        "STORAGE_DIR": str(storage_root),
        "audit": lambda *args, **kwargs: None,
        "get_client_ip": lambda: "127.0.0.1",
        "get_current_user_ctx": _actor,
        "get_db": get_db,
        "get_system_settings": lambda: {"feature_comfyui_enabled": True},
        "get_member_level_rule": lambda conn, level: {},
        "get_ua": lambda: "test-agent",
        "json_resp": _json_resp,
        "require_csrf": _passthrough,
        "require_csrf_safe": _passthrough,
        "comfyui_client": OfflineComfyUIClient(),
    })

    status = app.test_client().get("/api/comfyui/status")
    assert status.status_code == 200
    body = status.get_json()
    assert body["ok"] is True
    assert body["available"] is False
    assert body["comfyui_url"] == "http://fake-offline"


def test_root_can_test_unsaved_comfyui_endpoint(tmp_path):
    db_path = tmp_path / "comfyui.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    root_actor = {"id": 1, "username": "root", "role": "super_admin"}
    client = _build_app(db_path, storage_root, actor=lambda: root_actor).test_client()

    tested = client.post("/api/root/comfyui/test-connection", json={"host": "192.168.1.20", "port": 8192})

    assert tested.status_code == 200
    body = tested.get_json()
    assert body["ok"] is True
    assert body["available"] is True
    assert body["endpoint"] == {"mode": "remote", "host": "192.168.1.20", "port": 8192}


def test_local_comfyui_start_reuses_existing_backend(tmp_path):
    db_path = tmp_path / "comfyui.db"
    storage_root = tmp_path / "storage"
    comfy_base = tmp_path / "ComfyUI_windows_portable"
    storage_root.mkdir()
    comfy_base.mkdir()
    (comfy_base / "run_in_linux.sh").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    _init_db(db_path)
    client = _build_app(
        db_path,
        storage_root,
        settings={
            "comfyui_connection_mode": "local",
            "comfyui_base_dir": str(comfy_base),
            "comfyui_local_start_script": "run_in_linux.sh",
        },
    ).test_client()

    started = client.post("/api/comfyui/start", json={})

    assert started.status_code == 200
    body = started.get_json()
    assert body["ok"] is True
    assert body["connection_mode"] == "local"
    assert body["start"]["already_running"] is True


def test_local_comfyui_status_reports_starting_when_process_alive(tmp_path, monkeypatch):
    db_path = tmp_path / "comfyui.db"
    storage_root = tmp_path / "storage"
    comfy_base = tmp_path / "ComfyUI_windows_portable"
    storage_root.mkdir()
    comfy_base.mkdir()
    _init_db(db_path)
    temp_root = tmp_path / "tmp-runtime"
    temp_root.mkdir()
    port = 8192
    log_path = temp_root / "comfy-start.log"
    log_path.write_text(
        "Starting server\nTo see the GUI go to: http://0.0.0.0:8192\nFETCH ComfyRegistry Data: 40/143\n",
        encoding="utf-8",
    )
    state_file = temp_root / f"hackme_web_comfyui_local_{port}.json"
    state_file.write_text(
        '{"pid": 4321, "pgid": 4321, "port": 8192, "base_dir": "%s", "script": "run_in_linux.sh", "log_path": "%s"}'
        % (str(comfy_base), str(log_path)),
        encoding="utf-8",
    )
    monkeypatch.setattr("routes.comfyui.tempfile.gettempdir", lambda: str(temp_root))

    def fake_kill(pid, sig):
        if int(pid) == 4321 and sig == 0:
            return None
        raise ProcessLookupError()

    monkeypatch.setattr("routes.comfyui.os.kill", fake_kill)
    client = _build_app(
        db_path,
        storage_root,
        settings={
            "comfyui_connection_mode": "local",
            "comfyui_base_dir": str(comfy_base),
            "comfyui_api_host": "localhost",
            "comfyui_api_port": port,
        },
        extra_deps={
            "comfyui_client": None,
            "comfyui_client_factory": lambda url: OfflineComfyUIClient(),
        },
    ).test_client()

    status = client.get("/api/comfyui/status")

    assert status.status_code == 200
    body = status.get_json()
    assert body["ok"] is True
    assert body["available"] is False
    assert body["starting"] is True
    assert "正在載入自訂節點 / Registry" in body["msg"]
    assert body["startup_log_tail"][-1] == "FETCH ComfyRegistry Data: 40/143"


def test_comfyui_connection_test_requires_root_and_valid_endpoint(tmp_path):
    db_path = tmp_path / "comfyui.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    user_client = _build_app(db_path, storage_root).test_client()

    forbidden = user_client.post("/api/root/comfyui/test-connection", json={"host": "localhost", "port": 8192})
    assert forbidden.status_code == 403

    root_actor = {"id": 1, "username": "root", "role": "super_admin"}
    root_client = _build_app(db_path, storage_root, actor=lambda: root_actor).test_client()
    invalid = root_client.post("/api/root/comfyui/test-connection", json={"host": "http://127.0.0.1/path", "port": 8192})
    assert invalid.status_code == 400
    assert "Host" in invalid.get_json()["msg"]


def test_local_comfyui_connection_test_attempts_autostart(tmp_path, monkeypatch):
    db_path = tmp_path / "comfyui.db"
    storage_root = tmp_path / "storage"
    comfy_base = tmp_path / "ComfyUI_windows_portable"
    storage_root.mkdir()
    comfy_base.mkdir()
    (comfy_base / "run_in_linux.sh").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    _init_db(db_path)
    state = {"ready": False}

    class DummyPopen:
        def __init__(self, *args, **kwargs):
            self.pid = 4321
            state["ready"] = True

        def poll(self):
            return None

    class DummyRunResult:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr("routes.comfyui.subprocess.run", lambda *args, **kwargs: DummyRunResult())
    monkeypatch.setattr("routes.comfyui.subprocess.Popen", DummyPopen)
    root_actor = {"id": 1, "username": "root", "role": "super_admin"}
    client = _build_app(
        db_path,
        storage_root,
        settings={
            "comfyui_connection_mode": "local",
            "comfyui_base_dir": str(comfy_base),
            "comfyui_local_start_script": "run_in_linux.sh",
            "comfyui_api_host": "localhost",
            "comfyui_api_port": 8192,
        },
        actor=lambda: root_actor,
        extra_deps={
            "comfyui_client": None,
            "comfyui_client_factory": lambda url: RecoveringComfyUIClient(state),
        },
    ).test_client()

    tested = client.post(
        "/api/root/comfyui/test-connection",
        json={
            "mode": "local",
            "host": "localhost",
            "port": 8192,
            "base_dir": str(comfy_base),
            "local_start_script": "run_in_linux.sh",
        },
    )

    assert tested.status_code == 200
    body = tested.get_json()
    assert body["ok"] is True
    assert body["available"] is True
    assert body["autostart"]["attempted"] is True
    assert body["autostart"]["start"]["started"] is True


def test_local_comfyui_connection_test_reports_startup_failure_detail(tmp_path, monkeypatch):
    db_path = tmp_path / "comfyui.db"
    storage_root = tmp_path / "storage"
    comfy_base = tmp_path / "ComfyUI_windows_portable"
    storage_root.mkdir()
    comfy_base.mkdir()
    (comfy_base / "run_in_linux.sh").write_text("#!/usr/bin/env bash\necho boot failed >&2\nexit 3\n", encoding="utf-8")
    _init_db(db_path)

    class DummyPopen:
        def __init__(self, *args, **kwargs):
            self.pid = 4321
            self._returncode = 3

        def poll(self):
            return self._returncode

    class DummyRunResult:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr("routes.comfyui.subprocess.run", lambda *args, **kwargs: DummyRunResult())
    monkeypatch.setattr("routes.comfyui.subprocess.Popen", DummyPopen)
    monkeypatch.setattr("routes.comfyui.time.sleep", lambda *_args, **_kwargs: None)
    root_actor = {"id": 1, "username": "root", "role": "super_admin"}
    client = _build_app(
        db_path,
        storage_root,
        settings={
            "comfyui_connection_mode": "local",
            "comfyui_base_dir": str(comfy_base),
            "comfyui_local_start_script": "run_in_linux.sh",
            "comfyui_api_host": "localhost",
            "comfyui_api_port": 8192,
        },
        actor=lambda: root_actor,
        extra_deps={
            "comfyui_client": None,
            "comfyui_client_factory": lambda url: OfflineComfyUIClient(),
        },
    ).test_client()

    tested = client.post(
        "/api/root/comfyui/test-connection",
        json={
            "mode": "local",
            "host": "localhost",
            "port": 8192,
            "base_dir": str(comfy_base),
            "local_start_script": "run_in_linux.sh",
        },
    )

    assert tested.status_code == 200
    body = tested.get_json()
    assert body["ok"] is True
    assert body["available"] is False
    assert body["autostart"]["attempted"] is True
    assert "exit 3" in body["autostart"]["message"]


def test_root_can_stop_local_comfyui_with_tracked_pid(tmp_path, monkeypatch):
    db_path = tmp_path / "comfyui.db"
    storage_root = tmp_path / "storage"
    comfy_base = tmp_path / "ComfyUI_windows_portable"
    storage_root.mkdir()
    comfy_base.mkdir()
    _init_db(db_path)
    state = {"ready": True}
    temp_root = tmp_path / "tmp-runtime"
    temp_root.mkdir()
    port = 8192
    state_file = temp_root / f"hackme_web_comfyui_local_{port}.json"
    state_file.write_text(
        '{"pid": 4321, "pgid": 4321, "port": 8192, "base_dir": "%s", "script": "run_in_linux.sh"}' % str(comfy_base),
        encoding="utf-8",
    )
    monkeypatch.setattr("routes.comfyui.tempfile.gettempdir", lambda: str(temp_root))
    monkeypatch.setattr("routes.comfyui.time.sleep", lambda *_args, **_kwargs: None)

    def fake_killpg(pgid, sig):
        assert pgid == 4321
        state["ready"] = False

    def fake_kill(pid, sig):
        if int(pid) != 4321:
            raise ProcessLookupError()
        if sig == 0:
            if state["ready"]:
                return None
            raise ProcessLookupError()
        return None

    monkeypatch.setattr("routes.comfyui.os.killpg", fake_killpg)
    monkeypatch.setattr("routes.comfyui.os.kill", fake_kill)

    root_actor = {"id": 1, "username": "root", "role": "super_admin"}
    client = _build_app(
        db_path,
        storage_root,
        settings={
            "comfyui_connection_mode": "local",
            "comfyui_base_dir": str(comfy_base),
            "comfyui_local_start_script": "run_in_linux.sh",
            "comfyui_api_host": "localhost",
            "comfyui_api_port": port,
        },
        actor=lambda: root_actor,
        extra_deps={
            "comfyui_client": None,
            "comfyui_client_factory": lambda url: RecoveringComfyUIClient(state),
        },
    ).test_client()

    stopped = client.post("/api/root/comfyui/stop", json={})

    assert stopped.status_code == 200
    body = stopped.get_json()
    assert body["ok"] is True
    assert body["stop"]["stopped"] is True
    assert body["stop"]["killed_pids"] == [4321]
    assert not state_file.exists()


def test_root_comfyui_stop_requires_root(tmp_path):
    db_path = tmp_path / "comfyui.db"
    storage_root = tmp_path / "storage"
    comfy_base = tmp_path / "ComfyUI_windows_portable"
    storage_root.mkdir()
    comfy_base.mkdir()
    _init_db(db_path)
    client = _build_app(
        db_path,
        storage_root,
        settings={
            "comfyui_connection_mode": "local",
            "comfyui_base_dir": str(comfy_base),
            "comfyui_api_host": "localhost",
            "comfyui_api_port": 8192,
        },
    ).test_client()

    response = client.post("/api/root/comfyui/stop", json={})

    assert response.status_code == 403


def test_comfyui_civitai_inspect_requires_root_and_civitai_url(tmp_path):
    db_path = tmp_path / "comfyui.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    user_client = _build_app(db_path, storage_root).test_client()

    forbidden = user_client.post("/api/root/comfyui/civitai/inspect", json={"page_url": "https://civitai.com/models/123/a"})
    assert forbidden.status_code == 403

    root_actor = {"id": 1, "username": "root", "role": "super_admin"}
    root_client = _build_app(db_path, storage_root, actor=lambda: root_actor).test_client()
    invalid = root_client.post(
        "/api/root/comfyui/civitai/inspect",
        json={"page_url": "http://127.0.0.1/models/123456/local"},
    )
    assert invalid.status_code == 400
    assert "Civitai" in invalid.get_json()["msg"]


def test_comfyui_civitai_red_url_is_accepted(tmp_path, monkeypatch):
    db_path = tmp_path / "comfyui.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    root_actor = {"id": 1, "username": "root", "role": "super_admin"}
    client = _build_app(
        db_path,
        storage_root,
        actor=lambda: root_actor,
        settings={"comfyui_civitai_api_key": "secret-token"},
    ).test_client()

    def fake_urlopen(request_obj, timeout=0):
        url = request_obj.full_url
        if url == "https://civitai.com/api/v1/models/376130":
            payload = {
                "id": 376130,
                "name": "novaAnimeIL_V18",
                "type": "Checkpoint",
                "creator": {"username": "demo"},
                "modelVersions": [
                    {
                        "id": 2837020,
                        "name": "v18",
                        "downloadUrl": "https://civitai.com/api/download/models/2837020",
                        "files": [
                            {
                                "id": 5001,
                                "name": "novaAnimeIL_V18.safetensors",
                                "sizeKB": 1024,
                                "downloadUrl": "https://civitai.com/api/download/models/2837020",
                            }
                        ],
                    }
                ],
            }
            return _FakeResponse(url=url, body=json.dumps(payload), headers={"Content-Type": "application/json; charset=utf-8"})
        raise AssertionError(f"unexpected urlopen target: {url}")

    monkeypatch.setattr(comfyui_routes.urllib.request, "urlopen", fake_urlopen)
    inspected = client.post(
        "/api/root/comfyui/civitai/inspect",
        json={"page_url": "https://civitai.red/models/376130?modelVersionId=2837020"},
    )

    assert inspected.status_code == 200
    body = inspected.get_json()
    assert body["model"]["model_id"] == 376130
    assert body["model"]["selected_version_id"] == 2837020


def test_comfyui_civitai_inspect_and_download_flow(tmp_path, monkeypatch):
    db_path = tmp_path / "comfyui.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    comfy_base = tmp_path / "comfyui_portable"
    comfy_base.mkdir()
    (comfy_base / "main.py").write_text("# comfy", encoding="utf-8")
    root_actor = {"id": 1, "username": "root", "role": "super_admin"}
    client = _build_app(
        db_path,
        storage_root,
        actor=lambda: root_actor,
        settings={
            "comfyui_civitai_api_key": "secret-token",
            "comfyui_base_dir": str(comfy_base),
        },
    ).test_client()

    def fake_urlopen(request_obj, timeout=0):
        url = request_obj.full_url
        headers = dict(request_obj.header_items())
        if url == "https://civitai.com/api/v1/models/123456":
            assert headers.get("Authorization") == "Bearer secret-token"
            payload = {
                "id": 123456,
                "name": "Fancy Model",
                "type": "LORA",
                "creator": {"username": "artist"},
                "modelVersions": [
                    {
                        "id": 2001,
                        "name": "v1",
                        "baseModel": "SDXL",
                        "downloadUrl": "https://civitai.com/api/download/models/2001",
                        "files": [
                            {
                                "id": 3001,
                                "name": "fancy_v1.safetensors",
                                "sizeKB": 2048,
                                "downloadUrl": "https://civitai.com/api/download/models/2001",
                                "type": "Model",
                            }
                        ],
                    },
                    {
                        "id": 2002,
                        "name": "v2",
                        "baseModel": "SDXL",
                        "downloadUrl": "https://civitai.com/api/download/models/2002",
                        "files": [
                            {
                                "id": 3002,
                                "name": "fancy_v2.safetensors",
                                "sizeKB": 4096,
                                "downloadUrl": "https://civitai.com/api/download/models/2002",
                                "type": "Model",
                            }
                        ],
                    },
                ],
            }
            return _FakeResponse(url=url, body=json.dumps(payload), headers={"Content-Type": "application/json; charset=utf-8"})
        if url.startswith("https://civitai.com/api/download/models/2002"):
            assert "token=secret-token" in url
            return _FakeResponse(
                url=url,
                body=b"fake-model-bytes",
                headers={"Content-Disposition": 'attachment; filename="fancy_v2.safetensors"'},
            )
        raise AssertionError(f"unexpected urlopen target: {url}")

    monkeypatch.setattr(comfyui_routes.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(
        comfyui_routes.socket,
        "getaddrinfo",
        lambda host, port, type=0: [(None, None, None, None, ("104.21.72.187", port or 443))],
    )

    inspected = client.post(
        "/api/root/comfyui/civitai/inspect",
        json={"page_url": "https://civitai.com/models/123456/fancy-model?modelVersionId=2002"},
    )
    assert inspected.status_code == 200
    inspected_json = inspected.get_json()
    assert inspected_json["model"]["name"] == "Fancy Model"
    assert inspected_json["model"]["selected_version_id"] == 2002
    assert inspected_json["model"]["suggested_model_type"] == "lora"
    assert inspected_json["model"]["versions"][1]["files"][0]["id"] == 3002

    downloaded = client.post(
        "/api/root/comfyui/civitai/download",
        json={
            "page_url": "https://civitai.com/models/123456/fancy-model?modelVersionId=2002",
            "version_id": 2002,
            "file_id": 3002,
            "type": "lora",
            "base_dir": str(comfy_base),
        },
    )
    assert downloaded.status_code == 200
    downloaded_json = downloaded.get_json()
    assert downloaded_json["download"]["filename"] == "fancy_v2.safetensors"
    assert downloaded_json["download"]["civitai"]["version_id"] == 2002
    assert (comfy_base / "models" / "loras" / "fancy_v2.safetensors").exists()


def test_comfyui_legacy_direct_download_is_disabled(tmp_path):
    db_path = tmp_path / "comfyui.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    root_actor = {"id": 1, "username": "root", "role": "super_admin"}
    client = _build_app(db_path, storage_root, actor=lambda: root_actor).test_client()

    response = client.post(
        "/api/root/comfyui/download-model",
        json={"url": "https://example.com/a.safetensors", "type": "lora"},
    )

    assert response.status_code == 410
    assert "Civitai" in response.get_json()["msg"]


def test_comfyui_save_stores_generated_image_in_user_storage(tmp_path):
    db_path = tmp_path / "comfyui.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    client = _build_app(db_path, storage_root).test_client()
    preview = _generate_preview(client)

    saved = client.post(
        "/api/comfyui/save",
        json={
            "image_ref": preview["image_ref"],
            "virtual_path": "/ComfyUI/smoke.png",
        },
    )

    assert saved.status_code == 200
    body = saved.get_json()
    assert body["storage_file"]["virtual_path"] == "/ComfyUI/smoke.png"
    assert body["file"]["file_id"]

    stored_path = storage_root / "users" / "1" / body["file"]["file_id"]
    assert not stored_path.exists()
    assert list(storage_root.glob("users/1/*/hackme_web_00001_.png"))


def test_comfyui_image_ref_is_bound_to_generating_user(tmp_path):
    db_path = tmp_path / "comfyui.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    alice_client = _build_app(db_path, storage_root).test_client()
    preview = _generate_preview(alice_client)
    bob_actor = {
        "id": 2,
        "username": "bob",
        "role": "user",
        "member_level": "trusted",
        "effective_level": "trusted",
        "sanction_status": "none",
    }
    bob_client = _build_app(db_path, storage_root, actor=lambda: bob_actor).test_client()

    stolen = bob_client.post(
        "/api/comfyui/save",
        json={"image_ref": preview["image_ref"], "virtual_path": "/ComfyUI/stolen.png"},
    )

    assert stolen.status_code == 404
    assert "找不到" in stolen.get_json()["msg"]


def test_comfyui_save_defaults_to_output_folder_and_album(tmp_path):
    db_path = tmp_path / "comfyui.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    client = _build_app(db_path, storage_root).test_client()
    preview = _generate_preview(client)

    saved = client.post(
        "/api/comfyui/save",
        json={
            "image_ref": preview["image_ref"],
        },
    )

    assert saved.status_code == 200
    body = saved.get_json()
    assert body["storage_file"]["virtual_path"] == "/output/hackme_web_00001_.png"
    assert body["album"]["title"] == "output"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    folder = conn.execute(
        "SELECT * FROM storage_folders WHERE owner_user_id=1 AND virtual_path='/output' AND deleted_at IS NULL"
    ).fetchone()
    album_file = conn.execute(
        "SELECT * FROM album_files WHERE album_id=? AND file_id=? AND deleted_at IS NULL",
        (body["album"]["id"], body["file"]["file_id"]),
    ).fetchone()
    conn.close()
    assert folder is not None
    assert album_file["storage_file_id"] == body["storage_file"]["id"]


def test_output_album_syncs_files_moved_into_output_folder(tmp_path):
    db_path = tmp_path / "comfyui.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    actor = _actor()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        create_storage_folder(conn, actor=actor, path="/output")
        upload = create_uploaded_file_record(
            conn,
            owner_user_id=actor["id"],
            storage_path="users/1/manual/external.png",
            privacy_mode="standard_plain",
            size_bytes=12,
            original_filename="external.png",
            mime_type="image/png",
            user=actor,
        )
        file_row = conn.execute("SELECT * FROM uploaded_files WHERE id=?", (upload["file_id"],)).fetchone()
        storage_file, msg = create_storage_file_entry(
            conn,
            actor=actor,
            file_row=file_row,
            virtual_path="/imports/external.png",
            display_name="external.png",
            source="test",
        )
        assert msg is None

        moved, msg = move_storage_file(conn, actor=actor, storage_file_id=storage_file["id"], new_virtual_path="/output")
        assert msg is None
        album, msg = ensure_output_album(conn, actor=actor)

        assert msg is None
        assert moved["virtual_path"] == "/output/external.png"
        assert album["title"] == "output"
        assert [file["virtual_path"] for file in album["files"]] == ["/output/external.png"]
    finally:
        conn.close()


def test_output_album_repairs_file_record_stored_at_output_path(tmp_path):
    db_path = tmp_path / "comfyui.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    actor = _actor()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        upload = create_uploaded_file_record(
            conn,
            owner_user_id=actor["id"],
            storage_path="users/1/manual/external.png",
            privacy_mode="standard_plain",
            size_bytes=12,
            original_filename="external.png",
            mime_type="image/png",
            user=actor,
        )
        file_row = conn.execute("SELECT * FROM uploaded_files WHERE id=?", (upload["file_id"],)).fetchone()
        storage_file, msg = create_storage_file_entry(
            conn,
            actor=actor,
            file_row=file_row,
            virtual_path="/output",
            display_name="output",
            source="test",
        )
        assert msg is None

        album, msg = ensure_output_album(conn, actor=actor)
        repaired = conn.execute("SELECT * FROM storage_files WHERE id=?", (storage_file["id"],)).fetchone()
        folder = conn.execute(
            "SELECT * FROM storage_folders WHERE owner_user_id=1 AND virtual_path='/output' AND deleted_at IS NULL"
        ).fetchone()

        assert msg is None
        assert folder is not None
        assert repaired["virtual_path"] == "/output/external.png"
        assert [file["virtual_path"] for file in album["files"]] == ["/output/external.png"]
    finally:
        conn.close()


def test_output_album_prunes_files_moved_out_of_output_folder(tmp_path):
    db_path = tmp_path / "comfyui.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    client = _build_app(db_path, storage_root).test_client()
    preview = _generate_preview(client)

    saved = client.post(
        "/api/comfyui/save",
        json={
            "image_ref": preview["image_ref"],
        },
    )
    assert saved.status_code == 200
    body = saved.get_json()

    actor = _actor()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        moved, msg = move_storage_file(
            conn,
            actor=actor,
            storage_file_id=body["storage_file"]["id"],
            new_virtual_path="/imports/hackme_web_00001_.png",
        )
        assert msg is None
        album, msg = ensure_output_album(conn, actor=actor)

        assert moved["virtual_path"] == "/imports/hackme_web_00001_.png"
        assert msg is None
        assert album["files"] == []
        assert album["removed_count"] == 1
    finally:
        conn.close()


def test_comfyui_discard_deletes_original_comfyui_file_in_local_mode(tmp_path):
    FakeComfyUIClient.discarded = []
    db_path = tmp_path / "comfyui.db"
    storage_root = tmp_path / "storage"
    comfy_base = tmp_path / "ComfyUI"
    storage_root.mkdir()
    (comfy_base / "output").mkdir(parents=True)
    _init_db(db_path)
    client = _build_app(
        db_path,
        storage_root,
        settings={"comfyui_connection_mode": "local", "comfyui_base_dir": str(comfy_base)},
    ).test_client()
    preview = _generate_preview(client)

    discarded = client.post(
        "/api/comfyui/discard",
        json={
            "image_ref": preview["image_ref"],
            "prompt_id": preview["prompt_id"],
        },
    )

    assert discarded.status_code == 200
    body = discarded.get_json()
    assert body["discard"]["file_deleted"] is True
    assert body["discard"]["history_deleted"] is True
    assert FakeComfyUIClient.discarded == [{
        "image_ref": {"filename": "hackme_web_00001_.png", "subfolder": "", "type": "output"},
        "prompt_id": "prompt-1",
        "local_base_dir": str(comfy_base),
        "allow_api_delete": False,
    }]


def test_comfyui_discard_remote_mode_clears_preview_without_deleting_source(tmp_path):
    FakeComfyUIClient.discarded = []
    db_path = tmp_path / "comfyui.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    client = _build_app(db_path, storage_root, settings={"comfyui_connection_mode": "remote"}).test_client()
    preview = _generate_preview(client)

    discarded = client.post(
        "/api/comfyui/discard",
        json={
            "image_ref": preview["image_ref"],
            "prompt_id": preview["prompt_id"],
        },
    )

    assert discarded.status_code == 200
    body = discarded.get_json()
    assert body["ok"] is True
    assert body["warning"] == "source_file_not_deleted"
    assert body["discard"]["file_delete_supported"] is False
    assert FakeComfyUIClient.discarded == []


def test_comfyui_discard_tolerates_plain_text_history_response(tmp_path, monkeypatch):
    output_dir = tmp_path / "comfy-output"
    output_dir.mkdir()
    image_path = output_dir / "plain-history.png"
    image_path.write_bytes(b"fake-png")
    monkeypatch.setenv("COMFYUI_OUTPUT_DIR", str(output_dir))
    calls = []

    class PlainTextResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b"OK"

    def fake_urlopen(req, timeout=None):
        calls.append(req.full_url)
        return PlainTextResponse()

    monkeypatch.setattr("services.comfyui_client.urllib.request.urlopen", fake_urlopen)

    result = ComfyUIClient("http://fake-comfyui").discard_image(
        {"filename": "plain-history.png", "subfolder": "", "type": "output"},
        prompt_id="prompt-plain",
    )

    assert result["file_deleted"] is True
    assert result["history_deleted"] is True
    assert not image_path.exists()
    assert calls == ["http://fake-comfyui/history"]


def test_comfyui_discard_without_file_delete_endpoint_clears_preview_with_warning(tmp_path):
    class UnsupportedDeleteClient(FakeComfyUIClient):
        def discard_image(self, image_ref, *, prompt_id=None, **kwargs):
            return {
                "file_deleted": False,
                "file_missing": False,
                "file_delete_supported": False,
                "history_deleted": bool(prompt_id),
            }

    db_path = tmp_path / "comfyui.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    comfy_base = tmp_path / "ComfyUI"
    (comfy_base / "output").mkdir(parents=True)
    client = _build_app(
        db_path,
        storage_root,
        settings={"comfyui_connection_mode": "local", "comfyui_base_dir": str(comfy_base)},
        comfyui_client=UnsupportedDeleteClient(),
    ).test_client()
    preview = _generate_preview(client)

    discarded = client.post(
        "/api/comfyui/discard",
        json={
            "image_ref": preview["image_ref"],
            "prompt_id": preview["prompt_id"],
        },
    )

    assert discarded.status_code == 200
    body = discarded.get_json()
    assert body["ok"] is True
    assert body["warning"] == "source_file_not_deleted"
    assert body["discard"]["history_deleted"] is True
    assert "原始檔可能仍留在 ComfyUI output" in body["msg"]


def test_comfyui_interrupt_requests_backend_interrupt(tmp_path):
    FakeComfyUIClient.interrupted = 0
    db_path = tmp_path / "comfyui.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    root_actor = {"id": 1, "username": "root", "role": "super_admin"}
    client = _build_app(db_path, storage_root, actor=lambda: root_actor).test_client()

    interrupted = client.post("/api/comfyui/interrupt", json={})

    assert interrupted.status_code == 200
    body = interrupted.get_json()
    assert body["ok"] is True
    assert body["interrupt"]["interrupted"] is True
    assert FakeComfyUIClient.interrupted == 1


def test_comfyui_interrupt_without_owned_generation_does_not_interrupt_backend(tmp_path):
    FakeComfyUIClient.interrupted = 0
    db_path = tmp_path / "comfyui.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    client = _build_app(db_path, storage_root).test_client()

    interrupted = client.post("/api/comfyui/interrupt", json={})

    assert interrupted.status_code == 200
    body = interrupted.get_json()
    assert body["ok"] is True
    assert body["interrupt"]["backend_interrupted"] is False
    assert body["interrupt"]["reason"] == "no_owned_generation"
    assert FakeComfyUIClient.interrupted == 0


def test_comfyui_interrupt_denies_shared_backend_when_other_user_is_generating(tmp_path):
    FakeComfyUIClient.interrupted = 0
    db_path = tmp_path / "comfyui.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    active_generations = {
        "own": {"user_id": 1, "username": "test"},
        "other": {"user_id": 2, "username": "admin"},
    }
    client = _build_app(
        db_path,
        storage_root,
        extra_deps={"comfyui_active_generations": active_generations},
    ).test_client()

    interrupted = client.post("/api/comfyui/interrupt", json={})

    assert interrupted.status_code == 200
    body = interrupted.get_json()
    assert body["ok"] is True
    assert body["interrupt"]["backend_interrupted"] is False
    assert body["interrupt"]["reason"] == "shared_backend_busy"
    assert FakeComfyUIClient.interrupted == 0


def test_comfyui_interrupt_allows_owned_generation_when_backend_is_not_shared(tmp_path):
    FakeComfyUIClient.interrupted = 0
    db_path = tmp_path / "comfyui.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    active_generations = {"own": {"user_id": 1, "username": "test"}}
    client = _build_app(
        db_path,
        storage_root,
        extra_deps={"comfyui_active_generations": active_generations},
    ).test_client()

    interrupted = client.post("/api/comfyui/interrupt", json={})

    assert interrupted.status_code == 200
    body = interrupted.get_json()
    assert body["ok"] is True
    assert body["interrupt"]["backend_interrupted"] is True
    assert body["interrupt"]["reason"] == "owned_generation_only"
    assert FakeComfyUIClient.interrupted == 1


def test_comfyui_interrupt_tolerates_plain_text_response(monkeypatch):
    calls = []

    class PlainTextResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b"interrupted"

    def fake_urlopen(req, timeout=None):
        calls.append(req.full_url)
        return PlainTextResponse()

    monkeypatch.setattr("services.comfyui_client.urllib.request.urlopen", fake_urlopen)

    result = ComfyUIClient("http://fake-comfyui").interrupt()

    assert result == {"raw": "interrupted"}
    assert calls == ["http://fake-comfyui/interrupt"]


def test_comfyui_save_can_add_generated_image_to_album(tmp_path):
    db_path = tmp_path / "comfyui.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    album, msg = create_album(conn, actor=_actor(), title="AI Gallery")
    assert msg is None
    conn.commit()
    conn.close()
    client = _build_app(db_path, storage_root).test_client()
    preview = _generate_preview(client)

    saved = client.post(
        "/api/comfyui/save",
        json={
            "image_ref": preview["image_ref"],
            "virtual_path": "/ComfyUI/album.png",
            "album_id": album["id"],
        },
    )

    assert saved.status_code == 200
    body = saved.get_json()
    assert body["album"]["id"] == album["id"]
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT file_id, storage_file_id FROM album_files WHERE album_id=? AND deleted_at IS NULL",
        (album["id"],),
    ).fetchone()
    conn.close()
    assert row["file_id"] == body["file"]["file_id"]
    assert row["storage_file_id"] == body["storage_file"]["id"]


def test_comfyui_share_creates_comfyui_thread_with_preview_grant(tmp_path):
    db_path = tmp_path / "comfyui.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    album, msg = create_album(conn, actor=_actor(), title="Shared AI")
    assert msg is None
    conn.commit()
    conn.close()
    client = _build_app(db_path, storage_root).test_client()
    preview = _generate_preview(client)

    shared = client.post(
        "/api/comfyui/share",
        json={
            "image_ref": preview["image_ref"],
            "virtual_path": "/ComfyUI/share.png",
            "album_id": album["id"],
            "title": "My ComfyUI share",
            "note": "這張圖的心得",
            "generation": {
                "model": "dream.safetensors",
                "prompt": "a quiet test image",
                "negative_prompt": "noise",
                "width": 512,
                "height": 768,
                "steps": 18,
                "cfg": 6.5,
                "seed": 123,
                "batch_size": 2,
                "sampler_name": "euler",
                "scheduler": "normal",
            },
        },
    )

    assert shared.status_code == 200
    body = shared.get_json()
    assert body["thread"]["title"] == "My ComfyUI share"
    file_id = body["file"]["file_id"]
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    thread = conn.execute("SELECT * FROM forum_threads WHERE id=?", (body["thread"]["id"],)).fetchone()
    grant = conn.execute(
        "SELECT * FROM file_access_grants WHERE file_id=? AND context_type='forum_thread' AND context_id=?",
        (file_id, str(body["thread"]["id"])),
    ).fetchone()
    album_file = conn.execute(
        "SELECT id FROM album_files WHERE album_id=? AND file_id=? AND deleted_at IS NULL",
        (album["id"], file_id),
    ).fetchone()
    conn.close()
    assert thread["board_id"] == body["thread"]["board_id"]
    assert "[[comfyui-image:" + file_id + "]]" in thread["content"]
    assert "這張圖的心得" in thread["content"]
    assert "a quiet test image" in thread["content"]
    assert "張數：2" in thread["content"]
    assert grant["granted_to_role"] == "user"
    assert grant["can_preview"] == 1
    assert album_file is not None


def test_comfyui_frontend_is_wired():
    index_html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
    core_js = (ROOT / "public" / "js" / "00-core.js").read_text(encoding="utf-8")
    admin_js = (ROOT / "public" / "js" / "50-admin.js").read_text(encoding="utf-8")
    bootstrap_js = (ROOT / "public" / "js" / "90-bootstrap.js").read_text(encoding="utf-8")
    community_js = (ROOT / "public" / "js" / "25-community.js").read_text(encoding="utf-8")
    comfyui_js = (ROOT / "public" / "js" / "36-comfyui.js").read_text(encoding="utf-8")
    css = (ROOT / "public" / "styles.css").read_text(encoding="utf-8")
    settings_py = (ROOT / "services" / "settings.py").read_text(encoding="utf-8")
    smoke = (ROOT / "security" / "run_functional_smoke.sh").read_text(encoding="utf-8")

    assert 'id="tab-module-comfyui"' in index_html
    assert 'id="module-comfyui"' in index_html
    assert 'id="comfyui-model-select"' in index_html
    assert 'id="comfyui-lora-select"' in index_html
    assert 'id="comfyui-lora-add-btn"' in index_html
    assert 'id="comfyui-lora-count"' in index_html
    assert 'id="comfyui-selected-loras"' in index_html
    assert 'id="comfyui-generate-btn"' in index_html
    assert 'id="comfyui-interrupt-btn"' in index_html
    assert 'id="comfyui-load-draft-btn"' in index_html
    assert 'id="comfyui-batch-size"' in index_html
    assert 'id="comfyui-run-count"' in index_html
    assert 'id="comfyui-save-btn"' in index_html
    assert 'id="comfyui-album-select"' in index_html
    assert 'id="comfyui-share-btn"' in index_html
    assert 'id="comfyui-progress-panel"' in index_html
    assert 'id="comfyui-model-download-btn"' in index_html
    assert 'id="comfyui-civitai-inspect-btn"' in index_html
    assert 'id="comfyui-civitai-url"' in index_html
    assert 'id="comfyui-civitai-version"' in index_html
    assert 'id="comfyui-civitai-file"' in index_html
    assert 'id="comfyui-start-btn"' in index_html
    assert 'id="comfyui-stop-btn"' in index_html
    assert 'id="s-comfyui-connection-mode"' in index_html
    assert 'id="s-comfyui-remote-api-url"' in index_html
    assert 'id="s-comfyui-base-dir"' in index_html
    assert 'id="s-comfyui-local-start-script"' in index_html
    assert 'id="s-comfyui-civitai-api-key"' in index_html
    assert "/js/36-comfyui.js?v=20260503-comfyui-lora" in index_html
    assert "/styles.css?v=20260503-comfyui-lora" in index_html
    assert "width: min(420px, 100%);" in css
    assert "max-height: 320px;" in css
    assert 'id="s-comfyui-api-port"' in index_html
    assert 'id="comfyui-test-connection-btn"' in index_html
    assert 'id="comfyui-test-connection-status"' in index_html
    assert 'id="s-comfyui-max-batch-size"' in index_html
    assert 'tabModuleComfyui.style.display = canAccessModule("comfyui") ? "" : "none"' in core_js
    assert 'switchModuleTab("comfyui")' in bootstrap_js
    assert 'normTab === "comfyui"' in admin_js
    assert 'apiFetch(API + "/comfyui/generate"' in comfyui_js
    assert 'apiFetch(API + "/comfyui/billing-quote"' in comfyui_js
    assert 'apiFetch(API + "/root/comfyui/civitai/inspect"' in comfyui_js
    assert 'apiFetch(API + "/root/comfyui/civitai/download"' in comfyui_js
    assert 'apiFetch(API + "/comfyui/start"' in comfyui_js
    assert 'apiFetch(API + "/root/comfyui/stop"' in comfyui_js
    assert 'apiFetch(API + `/comfyui/jobs/${encodeURIComponent(jobId)}`' in comfyui_js
    assert "function startLocalComfyui()" in comfyui_js
    assert "function stopLocalComfyui()" in comfyui_js
    assert "function pollComfyuiJobUntilDone(jobId, controller, timeoutSeconds)" in comfyui_js
    assert '"async_progress": True' not in comfyui_js
    assert "async_progress: true" in comfyui_js
    assert "comfyuiConnectionMode !== \"local\"" in comfyui_js
    assert 'currentUser === "root"' in comfyui_js
    assert 'return true;' in comfyui_js
    assert 'tab.disabled = false;' in comfyui_js
    assert "不使用 LoRA（可略過）" in comfyui_js
    assert "scheduleComfyuiLocalStartPolling" in comfyui_js
    assert "function inspectComfyuiCivitaiModel()" in comfyui_js
    assert "function onComfyuiCivitaiVersionChange()" in comfyui_js
    assert "function updateComfyuiConnectionModeFields()" in admin_js
    assert "s-comfyui-connection-mode" in bootstrap_js
    assert "s-comfyui-civitai-api-key" in admin_js
    assert "startLocalComfyui" in bootstrap_js
    assert "inspectComfyuiCivitaiModel" in bootstrap_js
    assert "stopLocalComfyui" in bootstrap_js
    assert "json.starting" in admin_js
    assert "scheduleComfyuiLocalStartPolling({ attemptsLeft = 120, delayMs = 5000 }" in comfyui_js
    assert 'apiFetch(API + "/comfyui/interrupt"' in comfyui_js
    assert 'apiFetch(API + "/comfyui/save"' in comfyui_js
    assert 'apiFetch(API + "/comfyui/discard"' in comfyui_js
    assert 'source_file_not_deleted' in comfyui_js
    assert 'apiFetch(API + "/comfyui/share"' in comfyui_js
    assert 'apiFetch(API + "/comfyui/status"' in comfyui_js
    assert "function loadComfyuiLastSettings()" in comfyui_js
    assert 'let comfyuiMaxBatchSize = 1;' in comfyui_js
    assert 'let comfyuiBillingQuote = null;' in comfyui_js
    assert 'function applyComfyuiRuntimeLimits(payload = {})' in comfyui_js
    assert "非 root 帳號成功產圖後每張扣" in comfyui_js
    assert "function confirmComfyuiBilling(payload)" in comfyui_js
    assert "function preflightComfyuiBilling(payload, runCount, billingConfirmation)" in comfyui_js
    assert "function comfyuiRunCount()" in comfyui_js
    assert 'if (currentUser === "root") return { confirmed: true, required: false };' in comfyui_js
    assert "window.confirm" in comfyui_js
    assert "LoRA 加價" in comfyui_js
    assert 'comfyuiSelectedLoras.length >= COMFYUI_MAX_LORAS' in comfyui_js
    assert "batchSize * runCount" in comfyui_js
    assert "for (let requestIndex = 0; requestIndex < totalRequests; requestIndex += 1)" in comfyui_js
    assert "setComfyuiMessage(`正在產生第 ${requestIndex + 1} / ${totalRequests} 張圖片...`, true)" in comfyui_js
    assert "confirm_billing: billingConfirmation.required" in comfyui_js
    assert "json.billing?.charged" in comfyui_js
    assert 'batch_size: Math.max(1, Math.min(comfyuiMaxBatchSize, comfyuiNumberValue("comfyui-batch-size", 1)))' in comfyui_js
    assert "comfyuiGeneratedImages" in comfyui_js
    assert "renderComfyuiGeneratedImages" in comfyui_js
    assert 'savePath.value = `/output/${comfyuiCurrentImage.image_ref.filename}`;' in comfyui_js
    assert 'placeholder="/output/圖片.png"' in index_html
    assert "COMFYUI_DRAFT_FIELD_IDS" in comfyui_js
    assert "hackme_web:comfyui:draft" in comfyui_js
    assert "bindComfyuiDraftPersistence" in comfyui_js
    assert "restoreComfyuiDraft()" in comfyui_js
    assert 'album_id: selectedComfyuiAlbumId()' in comfyui_js
    assert "startComfyuiProgress(COMFYUI_GENERATION_TIMEOUT_SECONDS * runCount)" in comfyui_js
    assert "stopComfyuiProgress({ complete: true })" in comfyui_js
    assert "comfyuiGenerateAbortController.abort()" in comfyui_js
    assert "comfyuiShareGenerationPayload" in comfyui_js
    assert "payload.seed = comfyuiCurrentImage.seed" in comfyui_js
    assert 'id="comfyui-width" min="64" max="2048" step="8" value="1024"' in index_html
    assert 'id="comfyui-height" min="64" max="2048" step="8" value="1024"' in index_html
    assert 'id="s-comfyui-default-width"' in index_html
    assert 'id="s-comfyui-default-height"' in index_html
    assert "comfyuiDefaultWidth = 1024" in comfyui_js
    assert "comfyuiDefaultHeight = 1024" in comfyui_js
    assert 'if ($("s-comfyui-default-width"))' in admin_js
    assert "comfyui_default_width" in admin_js
    assert "interruptComfyuiGeneration" in bootstrap_js
    assert 'if (comfyuiLoadDraftBtn) comfyuiLoadDraftBtn.addEventListener("click", loadComfyuiLastSettings);' in bootstrap_js
    assert "bindComfyuiDraftPersistence" in bootstrap_js
    assert 'apiFetch(API + "/root/comfyui/test-connection"' in admin_js
    assert 'if (comfyuiTestConnectionBtn) comfyuiTestConnectionBtn.addEventListener("click", testComfyuiConnection);' in bootstrap_js
    assert 'shareComfyuiToCommunity' in bootstrap_js
    assert "comfyui-image:" in community_js
    assert "communityPreviewContentUrl" in community_js
    assert "csrf_token=${encodeURIComponent(token)}" not in community_js
    assert "/cloud-drive/files/${encodeURIComponent(fileId)}/preview/content" in community_js
    assert "/js/25-community.js?v=20260429-moderator-user-select" in index_html
    assert 'isComfyuiAvailableForNavigation' in admin_js
    assert '"feature_comfyui_enabled": False' in settings_py
    assert '"comfyui_api_host": os.environ.get("COMFYUI_API_HOST", "localhost")' in settings_py
    assert '"comfyui_api_port": 8192' in settings_py
    assert '"comfyui_max_batch_size": 1' in settings_py
    assert '"comfyui_default_width": 1024' in settings_py
    assert '"comfyui_default_height": 1024' in settings_py
    assert "/api/comfyui/models" in smoke
