"""Compatibility facade for video-platform helpers."""

import sys as _sys

from services.media import videos as _impl

_sys.modules[__name__] = _impl
