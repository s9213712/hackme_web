"""Tests for scripts/games/chess_pvp_history_to_replay.py — W1+W3.

Covers two harvest paths (pvp_filtered, human_beat_engine) plus the common
reject reasons. Uses tmp_path SQLite DBs seeded with a minimal users table
and the runtime game schema. Quality signal comes from
game_leaderboard_rewards rows; tests assert both accept and reject paths.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import chess

from routes.games import ensure_game_schema
from scripts.games.chess_pvp_history_to_replay import (
    HVE_SAMPLE_WEIGHT_CAP,
    PVP_SAMPLE_WEIGHT_CAP,
    _classify_match,
    _quality_user_set,
    _winner_side,
    run_export,
)


# ---- DB / fixtures -----------------------------------------------------


def _seed_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            role TEXT NOT NULL DEFAULT 'user',
            status TEXT NOT NULL DEFAULT 'active',
            deleted_at TEXT
        );
        INSERT INTO users (id, username, role, status) VALUES
          (1, 'root',  'super_admin', 'active'),
          (2, 'alice', 'user', 'active'),
          (3, 'bob',   'user', 'active'),
          (4, 'carol', 'user', 'active'),
          (5, 'dave',  'user', 'active');
        """
    )
    ensure_game_schema(conn)
    conn.commit()
    return conn


def _seed_leaderboard(
    conn: sqlite3.Connection,
    *,
    week_keys: list[str],
    ranked_user_ids: list[list[int]],
) -> None:
    """Insert rows into game_leaderboard_rewards.

    ranked_user_ids[i] is the rank-ordered list (rank 1 first) for week_keys[i].
    """
    rows = []
    for wk, users in zip(week_keys, ranked_user_ids):
        for rank, uid in enumerate(users, start=1):
            rows.append((wk, int(uid), rank))
    conn.executemany(
        "INSERT INTO game_leaderboard_rewards "
        "(game_key, week_key, user_id, rank, score, reward_points, created_at) "
        "VALUES ('chess', ?, ?, ?, ?, 0, '2026-05-08T00:00:00Z')",
        [(wk, uid, rank, 1000 - rank * 10) for wk, uid, rank in rows],
    )
    conn.commit()


def _make_history_legal(plies: int = 24) -> list[dict]:
    """Build a legal move_history of `plies` length using a known opening."""
    seq = [
        "e2e4", "e7e5", "g1f3", "b8c6", "f1b5", "a7a6", "b5a4", "g8f6",
        "e1g1", "f8e7", "f1e1", "b7b5", "a4b3", "d7d6", "c2c3", "e8g8",
        "h2h3", "c6a5", "b3c2", "c7c5", "d2d4", "d8c7", "b1d2", "a5c6",
        "d4d5", "c6d8", "a2a4", "c8b7", "a4b5", "a6b5", "d2f1", "d8b7",
    ]
    history: list[dict] = []
    board = chess.Board()
    for uci in seq[:plies]:
        move = chess.Move.from_uci(uci)
        piece = board.piece_at(move.from_square)
        captured = board.piece_at(move.to_square)
        by_color = "white" if board.turn == chess.WHITE else "black"
        history.append(
            {
                "by": by_color,
                "from": chess.square_name(move.from_square),
                "to": chess.square_name(move.to_square),
                "piece": piece.symbol() if piece else "",
                "captured": captured.symbol() if captured else None,
                "promotion": chess.piece_symbol(move.promotion) if move.promotion else None,
                "at": "2026-05-08T00:00:00Z",
            }
        )
        board.push(move)
    return history


def _insert_match(
    conn: sqlite3.Connection,
    *,
    match_id: int,
    mode: str = "pvp",
    status: str = "finished",
    white_user_id: int,
    black_user_id: int | None,
    human_side: str = "white",
    computer_difficulty: str = "normal",
    winner_user_id: int | None,
    result_reason: str | None = "checkmate",
    move_history: list[dict] | None = None,
    finished_at: str = "2026-05-10T12:00:00Z",
) -> None:
    history_json = json.dumps(move_history or [])
    conn.execute(
        """
        INSERT INTO game_matches (
            id, game_key, mode, status,
            white_user_id, black_user_id, human_side, computer_difficulty,
            current_turn, board_json, move_history_json,
            winner_user_id, result_reason,
            created_at, updated_at, finished_at
        ) VALUES (?, 'chess', ?, ?, ?, ?, ?, ?, 'white', '{}', ?, ?, ?,
                  '2026-05-10T11:00:00Z', '2026-05-10T12:00:00Z', ?)
        """,
        (
            match_id, mode, status,
            white_user_id, black_user_id, human_side, computer_difficulty,
            history_json, winner_user_id, result_reason, finished_at,
        ),
    )
    conn.commit()


# ---- _quality_user_set --------------------------------------------------


def test_quality_user_set_takes_top_pct_across_weeks(tmp_path):
    db = tmp_path / "q.db"
    conn = _seed_db(db)
    try:
        # 4 weeks with 5 users ranked. Top 30% of 5 = 1.5 → ceil-ish → 2 users / week.
        _seed_leaderboard(
            conn,
            week_keys=["2026-W18", "2026-W19", "2026-W20", "2026-W21"],
            ranked_user_ids=[
                [2, 3, 4, 5, 1],
                [3, 2, 5, 4, 1],
                [4, 5, 2, 3, 1],
                [5, 4, 3, 2, 1],
            ],
        )
        qualified, debug = _quality_user_set(conn, weeks=4, top_pct=30.0)
        # round(5 * 0.30) == 2 → top 2 per week
        # Week 18: {2,3}, Week 19: {3,2}, Week 20: {4,5}, Week 21: {5,4}
        # Union = {2,3,4,5}; user 1 always rank 5 → excluded.
        assert qualified == {2, 3, 4, 5}
        assert debug["union_size"] == 4
        assert len(debug["weeks_considered"]) == 4
        for wk_info in debug["by_week"].values():
            assert wk_info["cutoff"] == 2
    finally:
        conn.close()


def test_quality_user_set_only_K_most_recent_weeks(tmp_path):
    db = tmp_path / "q2.db"
    conn = _seed_db(db)
    try:
        # User 1 only ranked top in an OLD week → should NOT be included for K=2.
        _seed_leaderboard(
            conn,
            week_keys=["2026-W10", "2026-W11", "2026-W20", "2026-W21"],
            ranked_user_ids=[
                [1, 2, 3, 4, 5],
                [1, 2, 3, 4, 5],
                [2, 3, 4, 5, 1],
                [2, 3, 4, 5, 1],
            ],
        )
        qualified, debug = _quality_user_set(conn, weeks=2, top_pct=30.0)
        # Top 2 of W20 = {2, 3}, W21 = {2, 3}. User 1 excluded.
        assert 1 not in qualified
        assert qualified == {2, 3}
        assert debug["weeks_considered"] == ["2026-W21", "2026-W20"]
    finally:
        conn.close()


# ---- _classify_match ---------------------------------------------------


def test_classify_match_rejects_unfinished():
    class Row(dict):
        def __getitem__(self, key):
            return self.get(key)
    row = Row(status="active", mode="pvp")
    outcome, reason = _classify_match(row, move_history=[], quality_users=set(), min_plies=1)
    assert outcome == "reject"
    assert reason == "not_finished"


def test_classify_match_rejects_non_normal_end():
    class Row(dict):
        def __getitem__(self, key):
            return self.get(key)
    row = Row(status="finished", mode="pvp", result_reason="timeout", winner_user_id=2)
    outcome, reason = _classify_match(row, move_history=_make_history_legal(24), quality_users={2, 3}, min_plies=20)
    assert outcome == "reject"
    assert reason.startswith("non_normal_end")


def test_classify_match_rejects_too_short():
    class Row(dict):
        def __getitem__(self, key):
            return self.get(key)
    row = Row(status="finished", mode="pvp", result_reason="checkmate", winner_user_id=2,
              white_user_id=2, black_user_id=3)
    outcome, reason = _classify_match(row, move_history=_make_history_legal(8), quality_users={2, 3}, min_plies=20)
    assert outcome == "reject"
    assert "too_short" in reason


def test_classify_match_pvp_requires_both_sides_quality():
    class Row(dict):
        def __getitem__(self, key):
            return self.get(key)
    row_white_missing = Row(status="finished", mode="pvp", result_reason="checkmate", winner_user_id=2,
                            white_user_id=2, black_user_id=99)
    outcome, reason = _classify_match(row_white_missing, move_history=_make_history_legal(24), quality_users={2, 3}, min_plies=20)
    assert outcome == "reject"
    assert "no_player_quality:black" in reason


def test_classify_match_pvp_accepts_when_both_qualify():
    class Row(dict):
        def __getitem__(self, key):
            return self.get(key)
    row = Row(status="finished", mode="pvp", result_reason="checkmate", winner_user_id=2,
              white_user_id=2, black_user_id=3)
    outcome, reason = _classify_match(row, move_history=_make_history_legal(24), quality_users={2, 3}, min_plies=20)
    assert outcome == "pvp_filtered"
    assert reason == ""


def test_classify_match_human_beat_engine_requires_human_win():
    class Row(dict):
        def __getitem__(self, key):
            return self.get(key)
    # Computer won → winner_user_id is null → drops earlier on no_winner
    row_loss = Row(status="finished", mode="computer", result_reason="checkmate", winner_user_id=None,
                   white_user_id=2, black_user_id=None)
    outcome, reason = _classify_match(row_loss, move_history=_make_history_legal(24), quality_users={2}, min_plies=20)
    assert outcome == "reject"
    assert reason == "no_winner_or_drawn"

    # Human won, qualifies → human_beat_engine
    row_win = Row(status="finished", mode="computer", result_reason="checkmate", winner_user_id=2,
                  white_user_id=2, black_user_id=None)
    outcome, reason = _classify_match(row_win, move_history=_make_history_legal(24), quality_users={2}, min_plies=20)
    assert outcome == "human_beat_engine"
    assert reason == ""

    # Human won but not in quality set → reject
    row_unq = Row(status="finished", mode="computer", result_reason="checkmate", winner_user_id=2,
                  white_user_id=2, black_user_id=None)
    outcome, reason = _classify_match(row_unq, move_history=_make_history_legal(24), quality_users=set(), min_plies=20)
    assert outcome == "reject"
    assert "no_player_quality:human" in reason


def test_winner_side_handles_both_modes():
    class Row(dict):
        def __getitem__(self, key):
            return self.get(key)
    # PvP, white wins
    assert _winner_side(Row(mode="pvp", winner_user_id=2, white_user_id=2, black_user_id=3, human_side="white")) == "white"
    # PvP, black wins
    assert _winner_side(Row(mode="pvp", winner_user_id=3, white_user_id=2, black_user_id=3, human_side="white")) == "black"
    # Computer, human is white and won
    assert _winner_side(Row(mode="computer", winner_user_id=2, white_user_id=2, black_user_id=None, human_side="white")) == "white"
    # Computer, human is black and won
    assert _winner_side(Row(mode="computer", winner_user_id=2, white_user_id=2, black_user_id=None, human_side="black")) == "black"
    # No winner
    assert _winner_side(Row(mode="pvp", winner_user_id=None, white_user_id=2, black_user_id=3)) is None


# ---- run_export end-to-end ---------------------------------------------


def _run(db_path: Path, output_root: Path, **overrides) -> dict:
    kwargs = dict(
        db_path=db_path,
        since="",
        output_root=output_root,
        min_plies=20,
        quality_weeks=4,
        quality_top_pct=30.0,
        pvp_sample_weight=0.15,
        hve_sample_weight=0.20,
        limit=0,
    )
    kwargs.update(overrides)
    return run_export(**kwargs)


def test_run_export_emits_pvp_filtered_and_human_beat_engine(tmp_path):
    db = tmp_path / "rep.db"
    conn = _seed_db(db)
    try:
        _seed_leaderboard(
            conn,
            week_keys=["2026-W18", "2026-W19", "2026-W20", "2026-W21"],
            ranked_user_ids=[
                [2, 3, 4, 5, 1],
                [2, 3, 4, 5, 1],
                [2, 3, 4, 5, 1],
                [2, 3, 4, 5, 1],
            ],
        )
        # Match 1: PvP, alice (2) beats bob (3), checkmate, 24 plies. Both qualify.
        _insert_match(
            conn, match_id=1, mode="pvp", white_user_id=2, black_user_id=3,
            winner_user_id=2, result_reason="checkmate",
            move_history=_make_history_legal(24),
        )
        # Match 2: human-vs-engine, alice (2) beats experiment 4:pv, 24 plies.
        _insert_match(
            conn, match_id=2, mode="computer", white_user_id=2, black_user_id=None,
            computer_difficulty="experiment 4:pv",
            winner_user_id=2, result_reason="checkmate",
            move_history=_make_history_legal(24),
        )
        # Match 3: PvP but bob (3) plays root (1, never in top 30%) → reject.
        _insert_match(
            conn, match_id=3, mode="pvp", white_user_id=3, black_user_id=1,
            winner_user_id=3, result_reason="checkmate",
            move_history=_make_history_legal(24),
        )
        # Match 4: PvP but timeout → reject.
        _insert_match(
            conn, match_id=4, mode="pvp", white_user_id=2, black_user_id=3,
            winner_user_id=2, result_reason="timeout",
            move_history=_make_history_legal(24),
        )
        # Match 5: PvP but too short → reject.
        _insert_match(
            conn, match_id=5, mode="pvp", white_user_id=2, black_user_id=3,
            winner_user_id=2, result_reason="checkmate",
            move_history=_make_history_legal(8),
        )
        # Match 6: PvP draw → reject.
        _insert_match(
            conn, match_id=6, mode="pvp", white_user_id=2, black_user_id=3,
            winner_user_id=None, result_reason="stalemate",
            move_history=_make_history_legal(24),
        )
        # Match 7: human-vs-engine but computer won (winner_user_id=NULL) → reject.
        _insert_match(
            conn, match_id=7, mode="computer", white_user_id=2, black_user_id=None,
            computer_difficulty="experiment 4:pv",
            winner_user_id=None, result_reason="checkmate",
            move_history=_make_history_legal(24),
        )
    finally:
        conn.close()

    out_root = tmp_path / "out"
    summary = _run(db, out_root)

    counts = summary["counts"]
    assert counts["matches_total"] == 7
    assert counts["matches_accepted_pvp_filtered"] == 1
    assert counts["matches_accepted_human_beat_engine"] == 1
    assert counts["matches_rejected"] == 5

    run_dir = Path(summary["output_dir"])
    eligible_rows = [
        json.loads(line)
        for line in (run_dir / "pvp_replay_training_eligible.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    sources = {r["trusted_source"] for r in eligible_rows}
    assert sources == {"pvp_filtered", "human_beat_engine"}

    # Winner side for match 1 is white (alice=2 = white_user_id) → 12 white moves out of 24 plies.
    pvp_rows = [r for r in eligible_rows if r["trusted_source"] == "pvp_filtered"]
    assert all(r["side"] == "white" for r in pvp_rows)
    assert len(pvp_rows) == 12

    # human_beat_engine: alice played white and won → 12 white moves.
    hve_rows = [r for r in eligible_rows if r["trusted_source"] == "human_beat_engine"]
    assert all(r["side"] == "white" for r in hve_rows)
    assert all(r["label_quality"] == "clean" for r in hve_rows)
    assert all(r["weight"] == 0.20 for r in hve_rows)

    # PvP rows use the conservative review/weight=0.15 labels.
    assert all(r["label_quality"] == "review" for r in pvp_rows)
    assert all(r["weight"] == 0.15 for r in pvp_rows)

    rejected_rows = [
        json.loads(line)
        for line in (run_dir / "pvp_replay_rejected.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    rejected_ids = {row["match_id"] for row in rejected_rows}
    assert rejected_ids == {3, 4, 5, 6, 7}

    # candidates includes every parsed match.
    cand_rows = [
        json.loads(line)
        for line in (run_dir / "pvp_replay_candidates.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert {r["match_id"] for r in cand_rows} == {1, 2, 3, 4, 5, 6, 7}

    # Policy block hard-coded.
    assert summary["policy"]["diagnostic_only"] is True
    assert summary["policy"]["auto_train_hook"] is False
    assert summary["policy"]["production_runtime_mutation"] is False


def test_run_export_caps_sample_weight(tmp_path):
    db = tmp_path / "cap.db"
    _seed_db(db).close()
    out_root = tmp_path / "out"
    try:
        _run(db, out_root, pvp_sample_weight=PVP_SAMPLE_WEIGHT_CAP + 0.05)
    except SystemExit as exc:
        assert "exceeds policy cap" in str(exc)
    else:
        raise AssertionError("expected SystemExit on weight over cap")

    try:
        _run(db, out_root, hve_sample_weight=HVE_SAMPLE_WEIGHT_CAP + 0.05)
    except SystemExit as exc:
        assert "exceeds policy cap" in str(exc)
    else:
        raise AssertionError("expected SystemExit on hve weight over cap")
