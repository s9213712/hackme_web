"""Compatibility facade for cloud-drive helpers."""

import sys as _sys

from services.storage import cloud_drive as _impl

_sys.modules[__name__] = _impl
