# Flux Dev Full Text-to-Image

Flux dev full text-to-image workflow converted from origin.

- Source: `workflows/comfyui/origin/image/txt2img/flux_dev_full_text_to_image.json`
- Source Format: `ui_graph`
- Structural Test: `pass` (9 nodes)
- Allowlist Status: `allowlisted`
- Static Unknown Nodes: None
- Live Runtime Check: run `python3 scripts/comfyui/official_workflow_probe.py --preflight-only --only origin_flux_dev_txt2img` against a running ComfyUI.
- Regenerate: `python3 scripts/comfyui/materialize_system_workflows.py`
