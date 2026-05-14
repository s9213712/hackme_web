"""Contract tests for services/games/external_replay_safety.py (W4.2).

Locks the invariants that previously needed W4.1d / W4.1e / W4.1f patches:

  - canonical JSON serialization (matched key order, ensure_ascii=False,
    indent=2, trailing newline)
  - default-path detection across three layers (bundled / runtime / models-dir)
  - mutation-policy validator covers the CLI mode matrix A–H

If any layer regresses, this file fails before any CLI smoke test does.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.games.chess_nnue import (
    bundled_chess_nnue_model_path,
    default_chess_nnue_model_path,
)
from services.games.chess_pv import (
    bundled_chess_pv_model_path,
    default_chess_pv_model_path,
)
from services.games.external_replay_safety import (
    BUNDLED_MODELS_DIR,
    EngineMutationSpec,
    MutationPolicy,
    format_policy_violation,
    is_default_model_path,
    serialize_json_payload,
    validate_mutation_policy,
)


# ---- serialize_json_payload --------------------------------------------


def test_serialize_json_payload_is_deterministic_for_same_dict():
    payload = {"b": 1, "a": [2, 3], "c": {"y": True, "x": "中文"}}
    out_1 = serialize_json_payload(payload)
    out_2 = serialize_json_payload(payload)
    assert out_1 == out_2


def test_serialize_json_payload_settings_are_pinned():
    payload = {"b": 1, "a": "中文", "z": 0}
    out = serialize_json_payload(payload)
    # sort_keys + indent=2 + ensure_ascii=False + trailing newline.
    assert out.endswith("\n")
    assert "中文" in out  # ensure_ascii=False keeps raw Chinese, not \uXXXX
    assert "\\u" not in out  # belt-and-braces: no escaped unicode emitted
    keys_in_order = [line.split('"')[1] for line in out.splitlines() if line.startswith("  \"")]
    assert keys_in_order == sorted(keys_in_order)
    assert "  " in out  # indent=2 produces two-space indentation


def test_serialize_json_payload_byte_identical_for_roundtrip():
    payload = {"x": 1, "y": [3, 2, 1]}
    out = serialize_json_payload(payload)
    parsed = json.loads(out)
    assert serialize_json_payload(parsed) == out


# ---- is_default_model_path --------------------------------------------


def test_is_default_model_path_flags_bundled_pv_path():
    bundled = str(bundled_chess_pv_model_path())
    is_default, reason = is_default_model_path(
        bundled,
        bundled_resolver=bundled_chess_pv_model_path,
        default_resolver=default_chess_pv_model_path,
    )
    assert is_default is True
    assert "bundled" in reason


def test_is_default_model_path_flags_runtime_default(monkeypatch, tmp_path):
    monkeypatch.setenv("HACKME_RUNTIME_DIR", str(tmp_path))
    runtime = str(default_chess_nnue_model_path())
    is_default, reason = is_default_model_path(
        runtime,
        bundled_resolver=bundled_chess_nnue_model_path,
        default_resolver=default_chess_nnue_model_path,
    )
    assert is_default is True
    assert "runtime default" in reason


def test_is_default_model_path_flags_models_dir_sibling():
    sibling = str(BUNDLED_MODELS_DIR / "chess_experiment_4_pv_handmade.json")
    is_default, reason = is_default_model_path(
        sibling,
        bundled_resolver=bundled_chess_pv_model_path,
        default_resolver=bundled_chess_pv_model_path,
    )
    assert is_default is True
    assert "bundled-models dir" in reason


def test_is_default_model_path_allows_unrelated_path(tmp_path):
    candidate = tmp_path / "candidate" / "exp4_candidate.json"
    is_default, reason = is_default_model_path(
        str(candidate),
        bundled_resolver=bundled_chess_pv_model_path,
        default_resolver=bundled_chess_pv_model_path,
    )
    assert is_default is False
    assert reason == ""


def test_is_default_model_path_handles_empty_string():
    is_default, reason = is_default_model_path(
        "",
        bundled_resolver=bundled_chess_pv_model_path,
        default_resolver=bundled_chess_pv_model_path,
    )
    assert is_default is False
    assert reason == ""


# ---- validate_mutation_policy (CLI mode matrix A..H) ------------------


def _spec(engine_id: str, *, explicit_path: str = "", skip: bool = False) -> EngineMutationSpec:
    if engine_id == "exp4 PV":
        return EngineMutationSpec(
            engine_id=engine_id,
            cli_path_flag="--experiment-4-model-path",
            cli_skip_flag="--skip-exp4",
            explicit_path=explicit_path,
            skip=skip,
            bundled_resolver=bundled_chess_pv_model_path,
            default_resolver=default_chess_pv_model_path,
        )
    return EngineMutationSpec(
        engine_id="exp5 NNUE",
        cli_path_flag="--experiment-5-model-path",
        cli_skip_flag="--skip-exp5",
        explicit_path=explicit_path,
        skip=skip,
        bundled_resolver=bundled_chess_nnue_model_path,
        default_resolver=default_chess_nnue_model_path,
    )


def _policy(**kw) -> MutationPolicy:
    defaults = dict(
        dry_run=False,
        allow_default_model_paths=False,
        include_external_replay=True,
        engines=(_spec("exp4 PV"), _spec("exp5 NNUE")),
    )
    defaults.update(kw)
    return MutationPolicy(**defaults)


def test_mode_A_no_external_replay_is_always_allowed():
    """No --include-replay-jsonl → pre-W4 behaviour, validator is a no-op."""
    assert validate_mutation_policy(_policy(include_external_replay=False)) == []


def test_mode_B_dry_run_with_external_replay_allowed():
    """dry-run skips all mutation, even with implicit default paths."""
    assert validate_mutation_policy(_policy(dry_run=True)) == []


def test_mode_C_real_run_without_paths_rejected():
    problems = validate_mutation_policy(_policy())
    assert len(problems) == 2
    assert any("exp4 PV" in p and "--experiment-4-model-path" in p for p in problems)
    assert any("exp5 NNUE" in p and "--experiment-5-model-path" in p for p in problems)


def test_mode_D_bundled_path_rejected():
    bundled = str(bundled_chess_pv_model_path())
    policy = _policy(
        engines=(_spec("exp4 PV", explicit_path=bundled), _spec("exp5 NNUE", skip=True))
    )
    problems = validate_mutation_policy(policy)
    assert len(problems) == 1
    assert "exp4 PV" in problems[0]
    assert "bundled" in problems[0].lower()


def test_mode_E_runtime_default_path_rejected(monkeypatch, tmp_path):
    monkeypatch.setenv("HACKME_RUNTIME_DIR", str(tmp_path))
    runtime = str(default_chess_nnue_model_path())
    policy = _policy(
        engines=(_spec("exp4 PV", skip=True), _spec("exp5 NNUE", explicit_path=runtime))
    )
    problems = validate_mutation_policy(policy)
    assert len(problems) == 1
    assert "exp5 NNUE" in problems[0]
    assert "runtime default" in problems[0]


def test_mode_F_models_dir_sibling_rejected():
    sibling = str(BUNDLED_MODELS_DIR / "chess_experiment_5_nnue_local.json")
    policy = _policy(
        engines=(_spec("exp4 PV", skip=True), _spec("exp5 NNUE", explicit_path=sibling))
    )
    problems = validate_mutation_policy(policy)
    assert len(problems) == 1
    assert "models" in problems[0]


def test_mode_G_staging_path_allowed(tmp_path):
    staging4 = str(tmp_path / "staging" / "exp4_candidate.json")
    staging5 = str(tmp_path / "staging" / "exp5_candidate.json")
    policy = _policy(
        engines=(
            _spec("exp4 PV", explicit_path=staging4),
            _spec("exp5 NNUE", explicit_path=staging5),
        )
    )
    assert validate_mutation_policy(policy) == []


def test_mode_H_allow_default_flag_overrides_default_detection():
    bundled = str(bundled_chess_pv_model_path())
    policy = _policy(
        allow_default_model_paths=True,
        engines=(_spec("exp4 PV", explicit_path=bundled), _spec("exp5 NNUE", skip=True)),
    )
    assert validate_mutation_policy(policy) == []


def test_skip_engine_does_not_need_path():
    """skip_exp* takes the engine out of the validation entirely."""
    policy = _policy(
        engines=(_spec("exp4 PV", skip=True), _spec("exp5 NNUE", skip=True)),
    )
    assert validate_mutation_policy(policy) == []


def test_format_policy_violation_mentions_allow_default_escape():
    problems = ["exp4 PV: --experiment-4-model-path resolves to bundled path /x"]
    msg = format_policy_violation(problems)
    assert "refusing to train" in msg
    assert "--allow-default-model-paths" in msg
    assert "exp4 PV" in msg
