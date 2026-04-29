import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _release_id():
    tree = ast.parse((ROOT / "services" / "release_info.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "APP_RELEASE_ID":
                    return node.value.value
    raise AssertionError("APP_RELEASE_ID not found")


def test_release_id_is_synced_to_public_docs():
    release_id = _release_id()
    assert release_id == "2026.04.29-020"
    for rel in ("README.md", "README.zh-TW.md", "For_developer.md"):
        assert release_id in (ROOT / rel).read_text(encoding="utf-8")


def test_branching_policy_documents_numbered_branch_sequence():
    doc = (ROOT / "docs" / "BRANCHING_AND_RELEASE.md").read_text(encoding="utf-8")
    assert "01-feature-new-development" in doc
    assert "02-feature-forum-governance-security-modes" in doc
    assert "03-sidebar" in doc
    assert "04-economy" in doc
    assert "last numeric segment by 1" in doc
