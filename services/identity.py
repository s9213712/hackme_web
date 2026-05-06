"""Compatibility facade for identity helpers."""

import sys as _sys

from services.security import identity as _impl

_sys.modules[__name__] = _impl
