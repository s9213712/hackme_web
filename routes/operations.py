from routes.appeals import register_appeal_routes
from routes.moderation import register_moderation_routes
from routes.system_admin import register_system_admin_routes


def register_operation_routes(app, deps):
    register_appeal_routes(app, deps)
    register_moderation_routes(app, deps)
    register_system_admin_routes(app, deps)
