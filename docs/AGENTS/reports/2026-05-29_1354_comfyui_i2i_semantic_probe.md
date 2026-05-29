# ComfyUI I2I Semantic Probe

Date: 2026-05-29 13:54 Asia/Taipei

Scope: direct remote ComfyUI API only.  The remote workspace for this run is
`D:\codex_remote_workspace\i2i_comfyui_semantic_probe_20260529`; the old
`/mnt/d/tmp` path is not used.

## Current Findings

No code regression has been confirmed yet.  The main confirmed behavior boundary
so far is that plain `img2img` redraw is useful for broad redraw/style transfer
but not reliable for precise local semantic edits such as "make only the window
nighttime" or "turn off room lights".  Those requests should be tested as
inpainting/masked edits.

Remote workflow execution success is not counted as semantic success.  The
ControlNet canny/depth/lineart reruns all executed successfully, but visual
review showed that they mainly preserve structure/pose and do not reliably obey
the requested outfit/background replacement.  They are therefore recorded as
structure-control partials, not supported semantic edits.

Follow-up investigation of the inpaint/outpaint artifacts found that the plain
`VAEEncodeForInpaint` shortcut is too weak for clean edits on the current anime
checkpoint.  ComfyUI exposes `InpaintModelConditioning` and
`DifferentialDiffusion` on the remote host, and the probe now supports that
route.  It improves the earlier solid-frame outpaint failure mechanically, but
top-only wall/window outpainting is still not visually continuous.  User review
rejected the result, so the current shortcut path fails semantic outpainting.
After the official ComfyUI inpaint checkpoint was installed, outpainting was
rerun with `inpaint\512-inpainting-ema.safetensors` through both
`InpaintModelConditioning + DifferentialDiffusion` and the legacy
`VAEEncodeForInpaint` route.  Both produced disconnected/non-semantic extensions
on the current anime bedroom source, so the official inpaint checkpoint does
not rescue this shortcut outpaint case.

## Evidence Matrix

| Item | Status | Evidence | Notes |
|---|---|---|---|
| Source image | Accepted by user | `run_003_source_2girls/source_t2i_reference_2girls.png` | 1024x1024, 20 steps, CFG 6.5, legacy 2girls prompt. |
| 1. img2img redraw | Boundary confirmed | `run_004_img2img_redraw_2girls/`, `run_005_img2img_redraw_2girls_night/`, `run_006_img2img_redraw_2girls_lights_off/`, `run_007_img2img_redraw_2girls_lights_off_highdenoise/` | Low/mid denoise preserves composition but does not obey precise lighting/window edits; high denoise redraws too much. |
| 2. style imitation | Accepted by user | `run_008_img2img_style_handpainted_fantasy/`, `run_009_img2img_style_strong_watercolor/`, `run_010_img2img_style_realistic/`, `run_011_img2img_style_realistic_denoise08/` | Watercolor and realistic style transfer worked; denoise 0.8 was accepted for stronger realistic conversion. |
| 3. feature preserve | Generated, awaiting explicit visual acceptance | `run_012_img2img_feature_preserve/img2img_feature_preserve.png` | Low denoise 0.32 feature-preservation pass produced an artifact for review. |
| 4. inpaint remove/repair | Partial pass | `run_013_inpaint_remove_repair_redmask/`, `run_014_inpaint_remove_repair_windowmask/`, `run_021_inpaint_repair_conditioning_dd/` | Mask channel bug is fixed. `InpaintModelConditioning + DifferentialDiffusion` reduces whole-image/solid-block failure, but visual quality still depends on precise manual masks. |
| 5. inpaint replace/edit | Partial pass with artifacts | `run_015_inpaint_replace_wall_painting/`, `run_016_inpaint_replace_heart_sticker/`, `run_017_inpaint_replace_heart_sticker_weighted/`, `run_020_inpaint_replace_conditioning_dd/`, `run_032_inpaint_kimono_clothes/`, `run_033_inpaint_kimono_clothes_wider_mask/` | Prompt weighting made the red heart target appear, so the pipeline can perform replacement. Conditioning route improves locality. Clothing replacement to kimono worked; wider mask improves outfit coverage but changes arm/edge regions more and still leaves some right-side original frill/cloth remnants. |
| 6. outpaint | Failed visual review | `run_018_outpaint_indoor_extend/outpaint_expand_beach.png`, `run_019_outpaint_conditioning_dd/`, `run_022_outpaint_bed_wall_window/`, `run_023_outpaint_wall_window_top_only/`, `run_024_outpaint_official_inpaint_top_bottom/`, `run_025_outpaint_official_inpaint_vae_encode/` | The original shortcut produced a solid-color frame. Conditioning route can generate expanded content, but the top-only wall/window result is not coherent. Official `512-inpainting-ema.safetensors` was then tested and still hallucinated disconnected top/bottom content on the anime source. Treat outpainting as failed for this shortcut workflow. |
| 7. ControlNet copy composition/action | Partial: structure only | `run_026_controlnet_openpose_action_copy/`, `run_027_controlnet_openpose_union_sdxl/`, `run_028_controlnet_openpose_beach_bikini/`, `run_029_controlnet_openpose_beach_bikini_denoise045/`, `run_042_controlnet_canny_edge_copy/`, `run_043_controlnet_depth_structure_copy/`, `run_044_controlnet_lineart_copy/`, `run_045_controlnet_lineart_copy_fixed/` | Auto-selected SDXL pose anime model failed `ControlNetLoader` validation. Manual union SDXL OpenPose can preserve pose/composition, and canny/depth/lineart workflows now run. Visual review: canny/depth/lineart still mostly preserve the original maid/room image and do not satisfy the requested outfit/background semantic change. Treat as structure control only, not semantic edit support. `run_044` also exposed a preprocessor optional-default issue; the script now fills optional defaults and `run_045` passes execution. |
| 8. upscale redraw | Generated, awaiting user review | `run_030_upscale_redraw_imagescale/` | `ImageScale + VAEEncode + KSampler` produced a 1.25x redraw artifact. Composition is preserved on local inspection; face/mouth details need user review for redraw artifacts. This is not the project pure-upscale shortcut. |
| 9. blend/mix | Generated, awaiting user review | `run_031_two_image_blend_mix/` | `ImageBlend + VAEEncode + KSampler` mixed the original source with the beach ControlNet variant. Local inspection: beach color/waterline entered the background while characters remain close to source; this is closer to pixel blend plus redraw than high-level semantic multi-reference fusion. |
| 10. IPAdapter reference style/feature | Partial | `run_034_ipadapter_style_reference_watercolor/`, `run_035_ipadapter_style_reference_after_restart/`, `run_036_ipadapter_style_reference_watercolor_loaded/`, `run_037_new_watercolor_style_reference/`, `run_038_ipadapter_new_watercolor_style_reference/`, `run_039_new_ghibli_like_style_reference/`, `run_040_ipadapter_ghibli_like_style_reference/`, `run_041_ipadapter_ghibli_like_style_reference_soft/` | Initial runs failed because `extra_model_paths.yaml` did not expose the `ipadapter` model type. After adding `ipadapter: models/ipadapter` under the `E:\ComfyUI\` extra path and rebooting ComfyUI, `IPAdapterModelLoader` saw `ip-adapter-plus_sdxl_vit-h.safetensors` and `ip-adapter_sdxl_vit-h.safetensors`; style/composition reference generation then succeeded. Visual review: whole-image IPAdapter can transfer broad color/style, but strong weights can over-transfer color casts and weak weights under-transfer style. |
| 11. IPAdapter + masked inpaint | Partial/fail for user-facing support | `run_046_ipadapter_inpaint_kimono_watercolor/`, `run_047_ipadapter_inpaint_kimono_low_bleed/` | Added `ipadapter_inpaint_reference` to combine IPAdapter style composition with `InpaintModelConditioning`. `run_046` changed clothing toward patterned kimono but also altered faces/hair/linework. `run_047` reduced bleed with lower style weight/denoise but the kimono change became too weak. This is technically runnable but not reliable enough to expose as supported semantic local edit. |
| 12. FaceID / InstantID / PuLID identity transfer | Pass for clear human reference to anime via InstantID; FaceID/PuLID deleted as unsupported | `run_048_identity_faceid/`, `run_049_identity_faceid_realistic_ref/`, `run_050_identity_instantid_cpu_realistic_ref/`, `run_051_identity_instantid_cpu_realistic_ref_fixed_antelope/`, `run_052_identity_instantid_cpu_colorful/`, `run_053_identity_instantid_cpu_natural_color_lowweight/`, `run_054_identity_instantid_cpu_ogipote_natural_color/`, `run_055_reference_ahegao_ogipote/`, `run_056_no_instantid_ahegao_ogipote/`, `run_057_with_instantid_ahegao_ogipote/`, `run_058_reference_ahegao_ogipote_detectable/`, `run_059_no_instantid_ahegao_ogipote_v2/`, `run_060_with_instantid_ahegao_ogipote_v2/`, `run_061_reference_ahegao_ogipote_detector_friendly/`, `run_062_official_instantid_yann_reference/`, `run_063_official_no_instantid_yann_film_noir/`, `run_064_official_with_instantid_yann_film_noir/`, `run_065_official_with_instantid_yann_film_noir_controlnetmodel/`, `run_066_yann_instantid_ogipote_anime/`, `run_067_yann_instantid_ogipote_anime_girl/`, `run_068_yann_instantid_ogipote_anime_girl_clean_cheeks/`, `run_069_yann_pulid_ogipote_anime/`, `run_070_yann_pulid_ogipote_anime_after_xformers_fallback/`, `run_071_yann_faceid_ogipote_anime/` | Required model files and nodes were installed for testing. FaceID fails on the original anime two-person source because InsightFace detects no face. On the clear Yann human reference, FaceID executed and produced a visually plausible anime image, but user clarified that this is not enough: it did not achieve the required identity-transfer function, so FaceID is unsupported and its test-only models should be removed. InstantID initially failed because its auto-downloaded `antelopev2` pack unpacked as `models/antelopev2/antelopev2/*.onnx`; copying those files up to `models/antelopev2/*.onnx` fixed the missing `detection` assertion. CPU provider fallback avoids the CUDA provider DLL log spam. Separate `ahegao` reference probes produced clear-looking anime faces for human review, but InstantID rejected them with `Reference Image: No face detected` or produced outputs that user review found no closer than baseline. A control run using the official InstantID README reference image `examples/yann-lecun_resize.jpg` worked on a human face when using the official InstantID ControlNetModel file `ControlNetModel\diffusion_pytorch_model.safetensors`: the film-noir output inherited glasses, face shape, hairline, and expression. `run_066` then used the same human reference with the WAI anime checkpoint and `by ogipote` prompt; user review accepted it as successful human-reference-to-anime identity transfer. `run_067` tested male-reference-to-1girl transfer and preserved some reference traits but introduced a dark cheek artifact; `run_068` lowered weights and strengthened negatives, removing the artifact but also weakening identity retention, and user marked it barely acceptable. PuLID `run_069` reached `ApplyPulid` but failed in EVA02-CLIP with `memory_efficient_attention_forward` because the installed xFormers wheel is incompatible with Python 3.13 / torch cu130 on the RTX 2080 Ti. A remote fallback patch forced PyTorch attention and `run_070` executed, but visual review failed: it produced a distorted anime cat girl with weak/no Yann identity retention. Current conclusion: expose InstantID only for clear single human face references, including anime-stylized outputs; warn that anime/ahegao/multi-person/occluded references and cross-gender transfer are unreliable. Do not expose FaceID or PuLID as supported from this experiment. |

## Project State Notes

- Added `scripts/comfyui/standalone_comfyui_i2i_matrix.py` so the same direct
  ComfyUI I2I cases can be rerun on the remote host without a hackme_web server.
- Registered the script in `scripts/INDEX.md` and `scripts/comfyui/README.md`.
- Added `tests/scripts/comfyui/test_standalone_comfyui_i2i_matrix_script.py`.
- Fixed `services/comfyui/workflow/builder.py` inpaint shortcut masking from
  `LoadImageMask channel=alpha` to `channel=red`.  Current ComfyUI returns
  `1 - alpha` for alpha masks, while the hackme_web mask editor presents
  white-on-black masks where white means "repaint".
- Extended `scripts/comfyui/standalone_comfyui_i2i_matrix.py` with
  `--inpaint-method`, `--differential-diffusion`, and per-side outpaint controls
  so artifact reprobes can compare the legacy `VAEEncodeForInpaint` path with
  `InpaintModelConditioning`.
- Extended the same probe with `--controlnet-model` after the automatically
  selected SDXL pose anime ControlNet file failed loader validation.  This lets
  action/copy-composition tests pin a known loader-compatible ControlNet model.
- Added the `two_image_blend_mix` probe case with `--blend-image-path` for
  testing `ImageBlend + VAEEncode + KSampler` on remote ComfyUI instances that
  expose an `ImageBlend` node.
- Added `kimono_clothes` mask shape for targeted inpaint clothing-replacement
  reprobes.
- Added an `ipadapter_style_reference` probe case.  Current remote execution is
  now runnable after exposing the `ipadapter` model type in
  `extra_model_paths.yaml` and rebooting ComfyUI.
- Added an `ipadapter_inpaint_reference` probe case.  This verifies that the
  workflow can compose IPAdapter with masked inpaint, but the visual results are
  not currently clean enough for a supported feature.
- Added a temporary identity-transfer probe on the remote host for FaceID,
  InstantID, and PuLID.  It confirmed that InsightFace-based methods need
  detectable face references, and that the ComfyUI InstantID node reads
  `antelopev2` only from the default ComfyUI model directory, not the extra
  model path used for most shared models.  After cleanup, the retained remote
  identity probe is InstantID-only; FaceID/PuLID runnable entries were removed.
- Fixed direct-workflow default filling so optional node defaults are included.
  This was required because `LineArtPreprocessor` exposes `coarse` as optional
  in `/object_info` but raises at runtime when it is omitted.
- Web research notes: ComfyUI's basic inpaint/outpaint docs describe outpainting
  as an inpainting variant driven by masks; the remote host has the relevant
  core nodes but does not currently have a dedicated inpaint/fill/outpaint
  checkpoint filename available.
- Remote cleanup completed after visual review.  The remote workspace was
  renamed to `D:\codex_remote_workspace\i2i_comfyui_semantic_probe_20260529`
  and now keeps only the probe scripts plus `RESULT_SUMMARY.md`; all `run_*`
  audit image directories were removed.  The T2I workspace was likewise named
  `D:\codex_remote_workspace\t2i_comfyui_remote_probe_20260528`.
- Remote T2I/I2I README files now document every retained script's purpose and
  include direct CLI/`--interactive` usage examples for live audit.
- Unsupported test-only identity assets were removed from the remote ComfyUI
  host: FaceID IPAdapter/LoRA files, PuLID model/custom node/EVA CLIP assets,
  and the SD35 diffusers note/checkpoint/controlnet leftovers.  InstantID assets
  needed for the accepted clear-human-reference workflow remain in the normal
  ComfyUI model locations.
- All retained standalone T2I/I2I scripts now support `--interactive` while
  preserving non-interactive CLI mode for automation.
- Focused local check passed:
  `python3 -m pytest -q tests/scripts/comfyui/test_standalone_generation_scripts.py tests/scripts/comfyui/test_standalone_comfyui_i2i_matrix_script.py tests/comfyui/generation/test_comfyui_generation.py`
  (`37 passed`).

## Commands

Representative accepted source generation:

```bash
python_embeded/python.exe standalone_regular_comfyui_txt2img.py \
  --comfyui-url http://127.0.0.1:8188 \
  --width 1024 --height 1024 --steps 20 --cfg 6.5
```

Step-by-step I2I runs now use:

```bash
python_embeded/python.exe standalone_comfyui_i2i_matrix.py \
  --source-image-path D:/codex_remote_workspace/i2i_comfyui_semantic_probe_20260529/run_003_source_2girls/source_t2i_reference_2girls.png \
  --only-case CASE_ID
```
