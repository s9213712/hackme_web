# ComfyUI Flux Fill Inpaint Template Check

Date: 2026-05-19 10:49 Asia/Taipei

## Findings

1. Fixed: new origin workflow was not registered as a system bundle.
   - `workflows/comfyui/origin/image/edit/flux_fill_inpaint_example.json` existed, but the materialized system registry did not include it.
   - Evidence: `tests/comfyui/test_system_workflows.py::test_every_origin_workflow_has_converted_bundle` failed with extra origin path `image/edit/flux_fill_inpaint_example.json`.
   - Fix: added `origin_flux_fill_inpaint` to `scripts/comfyui/materialize_system_workflows.py`, `services/comfyui/template/seeding.py`, and system workflow tests.

2. Fixed: stale imported bundle would have polluted runtime templates.
   - A non-standard imported bundle directory `workflows/comfyui/origin_flux_inpaint/` was present alongside the correct system bundle.
   - Impact: first-boot seeding copies every complete workflow bundle directory, so the stale imported card could appear as an extra template.
   - Fix: removed the stale imported bundle and regenerated the canonical `workflows/comfyui/origin_flux_fill_inpaint/` bundle.

3. Fixed: Windows `:Zone.Identifier` marker files were present.
   - Removed `README.md:Zone.Identifier`, `manifest.json:Zone.Identifier`, and `workflow.json:Zone.Identifier`.

4. Fixed: workflow template image fields rejected freshly selected local files.
   - The template runner only accepted `cloudFileId` image assignments, so a local upload in a template card still hit the safe-remap warning before execution.
   - Fix: added `/api/comfyui/import-uploaded-image` and frontend auto-import before the remap gate. The workflow still executes with cloud-drive file IDs; local files are first stored as `standard_plain` cloud files and uploaded to ComfyUI input.

5. Fixed: LoadImage remap rejected `scan_status='not_required'`.
   - Files stored while scanning is disabled or not applicable are valid cloud-drive inputs elsewhere in the app, but the ComfyUI workflow remap gate only allowed `clean`.
   - Fix: allow `not_required` as a safe scan status while keeping `skipped` behind the existing explicit opt-in.

6. Fixed: workflow template seed-after mode was hidden in the legacy form.
   - Template users could edit seed values in the template card, but the after-run seed behavior (`fixed`, random, `+1`, `-1`) was only available in the generic form that is hidden for templates.
   - Fix: render a `任務後 Seed` selector beside template `seed` / `noise_seed` fields and use the current template seed as the `+1` / `-1` base after every workflow task.

7. Fixed: templates with repeated prompt fields did not ask whether prompts should be shared.
   - Some workflows expose multiple positive or negative `CLIPTextEncode` / `CLIPTextEncodeFlux` fields for one model path. Reusing the generic positive/negative labels made it unclear whether edits should apply globally or only to a single node.
   - Fix: detect repeated positive or negative prompt fields, show a `提示詞共用` selector before the template cards, and block execution until the user chooses either global sharing or independent fields. In shared mode, edits sync only fields with the same prompt role.

## Validation

- `python3 scripts/comfyui/materialize_system_workflows.py`: 25 origin bundles materialized; `origin_flux_fill_inpaint` is 12 nodes and allowlisted.
- `pytest -q tests/comfyui`: passed after upload-import, `not_required` remap, seed-after, and prompt-sharing regression coverage.
- `pytest tests/comfyui/storage/test_comfyui_storage.py tests/comfyui/test_template_run_gate.py tests/comfyui/test_template_remap.py`: 55 passed.
- `pytest -q tests/frontend/comfyui/test_comfyui_workflow_template_ui.py`: 16 passed.
- `pytest -q tests/frontend/comfyui`: 62 passed.
- `node --check public/js/36-comfyui.js` and `node --check public/js/36-comfyui-workflows.js`: passed.
- `pytest tests/comfyui/test_template_seeding.py tests/comfyui/test_system_workflows.py`: 115 passed.
- `git diff --check`: passed.
- Fresh isolated server on `https://127.0.0.1:5009`: seeded 25 official ComfyUI workflow bundles.
- Fresh isolated server on `https://127.0.0.1:5010`: seeded 25 official ComfyUI workflow bundles and includes the uploaded-image import, `not_required` remap, template seed-after, and prompt-sharing fixes.
- `curl -k -sS -I https://127.0.0.1:5010/`: returned `HTTP/1.1 200 OK`.
- Isolated asset check: `public/index.html`, `public/js/36-comfyui-workflows.js`, and `public/styles.css` include `20260519-template-prompt-sharing` and the `data-comfyui-template-prompt-sharing` UI hook.
- `/api/comfyui/workflows`: returned exactly one `origin_flux_fill_inpaint` official preset with `purpose=inpaint`, `generation_mode=inpaint`.
- LAN ComfyUI preflight at `http://192.168.18.19:8188`: `preflight_pass`, no missing nodes, no missing models.
- LAN ComfyUI acceptance-only: accepted prompt and returned prompt id `94017386-de0f-4985-a2c3-2ad52a897b81`; output generation intentionally skipped.

## Notes

- The temporary validation server on port `5009` was stopped after checks.
- The previously started isolated server on port `5008` was left running, but it was started before these fixes and does not reflect the new materialized bundle set.
- A newer isolated server on port `5010` is running from `/tmp/hackme_web_template_prompt_sharing_5010/hackme_web` and reflects the current fixes.
