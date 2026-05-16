from tests.comfyui._integration_suite import (
    test_comfyui_connection_test_requires_root_and_valid_endpoint,
    test_comfyui_local_start_template_download_requires_root,
    test_comfyui_status_reports_offline_backend,
    test_comfyui_status_warns_when_models_are_on_windows_mount,
    test_local_comfyui_connection_test_attempts_autostart,
    test_local_comfyui_connection_test_reports_startup_failure_detail,
    test_local_comfyui_start_reuses_existing_backend,
    test_local_comfyui_status_reports_starting_when_process_alive,
    test_root_can_download_local_comfyui_start_template,
    test_root_can_stop_local_comfyui_with_tracked_pid,
    test_root_can_test_unsaved_comfyui_endpoint,
    test_root_comfyui_stop_requires_root,
)
