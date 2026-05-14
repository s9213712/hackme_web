"""Adapter producing a unified EngineDecision dict from exp4 (PV) or exp5 (NNUE).

Phase 1 sparring smoke (diagnostic-only). Read-only invocation:
- Never writes to disk, store, or replay buffer.
- Audit fail-soft: explain calls are wrapped so per-ply errors don't crash the loop.
- exp4 uses the full chess_pv decision path (fusion / rule_guard / override / sanity);
  time-budget variance is accepted for smoke (see project memory: phase 2 will add
  fixed_depth_* profiles to chess_pv).
- exp5 uses fixed_depth_strong by default (deterministic, no time budget).
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import chess

from services.games.chess_pv import (
    choose_experiment_pv_move,
    explain_experiment_pv_decision,
)
from services.games.chess_nnue import (
    choose_experiment_nnue_move,
    explain_experiment_nnue_decision,
)


def compute_model_hash(model_path: Path) -> str:
    return hashlib.sha256(Path(model_path).read_bytes()).hexdigest()


def _move_dict_to_uci(move_dict: dict | None) -> str:
    if not move_dict:
        return ""
    fr = str(move_dict.get("from") or "")
    to = str(move_dict.get("to") or "")
    promo = str(move_dict.get("promotion") or "")
    if not fr or not to:
        return ""
    return (fr + to + promo).lower()


def _empty_decision(
    engine_id: str,
    model_path: Path,
    model_hash: str,
    fen: str,
    side: str,
    reason: str,
) -> dict:
    return {
        "engine_id": engine_id,
        "model_path": str(model_path),
        "model_hash": model_hash,
        "fen_before": fen,
        "side": side,
        "move": "",
        "legal": False,
        "raw_policy_top1": None,
        "raw_policy_top3": [],
        "search_best_move": None,
        "search_score": None,
        "final_score": None,
        "decision_reason": reason,
        "special_rule_tag": None,
        "audit_flags": {},
        "audit_error": True,
        "audit_error_message": reason,
    }


def _legal_check(fen: str, move_uci: str) -> tuple[bool, chess.Move | None]:
    if not move_uci:
        return False, None
    try:
        board = chess.Board(fen)
        mv = board.parse_uci(move_uci)
        return mv in board.legal_moves, mv
    except Exception:
        return False, None


def decide_and_audit_exp4(
    fen: str,
    side: str,
    *,
    model_path: Path,
    model_hash: str,
    search_profile: str = "balanced",
    fusion_mode: str = "balanced_fusion",
    decision_mode: str = "alpha_beta",
    enable_audit: bool = True,
) -> dict:
    """Run exp4 full chess_pv path, optionally capture audit via explain (fail-soft)."""
    board_state = {"__fen__": fen}

    try:
        move_dict = choose_experiment_pv_move(
            board_state,
            side,
            model_path=model_path,
            search_profile=search_profile,
            fusion_mode=fusion_mode,
            decision_mode=decision_mode,
        )
    except Exception as exc:
        return _empty_decision(
            "exp4", model_path, model_hash, fen, side, f"engine_error:{exc!r}"
        )

    move_uci = _move_dict_to_uci(move_dict)
    if not move_uci:
        return _empty_decision(
            "exp4", model_path, model_hash, fen, side, "engine_no_move"
        )

    legal, _ = _legal_check(fen, move_uci)

    decision: dict[str, Any] = {
        "engine_id": "exp4",
        "model_path": str(model_path),
        "model_hash": model_hash,
        "fen_before": fen,
        "side": side,
        "move": move_uci,
        "legal": legal,
        "raw_policy_top1": None,
        "raw_policy_top3": [],
        "search_best_move": None,
        "search_score": None,
        "final_score": None,
        "decision_reason": "",
        "special_rule_tag": None,
        "audit_flags": {
            "policy_override_used": None,
            "policy_override_reason": None,
            "search_guard_rejected": None,
            "real_disagreement_cp": None,
            "rule_guard_flags": None,
            "opening_sanity_flags": None,
            "mcts_score_diagnostic_only": None,
            "mcts_artifact_false_alarm": None,
            "final_decision_reason": None,
            "fusion_mode": fusion_mode,
            "decision_mode": decision_mode,
            "search_profile": search_profile,
        },
        "audit_error": False,
        "audit_error_message": "",
    }

    if not enable_audit:
        return decision

    try:
        audit = explain_experiment_pv_decision(
            board_state,
            side,
            model_path=model_path,
            search_profile=search_profile,
            fusion_mode=fusion_mode,
            decision_mode=decision_mode,
        )
    except Exception as exc:
        decision["audit_error"] = True
        decision["audit_error_message"] = f"explain_failed:{exc!r}"
        decision["audit_flags"]["opening_sanity_flags"] = ["exp4_explain_error"]
        return decision

    top_moves = list(audit.get("top_final_moves") or [])
    if top_moves:
        decision["raw_policy_top1"] = str(top_moves[0].get("move") or "") or None
        decision["raw_policy_top3"] = [
            str(r.get("move") or "") for r in top_moves[:3] if r.get("move")
        ]

    chosen_breakdown = dict(audit.get("chosen_breakdown") or {})
    decision["search_score"] = chosen_breakdown.get("search_score")
    decision["final_score"] = chosen_breakdown.get(
        "final_combined_score"
    ) or chosen_breakdown.get("fused_score")
    decision["decision_reason"] = str(audit.get("chosen_reason") or "")
    decision["special_rule_tag"] = (chosen_breakdown.get("rule_type") or None) or None

    policy_override = dict(audit.get("policy_override") or {})
    if policy_override:
        decision["audit_flags"]["policy_override_used"] = bool(
            policy_override.get("used")
        )
        decision["audit_flags"]["policy_override_reason"] = (
            str(policy_override.get("reason") or "") or None
        )
        search_guard = dict(policy_override.get("search_guard") or {})
        if search_guard:
            decision["audit_flags"]["search_guard_rejected"] = bool(
                search_guard.get("rejected")
            )
            decision["audit_flags"]["real_disagreement_cp"] = search_guard.get(
                "disagreement_cp"
            )
            decision["search_best_move"] = (
                str(search_guard.get("search_best_move") or "") or None
            )

    rule_fusion = dict(audit.get("rule_aware_fusion") or {})
    if rule_fusion:
        decision["audit_flags"]["rule_guard_flags"] = {
            "used": bool(rule_fusion.get("used")),
            "move": str(rule_fusion.get("move") or "") or None,
            "candidate_count": len(rule_fusion.get("candidates") or []),
        }

    reason = str(audit.get("chosen_reason") or "")
    sanity_flags = []
    if reason in ("opening_sanity_fallback", "opening_principle_fallback"):
        sanity_flags.append(reason)
    decision["audit_flags"]["opening_sanity_flags"] = sanity_flags or None

    mcts_info = dict(audit.get("mcts") or {})
    if mcts_info:
        sims = int(mcts_info.get("simulations") or 0)
        decision["audit_flags"]["mcts_score_diagnostic_only"] = sims > 0
        decision["audit_flags"]["mcts_artifact_false_alarm"] = None

    decision["audit_flags"]["final_decision_reason"] = reason or None

    return decision


def decide_and_audit_exp5(
    fen: str,
    side: str,
    *,
    model_path: Path,
    model_hash: str,
    search_profile: str = "fixed_depth_strong",
    enable_audit: bool = True,
) -> dict:
    """Run exp5 NNUE decision, optionally capture audit via explain (fail-soft)."""
    board_state = {"__fen__": fen}

    try:
        move_dict = choose_experiment_nnue_move(
            board_state,
            side,
            model_path=model_path,
            search_profile=search_profile,
        )
    except Exception as exc:
        return _empty_decision(
            "exp5", model_path, model_hash, fen, side, f"engine_error:{exc!r}"
        )

    move_uci = _move_dict_to_uci(move_dict)
    if not move_uci:
        return _empty_decision(
            "exp5", model_path, model_hash, fen, side, "engine_no_move"
        )

    legal, mv = _legal_check(fen, move_uci)

    decision: dict[str, Any] = {
        "engine_id": "exp5",
        "model_path": str(model_path),
        "model_hash": model_hash,
        "fen_before": fen,
        "side": side,
        "move": move_uci,
        "legal": legal,
        "raw_policy_top1": None,
        "raw_policy_top3": [],
        "search_best_move": None,
        "search_score": None,
        "final_score": None,
        "decision_reason": "alpha_beta_with_nnue_like_sparse_eval",
        "special_rule_tag": None,
        "audit_flags": {
            "search_profile": search_profile,
            "forced_mate_early_exit": None,
            "is_capture": None,
            "is_promotion": None,
        },
        "audit_error": False,
        "audit_error_message": "",
    }

    if not enable_audit:
        return decision

    try:
        audit = explain_experiment_nnue_decision(
            board_state,
            side,
            model_path=model_path,
            search_profile=search_profile,
        )
    except Exception as exc:
        decision["audit_error"] = True
        decision["audit_error_message"] = f"explain_failed:{exc!r}"
        decision["audit_flags"]["explain_error"] = True
        return decision

    top_moves = list(audit.get("top_final_moves") or [])
    if top_moves:
        decision["raw_policy_top1"] = str(top_moves[0].get("move") or "") or None
        decision["raw_policy_top3"] = [
            str(r.get("move") or "") for r in top_moves[:3] if r.get("move")
        ]

    chosen_breakdown = dict(audit.get("chosen_breakdown") or {})
    decision["search_score"] = chosen_breakdown.get("score") or chosen_breakdown.get(
        "static_eval_score"
    )
    decision["final_score"] = chosen_breakdown.get("score")
    decision["decision_reason"] = (
        str(audit.get("chosen_reason") or "") or decision["decision_reason"]
    )

    if legal and mv is not None:
        try:
            board = chess.Board(fen)
            after = board.copy(stack=False)
            after.push(mv)
            decision["audit_flags"]["forced_mate_early_exit"] = bool(
                after.is_checkmate()
            )
            decision["audit_flags"]["is_capture"] = bool(board.is_capture(mv))
            decision["audit_flags"]["is_promotion"] = bool(mv.promotion)
        except Exception:
            pass

    return decision
