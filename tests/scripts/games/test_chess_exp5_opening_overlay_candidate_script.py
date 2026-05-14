from scripts.games.chess_exp5_opening_overlay_candidate import build_opening_overlay


def test_exp5_opening_overlay_builder_keeps_clean_legal_multigood_rows():
    rows = [
        {
            "id": "start",
            "fen": "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
            "side": "white",
            "label_quality": "clean",
            "expected_uci_any": ["e2e4", "d2d4", "bad"],
            "position_id": "ce30807049a23e2f3a9eb122e950cb3530814ac9ce92c77c89d7adbb6c8bd3c4",
        },
        {
            "id": "review",
            "fen": "8/8/8/8/8/8/8/8 w - - 0 1",
            "side": "white",
            "label_quality": "review",
            "expected_uci_any": ["a1a2"],
        },
    ]

    overlay = build_opening_overlay(rows)

    assert overlay["enabled"] is True
    assert overlay["build_summary"]["input_rows"] == 2
    assert overlay["build_summary"]["position_count"] == 1
    assert overlay["build_summary"]["skipped_rows"] == 1
    entry = overlay["positions"]["ce30807049a23e2f3a9eb122e950cb3530814ac9ce92c77c89d7adbb6c8bd3c4"]
    assert [move["uci"] for move in entry["moves"]] == ["e2e4", "d2d4"]
