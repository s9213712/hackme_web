"""Compatibility facade for ComfyUI client helpers."""

import sys as _sys

from services.comfyui import client as _impl

_sys.modules[__name__] = _impl
