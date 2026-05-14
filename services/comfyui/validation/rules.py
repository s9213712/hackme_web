"""Workflow sanitization rules and validation errors for ComfyUI."""

import re


WORKFLOW_BLOCKED_CLASS_RE = re.compile(
    r"(shell|exec|command|subprocess|terminal|powershell|python|script|curl|wget|requests?|websocket|httprequest|downloadurl|runcode)",
    re.IGNORECASE,
)
WORKFLOW_BLOCKED_COMMAND_RE = re.compile(
    r"(bash\s+-|sh\s+-c|cmd\s+/c|powershell\b|python\s+-c|node\s+-e)",
    re.IGNORECASE,
)
WORKFLOW_ABSOLUTE_PATH_RE = re.compile(r"^(?:[A-Za-z]:[\\/]|/|~(?:/|\\\\))")
WORKFLOW_URL_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://")
WORKFLOW_SENSITIVE_KEY_RE = re.compile(
    r"(path|directory|folder|cwd|script|command|shell|exec|url|uri|api[_-]?key|token|secret|password|authorization|cookie)",
    re.IGNORECASE,
)
WORKFLOW_SAFE_SENSITIVE_KEYS = {
    "ckpt_name",
    "vae_name",
    "lora_name",
    "control_net_name",
    "model_name",
    "filename_prefix",
    "image",
    "text",
}
WORKFLOW_MAX_NODE_COUNT = 200
WORKFLOW_MAX_NESTING_DEPTH = 10
WORKFLOW_MAX_JSON_BYTES = 256_000


class WorkflowValidationError(ValueError):
    pass
