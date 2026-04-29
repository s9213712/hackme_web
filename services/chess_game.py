import copy

FILES = "abcdefgh"
RANKS = "12345678"
START_BOARD = {
    "a1": "R", "b1": "N", "c1": "B", "d1": "Q", "e1": "K", "f1": "B", "g1": "N", "h1": "R",
    "a2": "P", "b2": "P", "c2": "P", "d2": "P", "e2": "P", "f2": "P", "g2": "P", "h2": "P",
    "a7": "p", "b7": "p", "c7": "p", "d7": "p", "e7": "p", "f7": "p", "g7": "p", "h7": "p",
    "a8": "r", "b8": "n", "c8": "b", "d8": "q", "e8": "k", "f8": "b", "g8": "n", "h8": "r",
}
PIECE_LABELS = {
    "K": "白王", "Q": "白后", "R": "白車", "B": "白象", "N": "白馬", "P": "白兵",
    "k": "黑王", "q": "黑后", "r": "黑車", "b": "黑象", "n": "黑馬", "p": "黑兵",
}


def initial_board():
    return dict(START_BOARD)


def color_of(piece):
    if not piece:
        return None
    return "white" if piece.isupper() else "black"


def opponent(color):
    return "black" if color == "white" else "white"


def is_square(square):
    return isinstance(square, str) and len(square) == 2 and square[0] in FILES and square[1] in RANKS


def offset(square, df, dr):
    file_i = FILES.index(square[0]) + df
    rank_i = RANKS.index(square[1]) + dr
    if file_i < 0 or file_i >= 8 or rank_i < 0 or rank_i >= 8:
        return None
    return FILES[file_i] + RANKS[rank_i]


def normalize_board(board):
    if not isinstance(board, dict):
        return initial_board()
    clean = {}
    for square, piece in board.items():
        if is_square(square) and piece in PIECE_LABELS:
            clean[square] = piece
    return clean


def _slide_moves(board, square, color, directions):
    moves = []
    for df, dr in directions:
        cur = square
        while True:
            cur = offset(cur, df, dr)
            if not cur:
                break
            target = board.get(cur)
            if not target:
                moves.append(cur)
                continue
            if color_of(target) != color:
                moves.append(cur)
            break
    return moves


def pseudo_targets(board, square):
    piece = board.get(square)
    if not piece:
        return []
    color = color_of(piece)
    lower = piece.lower()
    if lower == "p":
        direction = 1 if color == "white" else -1
        start_rank = "2" if color == "white" else "7"
        moves = []
        one = offset(square, 0, direction)
        if one and not board.get(one):
            moves.append(one)
            two = offset(square, 0, direction * 2)
            if square[1] == start_rank and two and not board.get(two):
                moves.append(two)
        for df in (-1, 1):
            cap = offset(square, df, direction)
            if cap and board.get(cap) and color_of(board[cap]) != color:
                moves.append(cap)
        return moves
    if lower == "n":
        moves = []
        for df, dr in ((1, 2), (2, 1), (2, -1), (1, -2), (-1, -2), (-2, -1), (-2, 1), (-1, 2)):
            target = offset(square, df, dr)
            if target and color_of(board.get(target)) != color:
                moves.append(target)
        return moves
    if lower == "b":
        return _slide_moves(board, square, color, ((1, 1), (1, -1), (-1, 1), (-1, -1)))
    if lower == "r":
        return _slide_moves(board, square, color, ((1, 0), (-1, 0), (0, 1), (0, -1)))
    if lower == "q":
        return _slide_moves(board, square, color, ((1, 1), (1, -1), (-1, 1), (-1, -1), (1, 0), (-1, 0), (0, 1), (0, -1)))
    if lower == "k":
        moves = []
        for df in (-1, 0, 1):
            for dr in (-1, 0, 1):
                if df == 0 and dr == 0:
                    continue
                target = offset(square, df, dr)
                if target and color_of(board.get(target)) != color:
                    moves.append(target)
        return moves
    return []


def attacked_squares(board, by_color):
    attacked = set()
    for square, piece in board.items():
        if color_of(piece) != by_color:
            continue
        lower = piece.lower()
        if lower == "p":
            direction = 1 if by_color == "white" else -1
            for df in (-1, 1):
                target = offset(square, df, direction)
                if target:
                    attacked.add(target)
        elif lower == "k":
            for df in (-1, 0, 1):
                for dr in (-1, 0, 1):
                    if df == 0 and dr == 0:
                        continue
                    target = offset(square, df, dr)
                    if target:
                        attacked.add(target)
        else:
            attacked.update(pseudo_targets(board, square))
    return attacked


def king_piece(color):
    return "K" if color == "white" else "k"


def king_square(board, color):
    want = king_piece(color)
    for square, piece in board.items():
        if piece == want:
            return square
    return None


def in_check(board, color):
    king = king_square(board, color)
    if not king:
        return True
    return king in attacked_squares(board, opponent(color))


def apply_move_to_board(board, from_square, to_square, promotion=None):
    next_board = copy.deepcopy(board)
    piece = next_board.pop(from_square)
    captured = next_board.get(to_square)
    if piece.lower() == "p" and to_square[1] in {"1", "8"}:
        promoted = (promotion or "q").lower()
        if promoted not in {"q", "r", "b", "n"}:
            promoted = "q"
        piece = promoted.upper() if color_of(piece) == "white" else promoted
    next_board[to_square] = piece
    return next_board, captured


def legal_moves(board, color):
    board = normalize_board(board)
    if not king_square(board, color) or not king_square(board, opponent(color)):
        return []
    moves = []
    for from_square, piece in sorted(board.items()):
        if color_of(piece) != color:
            continue
        for to_square in pseudo_targets(board, from_square):
            if board.get(to_square) and color_of(board[to_square]) == color:
                continue
            if board.get(to_square) == king_piece(opponent(color)):
                continue
            next_board, captured = apply_move_to_board(board, from_square, to_square)
            if not in_check(next_board, color):
                moves.append({
                    "from": from_square,
                    "to": to_square,
                    "piece": piece,
                    "captured": captured,
                    "promotion": "q" if piece.lower() == "p" and to_square[1] in {"1", "8"} else None,
                })
    return moves


def validate_move(board, color, from_square, to_square, promotion=None):
    if not is_square(from_square) or not is_square(to_square):
        raise ValueError("棋格格式錯誤")
    board = normalize_board(board)
    piece = board.get(from_square)
    if not piece:
        raise ValueError("起點沒有棋子")
    if color_of(piece) != color:
        raise ValueError("現在不是這個棋子的回合")
    if board.get(to_square) == king_piece(opponent(color)):
        raise ValueError("不合法的走法：王不能被吃，必須以將死結束")
    for move in legal_moves(board, color):
        if move["from"] == from_square and move["to"] == to_square:
            next_board, captured = apply_move_to_board(board, from_square, to_square, promotion)
            move.update({"board": next_board, "captured": captured})
            return move
    raise ValueError("不合法的走法")


def game_status(board, turn):
    board = normalize_board(board)
    if not king_square(board, turn):
        return {"status": "finished", "winner_color": opponent(turn), "reason": "king_missing"}
    if not king_square(board, opponent(turn)):
        return {"status": "finished", "winner_color": turn, "reason": "king_missing"}
    moves = legal_moves(board, turn)
    if moves:
        return {"status": "active", "winner_color": None, "reason": "check" if in_check(board, turn) else ""}
    if in_check(board, turn):
        return {"status": "finished", "winner_color": opponent(turn), "reason": "checkmate"}
    return {"status": "finished", "winner_color": None, "reason": "stalemate"}


def board_rows(board):
    board = normalize_board(board)
    return [[board.get(file + rank, "") for file in FILES] for rank in reversed(RANKS)]
