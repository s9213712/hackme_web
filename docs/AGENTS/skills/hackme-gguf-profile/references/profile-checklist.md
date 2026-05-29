# GGUF Profile Checklist

Use this checklist for each new Hugging Face GGUF location.

## Metadata

- Hugging Face repo id:
- Source model card URL:
- GGUF file names:
- Precision variants:
- Variant sizes:
- License or access constraints:
- Token required:

## ComfyUI Mapping

- UNet loader class:
- CLIP loader class:
- Text encoder slot 1:
- Text encoder slot 2:
- Text encoder slot 3, if any:
- VAE file:
- Extra custom nodes:
- Workflow family:
- Whether the model-card workflow uses GGUF text-encoder loaders or normal
  safetensors loaders. Native GGUF UNet does not imply `TripleCLIPLoaderGGUF`.

## Project Changes

- Add profile in `services/comfyui/gguf_profiles.py`.
- Add or update companion-slot routing if the loader shape is new.
- Expose profile and variant to `/api/comfyui/models`.
- Update frontend dropdown behavior if needed.
- Update tests for valid profile, arbitrary rejection, disabled variant, and
  installed inventory.

## Test Evidence

- Download/cache root:
- Installed ComfyUI model paths:
- Output image path:
- Prompt/negative prompt:
- Width/height/steps/cfg/seed:
- ComfyUI total seconds:
- Peak VRAM/RSS if measured:
- Visual result: pass/fail and reason.

## Failure Handling

- If output is malformed, confirm companion files and loader class first.
- If API succeeds but image is garbage, keep the profile disabled.
- If multiple precision variants share one official workflow map, test at least
  one representative precision and mark other exposed variants with clear
  mapped/high-VRAM status.
