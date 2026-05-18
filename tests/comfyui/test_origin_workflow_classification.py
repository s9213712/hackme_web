from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ORIGIN_DIR = ROOT / "workflows" / "comfyui" / "origin"

ALLOWED_CATEGORIES = {
    ("audio", "t2a"),
    ("image", "controlnet"),
    ("image", "edit"),
    ("image", "outpaint"),
    ("image", "txt2img"),
    ("utility", "compare"),
    ("utility", "pose"),
    ("utility", "segmentation"),
    ("utility", "upscale"),
    ("video", "edit"),
    ("video", "i2v"),
    ("video", "t2v"),
}


def test_origin_workflow_jsons_are_classified_under_category_and_mode():
    root_jsons = sorted(path.name for path in ORIGIN_DIR.glob("*.json"))
    assert root_jsons == []

    workflow_paths = sorted(ORIGIN_DIR.glob("*/*/*.json"))
    assert workflow_paths

    for path in workflow_paths:
        rel = path.relative_to(ORIGIN_DIR)
        assert (rel.parts[0], rel.parts[1]) in ALLOWED_CATEGORIES


def test_origin_workflow_readme_indexes_every_raw_workflow():
    readme = (ORIGIN_DIR / "README.md").read_text(encoding="utf-8")

    for path in sorted(ORIGIN_DIR.glob("*/*/*.json")):
        rel = path.relative_to(ORIGIN_DIR).as_posix()
        assert f"`{rel}`" in readme
