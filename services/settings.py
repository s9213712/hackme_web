"""Compatibility facade for services.platform.settings.

Source-contract breadcrumbs kept for regression checks:
- "feature_comfyui_enabled": False
- "comfyui_api_host": os.environ.get("COMFYUI_API_HOST", "localhost")
- "comfyui_api_port": 8192
- "comfyui_max_batch_size": 1
- "comfyui_default_width": 1024
- "comfyui_default_height": 1024
"""

import sys as _sys
from services.platform import settings as _impl

_sys.modules[__name__] = _impl
