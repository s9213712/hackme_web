# exp4_16 vs exp5_08 diagnostic sparring smoke

## 目的

用 exp4_16 的 checkpoint@20 candidate 與 exp5_08 stage candidate 做 6 局 diagnostic smoke。這不是 promotion evidence，也不是 strength evidence；目的只是在實戰呼叫路徑中觀察：

- exp4_16 rule-aware final fusion 是否真的進入 `choose_experiment_pv_move` 實戰路徑。
- short castle / en-passant / promotion 類 special-rule 是否仍有 subtype 問題。
- exp4 / exp5 adapter audit hook 是否完整。

## 實驗命令

```bash
python3 scripts/games/chess_exp4_vs_exp5_sparring.py \
  --non-interactive \
  --mode smoke \
  --exp4-model-path <chess_results>/exp4_16_rule_aware_final_fusion_locked/exp4/checkpoints/20/exp4_quick_candidate_model.json \
  --exp5-model-path <chess_results>/exp5_08_stage_candidate/chess_experiment_5_nnue_stage_candidate.json \
  --output-root <chess_results> \
  --max-plies 80 \
  --search-profile-exp4 balanced \
  --search-profile-exp5 fixed_depth_strong
```

結果目錄：

- `<chess_results>/exp4_vs_exp5_smoke_20260512_032501`

## Gate 語意

`gate_state.json` 明確標記：

- `diagnostic_only=true`
- `can_use_as_promotion_evidence=false`
- `can_use_as_strength_evidence=false`
- `production_model_unchanged=true`
- exp4 使用 `balanced`，仍接受 time-budget variance。
- exp5 使用 `fixed_depth_strong`，是 deterministic profile。

## 實際結果

總表：

- exp4 win：3
- exp5 win：0
- draw：3
- illegal：0
- exp4 audit coverage：65/65 = 1.0
- exp5 audit coverage：60/60 = 1.0
- first move vs objective expected：3 hit / 3 miss

Cluster：

- tactic：3 games，exp4 win 2，draw 1
- special_rule：2 games，exp4 win 1，draw 1
- endgame：1 game，draw 1

## 關鍵觀察

### 1. Rule-aware adoption 已進入實戰路徑

exp4 在 sparring 中多次由 `rule_aware_final_fusion_bonus` 決策：

- `smoke_03_castle_kingside_white` ply 0：`e1c1`
- `smoke_04_castle_kingside_black` ply 0：`e8c8`
- promotion / underpromotion 多個 case 也觸發 rule-aware final fusion。

這代表 exp4_16 的修正不是只在 `explain` 報告裡有效，實戰 `choose` 路徑也確實使用 rule-aware fusion。

### 2. 但 special-rule subtype 仍未解

這輪暴露的重點不是「會不會 castling / promotion」，而是「選哪一種 subtype」：

- 白方 expected `e1g1`，exp4 選 `e1c1`。
- 黑方 expected `e8g8`，exp4 選 `e8c8`。
- promotion-to-queen seed 中，sparring artifact 記錄 exp4 實際輸出 `e7e8r`，但 audit 的 rule guard 記 `e7e8q`。

這和 exp4_16 gate 裡 `promotion_white_knight_mate` 選成 `e7e8r` 是同一類問題：special move adoption 已解，subtype selection 未解。

### 3. exp4 balanced profile 仍有 time-budget variance

同一 promotion-to-queen FEN 在直接重測時，`choose_experiment_pv_move` 多數會回 `e7e8q`，但 sparring artifact 曾記錄 `e7e8r`。因 exp4 sparring 仍用 `balanced` time-budget profile，這份結果不能當 deterministic strength evidence。

後續若要做 fair smoke，應新增或使用 exp4 fixed-depth profile，或讓 sparring script 對 exp4 也使用 deterministic decision path。

### 4. exp5 的目前訊號

exp5 在這 6 局 smoke 中沒有 illegal，也沒有 audit error。但此 smoke 不適合拿來比較勝率：

- mate-in-1 forced fixtures 會偏向先手一方。
- exp4/exp5 起始局面不是嚴格對稱 strength match。
- exp4 使用 time-budget profile，exp5 使用 fixed-depth profile。

## 結果判讀

這輪支持兩個結論：

1. exp4_16 可以作為 exp4-vs-exp5 diagnostic sparring 的 exp4 candidate。
2. exp4 下一個主要 blocker 應定義為 special-rule subtype selection，而不只是 special-rule adoption。

不應從這輪推出：

- exp4 比 exp5 強。
- exp4 可以 promotion。
- exp4 special-rule 已完成。

## 後續方向

建議 exp4_17 聚焦：

1. castling side selection：
   - kingside vs queenside 不可只共用 `castling` bonus。
   - 報告需拆 `castling_short` / `castling_long`。

2. promotion piece subtype：
   - queen promotion、knight mate、rook/bishop underpromotion 不可只共用 `promotion` / `underpromotion` bonus。
   - mate / stalemate / material context 要進 final fusion tie-breaker。

3. sparring deterministic profile：
   - 為 exp4 增加 `fixed_depth_*` profile，或在 sparring 中強制使用 deterministic path。
   - 否則 smoke 只能當 diagnostic，不能當 strength evidence。

4. 後續 12 局 fair smoke：
   - 移除 mate-in-1 forced fixture 的 strength scoring。
   - 改 opening mirror x4、K+P endgame mirror x4、special-rule mirror x4。
