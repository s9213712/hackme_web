# ComfyUI Origin Workflow Formal Probe

Timestamp: 2026-05-19 01:01 Asia/Taipei

Target ComfyUI: `http://192.168.18.19:8188`

Command:

```bash
python3 /home/s92137/hackme_web/scripts/comfyui/official_workflow_probe.py \
  --comfyui-url http://192.168.18.19:8188 \
  --formal-params \
  --include-heavy \
  --force-run \
  --continue-on-fail \
  --no-fetch-outputs \
  --timeout 3600 \
  --request-timeout 60 \
  --json-out /tmp/comfyui_origin_run_formal_safe_20260519.json
```

## Summary

- Total workflows tested: 24
- Initial full execution completed: 4
- Initial ComfyUI validation/runtime failed: 16
- Initial blocked before queueing by prompt safety gate: 4
- Post-fix acceptance-only pass: 19 accepted, 5 failed
- Full-output sanity check after clarification: 1 completed (`origin_sam3_segmentation`)
- Raw JSON report: `/tmp/comfyui_origin_run_formal_safe_20260519.json`
- Post-fix acceptance JSON report: `/tmp/comfyui_origin_acceptance_all_final_20260519.json`
- Full-output sanity JSON report: `/tmp/comfyui_origin_sam3_full_output_20260519.json`
- Mode: formal workflow parameters, heavy workflows included, preflight failures force-queued once, generated output references validated without downloading media bytes.

## Initial Full-Run Status

| Workflow | Status | Notes |
| --- | --- | --- |
| `origin_audio_ace_step_15_xl_base` | Failed | `TextEncodeAceStepAudio1.5` validation rejected missing required inputs such as lyrics/BPM/sampling params. |
| `origin_qwen_image_controlnet_2512` | Failed | Missing ControlNet/LoRA model files; ComfyUI also rejected missing ControlNet apply inputs. |
| `origin_sd35_large_canny_controlnet` | Failed | ComfyUI rejected missing `ImageScale`/related widget inputs in converted UI graph. |
| `origin_sd35_large_depth_controlnet` | Failed | ComfyUI rejected missing ControlNet/sampler required inputs in converted UI graph. |
| `origin_capybara_image_edit` | Failed | ComfyUI rejected missing resize/CLIP vision/batch inputs in converted UI graph. |
| `origin_qwen_image_edit_2509` | Failed | Missing Qwen edit LoRA plus return type mismatch in converted UI graph links. |
| `origin_one_click_anime_to_real` | Failed | Missing custom nodes and model files; first hard failure was `LayerUtility: ImageReelComposit`. |
| `origin_one_click_replace_aio_2511` | Failed | Missing many custom nodes and model files; first hard failure was `AIO_Preprocessor`. |
| `origin_flux_fill_outpaint` | Failed | ComfyUI rejected missing outpaint padding/feather inputs. |
| `origin_anima_txt2img` | Failed | Missing `anima-preview3-base.safetensors` diffusion model. |
| `origin_sd35_txt2img` | Completed | Output ref: `probe\\hackme_official_probe/origin_sd35_txt2img_00001_.png`; elapsed 94.9s. |
| `origin_sdxl_txt2img` | Completed | Output ref: `probe\\hackme_official_probe/origin_sdxl_txt2img_00001_.png`; elapsed 70.4s. |
| `origin_zit_txt2img` | Blocked | Built-in prompt was sexualized minor/age-ambiguous content; not queued. |
| `origin_flux_dev_txt2img` | Blocked | Built-in prompt was sexualized minor/age-ambiguous content; not queued. |
| `origin_qwen_image_txt2img` | Blocked | Built-in prompt was sexualized minor/age-ambiguous content; not queued. |
| `origin_netayume_txt2img` | Failed | ComfyUI rejected missing `StringConcatenate` delimiter inputs. |
| `origin_compare_2checkpoints` | Completed | Output ref: temp image from compare workflow; elapsed 100.1s. |
| `origin_sdpose_multi_person` | Failed | ComfyUI rejected invalid resize node input values and graph type mismatches. |
| `origin_sam3_segmentation` | Completed | Output ref: temp image from SAM3 utility workflow; elapsed 15.6s. |
| `origin_multi_method_upscale` | Blocked | Built-in prompt was sexualized minor/age-ambiguous content; not queued. |
| `origin_capybara_video_edit` | Failed | ComfyUI rejected missing video input/format/codec and invalid video length. |
| `origin_wan_vace_inpainting` | Failed | Missing Wan LoRA and `LoadVideo` file; video output format/codec inputs missing. |
| `origin_wan22_14b_i2v_subgraphed` | Failed | ComfyUI rejected video graph type mismatches and missing output format/codec. |
| `origin_ltx23_t2v` | Failed | Missing LTX LoRA; ComfyUI also rejected missing math expression/output format/codec inputs. |

## Post-Fix Acceptance Status

Acceptance-only means the prompt was accepted by ComfyUI validation and immediately interrupted by the probe before long generation. This run verifies template structure and current API compatibility, not final image/video quality.

| Workflow | Acceptance | Remaining issue |
| --- | --- | --- |
| `origin_audio_ace_step_15_xl_base` | Accepted | None in acceptance validation. |
| `origin_qwen_image_controlnet_2512` | Accepted | Preflight still reports missing `Qwen-Image-2512-Fun-Controlnet-Union-2602.safetensors` and `Qwen-Image-Lightning-4steps-V1.0.safetensors`, but ComfyUI accepted the prompt after the resize mapping fix. |
| `origin_sd35_large_canny_controlnet` | Accepted | Preflight reports local ControlNet name mismatch/missing file. |
| `origin_sd35_large_depth_controlnet` | Accepted | Preflight reports local ControlNet name mismatch/missing file. |
| `origin_capybara_image_edit` | Accepted | None in acceptance validation. |
| `origin_qwen_image_edit_2509` | Failed | Missing `Qwen-Image-Edit-2509-Lightning-4steps-V1.0-bf16.safetensors` LoRA files. |
| `origin_one_click_anime_to_real` | Failed | Missing LayerStyle/rgthree-style custom nodes and related Qwen/ZIT model files. |
| `origin_one_click_replace_aio_2511` | Failed | Missing ControlNet Aux, LayerStyle, Qwen edit helper nodes, rgthree node, and related model files. |
| `origin_flux_fill_outpaint` | Accepted | None in acceptance validation. |
| `origin_anima_txt2img` | Failed | Missing `anima-preview3-base.safetensors` diffusion model. |
| `origin_sd35_txt2img` | Accepted | None in acceptance validation. |
| `origin_sdxl_txt2img` | Accepted | None in acceptance validation. |
| `origin_zit_txt2img` | Accepted | Unsafe built-in prompt replaced with safe adult/non-explicit prompt. |
| `origin_flux_dev_txt2img` | Accepted | Unsafe built-in prompt replaced with safe adult/non-explicit prompt. |
| `origin_qwen_image_txt2img` | Accepted | Unsafe built-in prompt replaced with safe adult/non-explicit prompt. |
| `origin_netayume_txt2img` | Accepted | `StringConcatenate.delimiter` compatibility default added. |
| `origin_compare_2checkpoints` | Accepted | None in acceptance validation. |
| `origin_sdpose_multi_person` | Accepted | Resize, VAE, bbox/image, blend, and batch-size conversion fixed. |
| `origin_sam3_segmentation` | Accepted | None in acceptance validation. |
| `origin_multi_method_upscale` | Accepted | Unsafe built-in prompt replaced with safe adult/non-explicit prompt. |
| `origin_capybara_video_edit` | Accepted | Video input, scheduler, CLIP vision, resize, VAE, format/codec conversion fixed. |
| `origin_wan_vace_inpainting` | Accepted | Preflight still reports missing Wan LoRA files, but ComfyUI accepted the prompt with force-run. |
| `origin_wan22_14b_i2v_subgraphed` | Accepted | Video latent/output conversion fixed. |
| `origin_ltx23_t2v` | Failed | Missing `ltx-2.3-22b-distilled-lora-384.safetensors` and latent upscaler model. |

## Full-Output Sanity Check

To produce actual media output, do not use `--acceptance-only` and do not use `--no-fetch-outputs`.

| Workflow | Status | Output |
| --- | --- | --- |
| `origin_sam3_segmentation` | Completed | Prompt id `cae73521-c7de-42a6-aa76-a53c78059334`; image ref `ComfyUI_temp_ndduv_00001_.png`; 433 bytes fetched. |

## Tooling Changes

- `scripts/comfyui/official_workflow_probe.py` now supports formal mode, force-run mode, output-reference-only execution, and custom parameter overrides.
- Acceptance-only probes now interrupt and delete the just-submitted prompt id so validation does not leave queued probe jobs behind.
- Acceptance-only result details now explicitly say output was intentionally skipped.
- Custom override examples:
  - `--custom-params --custom-prompt "adult woman with cat ears in a cozy bedroom" --custom-steps 20`
  - `--custom-param-json '{"seed": 123, "node_inputs": {"3": {"steps": 12}}}'`
- The probe now ignores model inputs that are graph links, so linked model nodes are not falsely reported as missing model filenames.
- The probe blocks sexualized minor or age-ambiguous childlike prompts before queueing.

## Follow-Up

1. Install or remap the missing Qwen Edit, ANIMA, LTX, and one-click workflow model files if those templates must fully execute on `192.168.18.19`.
2. Install the missing custom-node packs for the one-click workflows, especially LayerStyle, ControlNet Aux, Qwen edit helper nodes, and rgthree.
3. Re-run full generation only for the accepted templates that matter operationally; acceptance-only has already verified the API prompt structure.
4. Keep user-provided test prompts unambiguously adult and non-explicit when bedroom/cat-ear/anime prompts are used.
