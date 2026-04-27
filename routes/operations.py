from routes.appeals import register_appeal_routes
from routes.community import register_community_routes
from routes.files import register_file_routes
from routes.moderation import register_moderation_routes
from routes.reports_notifications import register_reports_notification_routes
from routes.system_admin import register_system_admin_routes


def register_operation_routes(app, deps):
    register_community_routes(app, deps)
    register_file_routes(app, deps)
    register_appeal_routes(app, deps)
    register_reports_notification_routes(app, deps)
    register_moderation_routes(app, deps)
    register_system_admin_routes(app, deps)
