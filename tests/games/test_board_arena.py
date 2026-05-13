import json

from services.games.board_arena import (
    initial_board,
    play_board_ai_match,
    run_board_ai_benchmark,
    run_board_skill_suite,
    score_board,
    write_board_ai_benchmark_report,
)


def test_initial_board_and_score_helpers_are_game_scoped():
    reversi = initial_board("reversi")
    go = initial_board("go")
    gomoku = initial_board("gomoku")

    assert len(reversi) == 64
    assert score_board("reversi", reversi) == (2, 2)
    assert len(go) == 361
    assert score_board("go", go) == (0, 0)
    assert len(gomoku) == 225
    assert score_board("gomoku", gomoku) == (0, 0)


def test_play_board_ai_match_records_result_and_no_illegal_moves():
    match = play_board_ai_match("gomoku", "easy", "random", seed=7, max_plies=12)

    assert match["game_key"] == "gomoku"
    assert match["black_engine"] == "easy"
    assert match["white_engine"] == "random"
    assert match["result"] in {"black_win", "white_win", "draw"}
    assert match["plies"] <= 12
    assert match["illegal_moves"] == []
    assert "easy" in match["engine_timings"]


def test_skill_suite_quantifies_tactical_floor_by_engine():
    suite = run_board_skill_suite(["random", "normal"])

    assert suite["cases"] >= 8
    assert {row["game_key"] for row in suite["by_game"]} == {"go", "gomoku", "reversi"}
    normal = next(row for row in suite["by_engine"] if row["engine"] == "normal")
    random = next(row for row in suite["by_engine"] if row["engine"] == "random")
    assert normal["pass_rate"] >= random["pass_rate"]
    assert any(row["case_id"] == "block_open_four" for row in suite["results"])
    assert any(row["case_id"] == "build_open_four_threat" for row in suite["results"])
    assert any(row["case_id"] == "corner_priority" for row in suite["results"])


def test_board_ai_benchmark_reports_standings_elo_and_matrix():
    report = run_board_ai_benchmark(
        game_keys=["reversi"],
        engines=["random", "easy"],
        rounds=1,
        max_plies=12,
        seed=11,
    )

    assert report["games_played"] == 2
    assert report["games"] == ["reversi"]
    assert report["engines"] == ["random", "easy"]
    assert len(report["standings"]) == 2
    assert len(report["elo"]) == 2
    assert report["matrix"]["random"]["easy"]["games"] == 2
    assert report["skill_suite"]["cases"] >= 8


def test_write_board_ai_benchmark_report_writes_json(tmp_path):
    report = run_board_ai_benchmark(
        game_keys=["gomoku"],
        engines=["random", "easy"],
        rounds=1,
        max_plies=6,
        seed=13,
    )

    path = write_board_ai_benchmark_report(report, output_dir=tmp_path)

    assert path.exists()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["games_played"] == 2
    assert payload["games"] == ["gomoku"]
