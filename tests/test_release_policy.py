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
    assert release_id == "2026.05.02-039"
    for rel in ("README.md", "docs/README.zh-TW.md", "docs/For_developer.md"):
        assert release_id in (ROOT / rel).read_text(encoding="utf-8")


def test_branching_policy_documents_numbered_branch_sequence():
    doc = (ROOT / "docs" / "BRANCHING_AND_RELEASE.md").read_text(encoding="utf-8")
    assert "main" in doc
    assert "01.POINTSCHAIN" in doc
    assert "02-WebTerminal-docker" in doc
    assert "02-WebTerminal-qemu" in doc
    assert "03.Economy" in doc
    assert "hackme_web_lite" in doc
    assert "last numeric segment by 1" in doc


def test_root_keeps_only_readme_markdown_and_docs_has_index():
    root_markdown = sorted(path.name for path in ROOT.glob("*.md"))
    assert root_markdown == ["README.md", "SECURITY.md"]

    docs_index = (ROOT / "docs" / "README.md").read_text(encoding="utf-8")
    expected_links = [
        "README.zh-TW.md",
        "WEB.md",
        "For_developer.md",
        "SECURITY.md",
        "PHASE_STATUS.md",
        "implementation_workflow.md",
        "BRANCHING_AND_RELEASE.md",
        "security/PRE_RELEASE_CHECKLIST.md",
        "security/FUNCTIONAL_SMOKE.md",
        "security/FUNCTIONAL_PERMISSION_PENTEST.md",
        "security/PENTEST.md",
    ]
    for link in expected_links:
        assert f"]({link})" in docs_index
