# 2026-05-13 遊戲區 AI 技術與分數比較表

本文件整理目前已落盤證據中的最新比較結果。`experiment 5:nnue`
使用深度優化、300 題 tactical/human suite 與 v10 30 局 gauntlet 後的
最新分數；其他棋類與難度沿用主評測
`docs/games/2026-05-13_game_ai_strength_eval.json`。不同棋種的分數不可直接
等同棋力，只能比較本測試框架下的通過率、穩定性與可用性。

## 資料來源

- 主評測 JSON：`docs/games/2026-05-13_game_ai_strength_eval.json`
- 主評測報告：`docs/games/2026-05-13_game_ai_strength_report.md`
- exp5 最新 score probe：`docs/games/2026-05-13_exp5_score_probe_repetition_progress_v10.json`
- exp5 最新 300 題 suite：`docs/games/2026-05-13_exp5_tactical_suite_300_repetition_progress_v10.json`
- exp5 最新 30 局 gauntlet：`docs/games/2026-05-13_exp5_gauntlet_repetition_progress_v10.json`
- exp5 完整 reviewer 五局：`docs/games/2026-05-13_exp5_conversion_regression.json`
- 下載腳本轉換 replay：`docs/games/2026-05-13_exp5_download_script_probe_replay.jsonl`
- exp5 殘局轉換補強：`docs/games/2026-05-13_exp5_conversion_fix.md`
- exp5 Phase 1 engine upgrade：`docs/games/2026-05-13_exp5_phase1_engine_upgrade.md`
- exp5 advanced score optimization：`docs/games/2026-05-13_exp5_advanced_score_optimization.md`
- exp5 v10 advanced score：`docs/games/2026-05-13_exp5_advanced_score_repetition_progress_v10_fullrerun.json`

## 目前比較表

| 棋種 | AI / 難度 | 應用技術 | 主要參數 / 技術細節 | 分數 | 固定題 | 實戰 | 約略棋力 |
|---|---:|---|---|---:|---:|---:|---|
| 黑白棋 | easy | Alpha-beta + 手寫評估 | depth 1；子差、行動力、角、邊、X 格懲罰 | 27.71/40 | 3/4 | 3W/0D/3L | 初級到中級 |
| 黑白棋 | normal | Alpha-beta + 手寫評估 | depth 2；子差、行動力、角、邊、X 格懲罰 | 28.95/40 | 3/4 | 5W/0D/1L | 初級到中級 |
| 黑白棋 | hard | Alpha-beta + 手寫評估 | depth 4；子差、行動力、角、邊、X 格懲罰 | 28.95/40 | 3/4 | 5W/0D/1L | 初級到中級 |
| 圍棋 | easy | 9x9 簡化規則 + 啟發式 | 吃子、氣、中心 heuristic；無劫、無貼目 | 30.83/40 | 2/3 | 6W/0D/0L | 約 15-10 級；非段位 |
| 圍棋 | normal | 淺層 rollout + heuristic | candidate 14；rollouts 2；depth 10 | 30.83/40 | 2/3 | 6W/0D/0L | 約 15-10 級；非段位 |
| 圍棋 | hard | 淺層 rollout + heuristic | candidate 22；rollouts 4；depth 16 | 30.83/40 | 2/3 | 6W/0D/0L | 約 15-10 級；非段位 |
| 五子棋 | easy | 鄰近候選 + pattern evaluator + alpha-beta | depth 1；radius 1；立即勝與擋五 | 40.00/40 | 4/4 | 6W/0D/0L | 中級級位；約 5-1 級 |
| 五子棋 | normal | 鄰近候選 + pattern evaluator + alpha-beta | depth 1；radius 2；立即勝與擋五 | 40.00/40 | 4/4 | 6W/0D/0L | 中級級位；約 5-1 級 |
| 五子棋 | hard | 鄰近候選 + pattern evaluator + alpha-beta | depth 2；radius 2；立即勝與擋五 | 40.00/40 | 4/4 | 6W/0D/0L | 中級級位；約 5-1 級 |
| 西洋棋 | normal | 開局庫 + material/check heuristic | route 層先查 opening book，再做靜態材料與將軍評估 | 22.49/40 | 4.70/12.40 | 2W/4D/0L | 約 Elo 600-1000 |
| 西洋棋 | hard | 開局庫 + 一手回應懲罰 | opening book + opponent reply penalty | 23.83/40 | 5.05/12.40 | 4W/2D/0L | 約 Elo 600-1000 |
| 西洋棋 | experiment | Alpha-beta + SQLite learning bias | fast profile depth 2；120ms | 8.61/40 | 2.05/12.40 | 1W/1D/4L | 低於 Elo 800 或不穩定 |
| 西洋棋 | exp3:dl | JSON neural/policy style evaluator + search fallback | fast d1/q1；balanced d2/q2；strong d2/q4 | 23.82/40 | 5.40/12.40 | 1W/5D/0L | 約 Elo 600-1000 |
| 西洋棋 | exp4:pv | Policy/Value + MCTS option + guarded overlay | MCTS 32/72/160 sims；depth 1-2；qsearch 1/2/4 | 18.56/40 | 4.05/12.40 | 1W/1D/4L | 約 Elo 600-1000 |
| 西洋棋 | exp5:nnue | NNUE-like sparse evaluator + AlphaBeta/PVS | d2/q2 320ms；PGN replay prior；防 mate-in-1；簡化局面 mate-in-2；SEE；check/promotion/recapture extension；送子與循環過濾；殘局主動王與通路兵轉換評估；開局 e1/e8 走王防護；領先時避免讓對方宣告三次重複；只在落後時主動保和；立即將軍升變防護；v10 優勢方安全續戰反三重複規則 | 40.00/40；advanced 84.1482/100 | 14.40/14.40；300 題 suite 300/300 | 6W/0D/0L；30 局 gauntlet 18W/12D/0L | 約 Elo 1500-1800；非高階引擎 |

## 目前排序

1. 五子棋三個難度：`40.00/40`。固定題與弱基線全勝，但題組仍不足以證明高段 VCF/VCT 或引擎級。
2. 西洋棋 `exp5:nnue`：legacy `40.00/40`，advanced `84.1482/100`。已超過 30 分目標並通過 300 題 tactical/human suite；30 局 gauntlet 為 `18W/12D/0L`，仍不是高階引擎。
3. 圍棋三個難度：`30.83/40`。分數達 30 以上，但規則是 9x9 簡化版，不能換算成正式圍棋段位。
4. 黑白棋 normal/hard：`28.95/40`。合法性與短期戰術穩，但送角、X/C 格與長期行動力策略仍需補強。
5. 西洋棋 normal/hard/exp3/exp4：多在 `18-24/40`。主要被陷阱應對、長期策略與完整局穩定性拖低。
6. 西洋棋 `experiment`：`8.61/40`。目前只適合規則 smoke，不建議作棋力訓練對手。

## 客觀解讀

- 目前最可用的西洋棋路線是 `exp5:nnue`，但它不是高階引擎。它通過了新增陷阱、human probes、mate-in-1/mate-in-2、送子過濾、殘局轉換補強與 300 題 suite；30 局 gauntlet 已達 `18W/12D/0L`，但仍缺少高階引擎級的長線殘局技術。
- 五子棋分數最高，但這反映的是目前題庫範圍。若要宣稱高段，需要加入長 VCF/VCT、雙三雙四變體與對抗更強基線。
- 圍棋 hard 成本高但分數未高於 easy/normal。這是工程可用性問題，也代表 rollout 深度增加沒有在現有固定題上轉化成可觀棋力差異。
- 黑白棋難度體感有差，但固定 C/X 格問題仍存在。應優先補送角風險、行動力 trap 與奇偶終盤題。
- 西洋棋 `experiment`、`exp3:dl`、`exp4:pv` 的名稱不能被解讀成棋力等級；目前只能視為不同架構實驗，不宜標成高難度。

## exp5 最新補強摘要

- 使用昨天下載並轉換的 PGN replay，產生 `docs/games/2026-05-13_exp5_download_script_probe_replay.jsonl`。
- `scripts/games/chess_exp5_holdout_probe.py` 擴充為 100 題：60 題 synthetic/mirrored cases 加 40 題 downloaded PGN human probes。
- `services/games/chess_nnue.py` 補入 bounded forced mate-in-2、mate-in-one prevention、立即材料掉落過濾、repetition/stalemate guard 與 PGN replay prior。
- 最新 exp5 score probe：固定題 `14.40/14.40`，sparring `6W/0D/0L`，總分 `40.00/40`。
- 最新 exp5 300 題 tactical suite：`300/300`，其中 downloaded PGN human probes `240/240`，exact reference match `40/240 = 16.67%`。
- 最新 exp5 30 局 gauntlet：`18W/12D/0L`，AI score rate `0.8000`，threefold rate `40.00%`，complete-game rate `93.33%`。
- 最新 advanced score：`84.1482/100`。這表示它已能在多開局完整局中穩定不輸並贏下一部分對局，但仍缺乏高階殘局壓制力；其中 `2` 局勝局到 220 ply material cap，需列為轉換速度問題。

## 注意事項

- `exp5` 最新 legacy `40.00/40` 已飽和；目前應以 advanced `84.1482/100` 和 30 局 gauntlet 作為後續優化比較基準。它與主評測舊表中的 `24.05/40` 不是同一時間點的棋力狀態。
- JSON 主評測中的黑白棋固定題通過率是 `3/4 = 0.75`；主報告早期表格中 `0.67` 是文字表格未同步修正，應以 JSON 與本文件為準。
- exp5 live smoke 最新一次在獨立伺服器上遇到 login `401`，屬於該次 live-smoke 帳號/隔離環境設定問題；目前不能把它解讀為 AI 棋力退化。
