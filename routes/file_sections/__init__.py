from .admin_storage_routes import register_file_admin_storage_routes
from .remote_download_routes import register_file_remote_download_routes
from .share_preview_routes import register_file_share_preview_routes

__all__ = [
    "register_file_admin_storage_routes",
    "register_file_remote_download_routes",
    "register_file_share_preview_routes",
]
