import chess


FILES = "abcdefgh"
RANKS = "12345678"
FEN_KEY = "__fen__"
START_FEN = chess.STARTING_FEN
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
    return _board_to_state(chess.Board())


def color_of(piece):
    if not piece:
        return None
    return "white" if piece.isupper() else "black"


def opponent(color):
    return "black" if color == "white" else "white"


def is_square(square):
    return isinstance(square, str) and len(square) == 2 and square[0] in FILES and square[1] in RANKS


def normalize_board(board):
    if not isinstance(board, dict):
        return initial_board()
    clean = {}
    for square, piece in board.items():
        if is_square(square) and piece in PIECE_LABELS:
            clean[square] = piece
    if board.get(FEN_KEY):
        clean[FEN_KEY] = board.get(FEN_KEY)
    if clean == START_BOARD:
        clean[FEN_KEY] = START_FEN
    return clean


def _side_to_bool(color):
    return chess.WHITE if color == "white" else chess.BLACK


def _square_name(square):
    return chess.square_name(square)


def _board_to_state(board):
    state = {
        _square_name(square): piece.symbol()
        for square, piece in board.piece_map().items()
    }
    state[FEN_KEY] = board.fen()
    return state


def _board_from_state(state, turn=None):
    state = normalize_board(state)
    if state.get(FEN_KEY):
        try:
            board = chess.Board(state[FEN_KEY])
            if turn is not None:
                board.turn = _side_to_bool(turn)
            return board
        except Exception:
            pass
    board = chess.Board(None)
    for square, piece in state.items():
        if is_square(square) and piece in PIECE_LABELS:
            board.set_piece_at(chess.parse_square(square), chess.Piece.from_symbol(piece))
    if state == START_BOARD:
        board.castling_rights = chess.BB_A1 | chess.BB_H1 | chess.BB_A8 | chess.BB_H8
    else:
        board.castling_rights = 0
    board.turn = _side_to_bool(turn or "white")
    board.clear_stack()
    return board


def king_piece(color):
    return "K" if color == "white" else "k"


def king_square(board, color):
    board_obj = _board_from_state(board, color)
    square = board_obj.king(_side_to_bool(color))
    return _square_name(square) if square is not None else None


def in_check(board, color):
    board_obj = _board_from_state(board, color)
    if board_obj.king(_side_to_bool(color)) is None:
        return True
    return board_obj.is_check()


def _move_to_dict(board, move):
    piece = board.piece_at(move.from_square)
    captured = board.piece_at(move.to_square)
    if board.is_en_passant(move):
        capture_square = chess.square(chess.square_file(move.to_square), chess.square_rank(move.from_square))
        captured = board.piece_at(capture_square)
    return {
        "from": _square_name(move.from_square),
        "to": _square_name(move.to_square),
        "piece": piece.symbol() if piece else "",
        "captured": captured.symbol() if captured else None,
        "promotion": chess.piece_symbol(move.promotion) if move.promotion else None,
        "castle": bool(board.is_castling(move)),
        "en_passant": bool(board.is_en_passant(move)),
    }


def legal_moves(board, color):
    board_obj = _board_from_state(board, color)
    if board_obj.king(_side_to_bool(color)) is None or board_obj.king(_side_to_bool(opponent(color))) is None:
        return []
    moves = []
    for move in board_obj.legal_moves:
        target = board_obj.piece_at(move.to_square)
        if target and target.piece_type == chess.KING:
            continue
        moves.append(_move_to_dict(board_obj, move))
    return moves


def _uci_for_request(board, from_square, to_square, promotion=None):
    piece = board.piece_at(chess.parse_square(from_square))
    suffix = ""
    if piece and piece.piece_type == chess.PAWN and to_square[1] in {"1", "8"}:
        promoted = str(promotion or "q").lower()
        suffix = promoted if promoted in {"q", "r", "b", "n"} else "q"
    return f"{from_square}{to_square}{suffix}"


def apply_move_to_board(board, from_square, to_square, promotion=None, color=None):
    board_obj = _board_from_state(board, color)
    move = chess.Move.from_uci(_uci_for_request(board_obj, from_square, to_square, promotion))
    if move not in board_obj.legal_moves:
        raise ValueError("不合法的走法")
    info = _move_to_dict(board_obj, move)
    board_obj.push(move)
    return _board_to_state(board_obj), info["captured"]


def validate_move(board, color, from_square, to_square, promotion=None):
    if not is_square(from_square) or not is_square(to_square):
        raise ValueError("棋格格式錯誤")
    board_obj = _board_from_state(board, color)
    piece = board_obj.piece_at(chess.parse_square(from_square))
    if not piece:
        raise ValueError("起點沒有棋子")
    if color_of(piece.symbol()) != color:
        raise ValueError("現在不是這個棋子的回合")
    target_piece = board_obj.piece_at(chess.parse_square(to_square))
    if target_piece and target_piece.piece_type == chess.KING:
        raise ValueError("不合法的走法：王不能被吃，必須以將死結束")
    move = chess.Move.from_uci(_uci_for_request(board_obj, from_square, to_square, promotion))
    if move not in board_obj.legal_moves:
        raise ValueError("不合法的走法")
    info = _move_to_dict(board_obj, move)
    board_obj.push(move)
    info["board"] = _board_to_state(board_obj)
    return info


def game_status(board, turn):
    board_obj = _board_from_state(board, turn)
    if board_obj.king(_side_to_bool(turn)) is None:
        return {"status": "finished", "winner_color": opponent(turn), "reason": "king_missing"}
    if board_obj.king(_side_to_bool(opponent(turn))) is None:
        return {"status": "finished", "winner_color": turn, "reason": "king_missing"}
    if board_obj.is_checkmate():
        return {"status": "finished", "winner_color": opponent(turn), "reason": "checkmate"}
    if board_obj.is_stalemate():
        return {"status": "finished", "winner_color": None, "reason": "stalemate"}
    if board_obj.is_insufficient_material():
        return {"status": "finished", "winner_color": None, "reason": "insufficient_material"}
    if board_obj.is_seventyfive_moves():
        return {"status": "finished", "winner_color": None, "reason": "seventyfive_moves"}
    if board_obj.is_fivefold_repetition():
        return {"status": "finished", "winner_color": None, "reason": "fivefold_repetition"}
    return {"status": "active", "winner_color": None, "reason": "check" if board_obj.is_check() else ""}


def board_rows(board):
    state = normalize_board(board)
    return [[state.get(file + rank, "") for file in FILES] for rank in reversed(RANKS)]
