"""Hugging Face metadata helpers for the Diffusers backend."""

from __future__ import annotations

import importlib.util
import re
from pathlib import PurePosixPath

from services.comfyui.settings import normalize_huggingface_repo_id


_MODEL_FILE_EXTENSIONS = {".safetensors", ".bin", ".ckpt", ".pt", ".pth", ".gguf"}
_UNSUPPORTED_PIPELINE_TAGS = {
    "audio-to-audio",
    "automatic-speech-recognition",
    "image-to-video",
    "text-to-audio",
    "text-to-speech",
    "text-to-video",
    "video-to-video",
}
_PRECISION_LABELS = {
    "default": "預設精度",
    "fp16": "FP16 / half",
    "bf16": "BF16",
    "fp32": "FP32",
}
_PRECISION_ORDER = {"default": 0, "fp16": 1, "bf16": 2, "fp32": 3}


def normalize_diffusers_variant(value, *, allow_blank=True):
    raw = str(value or "").strip()
    if not raw or raw in {"__default__", "default"}:
        return "" if allow_blank else None
    if len(raw) > 64 or not re.match(r"^[A-Za-z0-9._-]+$", raw):
        return None
    return raw


def normalize_huggingface_repo_file(value, *, allow_blank=True):
    raw = str(value or "").strip()
    if not raw:
        return "" if allow_blank else None
    if len(raw) > 260 or raw.startswith(("/", "\\")) or "\\" in raw:
        return None
    parts = [part for part in raw.split("/") if part]
    if not parts or any(part in {".", ".."} for part in parts):
        return None
    if any(".." in part for part in parts):
        return None
    return "/".join(parts)


def _sibling_filename(sibling):
    if isinstance(sibling, dict):
        return str(sibling.get("rfilename") or sibling.get("filename") or "").strip()
    return str(getattr(sibling, "rfilename", "") or getattr(sibling, "filename", "") or "").strip()


def _sibling_size(sibling):
    for attr in ("size", "blob_size"):
        value = sibling.get(attr) if isinstance(sibling, dict) else getattr(sibling, attr, None)
        if isinstance(value, int) and value >= 0:
            return value
    lfs = sibling.get("lfs") if isinstance(sibling, dict) else getattr(sibling, "lfs", None)
    if isinstance(lfs, dict):
        value = lfs.get("size")
    else:
        value = getattr(lfs, "size", None)
    return value if isinstance(value, int) and value >= 0 else None


def _precision_from_filename(filename):
    lowered = str(filename or "").lower()
    if re.search(r"(^|[._/-])(fp16|float16|half)([._/-]|$)", lowered):
        return "fp16"
    if re.search(r"(^|[._/-])(bf16|bfloat16)([._/-]|$)", lowered):
        return "bf16"
    if re.search(r"(^|[._/-])(fp32|float32)([._/-]|$)", lowered):
        return "fp32"
    return "default"


def _gguf_quant_from_filename(filename):
    stem = PurePosixPath(str(filename or "")).name
    match = re.search(r"(Q[2-8](?:_[01])?|Q[2-6]_K(?:_[SM])?|BF16|F16|FP16|F32|FP32)", stem, re.IGNORECASE)
    return match.group(1).upper() if match else "GGUF"


def _option_sort_key(option):
    if option.get("kind") == "gguf":
        return (0, str(option.get("label") or ""))
    return (1, _PRECISION_ORDER.get(str(option.get("precision") or ""), 50), str(option.get("label") or ""))


def build_diffusers_variant_options(siblings):
    groups = {}
    gguf_options = []
    for sibling in siblings or []:
        filename = _sibling_filename(sibling)
        if not filename:
            continue
        path = PurePosixPath(filename)
        if path.suffix.lower() not in _MODEL_FILE_EXTENSIONS:
            continue
        size = _sibling_size(sibling)
        if path.suffix.lower() == ".gguf":
            quant = _gguf_quant_from_filename(filename)
            gguf_options.append({
                "kind": "gguf",
                "value": f"gguf::{filename}",
                "variant": "",
                "gguf_file": filename,
                "precision": quant.lower(),
                "label": f"GGUF {quant} · {path.name}",
                "size_bytes": int(size or 0),
                "file_count": 1,
                "files": [filename],
                "requires_base_repo": True,
            })
            continue
        lowered = filename.lower()
        if any(skip in lowered for skip in ("optimizer", "scheduler", "training_args")):
            continue
        precision = _precision_from_filename(filename)
        group = groups.setdefault(precision, {"precision": precision, "size_bytes": 0, "file_count": 0, "files": []})
        if size is not None:
            group["size_bytes"] += size
        group["file_count"] += 1
        if len(group["files"]) < 8:
            group["files"].append(filename)
    options = []
    options.extend(gguf_options)
    for precision, group in sorted(groups.items(), key=lambda item: (_PRECISION_ORDER.get(item[0], 50), item[0])):
        options.append({
            "kind": "diffusers",
            "value": "__default__" if precision == "default" else precision,
            "variant": "" if precision == "default" else precision,
            "precision": precision,
            "label": _PRECISION_LABELS.get(precision, precision),
            "size_bytes": int(group["size_bytes"] or 0),
            "file_count": int(group["file_count"] or 0),
            "files": list(group["files"]),
        })
    return sorted(options, key=_option_sort_key)


def _info_value(info, name, default=None):
    if isinstance(info, dict):
        return info.get(name, default)
    return getattr(info, name, default)


def _card_data_values(card_data, key):
    if not card_data:
        return []
    value = card_data.get(key) if isinstance(card_data, dict) else getattr(card_data, key, None)
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if str(value).strip() else []


def infer_gguf_base_repo(repo_id="", *, tags=None, card_data=None):
    candidates = []
    candidates.extend(_card_data_values(card_data, "base_model"))
    candidates.extend(_card_data_values(card_data, "base_model_name"))
    for tag in tags or []:
        text = str(tag or "").strip()
        if text.lower().startswith("base_model:"):
            candidates.append(text.split(":", 1)[1].strip())
    for candidate in candidates:
        normalized = normalize_huggingface_repo_id(candidate, allow_blank=True)
        if normalized:
            return normalized
    name = str(repo_id or "").split("/")[-1].lower()
    if any(token in name for token in ("sdxl", "illustrious", "pony", "noob")):
        return "stabilityai/stable-diffusion-xl-base-1.0"
    if "flux" in name:
        return "black-forest-labs/FLUX.1-schnell"
    return ""


def detect_diffusers_supported_modes(*, repo_id="", pipeline_tag="", library_name="", tags=None, config=None, siblings=None):
    repo_text = str(repo_id or "").lower()
    tag = str(pipeline_tag or "").strip().lower()
    library = str(library_name or "").strip().lower()
    tag_set = {str(item or "").strip().lower() for item in (tags or []) if str(item or "").strip()}
    config = config if isinstance(config, dict) else {}
    class_name = str(config.get("_class_name") or config.get("pipeline_class") or "").lower()
    sibling_names = [_sibling_filename(item).lower() for item in (siblings or [])]
    has_model_index = any(name.endswith("model_index.json") for name in sibling_names)
    has_gguf = any(name.endswith(".gguf") for name in sibling_names)
    is_diffusers = library == "diffusers" or "diffusers" in tag_set or has_model_index
    inpaint_hint = any("inpaint" in item for item in [repo_text, tag, class_name, *tag_set])

    supported = set()
    if tag in _UNSUPPORTED_PIPELINE_TAGS:
        return []
    if has_gguf:
        return ["txt2img"] if tag in {"", "text-to-image", "unconditional-image-generation"} else []
    if tag in {"text-to-image", "unconditional-image-generation"}:
        supported.add("txt2img")
    if tag == "image-to-image":
        supported.add("img2img")
    if inpaint_hint:
        supported.add("inpaint")
    if is_diffusers and tag in {"", "text-to-image"}:
        supported.update({"txt2img", "img2img"})
    if is_diffusers and any(name in class_name for name in ("text2image", "texttoimage", "text-to-image", "pipeline")):
        supported.add("txt2img")
    if is_diffusers and any(name in class_name for name in ("image2image", "imagetoimage", "img2img")):
        supported.add("img2img")
    if is_diffusers and inpaint_hint:
        supported.add("inpaint")
    return sorted(supported, key=["txt2img", "img2img", "inpaint"].index)


def inspect_huggingface_diffusers_repo(repo_value, *, token="", mode="txt2img"):
    repo_id = normalize_huggingface_repo_id(repo_value, allow_blank=True)
    if repo_id is None:
        return {"ok": False, "checked": False, "msg": "Hugging Face repo 格式不合法，請填 namespace/model 或模型頁網址"}
    if not repo_id:
        return {"ok": False, "checked": False, "msg": "請輸入 Hugging Face repo"}
    if importlib.util.find_spec("huggingface_hub") is None:
        return {"ok": False, "checked": False, "repo_id": repo_id, "msg": "缺少 huggingface_hub 套件，無法在下載前檢查模型 metadata"}
    try:
        from huggingface_hub import HfApi
    except Exception as exc:
        return {"ok": False, "checked": False, "repo_id": repo_id, "msg": f"Hugging Face metadata 工具載入失敗：{exc}"}
    try:
        info = HfApi().model_info(repo_id, token=(token or None), files_metadata=True)
    except Exception as exc:
        return {"ok": False, "checked": False, "repo_id": repo_id, "msg": f"Hugging Face repo 檢查失敗，尚未開始下載：{exc}"}

    siblings = list(_info_value(info, "siblings", []) or [])
    pipeline_tag = str(_info_value(info, "pipeline_tag", "") or "")
    library_name = str(_info_value(info, "library_name", "") or "")
    tags = list(_info_value(info, "tags", []) or [])
    card_data = _info_value(info, "cardData", None) or _info_value(info, "card_data", None)
    config = _info_value(info, "config", {}) or {}
    supported_modes = detect_diffusers_supported_modes(
        repo_id=repo_id,
        pipeline_tag=pipeline_tag,
        library_name=library_name,
        tags=tags,
        config=config,
        siblings=siblings,
    )
    requested_mode = str(mode or "txt2img").strip().lower() or "txt2img"
    variant_options = build_diffusers_variant_options(siblings)
    has_gguf_options = any(item.get("kind") == "gguf" for item in variant_options)
    suggested_base_repo = infer_gguf_base_repo(repo_id, tags=tags, card_data=card_data) if has_gguf_options else ""
    warnings = []
    if pipeline_tag.lower() in _UNSUPPORTED_PIPELINE_TAGS:
        warnings.append(f"此 repo 的 Hugging Face pipeline 是 {pipeline_tag}，不是本站 Diffusers 生圖模式。")
    if not supported_modes:
        warnings.append("沒有偵測到可用的 Diffusers t2i / i2i metadata；為避免下載無法使用的模型，請改用支援的 repo。")
    elif requested_mode not in supported_modes:
        warnings.append(f"此 repo 目前偵測支援 {', '.join(supported_modes)}，不支援 {requested_mode}。")
    if len(variant_options) > 1:
        warnings.append("偵測到多個精度版本，請先選擇要下載/載入的版本，避免同一模型重複下載。")
    if has_gguf_options:
        warnings.append("GGUF 需要選擇檔案並搭配 base Diffusers repo；Diffusers 官方目前不支援直接用 Pipeline 載入 GGUF repo。")
        if suggested_base_repo:
            warnings.append(f"已推定 base repo：{suggested_base_repo}。")
    if not variant_options:
        warnings.append("沒有取得模型檔大小；若這不是 Diffusers repo，生成前會被阻擋。")
    return {
        "ok": True,
        "checked": True,
        "repo_id": repo_id,
        "pipeline_tag": pipeline_tag,
        "library_name": library_name,
        "supported_modes": supported_modes,
        "requested_mode": requested_mode,
        "supported_for_mode": requested_mode in supported_modes,
        "variant_options": variant_options,
        "has_gguf": has_gguf_options,
        "suggested_base_repo": suggested_base_repo,
        "warnings": warnings,
    }
