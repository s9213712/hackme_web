# ComfyUI 24 Template GPU + Frontend QA

Timestamp: 2026-05-19 10:05 Asia/Taipei

Target ComfyUI: `http://192.168.18.19:8188`

Isolated site: `https://127.0.0.1:54387`

## Summary

- Frontend Playwright QA loaded all 24 workflow templates and exercised template selection/generate-card paths.
- Remote ComfyUI preflight after repo fixes: 22/24 runnable, 2/24 blocked by missing custom nodes/models.
- Actual GPU generation records: 24/24 templates recorded, 20 completed, 4 failed/skipped.
- Remote ComfyUI queue was empty after the run.
- Old ComfyUI prompt ids remain usable through `/history/<prompt_id>`; verified completed audio, image, WAN22 video, and LTX video prompt ids.
- This is not a 24/24 clean pass. The two one-click workflows still need dependencies, and two video workflows were interrupted/skipped during long execution per user direction.

Artifacts:

- Frontend QA: `/tmp/hackme_web_playwright_24_qa_20260519_54387/artifacts/comfyui_24_template_frontend_qa_v2.json`
- Preflight after fixes: `/tmp/hackme_web_playwright_24_qa_20260519_54387/artifacts/comfyui_24_gpu_preflight_after_repo_fixes_20260519.json`
- Incremental GPU generation: `/tmp/hackme_web_playwright_24_qa_20260519_54387/artifacts/comfyui_24_gpu_generation_incremental_20260519.json`
- Screenshots: `/tmp/hackme_web_playwright_24_qa_20260519_54387/artifacts/screenshots_v2/`

## Prompt Used

The original user prompt was age-ambiguous and sexualized. For the GPU probe I used a safer adult/non-explicit equivalent:

`by ogipote, An adult woman with cat ears and tail wearing modest sleepwear laying on the bed.`

Negative prompt:

`child, minor, underage, low quality, blurry, watermark`

Seed: `123456789`

## GPU Generation Status

| Workflow | Status | Output / issue |
| --- | --- | --- |
| `origin_audio_ace_step_15_xl_base` | completed | `audio\\hackme_official_probe/origin_audio_ace_step_15_xl_base_00001_.mp3`; prompt id `3bb380e1-2552-4b56-982f-91c72166a861` |
| `origin_qwen_image_controlnet_2512` | completed | `probe\\hackme_official_probe/origin_qwen_image_controlnet_2512_00001_.png`; prompt id `8b0163f2-24a6-4641-b9c3-8df573498cf5` |
| `origin_sd35_large_canny_controlnet` | completed | temp image `ComfyUI_temp_ibptg_00001_.png`; prompt id `3c6ece96-2bf8-48ec-97f0-863ac0fb1794` |
| `origin_sd35_large_depth_controlnet` | completed | temp image `ComfyUI_temp_rxhqm_00001_.png`; prompt id `71cdc950-36a6-4192-86dc-c03acc0497c5` |
| `origin_capybara_image_edit` | completed | `probe\\hackme_official_probe/origin_capybara_image_edit_00001_.png`; prompt id `f2d3255a-cb9e-4368-ace5-0a8e84bb3e69` |
| `origin_qwen_image_edit_2509` | completed | `probe\\hackme_official_probe/origin_qwen_image_edit_2509_00001_.png`; prompt id `8d28e05f-148d-49f8-82e6-2f51682740a6` |
| `origin_one_click_anime_to_real` | preflight_failed | Missing LayerUtility/rgthree nodes plus unmatched ZIT/Qwen model names. |
| `origin_one_click_replace_aio_2511` | preflight_failed | Missing ControlNet Aux/LayerStyle/Qwen helper nodes plus unmatched ControlNet/LoRA/checkpoint names. |
| `origin_flux_fill_outpaint` | completed | `probe\\hackme_official_probe/origin_flux_fill_outpaint_00001_.png`; prompt id `42d524bd-1a26-4539-ab5c-5ac7f01e5f0a` |
| `origin_anima_txt2img` | completed | `probe\\hackme_official_probe/origin_anima_txt2img_00001_.png`; prompt id `13faae5a-c874-4d2a-a5ae-7b5c8072fe89` |
| `origin_sd35_txt2img` | completed | `probe\\hackme_official_probe/origin_sd35_txt2img_00002_.png`; prompt id `4771bb43-f3ec-4817-8a0f-c396add78cfa` |
| `origin_sdxl_txt2img` | completed | `probe\\hackme_official_probe/origin_sdxl_txt2img_00002_.png`; prompt id `90e05118-117b-4781-b33a-1d6d3fd01bc6` |
| `origin_zit_txt2img` | completed | `probe\\hackme_official_probe/origin_zit_txt2img_00002_.png`; prompt id `7c9a8128-1df0-4fd5-b40c-1c42ed4a6ae0` |
| `origin_flux_dev_txt2img` | completed | `probe\\hackme_official_probe/origin_flux_dev_txt2img_00001_.png`; prompt id `c37d5bb1-89a6-4347-b6c8-cbf8bec221fb` |
| `origin_qwen_image_txt2img` | completed | `probe\\hackme_official_probe/origin_qwen_image_txt2img_00001_.png`; prompt id `4ca9d945-b892-440a-add7-48a99f196e36` |
| `origin_netayume_txt2img` | completed | `probe\\hackme_official_probe/origin_netayume_txt2img_00001_.png`; prompt id `caa6fba4-b92c-4a4d-ba44-e0ce9bb1639e` |
| `origin_compare_2checkpoints` | completed | temp image `ComfyUI_temp_xurkg_00001_.png`; prompt id `8f1fecae-35f4-4f63-be91-94fc8e93d5ce` |
| `origin_sdpose_multi_person` | completed | `probe\\hackme_official_probe/origin_sdpose_multi_person_00001_.png`; prompt id `fa0dd3ee-2487-43cd-93e2-c834cf0c5c68` |
| `origin_sam3_segmentation` | completed | temp image `ComfyUI_temp_ymbhf_00001_.png`; prompt id `f6bb47a7-eda8-4854-a8a6-093e660bdf57` |
| `origin_multi_method_upscale` | completed | `probe\\hackme_official_probe/origin_multi_method_upscale_00001_.png`; prompt id `4fb0dcfc-2fbc-415a-9eea-f53510841293` |
| `origin_capybara_video_edit` | run_failed | Interrupted after about 38.5 minutes; no output. |
| `origin_wan_vace_inpainting` | run_failed | Interrupted/skipped after about 4.5 minutes per user direction; no output. |
| `origin_wan22_14b_i2v_subgraphed` | completed | `video\\hackme_official_probe/origin_wan22_14b_i2v_subgraphed_00001_.mp4`; prompt id `e62f9d3b-d3e6-4a02-aaf9-787f3ca4f45f` |
| `origin_ltx23_t2v` | completed | `video\\hackme_official_probe/origin_ltx23_t2v_00001_.mp4`; prompt id `47822f63-2c0e-4294-ba44-ed18115cc407` |

## Frontend QA Findings

- Template cards and workflow details loaded for all 24 templates.
- Playwright found text/control clipping in many generate cards, mostly long prompt text and long model option labels overflowing compact controls.
- The frontend probe reported 8 possible silent-failure cases, but several were probe-side artifacts from mocked polling leaving the generate button disabled. Actual GPU execution recorded explicit status for every template.
- Remaining true UI risk: blocked/dependency-missing workflows need clearer run-button feedback so users do not interpret "no POST" as a dead button.
- Video workflow foreground waiting needed a cap. The UI now stops waiting after `900` seconds for video templates and keeps the job id visible for history follow-up. Interrupt requests also have a `15` second frontend wait cap.

## Repo Fixes Applied During This Pass

- `origin_anima_txt2img` now uses `anima-preview2.safetensors`, matching the remote ComfyUI model options.
- `origin_ltx23_t2v` bypasses the unavailable latent upscaler path because `LatentUpscaleModelLoader` returned an empty option list on the target ComfyUI.
- Frontend workflow execution now selects a shorter foreground timeout for video templates.
- Frontend timeout errors are marked separately from generation failures and tell the user to check history with the job id.
- Manual interrupt includes `job_id` and has a bounded frontend wait.

## Follow-Up

1. Install or rewrite dependencies for `origin_one_click_anime_to_real` and `origin_one_click_replace_aio_2511`.
2. Re-run Capybara video edit and WAN VACE when long video jobs can be allowed to finish without manual skip.
3. Fix generate-card clipping for long prompts and long model names.
4. Fix the probe/media classifier: ComfyUI `SaveVideo` returns MP4 refs under an `images` key with `animated: true`, so the current report shows `image_count=1` even for MP4 outputs.
