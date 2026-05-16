#!/usr/bin/env python3
"""Train the Experiment 6 neural network from Stockfish teacher labels.

Pipeline:

1. Collect positions: walk one or more replay JSONL files, pull each
   ``(fen, side_to_move)`` along the move sequence, and dedupe by
   FEN.
2. Label positions: call the local Stockfish binary at the supplied
   depth and record the centipawn evaluation from white's
   perspective (the same convention the network targets).
3. Train: pure-NumPy SGD with momentum on MSE loss in eval-cp
   space, batched over the labelled positions.
4. Save weights as a single ``.npz`` (NumPy compressed) at the path
   ``services/games/models/chess_experiment_6_neural.npz``.

Defaults are tuned for a small first run that fits in a few
minutes of CPU time. Production training should bump
``--positions``, ``--epochs``, and ``--depth`` and run on a
machine where Stockfish can use multiple threads.

This script is offline-only — runtime Exp6 inference never calls
Stockfish.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from collections import OrderedDict
from pathlib import Path

import chess
import numpy as np


_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from services.games.chess_neural import (  # noqa: E402
    EVAL_SCALE,
    HIDDEN_1_DIM,
    HIDDEN_2_DIM,
    INPUT_DIM,
    NeuralWeights,
    active_features,
    board_to_features,
    make_initial_weights,
    save_weights,
)
from services.games.chess_stockfish_teacher import (  # noqa: E402
    UciStockfish,
    analysis_limit,
    resolve_stockfish_path,
)


def _iter_replay_fens(paths: list[Path], max_positions: int) -> list[str]:
    """Walk replay JSONL files, push moves through ``chess.Board``,
    record FENs along the way until ``max_positions`` unique FENs
    are collected. Reservoir-style first-N, ordered by appearance.
    """
    seen: "OrderedDict[str, None]" = OrderedDict()
    for path in paths:
        if not path.exists():
            print(f"[exp6-train] skip missing replay: {path}", flush=True)
            continue
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except Exception:
                    continue
                moves = record.get("move_history") or record.get("moves") or []
                board = chess.Board()
                seen[board.fen()] = None
                if len(seen) >= max_positions:
                    return list(seen.keys())
                for entry in moves:
                    uci = entry.get("uci") if isinstance(entry, dict) else str(entry)
                    if not uci:
                        continue
                    try:
                        move = chess.Move.from_uci(uci)
                        if move not in board.legal_moves:
                            break
                        board.push(move)
                    except Exception:
                        break
                    seen[board.fen()] = None
                    if len(seen) >= max_positions:
                        return list(seen.keys())
    return list(seen.keys())


def _label_positions(
    fens: list[str],
    *,
    stockfish_path: str,
    depth: int,
    movetime_ms: int,
) -> list[tuple[str, float]]:
    """Probe each FEN with Stockfish and return (fen, cp_white)
    pairs. Skips positions Stockfish can't analyse (game over, etc.).
    """
    rows: list[tuple[str, float]] = []
    limit = analysis_limit(depth=int(depth), movetime_ms=int(movetime_ms))
    started = time.perf_counter()
    with UciStockfish(stockfish_path) as engine:
        for i, fen in enumerate(fens):
            try:
                board = chess.Board(fen)
            except Exception:
                continue
            if board.is_game_over():
                continue
            try:
                rows_pv = engine.analyse(board, limit=limit, multipv=1)
            except Exception as exc:
                print(f"[exp6-train] analyse failure at {fen[:40]}: {exc}", flush=True)
                continue
            if not rows_pv:
                continue
            row = rows_pv[0]
            # UciStockfish.analyse returns rows with ``teacher_eval_cp``
            # (signed cp from the side to move). Fall back to the legacy
            # ``score`` dict shape if a different teacher wrapper is
            # plugged in.
            cp_value = row.get("teacher_eval_cp")
            if cp_value is None:
                score = row.get("score")
                cp_value = _score_to_cp_value(score) if score is not None else None
            if cp_value is None:
                continue
            cp_white = float(cp_value) if board.turn == chess.WHITE else -float(cp_value)
            rows.append((fen, cp_white))
            if (i + 1) % 100 == 0:
                elapsed = time.perf_counter() - started
                print(f"[exp6-train] labelled {i+1}/{len(fens)} positions, {elapsed:.1f}s", flush=True)
    return rows


def _score_to_cp_value(score) -> float | None:
    """Convert a python-chess ``Score`` (or dict mirror) to a cp value
    from the side-to-move's perspective. Caller flips the sign to
    white-relative.

    Mate scores are clamped to a large but finite cp value so MSE
    training stays numerically stable.
    """
    if isinstance(score, dict):
        cp = score.get("cp")
        mate = score.get("mate")
    else:
        cp = getattr(score, "cp", None)
        mate = getattr(score, "mate", None)
    if cp is not None:
        return float(cp)
    if mate is not None:
        mate_value = int(mate)
        return math.copysign(2000.0, mate_value or 1)
    return None


def _build_dataset(rows: list[tuple[str, float]]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Pack labelled rows into dense arrays.

    Returns (features_sparse_idx, side_signs, labels) where:
    - features_sparse_idx is a list-of-lists of active indices per
      sample (variable-length; we densify in mini-batches);
    - side_signs is +1 for white-to-move, -1 for black-to-move;
    - labels is cp_white divided by EVAL_SCALE.
    """
    sparse_idx: list[np.ndarray] = []
    side_signs = np.empty(len(rows), dtype=np.float32)
    labels = np.empty(len(rows), dtype=np.float32)
    for i, (fen, cp_white) in enumerate(rows):
        board = chess.Board(fen)
        sparse_idx.append(np.asarray(active_features(board), dtype=np.int64))
        side_signs[i] = +1.0 if board.turn == chess.WHITE else -1.0
        labels[i] = float(cp_white) / EVAL_SCALE
    return sparse_idx, side_signs, labels


def _crelu(x: np.ndarray) -> np.ndarray:
    return np.clip(x, 0.0, 127.0)


def _crelu_grad(pre: np.ndarray) -> np.ndarray:
    return ((pre > 0.0) & (pre < 127.0)).astype(np.float32)


def _forward(batch_X: np.ndarray, weights: NeuralWeights):
    pre1 = batch_X @ weights.W1 + weights.b1
    h1 = _crelu(pre1)
    pre2 = h1 @ weights.W2 + weights.b2
    h2 = _crelu(pre2)
    y = h2 @ weights.W3 + weights.b3
    return pre1, h1, pre2, h2, y


def _backward(batch_X, side_signs, labels, weights, pre1, h1, pre2, h2, y):
    n = batch_X.shape[0]
    pred = y[:, 0]
    # Effective prediction in cp-units (network output × scale, then
    # signed by side-to-move). Loss is in white-cp scaled units (we
    # divided labels by EVAL_SCALE). Train against ``labels`` directly.
    err = pred - labels  # (n,)
    # dL/d_y = (2/n) * err  (MSE gradient).
    dy = (2.0 / n) * err.reshape(-1, 1)  # (n, 1)
    dW3 = h2.T @ dy             # (HIDDEN_2_DIM, 1)
    db3 = dy.sum(axis=0)        # (1,)
    dh2 = dy @ weights.W3.T     # (n, HIDDEN_2_DIM)
    dpre2 = dh2 * _crelu_grad(pre2)
    dW2 = h1.T @ dpre2          # (HIDDEN_1_DIM, HIDDEN_2_DIM)
    db2 = dpre2.sum(axis=0)
    dh1 = dpre2 @ weights.W2.T  # (n, HIDDEN_1_DIM)
    dpre1 = dh1 * _crelu_grad(pre1)
    dW1 = batch_X.T @ dpre1     # (INPUT_DIM, HIDDEN_1_DIM)
    db1 = dpre1.sum(axis=0)
    return dW1, db1, dW2, db2, dW3, db3


def _densify_batch(sparse_idx: list[np.ndarray], indices: np.ndarray) -> np.ndarray:
    X = np.zeros((indices.size, INPUT_DIM), dtype=np.float32)
    for row, src in enumerate(indices):
        X[row, sparse_idx[src]] = 1.0
    return X


def train(
    rows: list[tuple[str, float]],
    *,
    epochs: int,
    batch_size: int,
    lr: float,
    momentum: float,
    seed: int,
    init_weights: NeuralWeights | None = None,
) -> NeuralWeights:
    sparse_idx, side_signs, labels = _build_dataset(rows)
    weights = init_weights or make_initial_weights(seed=seed)
    rng = np.random.default_rng(seed)

    velocities = {
        "W1": np.zeros_like(weights.W1),
        "b1": np.zeros_like(weights.b1),
        "W2": np.zeros_like(weights.W2),
        "b2": np.zeros_like(weights.b2),
        "W3": np.zeros_like(weights.W3),
        "b3": np.zeros_like(weights.b3),
    }
    # Global per-tensor gradient norm clip. SGD with momentum on a
    # 768→256 layer is prone to exploding gradients when the network
    # is wide and the input is one-hot sparse — the first matmul
    # accumulates across ~32 active features, blowing the L1
    # pre-activation past the clipped-ReLU window in the first few
    # steps. Clipping each tensor's update keeps the optimizer
    # numerically stable until learning rate annealing kicks in.
    grad_clip = 1.0
    n_total = len(rows)
    for epoch in range(epochs):
        order = rng.permutation(n_total)
        epoch_loss = 0.0
        seen = 0
        for start in range(0, n_total, batch_size):
            batch_idx = order[start:start + batch_size]
            X = _densify_batch(sparse_idx, batch_idx)
            y = labels[batch_idx]
            pre1, h1, pre2, h2, out = _forward(X, weights)
            loss = float(((out[:, 0] - y) ** 2).mean())
            if not np.isfinite(loss):
                # Bail out gracefully on numerical blow-up; the caller
                # can re-try with a smaller lr.
                print(f"[exp6-train] non-finite loss at epoch {epoch+1}; aborting train.", flush=True)
                return weights
            epoch_loss += loss * batch_idx.size
            seen += batch_idx.size
            dW1, db1, dW2, db2, dW3, db3 = _backward(X, side_signs[batch_idx], y, weights, pre1, h1, pre2, h2, out)
            for name, grad in [("W1", dW1), ("b1", db1), ("W2", dW2), ("b2", db2), ("W3", dW3), ("b3", db3)]:
                norm = float(np.linalg.norm(grad))
                if norm > grad_clip:
                    grad = grad * (grad_clip / norm)
                velocities[name] = momentum * velocities[name] - lr * grad
                getattr(weights, name)[...] += velocities[name]
        if seen > 0:
            print(f"[exp6-train] epoch {epoch+1}/{epochs}  mean MSE (scaled cp): {epoch_loss / seen:.4f}", flush=True)
    return weights


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--replay",
        action="append",
        default=[],
        help="Replay JSONL files to walk for FENs. Repeatable.",
    )
    parser.add_argument("--positions", type=int, default=2000)
    parser.add_argument("--stockfish-path", default="")
    parser.add_argument("--depth", type=int, default=10)
    parser.add_argument("--movetime-ms", type=int, default=0)
    parser.add_argument("--epochs", type=int, default=12)
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--lr", type=float, default=0.01)
    parser.add_argument("--momentum", type=float, default=0.9)
    parser.add_argument("--seed", type=int, default=20260601)
    parser.add_argument(
        "--output",
        default="",
        help=(
            "Output .npz path. Empty (default) writes to the Exp6 "
            "runtime model path so training updates the online model "
            "rather than the read-only bundled seed."
        ),
    )
    parser.add_argument(
        "--cache-labels",
        default="",
        help="Optional JSONL file to cache (fen, cp_white) labels.",
    )
    args = parser.parse_args()

    stockfish_path = resolve_stockfish_path(str(args.stockfish_path or ""))
    if not stockfish_path:
        raise SystemExit("Stockfish binary not found; set --stockfish-path or STOCKFISH_PATH.")

    replay_paths = [Path(p) for p in args.replay]
    if not replay_paths:
        raise SystemExit("--replay <path>.jsonl is required (repeatable).")

    cache_path = Path(args.cache_labels) if args.cache_labels else None
    labelled: list[tuple[str, float]] = []
    if cache_path is not None and cache_path.exists():
        with cache_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                fen = rec.get("fen")
                cp_white = rec.get("cp_white")
                if fen and cp_white is not None:
                    labelled.append((str(fen), float(cp_white)))
        print(f"[exp6-train] loaded {len(labelled)} cached labels from {cache_path}", flush=True)

    if len(labelled) < args.positions:
        fens = _iter_replay_fens(replay_paths, args.positions)
        seen = {fen for fen, _cp in labelled}
        fens_to_label = [fen for fen in fens if fen not in seen][: args.positions - len(labelled)]
        print(
            f"[exp6-train] labelling {len(fens_to_label)} positions with stockfish (depth {args.depth})",
            flush=True,
        )
        new_rows = _label_positions(
            fens_to_label,
            stockfish_path=stockfish_path,
            depth=args.depth,
            movetime_ms=args.movetime_ms,
        )
        labelled.extend(new_rows)
        if cache_path is not None:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            with cache_path.open("a", encoding="utf-8") as handle:
                for fen, cp in new_rows:
                    handle.write(json.dumps({"fen": fen, "cp_white": cp}) + "\n")
            print(f"[exp6-train] appended {len(new_rows)} labels to {cache_path}", flush=True)

    if not labelled:
        raise SystemExit("no labelled positions; nothing to train.")
    print(f"[exp6-train] training on {len(labelled)} positions", flush=True)
    weights = train(
        labelled,
        epochs=int(args.epochs),
        batch_size=int(args.batch_size),
        lr=float(args.lr),
        momentum=float(args.momentum),
        seed=int(args.seed),
    )
    if args.output:
        out_path = Path(args.output)
    else:
        # Late import so the script still works in environments where
        # the runtime helpers can't import (e.g., bare external lab).
        from services.games.chess_exp6 import runtime_neural_weights_path
        out_path = runtime_neural_weights_path()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    save_weights(out_path, weights)
    print(f"[exp6-train] wrote weights to {out_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
