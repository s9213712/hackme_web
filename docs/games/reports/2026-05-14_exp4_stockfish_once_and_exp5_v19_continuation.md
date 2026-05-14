# Exp4 Stockfish Once Compare and Exp5 v19 Continuation

日期：2026-05-14

## 結論摘要

- Exp4 Stockfish 篩選資料只做一次比較後停止：teacher-rank 有極小改善，但仍未形成可用棋力提升；目前判斷瓶頸偏向 retrain/採用策略，不是單純樣本品質。
- Exp5 已接受的 v19 修正把 current/v18 類狀態從 `15W/11D/4L` 拉回 `21W/9D/0L`，advanced score `88.1035/100`。
- v19 仍未超過 v17：v17 參考為 `24W/6D/0L`、約 `90.94/100`，但 Stockfish audit 顯示 v17 有部分過擬合或不乾淨走法，不能盲目回退。
- 兩個新候選已拒絕：
  - broad forced mate search：能抓部分 mate-in-3/5，但 10 局焦點組無淨增益且耗時升高。
  - flank drift fullmove 13：start 變好，但 queen_pawn / early_queen 退步，總分下降。

## Exp4 單次比較

Evidence：

- `docs/games/evidence/stockfish_teacher/exp4_once_compare_2026-05-14.json`

結果：

| 指標 | retrain 前 | retrain 後 | 判讀 |
|---|---:|---:|---|
| avg expected rank | `12.2222` | `11.4444` | 微幅改善 |
| top1 hits | `0` | `0` | 無改善 |
| top3 hits | `0` | `1` | 微幅改善 |
| top5 hits | `1` | `2` | 微幅改善 |

結論：這不足以證明 Exp4 棋力實質上升，因此本階段停止 Exp4 retrain。前面較大的 Exp3/Exp4 retrain 也出現 checkpoint regression，支持「資料篩選有幫助，但 retrain 目標與採用策略仍不可靠」的判斷。

## Exp5 已接受修正

已保留在 `services/games/chess_nnue.py` 的修正：

- special-rule / high-value priority move 加入 mate-in-one safety，避免優先吃子繞過安全檢查。
- opening material floor 降低為開局 `180cp`，更容易拒絕開局中被戰術打爆的表面好手。
- near-flank double pawn drift 在原本 opening 窗口內納入過濾，修掉 queen_pawn 中的 `...b5` 類漂移。
- bare-king conversion filter 保留，但加入大子不被下一手直接吃掉的安全檢查，用於 KQK/KRK 類收官。
- 新增 `scripts/games/chess_gauntlet_extract_positions.py`，把 gauntlet replay 轉成可給 Stockfish audit 的 per-position rows。

Evidence：

- `docs/games/evidence/exp5/v19_priority_safety_opening_floor_wing_full_gauntlet_30.json`
- `docs/games/evidence/exp5/v19_priority_safety_opening_floor_wing_advanced_score_30s_runtime.json`
- `docs/games/evidence/exp5/v19_bare_king_conversion_safe_scandinavian.json`
- `docs/games/evidence/exp5/v19_bare_king_conversion_safe_full_gauntlet_30.json`
- `docs/games/evidence/exp5/v19_bare_king_conversion_safe_advanced_score_30s_runtime.json`
- `docs/games/evidence/exp5/v19_accepted_after_rejected_candidates_focus_6.json`

分數：

| 版本 / 候選 | 30 局 gauntlet | threefold | avg ms/game | advanced score | 判讀 |
|---|---:|---:|---:|---:|---|
| current/v18 probe | `15W/11D/4L` | `36.67%` | `12836.755` | 未重算 | 不可接受 |
| v19 priority+opening+wing | `20W/10D/0L` | `33.33%` | `14977.053` | `87.0894` | 改善 |
| v19 bare-safe accepted | `21W/9D/0L` | `30.00%` | `14973.033` | `88.1035` | 目前採用 |
| v17 reference | `24W/6D/0L` | `20.00%` | `14024.485` | `90.9406` | 分數較高但有 Stockfish-rejected move |

撤回失敗候選後的 sanity focus：`early_queen_probe, queen_pawn, scandinavian`
共 `6W/0D/0L`，確認目前工作樹仍符合 accepted 行為。

## Stockfish 差異與和局審核

Evidence：

- `docs/games/evidence/stockfish_teacher/exp5_v17_current_divergence_audit_2026-05-14/`
- `docs/games/evidence/stockfish_teacher/exp5_v19_bare_safe_draw_ai_moves_2026-05-14.jsonl`
- `docs/games/evidence/stockfish_teacher/exp5_v19_bare_safe_draw_ai_moves_audit_2026-05-14/`

v17/current divergence 結論：

- v17 在 early_queen probe 的 `...Bc5` 被 Stockfish 判為 rejected；current 的 `...Nf6` 反而乾淨。
- 因此 v17 分數雖高，但不能直接回退；應該抽取有效結構，而不是恢復所有 v17 行為。

v19 accepted draw audit：

- 抽出 `9` 局和棋中的 `504` 個 AI 決策。
- Stockfish depth 8 MultiPV audit：`324 clean / 89 review / 91 rejected`。
- 多數和棋是 Exp5 物質落後下守和，不能全面禁止三重複。
- 有少數 missed forced mate，但 broad mate search 會改壞其他線，未採用。

## 已拒絕候選

### Broad Forced Mate Search

Evidence：

- `docs/games/evidence/exp5/v19_forced_mate_search_focus_10.json`
- `docs/games/evidence/exp5/v19_forced_mate_search_repetition_safe_focus_10.json`
- `docs/games/evidence/stockfish_teacher/exp5_v19_forced_mate_focus_queen_pawn_draw_ai_moves_audit_2026-05-14/`

結果：

- 原版：`8W/2D/0L`，avg `17502.069ms`
- 加入 repetition-aware 後：`8W/2D/0L`，avg `19777.5ms`
- open_game 有改善，但 queen_pawn 被改成三重複和棋，沒有淨收益。

判定：拒絕。這類能力需要更可靠的 PV continuation 或真正 search/value 升級，不能用早期 return 的 broad filter 處理。

### Flank Drift Window 13

Evidence：

- `docs/games/evidence/exp5/v19_flank_drift_13_focus_10.json`

結果：

- `6W/4D/0L`，avg `15638.689ms`
- start 變成 `2W/0D`，但 queen_pawn 退成 `0W/2D`，early_queen 退成 `1W/1D`。

判定：拒絕。側翼兵限制不能單純延長；需要局面條件或 Stockfish-backed opening table。

## 腳本調用地圖補充

新增工具：

- `scripts/games/chess_gauntlet_extract_positions.py`

本階段主要鏈路：

```text
chess_exp5_gauntlet.py
  -> gauntlet JSON/JSONL
  -> chess_gauntlet_extract_positions.py --actor ai --result draw
  -> chess_stockfish_teacher_audit.py --stockfish-path /home/s92137/reference_repos/Stockfish/src/stockfish
  -> stockfish_audit_detail.jsonl / summary.json / teacher rows
```

`scripts/INDEX.md` 與 `scripts/CALL_MAP.md` 已加入此鏈路。

## 下一步建議

1. 保留目前 v19 accepted code path，不採用 forced mate search 與 flank13。
2. 若要追 `90+`，不要再加 broad filter；應建立 Stockfish-backed opening/PV continuation table，且只允許通過完整 gauntlet 的小型 overlay。
3. Exp3/Exp4 retrain 暫停大規模投入；先修 retrain gate、loss/採用策略，再談更多 Stockfish rows。
4. Exp5 的真上限仍在 search/eval 結構：depth-2 + filter stack 已接近本測試上限，下一階應該是 search-aware PV continuation、外部 UCI baseline、或受控 opening/endgame table。
