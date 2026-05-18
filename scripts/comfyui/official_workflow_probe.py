#!/usr/bin/env python3
"""Probe checked-in official ComfyUI workflows against a live ComfyUI API.

This intentionally bypasses hackme_web routes. It validates whether the
official workflow bundles themselves can be accepted by the target ComfyUI
server, then optionally queues each runnable workflow and fetches its output.
"""

from __future__ import annotations

import argparse
import copy
import json
import struct
import sys
import time
import zlib
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.comfyui.client import ComfyUIClient, ComfyUIError  # noqa: E402
from services.comfyui.template.seeding import SYSTEM_WORKFLOW_IDS  # noqa: E402


MODEL_INPUTS = {
    "CheckpointLoaderSimple": {"ckpt_name": ("CheckpointLoaderSimple", "ckpt_name")},
    "UNETLoader": {"unet_name": ("UNETLoader", "unet_name")},
    "CLIPLoader": {"clip_name": ("CLIPLoader", "clip_name")},
    "DualCLIPLoader": {
        "clip_name1": ("DualCLIPLoader", "clip_name1"),
        "clip_name2": ("DualCLIPLoader", "clip_name2"),
    },
    "VAELoader": {"vae_name": ("VAELoader", "vae_name")},
    "LoraLoader": {"lora_name": ("LoraLoader", "lora_name")},
    "LoraLoaderModelOnly": {"lora_name": ("LoraLoaderModelOnly", "lora_name")},
    "ControlNetLoader": {"control_net_name": ("ControlNetLoader", "control_net_name")},
    "UpscaleModelLoader": {"model_name": ("UpscaleModelLoader", "model_name")},
}

HEAVY_WORKFLOWS = {"ace_step_15_t2a_song", "wan22_14b_i2v_subgraphed"}


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _png_rgba(width, height, rgba):
    r, g, b, a = [max(0, min(255, int(v))) for v in rgba]
    row = bytes([r, g, b, a]) * int(width)
    raw = b"".join(b"\x00" + row for _ in range(int(height)))

    def chunk(tag, payload):
        body = tag + payload
        return struct.pack("!I", len(payload)) + body + struct.pack("!I", zlib.crc32(body) & 0xFFFFFFFF)

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack("!IIBBBBB", int(width), int(height), 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, level=9))
        + chunk(b"IEND", b"")
    )


def _load_workflow(bundle_id):
    path = REPO_ROOT / "workflows" / "comfyui" / bundle_id / "workflow.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _node_options(object_info, node_class, input_name):
    node = object_info.get(node_class) if isinstance(object_info, dict) else None
    required = ((node or {}).get("input") or {}).get("required") or {}
    raw = required.get(input_name)
    if isinstance(raw, list) and raw:
        first = raw[0]
        if isinstance(first, list):
            return {str(item) for item in first if str(item).strip()}
    return set()


def _preflight(bundle_id, workflow, object_info):
    available_classes = set(object_info.keys()) if isinstance(object_info, dict) else set()
    missing_nodes = []
    missing_models = []
    for node_id, node in sorted((workflow or {}).items(), key=lambda item: str(item[0])):
        if not isinstance(node, dict):
            continue
        class_type = str(node.get("class_type") or "").strip()
        if not class_type:
            missing_nodes.append({"node_id": node_id, "class_type": ""})
            continue
        if class_type not in available_classes:
            missing_nodes.append({"node_id": node_id, "class_type": class_type})
            continue
        inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}
        for input_name, option_ref in (MODEL_INPUTS.get(class_type) or {}).items():
            value = str(inputs.get(input_name) or "").strip()
            if not value:
                continue
            options = _node_options(object_info, *option_ref)
            if options and value not in options:
                missing_models.append({
                    "node_id": node_id,
                    "class_type": class_type,
                    "input": input_name,
                    "value": value,
                })
    return {
        "bundle_id": bundle_id,
        "missing_nodes": missing_nodes,
        "missing_models": missing_models,
        "runnable": not missing_nodes and not missing_models,
    }


def _patch_for_probe(
    workflow,
    bundle_id,
    *,
    width,
    height,
    steps,
    prompt,
    negative_prompt,
    checkpoint_model,
    source_image_name,
    mask_image_name,
):
    patched = copy.deepcopy(workflow)
    negative_node_ids = set()
    for node in patched.values():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}
        ref = inputs.get("negative")
        if isinstance(ref, list) and ref:
            negative_node_ids.add(str(ref[0]))
    for node in patched.values():
        if not isinstance(node, dict):
            continue
        class_type = str(node.get("class_type") or "")
        inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}
        if checkpoint_model and class_type == "CheckpointLoaderSimple" and "ckpt_name" in inputs:
            inputs["ckpt_name"] = checkpoint_model
        if "steps" in inputs:
            try:
                inputs["steps"] = min(int(inputs["steps"]), int(steps))
            except Exception:
                inputs["steps"] = int(steps)
        if "width" in inputs and isinstance(inputs.get("width"), int):
            inputs["width"] = min(int(inputs["width"]), int(width))
        if "height" in inputs and isinstance(inputs.get("height"), int):
            inputs["height"] = min(int(inputs["height"]), int(height))
        if "size_preset" in inputs and isinstance(inputs.get("size_preset"), str):
            inputs["size_preset"] = f"{int(width)}x{int(height)} (1:1)"
        if "resolution" in inputs and isinstance(inputs.get("resolution"), str):
            inputs["resolution"] = "1K" if max(int(width), int(height)) >= 1024 else "auto"
        if "prompt" in inputs and isinstance(inputs.get("prompt"), str):
            inputs["prompt"] = prompt
        if "text" in inputs and isinstance(inputs.get("text"), str):
            node_id = next((str(key) for key, value in patched.items() if value is node), "")
            inputs["text"] = negative_prompt if node_id in negative_node_ids else prompt
        if "batch_size" in inputs:
            inputs["batch_size"] = 1
        if "max_images" in inputs:
            inputs["max_images"] = 1
        if "number_of_images" in inputs:
            inputs["number_of_images"] = 1
        if "filename_prefix" in inputs:
            output_kind = "probe"
            if "audio" in class_type.lower():
                output_kind = "audio"
            elif "video" in class_type.lower():
                output_kind = "video"
            inputs["filename_prefix"] = f"{output_kind}/hackme_official_probe/{bundle_id}"
        if class_type == "LoadImage":
            inputs["image"] = source_image_name
            inputs["upload"] = "image"
        elif class_type == "LoadImageMask":
            inputs["image"] = mask_image_name
            inputs["upload"] = "image"
    return patched


def _result(bundle_id, *, status, detail="", preflight=None, elapsed_ms=None, output=None):
    payload = {
        "bundle_id": bundle_id,
        "status": status,
        "detail": detail,
        "checked_at": _now(),
    }
    if preflight is not None:
        payload["preflight"] = preflight
    if elapsed_ms is not None:
        payload["elapsed_ms"] = int(elapsed_ms)
    if output is not None:
        payload["output"] = output
    return payload


def run_probe(args):
    client = ComfyUIClient(args.comfyui_url, timeout=args.request_timeout)
    object_info = client.get_object_info()
    source_ref = client.upload_image_bytes(
        _png_rgba(args.image_size, args.image_size, (80, 140, 230, 255)),
        "hackme_official_probe_source.png",
        overwrite=True,
    )
    mask_ref = client.upload_image_bytes(
        _png_rgba(args.image_size, args.image_size, (255, 255, 255, 255)),
        "hackme_official_probe_mask.png",
        overwrite=True,
    )
    source_image_name = source_ref["filename"]
    mask_image_name = mask_ref["filename"]

    bundle_ids = list(SYSTEM_WORKFLOW_IDS)
    if args.only:
        wanted = {item.strip() for item in args.only.split(",") if item.strip()}
        bundle_ids = [item for item in bundle_ids if item in wanted]
    results = []
    for bundle_id in bundle_ids:
        workflow = _load_workflow(bundle_id)
        preflight = _preflight(bundle_id, workflow, object_info)
        if not preflight["runnable"]:
            results.append(_result(bundle_id, status="preflight_failed", preflight=preflight))
            if not args.continue_on_fail:
                break
            continue
        if args.preflight_only:
            results.append(_result(bundle_id, status="preflight_pass", preflight=preflight))
            continue
        if bundle_id in HEAVY_WORKFLOWS and not args.include_heavy:
            results.append(_result(bundle_id, status="skipped_heavy", preflight=preflight, detail="Use --include-heavy to run this heavy audio/video workflow."))
            continue
        patched = _patch_for_probe(
            workflow,
            bundle_id,
            width=args.width,
            height=args.height,
            steps=args.steps,
            prompt=args.prompt,
            negative_prompt=args.negative_prompt,
            checkpoint_model=args.checkpoint_model,
            source_image_name=source_image_name,
            mask_image_name=mask_image_name,
        )
        start = time.perf_counter()
        try:
            output = client.generate_from_workflow(patched, timeout_seconds=args.timeout, expected_count=1)
            elapsed_ms = (time.perf_counter() - start) * 1000
            media = output.get("media") if isinstance(output.get("media"), dict) else {}
            output_summary = {
                "prompt_id": output.get("prompt_id"),
                "primary_ref": output.get("image_ref"),
                "mime_type": output.get("mime_type"),
                "bytes": len(output.get("data") or b""),
                "image_count": len(output.get("images") or []),
                "video_count": len(media.get("videos") or []),
                "audio_count": len(media.get("audio") or []),
            }
            results.append(_result(bundle_id, status="completed", preflight=preflight, elapsed_ms=elapsed_ms, output=output_summary))
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start) * 1000
            results.append(_result(bundle_id, status="run_failed", preflight=preflight, elapsed_ms=elapsed_ms, detail=str(exc)))
            if not args.continue_on_fail:
                break

    completed = sum(1 for item in results if item["status"] == "completed")
    failed = sum(1 for item in results if item["status"] in {"preflight_failed", "run_failed"})
    return {
        "ok": failed == 0,
        "summary": {
            "comfyui_url": args.comfyui_url,
            "started_at": _now(),
            "bundle_count": len(bundle_ids),
            "completed": completed,
            "failed": failed,
            "preflight_only": bool(args.preflight_only),
            "include_heavy": bool(args.include_heavy),
        },
        "results": results,
    }


def parse_args():
    parser = argparse.ArgumentParser(description="Probe official hackme_web ComfyUI workflows.")
    parser.add_argument("--comfyui-url", default="http://127.0.0.1:8188")
    parser.add_argument("--timeout", type=int, default=240)
    parser.add_argument("--request-timeout", type=int, default=30)
    parser.add_argument("--steps", type=int, default=2)
    parser.add_argument("--width", type=int, default=512)
    parser.add_argument("--height", type=int, default=512)
    parser.add_argument("--image-size", type=int, default=128)
    parser.add_argument("--prompt", default="hackme_web official workflow probe")
    parser.add_argument("--negative-prompt", default="low quality, blurry, watermark, child, minor")
    parser.add_argument("--checkpoint-model", default="", help="Override CheckpointLoaderSimple ckpt_name for smoke/acceptance probes.")
    parser.add_argument("--only", default="", help="Comma-separated workflow ids to test.")
    parser.add_argument("--include-heavy", action="store_true", help="Also run audio/video heavy workflows.")
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--continue-on-fail", action="store_true")
    parser.add_argument("--json-out", default="")
    return parser.parse_args()


def main():
    args = parse_args()
    try:
        report = run_probe(args)
    except Exception as exc:
        report = {
            "ok": False,
            "summary": {"comfyui_url": args.comfyui_url, "started_at": _now(), "bundle_count": 0, "completed": 0, "failed": 1},
            "results": [_result("probe", status="probe_failed", detail=str(exc))],
        }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.json_out:
        path = Path(args.json_out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
    print(text)
    raise SystemExit(0 if report.get("ok") else 1)


if __name__ == "__main__":
    main()
