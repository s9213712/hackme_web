# Exp5 v24 Castle-Guard

日期：2026-05-14

## 不洩題原則

本報告只保留彙總數據與泛化原因，不公開 FEN、走法、teacher PV、逐題結果、完整 replay 或可還原題目的內容。raw replay / learning JSONL 只保留於 `runtime/private/`，不應 commit 或放入公開 docs。

## 變更

v24 新增候選 profile：

- `fixed_depth_fianchetto_tail_castle_guard`

核心變更：

- 保留王翼易位優先權。
- 取消王后翼易位的 early hard-priority，讓搜尋與安全閘自行決定。
- 保留 v22 的 fianchetto / tail mate-net 候選能力。

這是通用規則調整，不是針對 held-out 題或單局 replay 的硬編碼。

## 結果摘要

| Profile | W-D-L | Score rate | Threefold | Avg ms/game | Avg plies | Normalized |
|---|---:|---:|---:|---:|---:|---:|
| v20/v22 baseline family | 23-7-0 | 0.8833 | 0.2333 | ~15.2s | 77.0 | 90.1322 |
| v24 castle-guard | 24-6-0 | 0.9000 | 0.2000 | 16.23s | 73.6 | 91.1463 |

Held-out Stockfish validation aggregate versus v22 is effectively flat:

| Profile | Clean | Review | Rejected | Top1 | Top3 | Top5 | Avg CP Loss |
|---|---:|---:|---:|---:|---:|---:|---:|
| v22 `fixed_depth_fianchetto_tail` | 37 | 12 | 1 | 14 | 25 | 32 | 39.42 |
| v24 `fixed_depth_fianchetto_tail_castle_guard` | 37 | 12 | 1 | 14 | 25 | 32 | 39.74 |

## 解讀

v24 是目前第一個在不使用逐題硬編碼的前提下，把正式 30 局 gauntlet 從 23W/7D 推到 24W/6D 的候選。改善來源不是 held-out 題對齊率，而是完整對局中的早期王安全/材料流失風險下降。

仍需注意：

- 6 個和局仍全是三重複。
- 和局尾段平均仍偏材料落後，代表 AI 還常靠 repetition 取半分，而不是穩定壓倒對手。
- 下一階段應繼續處理中盤 quiet positional / tactical exposure，不應把 validation 題寫入 priors。

## 證據

- `docs/games/evidence/exp5/v24_castle_guard_full_gauntlet_30.json`：redacted aggregate replay evidence。
- `docs/games/evidence/exp5/v24_castle_guard_advanced_score_30s_fullinputs.json`
- `docs/games/evidence/exp5/v24_castle_guard_heldout_validation_50_stockfish.json`：redacted held-out aggregate。
- `docs/games/evidence/exp5/v24_castle_guard_draw_summary.json`
- Raw replay JSON/JSONL：`runtime/private/games/exp5/v24_castle_guard/`。
