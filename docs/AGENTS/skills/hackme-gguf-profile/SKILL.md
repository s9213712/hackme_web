---
name: hackme-gguf-profile
description: Use when the user gives a Hugging Face GGUF repo/file/model-card location and wants it added to hackme_web as an official ComfyUI GGUF profile, tested through the project, listed in installed-GGUF inventory, documented, and optionally copied to the remote ComfyUI host for backup.
---

# Hackme GGUF Profile

## Purpose

Turn a user-supplied Hugging Face GGUF location into a verified `hackme_web`
official GGUF profile. GGUF models are not generic `repo + file` assets: each
one needs its own UNet, text encoder, VAE, loader class, workflow family, cache
and install expectations, and visual test result.

## Workflow

1. Work from `/home/s92137/hackme_web`.
2. Inspect the model card and repo metadata before editing. Use current
   sources, preferably Hugging Face model card plus ComfyUI-GGUF/custom-node
   docs if the model card references them.
3. Identify the exact profile map:
   - `repo_id`, GGUF filenames and precision variants.
   - Whether each variant is verified, draft, or disabled.
   - Companion CLIP/T5/text encoder files, VAE files, and their repos.
   - Required ComfyUI loader classes such as `DualCLIPLoaderGGUF`,
     `TripleCLIPLoader`, or `TripleCLIPLoaderGGUF`. Do not assume text
     encoders are GGUF just because the UNet is GGUF; model-card workflows may
     use safetensors CLIP/T5 with `UnetLoaderGGUF`.
   - Workflow family, sampler defaults, and known VRAM/resource expectations.
4. Edit `services/comfyui/gguf_profiles.py`; for one-off repos enable only
   variants actually verified in this project. For multi-precision repos where
   the model card provides one shared workflow map for all precision siblings,
   expose all mapped variants only after at least one representative precision
   passes routing/visual smoke, and keep each variant status clear about
   verification and high-VRAM risk.
5. If routing needs new node families or companion slots, update:
   - `services/comfyui/workflow/builder.py`
   - `routes/comfyui.py`
   - `routes/comfyui_sections/runtime_routes.py`
   - `services/comfyui/client.py`
   - frontend files under `public/`
6. Add or update tests in `tests/comfyui` and `tests/frontend/comfyui`.
   Required cases:
   - Official profile resolves to the expected GGUF/CLIP/VAE/loader.
   - Arbitrary unmapped GGUF is rejected before download.
   - Disabled variants cannot be generated.
   - `/api/comfyui/models` exposes profile and installed-GGUF inventory.
7. Run targeted checks first, then `scripts/prepush/pre_push_checks.py --ci`.
8. Write a short report under `docs/AGENTS/reports` when a real model was
   tested or a remote machine was used.
9. Commit and push only after the worktree is clean and tests pass if the user
   requested push.

## Installed GGUF Inventory

When the user asks what GGUF models are installed, use the project API once it
exists:

- `/api/comfyui/models` should include `installed_gguf_models`.
- Root/admin UI should surface the same inventory near ComfyUI model/runtime
  controls.

Inventory must be derived from ComfyUI capabilities and should include at
least: ComfyUI option name, basename, whether it matches an official profile,
profile id, variant id, enabled/verified status, and source repo when known.

## Remote Backup

The usual remote ComfyUI host is `s92137@192.168.18.19`. When asked to back up
this skill, copy the skill directory under `/mnt/d/tmp` on the remote host, for
example:

```bash
ssh s92137@192.168.18.19 'mkdir -p /mnt/d/tmp/codex_skill_backups'
rsync -a /home/s92137/.codex/skills/hackme-gguf-profile/ \
  s92137@192.168.18.19:/mnt/d/tmp/codex_skill_backups/hackme-gguf-profile/
```

Do not copy Hugging Face tokens, runtime outputs, model files, or local cache
contents as part of the skill backup.

## Guardrails

- Never store HF tokens in config, docs, commits, reports, or command history
  snippets. Use `HF_TOKEN`, `--hf-token-file`, or stdin at runtime.
- Do not add machine-specific paths such as mounted drive roots to tracked
  files. Use environment variables or blank defaults.
- Do not expose a customer-facing GGUF until its model card mapping and visual
  output have been checked. Purple/garbage output is a failed profile even if
  the ComfyUI API returns success.
- Keep disabled variants visible but blocked if they are useful for future
  validation.

## Reference

Read `references/profile-checklist.md` when adding a new profile or debugging
a profile that produces bad images.
