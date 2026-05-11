from pathlib import Path

from services.system.release_artifacts import (
    build_qa_artifact_index,
    create_release_bundle,
    release_bundle_status,
)


def test_qa_artifact_index_collects_runtime_docs_and_tmp_artifacts(tmp_path):
    base = tmp_path / "repo"
    reports = tmp_path / "runtime" / "reports"
    tmp_root = tmp_path / "tmp"
    (base / "docs" / "AGENTS" / "reports").mkdir(parents=True)
    (reports / "qa").mkdir(parents=True)
    (tmp_root / "hackme_web_run" / "reports" / "qa").mkdir(parents=True)
    (base / "docs" / "AGENTS" / "reports" / "manual.md").write_text("# report\n", encoding="utf-8")
    (reports / "qa" / "playwright_deep_site_check.json").write_text('{"ok": true}\n', encoding="utf-8")
    (tmp_root / "hackme_web_run" / "reports" / "qa" / "screen.png").write_bytes(b"png")

    index = build_qa_artifact_index(
        base_dir=base,
        reports_dir=reports,
        tmp_root=tmp_root,
        limit=20,
        persist=True,
    )

    assert index["ok"] is True
    assert index["summary"]["artifact_count"] >= 3
    assert index["summary"]["by_kind"]["playwright"] == 1
    assert index["summary"]["by_kind"]["screenshot"] == 1
    assert Path(index["index_path"]).exists()


def test_release_bundle_marks_ready_only_when_gate_is_green(tmp_path):
    base = tmp_path / "repo"
    reports = tmp_path / "runtime" / "reports"
    base.mkdir()
    requirements = {
        "ok": True,
        "required": ["pytest"],
        "missing": [],
        "failed": [],
        "reports": {"pytest": {"target_commit": "abc123", "report_source": "test"}},
    }
    qa_index = {"generated_at": "now", "summary": {"artifact_count": 2}, "index_path": "reports/qa_artifacts/index.json"}

    bundle = create_release_bundle(
        base_dir=base,
        reports_dir=reports,
        git_repo_dir=base,
        created_by="root",
        production_requirements=requirements,
        qa_artifacts=qa_index,
        mark_ready=True,
    )

    assert bundle["ready"] is True
    assert Path(bundle["bundle_path"]).exists()
    assert Path(bundle["markdown_path"]).exists()
    status = release_bundle_status(reports_dir=reports)
    assert status["ready"] is True
    assert status["marker"]["bundle_path"] == bundle["bundle_path"]


def test_release_bundle_blocked_gate_does_not_mark_ready(tmp_path):
    base = tmp_path / "repo"
    reports = tmp_path / "runtime" / "reports"
    base.mkdir()
    requirements = {"ok": False, "required": ["pytest"], "missing": ["pytest"], "failed": [], "reports": {}}
    qa_index = {"generated_at": "now", "summary": {"artifact_count": 0}, "index_path": ""}

    bundle = create_release_bundle(
        base_dir=base,
        reports_dir=reports,
        git_repo_dir=base,
        created_by="root",
        production_requirements=requirements,
        qa_artifacts=qa_index,
        mark_ready=True,
    )

    assert bundle["ready"] is False
    assert bundle["status"] == "blocked"
    assert not (reports / "security" / "production_gate" / "production_ready_marker.json").exists()
