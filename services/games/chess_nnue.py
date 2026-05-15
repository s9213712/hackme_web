"""NNUE-like evaluator for the ``experiment 5:NNUE`` chess difficulty.

This is a lightweight, JSON-serializable NNUE-inspired route: sparse board
features feed an efficiently reusable evaluator, then the existing alpha-beta
search stack chooses the move. It is intentionally not a Stockfish-compatible
NNUE implementation; it gives us a clean exp5 surface for the NNUE + PVS line
without mixing that design into the exp3/exp4 learning gates.
"""

from __future__ import annotations

import json
import hashlib
import os
from datetime import datetime
from pathlib import Path

import chess

from services.games.chess import START_FEN, replay_board_from_history, to_chess_board
from services.games.chess_exp5_base_model import (
    EXP5_STATIC_BASE_MODEL_SHA256 as SOURCE_EXP5_STATIC_BASE_MODEL_SHA256,
    exp5_static_base_model_payload,
)
from services.games.chess_opening_book import book_candidates_for_chess_board
from services.games.chess_search import ZobristHasher, opening_sanity_filter, search_best_move
from services.games.chess_model_registry import bundled_seed_model_path, runtime_model_path
from services.games.chess_tactical_safety import choose_tactically_safe_move, tactical_safety_report


EXPERIMENT_NNUE_DIFFICULTY = "experiment 5:nnue"
LEGACY_CHESS_NNUE_MAIN_MODEL_NAME = "chess_experiment_5_nnue.json"
DEFAULT_CHESS_NNUE_EXPERIENCE_MODEL_NAME = "chess_experiment_5_nnue_experience.json"
DEFAULT_CHESS_NNUE_MODEL_NAME = DEFAULT_CHESS_NNUE_EXPERIENCE_MODEL_NAME
DEFAULT_CHESS_NNUE_REPLAY_NAME = "chess_experiment_5_nnue_experience_replay.jsonl"
EXP5_STATIC_BASE_MODEL_SHA256 = SOURCE_EXP5_STATIC_BASE_MODEL_SHA256
EXP5_MAIN_MODEL_ROLE = "static_base_eval_parameters"
EXP5_GENERATED_ARTIFACT_ROLE = "adapter_or_experience_table"
EXP5_SOURCE_BASE_MODULE = "services.games.chess_exp5_base_model"
EXP5_EXPERIENCE_DELTA_FORMAT = "exp5_source_base_delta_v1"
EXP5_PRODUCTION_SEARCH_PROFILE = "fixed_depth_fianchetto_tail_castle_guard_v28e_depth3_no_null_mate_net30_fast_king_mobility4"
_NNUE_VERSION = 1
_LEARNING_RATE = 18.0
_MAX_ABS_WEIGHT = 350.0
_V26_LONG_TAIL_FULLMOVE = 14
_V26_LONG_TAIL_MATERIAL_CP = 5200
_V26_SELECTIVE_DEPTH_MATERIAL_CP = 1800
_SEARCH_PROFILES = {
    "fast": {"depth": 1, "quiescence_depth": 1, "time_budget_ms": 140, "enable_pvs": False, "enable_rich_eval": False},
    "balanced": {
        "depth": 2,
        "quiescence_depth": 2,
        "time_budget_ms": 320,
        "enable_pvs": False,
        "enable_futility": False,
        "enable_rich_eval": False,
        "enable_static_opening_book": False,
        "enable_special_rule_fusion": False,
    },
    "strong": {
        "depth": 3,
        "quiescence_depth": 4,
        "time_budget_ms": 1100,
        "enable_pvs": True,
        "enable_lmr": True,
        "enable_null_move": True,
        "enable_futility": True,
        "enable_rich_eval": False,
        "enable_static_opening_book": False,
        "enable_special_rule_fusion": False,
    },
    "deep": {
        "depth": 4,
        "quiescence_depth": 4,
        "time_budget_ms": 30000,
        "enable_pvs": True,
        "enable_lmr": True,
        "enable_null_move": True,
        "enable_futility": True,
        "enable_rich_eval": True,
        "enable_static_opening_book": True,
        "enable_special_rule_fusion": True,
    },
    # exp5_05a deterministic profiles: no time budget so PVS results are
    # bit-for-bit reproducible across runs. Same depth/quiescence as the
    # equivalent timed profile.
    "fixed_depth_fast": {
        "depth": 1,
        "quiescence_depth": 1,
        "time_budget_ms": None,
        "enable_pvs": False,
        "enable_rich_eval": False,
    },
    "fixed_depth_balanced": {
        "depth": 2,
        "quiescence_depth": 2,
        "time_budget_ms": None,
        "enable_pvs": False,
        "enable_futility": False,
        "enable_rich_eval": False,
        "enable_pawn_structure": False,
        "enable_piece_activity": False,
        "enable_king_zone_pressure": False,
        "enable_static_opening_book": False,
        "enable_special_rule_fusion": False,
    },
    "fixed_depth_piece_activity": {
        "depth": 2,
        "quiescence_depth": 2,
        "time_budget_ms": None,
        "enable_pvs": False,
        "enable_futility": False,
        "enable_rich_eval": False,
        "enable_pawn_structure": False,
        "enable_piece_activity": True,
        "enable_king_zone_pressure": False,
        "enable_static_opening_book": False,
        "enable_special_rule_fusion": False,
    },
    "fixed_depth_piece_activity_midgame": {
        "depth": 2,
        "quiescence_depth": 2,
        "time_budget_ms": None,
        "enable_pvs": False,
        "enable_futility": False,
        "enable_rich_eval": False,
        "enable_pawn_structure": False,
        "enable_piece_activity": False,
        "enable_piece_activity_midgame": True,
        "enable_king_zone_pressure": False,
        "enable_static_opening_book": False,
        "enable_special_rule_fusion": False,
    },
    "fixed_depth_center_break": {
        "depth": 2,
        "quiescence_depth": 2,
        "time_budget_ms": None,
        "enable_pvs": False,
        "enable_futility": False,
        "enable_rich_eval": False,
        "enable_pawn_structure": False,
        "enable_piece_activity": False,
        "enable_piece_activity_midgame": True,
        "enable_center_break": True,
        "enable_fianchetto_development": False,
        "enable_king_zone_pressure": False,
        "enable_static_opening_book": False,
        "enable_special_rule_fusion": False,
    },
    "fixed_depth_fianchetto_development": {
        "depth": 2,
        "quiescence_depth": 2,
        "time_budget_ms": None,
        "enable_pvs": False,
        "enable_futility": False,
        "enable_rich_eval": False,
        "enable_pawn_structure": False,
        "enable_piece_activity": False,
        "enable_piece_activity_midgame": True,
        "enable_center_break": False,
        "enable_fianchetto_development": True,
        "enable_king_zone_pressure": False,
        "enable_static_opening_book": False,
        "enable_special_rule_fusion": False,
    },
    "fixed_depth_fianchetto_tail": {
        "depth": 2,
        "quiescence_depth": 2,
        "time_budget_ms": None,
        "enable_pvs": False,
        "enable_futility": False,
        "enable_rich_eval": False,
        "enable_pawn_structure": False,
        "enable_piece_activity": False,
        "enable_piece_activity_midgame": True,
        "enable_center_break": False,
        "enable_fianchetto_development": True,
        "enable_tail_mate_net": True,
        "enable_king_zone_pressure": False,
        "enable_static_opening_book": False,
        "enable_special_rule_fusion": False,
    },
    "fixed_depth_fianchetto_tail_tactical": {
        "depth": 2,
        "quiescence_depth": 2,
        "time_budget_ms": None,
        "enable_pvs": False,
        "enable_futility": False,
        "enable_rich_eval": False,
        "enable_pawn_structure": False,
        "enable_piece_activity": False,
        "enable_piece_activity_midgame": True,
        "enable_center_break": False,
        "enable_fianchetto_development": True,
        "enable_tail_mate_net": True,
        "tail_mate_min_margin_cp": -3000,
        "mate_two_min_margin_cp": -3000,
        "enable_king_zone_pressure": False,
        "enable_static_opening_book": False,
        "enable_special_rule_fusion": False,
    },
    "fixed_depth_fianchetto_tail_castle_guard": {
        "depth": 2,
        "quiescence_depth": 2,
        "time_budget_ms": None,
        "enable_pvs": False,
        "enable_futility": False,
        "enable_rich_eval": False,
        "enable_pawn_structure": False,
        "enable_piece_activity": False,
        "enable_piece_activity_midgame": True,
        "enable_center_break": False,
        "enable_fianchetto_development": True,
        "enable_tail_mate_net": True,
        "allow_queenside_castle_priority": False,
        "enable_king_zone_pressure": False,
        "enable_static_opening_book": False,
        "enable_special_rule_fusion": False,
    },
    "fixed_depth_fianchetto_tail_castle_guard_v26a_candidate_search": {
        "depth": 2,
        "quiescence_depth": 2,
        "time_budget_ms": None,
        "enable_pvs": False,
        "enable_futility": False,
        "enable_rich_eval": False,
        "enable_pawn_structure": False,
        "enable_piece_activity": False,
        "enable_piece_activity_midgame": True,
        "enable_center_break": False,
        "enable_fianchetto_development": True,
        "enable_tail_mate_net": True,
        "allow_queenside_castle_priority": False,
        "enable_king_zone_pressure": False,
        "enable_static_opening_book": False,
        "enable_special_rule_fusion": False,
        "enable_v26_candidate_search_ordering": True,
        "enable_v26_selective_depth": True,
        "v26_selective_depth": 3,
        "v26_selective_quiescence_depth": 3,
    },
    "fixed_depth_fianchetto_tail_castle_guard_v26_endgame_safety": {
        "depth": 2,
        "quiescence_depth": 2,
        "time_budget_ms": None,
        "enable_pvs": False,
        "enable_futility": False,
        "enable_rich_eval": False,
        "enable_pawn_structure": False,
        "enable_piece_activity": False,
        "enable_piece_activity_midgame": True,
        "enable_center_break": False,
        "enable_fianchetto_development": True,
        "enable_tail_mate_net": True,
        "allow_queenside_castle_priority": False,
        "enable_king_zone_pressure": False,
        "enable_static_opening_book": False,
        "enable_special_rule_fusion": False,
        "enable_v26_long_tail_eval": True,
        "enable_v26_long_tail_ordering": True,
        "enable_v26_selective_depth": True,
        "v26_selective_depth": 3,
        "v26_selective_quiescence_depth": 3,
    },
    "fixed_depth_fianchetto_tail_castle_guard_v26b_endgame_eval_light": {
        "depth": 2,
        "quiescence_depth": 2,
        "time_budget_ms": None,
        "enable_pvs": False,
        "enable_futility": False,
        "enable_rich_eval": False,
        "enable_pawn_structure": False,
        "enable_piece_activity": False,
        "enable_piece_activity_midgame": True,
        "enable_center_break": False,
        "enable_fianchetto_development": True,
        "enable_tail_mate_net": True,
        "allow_queenside_castle_priority": False,
        "enable_king_zone_pressure": False,
        "enable_static_opening_book": False,
        "enable_special_rule_fusion": False,
        "enable_v26_long_tail_eval": True,
        "enable_v26_long_tail_eval_strict": True,
        "v26_long_tail_scale_percent": 45,
    },
    "fixed_depth_fianchetto_tail_castle_guard_v26c_pruned_depth3": {
        "depth": 3,
        "quiescence_depth": 2,
        "time_budget_ms": None,
        "enable_pvs": True,
        "enable_lmr": True,
        "enable_null_move": True,
        "enable_futility": True,
        "enable_rich_eval": False,
        "enable_pawn_structure": False,
        "enable_piece_activity": False,
        "enable_piece_activity_midgame": True,
        "enable_center_break": False,
        "enable_fianchetto_development": True,
        "enable_tail_mate_net": True,
        "allow_queenside_castle_priority": False,
        "enable_king_zone_pressure": False,
        "enable_static_opening_book": False,
        "enable_special_rule_fusion": False,
    },
    "fixed_depth_fianchetto_tail_castle_guard_v26d_pruned_depth3_q3": {
        "depth": 3,
        "quiescence_depth": 3,
        "time_budget_ms": None,
        "enable_pvs": True,
        "enable_lmr": True,
        "enable_null_move": True,
        "enable_futility": True,
        "enable_rich_eval": False,
        "enable_pawn_structure": False,
        "enable_piece_activity": False,
        "enable_piece_activity_midgame": True,
        "enable_center_break": False,
        "enable_fianchetto_development": True,
        "enable_tail_mate_net": True,
        "allow_queenside_castle_priority": False,
        "enable_king_zone_pressure": False,
        "enable_static_opening_book": False,
        "enable_special_rule_fusion": False,
    },
    "fixed_depth_fianchetto_tail_castle_guard_v26e_pruned_depth3_no_null": {
        "depth": 3,
        "quiescence_depth": 2,
        "time_budget_ms": None,
        "enable_pvs": True,
        "enable_lmr": True,
        "enable_null_move": False,
        "enable_futility": True,
        "enable_rich_eval": False,
        "enable_pawn_structure": False,
        "enable_piece_activity": False,
        "enable_piece_activity_midgame": True,
        "enable_center_break": False,
        "enable_fianchetto_development": True,
        "enable_tail_mate_net": True,
        "allow_queenside_castle_priority": False,
        "enable_king_zone_pressure": False,
        "enable_static_opening_book": False,
        "enable_special_rule_fusion": False,
    },
    "fixed_depth_fianchetto_tail_castle_guard_v26f_depth3_no_null_no_futility": {
        "depth": 3,
        "quiescence_depth": 2,
        "time_budget_ms": None,
        "enable_pvs": True,
        "enable_lmr": True,
        "enable_null_move": False,
        "enable_futility": False,
        "enable_rich_eval": False,
        "enable_pawn_structure": False,
        "enable_piece_activity": False,
        "enable_piece_activity_midgame": True,
        "enable_center_break": False,
        "enable_fianchetto_development": True,
        "enable_tail_mate_net": True,
        "allow_queenside_castle_priority": False,
        "enable_king_zone_pressure": False,
        "enable_static_opening_book": False,
        "enable_special_rule_fusion": False,
    },
    "fixed_depth_fianchetto_tail_castle_guard_v26g_depth3_no_null_no_lmr": {
        "depth": 3,
        "quiescence_depth": 2,
        "time_budget_ms": None,
        "enable_pvs": True,
        "enable_lmr": False,
        "enable_null_move": False,
        "enable_futility": True,
        "enable_rich_eval": False,
        "enable_pawn_structure": False,
        "enable_piece_activity": False,
        "enable_piece_activity_midgame": True,
        "enable_center_break": False,
        "enable_fianchetto_development": True,
        "enable_tail_mate_net": True,
        "allow_queenside_castle_priority": False,
        "enable_king_zone_pressure": False,
        "enable_static_opening_book": False,
        "enable_special_rule_fusion": False,
    },
    "fixed_depth_fianchetto_tail_castle_guard_v27a_depth3_no_null_root_ordering": {
        "depth": 3,
        "quiescence_depth": 2,
        "time_budget_ms": None,
        "enable_pvs": True,
        "enable_lmr": True,
        "enable_null_move": False,
        "enable_futility": True,
        "enable_rich_eval": False,
        "enable_pawn_structure": False,
        "enable_piece_activity": False,
        "enable_piece_activity_midgame": True,
        "enable_center_break": False,
        "enable_fianchetto_development": True,
        "enable_tail_mate_net": True,
        "allow_queenside_castle_priority": False,
        "enable_king_zone_pressure": False,
        "enable_static_opening_book": False,
        "enable_special_rule_fusion": False,
        "enable_v27_root_long_tail_ordering": True,
    },
    "fixed_depth_fianchetto_tail_castle_guard_v27b_depth3_no_null_root_ordering_eval": {
        "depth": 3,
        "quiescence_depth": 2,
        "time_budget_ms": None,
        "enable_pvs": True,
        "enable_lmr": True,
        "enable_null_move": False,
        "enable_futility": True,
        "enable_rich_eval": False,
        "enable_pawn_structure": False,
        "enable_piece_activity": False,
        "enable_piece_activity_midgame": True,
        "enable_center_break": False,
        "enable_fianchetto_development": True,
        "enable_tail_mate_net": True,
        "allow_queenside_castle_priority": False,
        "enable_king_zone_pressure": False,
        "enable_static_opening_book": False,
        "enable_special_rule_fusion": False,
        "enable_v27_root_long_tail_ordering": True,
        "enable_v26_long_tail_eval": True,
        "enable_v26_long_tail_eval_strict": True,
        "v26_long_tail_scale_percent": 35,
    },
    "fixed_depth_fianchetto_tail_castle_guard_v27c_depth3_no_null_root_ordering_less_futility": {
        "depth": 3,
        "quiescence_depth": 2,
        "time_budget_ms": None,
        "enable_pvs": True,
        "enable_lmr": True,
        "enable_null_move": False,
        "enable_futility": True,
        "futility_margin_cp": 260,
        "enable_rich_eval": False,
        "enable_pawn_structure": False,
        "enable_piece_activity": False,
        "enable_piece_activity_midgame": True,
        "enable_center_break": False,
        "enable_fianchetto_development": True,
        "enable_tail_mate_net": True,
        "allow_queenside_castle_priority": False,
        "enable_king_zone_pressure": False,
        "enable_static_opening_book": False,
        "enable_special_rule_fusion": False,
        "enable_v27_root_long_tail_ordering": True,
    },
    "fixed_depth_fianchetto_tail_castle_guard_v27d_depth3_no_null_root_ordering_lmr6": {
        "depth": 3,
        "quiescence_depth": 2,
        "time_budget_ms": None,
        "enable_pvs": True,
        "enable_lmr": True,
        "lmr_min_move_index": 6,
        "enable_null_move": False,
        "enable_futility": True,
        "enable_rich_eval": False,
        "enable_pawn_structure": False,
        "enable_piece_activity": False,
        "enable_piece_activity_midgame": True,
        "enable_center_break": False,
        "enable_fianchetto_development": True,
        "enable_tail_mate_net": True,
        "allow_queenside_castle_priority": False,
        "enable_king_zone_pressure": False,
        "enable_static_opening_book": False,
        "enable_special_rule_fusion": False,
        "enable_v27_root_long_tail_ordering": True,
    },
    "fixed_depth_fianchetto_tail_castle_guard_v27e_depth3_no_null_less_futility": {
        "depth": 3,
        "quiescence_depth": 2,
        "time_budget_ms": None,
        "enable_pvs": True,
        "enable_lmr": True,
        "enable_null_move": False,
        "enable_futility": True,
        "futility_margin_cp": 260,
        "enable_rich_eval": False,
        "enable_pawn_structure": False,
        "enable_piece_activity": False,
        "enable_piece_activity_midgame": True,
        "enable_center_break": False,
        "enable_fianchetto_development": True,
        "enable_tail_mate_net": True,
        "allow_queenside_castle_priority": False,
        "enable_king_zone_pressure": False,
        "enable_static_opening_book": False,
        "enable_special_rule_fusion": False,
    },
    "fixed_depth_fianchetto_tail_castle_guard_v27f_depth3_no_null_lmr6": {
        "depth": 3,
        "quiescence_depth": 2,
        "time_budget_ms": None,
        "enable_pvs": True,
        "enable_lmr": True,
        "lmr_min_move_index": 6,
        "enable_null_move": False,
        "enable_futility": True,
        "enable_rich_eval": False,
        "enable_pawn_structure": False,
        "enable_piece_activity": False,
        "enable_piece_activity_midgame": True,
        "enable_center_break": False,
        "enable_fianchetto_development": True,
        "enable_tail_mate_net": True,
        "allow_queenside_castle_priority": False,
        "enable_king_zone_pressure": False,
        "enable_static_opening_book": False,
        "enable_special_rule_fusion": False,
    },
    "fixed_depth_fianchetto_tail_castle_guard_v27g_depth3_no_null_lmr6_less_futility": {
        "depth": 3,
        "quiescence_depth": 2,
        "time_budget_ms": None,
        "enable_pvs": True,
        "enable_lmr": True,
        "lmr_min_move_index": 6,
        "enable_null_move": False,
        "enable_futility": True,
        "futility_margin_cp": 260,
        "enable_rich_eval": False,
        "enable_pawn_structure": False,
        "enable_piece_activity": False,
        "enable_piece_activity_midgame": True,
        "enable_center_break": False,
        "enable_fianchetto_development": True,
        "enable_tail_mate_net": True,
        "allow_queenside_castle_priority": False,
        "enable_king_zone_pressure": False,
        "enable_static_opening_book": False,
        "enable_special_rule_fusion": False,
    },
    "fixed_depth_fianchetto_tail_castle_guard_v27h_depth3_no_null_mate_net30": {
        "depth": 3,
        "quiescence_depth": 2,
        "time_budget_ms": None,
        "enable_pvs": True,
        "enable_lmr": True,
        "enable_null_move": False,
        "enable_futility": True,
        "enable_rich_eval": False,
        "enable_pawn_structure": False,
        "enable_piece_activity": False,
        "enable_piece_activity_midgame": True,
        "enable_center_break": False,
        "enable_fianchetto_development": True,
        "enable_tail_mate_net": True,
        "tail_mate_min_margin_cp": -3000,
        "tail_mate_max_pieces": 30,
        "tail_mate_max_nodes": 12_000,
        "tail_mate_max_root_checks": 6,
        "mate_two_min_margin_cp": -3000,
        "mate_two_max_pieces": 30,
        "allow_queenside_castle_priority": False,
        "enable_king_zone_pressure": False,
        "enable_static_opening_book": False,
        "enable_special_rule_fusion": False,
    },
    "fixed_depth_fianchetto_tail_castle_guard_v27i_depth3_no_null_mate_net30_defense": {
        "depth": 3,
        "quiescence_depth": 2,
        "time_budget_ms": None,
        "enable_pvs": True,
        "enable_lmr": True,
        "enable_null_move": False,
        "enable_futility": True,
        "enable_rich_eval": False,
        "enable_pawn_structure": False,
        "enable_piece_activity": False,
        "enable_piece_activity_midgame": True,
        "enable_center_break": False,
        "enable_fianchetto_development": True,
        "enable_tail_mate_net": True,
        "tail_mate_min_margin_cp": -3000,
        "tail_mate_max_pieces": 30,
        "tail_mate_max_nodes": 12_000,
        "tail_mate_max_root_checks": 6,
        "mate_two_min_margin_cp": -3000,
        "mate_two_max_pieces": 30,
        "enable_v27_forced_mate_defense": True,
        "v27_forced_mate_defense_max_pieces": 30,
        "v27_forced_mate_defense_max_depth": 7,
        "v27_forced_mate_defense_max_nodes": 12_000,
        "allow_queenside_castle_priority": False,
        "enable_king_zone_pressure": False,
        "enable_static_opening_book": False,
        "enable_special_rule_fusion": False,
    },
    "fixed_depth_fianchetto_tail_castle_guard_v27k_depth3_no_null_mate_net30_defense_book": {
        "depth": 3,
        "quiescence_depth": 2,
        "time_budget_ms": None,
        "enable_pvs": True,
        "enable_lmr": True,
        "enable_null_move": False,
        "enable_futility": True,
        "enable_rich_eval": False,
        "enable_pawn_structure": False,
        "enable_piece_activity": False,
        "enable_piece_activity_midgame": True,
        "enable_center_break": False,
        "enable_fianchetto_development": True,
        "enable_tail_mate_net": True,
        "tail_mate_min_margin_cp": -3000,
        "tail_mate_max_pieces": 30,
        "tail_mate_max_nodes": 12_000,
        "tail_mate_max_root_checks": 6,
        "mate_two_min_margin_cp": -3000,
        "mate_two_max_pieces": 30,
        "enable_v27_forced_mate_defense": True,
        "v27_forced_mate_defense_max_pieces": 30,
        "v27_forced_mate_defense_max_depth": 7,
        "v27_forced_mate_defense_max_nodes": 12_000,
        "allow_queenside_castle_priority": False,
        "enable_king_zone_pressure": False,
        "enable_static_opening_book": True,
        "enable_special_rule_fusion": False,
    },
    "fixed_depth_fianchetto_tail_castle_guard_v28e_depth3_no_null_mate_net30_fast_king_mobility4": {
        "depth": 3,
        "quiescence_depth": 2,
        "time_budget_ms": None,
        "enable_pvs": True,
        "enable_lmr": True,
        "enable_null_move": False,
        "enable_futility": True,
        "enable_rich_eval": False,
        "enable_pawn_structure": False,
        "enable_piece_activity": False,
        "enable_piece_activity_midgame": True,
        "enable_center_break": False,
        "enable_fianchetto_development": True,
        "enable_tail_mate_net": True,
        "tail_mate_min_margin_cp": -3000,
        "tail_mate_max_pieces": 30,
        "tail_mate_max_nodes": 12_000,
        "tail_mate_max_root_checks": 6,
        "mate_two_min_margin_cp": -3000,
        "mate_two_max_pieces": 30,
        "enable_v27_forced_mate_defense": True,
        "v27_forced_mate_defense_max_pieces": 30,
        "v27_forced_mate_defense_max_depth": 7,
        "v27_forced_mate_defense_max_nodes": 12_000,
        "allow_queenside_castle_priority": False,
        "enable_king_zone_pressure": False,
        "enable_static_opening_book": True,
        "enable_special_rule_fusion": False,
        "enable_final_low_legal_check_escape": True,
        "final_low_legal_check_escape_max_legal": 4,
        "final_low_legal_check_escape_max_pieces": 30,
        "final_low_legal_check_escape_max_depth": 0,
        "final_low_legal_check_escape_max_nodes": 0,
        "final_low_legal_check_escape_enable_king_mobility4": True,
    },
    "fixed_depth_center_fianchetto": {
        "depth": 2,
        "quiescence_depth": 2,
        "time_budget_ms": None,
        "enable_pvs": False,
        "enable_futility": False,
        "enable_rich_eval": False,
        "enable_pawn_structure": False,
        "enable_piece_activity": False,
        "enable_piece_activity_midgame": True,
        "enable_center_break": True,
        "enable_fianchetto_development": True,
        "enable_king_zone_pressure": False,
        "enable_static_opening_book": False,
        "enable_special_rule_fusion": False,
    },
    "fixed_depth_static_book": {
        "depth": 2,
        "quiescence_depth": 2,
        "time_budget_ms": None,
        "enable_pvs": False,
        "enable_futility": False,
        "enable_rich_eval": False,
        "enable_pawn_structure": False,
        "enable_piece_activity": False,
        "enable_piece_activity_midgame": False,
        "enable_king_zone_pressure": False,
        "enable_static_opening_book": True,
        "enable_special_rule_fusion": False,
    },
    "fixed_depth_midgame_book": {
        "depth": 2,
        "quiescence_depth": 2,
        "time_budget_ms": None,
        "enable_pvs": False,
        "enable_futility": False,
        "enable_rich_eval": False,
        "enable_pawn_structure": False,
        "enable_piece_activity": False,
        "enable_piece_activity_midgame": True,
        "enable_king_zone_pressure": False,
        "enable_static_opening_book": True,
        "enable_special_rule_fusion": False,
    },
    "fixed_depth_pawn_structure": {
        "depth": 2,
        "quiescence_depth": 2,
        "time_budget_ms": None,
        "enable_pvs": False,
        "enable_futility": False,
        "enable_rich_eval": False,
        "enable_pawn_structure": True,
        "enable_piece_activity": False,
        "enable_king_zone_pressure": False,
        "enable_static_opening_book": False,
        "enable_special_rule_fusion": False,
    },
    "fixed_depth_king_pressure": {
        "depth": 2,
        "quiescence_depth": 2,
        "time_budget_ms": None,
        "enable_pvs": False,
        "enable_futility": False,
        "enable_rich_eval": False,
        "enable_pawn_structure": False,
        "enable_piece_activity": False,
        "enable_king_zone_pressure": True,
        "enable_static_opening_book": False,
        "enable_special_rule_fusion": False,
    },
    "fixed_depth_strong": {
        "depth": 3,
        "quiescence_depth": 4,
        "time_budget_ms": None,
        "enable_pvs": True,
        "enable_lmr": True,
        "enable_null_move": True,
        "enable_futility": True,
        "enable_rich_eval": False,
        "enable_static_opening_book": False,
        "enable_special_rule_fusion": False,
    },
    "fixed_depth_deep": {
        "depth": 4,
        "quiescence_depth": 4,
        "time_budget_ms": None,
        "enable_pvs": True,
        "enable_lmr": True,
        "enable_null_move": True,
        "enable_futility": True,
        "enable_rich_eval": True,
        "enable_static_opening_book": True,
        "enable_special_rule_fusion": True,
    },
}
_PIECE_VALUES = {
    chess.PAWN: 100,
    chess.KNIGHT: 320,
    chess.BISHOP: 335,
    chess.ROOK: 500,
    chess.QUEEN: 900,
    chess.KING: 20000,
}
_CENTER = {chess.D4, chess.E4, chess.D5, chess.E5}
_EXTENDED_CENTER = {chess.C3, chess.D3, chess.E3, chess.F3, chess.C4, chess.F4, chess.C5, chess.F5, chess.C6, chess.D6, chess.E6, chess.F6}
_CENTER_BREAK_PAWN_SQUARES = {chess.D4, chess.E4, chess.D5, chess.E5, chess.C4, chess.F4, chess.C5, chess.F5}
_FIANCHETTO_PLANS = (
    (chess.WHITE, chess.G3, chess.F1, chess.G2, {chess.D5, chess.E4, chess.F3, chess.C6}),
    (chess.WHITE, chess.B3, chess.C1, chess.B2, {chess.D4, chess.E5, chess.C3, chess.F6}),
    (chess.BLACK, chess.G6, chess.F8, chess.G7, {chess.D4, chess.E5, chess.F6, chess.C3}),
    (chess.BLACK, chess.B6, chess.C8, chess.B7, {chess.D5, chess.E4, chess.C6, chess.F3}),
)
_FLANK_FILES = {0, 7}
_NEAR_FLANK_FILES = {1, 6}
_OPENING_DEVELOPMENT_FULLMOVE_LIMIT = 10
_STATIC_OPENING_BOOK_FULLMOVE_LIMIT = 10
_OPENING_KING_WALK_FULLMOVE_LIMIT = 12
_TRAP_PRIOR_FULLMOVE_LIMIT = 12
_MOVE_HISTORY_KEY = "__move_history__"
_MATE_IN_TWO_MAX_PIECES = 12
_MATE_IN_TWO_MAX_LEGAL_MOVES = 45
_MATE_IN_TWO_MAX_REPLIES = 45
_CONVERSION_MARGIN_CP = 500
_CONVERSION_FULLMOVE = 20
_CONVERSION_TOTAL_MATERIAL_CP = 3600
_KING_ACTIVITY_WEIGHT = 42
_PASSED_PAWN_ADVANCE_WEIGHT = 26
_SEE_MAX_DEPTH = 8
_REPETITION_PROGRESS_MARGIN_CP = 300
_REPETITION_PROGRESS_SAFE_DROP_CP = 180
_REPETITION_PROGRESS_SCORE_DROP_CP = 1800.0
_ENDGAME_PROGRESS_SCORE_DROP_CP = 2200.0
_ENDGAME_PROGRESS_SAFE_DROP_CP = 240
_SHUFFLE_LOOKBACK_OWN_MOVES = 8
_ADAPTER_MODEL_PATH_ENV = "HTML_LEARNING_CHESS_ENGINE_NNUE_ADAPTER_MODEL_PATH"
_ADAPTER_ROWS_PATH_ENV = "HTML_LEARNING_CHESS_ENGINE_NNUE_ADAPTER_ROWS_PATH"
_ADAPTER_MODE_ENV = "HTML_LEARNING_CHESS_ENGINE_NNUE_ADAPTER_MODE"
_ADAPTER_ALLOW_EXACT_ENV = "HTML_LEARNING_CHESS_ENGINE_NNUE_ADAPTER_ALLOW_EXACT"
_ADAPTER_ALLOW_GENERAL_ENV = "HTML_LEARNING_CHESS_ENGINE_NNUE_ADAPTER_ALLOW_GENERAL"
_ADAPTER_REENTRY_ENV = "_HTML_LEARNING_CHESS_ENGINE_NNUE_ADAPTER_REENTRY"
_ADAPTER_MAX_MAIN_RANK_EXACT = 8
_ADAPTER_MAX_MAIN_SCORE_DROP_EXACT_CP = 220.0
_ADAPTER_MAX_MAIN_RANK_GENERAL = 2
_ADAPTER_MAX_MAIN_SCORE_DROP_GENERAL_CP = 80.0
_ADAPTER_MAX_MATERIAL_FLOOR_DROP_CP = 180
_ADAPTER_MEMORY_CACHE: dict[str, dict] = {}
_SPECIAL_RULE_FUSION_RANK_LIMIT = 3
_SPECIAL_RULE_FUSION_SCORE_DROP_CP = 180.0
_PAIRWISE_MARGIN_DEFAULT_CP = 180.0
_SOFT_TEACHER_TOP3_WEIGHT_DEFAULT = 0.45
_SOFT_TEACHER_TOP5_WEIGHT_DEFAULT = 0.22

# exp3-example2 lesson item 10: broader "post-castle haven" set, not just g1/c1.
# Example2 showed that exp3 never castled across 5/5 games and walked the king
# out by ply 8-21 in every one. Reward any king that has reached a corner-side
# squares typical of a castled-then-shuffled king; penalise a king that's
# still on the starting square after the opening.
_WHITE_KING_SAFE_SQUARES = {chess.G1, chess.H1, chess.G2, chess.H2, chess.F1, chess.F2,
                            chess.C1, chess.B1, chess.A1, chess.B2, chess.C2, chess.A2}
_BLACK_KING_SAFE_SQUARES = {chess.G8, chess.H8, chess.G7, chess.H7, chess.F8, chess.F7,
                            chess.C8, chess.B8, chess.A8, chess.B7, chess.C7, chess.A7}
# How late into the game an "uncastled, still on e1/e8" king starts being
# penalised. fullmove_number reaches 13 by ply 25 — clearly past opening.
_EARLY_KING_PENALTY_AFTER_FULLMOVE = 12
_REPLAY_PRIOR_MAX_FULLMOVE = 12
_REPLAY_PRIOR_LINES = (
    ("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", "white", "d2d4"),
    ("rnbqkbnr/pppppppp/8/8/3P4/8/PPP1PPPP/RNBQKBNR b KQkq - 0 1", "black", "g8f6"),
    ("rnbqkb1r/pppppppp/5n2/8/3P4/8/PPP1PPPP/RNBQKBNR w KQkq - 1 2", "white", "c2c4"),
    ("rnbqkb1r/pppppppp/5n2/8/2PP4/8/PP2PPPP/RNBQKBNR b KQkq - 0 2", "black", "c7c5"),
    ("rnbqkb1r/pp1ppppp/5n2/2p5/2PP4/8/PP2PPPP/RNBQKBNR w KQkq - 0 3", "white", "d4d5"),
    ("rnbqkb1r/pp1ppppp/5n2/2pP4/2P5/8/PP2PPPP/RNBQKBNR b KQkq - 0 3", "black", "e7e6"),
    ("rnbqkb1r/pp1p1ppp/4pn2/2pP4/2P5/8/PP2PPPP/RNBQKBNR w KQkq - 0 4", "white", "b1c3"),
    ("rnbqkb1r/pp1p1ppp/4pn2/2pP4/2P5/2N5/PP2PPPP/R1BQKBNR b KQkq - 1 4", "black", "e6d5"),
    ("rnbqkb1r/pp1p1ppp/5n2/2pp4/2P5/2N5/PP2PPPP/R1BQKBNR w KQkq - 0 5", "white", "c4d5"),
    ("rnbqkb1r/pp1p1ppp/5n2/2pP4/8/2N5/PP2PPPP/R1BQKBNR b KQkq - 0 5", "black", "d7d6"),
    ("rnbqkb1r/pp3ppp/3p1n2/2pP4/8/2N5/PP2PPPP/R1BQKBNR w KQkq - 0 6", "white", "e2e4"),
    ("rnbqkb1r/pp3ppp/3p1n2/2pP4/4P3/2N5/PP3PPP/R1BQKBNR b KQkq - 0 6", "black", "g7g6"),
    ("rnbqkb1r/pp3p1p/3p1np1/2pP4/4P3/2N5/PP3PPP/R1BQKBNR w KQkq - 0 7", "white", "f2f4"),
    ("rnbqkb1r/pp3p1p/3p1np1/2pP4/4PP2/2N5/PP4PP/R1BQKBNR b KQkq - 0 7", "black", "f8g7"),
    ("rnbqk2r/pp3pbp/3p1np1/2pP4/4PP2/2N5/PP4PP/R1BQKBNR w KQkq - 1 8", "white", "f1b5"),
    ("rnbqk2r/pp3pbp/3p1np1/1BpP4/4PP2/2N5/PP4PP/R1BQK1NR b KQkq - 2 8", "black", "f6d7"),
    ("rnbqk2r/pp1n1pbp/3p2p1/1BpP4/4PP2/2N5/PP4PP/R1BQK1NR w KQkq - 3 9", "white", "g1f3"),
    ("rnbqk2r/pp1n1pbp/3p2p1/1BpP4/4PP2/2N2N2/PP4PP/R1BQK2R b KQkq - 4 9", "black", "a7a6"),
    ("rnbqk2r/1p1n1pbp/p2p2p1/1BpP4/4PP2/2N2N2/PP4PP/R1BQK2R w KQkq - 0 10", "white", "b5d3"),
    ("rnbqk2r/1p1n1pbp/p2p2p1/2pP4/4PP2/2NB1N2/PP4PP/R1BQK2R b KQkq - 1 10", "black", "b7b5"),
    ("rnbqk2r/3n1pbp/p2p2p1/1ppP4/4PP2/2NB1N2/PP4PP/R1BQK2R w KQkq - 0 11", "white", "e1g1"),
    ("rnbqk2r/3n1pbp/p2p2p1/1ppP4/4PP2/2NB1N2/PP4PP/R1BQ1RK1 b kq - 1 11", "black", "e8g8"),
    ("rnbq1rk1/3n1pbp/p2p2p1/1ppP4/4PP2/2NB1N2/PP4PP/R1BQ1RK1 w - - 2 12", "white", "a2a3"),
    ("rnbq1rk1/3n1pbp/p2p2p1/1ppP4/4PP2/P1NB1N2/1P4PP/R1BQ1RK1 b - - 0 12", "black", "b5b4"),
)
_REPLAY_PRIOR_BY_POSITION = {
    (fen, side): move
    for fen, side, move in _REPLAY_PRIOR_LINES
}
_OPENING_TRAP_PRIOR_LINES = (
    # v17: code-level trap priors for common opening probes. These are not
    # generated model weights; they are deterministic engine knowledge used
    # before shallow search can be lured into the wrong branch.
    ("rnbqkbnr/pppp1ppp/8/4p3/2B1P3/8/PPPP1PPP/RNBQK1NR b KQkq -", "black", "f8d6"),
    ("rnbqkbnr/ppp2ppp/4p3/3P4/3P4/8/PPP2PPP/RNBQKBNR b KQkq -", "black", "f8b4"),
    ("rnbqk1nr/ppp2ppp/4p3/3P4/1b1P4/2P5/PP3PPP/RNBQKBNR b KQkq -", "black", "e6d5"),
    ("rnbk1bnr/ppp1pppp/8/1B6/8/8/PPPP1PqP/RNBQK1NR w KQ -", "white", "b1c3"),
    ("r1bqkb1r/ppppppp1/2n2n1p/8/2P5/2N2N2/PP1PPPPP/R1BQKB1R w KQkq -", "white", "e2e4"),
    ("r1bq1k1r/pppp2p1/2n3Bp/2b5/2Pp1p2/5N2/PP3PPP/R1BQ1RK1 w - -", "white", "a1b1"),
    ("r1bqkbnr/pppp1ppp/2n5/4p2Q/4P3/8/PPPP1PPP/RNB1KBNR w KQkq -", "white", "f1d3"),
)
_OPENING_TRAP_PRIOR_BY_POSITION = {
    (fen_key, side): move
    for fen_key, side, move in _OPENING_TRAP_PRIOR_LINES
}


def default_chess_nnue_model_path() -> Path:
    return runtime_model_path(DEFAULT_CHESS_NNUE_MODEL_NAME, env_var="HTML_LEARNING_CHESS_ENGINE_NNUE_MODEL_PATH")


def default_chess_nnue_replay_path() -> Path:
    return runtime_model_path(DEFAULT_CHESS_NNUE_REPLAY_NAME, env_var="HTML_LEARNING_CHESS_ENGINE_NNUE_REPLAY_PATH")


def bundled_chess_nnue_model_path() -> Path:
    return bundled_seed_model_path(LEGACY_CHESS_NNUE_MAIN_MODEL_NAME)


def exp5_model_artifact_policy() -> dict:
    return {
        "engine": EXPERIMENT_NNUE_DIFFICULTY,
        "main_model_role": EXP5_MAIN_MODEL_ROLE,
        "generated_artifact_role": EXP5_GENERATED_ARTIFACT_ROLE,
        "source_base_module": EXP5_SOURCE_BASE_MODULE,
        "static_base_model_sha256": EXP5_STATIC_BASE_MODEL_SHA256,
        "runtime_experience_model_name": DEFAULT_CHESS_NNUE_EXPERIENCE_MODEL_NAME,
        "experience_delta_format": EXP5_EXPERIENCE_DELTA_FORMAT,
        "main_model_generation_default": "disabled",
        "bundled_main_json_required": False,
        "score_versions_may_change_without_model_checksum_change": True,
    }


def _now() -> str:
    return datetime.now().isoformat()


def experiment_nnue_model_template() -> dict:
    return normalize_experiment_nnue_model_payload(exp5_static_base_model_payload()) or {
        "version": _NNUE_VERSION,
        "architecture": "nnue-like-sparse-accumulator-v1",
        "feature_weights": {},
        "piece_square_weights": {},
        "opening_overlay": {},
        "tempo": 12,
        "mobility_weight": 3,
        "king_safety_weight": 18,
        "training_objective": "position_move_evaluator_delta",
        "sample_count": 0,
        "updated_at": _now(),
    }


def _clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


def normalize_experiment_nnue_model_payload(model: dict) -> dict | None:
    if not isinstance(model, dict):
        return None
    if int(model.get("version") or 0) != _NNUE_VERSION:
        return None
    feature_weights = model.get("feature_weights") if isinstance(model.get("feature_weights"), dict) else {}
    piece_square_weights = model.get("piece_square_weights") if isinstance(model.get("piece_square_weights"), dict) else {}
    try:
        tempo = int(model.get("tempo", 12))
        mobility_weight = int(model.get("mobility_weight", 3))
        king_safety_weight = int(model.get("king_safety_weight", 18))
    except Exception:
        return None
    return {
        "version": _NNUE_VERSION,
        "architecture": "nnue-like-sparse-accumulator-v1",
        "feature_weights": {str(key): float(value) for key, value in feature_weights.items()},
        "piece_square_weights": {str(key): float(value) for key, value in piece_square_weights.items()},
        "opening_overlay": _normalize_opening_overlay(model.get("opening_overlay")),
        "tempo": tempo,
        "mobility_weight": mobility_weight,
        "king_safety_weight": king_safety_weight,
        "training_objective": str(model.get("training_objective") or "position_move_evaluator_delta"),
        "sample_count": max(0, int(model.get("sample_count") or 0)),
        "updated_at": str(model.get("updated_at") or _now()),
    }


def _normalize_opening_overlay(raw) -> dict:
    if not isinstance(raw, dict):
        return {}
    positions_raw = raw.get("positions")
    if not isinstance(positions_raw, dict):
        return {}
    positions: dict[str, dict] = {}
    for key, payload in positions_raw.items():
        key_text = str(key or "").strip()
        if not key_text or not isinstance(payload, dict):
            continue
        moves_raw = payload.get("moves") or payload.get("expected_uci_any") or []
        moves: list[dict] = []
        for index, item in enumerate(moves_raw):
            if isinstance(item, dict):
                uci = str(item.get("uci") or item.get("move") or "").strip().lower()
                weight = float(item.get("weight") or max(1, 100 - index))
            else:
                uci = str(item or "").strip().lower()
                weight = float(max(1, 100 - index))
            if len(uci) < 4:
                continue
            moves.append({"uci": uci, "weight": round(_clip(weight, 0.0, 10000.0), 6)})
        if not moves:
            continue
        positions[key_text] = {
            "id": str(payload.get("id") or key_text),
            "fen": str(payload.get("fen") or ""),
            "side": str(payload.get("side") or "").strip().lower(),
            "source": str(payload.get("source") or "opening_overlay"),
            "label_quality": str(payload.get("label_quality") or ""),
            "moves": moves,
        }
    if not positions:
        return {}
    try:
        max_fullmove = max(1, int(raw.get("max_fullmove") or 12))
    except Exception:
        max_fullmove = 12
    return {
        "enabled": bool(raw.get("enabled", True)),
        "version": str(raw.get("version") or "exp5_opening_overlay_v1"),
        "mode": str(raw.get("mode") or "exact_position_book_prior"),
        "max_fullmove": max_fullmove,
        "positions": positions,
    }


def _is_experience_delta_payload(model: dict) -> bool:
    if not isinstance(model, dict):
        return False
    return (
        str(model.get("delta_format") or "") == EXP5_EXPERIENCE_DELTA_FORMAT
        or str(model.get("artifact_role") or "") == EXP5_GENERATED_ARTIFACT_ROLE
        or str(model.get("base_model_sha256") or "") == EXP5_STATIC_BASE_MODEL_SHA256
    )


def _apply_numeric_deltas(base_mapping: dict, delta_mapping: dict) -> dict:
    merged = dict(base_mapping or {})
    for key, delta in (delta_mapping or {}).items():
        try:
            value = float(delta)
        except Exception:
            continue
        merged[str(key)] = round(float(merged.get(str(key)) or 0.0) + value, 6)
    return merged


def _compose_experience_delta_payload(payload: dict) -> dict | None:
    if not _is_experience_delta_payload(payload):
        return None
    base = experiment_nnue_model_template()
    scalar_deltas = payload.get("scalar_deltas") if isinstance(payload.get("scalar_deltas"), dict) else {}
    base["feature_weights"] = _apply_numeric_deltas(base.get("feature_weights") or {}, payload.get("feature_weights") or {})
    base["piece_square_weights"] = _apply_numeric_deltas(
        base.get("piece_square_weights") or {},
        payload.get("piece_square_weights") or {},
    )
    for key in ("tempo", "mobility_weight", "king_safety_weight"):
        if key in scalar_deltas:
            try:
                base[key] = int(round(float(base.get(key) or 0) + float(scalar_deltas[key])))
            except Exception:
                pass
    overlay = _normalize_opening_overlay(payload.get("opening_overlay"))
    if overlay:
        current = base.get("opening_overlay") if isinstance(base.get("opening_overlay"), dict) else {}
        current_positions = dict(current.get("positions") or {})
        current_positions.update(overlay.get("positions") or {})
        base["opening_overlay"] = {
            "enabled": bool(overlay.get("enabled", current.get("enabled", True))),
            "version": str(overlay.get("version") or current.get("version") or "exp5_opening_overlay_v1"),
            "mode": str(overlay.get("mode") or current.get("mode") or "exact_position_book_prior"),
            "max_fullmove": max(int(overlay.get("max_fullmove") or 0), int(current.get("max_fullmove") or 0), 1),
            "positions": current_positions,
        }
    base["sample_count"] = int(base.get("sample_count") or 0) + max(0, int(payload.get("sample_count") or 0))
    base["updated_at"] = str(payload.get("updated_at") or base.get("updated_at") or _now())
    return normalize_experiment_nnue_model_payload(base)


def _numeric_delta_mapping(current: dict, base: dict) -> dict:
    deltas: dict[str, float] = {}
    keys = set(current or {}) | set(base or {})
    for key in sorted(str(item) for item in keys):
        current_value = float((current or {}).get(key) or 0.0)
        base_value = float((base or {}).get(key) or 0.0)
        delta = round(current_value - base_value, 6)
        if abs(delta) > 1e-9:
            deltas[key] = delta
    return deltas


def _model_experience_delta_payload(model: dict) -> dict:
    normalized = normalize_experiment_nnue_model_payload(model) or experiment_nnue_model_template()
    base = experiment_nnue_model_template()
    scalar_deltas: dict[str, int] = {}
    for key in ("tempo", "mobility_weight", "king_safety_weight"):
        delta = int(normalized.get(key) or 0) - int(base.get(key) or 0)
        if delta:
            scalar_deltas[key] = delta
    overlay_delta = {}
    overlay = normalized.get("opening_overlay") if isinstance(normalized.get("opening_overlay"), dict) else {}
    base_overlay = base.get("opening_overlay") if isinstance(base.get("opening_overlay"), dict) else {}
    overlay_positions = overlay.get("positions") if isinstance(overlay.get("positions"), dict) else {}
    base_positions = base_overlay.get("positions") if isinstance(base_overlay.get("positions"), dict) else {}
    changed_positions = {
        key: value
        for key, value in overlay_positions.items()
        if base_positions.get(key) != value
    }
    if changed_positions:
        overlay_delta = {
            "enabled": bool(overlay.get("enabled", True)),
            "version": str(overlay.get("version") or "exp5_opening_overlay_v1"),
            "mode": str(overlay.get("mode") or "exact_position_book_prior"),
            "max_fullmove": int(overlay.get("max_fullmove") or 12),
            "positions": changed_positions,
        }
    return {
        "version": _NNUE_VERSION,
        "architecture": "nnue-like-sparse-accumulator-v1",
        "artifact_role": EXP5_GENERATED_ARTIFACT_ROLE,
        "delta_format": EXP5_EXPERIENCE_DELTA_FORMAT,
        "base_model_role": EXP5_MAIN_MODEL_ROLE,
        "base_model_sha256": EXP5_STATIC_BASE_MODEL_SHA256,
        "feature_weights": _numeric_delta_mapping(normalized.get("feature_weights") or {}, base.get("feature_weights") or {}),
        "piece_square_weights": _numeric_delta_mapping(
            normalized.get("piece_square_weights") or {},
            base.get("piece_square_weights") or {},
        ),
        "opening_overlay": overlay_delta,
        "scalar_deltas": scalar_deltas,
        "training_objective": str(normalized.get("training_objective") or "position_move_evaluator_delta"),
        "sample_count": max(0, int(normalized.get("sample_count") or 0) - int(base.get("sample_count") or 0)),
        "updated_at": str(normalized.get("updated_at") or _now()),
    }


def _load_model(model_path: Path | None) -> dict:
    if model_path is None:
        return experiment_nnue_model_template()
    path = Path(model_path)
    if not path.exists():
        return experiment_nnue_model_template()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return experiment_nnue_model_template()
    delta_model = _compose_experience_delta_payload(payload)
    if delta_model is not None:
        return delta_model
    return normalize_experiment_nnue_model_payload(payload) or experiment_nnue_model_template()


def _save_model(model_path: Path, model: dict) -> None:
    normalized = _model_experience_delta_payload(model)
    path = Path(model_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(normalized, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    tmp_path.replace(path)


def save_experiment_nnue_experience_delta(model_path: Path, model: dict) -> None:
    """Persist only an exp5 source-base experience delta."""
    _save_model(Path(model_path), model)


def _resolve_search_profile(profile: str | None) -> dict:
    normalized = str(profile or "balanced").strip().lower()
    return dict(_SEARCH_PROFILES.get(normalized) or _SEARCH_PROFILES["balanced"])


def _piece_feature_key(square: int, piece: chess.Piece) -> str:
    return f"{'w' if piece.color == chess.WHITE else 'b'}:{piece.symbol().lower()}:{chess.square_name(square)}"


def _material_score(board: chess.Board) -> int:
    score = 0
    for piece in board.piece_map().values():
        value = _PIECE_VALUES[piece.piece_type]
        score += value if piece.color == chess.WHITE else -value
    return score


def _non_king_material_total(board: chess.Board) -> int:
    total = 0
    for piece in board.piece_map().values():
        if piece.piece_type != chess.KING:
            total += _PIECE_VALUES[piece.piece_type]
    return total


def _is_conversion_phase(board: chess.Board, color: chess.Color) -> bool:
    margin = _material_margin_for_color(board, color)
    if margin < _CONVERSION_MARGIN_CP:
        return False
    return (
        board.fullmove_number >= _CONVERSION_FULLMOVE
        or _non_king_material_total(board) <= _CONVERSION_TOTAL_MATERIAL_CP
    )


def _king_center_activity(square: int | None) -> int:
    if square is None:
        return 0
    file_distance = abs(chess.square_file(square) - 3.5)
    rank_distance = abs(chess.square_rank(square) - 3.5)
    # 0 at a corner, 42 at the four central squares.
    return int(round((7.0 - (file_distance + rank_distance)) * 12.0))


def _king_distance(first: int | None, second: int | None) -> int:
    if first is None or second is None:
        return 7
    return max(
        abs(chess.square_file(first) - chess.square_file(second)),
        abs(chess.square_rank(first) - chess.square_rank(second)),
    )


def _edge_distance(square: int | None) -> int:
    if square is None:
        return 3
    file = chess.square_file(square)
    rank = chess.square_rank(square)
    return min(file, 7 - file, rank, 7 - rank)


def _promotion_distance(square: int, color: chess.Color) -> int:
    rank = chess.square_rank(square)
    return 7 - rank if color == chess.WHITE else rank


def _is_passed_pawn(board: chess.Board, square: int, color: chess.Color) -> bool:
    direction = 1 if color == chess.WHITE else -1
    file = chess.square_file(square)
    rank = chess.square_rank(square)
    for enemy_square in board.pieces(chess.PAWN, not color):
        enemy_file = chess.square_file(enemy_square)
        enemy_rank = chess.square_rank(enemy_square)
        if abs(enemy_file - file) > 1:
            continue
        if (enemy_rank - rank) * direction > 0:
            return False
    return True


def _passed_pawn_squares(board: chess.Board, color: chess.Color) -> list[int]:
    return [
        square
        for square in board.pieces(chess.PAWN, color)
        if _is_passed_pawn(board, square, color)
    ]


def _fastest_passed_pawn_distance(board: chess.Board, color: chess.Color) -> int | None:
    distances = [_promotion_distance(square, color) for square in _passed_pawn_squares(board, color)]
    return min(distances) if distances else None


def _passed_pawn_advance_score(board: chess.Board, color: chess.Color) -> int:
    score = 0
    for square in board.pieces(chess.PAWN, color):
        rank = chess.square_rank(square)
        if not _is_passed_pawn(board, square, color):
            continue
        advancement = rank if color == chess.WHITE else 7 - rank
        score += max(0, advancement - 1)
    return score


def _has_mating_major(board: chess.Board, color: chess.Color) -> bool:
    return bool(board.pieces(chess.QUEEN, color) or board.pieces(chess.ROOK, color))


def _non_king_piece_count(board: chess.Board, color: chess.Color) -> int:
    return sum(
        len(board.pieces(piece_type, color))
        for piece_type in (chess.PAWN, chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN)
    )


def _is_bare_king_conversion(board: chess.Board, color: chess.Color) -> bool:
    return (
        _non_king_piece_count(board, not color) == 0
        and _has_mating_major(board, color)
        and _material_margin_for_color(board, color) >= _PIECE_VALUES[chess.ROOK]
    )


def _line_is_clear(board: chess.Board, first: int, second: int) -> bool:
    file_delta = chess.square_file(second) - chess.square_file(first)
    rank_delta = chess.square_rank(second) - chess.square_rank(first)
    step_file = 0 if file_delta == 0 else 1 if file_delta > 0 else -1
    step_rank = 0 if rank_delta == 0 else 1 if rank_delta > 0 else -1
    if file_delta and rank_delta and abs(file_delta) != abs(rank_delta):
        return False
    current_file = chess.square_file(first) + step_file
    current_rank = chess.square_rank(first) + step_rank
    while 0 <= current_file <= 7 and 0 <= current_rank <= 7:
        current = chess.square(current_file, current_rank)
        if current == second:
            return True
        if board.piece_at(current) is not None:
            return False
        current_file += step_file
        current_rank += step_rank
    return False


def _major_cutoff_score(board: chess.Board, color: chess.Color) -> int:
    enemy_king = board.king(not color)
    if enemy_king is None:
        return 0
    score = 0
    enemy_file = chess.square_file(enemy_king)
    enemy_rank = chess.square_rank(enemy_king)
    for square in board.pieces(chess.ROOK, color) | board.pieces(chess.QUEEN, color):
        same_file = chess.square_file(square) == enemy_file
        same_rank = chess.square_rank(square) == enemy_rank
        if (same_file or same_rank) and _line_is_clear(board, square, enemy_king):
            score += 360
        elif abs(chess.square_file(square) - enemy_file) <= 1 or abs(chess.square_rank(square) - enemy_rank) <= 1:
            score += 120
    return score


def _bare_king_mate_net_score(board: chess.Board, color: chess.Color) -> int:
    if not _is_bare_king_conversion(board, color):
        return 0
    if board.is_stalemate():
        return -25_000
    if board.is_checkmate():
        return 25_000 if board.turn != color else -25_000
    own_king = board.king(color)
    enemy_king = board.king(not color)
    edge = _edge_distance(enemy_king)
    king_distance = _king_distance(own_king, enemy_king)
    score = 0
    score += (3 - edge) * 520
    score += max(0, 7 - king_distance) * (95 if edge <= 1 else 65)
    score += _major_cutoff_score(board, color)
    if board.turn != color:
        reply_count = board.legal_moves.count()
        score += max(0, 24 - reply_count) * 38
        if board.is_check():
            score += 220
    if edge == 0 and king_distance <= 2:
        score += 520
    return score


def _is_passed_pawn_race_phase(board: chess.Board, color: chess.Color) -> bool:
    if _non_king_material_total(board) > 1400:
        return False
    return bool(_passed_pawn_squares(board, color) or _passed_pawn_squares(board, not color))


def _passed_pawn_race_score(board: chess.Board, color: chess.Color) -> int:
    if not _is_passed_pawn_race_phase(board, color):
        return 0
    score = 0
    own_distance = _fastest_passed_pawn_distance(board, color)
    enemy_distance = _fastest_passed_pawn_distance(board, not color)
    if own_distance is not None:
        score += max(0, 7 - own_distance) * 190
        if own_distance <= 1:
            score += 850
    if enemy_distance is not None:
        score -= max(0, 7 - enemy_distance) * 230
        if enemy_distance <= 1:
            score -= 1050
    if own_distance is not None and enemy_distance is not None:
        score += (enemy_distance - own_distance) * 260
    return score


def _endgame_progress_score(board: chess.Board, color: chess.Color) -> int:
    score = 0
    score += _bare_king_mate_net_score(board, color)
    score += _passed_pawn_race_score(board, color)
    if not (_is_conversion_phase(board, color) or _is_passed_pawn_race_phase(board, color)):
        return score
    own_king = board.king(color)
    enemy_king = board.king(not color)
    score += (_king_center_activity(own_king) - _king_center_activity(enemy_king) // 3) * 3
    score += _passed_pawn_advance_score(board, color) * 90
    score -= _passed_pawn_advance_score(board, not color) * 110
    return score


def _recent_own_shuffle_penalty(board: chess.Board, move: chess.Move) -> int:
    piece = board.piece_at(move.from_square)
    if (
        piece is None
        or piece.piece_type == chess.PAWN
        or board.is_capture(move)
        or move.promotion
        or board.is_castling(move)
    ):
        return 0
    penalty = 0
    own_moves = list(board.move_stack[-2::-2])[:_SHUFFLE_LOOKBACK_OWN_MOVES]
    for index, previous in enumerate(own_moves):
        decay = max(0, 1_000 - index * 90)
        if previous.promotion:
            continue
        if previous.from_square == move.to_square and previous.to_square == move.from_square:
            penalty += decay
        elif previous.from_square == move.from_square and previous.to_square == move.to_square:
            penalty += max(0, decay - 180)
        elif {previous.from_square, previous.to_square} == {move.from_square, move.to_square}:
            penalty += max(0, decay - 260)
    return penalty


def _endgame_move_progress_score(board: chess.Board, move: chess.Move, color: chess.Color) -> int:
    after = board.copy(stack=True)
    after.push(move)
    if after.is_checkmate():
        return 50_000
    if after.is_stalemate():
        return -30_000
    score = _endgame_progress_score(after, color)
    piece = board.piece_at(move.from_square)
    if piece is not None and piece.color == color and piece.piece_type == chess.PAWN:
        before_distance = _promotion_distance(move.from_square, color)
        after_distance = _promotion_distance(move.to_square, color)
        if _is_passed_pawn(board, move.from_square, color) or _is_passed_pawn(after, move.to_square, color):
            score += max(0, before_distance - after_distance) * 820
            score += max(0, 7 - after_distance) * 170
            if after_distance <= 1:
                score += 1_200
    score -= _recent_own_shuffle_penalty(board, move)
    return score


def _should_apply_endgame_progress(board: chess.Board, color: chess.Color) -> bool:
    if _is_bare_king_conversion(board, color) or _is_passed_pawn_race_phase(board, color):
        return True
    if _non_king_material_total(board) > _CONVERSION_TOTAL_MATERIAL_CP:
        return False
    return _is_conversion_phase(board, color)


def _endgame_conversion_score(board: chess.Board) -> int:
    """White-positive score for converting a clear material edge.

    Earlier exp5 builds learned to avoid losses, but complete reviewer games
    showed a second-order weakness: when ahead in rook/pawn endings the engine
    kept its king on the rim and accepted perpetual-check repetitions. This
    term only activates in low-material or late positions with a clear material
    lead, so it does not rewrite opening king-safety behavior.
    """
    score = 0
    for color, sign in ((chess.WHITE, 1), (chess.BLACK, -1)):
        if not _is_conversion_phase(board, color):
            continue
        own_king = board.king(color)
        enemy_king = board.king(not color)
        margin = min(1800, max(_CONVERSION_MARGIN_CP, _material_margin_for_color(board, color)))
        scale = margin / 900.0
        king_delta = _king_center_activity(own_king) - (_king_center_activity(enemy_king) // 3)
        passed = _passed_pawn_advance_score(board, color)
        score += sign * int(round(king_delta * scale))
        score += sign * int(round(passed * _PASSED_PAWN_ADVANCE_WEIGHT * scale))
    return score


def _v26_long_tail_phase(board: chess.Board) -> bool:
    return (
        board.fullmove_number >= _V26_LONG_TAIL_FULLMOVE
        or _non_king_material_total(board) <= _V26_LONG_TAIL_MATERIAL_CP
    )


def _v26_strict_endgame_eval_phase(board: chess.Board) -> bool:
    if _non_king_material_total(board) <= 2600:
        return True
    if board.fullmove_number >= 28:
        return True
    distances = [
        distance
        for color in (chess.WHITE, chess.BLACK)
        for distance in [_fastest_passed_pawn_distance(board, color)]
        if distance is not None
    ]
    return bool(distances and min(distances) <= 3)


def _v26_open_file_king_pressure(board: chess.Board, color: chess.Color) -> int:
    king = board.king(color)
    if king is None:
        return 0
    king_file = chess.square_file(king)
    penalty = 0
    for file_index in range(max(0, king_file - 1), min(7, king_file + 1) + 1):
        own_pawns = [
            square
            for square in board.pieces(chess.PAWN, color)
            if chess.square_file(square) == file_index
        ]
        any_pawns = [
            square
            for pawn_color in (chess.WHITE, chess.BLACK)
            for square in board.pieces(chess.PAWN, pawn_color)
            if chess.square_file(square) == file_index
        ]
        if not own_pawns:
            penalty += 18
        if not any_pawns:
            penalty += 45
    enemy_major_squares = board.pieces(chess.ROOK, not color) | board.pieces(chess.QUEEN, not color)
    for square in enemy_major_squares:
        same_file = chess.square_file(square) == king_file
        same_rank = chess.square_rank(square) == chess.square_rank(king)
        if same_file and _line_is_clear(board, square, king):
            piece = board.piece_at(square)
            penalty += 240 if piece is not None and piece.piece_type == chess.QUEEN else 180
        elif same_rank and _line_is_clear(board, square, king):
            penalty += 90
    return min(720, penalty)


def _v26_passed_pawn_pressure(board: chess.Board, color: chess.Color) -> int:
    score = 0
    own_king = board.king(color)
    enemy_king = board.king(not color)
    for square in _passed_pawn_squares(board, color):
        rank = chess.square_rank(square)
        advancement = rank if color == chess.WHITE else 7 - rank
        distance = _promotion_distance(square, color)
        promotion_square = chess.square(chess.square_file(square), 7 if color == chess.WHITE else 0)
        protected = any(
            (piece := board.piece_at(attacker)) is not None
            and piece.color == color
            and piece.piece_type in {chess.PAWN, chess.KING, chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN}
            for attacker in board.attackers(color, square)
        )
        score += 40 + max(0, advancement - 1) * 38 + max(0, 5 - distance) * 95
        if protected:
            score += 110
        if distance <= 2:
            score += 420
        if distance <= 1:
            score += 900
        own_distance = _king_distance(own_king, promotion_square)
        enemy_distance = _king_distance(enemy_king, promotion_square)
        score += (enemy_distance - own_distance) * 70
    return score


def _v26_long_tail_score(board: chess.Board, *, strict: bool = False) -> int:
    if strict:
        active = _v26_strict_endgame_eval_phase(board)
    else:
        active = _v26_long_tail_phase(board)
    if not active:
        return 0
    score = 0
    for color, sign in ((chess.WHITE, 1), (chess.BLACK, -1)):
        score += sign * _v26_passed_pawn_pressure(board, color)
        score -= sign * _v26_open_file_king_pressure(board, color)
        if _non_king_material_total(board) <= _V26_SELECTIVE_DEPTH_MATERIAL_CP:
            own_king = board.king(color)
            enemy_king = board.king(not color)
            score += sign * (_king_center_activity(own_king) - _king_center_activity(enemy_king) // 4) * 2
    return score


def _v26_long_tail_move_bonus(
    board: chess.Board,
    move: chess.Move,
    color: chess.Color,
    *,
    include_progress: bool = True,
    include_repetition: bool = True,
) -> int:
    if not _v26_long_tail_phase(board):
        return 0
    before = _v26_long_tail_score(board)
    after = board.copy(stack=include_repetition)
    after.push(move)
    if after.is_checkmate():
        return 50_000
    if after.is_stalemate():
        return -30_000
    side_sign = 1 if color == chess.WHITE else -1
    bonus = side_sign * (_v26_long_tail_score(after) - before)
    if include_progress and (_should_apply_endgame_progress(board, color) or _passed_pawn_squares(board, color)):
        bonus += _endgame_move_progress_score(board, move, color) // 2
    if include_repetition and _material_margin_for_color(after, color) >= 350 and (
        after.can_claim_threefold_repetition() or after.is_repetition(2)
    ):
        bonus -= 1300
    moved_piece = after.piece_at(move.to_square)
    if (
        moved_piece is not None
        and moved_piece.color == color
        and moved_piece.piece_type in {chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN}
        and not board.is_capture(move)
        and not move.promotion
        and not board.gives_check(move)
    ):
        attackers = len(list(after.attackers(not color, move.to_square)))
        defenders = len(list(after.attackers(color, move.to_square)))
        value = _PIECE_VALUES[moved_piece.piece_type]
        if attackers and defenders == 0:
            bonus -= value * 2
        elif attackers > defenders:
            bonus -= value
    return max(-4000, min(4000, int(bonus)))


def _v26_should_selective_depth(board: chess.Board, color: chess.Color) -> bool:
    if not _v26_long_tail_phase(board):
        return False
    total_material = _non_king_material_total(board)
    if total_material <= _V26_SELECTIVE_DEPTH_MATERIAL_CP:
        return True
    own_dist = _fastest_passed_pawn_distance(board, color)
    enemy_dist = _fastest_passed_pawn_distance(board, not color)
    if own_dist is not None and own_dist <= 2:
        return True
    if enemy_dist is not None and enemy_dist <= 2:
        return True
    if board.fullmove_number >= 26 and board.legal_moves.count() <= 16:
        return True
    if _material_margin_for_color(board, color) >= 700 and (
        board.can_claim_threefold_repetition() or board.is_repetition(2)
    ):
        return True
    return False


def _pawn_structure_score(board: chess.Board) -> int:
    score = 0
    for color, sign in ((chess.WHITE, 1), (chess.BLACK, -1)):
        pawns_by_file = {
            file_index: [square for square in board.pieces(chess.PAWN, color) if chess.square_file(square) == file_index]
            for file_index in range(8)
        }
        for file_index, pawns in pawns_by_file.items():
            if len(pawns) > 1:
                score -= sign * (len(pawns) - 1) * 22
            adjacent = []
            if file_index > 0:
                adjacent.extend(pawns_by_file[file_index - 1])
            if file_index < 7:
                adjacent.extend(pawns_by_file[file_index + 1])
            for square in pawns:
                rank = chess.square_rank(square)
                advancement = rank if color == chess.WHITE else 7 - rank
                if not adjacent:
                    score -= sign * 16
                if _is_passed_pawn(board, square, color):
                    protected = any(
                        board.piece_at(attacker) is not None
                        and board.piece_at(attacker).piece_type == chess.PAWN
                        for attacker in board.attackers(color, square)
                    )
                    connected = any(
                        abs(chess.square_file(other) - file_index) == 1
                        and abs(chess.square_rank(other) - rank) <= 1
                        for other in _passed_pawn_squares(board, color)
                        if other != square
                    )
                    score += sign * (28 + max(0, advancement - 1) * 24)
                    if protected:
                        score += sign * 28
                    if connected:
                        score += sign * 22
    return score


def _file_has_pawn(board: chess.Board, file_index: int, color: chess.Color | None = None) -> bool:
    for square in chess.SquareSet(chess.BB_FILES[file_index]):
        piece = board.piece_at(square)
        if piece is not None and piece.piece_type == chess.PAWN and (color is None or piece.color == color):
            return True
    return False


def _piece_activity_score(board: chess.Board) -> int:
    score = 0
    for color, sign in ((chess.WHITE, 1), (chess.BLACK, -1)):
        if len(board.pieces(chess.BISHOP, color)) >= 2:
            score += sign * 38
        for knight in board.pieces(chess.KNIGHT, color):
            rank = chess.square_rank(knight)
            advancement = rank if color == chess.WHITE else 7 - rank
            if 2 <= advancement <= 5:
                supported_by_pawn = any(
                    board.piece_at(attacker) is not None
                    and board.piece_at(attacker).piece_type == chess.PAWN
                    for attacker in board.attackers(color, knight)
                )
                enemy_pawn_attackers = [
                    attacker
                    for attacker in board.attackers(not color, knight)
                    if (piece := board.piece_at(attacker)) is not None and piece.piece_type == chess.PAWN
                ]
                if supported_by_pawn and not enemy_pawn_attackers:
                    score += sign * 34
        seventh_rank = 6 if color == chess.WHITE else 1
        for rook in board.pieces(chess.ROOK, color):
            file_index = chess.square_file(rook)
            open_file = not _file_has_pawn(board, file_index)
            semi_open = not _file_has_pawn(board, file_index, color)
            if open_file:
                score += sign * 34
            elif semi_open:
                score += sign * 18
            if chess.square_rank(rook) == seventh_rank:
                score += sign * 32
    return score


def _center_break_score(board: chess.Board) -> int:
    """Reward generic central pawn breaks that hit overextended pieces.

    This is intentionally position-based, not an opening-line prior.  The term
    activates only for pawns already placed on central break squares and gives
    extra value when that pawn attacks an enemy minor/major piece in the center
    band or restrains an advanced enemy center pawn.
    """
    if _non_king_material_total(board) < 3000 or board.fullmove_number > 16:
        return 0
    score = 0
    for color, sign in ((chess.WHITE, 1), (chess.BLACK, -1)):
        enemy = not color
        enemy_advanced_center = [
            square
            for square in board.pieces(chess.PAWN, enemy)
            if square in _CENTER_BREAK_PAWN_SQUARES
            and ((enemy == chess.WHITE and chess.square_rank(square) >= 3) or (enemy == chess.BLACK and chess.square_rank(square) <= 4))
        ]
        for square in board.pieces(chess.PAWN, color):
            if square not in _CENTER_BREAK_PAWN_SQUARES:
                continue
            local = 0
            attacks = set(board.attacks(square))
            for target in attacks:
                piece = board.piece_at(target)
                if piece is None or piece.color == color:
                    continue
                if target in _CENTER or target in _EXTENDED_CENTER:
                    if piece.piece_type in {chess.KNIGHT, chess.BISHOP}:
                        local += 76
                    elif piece.piece_type == chess.QUEEN:
                        local += 92
                    elif piece.piece_type == chess.ROOK:
                        local += 38
                    elif piece.piece_type == chess.PAWN:
                        local += 26
            for enemy_pawn in enemy_advanced_center:
                if abs(chess.square_file(enemy_pawn) - chess.square_file(square)) <= 1:
                    local += 18
                if enemy_pawn in attacks:
                    local += 34
            defenders = [
                attacker
                for attacker in board.attackers(color, square)
                if (piece := board.piece_at(attacker)) is not None and piece.piece_type != chess.KING
            ]
            attackers = [
                attacker
                for attacker in board.attackers(enemy, square)
                if (piece := board.piece_at(attacker)) is not None and piece.piece_type != chess.KING
            ]
            if local and defenders:
                local += 14
            if local and len(attackers) > len(defenders) + 1:
                local -= 48
            score += sign * max(0, min(180, local))
    return score


def _fianchetto_development_score(board: chess.Board) -> int:
    """Prefer completing a fianchetto once the flank pawn has been committed."""
    if _non_king_material_total(board) < 3000 or board.fullmove_number > 18:
        return 0
    score = 0
    for color, pawn_square, home_bishop_square, target_bishop_square, center_targets in _FIANCHETTO_PLANS:
        sign = 1 if color == chess.WHITE else -1
        pawn = board.piece_at(pawn_square)
        bishop_home = board.piece_at(home_bishop_square)
        bishop_target = board.piece_at(target_bishop_square)
        if pawn != chess.Piece(chess.PAWN, color):
            continue
        if bishop_target == chess.Piece(chess.BISHOP, color):
            local = 58
            attacks = set(board.attacks(target_bishop_square))
            if attacks & set(center_targets):
                local += 18
            if board.has_castling_rights(color):
                local += 10
            score += sign * local
            continue
        if bishop_home == chess.Piece(chess.BISHOP, color):
            local = 54
            if board.piece_at(target_bishop_square) is None:
                local += 18
            score -= sign * local
    return score


def _center_break_move_bonus(board: chess.Board, move: chess.Move) -> int:
    if _non_king_material_total(board) < 3000 or board.fullmove_number > 16 or board.is_check():
        return 0
    piece = board.piece_at(move.from_square)
    if piece is None or piece.piece_type != chess.PAWN or move.promotion:
        return 0
    if move.to_square not in _CENTER_BREAK_PAWN_SQUARES:
        return 0
    bonus = 0
    after = board.copy(stack=False)
    after.push(move)
    for target in after.attacks(move.to_square):
        target_piece = after.piece_at(target)
        if target_piece is None or target_piece.color == piece.color:
            continue
        if target not in _CENTER and target not in _EXTENDED_CENTER:
            continue
        if target_piece.piece_type in {chess.KNIGHT, chess.BISHOP}:
            bonus += 1350
        elif target_piece.piece_type == chess.QUEEN:
            bonus += 1550
        elif target_piece.piece_type == chess.ROOK:
            bonus += 650
        elif target_piece.piece_type == chess.PAWN:
            bonus += 420
    enemy = not piece.color
    for enemy_pawn in after.pieces(chess.PAWN, enemy):
        if enemy_pawn not in _CENTER_BREAK_PAWN_SQUARES:
            continue
        if abs(chess.square_file(enemy_pawn) - chess.square_file(move.to_square)) <= 1:
            bonus += 260
        if enemy_pawn in after.attacks(move.to_square):
            bonus += 420
    if bonus and len(list(after.attackers(enemy, move.to_square))) > len(list(after.attackers(piece.color, move.to_square))) + 1:
        bonus -= 650
    return max(0, min(1900, bonus))


def _fianchetto_development_move_bonus(board: chess.Board, move: chess.Move) -> int:
    if _non_king_material_total(board) < 3000 or board.fullmove_number > 18 or board.is_check():
        return 0
    piece = board.piece_at(move.from_square)
    if piece is None or piece.piece_type != chess.BISHOP:
        return 0
    for checking_move in board.legal_moves:
        if checking_move == move or not board.gives_check(checking_move):
            continue
        checker = board.piece_at(checking_move.from_square)
        if checker is not None and checker.color == piece.color and checker.piece_type in {chess.QUEEN, chess.BISHOP, chess.KNIGHT}:
            return 0
    for color, pawn_square, home_bishop_square, target_bishop_square, center_targets in _FIANCHETTO_PLANS:
        if piece.color != color or move.from_square != home_bishop_square or move.to_square != target_bishop_square:
            continue
        if board.piece_at(pawn_square) != chess.Piece(chess.PAWN, color):
            continue
        bonus = 1320
        after = board.copy(stack=False)
        after.push(move)
        if set(after.attacks(target_bishop_square)) & set(center_targets):
            bonus += 240
        if board.has_castling_rights(color):
            bonus += 120
        return bonus
    return 0


def _king_zone_pressure_score(board: chess.Board) -> int:
    score = 0
    attacker_value = {
        chess.PAWN: 1,
        chess.KNIGHT: 3,
        chess.BISHOP: 3,
        chess.ROOK: 5,
        chess.QUEEN: 8,
        chess.KING: 0,
    }
    for color, sign in ((chess.WHITE, 1), (chess.BLACK, -1)):
        king = board.king(color)
        if king is None:
            continue
        zone = [king]
        king_file = chess.square_file(king)
        king_rank = chess.square_rank(king)
        for df in (-1, 0, 1):
            for dr in (-1, 0, 1):
                if df == 0 and dr == 0:
                    continue
                file_index = king_file + df
                rank_index = king_rank + dr
                if 0 <= file_index <= 7 and 0 <= rank_index <= 7:
                    zone.append(chess.square(file_index, rank_index))
        pressure = 0
        for target in zone:
            for attacker in board.attackers(not color, target):
                piece = board.piece_at(attacker)
                if piece is not None:
                    pressure += attacker_value.get(piece.piece_type, 0)
        score -= sign * min(420, pressure * 11)

        # Pawn shield for castled or castling-side kings. Missing shield pawns
        # become more important when files near the king are open.
        if king_file in {0, 1, 2, 5, 6, 7}:
            shield_rank = 1 if color == chess.WHITE else 6
            second_rank = 2 if color == chess.WHITE else 5
            missing = 0
            for file_index in range(max(0, king_file - 1), min(7, king_file + 1) + 1):
                primary = chess.square(file_index, shield_rank)
                secondary = chess.square(file_index, second_rank)
                if board.piece_at(primary) != chess.Piece(chess.PAWN, color) and board.piece_at(secondary) != chess.Piece(chess.PAWN, color):
                    missing += 1
            score -= sign * missing * 18
    return score


def _sparse_feature_score(board: chess.Board, model: dict) -> int:
    feature_weights = model.get("feature_weights") or {}
    piece_square_weights = model.get("piece_square_weights") or {}
    score = 0.0
    for square, piece in board.piece_map().items():
        sign = 1.0 if piece.color == chess.WHITE else -1.0
        score += sign * float(piece_square_weights.get(_piece_feature_key(square, piece), 0.0))
        if square in _CENTER and piece.piece_type in {chess.PAWN, chess.KNIGHT, chess.BISHOP}:
            score += sign * float(feature_weights.get("center_control", 18.0))
        elif square in _EXTENDED_CENTER and piece.piece_type in {chess.PAWN, chess.KNIGHT, chess.BISHOP}:
            score += sign * float(feature_weights.get("extended_center_control", 8.0))
    return int(round(score))


def _mobility_score(board: chess.Board, model: dict) -> int:
    current_turn = board.turn
    current = board.legal_moves.count()
    board.turn = not current_turn
    try:
        other = board.legal_moves.count()
    finally:
        board.turn = current_turn
    weight = int(model.get("mobility_weight") or 0)
    white_score = (current - other) * weight if current_turn == chess.WHITE else (other - current) * weight
    return int(white_score)


def _king_safety_score(board: chess.Board, model: dict) -> int:
    """King-safety eval term (centipawns, white-positive).

    Upgraded for exp5_06 (exp3-example2 lesson item 10):

    1. Reward the king for being inside a *post-castle haven* — a set of
       squares typical of a castled (and possibly slightly shuffled) king,
       NOT just g1/c1. This generalises "the king is safe" beyond the
       strict O-O/O-O-O target squares, so the model doesn't lose all
       reward when the king moves Kg1→h1 or Kg1→f1 after castling.

    2. Penalise an *uncastled* king that is still on its starting square
       after the opening (fullmove_number > 12). exp3 example2 showed the
       failure mode where a candidate model walks the king from e1 in the
       early middlegame because the eval surface has no incentive to
       castle. The penalty is `weight // 2` so it's smaller than the
       safe-haven reward but big enough that a same-difference safe move
       (e.g. Ke1-e2) doesn't look neutral.

    3. The is-check penalty is unchanged: still `-weight` for whichever
       side is currently in check.
    """
    weight = int(model.get("king_safety_weight") or 0)
    score = 0

    wk = board.king(chess.WHITE)
    bk = board.king(chess.BLACK)
    if wk in _WHITE_KING_SAFE_SQUARES:
        score += weight
    if bk in _BLACK_KING_SAFE_SQUARES:
        score -= weight

    # Uncastled-king penalty after the opening.
    fm = board.fullmove_number
    if fm > _EARLY_KING_PENALTY_AFTER_FULLMOVE and weight > 0:
        if wk == chess.E1 and board.has_castling_rights(chess.WHITE) is False:
            # K has moved (no rights) but is back on e1: an unusual case;
            # still treat as exposed.
            score -= weight // 2
        elif wk == chess.E1:
            # K hasn't moved at all — castling never happened; penalise.
            score -= weight // 2
        if bk == chess.E8 and board.has_castling_rights(chess.BLACK) is False:
            score += weight // 2
        elif bk == chess.E8:
            score += weight // 2

    if board.is_check():
        score += -weight if board.turn == chess.WHITE else weight
    return score


def _nnue_eval(board: chess.Board, model: dict, eval_cache: dict[int, int], hasher: ZobristHasher) -> int:
    board_hash = hasher.hash_board(board)
    cached = eval_cache.get(board_hash)
    if cached is not None:
        return cached
    score = _material_score(board)
    score += _sparse_feature_score(board, model)
    score += _mobility_score(board, model)
    score += _king_safety_score(board, model)
    if bool(model.get("_enable_rich_eval") or model.get("_enable_pawn_structure")):
        score += _pawn_structure_score(board)
    if bool(
        model.get("_enable_rich_eval")
        or model.get("_enable_piece_activity")
        or (
            model.get("_enable_piece_activity_midgame")
            and _non_king_material_total(board) >= 4200
            and (board.fullmove_number <= 8 or abs(_material_score(board)) >= 700)
        )
    ):
        score += _piece_activity_score(board)
    if bool(model.get("_enable_center_break")):
        score += _center_break_score(board)
    if bool(model.get("_enable_fianchetto_development")):
        score += _fianchetto_development_score(board)
    if bool(model.get("_enable_rich_eval") or model.get("_enable_king_zone_pressure")):
        score += _king_zone_pressure_score(board)
    score += _endgame_conversion_score(board)
    if bool(model.get("_enable_v26_long_tail_eval")):
        v26_scale = max(0, min(100, int(model.get("_v26_long_tail_scale_percent") or 100)))
        v26_score = _v26_long_tail_score(board, strict=bool(model.get("_enable_v26_long_tail_eval_strict")))
        score += int(round(v26_score * (v26_scale / 100.0)))
    score += int(model.get("tempo") or 0) if board.turn == chess.WHITE else -int(model.get("tempo") or 0)
    eval_cache[board_hash] = score
    return score


def _move_order_score(board: chess.Board, move: chess.Move) -> int:
    score = 0
    if board.is_capture(move):
        captured = _captured_piece(board, move)
        attacker = board.piece_at(move.from_square)
        if captured is not None:
            score += _PIECE_VALUES.get(captured.piece_type, 0) * 10
        if attacker is not None:
            score -= _PIECE_VALUES.get(attacker.piece_type, 0)
        see = _static_exchange_eval(board, move)
        score += see * 4
        if see < -80:
            score += see * 5
    if move.promotion:
        score += 8_000 + _promotion_priority(move) * 250
    if board.is_en_passant(move):
        score += 3_000
    if board.gives_check(move):
        score += 1_500
    # exp3-example2 lesson item 10: castling itself is desirable. Without this
    # bonus the cheap eval has no reason to pick e1g1 over a center pawn move
    # in the opening — exp3 castled 0/5 across the dirty replay set; the exp5
    # baseline (pre-fix) castled in 1/4 special-rule cases for the same
    # reason. The bonus is large enough to compete with the +500 develop-
    # minor-piece bonus + the +240 to-center bonus that often win on move 5.
    if board.is_castling(move):
        score += 700
    piece = board.piece_at(move.from_square)
    if piece and piece.piece_type in {chess.KNIGHT, chess.BISHOP} and chess.square_rank(move.from_square) in {0, 7}:
        score += 500
    if piece and piece.piece_type == chess.KING and _is_conversion_phase(board, piece.color):
        before_activity = _king_center_activity(move.from_square)
        after_activity = _king_center_activity(move.to_square)
        score += (after_activity - before_activity) * _KING_ACTIVITY_WEIGHT
    if move.to_square in _CENTER:
        score += 240
    return score


def _opening_development_bonus(board: chess.Board, move: chess.Move) -> int:
    """Prefer normal off-book development over flank pawn/rook wandering.

    The static route-level book handles common openings. This guard covers
    off-book positions, where the shallow NNUE eval has been prone to moves
    like ...a5/...a4 or early rook captures that win a pawn but leave
    development and king safety behind.
    """
    if board.fullmove_number > _OPENING_DEVELOPMENT_FULLMOVE_LIMIT or board.is_check():
        return 0
    piece = board.piece_at(move.from_square)
    if piece is None:
        return 0
    score = 0
    if board.is_castling(move):
        score += 2200
    if piece.piece_type in {chess.KNIGHT, chess.BISHOP}:
        home_rank = 0 if piece.color == chess.WHITE else 7
        if chess.square_rank(move.from_square) == home_rank:
            score += 1500
        if move.to_square in _CENTER or move.to_square in _EXTENDED_CENTER:
            score += 500
    if piece.piece_type == chess.PAWN:
        from_file = chess.square_file(move.from_square)
        to_rank = chess.square_rank(move.to_square)
        if from_file in {3, 4}:
            score += 1250
        elif from_file in {2, 5}:
            score += 450
        elif from_file in _NEAR_FLANK_FILES:
            score -= 300
        elif from_file in _FLANK_FILES:
            score -= 1100
        if move.to_square in _CENTER or move.to_square in _EXTENDED_CENTER:
            score += 350
        if to_rank in {3, 4}:
            score += 150
    if piece.piece_type == chess.ROOK:
        captured_value = _captured_piece_value(board, move)
        if not board.is_castling(move) and captured_value < _PIECE_VALUES[chess.ROOK] and not board.gives_check(move):
            score -= 2200
    if piece.piece_type == chess.QUEEN and not board.gives_check(move) and not board.is_capture(move):
        score -= 800
    return score


def _is_early_flank_pawn_drift(board: chess.Board, move: chess.Move) -> bool:
    if board.fullmove_number > _OPENING_DEVELOPMENT_FULLMOVE_LIMIT or board.is_check():
        return False
    piece = board.piece_at(move.from_square)
    if piece is None or piece.piece_type != chess.PAWN:
        return False
    from_file = chess.square_file(move.from_square)
    from_rank = chess.square_rank(move.from_square)
    to_rank = chess.square_rank(move.to_square)
    is_flank = from_file in _FLANK_FILES
    is_near_flank_double_push = from_file in _NEAR_FLANK_FILES and abs(to_rank - from_rank) >= 2
    if not (is_flank or is_near_flank_double_push):
        return False
    return not board.is_capture(move) and not board.gives_check(move) and move.promotion is None


def _is_early_rook_excursion(board: chess.Board, move: chess.Move) -> bool:
    if board.fullmove_number > _OPENING_DEVELOPMENT_FULLMOVE_LIMIT or board.is_check():
        return False
    piece = board.piece_at(move.from_square)
    if piece is None or piece.piece_type != chess.ROOK:
        return False
    if board.is_castling(move) or board.gives_check(move):
        return False
    return _captured_piece_value(board, move) < _PIECE_VALUES[chess.ROOK]


def _opening_development_filter(board: chess.Board, best_move: chess.Move | None, *, score_move) -> chess.Move | None:
    if best_move is None:
        return None
    if not (_is_early_flank_pawn_drift(board, best_move) or _is_early_rook_excursion(board, best_move)):
        return best_move
    alternatives = [
        move
        for move in board.legal_moves
        if (
            not _would_stalemate(board, move)
            and not _is_early_flank_pawn_drift(board, move)
            and not _is_early_rook_excursion(board, move)
        )
    ]
    if not alternatives:
        return best_move

    def candidate_score(move: chess.Move) -> float:
        return float(score_move(move)) + float(_opening_development_bonus(board, move))

    return max(alternatives, key=lambda move: (candidate_score(move), move.uci()))


def _is_low_value_opening_pawn_capture(board: chess.Board, move: chess.Move) -> bool:
    if board.fullmove_number > _OPENING_DEVELOPMENT_FULLMOVE_LIMIT or board.is_check():
        return False
    piece = board.piece_at(move.from_square)
    if piece is None or piece.piece_type != chess.PAWN:
        return False
    if not board.is_capture(move) or move.promotion or board.gives_check(move):
        return False
    if _captured_piece_value(board, move) > _PIECE_VALUES[chess.PAWN]:
        return False
    if _static_exchange_eval(board, move) > 180:
        return False
    return True


def _opening_low_value_capture_filter(board: chess.Board, best_move: chess.Move | None, *, score_move) -> chess.Move | None:
    if best_move is None or not _is_low_value_opening_pawn_capture(board, best_move):
        return best_move
    chosen_score = float(score_move(best_move))
    candidates: list[tuple[float, str, chess.Move]] = []
    for candidate in board.legal_moves:
        if candidate == best_move or _would_stalemate(board, candidate):
            continue
        piece = board.piece_at(candidate.from_square)
        if piece is None:
            continue
        if piece.piece_type not in {chess.KNIGHT, chess.BISHOP}:
            continue
        home_rank = 0 if piece.color == chess.WHITE else 7
        if chess.square_rank(candidate.from_square) != home_rank:
            continue
        if candidate.to_square not in _CENTER and candidate.to_square not in _EXTENDED_CENTER:
            continue
        after = board.copy(stack=False)
        after.push(candidate)
        if _opponent_mate_in_one_moves(after):
            continue
        if _worst_immediate_reply_material_margin(after, piece.color) < _material_margin_for_color(board, piece.color) - 380:
            continue
        score = float(score_move(candidate)) + float(_opening_development_bonus(board, candidate))
        if score >= chosen_score - 700.0:
            candidates.append((score, candidate.uci(), candidate))
    if not candidates:
        return best_move
    return sorted(candidates, reverse=True)[0][2]


def _is_opening_home_rank_minor_development(board: chess.Board, move: chess.Move) -> bool:
    if board.fullmove_number > _OPENING_DEVELOPMENT_FULLMOVE_LIMIT or board.is_check():
        return False
    piece = board.piece_at(move.from_square)
    if piece is None or piece.piece_type not in {chess.KNIGHT, chess.BISHOP}:
        return False
    home_rank = 0 if piece.color == chess.WHITE else 7
    if chess.square_rank(move.from_square) != home_rank:
        return False
    if move.to_square not in _CENTER and move.to_square not in _EXTENDED_CENTER:
        return False
    if move.promotion or board.gives_check(move):
        return False
    after = board.copy(stack=False)
    after.push(move)
    if _opponent_mate_in_one_moves(after):
        return False
    if _worst_immediate_reply_material_margin(after, piece.color) < _material_margin_for_color(board, piece.color) - 380:
        return False
    return True


def _is_opening_minor_revisit_before_home_development(board: chess.Board, move: chess.Move) -> bool:
    if board.fullmove_number > _OPENING_DEVELOPMENT_FULLMOVE_LIMIT or board.is_check():
        return False
    piece = board.piece_at(move.from_square)
    if piece is None or piece.piece_type not in {chess.KNIGHT, chess.BISHOP}:
        return False
    home_rank = 0 if piece.color == chess.WHITE else 7
    if chess.square_rank(move.from_square) == home_rank:
        return False
    if board.is_capture(move) or move.promotion or board.gives_check(move):
        return False
    return any(_is_opening_home_rank_minor_development(board, candidate) for candidate in board.legal_moves)


def _opening_minor_revisit_filter(board: chess.Board, best_move: chess.Move | None, *, score_move) -> chess.Move | None:
    if best_move is None or not _is_opening_minor_revisit_before_home_development(board, best_move):
        return best_move
    chosen_score = float(score_move(best_move)) + float(_opening_development_bonus(board, best_move))
    candidates: list[tuple[float, str, chess.Move]] = []
    for candidate in board.legal_moves:
        if candidate == best_move or _would_stalemate(board, candidate):
            continue
        if not _is_opening_home_rank_minor_development(board, candidate):
            continue
        score = float(score_move(candidate)) + float(_opening_development_bonus(board, candidate))
        if score >= chosen_score - 900.0:
            candidates.append((score, candidate.uci(), candidate))
    if not candidates:
        return best_move
    return sorted(candidates, reverse=True)[0][2]


def _opening_king_walk_filter(board: chess.Board, best_move: chess.Move | None, *, score_move) -> chess.Move | None:
    """Avoid early non-castling king walks when a sane non-king answer exists.

    The complete-game gauntlet exposed a French-defense loss where exp5 met
    opening checks with Kd2/Kd3/Ke2 while ordinary blocks or developing moves
    were legal. This guard is intentionally early-game only and keeps forced
    king escapes, castling, mates, and clearly profitable king captures intact.
    """
    if (
        best_move is None
        or not board.is_check()
        or board.fullmove_number > _OPENING_KING_WALK_FULLMOVE_LIMIT
    ):
        return best_move
    piece = board.piece_at(best_move.from_square)
    if piece is None or piece.piece_type != chess.KING or board.is_castling(best_move):
        return best_move
    home_square = chess.E1 if piece.color == chess.WHITE else chess.E8
    if best_move.from_square != home_square:
        return best_move
    after_best = board.copy(stack=False)
    after_best.push(best_move)
    if after_best.is_checkmate():
        return best_move
    if board.is_capture(best_move) and _captured_piece_value(board, best_move) >= _PIECE_VALUES[chess.ROOK]:
        if _static_exchange_eval(board, best_move) >= 0:
            return best_move
    color = piece.color
    chosen_floor = _worst_immediate_reply_material_margin(after_best, color)
    allowed_floor_drop = 700 if board.is_check() else 220
    chosen_score = float(score_move(best_move))
    candidates: list[tuple[float, int, str, chess.Move]] = []
    for candidate in board.legal_moves:
        if candidate == best_move or _would_stalemate(board, candidate):
            continue
        candidate_piece = board.piece_at(candidate.from_square)
        if candidate_piece is None or candidate_piece.piece_type == chess.KING:
            continue
        if board.is_capture(candidate) and _static_exchange_eval(board, candidate) < -150:
            continue
        after = board.copy(stack=False)
        after.push(candidate)
        if after.is_checkmate():
            return candidate
        if _opponent_mate_in_one_moves(after):
            continue
        floor = _worst_immediate_reply_material_margin(after, color)
        if floor < chosen_floor - allowed_floor_drop:
            continue
        score = float(score_move(candidate))
        score += float(_opening_development_bonus(board, candidate))
        if board.is_check():
            score += 1300.0
        if candidate_piece.piece_type in {chess.KNIGHT, chess.BISHOP}:
            home_rank = 0 if candidate_piece.color == chess.WHITE else 7
            if chess.square_rank(candidate.from_square) == home_rank:
                score += 700.0
            if candidate.to_square in _CENTER or candidate.to_square in _EXTENDED_CENTER:
                score += 300.0
        if candidate_piece.piece_type == chess.PAWN and candidate.to_square in _EXTENDED_CENTER:
            score += 450.0
        if candidate_piece.piece_type == chess.QUEEN and board.is_check():
            score -= 250.0
        candidates.append((score, floor, candidate.uci(), candidate))
    if not candidates:
        return best_move
    best_score, _floor, _uci, candidate = sorted(candidates, reverse=True)[0]
    if board.is_check() or best_score >= chosen_score - 120.0:
        return candidate
    return best_move


def _opening_moved_king_home_filter(board: chess.Board, best_move: chess.Move | None, *, score_move) -> chess.Move | None:
    """Prefer returning an already-walked king home during opening checks.

    A reviewer gauntlet regression exposed a narrow failure after early queen
    pressure: once the king had been pulled to e2/e7, a shallow eval preferred
    Kd1/Kd8 style drift over the safer Ke1/Ke8 reset. This guard only applies
    while in check, before move 12, and only when the home-square retreat is
    legal and tactically comparable.
    """
    if (
        best_move is None
        or not board.is_check()
        or board.fullmove_number > _OPENING_KING_WALK_FULLMOVE_LIMIT
    ):
        return best_move
    piece = board.piece_at(best_move.from_square)
    if piece is None or piece.piece_type != chess.KING or board.is_castling(best_move):
        return best_move
    home_square = chess.E1 if piece.color == chess.WHITE else chess.E8
    if best_move.from_square == home_square or best_move.to_square == home_square:
        return best_move
    home_move = chess.Move(best_move.from_square, home_square)
    if home_move not in board.legal_moves or _would_stalemate(board, home_move):
        return best_move
    chosen_after = board.copy(stack=True)
    chosen_after.push(best_move)
    home_after = board.copy(stack=True)
    home_after.push(home_move)
    if home_after.is_checkmate() or _opponent_mate_in_one_moves(home_after):
        return best_move
    color = piece.color
    chosen_floor = _worst_immediate_reply_material_margin(chosen_after, color)
    home_floor = _worst_immediate_reply_material_margin(home_after, color)
    if home_floor < chosen_floor - 220:
        return best_move
    chosen_score = float(score_move(best_move))
    home_score = float(score_move(home_move))
    if home_score >= chosen_score - 650.0:
        return home_move
    return best_move


def _promotion_priority(move: chess.Move) -> int:
    return {
        chess.QUEEN: 4,
        chess.ROOK: 3,
        chess.BISHOP: 2,
        chess.KNIGHT: 1,
    }.get(move.promotion, 0)


def _captured_piece(board: chess.Board, move: chess.Move) -> chess.Piece | None:
    if board.is_en_passant(move):
        capture_square = chess.square(chess.square_file(move.to_square), chess.square_rank(move.from_square))
        return board.piece_at(capture_square)
    return board.piece_at(move.to_square)


def _captured_piece_value(board: chess.Board, move: chess.Move) -> int:
    captured = _captured_piece(board, move)
    return _PIECE_VALUES.get(captured.piece_type, 0) if captured else 0


def _move_piece_value(board: chess.Board, move: chess.Move) -> int:
    piece = board.piece_at(move.from_square)
    if piece is None:
        return 0
    if move.promotion:
        return _PIECE_VALUES.get(move.promotion, _PIECE_VALUES[piece.piece_type])
    return _PIECE_VALUES[piece.piece_type]


def _least_valuable_capture_to(board: chess.Board, target_square: int) -> list[chess.Move]:
    captures = [
        move
        for move in board.legal_moves
        if board.is_capture(move) and move.to_square == target_square
    ]
    return sorted(
        captures,
        key=lambda move: (
            _move_piece_value(board, move),
            -_captured_piece_value(board, move),
            move.uci(),
        ),
    )


def _see_reply_gain(board: chess.Board, target_square: int, depth: int = 0) -> int:
    """Best material gain available by continuing captures on one square.

    This is a deliberately small legal-move SEE approximation. It is slower
    than bitboard SEE, but it is accurate enough for exp5's shallow Python
    search and avoids another hand-written "safe capture" special case.
    """
    if depth >= _SEE_MAX_DEPTH or board.is_game_over():
        return 0
    best = 0
    for reply in _least_valuable_capture_to(board, target_square):
        captured = _captured_piece_value(board, reply)
        if captured <= 0:
            continue
        after = board.copy(stack=False)
        after.push(reply)
        gain = captured - _see_reply_gain(after, target_square, depth + 1)
        if gain > best:
            best = gain
    return max(0, best)


def _static_exchange_eval(board: chess.Board, move: chess.Move) -> int:
    """Approximate centipawn exchange result for the side to move."""
    if move not in board.legal_moves:
        return -_PIECE_VALUES[chess.QUEEN]
    captured = _captured_piece_value(board, move)
    promotion_gain = 0
    piece = board.piece_at(move.from_square)
    if piece is not None and move.promotion:
        promotion_gain = _PIECE_VALUES.get(move.promotion, _PIECE_VALUES[piece.piece_type]) - _PIECE_VALUES[piece.piece_type]
    if captured <= 0 and promotion_gain <= 0:
        return 0
    after = board.copy(stack=False)
    after.push(move)
    if after.is_checkmate():
        return _PIECE_VALUES[chess.KING]
    return int(captured + promotion_gain - _see_reply_gain(after, move.to_square))


def _captured_pawn_promotion_danger(board: chess.Board, move: chess.Move) -> int:
    captured = _captured_piece(board, move)
    if captured is None or captured.piece_type != chess.PAWN:
        return 0
    rank = chess.square_rank(move.to_square)
    if captured.color == chess.BLACK and rank <= 2:
        return 3 - rank
    if captured.color == chess.WHITE and rank >= 5:
        return rank - 4
    return 0


def _material_margin_for_color(board: chess.Board, color: chess.Color) -> int:
    margin = 0
    for piece_type, value in _PIECE_VALUES.items():
        if piece_type == chess.KING:
            continue
        margin += len(board.pieces(piece_type, color)) * value
        margin -= len(board.pieces(piece_type, not color)) * value
    return margin


def _worst_immediate_reply_material_margin(board: chess.Board, color: chess.Color) -> int:
    """Worst material margin after the opponent's immediate forcing reply."""
    worst = _material_margin_for_color(board, color)
    for reply in board.legal_moves:
        after = board.copy(stack=False)
        after.push(reply)
        if after.is_checkmate():
            return -_PIECE_VALUES[chess.KING]
        if board.is_capture(reply):
            worst = min(worst, _material_margin_for_color(after, color))
    return worst


def _opponent_knight_fork_danger(board: chess.Board, color: chess.Color) -> int:
    """Estimate next-move knight checks that fork an undefended rook/queen."""
    if board.turn == color:
        return 0
    danger = 0
    for reply in board.legal_moves:
        piece = board.piece_at(reply.from_square)
        if piece is None or piece.color == color or piece.piece_type != chess.KNIGHT:
            continue
        after = board.copy(stack=False)
        after.push(reply)
        if not after.is_check():
            continue
        attacked_value = 0
        for square in after.attacks(reply.to_square):
            target = after.piece_at(square)
            if target is None or target.color != color:
                continue
            if target.piece_type in {chess.ROOK, chess.QUEEN}:
                attacked_value = max(attacked_value, _PIECE_VALUES[target.piece_type])
        if attacked_value <= 0:
            continue
        can_capture_forker = any(
            response.to_square == reply.to_square and after.is_capture(response)
            for response in after.legal_moves
        )
        if not can_capture_forker:
            danger = max(danger, attacked_value)
    return danger


def _legal_after_move(board: chess.Board, move: chess.Move) -> chess.Board:
    after = board.copy(stack=False)
    after.push(move)
    return after


def _to_nnue_board(board_state, side: str) -> chess.Board:
    if isinstance(board_state, dict) and isinstance(board_state.get(_MOVE_HISTORY_KEY), list):
        try:
            return replay_board_from_history(board_state.get(_MOVE_HISTORY_KEY), initial_fen=START_FEN)
        except Exception:
            pass
    return to_chess_board(board_state, side)


def _would_stalemate(board: chess.Board, move: chess.Move) -> bool:
    return _legal_after_move(board, move).is_stalemate()


def _opening_overlay_position_id(board: chess.Board, side: str) -> str:
    ep = chess.square_name(board.ep_square) if board.ep_square is not None else "-"
    text = "|".join([
        board.board_fen(),
        "w" if board.turn == chess.WHITE else "b",
        board.castling_xfen() or "-",
        ep,
        str(side or "").strip().lower(),
    ])
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _opening_overlay_priority_move(board: chess.Board, side: str, model: dict) -> chess.Move | None:
    overlay = model.get("opening_overlay") if isinstance(model.get("opening_overlay"), dict) else {}
    if not overlay or not overlay.get("enabled", True):
        return None
    if board.is_check():
        return None
    try:
        max_fullmove = int(overlay.get("max_fullmove") or 12)
    except Exception:
        max_fullmove = 12
    if board.fullmove_number > max_fullmove:
        return None
    positions = overlay.get("positions") if isinstance(overlay.get("positions"), dict) else {}
    position_id = _opening_overlay_position_id(board, side)
    entry = positions.get(position_id)
    if not isinstance(entry, dict):
        return None
    ranked = []
    for index, item in enumerate(entry.get("moves") or []):
        if not isinstance(item, dict):
            continue
        try:
            move = chess.Move.from_uci(str(item.get("uci") or "").strip().lower())
        except Exception:
            continue
        if move not in board.legal_moves or _would_stalemate(board, move):
            continue
        ranked.append((float(item.get("weight") or 0.0), -index, move.uci(), move))
    if not ranked:
        return None
    return sorted(ranked, reverse=True)[0][3]


def _replay_prior_priority_move(board: chess.Board, side: str) -> chess.Move | None:
    if board.fullmove_number > _REPLAY_PRIOR_MAX_FULLMOVE:
        return None
    move_uci = _REPLAY_PRIOR_BY_POSITION.get((board.fen(), str(side or "").strip().lower()))
    if not move_uci:
        return None
    try:
        move = chess.Move.from_uci(move_uci)
    except Exception:
        return None
    if move not in board.legal_moves or _would_stalemate(board, move):
        return None
    return move


def _position_rule_key(board: chess.Board) -> str:
    return " ".join(board.fen().split()[:4])


def _opening_trap_priority_move(board: chess.Board, side: str) -> chess.Move | None:
    if board.fullmove_number > _TRAP_PRIOR_FULLMOVE_LIMIT:
        return None
    move_uci = _OPENING_TRAP_PRIOR_BY_POSITION.get((_position_rule_key(board), str(side or "").strip().lower()))
    if not move_uci:
        return None
    try:
        move = chess.Move.from_uci(move_uci)
    except Exception:
        return None
    if move not in board.legal_moves or _would_stalemate(board, move):
        return None
    return move


def _static_opening_book_priority_move(board: chess.Board, side: str) -> chess.Move | None:
    """Deterministic book fallback for exp5 opening play.

    The route-level opening book is intentionally random for variety. Exp5
    needs stable benchmark behavior, so it uses the same curated lines through
    deterministic weighted candidates and only adopts book moves that do not
    immediately lose to mate or stalemate.
    """
    if board.is_check() or board.fullmove_number > _STATIC_OPENING_BOOK_FULLMOVE_LIMIT:
        return None
    if str(side or "").strip().lower() not in {"white", "black"}:
        return None
    for item in book_candidates_for_chess_board(board, max_candidates=5):
        move = item.get("move")
        if not isinstance(move, chess.Move) or move not in board.legal_moves:
            continue
        if _would_stalemate(board, move):
            continue
        after = board.copy(stack=True)
        after.push(move)
        if after.is_checkmate():
            return move
        if _opponent_mate_in_one_moves(after):
            continue
        return move
    return None


def _avoid_stalemate_filter(board: chess.Board, move: chess.Move | None, *, score_move) -> chess.Move | None:
    if move is None or not _would_stalemate(board, move):
        return move
    alternatives = [candidate for candidate in board.legal_moves if not _would_stalemate(board, candidate)]
    if not alternatives:
        return move
    mates = []
    for candidate in alternatives:
        after = _legal_after_move(board, candidate)
        if after.is_checkmate():
            mates.append(candidate)
    if mates:
        return sorted(mates, key=lambda candidate: candidate.uci())[0]
    return sorted(alternatives, key=lambda candidate: (score_move(candidate), candidate.uci()), reverse=True)[0]


def _avoid_claimable_repetition_filter(board: chess.Board, move: chess.Move | None, *, score_move) -> chess.Move | None:
    if move is None:
        return None
    after = board.copy(stack=True)
    after.push(move)
    if after.is_checkmate() or not after.can_claim_threefold_repetition():
        return move
    # A claimable repetition is a legitimate draw resource. Do not reject it
    # unless the AI is clearly ahead and has a materially safe alternative.
    repeat_margin = _material_margin_for_color(after, board.turn)
    if repeat_margin < -250:
        return move
    repeat_score = float(score_move(move))
    if repeat_margin >= _REPETITION_PROGRESS_MARGIN_CP:
        allowed_score_drop = _REPETITION_PROGRESS_SCORE_DROP_CP
        allowed_material_drop = _REPETITION_PROGRESS_SAFE_DROP_CP
    else:
        allowed_score_drop = 150.0
        allowed_material_drop = 150
    alternatives = []
    for candidate in board.legal_moves:
        candidate_after = board.copy(stack=True)
        candidate_after.push(candidate)
        if candidate_after.is_checkmate():
            return candidate
        if candidate_after.can_claim_threefold_repetition():
            continue
        if _would_stalemate(board, candidate):
            continue
        if _material_margin_for_color(candidate_after, board.turn) < repeat_margin - allowed_material_drop:
            continue
        if repeat_margin >= _REPETITION_PROGRESS_MARGIN_CP:
            floor = _worst_immediate_reply_material_margin(candidate_after, board.turn)
            if floor < repeat_margin - allowed_material_drop:
                continue
            if _opponent_claimable_repetition_replies(candidate_after):
                continue
            if _opponent_mate_in_one_moves(candidate_after):
                continue
        if float(score_move(candidate)) < repeat_score - allowed_score_drop:
            continue
        alternatives.append(candidate)
    if not alternatives:
        return move
    return sorted(alternatives, key=lambda candidate: (score_move(candidate), candidate.uci()), reverse=True)[0]


def _claimable_draw_resource_filter(board: chess.Board, move: chess.Move | None, *, side: str, score_move) -> chess.Move | None:
    if move is None:
        return None
    color = chess.WHITE if str(side or "white").lower() == "white" else chess.BLACK
    if _material_margin_for_color(board, color) > -250:
        return move
    after_chosen = board.copy(stack=True)
    after_chosen.push(move)
    if after_chosen.is_checkmate() or after_chosen.can_claim_threefold_repetition():
        return move
    candidates = []
    for candidate in board.legal_moves:
        candidate_after = board.copy(stack=True)
        candidate_after.push(candidate)
        if candidate_after.can_claim_threefold_repetition():
            candidates.append(candidate)
    if not candidates:
        return move
    return sorted(candidates, key=lambda candidate: (score_move(candidate), candidate.uci()), reverse=True)[0]


def _avoid_reversible_cycle_when_ahead_filter(
    board: chess.Board,
    move: chess.Move | None,
    *,
    side: str,
    score_move,
) -> chess.Move | None:
    if move is None or len(board.move_stack) < 2:
        return move
    color = chess.WHITE if str(side or "white").lower() == "white" else chess.BLACK
    if _material_margin_for_color(board, color) < 300:
        return move
    own_previous = board.move_stack[-2]
    if not (
        own_previous.from_square == move.to_square
        and own_previous.to_square == move.from_square
        and move.promotion is None
        and not board.is_capture(move)
        and not board.gives_check(move)
    ):
        return move
    chosen_score = float(score_move(move))
    candidates: list[tuple[float, str, chess.Move]] = []
    for candidate in board.legal_moves:
        if candidate == move:
            continue
        if _would_stalemate(board, candidate):
            continue
        if (
            own_previous.from_square == candidate.to_square
            and own_previous.to_square == candidate.from_square
            and candidate.promotion is None
            and not board.is_capture(candidate)
            and not board.gives_check(candidate)
        ):
            continue
        after = board.copy(stack=True)
        after.push(candidate)
        if after.is_checkmate():
            return candidate
        if _opponent_mate_in_one_moves(after):
            continue
        if _material_margin_for_color(after, color) < _material_margin_for_color(board, color) - 180:
            continue
        score = float(score_move(candidate))
        if score >= chosen_score - 320.0:
            candidates.append((score, candidate.uci(), candidate))
    if not candidates:
        return move
    return sorted(candidates, reverse=True)[0][2]


def _opponent_claimable_repetition_replies(board: chess.Board) -> list[chess.Move]:
    replies: list[chess.Move] = []
    for reply in board.legal_moves:
        after_reply = board.copy(stack=True)
        after_reply.push(reply)
        if after_reply.can_claim_threefold_repetition():
            replies.append(reply)
    return replies


def _opponent_promotion_moves(board: chess.Board) -> list[chess.Move]:
    return [reply for reply in board.legal_moves if reply.promotion]


def _opponent_checking_promotion_moves(board: chess.Board) -> list[chess.Move]:
    return [reply for reply in _opponent_promotion_moves(board) if board.gives_check(reply)]


def _avoid_unanswered_immediate_promotion_filter(
    board: chess.Board,
    move: chess.Move | None,
    *,
    side: str,
    score_move,
) -> chess.Move | None:
    if move is None:
        return move
    color = chess.WHITE if str(side or "white").lower() == "white" else chess.BLACK
    chosen_after = board.copy(stack=True)
    chosen_after.push(move)
    if chosen_after.is_checkmate() or not _opponent_checking_promotion_moves(chosen_after):
        return move

    margin = _material_margin_for_color(board, color)
    chosen_score = float(score_move(move))
    candidates: list[tuple[float, int, str, chess.Move]] = []
    for candidate in board.legal_moves:
        if candidate == move or _would_stalemate(board, candidate):
            continue
        after = board.copy(stack=True)
        after.push(candidate)
        if after.is_checkmate():
            return candidate
        if _opponent_mate_in_one_moves(after):
            continue
        if _opponent_checking_promotion_moves(after):
            continue
        floor = _worst_immediate_reply_material_margin(after, color)
        if floor < margin - 360:
            continue
        score = float(score_move(candidate))
        if board.gives_check(candidate):
            score += 450.0
        if score < chosen_score - 900.0:
            continue
        candidates.append((score, floor, candidate.uci(), candidate))
    if not candidates:
        return move
    return sorted(candidates, reverse=True)[0][3]


def _avoid_enabling_opponent_repetition_when_ahead_filter(
    board: chess.Board,
    move: chess.Move | None,
    *,
    side: str,
    score_move,
) -> chess.Move | None:
    if move is None or len(board.move_stack) < 6:
        return move
    color = chess.WHITE if str(side or "white").lower() == "white" else chess.BLACK
    margin = _material_margin_for_color(board, color)
    if margin < 300:
        return move
    chosen_after = board.copy(stack=True)
    chosen_after.push(move)
    if chosen_after.is_checkmate():
        return move
    if not _opponent_claimable_repetition_replies(chosen_after):
        return move

    chosen_score = float(score_move(move))
    if margin >= _REPETITION_PROGRESS_MARGIN_CP:
        allowed_score_drop = _REPETITION_PROGRESS_SCORE_DROP_CP
        allowed_floor_drop = _REPETITION_PROGRESS_SAFE_DROP_CP
    else:
        allowed_score_drop = 900.0 if margin >= 900 else 550.0
        allowed_floor_drop = 320
    candidates: list[tuple[float, int, str, chess.Move]] = []
    for candidate in board.legal_moves:
        if candidate == move or _would_stalemate(board, candidate):
            continue
        after = board.copy(stack=True)
        after.push(candidate)
        if after.is_checkmate():
            return candidate
        if after.can_claim_threefold_repetition():
            continue
        if _opponent_claimable_repetition_replies(after):
            continue
        if _opponent_mate_in_one_moves(after):
            continue
        floor = _worst_immediate_reply_material_margin(after, color)
        if floor < margin - allowed_floor_drop:
            continue
        score = float(score_move(candidate))
        if score < chosen_score - allowed_score_drop:
            continue
        candidates.append((score, floor, candidate.uci(), candidate))
    if not candidates:
        return move
    return sorted(candidates, reverse=True)[0][3]


def _endgame_progress_filter(
    board: chess.Board,
    move: chess.Move | None,
    *,
    side: str,
    score_move,
) -> chess.Move | None:
    if move is None:
        return None
    color = chess.WHITE if str(side or "white").lower() == "white" else chess.BLACK
    if not _should_apply_endgame_progress(board, color):
        return move
    margin = _material_margin_for_color(board, color)
    chosen_score = float(score_move(move))
    chosen_progress = _endgame_move_progress_score(board, move, color)
    chosen_after = board.copy(stack=True)
    chosen_after.push(move)
    if chosen_after.is_checkmate():
        return move

    candidates: list[tuple[int, float, int, str, chess.Move]] = []
    for candidate in board.legal_moves:
        if candidate == move or _would_stalemate(board, candidate):
            continue
        after = board.copy(stack=True)
        after.push(candidate)
        if after.is_checkmate():
            return candidate
        if _opponent_mate_in_one_moves(after):
            continue
        if margin >= -250 and after.can_claim_threefold_repetition():
            continue
        floor = _worst_immediate_reply_material_margin(after, color)
        if floor < margin - _ENDGAME_PROGRESS_SAFE_DROP_CP:
            continue
        progress = _endgame_move_progress_score(board, candidate, color)
        if progress <= chosen_progress + 260:
            continue
        candidate_score = float(score_move(candidate))
        if candidate_score < chosen_score - _ENDGAME_PROGRESS_SCORE_DROP_CP:
            continue
        candidates.append((progress, candidate_score, floor, candidate.uci(), candidate))
    if not candidates:
        return move
    return sorted(candidates, reverse=True)[0][4]


def _bare_king_conversion_filter(
    board: chess.Board,
    move: chess.Move | None,
    *,
    side: str,
    score_move,
) -> chess.Move | None:
    if move is None:
        return None
    color = chess.WHITE if str(side or "white").lower() == "white" else chess.BLACK
    if not _is_bare_king_conversion(board, color) or board.is_check():
        return move
    after_move = board.copy(stack=True)
    after_move.push(move)
    if after_move.is_checkmate():
        return move

    enemy_king = board.king(not color)
    own_king = board.king(color)
    enemy_edge = _edge_distance(enemy_king)
    king_distance = _king_distance(own_king, enemy_king)

    def conversion_score(candidate: chess.Move) -> tuple[int, float, str, chess.Move]:
        after = board.copy(stack=True)
        after.push(candidate)
        if after.is_checkmate():
            return (100_000, float(score_move(candidate)), candidate.uci(), candidate)
        if after.is_stalemate():
            return (-100_000, float(score_move(candidate)), candidate.uci(), candidate)
        progress = _bare_king_mate_net_score(after, color)
        moving_piece = board.piece_at(candidate.from_square)
        if moving_piece is not None and moving_piece.piece_type in {chess.ROOK, chess.QUEEN}:
            if any(response.to_square == candidate.to_square and after.is_capture(response) for response in after.legal_moves):
                progress -= 20_000
        progress -= _recent_own_shuffle_penalty(board, candidate) * 2
        if after.can_claim_threefold_repetition():
            progress -= 3_000
        if board.gives_check(candidate) and enemy_edge > 1 and king_distance > 2:
            progress -= 900
        return (progress, float(score_move(candidate)), candidate.uci(), candidate)

    candidates = [
        conversion_score(candidate)
        for candidate in board.legal_moves
        if not _would_stalemate(board, candidate)
    ]
    if not candidates:
        return move
    best_progress, _best_score, _best_uci, best_move = sorted(candidates, reverse=True)[0]
    current_progress = conversion_score(move)[0]
    if best_move == move:
        return move
    if best_progress >= current_progress + 120:
        return best_move
    if board.gives_check(move) and enemy_edge > 1 and king_distance > 2 and best_progress >= current_progress - 80:
        return best_move
    return move


def _avoid_non_progress_shuffle_when_ahead_filter(
    board: chess.Board,
    move: chess.Move | None,
    *,
    side: str,
    score_move,
) -> chess.Move | None:
    if move is None or len(board.move_stack) < 2:
        return move
    color = chess.WHITE if str(side or "white").lower() == "white" else chess.BLACK
    margin = _material_margin_for_color(board, color)
    conversion_like = _should_apply_endgame_progress(board, color)
    if margin < _REPETITION_PROGRESS_MARGIN_CP and not conversion_like:
        return move
    chosen_penalty = _recent_own_shuffle_penalty(board, move)
    if chosen_penalty <= 0:
        return move
    chosen_score = float(score_move(move))
    chosen_progress = _endgame_move_progress_score(board, move, color)
    allowed_drop = _ENDGAME_PROGRESS_SCORE_DROP_CP if conversion_like else 900.0
    candidates: list[tuple[int, float, int, str, chess.Move]] = []
    for candidate in board.legal_moves:
        if candidate == move or _would_stalemate(board, candidate):
            continue
        penalty = _recent_own_shuffle_penalty(board, candidate)
        if penalty >= chosen_penalty:
            continue
        after = board.copy(stack=True)
        after.push(candidate)
        if after.is_checkmate():
            return candidate
        if after.can_claim_threefold_repetition():
            continue
        if _opponent_claimable_repetition_replies(after):
            continue
        if _opponent_mate_in_one_moves(after):
            continue
        floor = _worst_immediate_reply_material_margin(after, color)
        if floor < margin - _ENDGAME_PROGRESS_SAFE_DROP_CP:
            continue
        progress = _endgame_move_progress_score(board, candidate, color)
        if progress < chosen_progress - 120:
            continue
        candidate_score = float(score_move(candidate))
        if candidate_score < chosen_score - allowed_drop:
            continue
        candidates.append((progress - penalty, candidate_score, floor, candidate.uci(), candidate))
    if not candidates:
        return move
    return sorted(candidates, reverse=True)[0][4]


def _advanced_pawn_push_score(board: chess.Board, move: chess.Move, color: chess.Color) -> int:
    piece = board.piece_at(move.from_square)
    if piece is None or piece.color != color or piece.piece_type != chess.PAWN:
        return 0
    if board.is_capture(move) or move.promotion:
        return 0
    before_rank = chess.square_rank(move.from_square)
    after_rank = chess.square_rank(move.to_square)
    if color == chess.WHITE:
        if after_rank <= before_rank or before_rank < 4:
            return 0
        distance = 7 - after_rank
    else:
        if after_rank >= before_rank or before_rank > 3:
            return 0
        distance = after_rank
    score = max(0, 6 - distance) * 260
    if distance <= 2:
        score += 620
    if _is_passed_pawn(board, move.from_square, color):
        score += 520
    after = board.copy(stack=False)
    after.push(move)
    if _is_passed_pawn(after, move.to_square, color):
        score += 620
    return score


def _avoid_shuffle_with_advanced_pawn_push_filter(
    board: chess.Board,
    move: chess.Move | None,
    *,
    side: str,
    score_move,
) -> chess.Move | None:
    if move is None or len(board.move_stack) < 2:
        return move
    chosen_penalty = _recent_own_shuffle_penalty(board, move)
    if chosen_penalty <= 0:
        return move
    color = chess.WHITE if str(side or "white").lower() == "white" else chess.BLACK
    margin = _material_margin_for_color(board, color)
    chosen_score = float(score_move(move))
    candidates: list[tuple[int, float, int, str, chess.Move]] = []
    for candidate in board.legal_moves:
        push_score = _advanced_pawn_push_score(board, candidate, color)
        if push_score <= 0 or _would_stalemate(board, candidate):
            continue
        after = board.copy(stack=True)
        after.push(candidate)
        if after.is_checkmate():
            return candidate
        if _opponent_mate_in_one_moves(after):
            continue
        floor = _worst_immediate_reply_material_margin(after, color)
        if floor < margin - 420:
            continue
        candidate_score = float(score_move(candidate))
        if candidate_score < chosen_score - 900.0:
            continue
        candidates.append((push_score, candidate_score, floor, candidate.uci(), candidate))
    if not candidates:
        return move
    return sorted(candidates, reverse=True)[0][4]


def _opponent_mate_in_one_moves(board: chess.Board) -> list[chess.Move]:
    mates: list[chess.Move] = []
    for reply in board.legal_moves:
        after = board.copy(stack=False)
        after.push(reply)
        if after.is_checkmate():
            mates.append(reply)
    return mates


def _forced_single_reply_mate_net_move(board: chess.Board) -> chess.Move | None:
    """Find a checking move where the only legal reply allows mate in one."""
    if board.legal_moves.count() > 90:
        return None
    candidates: list[tuple[int, int, str, chess.Move]] = []
    for move in board.legal_moves:
        if not board.gives_check(move) or _would_stalemate(board, move):
            continue
        after = board.copy(stack=False)
        after.push(move)
        if after.is_checkmate() or after.is_stalemate():
            continue
        replies = list(after.legal_moves)
        if len(replies) != 1:
            continue
        reply_board = after.copy(stack=False)
        reply_board.push(replies[0])
        mate_replies = _opponent_mate_in_one_moves(reply_board)
        if not mate_replies:
            continue
        candidates.append((
            _move_order_score(board, move),
            _captured_piece_value(board, move),
            move.uci(),
            move,
        ))
    if not candidates:
        return None
    return sorted(candidates, reverse=True)[0][3]


def _forced_mate_in_two_priority_move(
    board: chess.Board,
    *,
    max_pieces: int = _MATE_IN_TWO_MAX_PIECES,
    max_legal_moves: int = _MATE_IN_TWO_MAX_LEGAL_MOVES,
    max_replies: int = _MATE_IN_TWO_MAX_REPLIES,
    min_material_margin_cp: int = 0,
) -> chess.Move | None:
    """Find a conservative forced mate-in-two move in simplified positions.

    This is deliberately bounded to low-material or otherwise small legal-move
    spaces. Exp5's default live profile is shallow, so this fills an important
    human-visible gap in simple endgames without adding a broad expensive
    tactical solver to every middlegame move.
    """
    if len(board.piece_map()) > int(max_pieces or _MATE_IN_TWO_MAX_PIECES):
        return None
    if int(min_material_margin_cp or 0) > 0 and _material_margin_for_color(board, board.turn) < int(min_material_margin_cp):
        return None
    legal_moves = sorted(board.legal_moves, key=lambda item: item.uci())
    if not legal_moves or len(legal_moves) > int(max_legal_moves or _MATE_IN_TWO_MAX_LEGAL_MOVES):
        return None

    candidates: list[chess.Move] = []
    for move in legal_moves:
        after = board.copy(stack=False)
        after.push(move)
        if after.is_checkmate() or after.is_stalemate():
            continue
        replies = list(after.legal_moves)
        if not replies or len(replies) > int(max_replies or _MATE_IN_TWO_MAX_REPLIES):
            continue
        forced = True
        for reply in replies:
            reply_board = after.copy(stack=False)
            reply_board.push(reply)
            if not _opponent_mate_in_one_moves(reply_board):
                forced = False
                break
        if forced:
            candidates.append(move)
    if not candidates:
        return None
    return sorted(
        candidates,
        key=lambda move: (
            board.gives_check(move),
            _move_order_score(board, move),
            _captured_piece_value(board, move),
            move.uci(),
        ),
        reverse=True,
    )[0]


def _forced_checking_mate_priority_move(
    board: chess.Board,
    *,
    max_depth_plies: int = 7,
    max_pieces: int = 18,
    max_legal_moves: int = 70,
    min_material_margin_cp: int = 700,
    max_nodes: int = 30_000,
    max_root_checks: int = 5,
) -> chess.Move | None:
    """Find a bounded checking sequence that forces mate.

    This is a tail/endgame helper, not a full tactical search. It only considers
    checking attacker moves, then requires every defender reply to remain inside
    the forced mate tree. That keeps the search small and avoids changing quiet
    middlegame choices.
    """
    if len(board.piece_map()) > int(max_pieces or 18):
        return None
    legal_count = board.legal_moves.count()
    if legal_count <= 0 or legal_count > int(max_legal_moves or 70):
        return None
    if _material_margin_for_color(board, board.turn) < int(min_material_margin_cp or 0):
        return None

    attacker = board.turn
    max_depth_plies = max(1, int(max_depth_plies or 1))
    max_nodes = max(1000, int(max_nodes or 30_000))
    nodes = 0
    memo: dict[tuple[str, int, bool], bool] = {}

    def checking_moves(current: chess.Board) -> list[chess.Move]:
        moves = [move for move in current.legal_moves if current.gives_check(move)]
        return sorted(
            moves,
            key=lambda move: (
                current.is_capture(move),
                bool(move.promotion),
                _promotion_priority(move),
                _captured_piece_value(current, move),
                _move_order_score(current, move),
                move.uci(),
            ),
            reverse=True,
        )

    def can_force(current: chess.Board, depth: int) -> bool:
        nonlocal nodes
        nodes += 1
        if nodes > max_nodes:
            return False
        if current.is_checkmate():
            return current.turn != attacker
        if current.is_stalemate() or depth <= 0:
            return False
        key = (current.fen(), depth, current.turn)
        cached = memo.get(key)
        if cached is not None:
            return cached
        if current.turn == attacker:
            for move in checking_moves(current):
                current.push(move)
                ok = can_force(current, depth - 1)
                current.pop()
                if ok:
                    memo[key] = True
                    return True
            memo[key] = False
            return False

        replies = list(current.legal_moves)
        if not replies or len(replies) > int(max_legal_moves or 70):
            memo[key] = False
            return False
        for reply in replies:
            current.push(reply)
            ok = can_force(current, depth - 1)
            current.pop()
            if not ok:
                memo[key] = False
                return False
        memo[key] = True
        return True

    root_checks = checking_moves(board)
    if not root_checks or len(root_checks) > int(max_root_checks or 5):
        return None
    candidates: list[chess.Move] = []
    for move in root_checks:
        board.push(move)
        ok = can_force(board, max_depth_plies - 1)
        board.pop()
        if ok:
            candidates.append(move)
    if not candidates:
        return None
    return sorted(
        candidates,
        key=lambda move: (
            board.is_capture(move),
            bool(move.promotion),
            _promotion_priority(move),
            _captured_piece_value(board, move),
            _move_order_score(board, move),
            move.uci(),
        ),
        reverse=True,
    )[0]


def _has_bounded_opponent_forced_mate(
    board: chess.Board,
    *,
    max_depth_plies: int,
    max_pieces: int,
    max_nodes: int,
) -> bool:
    return (
        _forced_checking_mate_priority_move(
            board,
            max_depth_plies=max_depth_plies,
            max_pieces=max_pieces,
            max_legal_moves=70,
            min_material_margin_cp=-3000,
            max_nodes=max_nodes,
            max_root_checks=6,
        )
        is not None
    )


def _avoid_opponent_forced_mate_net_filter(
    board: chess.Board,
    move: chess.Move | None,
    *,
    side: str,
    score_move,
    max_depth_plies: int = 7,
    max_pieces: int = 30,
    max_nodes: int = 12_000,
    scan_limit: int = 16,
) -> chess.Move | None:
    """Avoid candidate moves that allow a bounded checking forced mate.

    This is deliberately narrower than a general tactical solver: it first
    tests only the already selected move. Alternative scanning happens only if
    that move fails the bounded mate-net check.
    """
    if move is None:
        return None
    if len(board.piece_map()) > int(max_pieces or 30) or board.legal_moves.count() > 70:
        return move
    color = chess.WHITE if str(side or "white").lower() == "white" else chess.BLACK
    after = board.copy(stack=False)
    after.push(move)
    if after.is_checkmate() or after.is_stalemate():
        return move
    if not _has_bounded_opponent_forced_mate(
        after,
        max_depth_plies=max_depth_plies,
        max_pieces=max_pieces,
        max_nodes=max_nodes,
    ):
        return move

    chosen_score = float(score_move(move))
    candidates: list[tuple[float, int, str, chess.Move]] = []
    ordered = sorted(
        [candidate for candidate in board.legal_moves if candidate != move],
        key=lambda candidate: (float(score_move(candidate)), candidate.uci()),
        reverse=True,
    )[: max(1, int(scan_limit or 16))]
    for candidate in ordered:
        if _would_stalemate(board, candidate):
            continue
        candidate_after = board.copy(stack=False)
        candidate_after.push(candidate)
        if candidate_after.is_checkmate():
            return candidate
        if _opponent_mate_in_one_moves(candidate_after):
            continue
        if _has_bounded_opponent_forced_mate(
            candidate_after,
            max_depth_plies=max_depth_plies,
            max_pieces=max_pieces,
            max_nodes=max_nodes,
        ):
            continue
        floor = _worst_immediate_reply_material_margin(candidate_after, color)
        candidate_score = float(score_move(candidate))
        if candidate_score < chosen_score - 1800.0 and floor < _material_margin_for_color(board, color) - 900:
            continue
        candidates.append((candidate_score, floor, candidate.uci(), candidate))
    if not candidates:
        return move
    return sorted(candidates, reverse=True)[0][3]


def _low_legal_check_escape_filter(
    board: chess.Board,
    move: chess.Move | None,
    *,
    side: str,
    score_move,
    max_legal: int = 4,
    max_pieces: int = 30,
    max_depth_plies: int = 7,
    max_nodes: int = 12_000,
    enable_king_mobility4: bool = False,
) -> chess.Move | None:
    """Final narrow guard for low-legal check evasions.

    Earlier post-search filters may replace a safe search result. This guard
    only runs in check with very few legal moves, where scanning every evasion
    is cheap and avoids obvious forced-mate funnels.
    """
    if move is None or not board.is_check():
        return move
    legal_moves = list(board.legal_moves)
    if len(legal_moves) <= 1 or len(legal_moves) > int(max_legal or 4):
        return move
    if len(board.piece_map()) > int(max_pieces or 30):
        return move
    color = chess.WHITE if str(side or "white").lower() == "white" else chess.BLACK

    def king_edge_distance(after: chess.Board) -> int:
        square = after.king(color)
        if square is None:
            return 0
        file_index = chess.square_file(square)
        rank_index = chess.square_rank(square)
        return min(file_index, 7 - file_index, rank_index, 7 - rank_index)

    risk_cache: dict[str, tuple[bool, bool]] = {}
    depth_limit = max(0, int(max_depth_plies if max_depth_plies is not None else 7))
    node_limit = max(0, int(max_nodes if max_nodes is not None else 12_000))

    def candidate_risk(candidate: chess.Move) -> tuple[bool, bool]:
        uci = candidate.uci()
        cached = risk_cache.get(uci)
        if cached is not None:
            return cached
        after = board.copy(stack=False)
        after.push(candidate)
        mate_in_one = not after.is_checkmate() and bool(_opponent_mate_in_one_moves(after))
        forced_mate = False
        if not mate_in_one and depth_limit > 0 and node_limit > 0:
            forced_mate = _has_bounded_opponent_forced_mate(
                after,
                max_depth_plies=depth_limit,
                max_pieces=int(max_pieces or 30),
                max_nodes=node_limit,
            )
        risk_cache[uci] = (mate_in_one, forced_mate)
        return risk_cache[uci]

    def candidate_tuple(candidate: chess.Move) -> tuple[int, float, str, chess.Move]:
        after = board.copy(stack=False)
        after.push(candidate)
        if after.is_checkmate():
            return (10_000_000, float(score_move(candidate)), candidate.uci(), candidate)
        mate_in_one, forced_mate = candidate_risk(candidate)
        moving_piece = board.piece_at(candidate.from_square)
        is_king_move = bool(moving_piece and moving_piece.piece_type == chess.KING)
        opponent_check_count = sum(1 for reply in after.legal_moves if after.gives_check(reply))
        score = 0
        if mate_in_one:
            score -= 1_000_000
        if forced_mate:
            score -= 250_000
        score += king_edge_distance(after) * 900
        score -= opponent_check_count * 35
        if is_king_move and king_edge_distance(after) == 0:
            score -= 700
        if not is_king_move:
            score += 450
        if board.is_capture(candidate):
            score += min(900, _captured_piece_value(board, candidate))
        if candidate.promotion:
            score += 1200
        score += int(max(-5000.0, min(5000.0, float(score_move(candidate)))))
        return (score, float(score_move(candidate)), candidate.uci(), candidate)

    chosen_mate_in_one, chosen_forced_mate = candidate_risk(move)
    if not chosen_mate_in_one and not chosen_forced_mate:
        if not bool(enable_king_mobility4) or len(legal_moves) != 4:
            return move
        chosen_piece = board.piece_at(move.from_square)
        if not chosen_piece or chosen_piece.piece_type != chess.KING:
            return move
        chosen_after = board.copy(stack=False)
        chosen_after.push(move)
        if king_edge_distance(chosen_after) != 0:
            return move
        chosen_score = candidate_tuple(move)[0]
        king_candidates: list[tuple[int, float, str, chess.Move]] = []
        for candidate in legal_moves:
            if candidate == move:
                continue
            moving_piece = board.piece_at(candidate.from_square)
            if not moving_piece or moving_piece.piece_type != chess.KING:
                continue
            after = board.copy(stack=False)
            after.push(candidate)
            if king_edge_distance(after) <= 0:
                continue
            mate_in_one, forced_mate = candidate_risk(candidate)
            if mate_in_one or forced_mate:
                continue
            score = candidate_tuple(candidate)[0]
            king_candidates.append((score, float(score_move(candidate)), candidate.uci(), candidate))
        if not king_candidates:
            return move
        best_king = sorted(king_candidates, reverse=True)[0]
        if best_king[0] <= chosen_score + 250:
            return move
        return best_king[3]

    chosen = candidate_tuple(move)
    chosen_score = chosen[0]
    candidates = [candidate_tuple(candidate) for candidate in legal_moves]
    best = sorted(candidates, reverse=True)[0]
    if best[3] == move:
        return move
    if best[0] <= chosen_score + 650:
        return move
    return best[3]


def _avoid_allowing_mate_in_one_filter(board: chess.Board, move: chess.Move | None, *, score_move) -> chess.Move | None:
    if move is None:
        return None
    after = board.copy(stack=False)
    after.push(move)
    if after.is_checkmate() or not _opponent_mate_in_one_moves(after):
        return move
    alternatives: list[chess.Move] = []
    for candidate in board.legal_moves:
        candidate_after = board.copy(stack=False)
        candidate_after.push(candidate)
        if candidate_after.is_checkmate():
            return candidate
        if _would_stalemate(board, candidate):
            continue
        if _opponent_mate_in_one_moves(candidate_after):
            continue
        alternatives.append(candidate)
    if not alternatives:
        return move
    return sorted(alternatives, key=lambda candidate: (score_move(candidate), candidate.uci()), reverse=True)[0]


def _avoid_immediate_material_drop_filter(
    board: chess.Board,
    move: chess.Move | None,
    *,
    side: str,
    score_move,
    compensation_fn=None,
) -> chess.Move | None:
    if move is None:
        return None
    chosen_after = board.copy(stack=False)
    chosen_after.push(move)
    if chosen_after.is_checkmate():
        return move
    color = chess.WHITE if str(side or "white").lower() == "white" else chess.BLACK
    chosen_floor = _worst_immediate_reply_material_margin(chosen_after, color)
    if board.fullmove_number <= _OPENING_DEVELOPMENT_FULLMOVE_LIMIT:
        chosen_floor -= _opponent_knight_fork_danger(chosen_after, color)

    candidates: list[tuple[int, float, str, chess.Move]] = []
    best_floor = chosen_floor
    for candidate in board.legal_moves:
        if _would_stalemate(board, candidate):
            continue
        after = board.copy(stack=False)
        after.push(candidate)
        if after.is_checkmate():
            return candidate
        if _opponent_mate_in_one_moves(after):
            continue
        floor = _worst_immediate_reply_material_margin(after, color)
        if board.fullmove_number <= _OPENING_DEVELOPMENT_FULLMOVE_LIMIT:
            floor -= _opponent_knight_fork_danger(after, color)
        best_floor = max(best_floor, floor)
        candidates.append((floor, float(score_move(candidate)), candidate.uci(), candidate))
    required_floor_gain = 180 if board.fullmove_number <= _OPENING_DEVELOPMENT_FULLMOVE_LIMIT else _PIECE_VALUES[chess.KNIGHT]
    if best_floor - chosen_floor < required_floor_gain:
        return move
    safer = [item for item in candidates if item[0] >= best_floor - 80]
    if not safer:
        return move
    if compensation_fn is not None:
        try:
            compensation = float(compensation_fn(move))
        except Exception:
            compensation = 0.0
        if compensation >= 1200.0 and best_floor - chosen_floor <= 380:
            return move
    return sorted(safer, reverse=True)[0][3]


def _conversion_check_evasion_filter(
    board: chess.Board,
    move: chess.Move | None,
    *,
    side: str,
    score_move,
) -> chess.Move | None:
    if move is None or not board.is_check():
        return move
    color = chess.WHITE if str(side or "white").lower() == "white" else chess.BLACK
    if not _is_conversion_phase(board, color):
        return move
    piece = board.piece_at(move.from_square)
    if piece is None or piece.piece_type != chess.KING:
        return move

    chosen_score = float(score_move(move))
    candidates: list[tuple[float, str, chess.Move]] = []
    for candidate in board.legal_moves:
        candidate_piece = board.piece_at(candidate.from_square)
        if candidate_piece is None or candidate_piece.piece_type != chess.KING:
            continue
        if _would_stalemate(board, candidate):
            continue
        after = board.copy(stack=True)
        after.push(candidate)
        if after.is_checkmate() or _opponent_mate_in_one_moves(after):
            continue
        opponent_claim_replies = 0
        opponent_check_replies = 0
        for reply in after.legal_moves:
            reply_board = after.copy(stack=True)
            reply_board.push(reply)
            if reply_board.can_claim_threefold_repetition():
                opponent_claim_replies += 1
            if after.gives_check(reply):
                opponent_check_replies += 1
        score = float(score_move(candidate))
        score -= opponent_claim_replies * 220.0
        score -= opponent_check_replies * 18.0
        candidates.append((score, candidate.uci(), candidate))
    if not candidates:
        return move
    best_score, _best_uci, best_move = sorted(candidates, reverse=True)[0]
    if best_move == move:
        return move
    # Only override alpha-beta when the conversion-aware score strongly prefers
    # another king escape. This keeps ordinary tactical check evasions intact.
    if best_score >= chosen_score + 140.0:
        return best_move
    return move


def _special_rule_priority_move(board: chess.Board, *, allow_queenside_castle: bool = True) -> chess.Move | None:
    """Conservative rule/tactic priority before the shallow NNUE/PVS search.

    The NNUE-like eval is intentionally small, so depth-limited search can miss
    rule-specific forcing moves that are obvious to humans: promotion, legal
    en-passant, and high-value captures. This helper only preempts search for
    clear, legal, non-stalemating moves; normal positional choices still go
    through alpha-beta/PVS.
    """
    legal_moves = sorted(board.legal_moves, key=lambda item: item.uci())
    if not legal_moves:
        return None

    def priority_safe(move: chess.Move) -> bool:
        if _would_stalemate(board, move):
            return False
        after = _legal_after_move(board, move)
        if after.is_checkmate():
            return True
        return not _opponent_mate_in_one_moves(after)

    promotions = [move for move in legal_moves if move.promotion and priority_safe(move)]
    if promotions:
        return sorted(
            promotions,
            key=lambda move: (
                _legal_after_move(board, move).is_checkmate(),
                move.promotion == chess.QUEEN,
                _promotion_priority(move),
                board.gives_check(move),
                _captured_piece_value(board, move),
                -ord(move.uci()[0]),
            ),
            reverse=True,
        )[0]

    en_passant = [move for move in legal_moves if board.is_en_passant(move) and priority_safe(move)]
    if en_passant:
        return en_passant[0]

    material_captures = [
        move
        for move in legal_moves
        if (
            board.is_capture(move)
            and _captured_piece_value(board, move) >= _PIECE_VALUES[chess.KNIGHT]
            and priority_safe(move)
        )
    ]
    safe_material_captures = [
        move
        for move in material_captures
        if tactical_safety_report(
            board,
            move,
            max_direct_loss_cp=120,
            compensation_window_cp=60,
        ).get("safe")
        and _static_exchange_eval(board, move) >= -120
    ]
    if safe_material_captures:
        return sorted(
            safe_material_captures,
            key=lambda move: (
                _captured_piece_value(board, move),
                board.gives_check(move),
                -_PIECE_VALUES.get((board.piece_at(move.from_square) or chess.Piece(chess.PAWN, board.turn)).piece_type, 0),
                move.uci(),
            ),
            reverse=True,
        )[0]

    dangerous_pawn_captures = [
        move
        for move in legal_moves
        if (
            board.is_capture(move)
            and _captured_pawn_promotion_danger(board, move) >= 2
            and priority_safe(move)
            and tactical_safety_report(
                board,
                move,
                max_direct_loss_cp=120,
                compensation_window_cp=60,
            ).get("safe")
            and _static_exchange_eval(board, move) >= -120
        )
    ]
    if dangerous_pawn_captures:
        return sorted(
            dangerous_pawn_captures,
            key=lambda move: (
                _captured_pawn_promotion_danger(board, move),
                board.gives_check(move),
                -_PIECE_VALUES.get((board.piece_at(move.from_square) or chess.Piece(chess.PAWN, board.turn)).piece_type, 0),
                move.uci(),
            ),
            reverse=True,
        )[0]

    castles = [move for move in legal_moves if board.is_castling(move) and priority_safe(move)]
    if castles and board.fullmove_number <= 12 and not board.is_check():
        kingside = [move for move in castles if chess.square_file(move.to_square) > chess.square_file(move.from_square)]
        if kingside:
            return sorted(kingside, key=lambda item: item.uci())[0]
        if allow_queenside_castle:
            return sorted(castles, key=lambda item: item.uci())[0]

    return None


def _special_rule_fusion_bonus(board: chess.Board, move: chess.Move) -> int:
    bonus = 0
    if move.promotion:
        bonus += 3600 + _promotion_priority(move) * 260
        if board.gives_check(move):
            bonus += 450
        if _captured_piece_value(board, move):
            bonus += _captured_piece_value(board, move)
    if board.is_en_passant(move):
        bonus += 700
        if _static_exchange_eval(board, move) < -120:
            bonus -= 1200
    if board.is_castling(move):
        bonus += 1100
        if board.fullmove_number <= _OPENING_DEVELOPMENT_FULLMOVE_LIMIT:
            bonus += 850
    return bonus


def _is_special_rule_move(board: chess.Board, move: chess.Move) -> bool:
    return bool(move.promotion or board.is_en_passant(move) or board.is_castling(move))


def _special_rule_fusion_filter(
    board: chess.Board,
    move: chess.Move | None,
    *,
    score_move,
) -> chess.Move | None:
    """Let rare rule-aware moves win close final decisions.

    This is intentionally a final fusion step, not a blanket override. It only
    considers legal special-rule candidates whose raw score is already near
    the top of the current policy surface, then adds a small deterministic
    bonus so castling/en-passant/promotion are not lost to ordinary quiet moves
    with similar shallow eval scores.
    """
    if move is None:
        return None
    current_score = float(score_move(move))
    scored: list[tuple[float, str, chess.Move]] = []
    for candidate in board.legal_moves:
        if _would_stalemate(board, candidate):
            continue
        base_score = float(score_move(candidate))
        scored.append((base_score, candidate.uci(), candidate))
    if not scored:
        return move
    ranked = sorted(scored, key=lambda item: (-item[0], item[1]))
    rank_by_uci = {candidate.uci(): index for index, (_score, _uci, candidate) in enumerate(ranked, start=1)}
    candidates: list[tuple[float, float, str, chess.Move]] = []
    for base_score, uci, candidate in ranked:
        if not _is_special_rule_move(board, candidate):
            continue
        if int(rank_by_uci.get(uci) or 9999) > _SPECIAL_RULE_FUSION_RANK_LIMIT:
            continue
        if base_score < current_score - _SPECIAL_RULE_FUSION_SCORE_DROP_CP:
            continue
        after = board.copy(stack=True)
        after.push(candidate)
        if after.is_checkmate():
            return candidate
        if _opponent_mate_in_one_moves(after):
            continue
        candidates.append((base_score + _special_rule_fusion_bonus(board, candidate), base_score, uci, candidate))
    if not candidates:
        return move
    best_fused, best_base, _uci, best_move = sorted(candidates, reverse=True)[0]
    current_fused = current_score + (_special_rule_fusion_bonus(board, move) if _is_special_rule_move(board, move) else 0)
    if best_move != move and best_fused < current_fused + 80.0 and best_base < current_score + 20.0:
        return move
    return best_move


def _move_dict(board: chess.Board, move: chess.Move) -> dict:
    piece = board.piece_at(move.from_square)
    captured = _captured_piece(board, move)
    return {
        "from": chess.square_name(move.from_square),
        "to": chess.square_name(move.to_square),
        "piece": piece.symbol() if piece else "",
        "captured": captured.symbol() if captured else None,
        "promotion": chess.piece_symbol(move.promotion) if move.promotion else None,
        "castle": bool(board.is_castling(move)),
        "en_passant": bool(board.is_en_passant(move)),
    }


def _score_move_for_side(board: chess.Board, move: chess.Move, side: str, model: dict, eval_cache: dict[int, int], hasher: ZobristHasher) -> float:
    after = board.copy(stack=False)
    after.push(move)
    color = chess.WHITE if str(side or "white").lower() == "white" else chess.BLACK
    side_sign = 1.0 if color == chess.WHITE else -1.0
    score = side_sign * float(_nnue_eval(after, model, eval_cache, hasher))
    score += float(_move_order_score(board, move))
    score += float(_opening_development_bonus(board, move))
    if bool(model.get("_enable_center_break")):
        score += float(_center_break_move_bonus(board, move))
    if bool(model.get("_enable_fianchetto_development")):
        score += float(_fianchetto_development_move_bonus(board, move))
    if _should_apply_endgame_progress(board, color):
        score += float(_endgame_move_progress_score(board, move, color))
    if bool(model.get("_enable_v26_long_tail_ordering")):
        score += float(_v26_long_tail_move_bonus(board, move, color))
    return score


def _exp5_qmove_filter(board: chess.Board, move: chess.Move) -> bool:
    if move.promotion:
        return True
    if board.gives_check(move):
        return True
    if not board.is_capture(move):
        return False
    captured = _captured_piece_value(board, move)
    if captured >= _PIECE_VALUES[chess.KNIGHT]:
        return True
    return _static_exchange_eval(board, move) >= 0


def _exp5_search_extension(board: chess.Board, move: chess.Move, ply: int, depth: int) -> int:
    if depth <= 0:
        return 0
    if board.gives_check(move):
        return 1
    if move.promotion:
        return 1
    if board.is_capture(move):
        if _captured_piece_value(board, move) >= _PIECE_VALUES[chess.ROOK]:
            return 1
        if board.move_stack:
            previous = board.peek()
            if move.to_square == previous.to_square and _static_exchange_eval(board, move) >= -80:
                return 1
    return 0


def rank_experiment_nnue_policy_moves(board_state, side: str, *, model_path=None, search_profile="fast") -> list[dict]:
    board = _to_nnue_board(board_state, side)
    ai_color = chess.WHITE if side == "white" else chess.BLACK
    if board.turn != ai_color:
        board.turn = ai_color
    if board.is_game_over():
        return []
    model = _load_model(Path(model_path or default_chess_nnue_model_path()))
    hasher = ZobristHasher(seed=20260530)
    eval_cache: dict[int, int] = {}
    rows = []
    for move in sorted(board.legal_moves, key=lambda item: item.uci()):
        score = _score_move_for_side(board, move, side, model, eval_cache, hasher)
        rows.append({"move": move.uci(), "raw_policy_score": round(float(score), 8)})
    if not rows:
        return []
    max_score = max(float(row["raw_policy_score"]) for row in rows)
    denom = sum(pow(2.718281828459045, (float(row["raw_policy_score"]) - max_score) / 400.0) for row in rows)
    ranked = sorted(rows, key=lambda row: (-float(row["raw_policy_score"]), str(row["move"])))
    rank = {str(row["move"]): index for index, row in enumerate(ranked, start=1)}
    for row in rows:
        row["policy_probability"] = (
            round(pow(2.718281828459045, (float(row["raw_policy_score"]) - max_score) / 400.0) / denom, 8)
            if denom
            else 0.0
        )
        row["raw_policy_rank"] = rank[str(row["move"])]
        row["move_order_score"] = int(round(float(row["raw_policy_score"])))
        row["move_order_rank"] = row["raw_policy_rank"]
        row["legal_move_bonus_penalty"] = 0
    return sorted(rows, key=lambda row: (int(row["raw_policy_rank"]), str(row["move"])))


def explain_experiment_nnue_decision(
    board_state,
    side: str,
    *,
    model_path=None,
    search_profile="fast",
    watched_moves: list[str] | None = None,
    **_kwargs,
) -> dict:
    rows = rank_experiment_nnue_policy_moves(board_state, side, model_path=model_path, search_profile=search_profile)
    move = choose_experiment_nnue_move(board_state, side, model_path=model_path, search_profile=search_profile)
    chosen = f"{move['from']}{move['to']}{move.get('promotion') or ''}".lower() if move else ""
    watched = {str(item or "").strip().lower() for item in (watched_moves or []) if str(item or "").strip()}
    return {
        "supported": True,
        "engine": EXPERIMENT_NNUE_DIFFICULTY,
        "architecture": "nnue-like-sparse-accumulator-v1",
        "search_profile": str(search_profile or "fast"),
        "chosen_move": chosen,
        "chosen_reason": "alpha_beta_with_nnue_like_sparse_eval",
        "chosen_breakdown": next((row for row in rows if str(row.get("move") or "") == chosen), {}),
        "top_final_moves": rows[:5],
        "watched_moves": [row for row in rows if str(row.get("move") or "") in watched],
    }


def _move_payload_to_chess_move(board: chess.Board, payload: dict | None) -> chess.Move | None:
    if not isinstance(payload, dict):
        return None
    uci = f"{payload.get('from') or ''}{payload.get('to') or ''}{payload.get('promotion') or ''}".lower()
    try:
        move = chess.Move.from_uci(uci)
    except Exception:
        return None
    return move if move in board.legal_moves else None


def _legal_uci_list(board: chess.Board, raw_moves) -> list[str]:
    moves: list[str] = []
    seen: set[str] = set()
    for item in raw_moves or []:
        if isinstance(item, dict):
            text = str(item.get("move") or item.get("uci") or "").strip().lower()
        else:
            text = str(item or "").strip().lower()
        try:
            move = chess.Move.from_uci(text)
        except Exception:
            continue
        if move not in board.legal_moves or move.uci() in seen:
            continue
        seen.add(move.uci())
        moves.append(move.uci())
    return moves


def _adapter_cache_key(path: Path) -> str:
    try:
        stat = path.stat()
    except OSError:
        return f"{path}|missing"
    return f"{path}|{stat.st_mtime_ns}|{stat.st_size}"


def _load_adapter_memory(rows_path: Path | None) -> dict[str, dict]:
    if rows_path is None:
        return {}
    path = Path(rows_path)
    if not path.exists():
        return {}
    cache_key = _adapter_cache_key(path)
    cached = _ADAPTER_MEMORY_CACHE.get(cache_key)
    if isinstance(cached, dict):
        return cached
    memory: dict[str, dict] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        lines = []
    for line in lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        if not isinstance(row, dict):
            continue
        fen = str(row.get("fen") or "").strip()
        side = str(row.get("side") or ("white" if " w " in fen else "black")).strip().lower()
        move_uci = str(row.get("move_uci") or row.get("teacher_move") or "").strip().lower()
        if not fen or side not in {"white", "black"} or len(move_uci) < 4:
            continue
        key = f"{fen}|{side}"
        current = memory.get(key)
        quality = str(row.get("label_quality") or "clean").strip().lower()
        priority = 2 if quality == "clean" else 1 if quality == "review" else 0
        if current is not None and int(current.get("_priority") or 0) > priority:
            continue
        teacher_top3 = [str(item).strip().lower() for item in (row.get("teacher_top3") or []) if str(item).strip()]
        if move_uci not in teacher_top3:
            teacher_top3.insert(0, move_uci)
        memory[key] = {
            "move_uci": move_uci,
            "teacher_top3": teacher_top3[:3],
            "teacher_top5": [str(item).strip().lower() for item in (row.get("teacher_top5") or []) if str(item).strip()],
            "label_quality": quality,
            "baseline_teacher_rank": row.get("baseline_teacher_rank"),
            "baseline_policy_gap_cp": row.get("baseline_policy_gap_cp"),
            "label_quality_reason": str(row.get("label_quality_reason") or ""),
            "source": str(row.get("source") or ""),
            "position_id": str(row.get("position_id") or ""),
            "_priority": priority,
        }
    _ADAPTER_MEMORY_CACHE.clear()
    _ADAPTER_MEMORY_CACHE[cache_key] = memory
    return memory


def _policy_row_for_move(rows: list[dict], move: chess.Move | None) -> dict:
    if move is None:
        return {}
    wanted = move.uci()
    return next((row for row in rows if str(row.get("move") or "") == wanted), {})


def _adapter_move_safety_report(
    board: chess.Board,
    *,
    side: str,
    main_move: chess.Move | None,
    adapter_move: chess.Move,
) -> dict:
    if main_move is not None:
        main_after = board.copy(stack=True)
        main_after.push(main_move)
    else:
        main_after = None
    adapter_after = board.copy(stack=True)
    adapter_after.push(adapter_move)
    color = chess.WHITE if str(side or "white").lower() == "white" else chess.BLACK
    reasons: list[str] = []
    if main_after is not None and main_after.is_checkmate():
        reasons.append("main_already_checkmates")
    if adapter_after.is_stalemate():
        reasons.append("adapter_stalemates")
    if _opponent_mate_in_one_moves(adapter_after):
        reasons.append("adapter_allows_mate_in_one")
    if main_after is not None:
        main_floor = _worst_immediate_reply_material_margin(main_after, color)
        adapter_floor = _worst_immediate_reply_material_margin(adapter_after, color)
        if adapter_floor < main_floor - _ADAPTER_MAX_MATERIAL_FLOOR_DROP_CP:
            reasons.append("adapter_material_floor_too_low")
    else:
        main_floor = None
        adapter_floor = _worst_immediate_reply_material_margin(adapter_after, color)
    if (
        adapter_after.can_claim_threefold_repetition()
        and (main_after is None or not main_after.can_claim_threefold_repetition())
        and _material_margin_for_color(board, color) > -250
    ):
        reasons.append("adapter_claimable_repetition_without_need")
    if _material_margin_for_color(board, color) >= 300 and _opponent_claimable_repetition_replies(adapter_after):
        reasons.append("adapter_enables_opponent_repetition_when_ahead")
    return {
        "safe": not reasons,
        "reasons": reasons,
        "main_material_floor": main_floor,
        "adapter_material_floor": adapter_floor,
    }


def _choose_experiment_nnue_move_with_adapter(board_state, side: str, *, search_profile="balanced") -> dict | None:
    adapter_path_text = os.environ.get(_ADAPTER_MODEL_PATH_ENV, "").strip()
    mode = os.environ.get(_ADAPTER_MODE_ENV, "guarded").strip().lower()
    if not adapter_path_text or mode not in {"guarded", "exact", "shadow"}:
        return None
    adapter_path = Path(adapter_path_text)
    if not adapter_path.exists():
        return None
    rows_text = os.environ.get(_ADAPTER_ROWS_PATH_ENV, "").strip()
    rows_path = Path(rows_text) if rows_text else None
    main_model_path = default_chess_nnue_model_path()

    previous_reentry = os.environ.get(_ADAPTER_REENTRY_ENV)
    os.environ[_ADAPTER_REENTRY_ENV] = "1"
    try:
        main_payload = choose_experiment_nnue_move(board_state, side, model_path=None, search_profile=search_profile)
    finally:
        if previous_reentry is None:
            os.environ.pop(_ADAPTER_REENTRY_ENV, None)
        else:
            os.environ[_ADAPTER_REENTRY_ENV] = previous_reentry

    board = _to_nnue_board(board_state, side)
    ai_color = chess.WHITE if side == "white" else chess.BLACK
    if board.turn != ai_color:
        board.turn = ai_color
    if board.is_game_over():
        return main_payload
    main_move = _move_payload_to_chess_move(board, main_payload)
    memory = _load_adapter_memory(rows_path)
    memory_row = memory.get(f"{board.fen()}|{side}")
    memory_move: chess.Move | None = None
    if memory_row:
        try:
            parsed = chess.Move.from_uci(str(memory_row.get("move_uci") or ""))
        except Exception:
            parsed = None
        if parsed is not None and parsed in board.legal_moves:
            memory_move = parsed
    allow_exact = (
        mode == "exact"
        or os.environ.get(_ADAPTER_ALLOW_EXACT_ENV, "").strip().lower() in {"1", "true", "yes", "on"}
    )
    allow_general = os.environ.get(_ADAPTER_ALLOW_GENERAL_ENV, "").strip().lower() in {"1", "true", "yes", "on"}
    model_adapter_move: chess.Move | None = None
    adapter_payload: dict | None = None
    if mode == "shadow" or (memory_move is None and allow_general):
        previous_reentry = os.environ.get(_ADAPTER_REENTRY_ENV)
        os.environ[_ADAPTER_REENTRY_ENV] = "1"
        try:
            adapter_payload = choose_experiment_nnue_move(board_state, side, model_path=adapter_path, search_profile=search_profile)
        finally:
            if previous_reentry is None:
                os.environ.pop(_ADAPTER_REENTRY_ENV, None)
            else:
                os.environ[_ADAPTER_REENTRY_ENV] = previous_reentry
        model_adapter_move = _move_payload_to_chess_move(board, adapter_payload)
    adapter_move = memory_move or model_adapter_move
    adapter_source = "exact_memory" if memory_move is not None else "adapter_model" if model_adapter_move is not None else "none"
    audit = {
        "enabled": True,
        "mode": mode,
        "allow_exact_memory_adoption": allow_exact,
        "allow_general_adapter_model": allow_general,
        "main_model_path": str(main_model_path),
        "adapter_model_path": str(adapter_path),
        "adapter_rows_path": str(rows_path or ""),
        "source": adapter_source,
        "memory_label_quality": str((memory_row or {}).get("label_quality") or ""),
        "memory_label_quality_reason": str((memory_row or {}).get("label_quality_reason") or ""),
        "memory_baseline_teacher_rank": (memory_row or {}).get("baseline_teacher_rank"),
        "memory_baseline_policy_gap_cp": (memory_row or {}).get("baseline_policy_gap_cp"),
        "main_move": main_move.uci() if main_move else "",
        "adapter_model_move": model_adapter_move.uci() if model_adapter_move else "",
        "adapter_move": adapter_move.uci() if adapter_move else "",
        "adopted": False,
        "reasons": [],
    }
    if memory_move is None and mode != "shadow" and not allow_general:
        audit["reasons"].append("no_exact_memory")
        payload = dict(main_payload or {})
        payload["adapter_decision"] = audit
        return payload
    if mode == "shadow":
        payload = dict(main_payload or {})
        payload["adapter_decision"] = audit
        return payload
    if adapter_source == "exact_memory" and not allow_exact:
        audit["reasons"].append("exact_memory_shadow_only")
        payload = dict(main_payload or {})
        payload["adapter_decision"] = audit
        return payload
    if adapter_move is None:
        audit["reasons"].append("adapter_no_legal_move")
        payload = dict(main_payload or {})
        payload["adapter_decision"] = audit
        return payload
    if main_move == adapter_move:
        audit["reasons"].append("same_as_main")
        payload = dict(main_payload or {})
        payload["adapter_decision"] = audit
        return payload

    safety = _adapter_move_safety_report(board, side=side, main_move=main_move, adapter_move=adapter_move)
    audit["safety"] = safety
    if not safety.get("safe"):
        audit["reasons"].extend(safety.get("reasons") or ["adapter_safety_failed"])
        payload = dict(main_payload or {})
        payload["adapter_decision"] = audit
        return payload

    main_rows = rank_experiment_nnue_policy_moves({"__fen__": board.fen()}, side, model_path=main_model_path, search_profile="fast")
    adapter_rows = rank_experiment_nnue_policy_moves({"__fen__": board.fen()}, side, model_path=adapter_path, search_profile="fast")
    main_row = _policy_row_for_move(main_rows, main_move)
    adapter_under_main = _policy_row_for_move(main_rows, adapter_move)
    adapter_under_adapter = _policy_row_for_move(adapter_rows, adapter_move)
    main_score = float(main_row.get("raw_policy_score") or 0.0)
    adapter_main_score = float(adapter_under_main.get("raw_policy_score") or 0.0)
    main_rank_for_adapter = int(adapter_under_main.get("raw_policy_rank") or 9999)
    adapter_rank = int(adapter_under_adapter.get("raw_policy_rank") or 9999)
    score_drop = main_score - adapter_main_score
    audit["main_rank_for_adapter"] = main_rank_for_adapter
    audit["adapter_rank_under_adapter"] = adapter_rank
    audit["main_score"] = main_score
    audit["adapter_move_main_score"] = adapter_main_score
    audit["main_score_drop_for_adapter"] = round(score_drop, 6)
    if adapter_source == "exact_memory":
        support = (
            main_rank_for_adapter <= _ADAPTER_MAX_MAIN_RANK_EXACT
            or score_drop <= _ADAPTER_MAX_MAIN_SCORE_DROP_EXACT_CP
        )
    else:
        support = (
            mode == "guarded"
            and adapter_rank == 1
            and main_rank_for_adapter <= _ADAPTER_MAX_MAIN_RANK_GENERAL
            and score_drop <= _ADAPTER_MAX_MAIN_SCORE_DROP_GENERAL_CP
        )
    if mode == "exact" and adapter_source != "exact_memory":
        support = False
    if not support:
        audit["reasons"].append("insufficient_main_model_support")
        payload = dict(main_payload or {})
        payload["adapter_decision"] = audit
        return payload

    payload = _move_dict(board, adapter_move)
    audit["adopted"] = True
    payload["adapter_decision"] = audit
    return payload


def choose_experiment_nnue_move(board_state, side: str, *, model_path=None, search_profile="balanced"):
    if (
        model_path is None
        and not os.environ.get(_ADAPTER_REENTRY_ENV)
        and os.environ.get(_ADAPTER_MODEL_PATH_ENV, "").strip()
    ):
        adapter_payload = _choose_experiment_nnue_move_with_adapter(board_state, side, search_profile=search_profile)
        if adapter_payload is not None:
            return adapter_payload
    board = _to_nnue_board(board_state, side)
    ai_color = chess.WHITE if side == "white" else chess.BLACK
    if board.turn != ai_color:
        board.turn = ai_color
    if board.is_game_over():
        return None
    forced_mates: list[chess.Move] = []
    for move in board.legal_moves:
        board.push(move)
        if board.is_checkmate():
            forced_mates.append(move)
        board.pop()
    if forced_mates:
        best_mate = sorted(
            forced_mates,
            key=lambda move: (
                bool(move.promotion),
                _promotion_priority(move),
                board.gives_check(move),
                _captured_piece_value(board, move),
                move.uci(),
            ),
            reverse=True,
        )[0]
        return _move_dict(board, best_mate)
    forced_single_reply_mate_net = _forced_single_reply_mate_net_move(board)
    if forced_single_reply_mate_net is not None:
        return _move_dict(board, forced_single_reply_mate_net)
    profile = _resolve_search_profile(search_profile)
    model = dict(_load_model(Path(model_path or default_chess_nnue_model_path())))
    model["_enable_rich_eval"] = bool(profile.get("enable_rich_eval"))
    model["_enable_pawn_structure"] = bool(profile.get("enable_pawn_structure"))
    model["_enable_piece_activity"] = bool(profile.get("enable_piece_activity"))
    model["_enable_piece_activity_midgame"] = bool(profile.get("enable_piece_activity_midgame"))
    model["_enable_center_break"] = bool(profile.get("enable_center_break"))
    model["_enable_fianchetto_development"] = bool(profile.get("enable_fianchetto_development"))
    model["_enable_king_zone_pressure"] = bool(profile.get("enable_king_zone_pressure"))
    model["_enable_v26_long_tail_eval"] = bool(profile.get("enable_v26_long_tail_eval"))
    model["_enable_v26_long_tail_eval_strict"] = bool(profile.get("enable_v26_long_tail_eval_strict"))
    model["_v26_long_tail_scale_percent"] = int(profile.get("v26_long_tail_scale_percent") or 100)
    model["_enable_v26_long_tail_ordering"] = bool(profile.get("enable_v26_long_tail_ordering"))
    model["_enable_v26_candidate_search_ordering"] = bool(profile.get("enable_v26_candidate_search_ordering"))
    model["_enable_v27_root_long_tail_ordering"] = bool(profile.get("enable_v27_root_long_tail_ordering"))
    if model_path is None:
        replay_prior_move = _replay_prior_priority_move(board, side)
        if replay_prior_move is not None:
            return _move_dict(board, replay_prior_move)
    opening_trap_move = _opening_trap_priority_move(board, side)
    if opening_trap_move is not None:
        return _move_dict(board, opening_trap_move)
    overlay_move = _opening_overlay_priority_move(board, side, model)
    priority_move = _special_rule_priority_move(
        board,
        allow_queenside_castle=bool(profile.get("allow_queenside_castle_priority", True)),
    )
    if overlay_move is not None:
        # Exact curated opening overlays may override the broad "castle early"
        # heuristic and ordinary minor-piece trades, but not forcing rule/tactic
        # priorities such as promotion, en-passant, or high-value captures.
        priority_is_ordinary_minor_capture = (
            priority_move is not None
            and board.is_capture(priority_move)
            and _captured_piece_value(board, priority_move) < _PIECE_VALUES[chess.ROOK]
            and not board.is_en_passant(priority_move)
            and priority_move.promotion is None
        )
        if priority_move is None or board.is_castling(priority_move) or priority_is_ordinary_minor_capture:
            return _move_dict(board, overlay_move)
    static_book_move = _static_opening_book_priority_move(board, side) if bool(profile.get("enable_static_opening_book")) else None
    if static_book_move is not None:
        # The static opening book is a broad sanity layer. Let forcing tactical
        # priorities (promotion, en-passant, high-value captures) preempt it,
        # but allow the book to beat generic early castling/minor-capture
        # preferences so exp5 follows coherent openings before shallow search.
        priority_is_forcing = (
            priority_move is not None
            and (
                priority_move.promotion
                or board.is_en_passant(priority_move)
                or (
                    board.is_capture(priority_move)
                    and _captured_piece_value(board, priority_move) >= _PIECE_VALUES[chess.ROOK]
                )
            )
        )
        if not priority_is_forcing:
            return _move_dict(board, static_book_move)
    if bool(profile.get("enable_tail_mate_net")):
        forced_checking_mate = _forced_checking_mate_priority_move(
            board,
            max_depth_plies=7,
            max_pieces=int(profile.get("tail_mate_max_pieces", 18)),
            max_legal_moves=70,
            min_material_margin_cp=int(profile.get("tail_mate_min_margin_cp", 1300)),
            max_nodes=int(profile.get("tail_mate_max_nodes", 8_000)),
            max_root_checks=int(profile.get("tail_mate_max_root_checks", 5)),
        )
        if forced_checking_mate is not None:
            return _move_dict(board, forced_checking_mate)
        forced_mate_two = _forced_mate_in_two_priority_move(
            board,
            max_pieces=int(profile.get("mate_two_max_pieces", 18)),
            max_legal_moves=70,
            max_replies=70,
            min_material_margin_cp=int(profile.get("mate_two_min_margin_cp", 700)),
        )
    else:
        forced_mate_two = _forced_mate_in_two_priority_move(board)
    if priority_move is not None:
        if board.is_castling(priority_move) and forced_mate_two is not None:
            return _move_dict(board, forced_mate_two)
        return _move_dict(board, priority_move)
    if forced_mate_two is not None:
        return _move_dict(board, forced_mate_two)

    hasher = ZobristHasher(seed=20260530)
    eval_cache: dict[int, int] = {}
    search_depth = int(profile["depth"])
    quiescence_depth = int(profile["quiescence_depth"])
    if bool(profile.get("enable_v26_selective_depth")) and _v26_should_selective_depth(board, ai_color):
        search_depth = max(search_depth, int(profile.get("v26_selective_depth") or search_depth))
        quiescence_depth = max(quiescence_depth, int(profile.get("v26_selective_quiescence_depth") or quiescence_depth))
    def move_order_fn(current_board, move, _ply):
        return (
            _move_order_score(current_board, move)
            + (
                _v26_long_tail_move_bonus(
                    current_board,
                    move,
                    current_board.turn,
                    include_progress=False,
                    include_repetition=False,
                )
                if bool(
                    model.get("_enable_v26_long_tail_ordering")
                    or model.get("_enable_v26_candidate_search_ordering")
                    or (model.get("_enable_v27_root_long_tail_ordering") and int(_ply or 0) == 0)
                )
                else 0
            )
        )

    result = search_best_move(
        board,
        max_depth=search_depth,
        evaluate=lambda current_board: _nnue_eval(current_board, model, eval_cache, hasher),
        move_order_fn=move_order_fn,
        qmove_filter=_exp5_qmove_filter,
        extension_fn=_exp5_search_extension,
        max_extensions=2,
        hasher=hasher,
        quiescence_depth=quiescence_depth,
        time_budget_ms=profile.get("time_budget_ms"),
        enable_pvs=bool(profile.get("enable_pvs")),
        enable_lmr=bool(profile.get("enable_lmr")),
        enable_null_move=bool(profile.get("enable_null_move")),
        enable_futility=bool(profile.get("enable_futility")),
        futility_margin_cp=int(profile.get("futility_margin_cp") or 180),
        lmr_min_move_index=int(profile.get("lmr_min_move_index") or 4),
    )
    best_move = opening_sanity_filter(board, result.best_move, score_move=lambda move: _move_order_score(board, move))
    score_move = lambda move: _score_move_for_side(board, move, side, model, eval_cache, hasher)
    best_move = _opening_development_filter(board, best_move, score_move=score_move)
    best_move = _opening_low_value_capture_filter(board, best_move, score_move=score_move)
    best_move = _opening_minor_revisit_filter(board, best_move, score_move=score_move)
    best_move = _opening_king_walk_filter(board, best_move, score_move=score_move)
    if bool(profile.get("enable_special_rule_fusion")):
        best_move = _special_rule_fusion_filter(board, best_move, score_move=score_move)
    if bool(profile.get("enable_v27_forced_mate_defense")):
        best_move = _avoid_opponent_forced_mate_net_filter(
            board,
            best_move,
            side=side,
            score_move=score_move,
            max_depth_plies=int(profile.get("v27_forced_mate_defense_max_depth", 7)),
            max_pieces=int(profile.get("v27_forced_mate_defense_max_pieces", 30)),
            max_nodes=int(profile.get("v27_forced_mate_defense_max_nodes", 12_000)),
            scan_limit=int(profile.get("v27_forced_mate_defense_scan_limit", 16)),
        )
    compensation_fn = None
    if bool(model.get("_enable_center_break") or model.get("_enable_fianchetto_development")):
        compensation_fn = lambda move: (
            (_center_break_move_bonus(board, move) if bool(model.get("_enable_center_break")) else 0)
            + (_fianchetto_development_move_bonus(board, move) if bool(model.get("_enable_fianchetto_development")) else 0)
        )
    best_move, _safety_report = choose_tactically_safe_move(
        board,
        best_move,
        score_move=score_move,
        max_direct_loss_cp=80,
        compensation_window_cp=40,
    )
    best_move = _conversion_check_evasion_filter(board, best_move, side=side, score_move=score_move)
    best_move = _avoid_allowing_mate_in_one_filter(board, best_move, score_move=score_move)
    best_move = _avoid_immediate_material_drop_filter(
        board,
        best_move,
        side=side,
        score_move=score_move,
        compensation_fn=compensation_fn,
    )
    best_move = _avoid_unanswered_immediate_promotion_filter(board, best_move, side=side, score_move=score_move)
    best_move = _claimable_draw_resource_filter(board, best_move, side=side, score_move=score_move)
    best_move = _avoid_claimable_repetition_filter(board, best_move, score_move=score_move)
    best_move = _avoid_reversible_cycle_when_ahead_filter(board, best_move, side=side, score_move=score_move)
    best_move = _avoid_enabling_opponent_repetition_when_ahead_filter(board, best_move, side=side, score_move=score_move)
    best_move = _avoid_non_progress_shuffle_when_ahead_filter(board, best_move, side=side, score_move=score_move)
    best_move = _avoid_shuffle_with_advanced_pawn_push_filter(board, best_move, side=side, score_move=score_move)
    best_move = _endgame_progress_filter(board, best_move, side=side, score_move=score_move)
    best_move = _bare_king_conversion_filter(board, best_move, side=side, score_move=score_move)
    best_move = _opening_minor_revisit_filter(board, best_move, score_move=score_move)
    best_move = _opening_king_walk_filter(board, best_move, score_move=score_move)
    if bool(profile.get("enable_final_low_legal_check_escape")):
        best_move = _low_legal_check_escape_filter(
            board,
            best_move,
            side=side,
            score_move=score_move,
            max_legal=int(profile.get("final_low_legal_check_escape_max_legal", 4)),
            max_pieces=int(profile.get("final_low_legal_check_escape_max_pieces", 30)),
            max_depth_plies=int(profile.get("final_low_legal_check_escape_max_depth", 7)),
            max_nodes=int(profile.get("final_low_legal_check_escape_max_nodes", 12_000)),
            enable_king_mobility4=bool(profile.get("final_low_legal_check_escape_enable_king_mobility4")),
        )
    best_move = _avoid_stalemate_filter(board, best_move, score_move=score_move)
    return _move_dict(board, best_move) if best_move is not None else None


def build_experiment_nnue_sample_from_position(
    *,
    fen: str,
    move_uci: str,
    side: str | None = None,
    target: float = 1.0,
    weight: float = 1.0,
    source: str = "external",
    hard_negatives: list[str] | None = None,
    teacher_top3: list[str] | None = None,
    teacher_top5: list[str] | None = None,
    teacher_top_weights: dict[str, float] | None = None,
    search_profile: str = "fast",
) -> dict | None:
    fen_text = str(fen or "").strip()
    move_text = str(move_uci or "").strip().lower()
    if not fen_text or len(move_text) < 4:
        return None
    try:
        board_before = chess.Board(fen_text)
    except Exception:
        return None
    mover = str(side or ("white" if board_before.turn == chess.WHITE else "black")).strip().lower()
    if mover not in {"white", "black"}:
        return None
    board_before.turn = chess.WHITE if mover == "white" else chess.BLACK
    try:
        move = chess.Move.from_uci(move_text)
    except Exception:
        return None
    if move not in board_before.legal_moves:
        return None
    sample = {
        "fen": board_before.fen(),
        "move_uci": move.uci(),
        "side": mover,
        "target": _clip(float(target), -1.0, 1.0),
        "weight": _clip(float(weight), 0.1, 8.0),
        "source": str(source or "external"),
        "hard_negatives": [str(item).strip().lower() for item in (hard_negatives or []) if str(item).strip()],
        "search_profile": str(search_profile or "fast"),
        "sample_format": "exp5_nnue_position_move_v1",
    }
    if teacher_top3:
        sample["teacher_top3"] = _legal_uci_list(board_before, teacher_top3)
    if teacher_top5:
        sample["teacher_top5"] = _legal_uci_list(board_before, teacher_top5)
    if isinstance(teacher_top_weights, dict):
        weights: dict[str, float] = {}
        for key, value in teacher_top_weights.items():
            try:
                move_key = chess.Move.from_uci(str(key or "").strip().lower()).uci()
            except Exception:
                continue
            if chess.Move.from_uci(move_key) in board_before.legal_moves:
                weights[move_key] = round(_clip(float(value), 0.0, 1.0), 6)
        if weights:
            sample["teacher_top_weights"] = weights
    return sample


def normalize_experiment_nnue_replay_sample(sample: dict) -> dict | None:
    if not isinstance(sample, dict):
        return None
    try:
        target = float(sample.get("target", 1.0) or 0.0)
        weight = float(sample.get("weight", 1.0) or 1.0)
    except Exception:
        return None
    normalized = build_experiment_nnue_sample_from_position(
        fen=str(sample.get("fen") or sample.get("board_fen") or "").strip(),
        move_uci=str(sample.get("move_uci") or sample.get("uci") or sample.get("move") or "").strip(),
        side=sample.get("side"),
        target=target,
        weight=weight,
        source=str(sample.get("source") or "external"),
        hard_negatives=list(sample.get("hard_negatives") or []),
        teacher_top3=list(sample.get("teacher_top3") or sample.get("teacher_top_moves") or []),
        teacher_top5=list(sample.get("teacher_top5") or []),
        teacher_top_weights=sample.get("teacher_top_weights") if isinstance(sample.get("teacher_top_weights"), dict) else None,
        search_profile=str(sample.get("search_profile") or "fast"),
    )
    if normalized is None:
        return None
    for key in (
        "label_quality",
        "label_quality_reason",
        "category",
        "source_category",
        "dataset_split_bucket",
        "position_id",
        "teacher_backend",
        "teacher_top_k_method",
        "static_teacher_top_k",
    ):
        if key in sample:
            normalized[key] = sample[key]
    return normalized


def _load_replay_entries(replay_path: Path) -> list[dict]:
    path = Path(replay_path)
    if not path.exists():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except Exception:
            continue
        normalized = normalize_experiment_nnue_replay_sample(payload)
        if normalized is not None:
            rows.append(normalized)
    return rows


def _write_replay_entries(replay_path: Path, entries: list[dict]) -> int:
    path = Path(replay_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in entries)
    path.write_text(body, encoding="utf-8")
    return len(entries)


def _legal_hard_negative_moves(board: chess.Board, expected_move: chess.Move, hard_negatives: list[str]) -> list[chess.Move]:
    moves: list[chess.Move] = []
    seen: set[str] = set()
    for item in hard_negatives or []:
        try:
            move = chess.Move.from_uci(str(item or "").strip().lower())
        except Exception:
            continue
        if move == expected_move or move not in board.legal_moves or move.uci() in seen:
            continue
        seen.add(move.uci())
        moves.append(move)
    return moves


def _soft_teacher_moves(
    board: chess.Board,
    expected_move: chess.Move,
    sample: dict,
    *,
    top3_weight: float,
    top5_weight: float,
) -> list[tuple[chess.Move, float]]:
    """Return legal alternative teacher moves with fractional positive weight."""
    weighted: dict[str, float] = {}
    explicit = sample.get("teacher_top_weights")
    if isinstance(explicit, dict):
        for raw_move, raw_weight in explicit.items():
            try:
                move = chess.Move.from_uci(str(raw_move or "").strip().lower())
                weight = float(raw_weight)
            except Exception:
                continue
            if move == expected_move or move not in board.legal_moves:
                continue
            weighted[move.uci()] = max(weighted.get(move.uci(), 0.0), _clip(weight, 0.0, 1.0))
    top3 = _legal_uci_list(board, sample.get("teacher_top3") or [])
    top5 = _legal_uci_list(board, sample.get("teacher_top5") or [])
    for index, uci in enumerate(top3):
        try:
            move = chess.Move.from_uci(uci)
        except Exception:
            continue
        if move == expected_move:
            continue
        # top2/top3 should be treated as reasonable alternatives, but weaker
        # than the explicit teacher move.
        decay = 1.0 if index <= 1 else 0.78
        weighted[uci] = max(weighted.get(uci, 0.0), _clip(float(top3_weight) * decay, 0.0, 1.0))
    for index, uci in enumerate(top5):
        try:
            move = chess.Move.from_uci(uci)
        except Exception:
            continue
        if move == expected_move or uci in weighted:
            continue
        decay = 1.0 if index <= 2 else 0.75
        weighted[uci] = max(weighted.get(uci, 0.0), _clip(float(top5_weight) * decay, 0.0, 1.0))
    result: list[tuple[chess.Move, float]] = []
    for uci, weight in sorted(weighted.items(), key=lambda item: (-item[1], item[0])):
        if weight <= 0.0:
            continue
        move = chess.Move.from_uci(uci)
        if move in board.legal_moves and move != expected_move:
            result.append((move, weight))
    return result


def _adjust_weight(mapping: dict, key: str, delta: float) -> None:
    mapping[key] = round(_clip(float(mapping.get(key) or 0.0) + float(delta), -_MAX_ABS_WEIGHT, _MAX_ABS_WEIGHT), 6)


def _train_position_move(model: dict, sample: dict, *, target_override: float | None = None, weight_override: float | None = None) -> bool:
    try:
        board = chess.Board(str(sample.get("fen") or ""))
        side = str(sample.get("side") or "white").strip().lower()
        board.turn = chess.WHITE if side == "white" else chess.BLACK
        move = chess.Move.from_uci(str(sample.get("move_uci") or ""))
    except Exception:
        return False
    if side not in {"white", "black"} or move not in board.legal_moves:
        return False
    target = float(sample.get("target") or 0.0) if target_override is None else float(target_override)
    weight = float(sample.get("weight") or 1.0) if weight_override is None else float(weight_override)
    side_sign = 1.0 if side == "white" else -1.0
    # Piece-square and shared center weights are evaluated with the piece color
    # sign in _sparse_feature_score. A positive target should therefore
    # increase the moved piece's own feature weight for BOTH colors: white gets
    # +weight in eval, black gets -weight in eval. The tempo term is still
    # side-signed below because tempo is keyed to side-to-move rather than a
    # piece-color feature.
    delta = _clip(target, -1.0, 1.0) * _clip(weight, 0.1, 8.0) * _LEARNING_RATE
    after = board.copy(stack=False)
    after.push(move)
    moved_piece = after.piece_at(move.to_square)
    if moved_piece is not None:
        _adjust_weight(model.setdefault("piece_square_weights", {}), _piece_feature_key(move.to_square, moved_piece), delta)
        if move.to_square in _CENTER and moved_piece.piece_type in {chess.PAWN, chess.KNIGHT, chess.BISHOP}:
            _adjust_weight(model.setdefault("feature_weights", {}), "center_control", delta * 0.12)
        elif move.to_square in _EXTENDED_CENTER and moved_piece.piece_type in {chess.PAWN, chess.KNIGHT, chess.BISHOP}:
            _adjust_weight(model.setdefault("feature_weights", {}), "extended_center_control", delta * 0.08)
    if board.is_castling(move):
        model["king_safety_weight"] = int(round(_clip(int(model.get("king_safety_weight") or 0) + abs(delta) * 0.04, -80, 120)))
    if board.fullmove_number <= 8:
        model["tempo"] = int(round(_clip(int(model.get("tempo") or 0) + side_sign * _clip(target, -1.0, 1.0) * 0.2, -40, 40)))
    model["sample_count"] = int(model.get("sample_count") or 0) + 1
    model["updated_at"] = _now()
    return True


def _policy_probe_for_sample(model_path: Path, sample: dict) -> dict | None:
    fen = str(sample.get("fen") or "").strip()
    side = str(sample.get("side") or "").strip().lower()
    expected = str(sample.get("move_uci") or "").strip().lower()
    if not fen or side not in {"white", "black"} or not expected:
        return None
    rows = rank_experiment_nnue_policy_moves({"__fen__": fen}, side, model_path=model_path, search_profile=str(sample.get("search_profile") or "fast"))
    expected_row = next((row for row in rows if str(row.get("move") or "") == expected), None)
    if expected_row is None:
        return None
    top1 = str(rows[0].get("move") or "") if rows else ""
    old_row = next((row for row in rows if str(row.get("move") or "") == top1), None)
    return {
        "fen": fen,
        "side": side,
        "expected_move": expected,
        "raw_policy_top1": top1,
        "expected_move_rank": int(expected_row.get("raw_policy_rank") or 0),
        "expected_move_probability": float(expected_row.get("policy_probability") or 0.0),
        "expected_move_logit": float(expected_row.get("raw_policy_score") or 0.0),
        "old_move": top1,
        "old_move_rank": int((old_row or {}).get("raw_policy_rank") or 0),
        "margin_vs_old_move": round(float(expected_row.get("raw_policy_score") or 0.0) - float((old_row or {}).get("raw_policy_score") or 0.0), 8),
    }


def train_experiment_nnue_from_replay_samples(
    samples: list[dict],
    *,
    model_path=None,
    replay_path=None,
    replace_replay: bool = False,
    epochs: int = 1,
    soft_teacher_topk: bool = True,
    soft_teacher_top3_weight: float = _SOFT_TEACHER_TOP3_WEIGHT_DEFAULT,
    soft_teacher_top5_weight: float = _SOFT_TEACHER_TOP5_WEIGHT_DEFAULT,
    pairwise_hard_negative: bool = True,
    pairwise_margin_cp: float = _PAIRWISE_MARGIN_DEFAULT_CP,
) -> dict:
    normalized_samples = []
    rejected = 0
    for item in samples or []:
        normalized = normalize_experiment_nnue_replay_sample(item)
        if normalized is None:
            rejected += 1
            continue
        normalized_samples.append(normalized)
    model_path = Path(model_path or default_chess_nnue_model_path())
    replay_path = Path(replay_path or default_chess_nnue_replay_path())
    existing = [] if replace_replay else _load_replay_entries(replay_path)
    replay_entries = existing + normalized_samples
    replay_size = _write_replay_entries(replay_path, replay_entries)
    probe_sample = next((sample for sample in normalized_samples if sample.get("fen") and sample.get("move_uci") and sample.get("side")), None)
    policy_probe_before = _policy_probe_for_sample(model_path, probe_sample or {}) if probe_sample else None
    model = _load_model(model_path)
    positive_updates = 0
    soft_target_updates = 0
    hard_negative_updates = 0
    pairwise_hard_negative_updates = 0
    effective_epochs = max(1, int(epochs or 1))
    pairwise_margin = max(20.0, float(pairwise_margin_cp or _PAIRWISE_MARGIN_DEFAULT_CP))
    for _epoch in range(effective_epochs):
        for sample in replay_entries:
            repeat = max(1, int(round(float(sample.get("weight") or 1.0))))
            try:
                board = chess.Board(str(sample.get("fen") or ""))
                side = str(sample.get("side") or "white").strip().lower()
                board.turn = chess.WHITE if side == "white" else chess.BLACK
                expected = chess.Move.from_uci(str(sample.get("move_uci") or ""))
            except Exception:
                continue
            if expected not in board.legal_moves:
                continue
            soft_moves = _soft_teacher_moves(
                board,
                expected,
                sample,
                top3_weight=float(soft_teacher_top3_weight),
                top5_weight=float(soft_teacher_top5_weight),
            ) if soft_teacher_topk else []
            for _index in range(repeat):
                if _train_position_move(model, sample):
                    positive_updates += 1
                for soft_move, soft_weight in soft_moves:
                    soft_sample = dict(sample)
                    soft_sample["move_uci"] = soft_move.uci()
                    if _train_position_move(
                        model,
                        soft_sample,
                        target_override=float(sample.get("target") or 1.0) * soft_weight,
                        weight_override=float(sample.get("weight") or 1.0),
                    ):
                        soft_target_updates += 1
            for negative in _legal_hard_negative_moves(board, expected, list(sample.get("hard_negatives") or [])):
                negative_sample = dict(sample)
                negative_sample["move_uci"] = negative.uci()
                negative_weight = max(1.0, float(sample.get("weight") or 1.0))
                if pairwise_hard_negative:
                    hasher = ZobristHasher(seed=20260530)
                    eval_cache: dict[int, int] = {}
                    expected_score = _score_move_for_side(board, expected, side, model, eval_cache, hasher)
                    negative_score = _score_move_for_side(board, negative, side, model, eval_cache, hasher)
                    violation = pairwise_margin - (float(expected_score) - float(negative_score))
                    if violation > 0.0:
                        scale = _clip(violation / pairwise_margin, 0.25, 2.0)
                        pair_weight = max(0.1, min(8.0, negative_weight * scale))
                        if _train_position_move(model, sample, target_override=abs(float(sample.get("target") or 1.0)), weight_override=pair_weight):
                            pairwise_hard_negative_updates += 1
                        if _train_position_move(
                            model,
                            negative_sample,
                            target_override=-abs(float(sample.get("target") or 1.0)),
                            weight_override=pair_weight,
                        ):
                            pairwise_hard_negative_updates += 1
                if _train_position_move(
                    model,
                    negative_sample,
                    target_override=-abs(float(sample.get("target") or 1.0)),
                    weight_override=negative_weight,
                ):
                    hard_negative_updates += 1
    if replay_entries:
        _save_model(model_path, model)
    policy_probe_after = _policy_probe_for_sample(model_path, probe_sample or {}) if probe_sample else None
    policy_probe = {
        "supported": bool(policy_probe_before and policy_probe_after),
        "before": policy_probe_before or {},
        "after": policy_probe_after or {},
        "training_applied": bool(replay_entries),
    }
    if policy_probe_before and policy_probe_after:
        policy_probe.update(
            {
                "expected_rank_delta": int(policy_probe_after["expected_move_rank"]) - int(policy_probe_before["expected_move_rank"]),
                "expected_margin_delta": round(float(policy_probe_after["margin_vs_old_move"]) - float(policy_probe_before["margin_vs_old_move"]), 8),
                "raw_policy_top1_changed_to_expected": bool(policy_probe_after["raw_policy_top1"] == policy_probe_after["expected_move"]),
            }
        )
    return {
        "ok": True,
        "engine": EXPERIMENT_NNUE_DIFFICULTY,
        "retrain_supported": True,
        "training_applied": bool(replay_entries),
        "reason": "basic exp5 NNUE-like replay trainer; strength validation and promotion gates are pending exp5-specific design",
        "accepted_samples": len(normalized_samples),
        "rejected_samples": rejected,
        "replay_size": replay_size,
        "model_path": str(model_path),
        "replay_path": str(replay_path),
        "sample_count": int(model.get("sample_count") or 0),
        "sample_format": "exp5_nnue_position_move_v1",
        "training_objective": "position_move_evaluator_delta",
        "positive_updates": positive_updates,
        "soft_target_updates": soft_target_updates,
        "hard_negative_updates": hard_negative_updates,
        "pairwise_hard_negative_updates": pairwise_hard_negative_updates,
        "soft_teacher_topk": bool(soft_teacher_topk),
        "soft_teacher_top3_weight": float(soft_teacher_top3_weight),
        "soft_teacher_top5_weight": float(soft_teacher_top5_weight),
        "pairwise_hard_negative": bool(pairwise_hard_negative),
        "pairwise_margin_cp": pairwise_margin,
        "epochs": effective_epochs,
        "policy_probe": policy_probe,
    }
