# ANIMA Text-to-Image

ANIMA text-to-image workflow converted from origin.

- Source: `workflows/comfyui/origin/image/txt2img/ANIMA.json`
- Source Format: `api_prompt`
- Structural Test: `pass` (10 nodes)
- Allowlist Status: `allowlisted`
- Static Unknown Nodes: None
- Live Runtime Check: run `python3 scripts/comfyui/official_workflow_probe.py --preflight-only --only origin_anima_txt2img` against a running ComfyUI.
- Regenerate: `python3 scripts/comfyui/materialize_system_workflows.py`
