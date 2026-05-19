# Multi-Method Upscale Utility - Mode Test

Experimental copy of Multi-Method Upscale Utility. It keeps the original graph,
but the app can run it as model upscale, latent upscale, or a combined pass
without changing the original template.

- Source: `workflows/comfyui/origin/utility/upscale/多種放大方法.json`
- Source Format: `ui_graph`
- Structural Test: `pass` (18 nodes)
- Allowlist Status: `allowlisted`
- Static Unknown Nodes: None
- Live Runtime Check: run `python3 scripts/comfyui/official_workflow_probe.py --preflight-only --only origin_multi_method_upscale_mode_test` against a running ComfyUI.
- Regenerate: `python3 scripts/comfyui/materialize_system_workflows.py`
