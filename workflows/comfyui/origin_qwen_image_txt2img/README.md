# Qwen Image Text-to-Image

Qwen image text-to-image workflow converted from origin.

- Source: `workflows/comfyui/origin/image/txt2img/image_qwen_image.json`
- Source Format: `ui_graph`
- Structural Test: `pass` (14 nodes)
- Allowlist Status: `allowlisted`
- Static Unknown Nodes: None
- Live Runtime Check: run `python3 scripts/comfyui/official_workflow_probe.py --preflight-only --only origin_qwen_image_txt2img` against a running ComfyUI.
- Regenerate: `python3 scripts/comfyui/materialize_system_workflows.py`
