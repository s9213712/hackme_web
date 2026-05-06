"""Compatibility facade for server-mode context helpers."""

import sys as _sys

from services.server_mode import context as _impl

_sys.modules[__name__] = _impl
