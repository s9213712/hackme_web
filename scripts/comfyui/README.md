# ComfyUI Scripts

This folder holds ComfyUI-specific live probes and helper tooling.

- [comfyui_run_in_linux.template.sh](comfyui_run_in_linux.template.sh): Linux local startup template that operators can download from the root ComfyUI settings panel
- [feature_probe.py](feature_probe.py): end-to-end ComfyUI feature probe
- [standalone_hf_diffusers_txt2img.py](standalone_hf_diffusers_txt2img.py): direct HF Diffusers txt2img probe for another machine; it does not call hackme_web and records cache placement, timings, output image, and resource peaks
- [standalone_gguf_txt2img.py](standalone_gguf_txt2img.py): direct GGUF probe for another machine; GGUF should be selected from an official profile because each model needs its own UNet/CLIP/VAE/loader map
- [standalone_regular_comfyui_txt2img.py](standalone_regular_comfyui_txt2img.py): direct ComfyUI API SDXL checkpoint workflow probe for the regular JAN v777 path
- [generation_probe_config.example.json](generation_probe_config.example.json): shared config for all three standalone generation probes; CLI flags override the config when explicitly supplied
- [generation_probe_dependencies.md](generation_probe_dependencies.md): remote runtime package/model dependency checklist and standard commands
- [generation_probe_requirements.txt](generation_probe_requirements.txt): pip requirements for the isolated WSL dependency target used by the standalone probes

Example external-machine checks:

Do not put Hugging Face tokens in `generation_probe_config.example.json` or
any copied config. Pass tokens at runtime with `HF_TOKEN`, `--hf-token-file`,
or `--hf-token-stdin`; reports only store `hf_token_supplied: true/false`.

```bash
export HF_TOKEN=...
python3 standalone_hf_diffusers_txt2img.py \
  --config generation_probe_config.example.json \
  --out-dir /tmp/hackme_hf_diffusers_probe
```

```bash
export HF_TOKEN=...
python3 standalone_gguf_txt2img.py \
  --config generation_probe_config.example.json \
  --gguf-profile wai_illustrious_v110_q8 \
  --out-dir /tmp/hackme_gguf_probe
```

```bash
python3 standalone_regular_comfyui_txt2img.py \
  --config generation_probe_config.example.json \
  --out-dir /tmp/hackme_regular_comfyui_probe
```

For GGUF diagnosis without generation, run `standalone_gguf_txt2img.py --backend inspect --preflight-only`. Do not expose arbitrary GGUF repos as customer-facing options until a profile has been model-card mapped, predownloaded, and visually verified.
