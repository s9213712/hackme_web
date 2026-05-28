from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_experiment_area_uses_bounded_performance_profile():
    js = (ROOT / "public" / "js" / "42-experiments.js").read_text(encoding="utf-8")

    assert "function experimentPerformanceProfile()" in js
    assert "navigator.hardwareConcurrency" in js
    assert "prefers-reduced-motion: reduce" in js
    assert "EXPERIMENT_DPR_CAP" in js
    assert "const dt = Math.min(64" in js
