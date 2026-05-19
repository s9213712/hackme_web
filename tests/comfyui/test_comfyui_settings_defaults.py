import os

from services.comfyui.settings import COMFYUI_DEFAULT_SETTINGS, DEFAULT_COMFYUI_REMOTE_API_URL
from services.platform.settings import DEFAULT_SETTINGS


def test_comfyui_defaults_use_lan_remote_api_mode():
    expected_url = os.environ.get("COMFYUI_API_URL", "http://192.168.18.19:8188").rstrip("/")
    assert DEFAULT_COMFYUI_REMOTE_API_URL == expected_url
    assert COMFYUI_DEFAULT_SETTINGS["comfyui_connection_mode"] == "remote"
    assert COMFYUI_DEFAULT_SETTINGS["comfyui_remote_api_url"] == DEFAULT_COMFYUI_REMOTE_API_URL
    assert COMFYUI_DEFAULT_SETTINGS["comfyui_allow_in_process_diffusers"] is False
    assert DEFAULT_SETTINGS["comfyui_remote_api_url"] == DEFAULT_COMFYUI_REMOTE_API_URL
    assert DEFAULT_SETTINGS["comfyui_allow_in_process_diffusers"] is False
