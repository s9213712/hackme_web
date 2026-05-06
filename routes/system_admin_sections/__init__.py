from .runtime_routes import register_system_admin_runtime_routes
from .security_routes import register_system_admin_security_routes
from .settings_routes import register_system_admin_settings_routes

__all__ = [
    "register_system_admin_runtime_routes",
    "register_system_admin_security_routes",
    "register_system_admin_settings_routes",
]
