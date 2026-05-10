#!/usr/bin/env python3
"""Playwright check for the ComfyUI visual node/line workflow builder.

This serves the public directory from an isolated localhost port and verifies
the standalone builder can render nodes, drag nodes, and create a wire by
dragging from an output port to an input port.
"""

from __future__ import annotations

import socket
import subprocess
import sys
import tempfile
import time
import json
from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[2]
PUBLIC_DIR = ROOT / "public"


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def center(box: dict[str, float]) -> tuple[float, float]:
    return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2


def drag_between(page, source_selector: str, target_selector: str) -> None:
    source = page.locator(source_selector).first
    target = page.locator(target_selector).first
    source.wait_for(state="visible", timeout=5000)
    target.wait_for(state="visible", timeout=5000)
    source.scroll_into_view_if_needed()
    source_box = source.bounding_box()
    source.hover()
    page.mouse.down()
    target.scroll_into_view_if_needed()
    target_box = target.bounding_box()
    if not source_box or not target_box:
        raise AssertionError("source/target port missing bounding box")
    sx, sy = center(source_box)
    tx, ty = center(target_box)
    page.mouse.move((sx + tx) / 2, (sy + ty) / 2, steps=8)
    target.hover()
    page.mouse.up()


def main() -> int:
    port = free_port()
    server = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1", "--directory", str(PUBLIC_DIR)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        cwd=str(ROOT),
    )
    try:
        time.sleep(0.4)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.goto(f"http://127.0.0.1:{port}/comfyui-workflow-editor.html", wait_until="networkidle")
            page.locator(".wf-node").first.wait_for(state="visible", timeout=8000)

            node_count = page.locator(".wf-node").count()
            edge_count = page.locator(".edge-path").count()
            if node_count < 7 or edge_count < 8:
                raise AssertionError(f"starter graph incomplete: nodes={node_count}, edges={edge_count}")

            drag_between(
                page,
                '.wf-node:has-text("主模型") .port.output[data-port-name="VAE"]',
                '.wf-node:has-text("VAE 解碼") .port.input[data-port-name="vae"]',
            )
            status = page.locator("#status").inner_text(timeout=5000)
            if "已連線" not in status:
                raise AssertionError(f"port drag did not create connection, status={status!r}")
            edge_rows_before = page.locator("[data-delete-edge]").count()
            if edge_rows_before < 1:
                raise AssertionError("edge management panel did not list removable edges")
            page.locator("[data-delete-edge]").first.click()
            edge_rows_after = page.locator("[data-delete-edge]").count()
            if edge_rows_after >= edge_rows_before:
                raise AssertionError("deleting an edge did not update the edge list")

            first_node = page.locator(".wf-node").first
            first_node.scroll_into_view_if_needed()
            first_box = first_node.bounding_box()
            first_edge_before = page.locator(".edge-path").first.get_attribute("d")
            if not first_box:
                raise AssertionError("first node missing bounding box")
            page.mouse.move(first_box["x"] + 35, first_box["y"] + 20)
            page.mouse.down()
            page.mouse.move(first_box["x"] + 70, first_box["y"] + 45, steps=8)
            page.mouse.up()
            first_edge_after = page.locator(".edge-path").first.get_attribute("d")
            if first_edge_before == first_edge_after:
                raise AssertionError("dragging a node did not update edge geometry")

            page.locator('[data-add-node="LoadImage"]').click()
            page.locator('.wf-node:has-text("Load Image")').last.wait_for(state="visible", timeout=5000)
            page.locator('[data-add-node="ImagePadForOutpaint"]').click()
            if page.locator('.wf-node:has-text("Outpaint Pad")').count() < 1:
                raise AssertionError("Outpaint Pad node was not added")

            with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8", delete=False) as handle:
                json.dump(
                    {
                        "name": "Imported visual graph",
                        "workflow_json": {
                            "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "demo.safetensors"}, "_meta": {"title": "Imported Model"}},
                            "2": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["1", 1], "text": "hello"}, "_meta": {"title": "Imported Prompt"}},
                        },
                        "layout_json": {
                            "node_order": ["1", "2"],
                            "node_positions": {"1": [80, 80], "2": [360, 80]},
                            "field_overrides": {"1": {"label": "Imported Model"}, "2": {"label": "Imported Prompt"}},
                        },
                    },
                    handle,
                )
                import_path = handle.name
            page.locator("#importJsonFile").set_input_files(import_path)
            page.locator('.wf-node:has-text("Imported Model")').wait_for(state="visible", timeout=5000)
            imported_status = page.locator("#status").inner_text(timeout=5000)
            if "已匯入 JSON" not in imported_status:
                raise AssertionError(f"JSON import did not report success, status={imported_status!r}")
            exported = json.loads(page.locator("#jsonOut").input_value())
            workflow_ids = set(exported["workflow_json"].keys())
            layout_ids = set(exported["layout_json"]["node_order"])
            if not layout_ids.issubset(workflow_ids):
                raise AssertionError(f"exported layout ids do not match workflow ids: workflow={workflow_ids}, layout={layout_ids}")

            mobile_page = browser.new_page(viewport={"width": 390, "height": 844})
            mobile_page.goto(f"http://127.0.0.1:{port}/comfyui-workflow-editor.html", wait_until="networkidle")
            mobile_page.locator(".wf-node").first.wait_for(state="visible", timeout=8000)
            mobile_widths = mobile_page.evaluate("({body: document.body.scrollWidth, doc: document.documentElement.scrollWidth, inner: window.innerWidth})")
            if mobile_widths["body"] > mobile_widths["inner"] or mobile_widths["doc"] > mobile_widths["inner"]:
                raise AssertionError(f"mobile viewport has page-level horizontal overflow: {mobile_widths}")
            mobile_page.close()

            browser.close()
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
    print("PASS comfyui visual workflow builder: render, drag, wire, delete edge, import JSON, and mobile layout work")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
