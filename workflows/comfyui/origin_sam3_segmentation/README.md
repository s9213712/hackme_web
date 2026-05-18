# SAM3 Image Segmentation Utility

SAM3 segmentation utility workflow converted from origin.

- Source: `workflows/comfyui/origin/utility/segmentation/utility_image_segment_sam3.json`
- Source Format: `ui_graph`
- Structural Test: `pass` (7 nodes)
- Allowlist Status: `allowlisted`
- Static Unknown Nodes: None
- Live Runtime Check: run `python3 scripts/comfyui/official_workflow_probe.py --preflight-only --only origin_sam3_segmentation` against a running ComfyUI.
- Regenerate: `python3 scripts/comfyui/materialize_system_workflows.py`
