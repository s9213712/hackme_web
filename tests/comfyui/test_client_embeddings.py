from services.comfyui.client import ComfyUIClient, ComfyUIError


class _StubComfyUIClient(ComfyUIClient):
    def __init__(self, responses):
        super().__init__("http://stub-comfyui")
        self.responses = list(responses)
        self.paths = []

    def _json_request(self, path, **kwargs):
        self.paths.append(path)
        if not self.responses:
            raise AssertionError(f"unexpected request: {path}")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def test_get_embeddings_falls_back_to_lora_manager_when_native_endpoint_is_html():
    client = _StubComfyUIClient([
        ComfyUIError("ComfyUI 回應不是 JSON"),
        {
            "items": [
                {"file_name": "Smooth_Negative-neg", "file_path": "E:/ComfyUI/models/embeddings/Smooth_Negative-neg.safetensors"},
                {"file_path": "D:/ComfyUI/ComfyUI_windows_portable/ComfyUI/models/embeddings/easynegative.pt"},
            ],
            "total_pages": 1,
        },
    ])

    assert client.get_embeddings() == ["Smooth_Negative-neg", "easynegative.pt"]
    assert client.paths[0] == "/embeddings"
    assert client.paths[1] == "/api/lm/embeddings/list?page=1&page_size=200"


def test_get_embeddings_reads_all_lora_manager_pages():
    client = _StubComfyUIClient([
        ComfyUIError("ComfyUI 回應不是 JSON"),
        {"items": [{"file_name": "first"}], "total_pages": 2},
        {"items": [{"file_name": "second"}], "total_pages": 2},
    ])

    assert client.get_embeddings() == ["first", "second"]
