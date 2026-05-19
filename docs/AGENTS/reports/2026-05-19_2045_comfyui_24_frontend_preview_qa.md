# ComfyUI 24 Template Frontend Preview QA

- Date: 2026-05-19
- Frontend under test: `https://127.0.0.1:5007`
- ComfyUI backend under test: `http://192.168.18.19:8188`
- Default-configuration GPU run: 24 official frontend templates
- Result artifact: `/tmp/hackme_comfyui_template_default_qa_full_20260519/results.json`
- Contact sheets:
  - `/tmp/hackme_comfyui_template_default_qa_full_20260519/contact_sheet_01.jpg`
  - `/tmp/hackme_comfyui_template_default_qa_full_20260519/contact_sheet_02.jpg`
- Frontend preview checks:
  - `/tmp/hackme_comfyui_template_default_qa_full_20260519/frontend_preview_checks/frontend_preview_check.json`
  - `/tmp/hackme_comfyui_template_default_qa_full_20260519/frontend_preview_checks/wan22_existing_job_preview.png`
  - `/tmp/hackme_comfyui_template_default_qa_full_20260519/frontend_preview_checks/synthetic_media_preview.png`

## Summary

- 24 templates were submitted through the frontend with defaults.
- 13 passed cleanly.
- 3 completed but had output or preview issues.
- 8 failed or were rejected before usable output.
- A separate direct preflight against `192.168.18.19:8188` checked 25 system workflows; only `origin_ltx23_t2v` failed preflight.

## High Priority Findings

1. `WAN 2.2 14B I2V Subgraphed` generated an MP4 but the frontend treated it as an image.
   - Existing job `c47c09a30e02c74f62fa140a` returned `result_image_count=1`, `result_media_count=0`.
   - Hydrated output MIME was `video/mp4`.
   - DOM had `imageCount=1`, `videoCount=0`.
   - Screenshot shows a broken `<img>` preview, not a playable `<video>`.
   - Fix applied in repo: `services/comfyui/execution.py` now routes `SaveVideo`/video-extension outputs to media even if ComfyUI reports them under `images`.

2. SDXL template user inputs were polluted by global/manual model fields during the QA run.
   - `origin_sdxl_txt2img` prepared node `4.ckpt_name` as `sd3.5_large_fp8_scaled.safetensors` even though the SDXL workflow default is `sd_xl_base_1.0.safetensors`.
   - This matches the earlier manual-field override concern and likely caused the SDXL job error.
   - Fix applied in repo: template MODEL fields now keep template defaults by default and expose an edit button for customization. LoRA selector fields remain selectable.

3. `LTX 2.3 Text-to-Video` is still rejected by the app because the running ComfyUI backend reports zero latent upscale models.
   - Direct backend check: `GET http://192.168.18.19:8188/object_info/LatentUpscaleModelLoader`
   - Returned `options: []` for `model_name`.
   - Repo-side gate already supports rewriting `ltx-2.3-spatial-upscaler-x2-1.1.safetensors` to a subfolder option such as `3/ltx-2.3-spatial-upscaler-x2-1.1.safetensors`; the blocker is that this 8188 process is not exposing any options for that loader.

4. `Qwen Image 2512 ControlNet` completed but the visible outputs are not acceptable final prompt images.
   - Output 1 was almost black.
   - Output 2 was an edge/preprocess-looking image.
   - Contact sheet confirms the foreground preview is not a normal generated image.

5. `WAN VACE Video Inpainting` completed on the backend but produced 73 image outputs and 0 media outputs.
   - Job `b2803f437c3d067cd547cffb`: `completed`, `已完成，共 73 張圖片、0 個媒體輸出`.
   - The template declares image and video output kinds, but the current app result has no playable media item.

## Template Results

| # | Template | Status | Outputs | Notes |
|---|---|---|---|---|
| 01 | ACE-Step 1.5 XL Base | Passed | 0 image, 1 media | Audio preview works. |
| 02 | Qwen Image 2512 ControlNet | Completed with issues | 2 images | Black/preprocess-like outputs. |
| 03 | SD3.5 Large Canny ControlNet | Rejected | 0 | Missing `SD35\sd3.5_large_controlnet_canny.safetensors`. |
| 04 | SD3.5 Large Depth ControlNet | Rejected | 0 | Missing `SD35\sd3.5_large_controlnet_depth.safetensors`. |
| 05 | Capybara v0.1 Image Edit | Rejected | 0 | Missing `sigclip_vision_patch14_384.safetensors`. |
| 06 | Qwen Image Edit 2509 | Passed | 2 images | Gallery showed both outputs. |
| 07 | Flux Fill Inpaint | Passed | 1 image | Preview works. |
| 08 | One-Click Anime to Real | Rejected | 0 | Official example image exceeds 8 MB upload/import limit. |
| 09 | Flux Fill Outpaint | Passed | 1 image | Preview works. |
| 10 | ANIMA Text-to-Image | Passed | 1 image | Prompt-following image. |
| 11 | SD3.5 Text-to-Image | Passed | 1 image | Prompt-following image. |
| 12 | SDXL Text-to-Image | Job error | 0 | Model field override bug found and fixed in repo. |
| 13 | ZIT Text-to-Image | Passed | 1 image | Prompt-following image. |
| 14 | Flux Dev Full Text-to-Image | Passed | 1 image | Prompt-following image. |
| 15 | Qwen Image Text-to-Image | Passed | 1 image | Prompt-following image. |
| 16 | NetaYume Text-to-Image | Passed | 1 image | Prompt-following image. |
| 17 | Multi-Compare Checkpoints Test | Passed | 2 images | Both comparison outputs visible with labels. |
| 18 | SDPose Multi-Person Utility | Completed with issues | 2 images | One output is almost black; preview output exists. |
| 19 | SAM3 Image Segmentation Utility | Passed | 2 images | Image and mask both visible. |
| 20 | Multi-Method Upscale Utility | Passed | 1 image | First-stage output label visible. |
| 21 | Capybara v0.1 Video Edit | Rejected | 0 | Missing `sigclip_vision_patch14_384.safetensors`. |
| 22 | WAN VACE Video Inpainting | Backend completed, QA script errored | 73 images, 0 media | No playable media output in app job result. |
| 23 | WAN 2.2 14B I2V Subgraphed | Completed with issues | MP4 misclassified as image | Fixed in repo output classification. |
| 24 | LTX 2.3 Text-to-Video | Rejected | 0 | 8188 reports no latent upscale model options. |

## Frontend Preview Result

- Current frontend can render playable media when it receives a proper `media` payload:
  - synthetic check produced `videoCount=1`, `hasControls=true`.
- Current bad WAN 2.2 result cannot preview as video because backend saved it under `images`:
  - preview DOM: `imageCount=1`, `videoCount=0`.
- Therefore the preview bug is primarily backend output classification, not the video player renderer.

## Changes Applied

- `services/comfyui/execution.py`
  - Classifies `SaveVideo`, `VHS_VideoCombine`, video extensions, and audio extensions into media buckets even when ComfyUI reports them under `images`.
- `public/js/36-comfyui-workflows.js`
  - Keeps template MODEL defaults instead of collecting global/manual select values.
  - Keeps LoRA selector fields usable.
  - Leaves edit/reset controls for model customization.
- Tests added/updated:
  - `tests/comfyui/test_execution_media_outputs.py`
  - `tests/frontend/comfyui/test_comfyui_workflow_template_ui.py`
- QA helper added:
  - `scripts/testing/playwright_comfyui_template_default_qa.py`

## Verification

- `python3 -m pytest tests/comfyui/test_execution_media_outputs.py tests/frontend/comfyui/test_comfyui_workflow_template_ui.py`
  - 25 passed.
- Playwright preview smoke against 5007:
  - Existing WAN 2.2 job: confirmed MP4 was rendered as broken image.
  - Synthetic media payload: confirmed frontend creates playable `<video controls>`.

## Remaining Work

- Restart or refresh the 5007 isolated frontend server before rechecking the SDXL template in-browser; the running process is from `/tmp/hackme_web_embedding_toggle_5007/hackme_web` and was still serving the older workflow JS during the quick no-GPU prepare check.
- Re-run targeted templates after deploying the repo fix:
  - SDXL Text-to-Image
  - WAN 2.2 14B I2V Subgraphed
  - WAN VACE Video Inpainting
- Fix or replace unacceptable Qwen ControlNet outputs.
- Decide whether the 8 MB official-template media limit should be raised or the One-Click Anime to Real example image should be compressed.
- On the actual `192.168.18.19:8188` ComfyUI process, make `LatentUpscaleModelLoader` expose the installed LTX upscaler option; the repo cannot select an option that the backend reports as an empty list.
