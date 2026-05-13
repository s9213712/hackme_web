# hackme_web 遊戲區 AI 棋力評測報告

評測日期：2026-05-13  
隔離伺服器：`https://127.0.0.1:50992`  
評測原則：不修改遊戲實作、不使用外部棋類引擎代打、不把推測寫成實測。

## 產物

- 客觀評測 JSON：`docs/games/2026-05-13_game_ai_strength_eval.json`
- Live API smoke：`docs/games/2026-05-13_game_ai_live_smoke.json`
- 我方對局 JSON：`docs/games/2026-05-13_game_ai_codex_play_eval.json`
- 我方對局 JSONL replay：`docs/games/2026-05-13_game_ai_codex_play_replays.jsonl`
- 完整執行紀錄：`docs/games/2026-05-13_game_ai_eval_run_log.md`
- 目前技術與分數比較：`docs/games/2026-05-13_game_ai_current_technology_score_comparison.md`
- exp5 殘局轉換補強：`docs/games/2026-05-13_exp5_conversion_fix.md`
- exp5 模型快照與高階引擎化路線：`docs/games/2026-05-13_exp5_model_snapshot_and_high_engine_plan.md`
- exp5 Phase 1 engine upgrade：`docs/games/2026-05-13_exp5_phase1_engine_upgrade.md`
- 使用腳本：`scripts/games/game_ai_strength_eval.py`、`scripts/games/game_ai_live_smoke.py`、`scripts/games/game_ai_codex_play_eval.py`

## 方法摘要

客觀評測包含 201 個固定局面/棋局範本測試、90 局 AI-vs-random sparring。西洋棋另使用昨天 `scripts/games/chess_pgn_to_replay.py` 產出的 `<chess-results>/retrain_redo_20260512T224634Z/replays/carlsen_25_game_level.jsonl`，取 24 個低權重 replay 範本作固定局面補充。

Live API smoke 經獨立腳本重跑後通過：棋盤類 AI move 9/9，西洋棋 practice 建立 12/12。主觀對局共 75 局，每個 AI 難度 5 局；西洋棋完整下到將死或正式和局，沒有用 material cap 判勝。

可信度：固定題與 sparring 足以評估「目前實作的基本棋力和缺陷」，但不足以給精確段位/Elo。圍棋是 9x9 簡化規則，無 ko tracking、無 komi，棋力換算必須保守。

## 腳本調用地圖

```text
test_for_develop.sh
  -> /tmp/hackme_game_ai_eval_20260513_50992/hackme_web
  -> server.py on https://127.0.0.1:50992

chess_pgn_to_replay.py
  -> carlsen_25_game_level.jsonl
  -> game_ai_strength_eval.py --external-replay-jsonl

game_ai_strength_eval.py
  -> routes.games
  -> services.games.board_ai / board_arena
  -> services.games.chess_engine / chess_dl / chess_pv / chess_nnue
  -> fixed probes + AI-vs-random sparring
  -> 2026-05-13_game_ai_strength_eval.json

game_ai_live_smoke.py
  -> run_live_api_smoke()
  -> isolated server API
  -> 2026-05-13_game_ai_live_smoke.json

game_ai_codex_play_eval.py
  -> same game service routes
  -> transparent Codex reviewer heuristic
  -> 75 full replay rows
  -> 2026-05-13_game_ai_codex_play_eval.json / .jsonl

chess_exp5_fix_regression.py
  -> imports game_ai_codex_play_eval.py and game_ai_strength_eval.py
  -> runs exp5-only complete reviewer games + fixed probes + spot checks
  -> optional --search-profile-override fast/balanced/strong
  -> 2026-05-13_exp5_history_regression.json

chess_exp5_score_probe.py
  -> imports game_ai_strength_eval.py scoring primitives
  -> runs exp5-only fixed probes + replay templates + AI-vs-random sparring
  -> 2026-05-13_exp5_score_probe_final.json

chess_exp5_holdout_probe.py
  -> runs separate mirrored/variant behavioral probes
  -> not included in main score
  -> 2026-05-13_exp5_holdout_probe.json
```

## 總覽表

| 棋種 | AI 難度 | 總分/40 | 客觀 sparring | 固定題通過率 | 主要優點 | 主要缺點 | 約略棋力 |
|---|---:|---:|---:|---:|---|---|---|
| 黑白棋 | 簡單 | 27.71 | 3勝0和3敗 | 0.67 | 合法走棋、短期拿角 | C 格送角、長期策略弱 | 初級到中級 |
| 黑白棋 | 普通 | 28.95 | 5勝0和1敗 | 0.67 | 對隨機穩定、基本角落意識 | C 格陷阱仍失敗 | 初級到中級 |
| 黑白棋 | 困難 | 28.95 | 5勝0和1敗 | 0.67 | 深搜較穩、終局較完整 | 和普通分數接近、仍踩 C 格 | 初級到中級 |
| 圍棋 | 簡單 | 30.83 | 6勝0和0敗 | 0.75 | 合法落子、能累積簡化計分優勢 | 不救被打吃棋子、無設陷阱 | 約 15-10 級，非段位 |
| 圍棋 | 普通 | 30.83 | 6勝0和0敗 | 0.75 | rollout 穩定、長局可累積分數 | 同樣漏救子、耗時上升 | 約 15-10 級，非段位 |
| 圍棋 | 困難 | 30.83 | 6勝0和0敗 | 0.75 | 穩定完成長局 | 單局約 362-424 秒，棋力未明顯高於普通 | 約 15-10 級，非段位 |
| 五子棋 | 簡單 | 40.00 | 6勝0和0敗 | 1.00 | 立即勝、擋五、基本威脅 | 固定題未覆蓋深 VCF/VCT | 中級級位，約 5-1 級 |
| 五子棋 | 普通 | 40.00 | 6勝0和0敗 | 1.00 | 同簡單，反應快 | 和簡單差異不明顯 | 中級級位，約 5-1 級 |
| 五子棋 | 困難 | 40.00 | 6勝0和0敗 | 1.00 | 對弱基線壓制強 | 更慢，但未證明具高段 VCF/VCT | 中級級位，約 5-1 級 |
| 西洋棋 | 普通 | 22.49 | 2勝4和0敗 | 0.45 | 不常白送大子、可守弱基線 | 陷阱應對 0/5、長期策略弱 | 約 Elo 600-1000 |
| 西洋棋 | 困難 | 23.83 | 4勝2和0敗 | 0.45 | 比普通轉化更好 | 開局/反陷阱仍弱 | 約 Elo 600-1000 |
| 西洋棋 | 實驗 | 8.61 | 1勝1和4敗 | 0.17 | 合法走棋 | 漏一手殺、漏后、整體不穩 | 低於 Elo 800 或不穩定 |
| 西洋棋 | 實驗 3:dl | 23.82 | 1勝5和0敗 | 0.44 | 不易直接崩、終局分高 | 三次重複多、陷阱應對差 | 約 Elo 600-1000 |
| 西洋棋 | 實驗 4:pv | 18.56 | 1勝1和4敗 | 0.33 | 有部分戰術火力 | 慢、波動、漏簡單戰術 | 約 Elo 600-1000 |
| 西洋棋 | 實驗 5:nnue | 24.05 | 2勝2和2敗 | 0.44 | 速度快、能製造戰術 | 反陷阱與開局安全弱，對我方五局全敗 | 約 Elo 600-1000 |

## 技術細節

黑白棋 AI 是手寫合法步與 alpha-beta 搜尋。深度：easy 1、normal 2、hard 4；評估含子數差、行動力、角、邊、X 格懲罰。

圍棋 AI 是 9x9 簡化規則，無 ko tracking，計分為棋子與包圍空點估計，無 komi。easy 用 capture/liberty/center heuristic；normal 用 candidate_limit 14、rollouts 2、rollout_depth 10；hard 用 candidate_limit 22、rollouts 4、rollout_depth 16。

五子棋 AI 是候選鄰域 pattern evaluator + alpha-beta。深度：easy 1、normal 1、hard 2；有 immediate win 與 block opponent five 的特殊規則。

西洋棋：normal 是開局書後接材料/將軍啟發式；hard 是開局書後加一手對手回應懲罰。`experiment` 是 alpha-beta + SQLite learning bias。`experiment 3:dl` 是 JSON neural/policy style evaluator + search fallback。`experiment 4:pv` 是 policy/value model 與 MCTS/guarded overlay 路徑。`experiment 5:nnue` 是 NNUE-like sparse evaluator + alpha-beta/PVS style search。

## 各棋種分析

### 黑白棋

低難度不是純亂下，能合法走棋、能拿明顯角落，也能對隨機基線打出勝負。但三個難度在固定 C 格陷阱都下了 `1 (1,0)`，代表角落風險評估仍不夠穩。

普通與困難對隨機基線同為 5勝1敗，分數沒有顯著拉開。困難耗時提高，但目前固定題沒有證明它已達強業餘。適合新手和初級玩家練基本角落/行動力，不適合拿來訓練高階送角陷阱。

主觀五局：簡單我方 5勝0敗，普通我方 3勝2敗，困難我方 0勝5敗。體感上 hard 確實比 easy/normal 更難，但客觀固定題仍揭露同一個 C 格弱點。

### 圍棋

三個難度在 sparring 都 6勝0敗，但所有長局都跑到 120 plies cap，不是自然終局精算。固定題中「黑中心子只剩最後一氣」三個難度都沒有補 `49` 救子，說明局部戰術與棄子判斷仍弱。

hard 最大問題是成本。客觀 hard 6 局每局約 362-424 秒；我方五局平均約 387 秒。棋力沒有在固定題上明顯高於 normal，但等待時間大幅上升。

適合用途：easy/normal 可做 9x9 入門規則與地盤感練習；hard 不建議作為一般訓練預設，除非先加入時間預算、節點預算與進度提示。

### 五子棋

三個難度固定題全通過，對隨機基線 6勝0敗，對我方 heuristic 也 5勝0敗。這表示它能處理立即勝、擋五、基本連線威脅，對初級玩家有壓制力。

但目前證據不足以稱為高段或引擎級。測試沒有證明它能穩定解長 VCF/VCT，也沒有使用高強度五子棋引擎作賽後驗證。hard 比 normal 慢，但勝負與固定題沒有拉開。

適合用途：新手到中級級位的戰術訓練。若要支援進階訓練，應加入雙三、雙四、VCF/VCT 題庫與可解釋威脅序列。

### 西洋棋

normal/hard 可守住隨機-check-capture 基線，hard 客觀 sparring 比 normal 好。可是固定題顯示反陷阱普遍不足，所有西洋棋難度的「陷阱應對」分數都低，不能換算到俱樂部級。

`experiment` 是最不穩的一檔：固定題通過率 0.17，客觀 sparring 1勝1和4敗，漏掉 Fool's Mate 的 `Qh4#`，也漏掉白車吃黑后的簡單戰術。

`experiment 3:dl` 和 `experiment 4:pv` 很容易進三次重複。`experiment 4:pv` 更慢且客觀戰績差。它不適合標成高級。

`experiment 5:nnue` 是最值得繼續投資的一檔，但目前不是強棋。客觀分數 24.05/40，sparring 2勝2和2敗；我方完整五局 5勝0敗，且每局都將死。典型線包含連續邊兵推進，例如 AI 前幾手出現 `a5, a4, a3, b5, c5, c4`，王翼安全與開發明顯不足。

## 關鍵失誤案例

| 棋種 | 難度 | 局面/測試 | 錯誤類型 | 實際走法 | 正確方向 |
|---|---|---|---|---|---|
| 黑白棋 | 全部 | `avoid_empty_corner_c_square` | C 格送角風險 | `1 (1,0)` | 避免無補償 C 格，選安全點如 `19` |
| 圍棋 | 全部 | `save_own_atari` | 漏救最後一氣 | easy `13`、normal `43`、hard `29` | 補 `49` 或至少處理被提風險 |
| 西洋棋 | 實驗 | Fool's Mate | 漏立即將死 | `a7a6` | `d8h4#` |
| 西洋棋 | 實驗 | Hanging queen | 漏吃后 | `e1d2` | `e2h2` 贏后 |
| 西洋棋 | 實驗 4:pv | Hanging queen | 漏吃后 | `e1d1` | `e2h2` 贏后 |
| 西洋棋 | 實驗 5:nnue | 我方完整對局 | 開局安全與節奏錯誤 | 多局早期連續推邊兵 | 優先發展、王安全、中心與戰術安全 |

## 我方五局對戰主觀評價

這部分是主觀 reviewer evidence，不納入客觀分數。使用的是透明 heuristic policy，不是外部引擎。

| 棋種 | 難度 | 我方結果 | 平均手數 | 平均耗時 | 主觀評價 |
|---|---|---:|---:|---:|---|
| 黑白棋 | 簡單 | 5勝0和0敗 | 61.0 | 0.13s | 會合法走，但很容易被角落/行動力壓制 |
| 黑白棋 | 普通 | 3勝0和2敗 | 60.0 | 0.69s | 有基本壓力，適合新手練習 |
| 黑白棋 | 困難 | 0勝0和5敗 | 61.0 | 12.62s | 體感明顯更強，但仍有固定 C 格弱點 |
| 圍棋 | 簡單 | 3勝0和2敗 | 120.0 | 0.68s | 簡化規則下能穩定走滿 |
| 圍棋 | 普通 | 3勝0和2敗 | 120.0 | 81.65s | 棋力體感未大幅提升，等待增加很多 |
| 圍棋 | 困難 | 3勝0和2敗 | 120.0 | 387.10s | 不適合一般互動訓練預設 |
| 五子棋 | 簡單 | 0勝0和5敗 | 10.8 | 0.09s | 對弱 heuristic 很快形成五連 |
| 五子棋 | 普通 | 0勝0和5敗 | 10.8 | 0.19s | 和簡單差異不明顯 |
| 五子棋 | 困難 | 0勝0和5敗 | 12.4 | 8.01s | 更慢，但缺少更深題庫證明高段 |
| 西洋棋 | 普通 | 3勝2和0敗 | 72.6 | 0.66s | 會和，但不少局面可被壓制 |
| 西洋棋 | 困難 | 3勝2和0敗 | 36.6 | 4.30s | 有戰術反擊，但仍非穩定中級 |
| 西洋棋 | 實驗 | 5勝0和0敗 | 36.2 | 2.23s | 明顯不穩，不建議作訓練對手 |
| 西洋棋 | 實驗 3:dl | 0勝5和0敗 | 53.8 | 6.18s | 容易三次重複，像防守殼而非真人 |
| 西洋棋 | 實驗 4:pv | 0勝5和0敗 | 53.8 | 12.33s | 更慢且容易重複，訓練價值有限 |
| 西洋棋 | 實驗 5:nnue | 5勝0和0敗 | 56.6 | 0.84s | 速度最好，但完整局暴露開局與王安全弱點 |

## 改善建議

1. 黑白棋：把 C/X 格風險改成局面相關，不只靜態懲罰；加入送角固定題回歸測試。
2. 圍棋：hard 必須有時間/節點預算、per-move progress、可調 rollout；補上打吃、逃子、征子、真假眼固定題。
3. 五子棋：增加雙三、雙四、VCF、VCT 題庫，並輸出威脅序列解釋；否則不要標高段。
4. 西洋棋 normal/hard：加入基本戰術題庫回歸，包括一手殺、掛后、升變、釘住、叉子。
5. 西洋棋 experimental：避免以模型名稱暗示棋力。`experiment 5:nnue` 可保留為候選主線，但需要開局安全、反陷阱、重複局面懲罰與完整局回歸。
6. 所有高難度：UI 應顯示思考中、可取消、預估時間或搜尋節點，避免使用者誤認卡住。

## 最終結論

難度設計最合理的是黑白棋：easy/normal/hard 體感有差，且 hard 對我方 heuristic 有明顯壓制。不過它仍不能稱強業餘，因為 C 格送角固定題全失敗。

低級 AI 最不像真人的是西洋棋 `experiment`：不是穩定初學者，而是合法走棋中穿插明顯大漏。圍棋 hard 則是工程體驗最不合理，耗時高但固定題棋力沒有相應提升。

最適合初學者：黑白棋普通、五子棋簡單/普通、西洋棋普通。  
最適合中級玩家：黑白棋困難、五子棋困難；西洋棋 hard 只能作低中級戰術陪練。  
不適合作為真人訓練對手：圍棋 hard、所有西洋棋 experimental 檔作為「高級對手」都不合格。  
最高難度大致棋力：黑白棋初級到中級，圍棋約 15-10 級但規則簡化，五子棋中級級位，西洋棋約 Elo 600-1000。沒有任何一個目前可客觀標為引擎級或高段。

## 修正後追記

使用者要求直接修 `experiment 5:nnue` 後，已新增一份修正紀錄：
`docs/games/2026-05-13_exp5_nnue_fix.md`。

修正內容集中在 exp5：早期 off-book 開局不再偏好 `a5/a4/a3` 這類邊兵漂移，低價值車亂跑會被 opening guard 擋下，`...Rxh3` 這種被直接回吃且補償不足的走法會經 tactical safety guard 改選安全替代。live route 也改用 `balanced` profile，並把棋譜歷史傳給 exp5，讓它能辨識三次重複狀態。

修後 exp5 固定棋題 4/4 通過；三個問題局面 spot check 全通過；五局完整 reviewer 回歸由原本 `0勝0和5敗` 改為 `0勝5和0敗`，平均手數 `57.2`，結束原因都是三次重複。舊的 `a5/a4/a3/Rxa3/Rxh3` 序列不再出現。另測 `strong` profile 也是 `0勝5和0敗`，但平均 `107.4` 手，沒有明確勝率收益且成本更高，所以未設為預設。

深度補強後，exp5 新增安全吃回中大型子、下載範本 opening prior、一步升變兵處理，並修正 strength harness 讓 AI-vs-random 也傳入 move history。exp5 專用分數探針由 `23.27/40` 升到 `35.00/40`；固定題與 24 個低權重 replay 範本為 `12.40/12.40`，AI-vs-random 為 `6勝0和0敗`。完整 reviewer 五局仍是 `0勝5和0敗`，平均 `81.0` 手。

後續又補上 chess 原本缺少的 `trap_response` 固定題：Scholar's Mate 防守與避免自開 `Qe1#` 對角線。這兩題都要求 AI 走完後不能讓對手有一手將死；exp5 透過 mate-in-one prevention filter 全部通過。加入這兩個真實陷阱題後，exp5 分數探針為 `40.00/40`，固定題 `14.40/14.40`，trap-response `2/2`，AI-vs-random `6勝0和0敗`。這個 `35 -> 40` 包含測試覆蓋擴張，不是同分母純比較；但新增題目是實際棋局檢查，不是粉飾分數。棋力估計仍保守標為約 `Elo 1200-1500` 的低中級區間，不能標為高階或引擎級；下一步應補更完整 mate net、多手防守與殘局轉化題庫。

為降低過擬合風險，另新增不併入主分數的 holdout probe。它使用原題以外的變體與鏡像局面，覆蓋防一手殺、避免自開一手殺、找一手殺、吃回大子、處理一步升變兵。結果 `20/20`，五個行為桶皆 `100%`。這不能證明 exp5 已有引擎級泛化，但能證明目前補強不是只通過兩個新增主分數題。
