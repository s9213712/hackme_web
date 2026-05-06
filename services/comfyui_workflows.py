"""Compatibility facade for ComfyUI workflow sanitization helpers."""

import sys as _sys

from services.comfyui import workflows as _impl

_sys.modules[__name__] = _impl
