# Multi-Compare Checkpoints Test

Test workflow derived from Compare Two Checkpoints without overwriting the original bundle.

- Source: `workflows/comfyui/origin/utility/compare/compare_2checkpoints.json`
- Source Format: `ui_graph`
- Structural Test: `pass` (12 base nodes)
- Dynamic Runtime: the project UI can add checkpoint branches and shared LoRA layers before execution.
- Allowlist Status: `allowlisted`
- Static Unknown Nodes: None
- Live Runtime Check: run `python3 scripts/comfyui/official_workflow_probe.py --preflight-only --only origin_multi_compare_checkpoints_test` against a running ComfyUI.
