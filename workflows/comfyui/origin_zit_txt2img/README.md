# ZIT Text-to-Image

ZIT text-to-image workflow converted from origin.

- Source: `workflows/comfyui/origin/image/txt2img/ZIT.json`
- Source Format: `ui_graph`
- Structural Test: `pass` (10 nodes)
- Allowlist Status: `allowlisted`
- Static Unknown Nodes: None
- Live Runtime Check: run `python3 scripts/comfyui/official_workflow_probe.py --preflight-only --only origin_zit_txt2img` against a running ComfyUI.
- Regenerate: `python3 scripts/comfyui/materialize_system_workflows.py`
