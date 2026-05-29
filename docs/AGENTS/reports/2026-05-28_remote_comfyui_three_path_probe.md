# Remote ComfyUI Three-Path Probe

Date: 2026-05-28

Host: `s92137@192.168.18.19` (`DESKTOP-JHEPDG2`)

Shared config: `/mnt/d/tmp/hackme_comfyui_remote_probe/generation_probe_config.example.json`

Common parameters: `1920x1080`, `24` steps, `cfg=5.0`, seed `20260528`, same prompt/negative prompt from the shared config.

## Results

| Path | Result | Image | Key timings | Peak resources |
|---|---:|---|---|---|
| Regular ComfyUI JAN v777 | PASS | `D:\tmp\hackme_comfyui_remote_probe\regular_1920x1080_steps24_win\regular_comfyui.png` | ComfyUI total `24.196s` | GPU `100%`, VRAM `14557.9MB`, RAM used `49.3%` |
| HF Diffusers | PASS | `/mnt/d/tmp/hackme_comfyui_remote_probe/hf_1920x1080_steps24_token_r3/hf_diffusers.png` | import `13.971s`, pipeline load `25.386s`, move `1.396s`, generate `28.782s`, save `0.471s` | GPU `100%`, VRAM `22444.1MB`, process RSS `13924.7MB` |
| GGUF via ComfyUI-GGUF official profile | PASS | `D:\tmp\hackme_comfyui_remote_probe\gguf_1920x1080_steps24_illustrious_aux\gguf.png` | GGUF cache hit `0.209s`, aux download/install `135.737s`, ComfyUI total `24.394s` | GPU `100%`, VRAM `10334.1MB`, process RSS `661.7MB` |

## Cache

- HF Diffusers cache: `/mnt/d/tmp/hackme_hf_cache/hub/models--dhead--wai-nsfw-illustrious-sdxl-v140-sdxl`, `27756441028` bytes.
- GGUF cache: `D:\tmp\hackme_hf_cache\hub\models--kekusprod--WAI-NSFW-illustrious-SDXL-v110-GGUF`, `5517496296` bytes.
- GGUF installed for ComfyUI-GGUF: `D:\ComfyUI\ComfyUI_windows_portable\ComfyUI\models\unet\WAI-NSFW-illustrious-SDXL-v110-Q8_0.gguf`.
- GGUF companion cache: `D:\tmp\hackme_hf_cache\hub\models--calcuis--illustrious`.
- GGUF companion install targets:
  - `D:\ComfyUI\ComfyUI_windows_portable\ComfyUI\models\text_encoders\illustrious_clip_l_fp8_e4m3fn.safetensors`
  - `D:\ComfyUI\ComfyUI_windows_portable\ComfyUI\models\text_encoders\illustrious_clip_g_fp8_e4m3fn.safetensors`
  - `D:\ComfyUI\ComfyUI_windows_portable\ComfyUI\models\vae\illustrious_v110_vae_fp8_e4m3fn.safetensors`

## Notes

- Tokens are not stored in config or reports. Runtime token input must use `HF_TOKEN`, `--hf-token-file`, or stdin. Reports only retain `hf_token_supplied`.
- The first no-token HF attempt was slow and incomplete. The token-backed run completed after cache was present and generated successfully.
- The ComfyUI server is the Windows portable process. WSL could not connect to Windows ComfyUI through `127.0.0.1` or `192.168.18.19` from inside WSL, so ComfyUI API probes must run under Windows portable Python and target `http://127.0.0.1:8188`.
- HF Diffusers direct path runs well under the WSL ComfyUI venv plus `/mnt/d/tmp/hackme_probe_deps`.
- GGUF metadata classified the selected file as `comfyui_gguf`, so the correct path is ComfyUI-GGUF, not direct Diffusers.
- The generic SDXL CLIP/VAE GGUF attempts produced unusable purple output even when the API returned success. The passing GGUF run used the model-card required `calcuis/illustrious` companion CLIP/VAE files and `DualCLIPLoaderGGUF`.
- Customer-facing GGUF must be exposed as official profiles only. Each profile needs an explicit model map for UNet GGUF, text encoders, VAE, loader class, cache/install paths, and verified sampler defaults.

## Remote Cleanup Target

- Scripts/config/docs were staged under `/mnt/d/tmp/hackme_comfyui_remote_probe`.
- WSL isolated deps were staged under `/mnt/d/tmp/hackme_probe_deps`.
- HF model cache was staged under `/mnt/d/tmp/hackme_hf_cache/hub`.
- Successful output images and reports were staged under:
  - `/mnt/d/tmp/hackme_comfyui_remote_probe/hf_1920x1080_steps24_token_r3`
  - `/mnt/d/tmp/hackme_comfyui_remote_probe/regular_1920x1080_steps24_win`
  - `/mnt/d/tmp/hackme_comfyui_remote_probe/gguf_1920x1080_steps24_illustrious_aux`
- Final cleanup should remove remote cache/probe/deps output directories and
  leave only copied scripts/docs/skill backup plus installed supported ComfyUI
  model files.
- 2026-05-29 cleanup removed `/mnt/d/tmp/hackme_hf_cache` and
  `/mnt/d/tmp/hackme_probe_deps`. After remounting the remote WSL `D:` drvfs
  mount, verification showed the probe root reduced to scripts/config/reports,
  no SD35-specific model leftovers, and the skill backup still present. A 28KB
  `retest_hf_diffusionpipeline_20260529/Thumbs.db` directory remained locked by
  Windows and was explicitly left alone. Windows ComfyUI was restarted and port
  `8188` was observed listening; the final Windows-side HTTP check was blocked
  by a later SSH timeout.
