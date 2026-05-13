"""P4 regression test: /api/community/boards returns correct counts in a
single aggregated query rather than 1 + 2N subqueries."""

import sqlite3

from tests.community.test_community_permissions import _build_app, _seed_community_db


def test_boards_list_returns_thread_and_post_counts(tmp_path):
    db_path = tmp_path / "community.db"
    ids = _seed_community_db(db_path)

    # Find the board that actually owns the seeded thread (the seed picks
    # the first existing board via LIMIT 1, which on a fresh DB is one of
    # the default seeded boards rather than the user-created "版面").
    conn = sqlite3.connect(db_path)
    try:
        thread_board_id = conn.execute(
            "SELECT board_id FROM forum_threads WHERE id=?", (ids["thread"],)
        ).fetchone()[0]
    finally:
        conn.close()

    actor_box = {"actor": {"id": 1, "username": "root", "role": "super_admin"}}
    client = _build_app(str(db_path), actor_box).test_client()

    payload = client.get("/api/community/boards").get_json()
    boards = payload["boards"]
    assert boards, "seed should leave at least one board"
    board = next(item for item in boards if item["id"] == thread_board_id)
    # Seed creates one approved thread with at least one reply post.
    assert board["thread_count"] == 1
    assert board["post_count"] >= 1
    # And the empty user-created board ("版面") should report zero/zero.
    empty_board = next(item for item in boards if item["title"] == "版面")
    assert empty_board["thread_count"] == 0
    assert empty_board["post_count"] == 0


def test_boards_list_counts_ignore_deleted(tmp_path):
    db_path = tmp_path / "community.db"
    ids = _seed_community_db(db_path)

    # Mark every thread + post under the board as deleted; counts must drop.
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("UPDATE forum_threads SET is_deleted=1")
        conn.execute("UPDATE forum_posts SET is_deleted=1")
        conn.commit()
    finally:
        conn.close()

    actor_box = {"actor": {"id": 1, "username": "root", "role": "super_admin"}}
    client = _build_app(str(db_path), actor_box).test_client()
    boards = client.get("/api/community/boards").get_json()["boards"]
    board = next(item for item in boards if item["title"] == "版面")
    assert board["thread_count"] == 0
    assert board["post_count"] == 0


def test_boards_list_counts_scale_to_many_boards(tmp_path):
    """When there are many boards the endpoint must still return correct
    counts (a regression suite proxy for the N+1 elimination)."""
    db_path = tmp_path / "community.db"
    _seed_community_db(db_path)

    # Add 5 more approved boards, each with a different known count.
    conn = sqlite3.connect(db_path)
    try:
        for idx in range(5):
            cur = conn.execute(
                "INSERT INTO forum_boards (category_id, title, description, rules, visibility, sort_order, "
                "last_activity_at, owner_user_id, owner_username, status, is_active, slug, created_at, updated_at) "
                "VALUES (1, ?, '', '', 'public', 100, '2026-01-01T00:00:00', 1, 'root', 'approved', 1, ?, "
                "'2026-01-01T00:00:00', '2026-01-01T00:00:00')",
                (f"擴充版-{idx}", f"board-extra-{idx}"),
            )
            board_id = cur.lastrowid
            for thread_idx in range(idx + 1):
                cur_t = conn.execute(
                    "INSERT INTO forum_threads (board_id, title, content, status, post_type, is_sticky, is_locked, "
                    "is_curated, view_count, is_deleted, author_user_id, author_username, created_at, updated_at) "
                    "VALUES (?, ?, '', 'approved', 'normal', 0, 0, 0, 0, 0, 1, 'root', "
                    "'2026-01-01T00:00:00', '2026-01-01T00:00:00')",
                    (board_id, f"thread-{thread_idx}"),
                )
                thread_id = cur_t.lastrowid
                # 2 posts per thread
                for _ in range(2):
                    conn.execute(
                        "INSERT INTO forum_posts (thread_id, content, is_pinned, is_hidden, is_deleted, "
                        "author_user_id, author_username, created_at, updated_at) "
                        "VALUES (?, '', 0, 0, 0, 1, 'root', "
                        "'2026-01-01T00:00:00', '2026-01-01T00:00:00')",
                        (thread_id,),
                    )
        conn.commit()
    finally:
        conn.close()

    actor_box = {"actor": {"id": 1, "username": "root", "role": "super_admin"}}
    client = _build_app(str(db_path), actor_box).test_client()
    boards = {b["title"]: b for b in client.get("/api/community/boards").get_json()["boards"]}
    for idx in range(5):
        b = boards[f"擴充版-{idx}"]
        assert b["thread_count"] == idx + 1
        assert b["post_count"] == (idx + 1) * 2
