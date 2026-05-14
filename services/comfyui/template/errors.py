"""§11 Centralized error-message catalog (繁中) for the template importer.

Every user-facing error in the preview / import / run pipeline goes through
this module so:
- Wording stays consistent across stages.
- Translation / localization changes touch one file.
- Audit logs and HTTP responses share the same string source — no drift
  between "what we logged" vs "what the user saw".

Each catalog entry is paired with a *stable stage tag* (used by the audit
chain and the JSON ``stage`` field) so operators can grep across logs.

Spec reference: docs/comfyui/COMFYUI_TEMPLATE_IMPORTER_PLAN.md §11.
"""

from __future__ import annotations

from dataclasses import dataclass


# Stage tags — stable identifiers we use in audit detail and the API
# response's ``stage`` field. Keep them ASCII so log greps don't depend
# on Unicode.
class Stage:
    PARSE = "parse"
    SANITIZE = "sanitize"
    ANALYZE = "analyze"
    ALLOWLIST = "allowlist"
    CAPABILITY = "capability"
    CAPABILITY_MODELS = "capability_models"
    SAFETY = "safety"
    INPUTS = "inputs"
    INPUTS_CONSTRAINTS = "inputs_constraints"
    TOKEN = "token"
    TOKEN_INVALID = "token_invalid"
    TITLE = "title"
    GATE1_SANITIZE = "gate1_sanitize"
    GATE1_ANALYZE = "gate1_analyze"
    GATE2_CAPABILITY = "gate2_capability"
    GATE2_MODELS = "gate2_models"
    GATE3_ALLOWLIST = "gate3_allowlist"
    GATE4_INPUTS = "gate4_inputs"
    GATE4_CONSTRAINTS = "gate4_constraints"
    GATE5_SAFETY = "gate5_safety"


@dataclass(frozen=True)
class TemplateError:
    """One catalog entry."""

    stage: str
    template: str  # used as f-string-ish via .format(**ctx)

    def format(self, **ctx) -> str:
        try:
            return self.template.format(**ctx)
        except (KeyError, IndexError):
            return self.template


# ----------------------------------------------------------------------------
# Catalog
# ----------------------------------------------------------------------------

PARSE_BODY_NOT_JSON = TemplateError(
    Stage.PARSE,
    "workflow 必須是 JSON",
)
PARSE_BODY_NOT_OBJECT = TemplateError(
    Stage.PARSE,
    "workflow 必須是 JSON 物件",
)
PARSE_MULTIPART_MISSING_FILE = TemplateError(
    Stage.PARSE,
    "缺少 workflow 檔案",
)
PARSE_MULTIPART_EMPTY_FILE = TemplateError(
    Stage.PARSE,
    "workflow 檔案為空",
)
PARSE_MULTIPART_OVERSIZE = TemplateError(
    Stage.PARSE,
    "workflow 大小超過 {max_kb}KB 上限",
)
PARSE_NOT_UTF8 = TemplateError(
    Stage.PARSE,
    "workflow 必須是 UTF-8 編碼的 JSON 文字",
)
PARSE_MISSING_FIELD = TemplateError(
    Stage.PARSE,
    "請提供 workflow（dict）或 workflow_text（API-format JSON 字串）",
)
PARSE_EMPTY_BODY = TemplateError(
    Stage.PARSE,
    "workflow 內容為空",
)
PARSE_JSON_DECODE = TemplateError(
    Stage.PARSE,
    "workflow JSON 格式錯誤：{detail}（行 {line}）。請確認上傳的是 ComfyUI API format（不是 UI graph）。",
)

SANITIZE_GENERIC = TemplateError(
    Stage.SANITIZE,
    "{detail}",
)

ALLOWLIST_DENIED_CLASSES = TemplateError(
    Stage.ALLOWLIST,
    "workflow 含明確拒絕的節點類型：{denied}。第一版不支援這些類別（見 §4.3）。",
)
ALLOWLIST_UNKNOWN_CLASSES = TemplateError(
    Stage.ALLOWLIST,
    "workflow 含未授權的節點類型：{unknown}。第一版只支援 17 種核心節點 + ControlNet 標準 preprocessor，完整清單見 docs/comfyui/COMFYUI_TEMPLATE_IMPORTER_PLAN.md §4。",
)

CAPABILITY_UNSUPPORTED = TemplateError(
    Stage.CAPABILITY,
    "workflow 在本地 ComfyUI 上不支援：{unsupported}",
)
CAPABILITY_NOT_CONNECTED = TemplateError(
    Stage.CAPABILITY,
    "尚未連線到本地 ComfyUI；無法判斷 workflow 是否可執行",
)
CAPABILITY_MODELS_MISSING = TemplateError(
    Stage.CAPABILITY_MODELS,
    "本地 ComfyUI 缺少模型：{missing_models}",
)

SAFETY_GENERIC = TemplateError(
    Stage.SAFETY,
    "{detail}",
)

INPUTS_MISSING = TemplateError(
    Stage.INPUTS,
    "必要欄位未填：{missing}",
)
INPUTS_CONSTRAINT = TemplateError(
    Stage.INPUTS_CONSTRAINTS,
    "user_inputs[{node_id}].{input_name}：{detail}",
)

TOKEN_MISSING = TemplateError(
    Stage.TOKEN,
    "缺少 preview_token；請先呼叫 /api/comfyui/templates/preview",
)
TOKEN_INVALID = TemplateError(
    Stage.TOKEN_INVALID,
    "preview_token 無效或已過期，請重新預覽 workflow",
)
TITLE_BLANK = TemplateError(
    Stage.TITLE,
    "title 不可為空",
)


# ----------------------------------------------------------------------------
# Run-gate stage helpers — RunGateFailure carries (gate, stage, msg).
# These tag the gate-specific stage explicitly so the route helper can
# emit the audit_detail per §10.3.1.
# ----------------------------------------------------------------------------


def gate1_sanitize_msg(detail: str) -> tuple[str, str]:
    return Stage.GATE1_SANITIZE, detail


def gate1_analyze_msg(detail: str) -> tuple[str, str]:
    return Stage.GATE1_ANALYZE, detail


def gate2_capability_msg(unsupported) -> tuple[str, str]:
    return Stage.GATE2_CAPABILITY, f"本地 ComfyUI 缺少節點：{unsupported}"


def gate2_models_msg(missing_models) -> tuple[str, str]:
    return Stage.GATE2_MODELS, f"缺少模型：{missing_models}"


def gate3_allowlist_msg(detail: str) -> tuple[str, str]:
    return Stage.GATE3_ALLOWLIST, detail


def gate4_inputs_msg(missing) -> tuple[str, str]:
    return Stage.GATE4_INPUTS, f"必要欄位未填：{missing}"


def gate4_constraints_msg(detail: str) -> tuple[str, str]:
    return Stage.GATE4_CONSTRAINTS, detail


def gate5_safety_msg(detail: str) -> tuple[str, str]:
    return Stage.GATE5_SAFETY, detail


__all__ = [
    "Stage",
    "TemplateError",
    "PARSE_BODY_NOT_JSON",
    "PARSE_BODY_NOT_OBJECT",
    "PARSE_MULTIPART_MISSING_FILE",
    "PARSE_MULTIPART_EMPTY_FILE",
    "PARSE_MULTIPART_OVERSIZE",
    "PARSE_NOT_UTF8",
    "PARSE_MISSING_FIELD",
    "PARSE_EMPTY_BODY",
    "PARSE_JSON_DECODE",
    "SANITIZE_GENERIC",
    "ALLOWLIST_DENIED_CLASSES",
    "ALLOWLIST_UNKNOWN_CLASSES",
    "CAPABILITY_UNSUPPORTED",
    "CAPABILITY_NOT_CONNECTED",
    "CAPABILITY_MODELS_MISSING",
    "SAFETY_GENERIC",
    "INPUTS_MISSING",
    "INPUTS_CONSTRAINT",
    "TOKEN_MISSING",
    "TOKEN_INVALID",
    "TITLE_BLANK",
    "gate1_sanitize_msg",
    "gate1_analyze_msg",
    "gate2_capability_msg",
    "gate2_models_msg",
    "gate3_allowlist_msg",
    "gate4_inputs_msg",
    "gate4_constraints_msg",
    "gate5_safety_msg",
]
