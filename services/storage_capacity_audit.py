"""Compatibility facade for storage capacity helpers."""

import sys as _sys

from services.storage import capacity_audit as _impl

_sys.modules[__name__] = _impl
