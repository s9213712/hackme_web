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
from services.comfyui.template.safety import (
    SafetyError,
    enforce_allowlist,
    next_safe_node_id,
    rewrite_save_image_prefix,
)
from services.comfyui.template.ui_schema import (
    UISchema,
    build_ui_schema,
    required_user_inputs,
)
from services.comfyui.template.remap import (
    ALLOWED_IMAGE_EXTENSIONS,
    ALLOWED_IMAGE_MIMES,
    DEFAULT_MAX_IMAGE_BYTES,
    PROTECTED_IMAGE_INPUTS,
    UploadCallback,
    remap_load_image_to_cloud_file,
)

__all__ = [
    "ALLOWED_IMAGE_EXTENSIONS",
    "ALLOWED_IMAGE_MIMES",
    "DEFAULT_MAX_IMAGE_BYTES",
    "PROTECTED_IMAGE_INPUTS",
    "UploadCallback",
    "remap_load_image_to_cloud_file",
    "CORE_ALLOWLIST",
    "CONTROLNET_PREPROCESSOR_ALLOWLIST",
    "EXPLICIT_DENYLIST",
    "CapabilityCheck",
    "CapabilityOverall",
    "FieldCategory",
    "InputField",
    "NodeAnalysis",
    "SafetyError",
    "UISchema",
    "WorkflowAnalysis",
    "analyze_workflow_json",
    "build_ui_schema",
    "check_workflow_capability",
    "classify_input_field",
    "enforce_allowlist",
    "is_allowed_class",
    "is_explicitly_denied_class",
    "iter_required_models",
    "next_safe_node_id",
    "required_user_inputs",
    "reset_object_info_cache",
    "rewrite_save_image_prefix",
]
