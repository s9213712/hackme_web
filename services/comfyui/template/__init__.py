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
    embedding_option_available,
    iter_required_models,
    model_option_available,
    reset_object_info_cache,
    rewrite_workflow_model_inputs_to_local_options,
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
    ALLOWED_VIDEO_EXTENSIONS,
    ALLOWED_VIDEO_MIMES,
    DEFAULT_MAX_IMAGE_BYTES,
    DEFAULT_MAX_VIDEO_BYTES,
    PROTECTED_IMAGE_INPUTS,
    PROTECTED_MEDIA_INPUTS,
    PROTECTED_VIDEO_INPUTS,
    UploadCallback,
    remap_load_image_to_cloud_file,
)
from services.comfyui.template.preview_store import (
    DatabasePreviewStore,
    InMemoryPreviewStore,
    PREVIEW_TOKEN_TTL_SECONDS,
    PreviewEntry,
    PreviewStore,
    get_default_preview_store,
    reset_default_preview_store,
    set_default_preview_store,
)
from services.comfyui.template.normalize import (
    convert_ui_graph_to_api_workflow,
    is_ui_graph_workflow,
    normalize_uploaded_workflow_json,
)
from services.comfyui.template.run_gate import (
    RunGateFailure,
    RunGateResult,
    run_workflow_through_gates,
)
from services.comfyui.template.cleanup import (
    COMFYUI_RUN_TTL_SECONDS,
    cleanup_run_temp_files,
    list_active_run_dirs,
    register_run_dir,
    registry_size,
    reset_registry,
    sweep_orphaned_run_dirs,
)
from services.comfyui.template.seeding import (
    REPO_SOURCE_DIR,
    list_runtime_workflows,
    runtime_comfyui_dir,
    seed_default_comfyui_workflows,
)
from services.comfyui.template import errors

__all__ = [
    "ALLOWED_IMAGE_EXTENSIONS",
    "ALLOWED_IMAGE_MIMES",
    "ALLOWED_VIDEO_EXTENSIONS",
    "ALLOWED_VIDEO_MIMES",
    "DEFAULT_MAX_IMAGE_BYTES",
    "DEFAULT_MAX_VIDEO_BYTES",
    "DatabasePreviewStore",
    "InMemoryPreviewStore",
    "PREVIEW_TOKEN_TTL_SECONDS",
    "PROTECTED_IMAGE_INPUTS",
    "PROTECTED_MEDIA_INPUTS",
    "PROTECTED_VIDEO_INPUTS",
    "PreviewEntry",
    "PreviewStore",
    "RunGateFailure",
    "RunGateResult",
    "COMFYUI_RUN_TTL_SECONDS",
    "REPO_SOURCE_DIR",
    "cleanup_run_temp_files",
    "errors",
    "list_active_run_dirs",
    "list_runtime_workflows",
    "register_run_dir",
    "registry_size",
    "reset_registry",
    "runtime_comfyui_dir",
    "seed_default_comfyui_workflows",
    "sweep_orphaned_run_dirs",
    "UploadCallback",
    "get_default_preview_store",
    "remap_load_image_to_cloud_file",
    "reset_default_preview_store",
    "run_workflow_through_gates",
    "set_default_preview_store",
    "convert_ui_graph_to_api_workflow",
    "is_ui_graph_workflow",
    "normalize_uploaded_workflow_json",
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
    "embedding_option_available",
    "is_allowed_class",
    "is_explicitly_denied_class",
    "iter_required_models",
    "model_option_available",
    "next_safe_node_id",
    "required_user_inputs",
    "reset_object_info_cache",
    "rewrite_workflow_model_inputs_to_local_options",
    "rewrite_save_image_prefix",
]
