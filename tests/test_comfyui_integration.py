import io
import sqlite3
from pathlib import Path

from flask import Flask, jsonify, make_response

from routes.comfyui import register_comfyui_routes
from services.cloud_drive import ensure_cloud_drive_attachment_schema
from services.comfyui_client import ComfyUIImage
from services.member_levels import ensure_member_level_rules_schema
from services.storage_albums import ensure_storage_album_schema
from services.upload_security import ensure_upload_security_schema, update_cloud_drive_security_policy


ROOT = Path(__file__).resolve().parents[1]


class FakeComfyUIClient:
    base_url = "http://fake-comfyui"

    def get_models(self):
        return ["dream.safetensors", "photo.ckpt"]

    def get_sampler_options(self):
        return {"samplers": ["euler", "dpmpp_2m"], "schedulers": ["normal", "karras"]}

    def generate_image(self, params, *, timeout_seconds=180):
        return {
            "prompt_id": "prompt-1",
            "image_ref": {"filename": "hackme_web_00001_.png", "subfolder": "", "type": "output"},
            "mime_type": "image/png",
            "data": b"fake-png-bytes",
        }

    def fetch_image(self, image_ref):
        return ComfyUIImage(
            filename=image_ref.get("filename") or "hackme_web_00001_.png",
            subfolder=image_ref.get("subfolder") or "",
            type=image_ref.get("type") or "output",
            mime_type="image/png",
            data=b"fake-png-bytes",
        )


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


def _build_app(db_path, storage_root):
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
        "comfyui_client": FakeComfyUIClient(),
    })
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
        },
    )
    assert generated.status_code == 200
    body = generated.get_json()
    assert body["image"]["prompt_id"] == "prompt-1"
    assert body["image"]["data_url"].startswith("data:image/png;base64,")
    assert body["image"]["seed"] == 123


def test_comfyui_save_stores_generated_image_in_user_storage(tmp_path):
    db_path = tmp_path / "comfyui.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    client = _build_app(db_path, storage_root).test_client()

    saved = client.post(
        "/api/comfyui/save",
        json={
            "image_ref": {"filename": "hackme_web_00001_.png", "subfolder": "", "type": "output"},
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


def test_comfyui_frontend_is_wired():
    index_html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
    core_js = (ROOT / "public" / "js" / "00-core.js").read_text(encoding="utf-8")
    admin_js = (ROOT / "public" / "js" / "50-admin.js").read_text(encoding="utf-8")
    bootstrap_js = (ROOT / "public" / "js" / "90-bootstrap.js").read_text(encoding="utf-8")
    comfyui_js = (ROOT / "public" / "js" / "36-comfyui.js").read_text(encoding="utf-8")
    settings_py = (ROOT / "services" / "settings.py").read_text(encoding="utf-8")
    smoke = (ROOT / "security" / "run_functional_smoke.sh").read_text(encoding="utf-8")

    assert 'id="tab-module-comfyui"' in index_html
    assert 'id="module-comfyui"' in index_html
    assert 'id="comfyui-model-select"' in index_html
    assert 'id="comfyui-generate-btn"' in index_html
    assert 'id="comfyui-save-btn"' in index_html
    assert "/js/36-comfyui.js?v=20260428-forum-pages" in index_html
    assert 'id="s-comfyui-api-port"' in index_html
    assert 'tabModuleComfyui.style.display = canAccessModule("comfyui") ? "" : "none"' in core_js
    assert 'switchModuleTab("comfyui")' in bootstrap_js
    assert 'normTab === "comfyui"' in admin_js
    assert 'fetch(API + "/comfyui/generate"' in comfyui_js
    assert 'fetch(API + "/comfyui/save"' in comfyui_js
    assert '"feature_comfyui_enabled": True' in settings_py
    assert '"comfyui_api_port": 8192' in settings_py
    assert "/api/comfyui/models" in smoke
