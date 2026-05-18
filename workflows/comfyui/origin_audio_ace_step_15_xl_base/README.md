# ACE-Step 1.5 XL Base（T2A）

ACE-Step 1.5 text-to-audio / music workflow converted from origin.

- Source: `workflows/comfyui/origin/audio/t2a/audio_ace_step1_5_xl_base.json`
- Source Format: `ui_graph`
- Structural Test: `pass` (10 nodes)
- Allowlist Status: `allowlisted`
- Static Unknown Nodes: None
- Live Runtime Check: run `python3 scripts/comfyui/official_workflow_probe.py --preflight-only --only origin_audio_ace_step_15_xl_base` against a running ComfyUI.
- Regenerate: `python3 scripts/comfyui/materialize_system_workflows.py`
