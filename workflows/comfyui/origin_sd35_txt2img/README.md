# SD3.5 Text-to-Image

SD3.5 text-to-image workflow converted from origin.

- Source: `workflows/comfyui/origin/image/txt2img/SD3.5.json`
- Source Format: `api_prompt`
- Structural Test: `pass` (7 nodes)
- Allowlist Status: `allowlisted`
- Static Unknown Nodes: None
- Live Runtime Check: run `python3 scripts/comfyui/official_workflow_probe.py --preflight-only --only origin_sd35_txt2img` against a running ComfyUI.
- Regenerate: `python3 scripts/comfyui/materialize_system_workflows.py`
