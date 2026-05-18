# ComfyUI Origin Workflows

This directory keeps raw upstream ComfyUI workflow JSON files before they are converted into first-party workflow bundles with `manifest.json` and `workflow.json`.

Keep raw files under `category/mode/`. Do not place JSON files directly in this root directory.

## Categories

| Category | Purpose |
| --- | --- |
| `image/txt2img` | Text-to-image workflows that produce still images from prompts. |
| `image/edit` | Image editing workflows that require an input image. |
| `image/outpaint` | Outpaint workflows that extend an input image canvas. |
| `image/controlnet` | Image workflows driven by ControlNet, depth, canny, or other control images. |
| `video/i2v` | Image-to-video workflows. |
| `video/t2v` | Text-to-video workflows. |
| `video/edit` | Video edit, inpaint, or video-to-video workflows. |
| `audio/t2a` | Text-to-audio or text-to-music workflows. |
| `utility/compare` | Comparison or evaluation helper workflows. |
| `utility/upscale` | Upscale and enhancement helper workflows. |
| `utility/segmentation` | Masking or segmentation helper workflows. |
| `utility/pose` | Pose or skeleton extraction helper workflows. |

## Current Files

| Path | Notes |
| --- | --- |
| `audio/t2a/audio_ace_step1_5_xl_base.json` | ACE-Step text-to-audio/music workflow. |
| `image/controlnet/image_qwen_Image_2512_controlnet.json` | Qwen image ControlNet workflow. |
| `image/controlnet/sd3.5_large_canny_controlnet_example.json` | SD3.5 canny ControlNet workflow. |
| `image/controlnet/sd3.5_large_depth.json` | SD3.5 depth ControlNet workflow. |
| `image/edit/Image_capybara_v0_1_image_edit.json` | Capybara image edit workflow. |
| `image/edit/image_qwen_image_edit_2509.json` | Qwen image edit workflow. |
| `image/edit/【50】一键动漫转真人.json` | One-click anime-to-real image edit workflow. |
| `image/edit/【70】一键换万物超级精准-AIO-2511版本.json` | One-click replacement AIO image edit workflow. |
| `image/outpaint/flux_fill_outpaint_example.json` | Flux fill/outpaint workflow. |
| `image/txt2img/ANIMA.json` | ANIMA text-to-image workflow. |
| `image/txt2img/SD3.5.json` | SD3.5 simple text-to-image workflow. |
| `image/txt2img/SDXL.json` | SDXL simple text-to-image workflow. |
| `image/txt2img/ZIT.json` | ZIT text-to-image workflow. |
| `image/txt2img/flux_dev_full_text_to_image.json` | Flux dev text-to-image workflow. |
| `image/txt2img/image_qwen_image.json` | Qwen image text-to-image workflow. |
| `image/txt2img/netayume.json` | Netayume text-to-image workflow. |
| `utility/compare/compare_2checkpoints.json` | Two-checkpoint comparison workflow. |
| `utility/pose/utility_sdpose_multi_person.json` | Multi-person pose helper workflow. |
| `utility/segmentation/utility_image_segment_sam3.json` | SAM3 segmentation helper workflow. |
| `utility/upscale/多種放大方法.json` | Multi-method image upscale workflow. |
| `video/edit/video_capybara_v0_1_video_edit.json` | Capybara video edit workflow. |
| `video/edit/video_wan_vace_inpainting.json` | WAN VACE video inpaint workflow. |
| `video/i2v/03_video_wan2_2_14B_i2v_subgraphed.json` | WAN 2.2 14B image-to-video workflow. |
| `video/t2v/video_ltx2_3_t2v.json` | LTX text-to-video workflow. |
