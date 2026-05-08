"""Verify the two ComfyUI native example JSON files under docs/comfyui/
are correctly handled by the importer.

Both files in the docs are UI-graph-format exports (with ``nodes:[...]`` /
``links:[...]`` / ``pos`` / ``widgets_values``), which spec §3.2 explicitly
rejects in favor of the API prompt format. These tests assert the
importer rejects each one with a precise sanitize-stage error so
operators can grep regressions later if someone tries to "fix" the
sanitize check by accepting UI graph silently.
"""

import json
from pathlib import Path

import pytest

from services.comfyui.validation.rules import WorkflowValidationError
from services.comfyui.validation.sanitize import sanitize_workflow_json


REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS_DIR = REPO_ROOT / "docs" / "comfyui"


_EXAMPLE_FILES = [
    "Unsaved Workflow.json",
    "sdxl_simple.json",
]


@pytest.mark.parametrize("filename", _EXAMPLE_FILES)
def test_docs_example_is_present(filename):
    path = DOCS_DIR / filename
    assert path.is_file(), f"docs/comfyui/{filename} should exist as a UI-graph reference"


@pytest.mark.parametrize("filename", _EXAMPLE_FILES)
def test_docs_example_is_ui_graph_not_api_format(filename):
    """Both examples must be UI graph (nodes/links) so the rejection test
    actually exercises the §3.2 path."""
    payload = json.loads((DOCS_DIR / filename).read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    assert "nodes" in payload and isinstance(payload["nodes"], list)
    assert "links" in payload, f"{filename} should be UI graph format"


@pytest.mark.parametrize("filename", _EXAMPLE_FILES)
def test_docs_example_is_rejected_by_sanitize(filename):
    """sanitize_workflow_json (§3) must refuse UI graph format. Without
    the rejection, a UI-graph export would slip past Gate 1 and either
    crash the analyzer downstream or — worse — get ingested as if it
    were API format."""
    payload = json.loads((DOCS_DIR / filename).read_text(encoding="utf-8"))
    with pytest.raises(WorkflowValidationError):
        sanitize_workflow_json(payload)


def test_unsaved_workflow_top_level_keys_match_ui_graph_shape():
    """Spot-check the canonical UI-graph shape so any future
    UI-graph variant we want to add as a regression case can be
    validated against this baseline."""
    payload = json.loads((DOCS_DIR / "Unsaved Workflow.json").read_text(encoding="utf-8"))
    assert {"nodes", "links", "groups", "config", "extra", "version"} <= set(payload.keys())


def test_sdxl_simple_carries_ksampler_advanced_node():
    """sdxl_simple.json should advertise a SDXL-typical KSamplerAdvanced
    node — confirms the example is meaningfully different from
    Unsaved Workflow.json's KSampler."""
    payload = json.loads((DOCS_DIR / "sdxl_simple.json").read_text(encoding="utf-8"))
    types = {node.get("type", "") for node in payload.get("nodes", [])}
    assert "KSamplerAdvanced" in types
