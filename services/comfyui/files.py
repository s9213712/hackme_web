"""ComfyUI file upload/fetch/discard helpers."""

import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def upload_image_bytes(client, data, filename, *, image_type="input", overwrite=False, subfolder="", error_cls):
    filename = Path(str(filename or "upload.png")).name
    payload = client._multipart_request(
        "/upload/image",
        fields={
            "type": str(image_type or "input"),
            "overwrite": "true" if overwrite else "false",
            "subfolder": str(subfolder or ""),
        },
        files=[{
            "field": "image",
            "filename": filename,
            "content_type": "application/octet-stream",
            "data": data or b"",
        }],
    )
    name = str(payload.get("name") or filename).strip()
    if not name:
        raise error_cls("ComfyUI 未回傳上傳檔名")
    return {
        "filename": name,
        "subfolder": str(payload.get("subfolder") or subfolder or "").strip(),
        "type": str(payload.get("type") or image_type or "input").strip() or "input",
    }


def fetch_image(client, image_ref, *, error_cls, image_cls):
    filename = str((image_ref or {}).get("filename") or "").strip()
    subfolder = str((image_ref or {}).get("subfolder") or "").strip()
    image_type = str((image_ref or {}).get("type") or "output").strip() or "output"
    if not filename:
        raise error_cls("缺少 ComfyUI 圖片檔名")
    query = urllib.parse.urlencode({"filename": filename, "subfolder": subfolder, "type": image_type})
    req = urllib.request.Request(client._url(f"/view?{query}"), headers={"Accept": "image/*"})
    try:
        with urllib.request.urlopen(req, timeout=client.timeout) as resp:
            content_type = resp.headers.get("Content-Type") or "image/png"
            data = resp.read()
    except urllib.error.URLError as exc:
        raise error_cls(f"ComfyUI 圖片讀取失敗：{getattr(exc, 'reason', exc)}") from exc
    if not data:
        raise error_cls("ComfyUI 圖片內容為空")
    return image_cls(filename=filename, subfolder=subfolder, type=image_type, mime_type=content_type, data=data)


def local_dir_for_type(image_type, *, error_cls, local_base_dir=None):
    normalized = str(image_type or "output").strip().lower() or "output"
    if normalized not in {"output", "input", "temp"}:
        raise error_cls("ComfyUI 圖片類型不支援刪除")
    explicit = os.environ.get(f"COMFYUI_{normalized.upper()}_DIR")
    if explicit:
        return Path(explicit).expanduser()
    base_dir = local_base_dir or os.environ.get("COMFYUI_BASE_DIR")
    if base_dir:
        return Path(base_dir).expanduser() / normalized
    return None


def safe_local_image_path(image_ref, *, error_cls, local_base_dir=None):
    filename = str((image_ref or {}).get("filename") or "").strip()
    subfolder = str((image_ref or {}).get("subfolder") or "").strip()
    image_type = str((image_ref or {}).get("type") or "output").strip() or "output"
    if not filename:
        raise error_cls("缺少 ComfyUI 圖片檔名")
    if Path(filename).name != filename or filename in {".", ".."}:
        raise error_cls("ComfyUI 圖片檔名不合法")
    base_dir = local_dir_for_type(image_type, error_cls=error_cls, local_base_dir=local_base_dir)
    if not base_dir:
        return None
    relative = Path(subfolder) / filename if subfolder else Path(filename)
    if relative.is_absolute() or any(part in {"..", ""} for part in relative.parts):
        raise error_cls("ComfyUI 圖片路徑不合法")
    base = base_dir.resolve()
    target = (base / relative).resolve()
    try:
        target.relative_to(base)
    except ValueError as exc:
        raise error_cls("ComfyUI 圖片路徑超出允許目錄") from exc
    return target


def discard_image(client, image_ref, *, prompt_id=None, local_base_dir=None, allow_api_delete=True, error_cls):
    result = {
        "file_deleted": False,
        "file_missing": False,
        "file_delete_supported": False,
        "history_deleted": False,
    }
    target = safe_local_image_path(image_ref, error_cls=error_cls, local_base_dir=local_base_dir)
    if target:
        result["file_delete_supported"] = True
        if target.exists():
            if not target.is_file():
                raise error_cls("ComfyUI 目標路徑不是檔案")
            target.unlink()
            result["file_deleted"] = True
        else:
            result["file_missing"] = True
    elif allow_api_delete:
        filename = str((image_ref or {}).get("filename") or "").strip()
        subfolder = str((image_ref or {}).get("subfolder") or "").strip()
        image_type = str((image_ref or {}).get("type") or "output").strip() or "output"
        query = urllib.parse.urlencode({"filename": filename, "subfolder": subfolder, "type": image_type})
        req = urllib.request.Request(client._url(f"/view?{query}"), method="DELETE", headers={"Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=client.timeout):
                result["file_delete_supported"] = True
                result["file_deleted"] = True
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                result["file_delete_supported"] = True
                result["file_missing"] = True
            elif exc.code not in {405, 501}:
                raise error_cls(f"ComfyUI 原始檔刪除失敗：HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise error_cls(f"ComfyUI 原始檔刪除失敗：{getattr(exc, 'reason', exc)}") from exc
    if prompt_id:
        client._json_request("/history", method="POST", payload={"delete": [str(prompt_id)]}, allow_non_json=True)
        result["history_deleted"] = True
    return result
