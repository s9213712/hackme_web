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

## Visual Node / Line Builder

The standalone visual builder is available from the ComfyUI workflow area. It
lets users add nodes, drag nodes, connect output ports to input ports, delete
edges, import existing workflow JSON, and send the generated workflow/layout
back to the main ComfyUI page for saving.

Supported built-in node groups include:

- Model / text: checkpoint, prompt encoders, LoRA, VAE.
- Image / latent / inpaint: image loaders, mask loader, VAE encode/decode,
  outpaint pad, KSampler, KSampler Advanced, SaveImage.
- Control / upscale: ControlNet loader/apply and upscale model/image nodes.
- Custom / API: a placeholder node where users can set the actual ComfyUI
  `class_type` and inputs without writing application code.

Custom/API nodes are intentionally treated as placeholders until a live
ComfyUI `object_info` check can verify their exact schema. The builder preserves
their `class_type`, inputs, outputs, and layout metadata during import/export.

## Live Node Catalog

The visual builder can load a compact node catalog from:

```text
GET /api/comfyui/node-catalog
```

The endpoint requires login and uses the configured ComfyUI backend for the
current user. It calls ComfyUI `/object_info`, then returns only a safe editor
summary: `class_type`, display name, category, input schema summary, output
names, and a paid/API-node flag. It does not return secrets or raw workflow
payloads.

After clicking `載入節點目錄`, installed custom nodes appear in the toolbox and
can be added directly to the node graph. Non-link inputs render as normal form
controls where possible, so users do not need to edit JSON for common fields.
Link inputs still connect through the node/line UI.

Catalog and imported custom nodes are exported in `required_custom_nodes` with
their `class_type`, display name, category, and paid/API flag. This lets another
server warn users about missing custom node packages before execution.

## Import JSON

The importer accepts either raw ComfyUI workflow JSON or the project wrapped
workflow preset JSON exported by this site. Import validation rejects malformed
JSON, unsafe absolute paths, external URLs, path traversal, blocked command
fragments, inline API keys/tokens/secrets, and unsupported layout value types.

If a layout needs models or custom nodes that are not available, the UI shows a
clear dependency warning. Execution returns a stage such as `missing_model`,
`unknown_node`, `sanitize`, `schema_validation`, or `execution_failed`.

## Paid / API Nodes

ComfyUI API nodes that use ComfyUI Account credits are supported with a server
side gate:

- Root must enable paid/API nodes in server settings.
- Root must save the ComfyUI Account API Key in server settings.
- Workflow JSON must not contain inline keys, tokens, cookies, or secrets.
- Execution detects likely paid/API nodes and requires explicit confirmation.
- The backend injects the key only into the ComfyUI `/prompt` payload as
  `extra_data.api_key_comfy_org`.
- Exports, layout JSON, run records, and audit summaries must not contain the
  cleartext key.

Credit balance is not queried from this app because ComfyUI does not currently
document a stable REST endpoint for it. Users should inspect credits in the
ComfyUI UI under Settings / Credits.

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
  unsafe layout values. Also remove inline API keys, tokens, cookies, or
  secrets; configure the ComfyUI Account API Key in server settings instead.
- `missing_model`: install the required checkpoint, VAE, LoRA, ControlNet, or
  upscale model.
- `unknown_node`: install the required ComfyUI custom node package or choose a
  different workflow.
- `version_incompatible`: inspect the project version, ComfyUI version, and
  workflow schema warning before running the layout.
- `paid_api_nodes_disabled`: ask root to enable paid/API nodes.
- `paid_api_key_missing`: ask root to save the ComfyUI Account API Key.
- `paid_api_confirmation_required`: confirm the workflow may consume credits.

## Verification

Run the focused checks after touching the builder:

```bash
node --check public/js/comfyui-workflow-editor.js
python3 scripts/testing/playwright_comfyui_workflow_builder_check.py
PYTHONPATH=/home/s92137/hackme_web pytest -q tests/comfyui/test_paid_api_nodes.py tests/comfyui/workflows/test_paid_api_workflow_gate.py
```
