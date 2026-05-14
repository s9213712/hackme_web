import chess

from scripts.games.chess_exp5_opening_overlay_staging_validation import (
    _bad_overlay_move,
    build_fresh_non_overlay_opening_probes,
)


def test_exp5_17_fresh_opening_probes_do_not_overlap_given_overlay_ids():
    probes = build_fresh_non_overlay_opening_probes(set())

    assert len(probes) >= 10
    assert all(not probe["position_id_overlaps_overlay"] for probe in probes)
    assert len({probe["position_id"] for probe in probes}) == len(probes)


def test_exp5_17_bad_overlay_move_avoids_forbidden_current_move():
    fen = "8/P7/8/8/8/8/8/k1K5 w - - 0 1"
    bad = _bad_overlay_move(fen, "white", forbidden={"a7a8q"})
    board = chess.Board(fen)

    assert bad != "a7a8q"
    assert chess.Move.from_uci(bad) in board.legal_moves
