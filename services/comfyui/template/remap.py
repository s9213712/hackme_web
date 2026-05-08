"""§7.3 LoadImage / LoadImageMask remap to hackme_web cloud-drive uploads.

The remap is split in two so the pure workflow → workflow transform stays
unit-testable without a live ComfyUI / filesystem:

1. ``remap_load_image_to_cloud_file()`` validates the cloud-drive file row
   (owner, mime, size, scan_status, decode), then asks the caller-supplied
   ``upload_callback`` to actually push the bytes into ComfyUI ``input/``
   under a per-run subfolder. The callback returns the ComfyUI-assigned
   filename, which we splice back into ``LoadImage.image``.

2. ``build_default_upload_callback()`` (used by the Phase 4 route) wraps
   the real ``services/comfyui/files.upload_image_bytes`` + the runtime
   storage path lookup. Routes that don't have a live ComfyUI yet (e.g.,
   tests) supply their own callback.

Validation matches §7.3 (the spec's mime / size / scan / decode list) +
§10.3.3's hard-fail rule on protected inputs (LoadImage / LoadImageMask).

Spec reference: docs/comfyui/COMFYUI_TEMPLATE_IMPORTER_PLAN.md §7.3.
"""

from __future__ import annotations

import copy
from typing import Any, Callable, Mapping, Protocol

from services.comfyui.template.safety import SafetyError, _safe_run_id


# (class_type, input_name) pairs whose `image`-shaped input must be remapped.
# Same set as §10.3.3's PROTECTED_INPUTS — kept here as the source of truth.
PROTECTED_IMAGE_INPUTS: frozenset[tuple[str, str]] = frozenset(
    {
        ("LoadImage", "image"),
        ("LoadImageMask", "image"),
        ("LoadImageMask", "mask"),
    }
)

ALLOWED_IMAGE_MIMES: frozenset[str] = frozenset(
    {"image/png", "image/jpeg", "image/jpg", "image/webp"}
)
ALLOWED_IMAGE_EXTENSIONS: frozenset[str] = frozenset(
    {".png", ".jpg", ".jpeg", ".webp"}
)
DEFAULT_MAX_IMAGE_BYTES = 8 * 1024 * 1024  # 8 MiB


class UploadCallback(Protocol):
    """Adapter the route layer passes in for the actual ComfyUI upload.

    Inputs:
        file_row: the validated `uploaded_files` row (sqlite3.Row).
        target_filename: filename we want ComfyUI to use; the callback
            should pass it through ``upload_image_bytes(filename=...)``.
        run_id: per-request id, used as ComfyUI subfolder.

    Returns:
        A dict shaped like ``{"filename": "<comfy filename>",
        "subfolder": "<run_id>", "type": "input"}`` — exactly what
        ``services/comfyui/files.upload_image_bytes`` returns.
    """

    def __call__(
        self,
        *,
        file_row: Mapping[str, Any],
        target_filename: str,
        run_id: str,
    ) -> Mapping[str, Any]:
        ...


def _resolve_image_path(value: Any) -> str | None:
    """Recover the cloud-drive image path/id the analyzer surfaced as a scalar."""
    if isinstance(value, str):
        return value
    return None


def _validate_uploaded_file_row(
    file_row: Mapping[str, Any] | None,
    *,
    cloud_file_id: str,
    actor: Mapping[str, Any],
    upload_scan_skip_allowed: bool,
    max_bytes: int,
    image_decoder: Callable[[bytes], None] | None = None,
    file_bytes_loader: Callable[[Mapping[str, Any]], bytes] | None = None,
) -> None:
    """Run §7.3's owner / mime / size / scan / decode gate.

    Raises ``SafetyError`` on any failure. The caller is responsible for
    constructing ``file_row`` (typically by SELECTing from uploaded_files).

    `upload_scan_skip_allowed` mirrors §7.3's policy: only accept
    ``scan_status="skipped"`` when root has explicitly opted in via
    ``security.upload_scan_skip_allowed=true``.
    """
    if file_row is None:
        raise SafetyError(f"image 檔 {cloud_file_id} 不存在或已刪除")
    if file_row.get("deleted_at"):
        raise SafetyError(f"image 檔 {cloud_file_id} 已刪除")

    actor_id = int(actor.get("id") or 0)
    if int(file_row.get("owner_user_id") or 0) != actor_id:
        raise SafetyError(f"image 檔 {cloud_file_id} 不屬於你")

    # MIME — privacy_mode "standard_plain" populates plain_for_public; the
    # encrypted privacy modes don't expose a plaintext mime to the server.
    plain_mime = str(file_row.get("mime_type_plain_for_public") or "").strip().lower()
    privacy_mode = str(file_row.get("privacy_mode") or "").strip().lower()
    if privacy_mode != "standard_plain":
        raise SafetyError(
            f"image 檔 {cloud_file_id} 為 {privacy_mode} 模式，本版只支援 standard_plain 圖片做 LoadImage 來源"
        )
    if plain_mime not in ALLOWED_IMAGE_MIMES:
        raise SafetyError(
            f"image 檔 {cloud_file_id} 的 MIME ({plain_mime!r}) 不在允許清單中"
        )

    # File extension (derived from original filename plain). Empty extension
    # is rejected — we don't trust that ComfyUI will sniff the type.
    plain_filename = str(file_row.get("original_filename_plain_for_public") or "")
    if "." in plain_filename:
        ext = plain_filename[plain_filename.rfind(".") :].lower()
    else:
        ext = ""
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        raise SafetyError(
            f"image 檔 {cloud_file_id} 的副檔名 ({ext!r}) 不在允許清單中"
        )

    # Size
    size = int(file_row.get("size_bytes") or 0)
    if size <= 0:
        raise SafetyError(f"image 檔 {cloud_file_id} 大小未知或為 0")
    if size > int(max_bytes):
        raise SafetyError(
            f"image 檔 {cloud_file_id} 大小 {size} 超過上限 {max_bytes}"
        )

    # Scan status (clean by default; skipped only when root has opted in).
    scan_status = str(file_row.get("scan_status") or "").strip().lower()
    allowed_scan = {"clean"}
    if upload_scan_skip_allowed:
        allowed_scan.add("skipped")
    if scan_status not in allowed_scan:
        raise SafetyError(
            f"image 檔 {cloud_file_id} 未通過安全掃描 (scan_status={scan_status!r})"
        )

    # Decode — ensures the bytes are actually a parseable image, not a
    # mis-extension'd archive / shellcode. Optional in unit tests; the
    # production path always supplies a decoder.
    if image_decoder is not None and file_bytes_loader is not None:
        try:
            image_decoder(file_bytes_loader(file_row))
        except SafetyError:
            raise
        except Exception as exc:
            raise SafetyError(f"image 檔 {cloud_file_id} 解碼失敗：{exc}") from exc


def remap_load_image_to_cloud_file(
    workflow: Mapping[str, Any],
    *,
    image_field_assignments: Mapping[str, str],
    actor: Mapping[str, Any],
    conn,
    run_id: str,
    upload_callback: UploadCallback,
    fetch_file_row: Callable[[Any, str], Mapping[str, Any] | None] | None = None,
    upload_scan_skip_allowed: bool = False,
    max_bytes: int = DEFAULT_MAX_IMAGE_BYTES,
    image_decoder: Callable[[bytes], None] | None = None,
    file_bytes_loader: Callable[[Mapping[str, Any]], bytes] | None = None,
) -> dict[str, Any]:
    """Replace LoadImage / LoadImageMask `image` inputs with ComfyUI uploads.

    Strict policy:
      * Author-supplied ``image`` strings inside the workflow are **never**
        trusted (see §7.3). The user must explicitly assign each image
        node id to a cloud-drive file id via ``image_field_assignments``.
      * Every assignment runs through ``_validate_uploaded_file_row``
        (owner / mime / extension / size / scan / decode).
      * Every assigned cloud-drive file is uploaded into ComfyUI ``input/``
        under subfolder ``<safe_run_id>`` via ``upload_callback``.
      * Each protected node id (LoadImage / LoadImageMask) **must** appear
        in the assignments — nodes the user didn't fill in still raise.

    Returns a deep copy of the workflow with each protected input rewritten
    to ComfyUI's returned reference (typically ``"<subfolder>/<filename>"``
    so ComfyUI can locate the file under input/).
    """
    if not isinstance(workflow, dict):
        raise SafetyError("workflow 必須是 ComfyUI API-format 物件")
    safe_run = _safe_run_id(run_id)
    new_wf = copy.deepcopy(workflow)
    actor_id = int(actor.get("id") or 0)
    if actor_id <= 0:
        raise SafetyError("actor.id 缺漏")

    # Discover every protected node id that needs an assignment.
    protected_node_ids: dict[str, tuple[str, str]] = {}
    for node_id, node in new_wf.items():
        if not isinstance(node, dict):
            continue
        class_type = str(node.get("class_type") or "")
        inputs = node.get("inputs") or {}
        if not isinstance(inputs, dict):
            continue
        for input_name in inputs.keys():
            if (class_type, input_name) in PROTECTED_IMAGE_INPUTS:
                protected_node_ids[node_id] = (class_type, input_name)
                break

    missing = [nid for nid in protected_node_ids if nid not in image_field_assignments]
    if missing:
        raise SafetyError(
            f"以下 LoadImage / LoadImageMask 節點沒有指定圖片來源：{sorted(missing)}"
        )

    extra = [nid for nid in image_field_assignments if nid not in protected_node_ids]
    if extra:
        raise SafetyError(
            f"image_field_assignments 含有不存在或非 LoadImage 的節點：{sorted(extra)}"
        )

    if fetch_file_row is None:
        fetch_file_row = _default_fetch_file_row

    for node_id, cloud_file_id in image_field_assignments.items():
        cloud_file_id_str = str(cloud_file_id or "").strip()
        if not cloud_file_id_str:
            raise SafetyError(f"node {node_id} 的圖片來源不可為空")
        file_row = fetch_file_row(conn, cloud_file_id_str)
        _validate_uploaded_file_row(
            file_row,
            cloud_file_id=cloud_file_id_str,
            actor=actor,
            upload_scan_skip_allowed=upload_scan_skip_allowed,
            max_bytes=max_bytes,
            image_decoder=image_decoder,
            file_bytes_loader=file_bytes_loader,
        )
        target_filename = f"{actor_id}_{safe_run}_{node_id}.png"
        upload_result = upload_callback(
            file_row=file_row,
            target_filename=target_filename,
            run_id=safe_run,
        ) or {}
        comfy_filename = str(upload_result.get("filename") or "").strip()
        comfy_subfolder = str(upload_result.get("subfolder") or "").strip()
        if not comfy_filename:
            raise SafetyError(f"node {node_id} 上傳到 ComfyUI 後未取得檔名")

        # Splice into the workflow.
        class_type, input_name = protected_node_ids[node_id]
        node = new_wf[node_id]
        # ComfyUI's LoadImage accepts "<subfolder>/<filename>" or just "filename".
        # Use the subfolder form so per-run cleanup can target a single dir.
        loaded = (
            f"{comfy_subfolder}/{comfy_filename}" if comfy_subfolder else comfy_filename
        )
        node["inputs"][input_name] = loaded

    return new_wf


def _default_fetch_file_row(conn, cloud_file_id: str) -> Mapping[str, Any] | None:
    """Default lookup against the canonical uploaded_files table."""
    row = conn.execute(
        """
        SELECT id, owner_user_id, storage_path, privacy_mode, risk_level,
               scan_status, original_filename_plain_for_public,
               mime_type_plain_for_public, size_bytes, deleted_at
        FROM uploaded_files
        WHERE id = ? AND deleted_at IS NULL
        """,
        (cloud_file_id,),
    ).fetchone()
    if row is None:
        return None
    # sqlite3.Row supports mapping access via [];  return as-is so the validator
    # can read columns through `.get()` polyfilled below.
    return _RowAdapter(row)


class _RowAdapter:
    """Adapt sqlite3.Row to a dict-ish interface (`.get(key, default)`)."""

    def __init__(self, row):
        self._row = row

    def __getitem__(self, key):  # pragma: no cover - sqlite3.Row already supports this
        return self._row[key]

    def get(self, key, default=None):
        try:
            return self._row[key]
        except (KeyError, IndexError):
            return default

    def keys(self):  # pragma: no cover - convenience
        return list(self._row.keys())


__all__ = [
    "ALLOWED_IMAGE_EXTENSIONS",
    "ALLOWED_IMAGE_MIMES",
    "DEFAULT_MAX_IMAGE_BYTES",
    "PROTECTED_IMAGE_INPUTS",
    "SafetyError",
    "UploadCallback",
    "remap_load_image_to_cloud_file",
]
