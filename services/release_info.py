"""Compatibility facade for services.platform.release_info."""

from services.platform import release_info as _impl

APP_NAME = "hackme_web"
APP_RELEASE_ID = "2026.05.07-154"

assert APP_NAME == _impl.APP_NAME
assert APP_RELEASE_ID == _impl.APP_RELEASE_ID
