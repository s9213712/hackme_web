"""Workflow sanitization entrypoints for ComfyUI JSON graphs."""

import hashlib
import json

from services.comfyui.validation.rules import (
    WORKFLOW_ABSOLUTE_PATH_RE,
    WORKFLOW_BLOCKED_CLASS_RE,
    WORKFLOW_BLOCKED_COMMAND_RE,
    WORKFLOW_MAX_JSON_BYTES,
    WORKFLOW_MAX_NESTING_DEPTH,
    WORKFLOW_MAX_NODE_COUNT,
    WORKFLOW_SENSITIVE_KEY_RE,
    WORKFLOW_SAFE_SENSITIVE_KEYS,
    WORKFLOW_URL_RE,
    WorkflowValidationError,
)
from services.comfyui.workflow.summary import extract_workflow_summary


def _canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _looks_like_path_traversal(text):
    normalized = str(text or "").replace("\\", "/")
    parts = [part for part in normalized.split("/") if part not in ("", ".")]
    return any(part == ".." for part in parts)


def _normalize_node_id(node_id):
    text = str(node_id or "").strip()
    if not text:
        raise WorkflowValidationError("workflow node id 不可為空")
    if len(text) > 40:
        raise WorkflowValidationError("workflow node id 過長")
    return text


def _sanitize_leaf(value, *, field_name, field_path):
    if isinstance(value, str):
        text = value.strip()
        if WORKFLOW_BLOCKED_COMMAND_RE.search(text):
            raise WorkflowValidationError(f"workflow 欄位 {field_path} 含有不允許的命令片段")
        if WORKFLOW_URL_RE.match(text):
            raise WorkflowValidationError(f"workflow 欄位 {field_path} 不可包含外部 URL")
        if WORKFLOW_ABSOLUTE_PATH_RE.match(text):
            raise WorkflowValidationError(f"workflow 欄位 {field_path} 不可包含絕對路徑")
        if _looks_like_path_traversal(text):
            raise WorkflowValidationError(f"workflow 欄位 {field_path} 不可包含路徑穿越")
        if WORKFLOW_SENSITIVE_KEY_RE.search(field_name or "") and field_name not in WORKFLOW_SAFE_SENSITIVE_KEYS and text:
            raise WorkflowValidationError(f"workflow 欄位 {field_path} 不可包含敏感路徑或命令資訊")
        return value
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    raise WorkflowValidationError(f"workflow 欄位 {field_path} 類型不支援")


def _sanitize_value(value, *, field_name="", field_path="workflow", depth=0):
    if depth > WORKFLOW_MAX_NESTING_DEPTH:
        raise WorkflowValidationError(f"{field_path} 巢狀層級過深")
    if isinstance(value, dict):
        sanitized = {}
        for key, item in value.items():
            key_text = str(key or "").strip()
            if not key_text:
                raise WorkflowValidationError(f"{field_path} 含有空白欄位名稱")
            child_path = f"{field_path}.{key_text}"
            sanitized[key_text] = _sanitize_value(item, field_name=key_text, field_path=child_path, depth=depth + 1)
        return sanitized
    if isinstance(value, list):
        return [
            _sanitize_value(item, field_name=field_name, field_path=f"{field_path}[{index}]", depth=depth + 1)
            for index, item in enumerate(value)
        ]
    return _sanitize_leaf(value, field_name=field_name, field_path=field_path)


def sanitize_workflow_json(workflow_json):
    candidate = workflow_json
    if isinstance(candidate, str):
        if len(candidate.encode("utf-8")) > WORKFLOW_MAX_JSON_BYTES:
            raise WorkflowValidationError("workflow JSON 過大")
        try:
            candidate = json.loads(candidate)
        except json.JSONDecodeError as exc:
            raise WorkflowValidationError("workflow JSON 格式不正確") from exc
    if not isinstance(candidate, dict) or not candidate:
        raise WorkflowValidationError("workflow JSON 必須是非空物件")
    if len(candidate) > WORKFLOW_MAX_NODE_COUNT:
        raise WorkflowValidationError("workflow node 數量過多")
    sanitized = {}
    for node_id, node in candidate.items():
        safe_node_id = _normalize_node_id(node_id)
        if not isinstance(node, dict):
            raise WorkflowValidationError(f"workflow node {safe_node_id} 格式不正確")
        safe_node = _sanitize_value(node, field_name=safe_node_id, field_path=f"workflow.{safe_node_id}", depth=1)
        safe_class = str(safe_node.get("class_type") or "").strip()
        if not safe_class:
            raise WorkflowValidationError(f"workflow node {safe_node_id} 缺少 class_type")
        if WORKFLOW_BLOCKED_CLASS_RE.search(safe_class):
            raise WorkflowValidationError(f"workflow node {safe_node_id} 使用了不允許的節點：{safe_class}")
        if not isinstance(safe_node.get("inputs"), dict):
            raise WorkflowValidationError(f"workflow node {safe_node_id} 缺少 inputs")
        sanitized[safe_node_id] = safe_node
    if len(_canonical_json(sanitized).encode("utf-8")) > WORKFLOW_MAX_JSON_BYTES:
        raise WorkflowValidationError("workflow JSON 過大")
    summary = extract_workflow_summary(sanitized)
    workflow_hash = hashlib.sha256(_canonical_json(sanitized).encode("utf-8")).hexdigest()
    return {
        "workflow_json": sanitized,
        "workflow_hash": workflow_hash,
        **summary,
    }


def workflow_json_to_pretty_text(workflow_json):
    return json.dumps(workflow_json, ensure_ascii=False, sort_keys=True, indent=2)
