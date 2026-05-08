"""ComfyUI Template Importer (Phase 1) — see docs/comfyui/COMFYUI_TEMPLATE_IMPORTER_PLAN.md.

Public surface kept intentionally narrow; everything below `template/` is
implementation detail. Re-export only the names that route handlers are
expected to import.
"""

from services.comfyui.template.allowlist import (
    CORE_ALLOWLIST,
    CONTROLNET_PREPROCESSOR_ALLOWLIST,
    EXPLICIT_DENYLIST,
    is_allowed_class,
    is_explicitly_denied_class,
)
from services.comfyui.template.analyzer import (
    FieldCategory,
    InputField,
    NodeAnalysis,
    WorkflowAnalysis,
    analyze_workflow_json,
    classify_input_field,
)
from services.comfyui.template.capability import (
    CapabilityCheck,
    CapabilityOverall,
    check_workflow_capability,
    iter_required_models,
    reset_object_info_cache,
)

__all__ = [
    "CORE_ALLOWLIST",
    "CONTROLNET_PREPROCESSOR_ALLOWLIST",
    "EXPLICIT_DENYLIST",
    "CapabilityCheck",
    "CapabilityOverall",
    "FieldCategory",
    "InputField",
    "NodeAnalysis",
    "WorkflowAnalysis",
    "analyze_workflow_json",
    "check_workflow_capability",
    "classify_input_field",
    "is_allowed_class",
    "is_explicitly_denied_class",
    "iter_required_models",
    "reset_object_info_cache",
]
