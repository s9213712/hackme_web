# Exp5 v21 Fianchetto / Tail Audit

日期：2026-05-14

## 本階段目標

根據 50 題 held-out Stockfish validation 的缺口，嘗試加入兩類通用棋理特徵：

1. center-break：中心反擊、用中心兵打擊過度伸展的子力。
2. fianchetto development：側翼兵已推後，優先完成象翼/王翼 fianchetto 發展。

同時回應「最後幾步」的測試目的：新增 tail extraction，用完整對局最後 12 個 AI 決策來測殘局/轉換能力。

## 源碼變更

主要檔案：

- `services/games/chess_nnue.py`
- `scripts/games/chess_gauntlet_extract_positions.py`
- `scripts/INDEX.md`
- `scripts/CALL_MAP.md`

新增/調整 profile：

- `fixed_depth_center_break`
- `fixed_depth_fianchetto_development`
- `fixed_depth_center_fianchetto`

新增 eval / move compensation：

- `_center_break_score`
- `_fianchetto_development_score`
- `_center_break_move_bonus`
- `_fianchetto_development_move_bonus`

安全閘：

- fianchetto move bonus 不覆蓋同局面已有的 queen/bishop/knight checking resource。
- `_avoid_immediate_material_drop_filter` 可接受 profile-gated compensation，但預設 profile 不受影響。

## Center-Break 結果

center-break 能改善部分 gambit / center-counter 類問題，但補太寬後在其他 held-out 題退步：

| Profile | Clean | Review | Rejected | Avg CP Loss |
|---|---:|---:|---:|---:|
| `fixed_depth_center_break` | 35/50 | 12/50 | 3/50 | 51.04 |
| `fixed_depth_center_fianchetto` | 36/50 | 12/50 | 2/50 | 47.18 |

主要新增問題：在若干 gambit / human-probe 類題目中過度偏好中心反擊，導致發展與戰術資源排序退步。

結論：center-break 方向正確，但目前條件太寬，先不採用。

## Fianchetto 結果

第一次 fianchetto candidate：

- 50 題 held-out 改善。
- 但完整 gauntlet 在 Caro-Kann 白方局輸一局。
- 原因：某個中局檢查資源被 fianchetto 發展 bonus 蓋過，錯過戰術性先手。

加入 checking-resource safety gate 後得到 v21b。

## v21b 對照

### 50 題 Held-Out Stockfish Validation

不洩題原則：本節只列彙總統計，不列 held-out 題號、FEN、candidate move、teacher move 或逐題 CP loss。

| Profile | Clean | Review | Rejected | Top1 | Top3 | Top5 | Avg CP Loss |
|---|---:|---:|---:|---:|---:|---:|---:|
| `fixed_depth_piece_activity_midgame` | 36/50 | 12/50 | 2/50 | 13 | 24 | 31 | 44.16 |
| `fixed_depth_fianchetto_development` v21b | 37/50 | 12/50 | 1/50 | 14 | 25 | 32 | 40.00 |

證據：

- `docs/games/evidence/exp5/v21b_fianchetto_safe_heldout_validation_50_stockfish.json`
- `docs/games/evidence/exp5/v21b_fianchetto_safe_heldout_validation_50_stockfish.jsonl`

### 固定 30 局 Gauntlet

| Profile | W-D-L | Score Rate | Threefold | Avg ms/game | Avg plies |
|---|---:|---:|---:|---:|---:|
| v20 `fixed_depth_piece_activity_midgame` | 23-7-0 | 0.8833 | 0.2333 | 14830.712 | 78.27 |
| v21b `fixed_depth_fianchetto_development` | 23-7-0 | 0.8833 | 0.2333 | 15671.784 | 79.80 |

Advanced score with the same score-probe/tactical inputs:

| Profile | Normalized | Grade |
|---|---:|---|
| v20 | 90.1322 | `advanced_engine_candidate` |
| v21b | 90.1322 | `advanced_engine_candidate` |

證據：

- `docs/games/evidence/exp5/v21b_fianchetto_safe_full_gauntlet_30.json`
- `docs/games/evidence/exp5/v21b_fianchetto_safe_full_gauntlet_30.jsonl`
- `docs/games/evidence/exp5/v21b_fianchetto_safe_advanced_score_30s_fullinputs.json`

## Tail-12 Audit

依據：

- 取最後幾步是為了測殘局處理、勝勢轉換、三重複處理、逼和/拖局風險。
- 這不能代表完整佈局能力；完整佈局能力仍需更多 opening seeds 或外部 PGN/Stockfish 篩選局面。
- `12` 是折衷值：足夠覆蓋最後階段的關鍵決策，又不讓 Stockfish teacher 審核成本過高。

流程：

```text
chess_exp5_gauntlet.py full game JSONL
  -> chess_gauntlet_extract_positions.py --actor ai --tail-actor-moves 12
  -> 360 AI tail rows
  -> chess_stockfish_teacher_audit.py --sample-every 7 --max-positions 50
```

Tail audit 對照：

| Profile | Tail rows | Audited | Clean | Review | Rejected | Hard negatives |
|---|---:|---:|---:|---:|---:|---:|
| v20 | 360 | 50 | 28 | 11 | 11 | 9 |
| v21b | 360 | 50 | 31 | 10 | 9 | 7 |

證據：

- `docs/games/evidence/exp5/v20_piece_activity_midgame_gate700_tail12_stockfish_audit/summary.json`
- `docs/games/evidence/exp5/v21b_fianchetto_safe_tail12_stockfish_audit/summary.json`
- `docs/games/evidence/exp5/v21b_fianchetto_safe_tail12_ai_positions.jsonl`

註：tail raw rows 也視為敏感驗證材料；公開報告只使用 aggregate summary。

## 結論

v21b 不是固定分數突破版：advanced score 與 v20 相同，且速度略慢。因此不應把它描述成「明顯超越 v20」。

但 v21b 有兩個實質改善：

1. 50 題 held-out Stockfish validation 小幅改善：rejected 2 -> 1、avg cp loss 44.16 -> 40.00。
2. Tail-12 殘局/後段 audit 改善：clean 28 -> 31、rejected 11 -> 9。

目前建議：

- 保留 `fixed_depth_fianchetto_development` 作為 candidate profile。
- 不改 `EXP5_PRODUCTION_SEARCH_PROFILE`。
- 不採用 center-break profile。
- 下一步應專注 tail audit 的 rejected rows，改善殘局/轉換，而不是再調 opening 題。
