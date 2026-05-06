"""Compatibility facade for media streaming helpers."""

import sys as _sys

from services.media import streaming as _impl

_sys.modules[__name__] = _impl
