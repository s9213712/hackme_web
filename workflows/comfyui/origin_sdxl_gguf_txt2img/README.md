# SDXL GGUF Text-to-Image (ComfyUI-GGUF)

SDXL text-to-image workflow for ComfyUI-GGUF native UNet files.

- Source: `workflows/comfyui/origin/image/txt2img/sdxl_gguf_comfyui.json`
- Source Format: `api_prompt`
- Structural Test: `pass` (9 nodes)
- Allowlist Status: `allowlisted`
- Static Unknown Nodes: None
- Required custom node: `ComfyUI-GGUF` with `UnetLoaderGGUF`.
- Model location: place GGUF UNet files under `ComfyUI/models/unet/`.
- Live Runtime Check: run `python3 scripts/comfyui/official_workflow_probe.py --preflight-only --only origin_sdxl_gguf_txt2img` against a running ComfyUI.
