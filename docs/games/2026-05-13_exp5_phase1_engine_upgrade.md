# 2026-05-13 Exp5 Phase 1 Engine Upgrade

## 範圍

本輪依照高階引擎化路線先做 Phase 1：提高評測上限與補 exp5 搜尋核心。沒有替換預設模型檔；`services/games/models/chess_experiment_5_nnue.json` 保持作為目前 runtime 模型。若之後產生更好的模型並要覆蓋，必須先快照舊模型與 checksum。

## 程式改動

- `services/games/chess_search.py`
  - 新增可選 `extension_fn` 與 `max_extensions`。
  - 預設關閉，因此其他引擎呼叫不受影響。
  - exp5 可針對將軍、升變、重大吃子、recapture 多看一層。
- `services/games/chess_nnue.py`
  - 新增 legal-move static exchange evaluation：`_static_exchange_eval()`。
  - move ordering 會獎勵正 SEE、懲罰負 SEE。
  - high-value capture priority 需通過 tactical safety 與 SEE。
  - exp5 quiescence filter 納入升變、將軍、吃子與 SEE >= 0 的小吃子。
  - 新增 search extension：check / promotion / high-value capture / recapture。
  - 補 `_claimable_draw_resource_filter()`：不明顯領先時仍可保留三次重複守和。
  - 補 `_avoid_reversible_cycle_when_ahead_filter()`：明顯領先時避免無戰術理由反走自己上一手造成循環。
- `scripts/games/chess_exp5_gauntlet.py`
  - 新增完整局 gauntlet，支援多開局、雙方顏色、JSON 與 JSONL replay。
- `scripts/games/chess_exp5_tactical_suite.py`
  - 新增較大的 tactical/behavioral suite wrapper，預設 300 題。
- `tests/games/test_chess_exp5_architecture.py`
  - 新增 SEE 單元測試。
  - 新增領先時避免反向循環測試。

## 驗證結果

| 驗證項 | 結果 |
|---|---:|
| exp5 / opening / practice / self-play 目標測試 | `43 passed` |
| exp5 architecture 單測 | `22 passed` |
| py_compile | pass |
| exp5 score probe | `40.00/40` |
| fixed probes | `14.40/14.40` |
| score probe sparring | `6W/0D/0L` |
| 300 題 tactical suite | `300/300` |
| PGN human probes in 300 題 suite | `240/240` |
| 300 題 exact reference matches | `40/240 = 16.67%` |
| 16 局 gauntlet | `7W/9D/0L` |
| gauntlet AI score rate | `0.7188` |
| gauntlet replay rows | `16` |

主要 artifacts：

- `docs/games/2026-05-13_exp5_score_probe_see_extension.json`
- `docs/games/2026-05-13_exp5_tactical_suite_300_see_extension.json`
- `docs/games/2026-05-13_exp5_gauntlet_see_extension.json`
- `docs/games/2026-05-13_exp5_gauntlet_see_extension.jsonl`

## 解讀

本輪不是模型訓練，而是 engine 核心與評測上限升級。結果有三個重點：

1. 原 score probe 沒退：仍是 `40.00/40`，固定題全過，AI-vs-random `6W/0D/0L`。
2. 題庫上限提高：300 題 suite 全過，且其中 240 題來自下載 PGN replay 的 human probes。
3. 完整局壓力測試更嚴格：16 局多開局 gauntlet 中 exp5 `7W/9D/0L`，沒有輸，但三次重複仍多。

這支持「比前一版更可測、更穩」；但還不足以稱高階引擎。gauntlet 顯示剩餘瓶頸是：

- queen-pawn、sicilian、start 等開局仍常導向三次重複。
- 局面接近均勢或小優時，exp5 缺少長線壓制計畫。
- 需要更強 search pruning/extension、perpetual-check planning、rook/pawn ending technique，以及真正 teacher-labeled training。

## 下一步

要繼續往高階引擎靠近，下一輪應優先：

1. 實作 null-move pruning / late move reductions / futility pruning，否則 depth 很難再加。
2. 建立 stronger sparring baseline，而不是只打 transparent reviewer policy。
3. 針對 gauntlet 的 9 局和棋建立 regression probes，分辨哪些是合理守和、哪些是漏勝。
4. 若要替換模型，先快照目前 `services/games/models/chess_experiment_5_nnue.json`，再用離線 teacher-labeled data 產生新模型。

## Phase 1B - Advanced Score Optimization

後續依照「舊分數已無參考價值，需要提高分數上限」的要求，新增
advanced non-saturated score。v10 已超過 v7，成為目前最佳乾淨候選：

| 項目 | v1 baseline | v7 | v10 current best |
|---|---:|---:|---:|
| advanced score | `80.5560/100` | `83.5503/100` | `84.1482/100` |
| complete gauntlet | `14W/15D/1L` | `17W/13D/0L` | `18W/12D/0L` |
| gauntlet score rate | `0.7167` | `0.7833` | `0.8000` |
| threefold rate | `50.00%` | `43.33%` | `40.00%` |
| legacy score probe | `40.00/40` | `40.00/40` | `40.00/40` |
| tactical suite | `300/300` | `300/300` | `300/300` |

採納的 v7 改動：

- 開局被將軍時避免 e1/e8 原位王非必要走王。
- 領先時避免讓對方下一手可宣告三次重複。
- 只有落後時主動保留三次重複守和；均勢或領先時偏向安全續戰。
- 阻止對方下一手可「升變並將軍」的高危升變。

v10 追加改動：

- 優勢方如果下一手會讓自己或對手可宣告三次重複，且存在材料安全
  的非重複替代手，就接受較低靜態分數的續戰手。
- French 回歸案例由重複 `Rc8+` 改為 `Rxb7`。
- King's Indian 回歸案例由重複 `Rd6+` 改為 `Re7`。

未採納但已記錄的嘗試：

- v2 broad king-walk guard：分數降至 `75.4820/100` 且新增敗局。
- v6 broad promotion guard：分數高但有 `2` 個完整局敗局，不可接受。
- v8 king-capture ordering：focused 有收益，但完整 gauntlet 降至 `81.5769/100`。
- v9 reversible checking-cycle guard：focused 未改善，不採納。

完整紀錄：

- `docs/games/2026-05-13_exp5_advanced_score_optimization.md`
- `docs/games/2026-05-13_exp5_advanced_score_repetition_progress_v10_fullrerun.json`
- `docs/games/2026-05-13_exp5_gauntlet_repetition_progress_v10.json`
- `docs/games/2026-05-13_exp5_gauntlet_repetition_progress_v10.jsonl`
