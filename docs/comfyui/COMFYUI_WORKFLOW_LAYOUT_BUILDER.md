# ComfyUI Workflow Layout Builder

The ComfyUI page includes a Workflow Layout Builder for creating reusable
workflow layouts without editing application code.

## Create A Layout

1. Open the ComfyUI module.
2. Use the normal generation form or paste a ComfyUI workflow JSON.
3. Fill in the layout name, description, purpose, ComfyUI version, project
   version, workflow schema version, and optional UI layout JSON.
4. Click `新增版面`.

Each saved layout records the sanitized workflow JSON, UI layout JSON,
required models, required LoRAs, required ControlNet models, required custom
nodes, creator, creation time, and update time. Updates create version history
instead of only overwriting the active row.

## Import JSON

The importer accepts either raw ComfyUI workflow JSON or the project wrapped
workflow preset JSON exported by this site. Import validation rejects malformed
JSON, unsafe absolute paths, external URLs, path traversal, blocked command
fragments, and unsupported layout value types.

If a layout needs models or custom nodes that are not available, the UI shows a
clear dependency warning. Execution returns a stage such as `missing_model`,
`unknown_node`, `sanitize`, `schema_validation`, or `execution_failed`.

## Export JSON

Export returns three forms in one file:

- `raw_workflow_json`: the ComfyUI workflow graph.
- `workflow_preset_json`: the project wrapper containing project version,
  ComfyUI version, workflow schema version, dependencies, timestamps, and
  default parameters.
- `layout_json`: UI layout metadata for panels, node order, node positions, and
  field overrides.

The exported wrapper can be imported again later.

## Permissions

Regular users can create, edit, delete, export, run, duplicate, and set defaults
only for their own layouts. Public and official layouts are readable by other
users. Root can publish owned layouts as official layouts.

## Troubleshooting

- `schema_validation`: fix invalid JSON shape or malformed JSON text.
- `sanitize`: remove absolute paths, external URLs, command fragments, or
  unsafe layout values.
- `missing_model`: install the required checkpoint, VAE, LoRA, ControlNet, or
  upscale model.
- `unknown_node`: install the required ComfyUI custom node package or choose a
  different workflow.
- `version_incompatible`: inspect the project version, ComfyUI version, and
  workflow schema warning before running the layout.
