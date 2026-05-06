"""Compatibility facade for E2EE media streaming helpers."""

import sys as _sys

from services.media import e2ee_streaming as _impl

_sys.modules[__name__] = _impl
