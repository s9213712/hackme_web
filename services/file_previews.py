"""Compatibility facade for file preview helpers."""

import sys as _sys

from services.media import previews as _impl

_sys.modules[__name__] = _impl
