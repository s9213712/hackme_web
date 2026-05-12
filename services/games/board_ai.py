import hashlib
import math
import random


BOARD_AI_GAME_KEYS = {"reversi", "go", "gomoku"}
BOARD_AI_DIFFICULTIES = {"easy", "normal", "hard"}
BOARD_AI_SIZES = {
    "reversi": 8,
    "go": 9,
    "gomoku": 15,
}
COLORS = {"black", "white"}
EMPTY = ""


def opponent(color):
    return "white" if color == "black" else "black"


def choose_board_game_ai_move(game_key, board, turn, difficulty="normal"):
    game_key = str(game_key or "").strip().lower()
    if game_key not in BOARD_AI_GAME_KEYS:
        raise ValueError("不支援的棋類 AI")
    difficulty = str(difficulty or "normal").strip().lower()
    if difficulty not in BOARD_AI_DIFFICULTIES:
        raise ValueError("不支援的 AI 難度")
    turn = _normalize_color(turn)
    size = BOARD_AI_SIZES[game_key]
    board = _normalize_board(board, size)
    if game_key == "reversi":
        return _choose_reversi_move(board, turn, difficulty)
    if game_key == "gomoku":
        return _choose_gomoku_move(board, turn, difficulty)
    return _choose_go_move(board, turn, difficulty)


def _normalize_color(value):
    color = str(value or "").strip().lower()
    if color not in COLORS:
        raise ValueError("棋色格式錯誤")
    return color


def _normalize_board(board, size):
    if not isinstance(board, list) or len(board) != size * size:
        raise ValueError("棋盤格式錯誤")
    normalized = []
    for value in board:
        cell = "" if value is None else str(value).strip().lower()
        if cell not in {"", "black", "white"}:
            raise ValueError("棋盤內容格式錯誤")
        normalized.append(cell)
    return tuple(normalized)


def _idx(x, y, size):
    return y * size + x


def _xy(index, size):
    return index % size, index // size


def _in_bounds(x, y, size):
    return 0 <= x < size and 0 <= y < size


def _neighbors(index, size):
    x, y = _xy(index, size)
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        nx, ny = x + dx, y + dy
        if _in_bounds(nx, ny, size):
            yield _idx(nx, ny, size)


def _decision(game_key, turn, difficulty, action, move=None, score=0, reason=""):
    payload = {
        "game_key": game_key,
        "turn": turn,
        "difficulty": difficulty,
        "action": action,
        "score": int(round(score)),
        "reason": reason,
    }
    if move is not None:
        size = BOARD_AI_SIZES[game_key]
        x, y = _xy(move, size)
        payload["move"] = {"index": int(move), "x": x, "y": y}
    return payload


REVERSI_DIRS = (
    (1, 0), (-1, 0), (0, 1), (0, -1),
    (1, 1), (1, -1), (-1, 1), (-1, -1),
)


def reversi_flips(board, index, color):
    size = BOARD_AI_SIZES["reversi"]
    if board[index]:
        return []
    other = opponent(color)
    x, y = _xy(index, size)
    flips = []
    for dx, dy in REVERSI_DIRS:
        line = []
        nx, ny = x + dx, y + dy
        while _in_bounds(nx, ny, size) and board[_idx(nx, ny, size)] == other:
            line.append(_idx(nx, ny, size))
            nx += dx
            ny += dy
        if line and _in_bounds(nx, ny, size) and board[_idx(nx, ny, size)] == color:
            flips.extend(line)
    return flips


def reversi_legal_moves(board, color):
    return [index for index, value in enumerate(board) if not value and reversi_flips(board, index, color)]


def reversi_apply_move(board, index, color):
    flips = reversi_flips(board, index, color)
    if not flips:
        return None
    next_board = list(board)
    next_board[index] = color
    for flip_index in flips:
        next_board[flip_index] = color
    return tuple(next_board)


def _reversi_terminal(board):
    return not any(not cell for cell in board) or (
        not reversi_legal_moves(board, "black") and not reversi_legal_moves(board, "white")
    )


def _reversi_eval(board, color):
    other = opponent(color)
    disc_diff = board.count(color) - board.count(other)
    mobility = len(reversi_legal_moves(board, color)) - len(reversi_legal_moves(board, other))
    corners = (0, 7, 56, 63)
    corner_score = sum(1 for index in corners if board[index] == color) - sum(1 for index in corners if board[index] == other)
    edge_indices = set(range(8)) | set(range(56, 64)) | {i * 8 for i in range(8)} | {i * 8 + 7 for i in range(8)}
    edge_score = sum(1 for index in edge_indices if board[index] == color) - sum(1 for index in edge_indices if board[index] == other)
    x_squares = (9, 14, 49, 54)
    x_penalty = sum(1 for index in x_squares if board[index] == color) - sum(1 for index in x_squares if board[index] == other)
    if _reversi_terminal(board):
        return disc_diff * 1000
    return disc_diff * 3 + mobility * 18 + corner_score * 120 + edge_score * 8 - x_penalty * 28


def _reversi_search(board, turn, depth, root_color, alpha, beta):
    if depth <= 0 or _reversi_terminal(board):
        return _reversi_eval(board, root_color)
    moves = reversi_legal_moves(board, turn)
    if not moves:
        return _reversi_search(board, opponent(turn), depth - 1, root_color, alpha, beta)
    maximizing = turn == root_color
    if maximizing:
        value = -math.inf
        for move in _ordered_reversi_moves(board, moves, turn):
            value = max(value, _reversi_search(reversi_apply_move(board, move, turn), opponent(turn), depth - 1, root_color, alpha, beta))
            alpha = max(alpha, value)
            if alpha >= beta:
                break
        return value
    value = math.inf
    for move in _ordered_reversi_moves(board, moves, turn):
        value = min(value, _reversi_search(reversi_apply_move(board, move, turn), opponent(turn), depth - 1, root_color, alpha, beta))
        beta = min(beta, value)
        if alpha >= beta:
            break
    return value


def _ordered_reversi_moves(board, moves, color):
    corners = {0, 7, 56, 63}
    return sorted(moves, key=lambda move: (move not in corners, -len(reversi_flips(board, move, color)), move))


def _choose_reversi_move(board, turn, difficulty):
    moves = reversi_legal_moves(board, turn)
    if not moves:
        action = "finish" if not reversi_legal_moves(board, opponent(turn)) else "pass"
        return _decision("reversi", turn, difficulty, action, reason="no-legal-move")
    depth = {"easy": 1, "normal": 2, "hard": 4}[difficulty]
    best_move = None
    best_score = -math.inf
    for move in _ordered_reversi_moves(board, moves, turn):
        next_board = reversi_apply_move(board, move, turn)
        score = _reversi_search(next_board, opponent(turn), depth - 1, turn, -math.inf, math.inf)
        if score > best_score or (score == best_score and (best_move is None or move < best_move)):
            best_move = move
            best_score = score
    return _decision("reversi", turn, difficulty, "move", best_move, best_score, "alpha-beta")


GOMOKU_DIRS = ((1, 0), (0, 1), (1, 1), (1, -1))


def gomoku_has_five(board, index, color):
    size = BOARD_AI_SIZES["gomoku"]
    x, y = _xy(index, size)
    for dx, dy in GOMOKU_DIRS:
        total = 1
        for sign in (1, -1):
            nx, ny = x + dx * sign, y + dy * sign
            while _in_bounds(nx, ny, size) and board[_idx(nx, ny, size)] == color:
                total += 1
                nx += dx * sign
                ny += dy * sign
        if total >= 5:
            return True
    return False


def gomoku_candidate_moves(board, difficulty="normal"):
    size = BOARD_AI_SIZES["gomoku"]
    stones = [index for index, value in enumerate(board) if value]
    if not stones:
        return [_idx(size // 2, size // 2, size)]
    radius = 1 if difficulty == "easy" else 2
    candidates = set()
    for stone in stones:
        sx, sy = _xy(stone, size)
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                nx, ny = sx + dx, sy + dy
                if _in_bounds(nx, ny, size):
                    index = _idx(nx, ny, size)
                    if not board[index]:
                        candidates.add(index)
    center = (size - 1) / 2
    return sorted(candidates, key=lambda index: (abs(_xy(index, size)[0] - center) + abs(_xy(index, size)[1] - center), index))


def _gomoku_apply_move(board, index, color):
    if board[index]:
        return None
    next_board = list(board)
    next_board[index] = color
    return tuple(next_board)


def _gomoku_window_score(count):
    return (0, 4, 24, 180, 1400, 100000)[count]


def _gomoku_eval(board, color):
    other = opponent(color)
    size = BOARD_AI_SIZES["gomoku"]
    score = 0
    for y in range(size):
        for x in range(size):
            for dx, dy in GOMOKU_DIRS:
                end_x = x + dx * 4
                end_y = y + dy * 4
                if not _in_bounds(end_x, end_y, size):
                    continue
                window = [board[_idx(x + dx * step, y + dy * step, size)] for step in range(5)]
                own = window.count(color)
                theirs = window.count(other)
                if own and theirs:
                    continue
                if own:
                    score += _gomoku_window_score(own)
                elif theirs:
                    score -= _gomoku_window_score(theirs) * 1.2
    return score


def _find_gomoku_winning_move(board, color, candidates):
    for move in candidates:
        next_board = _gomoku_apply_move(board, move, color)
        if next_board and gomoku_has_five(next_board, move, color):
            return move
    return None


def _gomoku_search(board, turn, depth, root_color, alpha, beta, difficulty):
    candidates = gomoku_candidate_moves(board, difficulty)
    if depth <= 0 or not candidates:
        return _gomoku_eval(board, root_color)
    limit = {"easy": 8, "normal": 14, "hard": 22}[difficulty]
    candidates = sorted(candidates, key=lambda move: _gomoku_eval(_gomoku_apply_move(board, move, turn), turn), reverse=True)[:limit]
    maximizing = turn == root_color
    if maximizing:
        value = -math.inf
        for move in candidates:
            next_board = _gomoku_apply_move(board, move, turn)
            if gomoku_has_five(next_board, move, turn):
                return 1000000
            value = max(value, _gomoku_search(next_board, opponent(turn), depth - 1, root_color, alpha, beta, difficulty))
            alpha = max(alpha, value)
            if alpha >= beta:
                break
        return value
    value = math.inf
    for move in candidates:
        next_board = _gomoku_apply_move(board, move, turn)
        if gomoku_has_five(next_board, move, turn):
            return -1000000
        value = min(value, _gomoku_search(next_board, opponent(turn), depth - 1, root_color, alpha, beta, difficulty))
        beta = min(beta, value)
        if alpha >= beta:
            break
    return value


def _choose_gomoku_move(board, turn, difficulty):
    candidates = gomoku_candidate_moves(board, difficulty)
    if not candidates:
        return _decision("gomoku", turn, difficulty, "finish", reason="board-full")
    own_win = _find_gomoku_winning_move(board, turn, candidates)
    if own_win is not None:
        return _decision("gomoku", turn, difficulty, "move", own_win, 1000000, "win-now")
    block = _find_gomoku_winning_move(board, opponent(turn), candidates)
    if block is not None:
        return _decision("gomoku", turn, difficulty, "move", block, 900000, "block-five")
    depth = {"easy": 1, "normal": 1, "hard": 2}[difficulty]
    limit = {"easy": 8, "normal": 16, "hard": 24}[difficulty]
    best_move = None
    best_score = -math.inf
    ordered = sorted(candidates, key=lambda move: _gomoku_eval(_gomoku_apply_move(board, move, turn), turn), reverse=True)[:limit]
    for move in ordered:
        next_board = _gomoku_apply_move(board, move, turn)
        score = _gomoku_search(next_board, opponent(turn), depth - 1, turn, -math.inf, math.inf, difficulty)
        if score > best_score or (score == best_score and (best_move is None or move < best_move)):
            best_move = move
            best_score = score
    return _decision("gomoku", turn, difficulty, "move", best_move, best_score, "pattern-search")


def go_group_and_liberties(board, start):
    size = BOARD_AI_SIZES["go"]
    color = board[start]
    group = set()
    liberties = set()
    stack = [start]
    while stack:
        current = stack.pop()
        if current in group:
            continue
        group.add(current)
        for neighbor in _neighbors(current, size):
            value = board[neighbor]
            if not value:
                liberties.add(neighbor)
            elif value == color and neighbor not in group:
                stack.append(neighbor)
    return group, liberties


def go_apply_move(board, index, color):
    size = BOARD_AI_SIZES["go"]
    if board[index]:
        return None, 0
    next_board = list(board)
    next_board[index] = color
    captured = 0
    other = opponent(color)
    for neighbor in _neighbors(index, size):
        if next_board[neighbor] != other:
            continue
        group, liberties = go_group_and_liberties(tuple(next_board), neighbor)
        if not liberties:
            captured += len(group)
            for stone in group:
                next_board[stone] = EMPTY
    own_group, own_liberties = go_group_and_liberties(tuple(next_board), index)
    if not own_liberties and captured == 0:
        return None, 0
    return tuple(next_board), captured


def go_legal_moves(board, color):
    moves = []
    for index, value in enumerate(board):
        if value:
            continue
        next_board, _captured = go_apply_move(board, index, color)
        if next_board is not None:
            moves.append(index)
    return moves


def _go_area_eval(board, color):
    size = BOARD_AI_SIZES["go"]
    other = opponent(color)
    score = board.count(color) * 9 - board.count(other) * 9
    for index, value in enumerate(board):
        if value:
            continue
        adj = [board[n] for n in _neighbors(index, size)]
        if color in adj and other not in adj:
            score += 2
        elif other in adj and color not in adj:
            score -= 2
    return score


def _go_move_heuristic(board, move, color):
    next_board, captured = go_apply_move(board, move, color)
    if next_board is None:
        return -math.inf
    group, liberties = go_group_and_liberties(next_board, move)
    adjacent_allies = sum(1 for neighbor in _neighbors(move, BOARD_AI_SIZES["go"]) if board[neighbor] == color)
    adjacent_enemies = sum(1 for neighbor in _neighbors(move, BOARD_AI_SIZES["go"]) if board[neighbor] == opponent(color))
    x, y = _xy(move, BOARD_AI_SIZES["go"])
    center_bias = 8 - abs(x - 4) - abs(y - 4)
    return captured * 120 + len(liberties) * 8 + adjacent_allies * 6 + adjacent_enemies * 3 + center_bias + _go_area_eval(next_board, color)


def _seed_for_go(board, color, difficulty):
    payload = "|".join(board) + f"|{color}|{difficulty}"
    return int(hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12], 16)


def _go_rollout_score(board, color, rng, depth):
    current = board
    turn = opponent(color)
    passes = 0
    for _step in range(depth):
        moves = go_legal_moves(current, turn)
        if not moves:
            passes += 1
            if passes >= 2:
                break
            turn = opponent(turn)
            continue
        passes = 0
        ranked = sorted(moves, key=lambda move: _go_move_heuristic(current, move, turn), reverse=True)
        move = rng.choice(ranked[: min(6, len(ranked))])
        current, _captured = go_apply_move(current, move, turn)
        turn = opponent(turn)
    return _go_area_eval(current, color)


def _choose_go_move(board, turn, difficulty):
    moves = go_legal_moves(board, turn)
    if not moves:
        return _decision("go", turn, difficulty, "pass", reason="no-legal-move")
    base_scores = [(move, _go_move_heuristic(board, move, turn)) for move in moves]
    base_scores.sort(key=lambda item: (-item[1], item[0]))
    if difficulty == "easy":
        move, score = base_scores[0]
        return _decision("go", turn, difficulty, "move", move, score, "capture-heuristic")
    candidate_limit = 14 if difficulty == "normal" else 22
    rollout_count = 2 if difficulty == "normal" else 4
    rollout_depth = 10 if difficulty == "normal" else 16
    rng = random.Random(_seed_for_go(board, turn, difficulty))
    best_move = None
    best_score = -math.inf
    for move, heuristic_score in base_scores[:candidate_limit]:
        next_board, _captured = go_apply_move(board, move, turn)
        rollout_score = sum(_go_rollout_score(next_board, turn, rng, rollout_depth) for _ in range(rollout_count)) / rollout_count
        score = heuristic_score + rollout_score
        if score > best_score or (score == best_score and (best_move is None or move < best_move)):
            best_move = move
            best_score = score
    return _decision("go", turn, difficulty, "move", best_move, best_score, "mcts-rollout")
