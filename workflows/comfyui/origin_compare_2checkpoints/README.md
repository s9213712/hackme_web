# Compare Two Checkpoints

Two-checkpoint comparison workflow converted from origin.

- Source: `workflows/comfyui/origin/utility/compare/compare_2checkpoints.json`
- Source Format: `ui_graph`
- Structural Test: `pass` (12 nodes)
- Allowlist Status: `allowlisted`
- Static Unknown Nodes: None
- Live Runtime Check: run `python3 scripts/comfyui/official_workflow_probe.py --preflight-only --only origin_compare_2checkpoints` against a running ComfyUI.
- Regenerate: `python3 scripts/comfyui/materialize_system_workflows.py`
