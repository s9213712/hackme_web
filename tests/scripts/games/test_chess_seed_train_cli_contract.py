"""End-to-end CLI contract tests for chess_seed_train.py external replay.

These subprocess-driven tests cover the wiring layer that pure unit tests
miss — main()-level argument ordering, stdout vs disk byte-identity, and
mutation sentinels against the bundled model paths. The unit tests in
``tests/services/games/test_external_replay_safety.py`` cover the validator
in isolation; this file covers the *invocation*.

CLI mode matrix (see services.games.external_replay_safety):

  A  no --include-replay-jsonl + non-dry-run  → allowed (pre-W4 baseline,
                                                not subprocess-tested
                                                because run_training_session
                                                is slow; covered by existing
                                                unit tests).
  B  --include-replay-jsonl + --dry-run       → tested below.
  C  --include-replay-jsonl + non-dry-run + no model paths  → tested below.
  D  --include-replay-jsonl + non-dry-run + bundled path    → tested below.
  E  --include-replay-jsonl + non-dry-run + runtime path    → covered by
                                                              validator
                                                              unit tests.
  F  --include-replay-jsonl + non-dry-run + models-dir path → covered by
                                                              validator
                                                              unit tests.
  G  --include-replay-jsonl + non-dry-run + staging path    → covered by
                                                              _train_with_external_replay
                                                              skip-flag unit
                                                              tests (real
                                                              subprocess run
                                                              triggers
                                                              full self-play
                                                              schedule).
  H  --include-replay-jsonl + non-dry-run + --allow-default → covered by
                                                              validator
                                                              unit tests.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from services.games.chess_nnue import bundled_chess_nnue_model_path
from services.games.chess_pv import bundled_chess_pv_model_path
from services.games.external_replay_safety import serialize_json_payload


REPO_ROOT = Path(__file__).resolve().parents[3]
CHESS_SEED_TRAIN = REPO_ROOT / "scripts" / "games" / "chess_seed_train.py"


def _write_dummy_replay_jsonl(path: Path) -> None:
    """A minimal valid PvP-filtered row the trainers' normalizers accept."""
    row = {
        "fen": "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1",
        "move_uci": "e7e5",
        "side": "black",
        "target": 1.0,
        "weight": 0.15,
        "source": "pvp",
        "source_id": "cli_contract_test:match:1:ply:0",
        "trusted_source": "pvp_filtered",
        "label_quality": "review",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")


def _run_seed_train(
    cli_args: list[str],
    *,
    runtime_dir: Path,
    report_dir: Path,
    timeout: int = 60,
) -> subprocess.CompletedProcess:
    # Inherit the test harness env (PATH, site-packages discovery, etc.) so
    # the subprocess can import chess / python-chess; just pin
    # HACKME_RUNTIME_DIR to the test sandbox.
    env = dict(os.environ)
    env["HACKME_RUNTIME_DIR"] = str(runtime_dir)
    return subprocess.run(
        [
            sys.executable,
            str(CHESS_SEED_TRAIN),
            "--report-dir",
            str(report_dir),
            *cli_args,
        ],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(REPO_ROOT),
        timeout=timeout,
    )


def _bundled_mtimes() -> dict[str, float | None]:
    """Snapshot mtimes of bundled exp4/exp5 artifacts for mutation sentinel."""
    out: dict[str, float | None] = {}
    for label, path in (
        ("exp4_pv", bundled_chess_pv_model_path()),
        ("exp5_nnue", bundled_chess_nnue_model_path()),
    ):
        try:
            out[label] = path.stat().st_mtime
        except FileNotFoundError:
            out[label] = None
    return out


# ---- mode B: dry-run with external replay -----------------------------


def test_mode_B_dry_run_writes_artifact_and_leaves_bundled_unchanged(tmp_path):
    """Dry-run is the most critical surface — verifies main() correctly
    routes around run_training_session, the artifact is byte-identical to
    stdout, and bundled models stay untouched. Combines W4.1f + W4.1e +
    W4.1b acceptance criteria in one subprocess.
    """
    runtime = tmp_path / "rt"
    runtime.mkdir()
    report = tmp_path / "reports"
    jsonl = tmp_path / "external.jsonl"
    _write_dummy_replay_jsonl(jsonl)

    bundled_before = _bundled_mtimes()

    result = _run_seed_train(
        [
            "--preset",
            "micro",
            "--include-replay-jsonl",
            str(jsonl),
            "--dry-run",
        ],
        runtime_dir=runtime,
        report_dir=report,
        timeout=90,
    )

    assert result.returncode == 0, f"stderr:\n{result.stderr}\nstdout:\n{result.stdout}"

    # stdout is the canonical serialized payload.
    payload = json.loads(result.stdout)
    assert payload["dry_run"] is True
    assert "dry_run_artifact" in payload

    # Byte-identical: stdout == disk artifact == serialize_json_payload(payload).
    expected = serialize_json_payload(payload)
    assert result.stdout == expected, "stdout drifted from canonical serializer"

    artifact_path = Path(payload["dry_run_artifact"])
    assert artifact_path.exists(), f"dry-run artifact missing: {artifact_path}"
    assert artifact_path.read_text(encoding="utf-8") == expected, (
        "disk artifact differs from stdout — W4.1f regression"
    )

    # external_replay block confirms the validator ran end-to-end and
    # normalize_validation actually executed.
    er = payload["external_replay"]
    assert er["enabled"] is True
    assert er["dry_run"] is True
    nv = er["normalize_validation"]
    assert nv["exp4_failed"] == 0
    assert nv["exp5_failed"] == 0
    assert nv["exp4_ok"] >= 1
    assert nv["exp5_ok"] >= 1
    assert er["train_result"]["skipped_reason"] == "dry_run"
    assert er["train_result"]["trained_exp4"] is False
    assert er["train_result"]["trained_exp5"] is False

    # Mutation sentinel: bundled models must not have been touched.
    bundled_after = _bundled_mtimes()
    assert bundled_after == bundled_before, (
        f"bundled mtime drifted in dry-run: before={bundled_before} "
        f"after={bundled_after}"
    )


# ---- mode C: real run with no model paths -----------------------------


def test_mode_C_real_run_without_paths_is_rejected(tmp_path):
    runtime = tmp_path / "rt"
    runtime.mkdir()
    report = tmp_path / "reports"
    jsonl = tmp_path / "external.jsonl"
    _write_dummy_replay_jsonl(jsonl)

    bundled_before = _bundled_mtimes()

    result = _run_seed_train(
        [
            "--preset",
            "micro",
            "--include-replay-jsonl",
            str(jsonl),
        ],
        runtime_dir=runtime,
        report_dir=report,
        timeout=30,
    )

    assert result.returncode != 0
    combined = (result.stdout + "\n" + result.stderr).lower()
    assert "refusing to train" in combined
    assert "exp4 pv" in combined
    assert "exp5 nnue" in combined
    # Bundled untouched — guard fired before any training started.
    assert _bundled_mtimes() == bundled_before


# ---- mode D: real run with bundled model path explicitly ---------------


def test_mode_D_real_run_with_bundled_path_is_rejected(tmp_path):
    """W4.1e regression: typing the bundled path explicitly must not slip
    past the guard. Verifies the resolved-path check fires at the
    subprocess layer, not only in unit tests.
    """
    runtime = tmp_path / "rt"
    runtime.mkdir()
    report = tmp_path / "reports"
    jsonl = tmp_path / "external.jsonl"
    _write_dummy_replay_jsonl(jsonl)

    bundled_before = _bundled_mtimes()
    bundled_pv = str(bundled_chess_pv_model_path())

    result = _run_seed_train(
        [
            "--preset",
            "micro",
            "--include-replay-jsonl",
            str(jsonl),
            "--experiment-4-model-path",
            bundled_pv,
            "--skip-exp5",
        ],
        runtime_dir=runtime,
        report_dir=report,
        timeout=30,
    )

    assert result.returncode != 0
    combined = (result.stdout + "\n" + result.stderr).lower()
    assert "refusing to train" in combined
    assert "exp4 pv" in combined
    assert "bundled" in combined
    assert _bundled_mtimes() == bundled_before
