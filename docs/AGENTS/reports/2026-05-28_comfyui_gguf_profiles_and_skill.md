# ComfyUI GGUF Profiles and Skill

Date: 2026-05-28

## Scope

- Add a reusable Codex skill for turning user-supplied Hugging Face GGUF repos
  into official `hackme_web` ComfyUI GGUF profiles.
- Add or update official GGUF profile records for:
  - `sothmik/Wai-NSFW-Illustrious-v140-Q8-GGUF`
  - `calcuis/illustrious`
  - `btaskel/Illustrious-XL-v2.0-GGUF` as a hidden disabled failed record only.
  - `void-gryph/diving-illustrious-flat-anime-paradigm-shift-GGUF`
  - `calcuis/sd3.5-large-gguf` as a hidden disabled blocker record only.
- Expose installed GGUF inventory from the ComfyUI model list.
- Extend the standalone GGUF probe so another machine can retest SDXL dual-CLIP
  and SD3.5 triple-CLIP mappings from one shared config.

## Key Findings

- `sothmik/Wai-NSFW-Illustrious-v140-Q8-GGUF` is a native ComfyUI-GGUF UNet and
  works with the existing Illustrious companion files from `calcuis/illustrious`
  through `DualCLIPLoaderGGUF`.
- `calcuis/sd3.5-large-gguf` technically loads only through the model-card
  workflow (`UnetLoaderGGUF + TripleCLIPLoader`, safetensors `clip_g`,
  `clip_l`, `t5xxl_fp8_e4m3fn`, and VAE), but the generated image was judged
  abnormal. SD35 GGUF is therefore abandoned, hidden from the frontend, and kept
  only as a disabled blocker record for stale requests or installed leftovers.
- The remote ComfyUI output metadata maps `hackme_probe_gguf_00009_` to
  `calcuis/illustrious` Q4_0, `hackme_probe_gguf_00010_` to `btaskel`
  Q8_0, and `hackme_probe_gguf_00011_` to the `void-gryph/diving`
  Q4_K_M file. The earlier verbal note that "11 = btaskel" was incorrect.
- `btaskel/Illustrious-XL-v2.0-GGUF` is abandoned and hidden from public
  frontend options because both probe `00010` and the 2026-05-29 reprobe
  completed technically while still being judged visually abnormal. The
  `void-gryph` profile remains enabled because probe `00011` and the reprobe
  were accepted.

## Remote Evidence

Target host: `s92137@192.168.18.19`

Remote probe root: `/mnt/d/tmp/hackme_comfyui_remote_probe`

| Profile | Result | Output | Timing | Peak resources |
|---|---:|---|---|---|
| calcuis Illustrious Q4_0 | PASS | `D:\ComfyUI\ComfyUI_windows_portable\ComfyUI\output\hackme_probe_gguf_00009_.png` | ComfyUI output metadata checked | `UnetLoaderGGUF` + `DualCLIPLoader`; VAE `illustrious_vae.safetensors` |
| btaskel Illustrious XL v2.0 Q8_0 | FAIL / abandoned / hidden | `D:\ComfyUI\ComfyUI_windows_portable\ComfyUI\output\hackme_probe_gguf_00010_.png` | ComfyUI output metadata checked | Visual smoke rejected; profile is hidden from public options |
| Diving Illustrious Flat Anime Q4_K_M | PASS | `D:\ComfyUI\ComfyUI_windows_portable\ComfyUI\output\hackme_probe_gguf_00011_.png` | ComfyUI output metadata checked | `UnetLoaderGGUF` + `DualCLIPLoader`; VAE `vae.safetensors` |
| calcuis Illustrious Q4_0 reprobe | PASS | `D:\tmp\hackme_comfyui_remote_probe\reprobe_calcuis_illustrious_q4_0_20260529_0712\gguf.png` | ComfyUI total `30.143s` | VRAM `7122.0MB`; GPU `100%` |
| btaskel Illustrious XL v2.0 Q8_0 reprobe | FAIL / abandoned / hidden | `D:\tmp\hackme_comfyui_remote_probe\reprobe_btaskel_illustrious_xl_v20_q8_0_20260529_0712\gguf.png` | ComfyUI total `27.197s` | API success but visual output abnormal; VRAM `10290.0MB`; GPU `100%` |
| Diving Illustrious Flat Anime Q4_K_M reprobe | PASS | `D:\tmp\hackme_comfyui_remote_probe\reprobe_diving_illustrious_flat_anime_q4_k_m_20260529_0712\gguf.png` | ComfyUI total `33.194s` | VRAM `11186.0MB`; GPU `100%` |
| sothmik WAI v14 Q8 | PASS | `D:\tmp\hackme_comfyui_remote_probe\gguf_sothmik_v140_q8_1920x1080_steps24\gguf.png` | download/cache `152.432s`; ComfyUI total `27.154s` | VRAM `11399.3MB`; process RSS `655.6MB`; GPU `100%` |
| SD3.5 Large Q4_0 | FAIL / abandoned | `D:\tmp\hackme_comfyui_remote_probe\gguf_sd35_large_q4_0_1920x1080_steps28\gguf.png` | companion download/cache `373.534s`; ComfyUI total `111.536s` | API success but visual output abnormal; VRAM `14215.8MB`; process RSS `661.8MB`; GPU `100%` |

SD3.5 selected models:

- UNet: `sd3.5_large-q4_0.gguf`
- CLIP loader: `TripleCLIPLoader`
- CLIP-G: `clip_g.safetensors`
- CLIP-L: `clip_l.safetensors`
- T5: `t5xxl_fp8_e4m3fn.safetensors`
- VAE: `diffusion_pytorch_model.safetensors`

## Project Changes

- `services/comfyui/gguf_profiles.py` now includes:
  - WAI Illustrious SDXL v14 Q8 profile.
  - Calcuis Illustrious Q4_0 enabled, with higher precisions mapped but
    disabled until individually validated.
  - Btaskel Illustrious XL v2.0 Q8_0 hidden and disabled after failed visual
    smoke and failed visual reprobe.
  - Diving Illustrious Flat Anime Q4_K_M enabled, with higher precisions mapped
    but disabled until individually validated.
  - SD3.5 Large GGUF hidden and disabled after failed visual output.
  - `installed_gguf_inventory(...)` for mapping ComfyUI diffusion model options
    back to official profile/variant status.
- `/api/comfyui/models` and `/api/comfyui/installed-gguf` expose installed GGUF
  inventory.
- The ComfyUI UI shows installed GGUF inventory near the official GGUF selector.
- `scripts/comfyui/standalone_gguf_txt2img.py` supports third text encoder/T5
  slots and SD3.5-style `TripleCLIPLoader` workflows for future internal
  reprobes, but SD35 and btaskel are not exposed as supported/public options.
- `scripts/comfyui/hf_diffusers_repo_smoke.sh` batch-tests HF Diffusers repos
  with token via env/file/stdin, model-card loading hints, and repo-slug output
  names for live audit.
- `services/comfyui/huggingface.py` and `services/comfyui/diffusers_client.py`
  now parse/apply model-card `DiffusionPipeline.from_pretrained(...)` hints,
  keep HF cache under root-configured paths, and avoid downloading unrelated
  precision files when a specific precision is selected.
- Skill backup locations:
  - Repo copy: `docs/AGENTS/skills/hackme-gguf-profile`
  - Remote copy: `/mnt/d/tmp/codex_skill_backups/hackme-gguf-profile`

## HF Diffusers T2I Reprobe

Common prompt suite: the current 1girl beach prompt plus the legacy 2girls
audit prompt, `1024x1024`, `20` steps, `cfg=6.5`, seed `20260529`.

| Repo | Result | Notes |
|---|---:|---|
| `Heartsync/NSFW-Uncensored` | PASS | Retested with `DiffusionPipeline`; first prompt needed adjustment, the 2girls audit output was accepted. |
| `John6666/wai-ani-nsfw-ponyxl-v6-sdxl` | FAIL / removed | Output was noise/static. Upstream maps to WAI-ANI-PONYXL v6.0; replaced instead of keeping it supported. |
| `John6666/perfect-rsb-mix-illustrious-real-anime-sfw-nsfw-definitive-iota-sdxl` | PASS | Replacement John6666 repo; both default and 2girls audit outputs accepted. |
| `cagliostrolab/animagine-xl-4.0` | RUNTIME OK / visual marginal | Pipeline loads and generates after using the full Diffusers repo instead of root checkpoint files, but visual result was not accepted as a clean pass. |
| `circlestone-labs/Anima-Base-v1.0-Diffusers` | UNSUPPORTED | Repo has `modular_model_index.json` but no `model_index.json`; it requires `diffusers.AnimaTextConditioner`, which is absent from the installed `diffusers 0.39.0.dev0` package. |

## Verification

- `python3 -m py_compile` on touched Python modules and standalone probe.
- `python3 -m json.tool scripts/comfyui/generation_probe_config.example.json`
- `python3 -m pytest -q tests/comfyui/generation/test_comfyui_generation.py tests/frontend/comfyui/test_comfyui_diffusers_repo_ui.py`
- `quick_validate.py` for both local and repo skill copies.

## Notes

- No Hugging Face token is stored in config, docs, skill files, or reports.
- Remote scripts/config/report remnants were consolidated under
  `/mnt/d/codex_remote_workspace/t2i_comfyui_remote_probe_20260528`; skill
  backup artifacts are under `/mnt/d/codex_remote_workspace/codex_skill_backups`.
- `btaskel/Illustrious-XL-v2.0-GGUF` model/cache/reprobe artifacts were removed
  from the remote host after the failed visual reprobe decision, and its public
  GGUF profile/config example entry is hidden or removed.
- 2026-05-29 cleanup removed `/mnt/d/tmp/hackme_hf_cache`,
  `/mnt/d/tmp/hackme_probe_deps`, and SD35-specific
  `t5xxl_fp8_e4m3fn.safetensors` / `diffusion_pytorch_model.safetensors`
  model leftovers. The frontend no longer lists SD35 GGUF as a selectable
  supported profile.
- 2026-05-30 cleanup also removed stale SD3.5 checkpoint/controlnet leftovers:
  `/mnt/e/ComfyUI/models/checkpoints/sd3.5_large_fp8_scaled.*` and
  `/mnt/e/ComfyUI/models/controlnet/SD35/`.
- The final reachable remote verification showed no btaskel, SD35, FaceID, or
  PuLID model leftovers and all retained remote scripts documented in README
  files. One 28KB `retest_hf_diffusionpipeline_20260529/Thumbs.db` probe
  directory remained locked by Windows and was left alone by user decision.
