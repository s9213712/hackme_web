# 2026-05-14 Auto-Retrain 暫停與 retrain 退步研究摘要

## 本階段處置

- 已將西洋棋 pipeline auto-retrain 預設關閉。
- replay 仍照常寫入 `chess_replays.jsonl`，並保留 trusted / quarantine / rejected 分類與後續優質紀錄篩選。
- 手動 retrain pipeline、推薦命令、candidate/stage/promote 流程仍保留。
- 若要短期驗證 auto-retrain，必須明確設定：
  - `HTML_LEARNING_CHESS_AUTORETRAIN_ENABLED=1`
  - 或舊別名 `HTML_LEARNING_CHESS_PIPELINE_AUTORUN_ENABLED=1`
- 預設阻擋原因代碼：`auto_retrain_disabled_pending_research`。

## 目前呼叫流程

1. `routes/games.py::collect_computer_replay(...)`
2. `collect_match_replay(...)`
3. `services/games/chess_replay_buffer.py` 寫入與分類 replay。
4. 若 replay stored，呼叫 `maybe_launch_chess_train_pipeline(...)`。
5. `services/games/chess_pipeline.py` 現在預設回傳 disabled，不 fork `chess_train_pipeline.py`。

因此目前仍會留下對局紀錄與篩選資料，但不會把新 replay 自動訓回 production model。

## 查詢到的相關研究與開源實務

| 來源 | 重點 | 對本專案的含義 |
|---|---|---|
| [AlphaZero 論文](https://arxiv.org/abs/1712.01815) | AlphaZero 是大規模 self-play + search + neural net 的閉環，不是把少量局直接寫回模型。 | 我們目前 replay 數量、teacher 深度、搜尋與 gate 都不足以支撐「越玩越強」假設。 |
| [Leela Chess Zero 官方 networks/runs 說明](https://lczero.org/play/networks/) | Lc0 說 neural network 需要數百萬高品質棋局；RL run 會用新網路產生下一批 self-play，並以 snapshots 管理。 | 我們 10/100 局級別的 retrain 更像噪音注入，不能期待穩定提升。 |
| [LCZero training site](https://training.lczero.org/) | 分散式 self-play 每日大量產生棋局，並追蹤 Elo / runs / networks。 | 可靠 online learning 需要大量資料與可重現評測，不是 server 端即時熱更新。 |
| [DAgger 論文](https://arxiv.org/abs/1011.0686) | 序列決策違反 i.i.d. 假設；learner 走錯後會進入訓練集沒覆蓋的狀態，需要在 learner 自己訪問的狀態上詢問 expert。 | 只存「玩家或弱 AI 走過的棋」不夠，必須讓 Stockfish/更強 teacher 對那些狀態標 topK/value。 |
| [Catastrophic forgetting, Kirkpatrick et al.](https://arxiv.org/abs/1612.00796) | sequential learning 會忘掉舊能力，需要保護重要權重或其他 continual-learning 手段。 | exp3/exp4/exp5 用小批 replay 覆寫主模型，很容易破壞既有 tactic/opening/endgame 能力。 |
| [Measuring Catastrophic Forgetting](https://arxiv.org/abs/1708.02072) | 常見緩解包含 regularization、ensembling、rehearsal、dual-memory、sparse-coding。 | 目前應改成主模型不變，小型 adapter/experience model 先候選化，再用 rehearsal + holdout gate 決定是否採納。 |
| [Offline RL / BCQ 論文](https://arxiv.org/abs/1812.02900) | 固定批次資料會有 extrapolation error；資料分布與當前 policy 不一致時，標準 off-policy learning 會失效。 | replay 篩選只能減少爛資料，不代表能安全提升 policy；還需要限制 action space 或用 teacher value/policy 做保守更新。 |
| [Stockfish 官方 repo / Fishtest](https://github.com/official-stockfish/Stockfish) | Stockfish 改進依賴 Fishtest 大量測試。 | 我們不能用 10 局或單一 gauntlet 當 promotion 充分證據，至少要獨立 holdout + fresh probes + 統計門檻。 |
| [Maia 論文](https://arxiv.org/abs/2006.01855) / [repo](https://github.com/CSSLab/maia-chess) | Maia 用大量 human games、skill-level 分層、train/validation 流程，目標是預測人類走法而不是單純變強。 | 若要真人風格或分級 AI，資料和目標要分開；Stockfish 強度 teacher 與 human-like teacher 不該混成同一個 loss。 |

## 為何我們一直 retrain 反而退步

目前最可能原因不是「資料完全沒用」，而是 retrain 閉環本身不合格：

1. replay 是當前弱 policy 與人類/heuristic 對手產生，分布偏窄且帶有自身錯誤。
2. Stockfish 篩選目前主要是「過濾或審核」，尚未完整提供 topK policy、centipawn/WDL value、hard negative 與 category label。
3. 小批量 sequential retrain 會把新樣本權重放大，造成 catastrophic forgetting。
4. 訓練目標仍偏「模仿某一步」，而不是「teacher 排序 + value + outcome + search gate」。
5. 現有 benchmark 已被 exp5 多輪優化接近天花板，少量分數變動可能反映 benchmark fitting，而非真實 Elo 提升。
6. exp3/exp4 初始模型容量與特徵較弱，直接吸收 replay 可能只學到局部偏見。

## 保守後續方案

在研究完成前不再 auto-promote retrain 結果。建議下一階段：

1. replay buffer 只當「筆記本」與候選資料池。
2. Stockfish teacher 對 replay 逐局標註：`best_move/topK/cp/wdl/blunder_delta/category`。
3. 訓練只產生小型 adapter/experience model，不覆寫主模型。
4. adapter 必須通過：
   - 舊固定 probes。
   - 新 fresh probes。
   - 人類陷阱 probes。
   - Stockfish skill gauntlet 或 UCI 對局。
   - 舊能力 rehearsal gate。
5. 只有 adapter 在獨立 holdout 穩定改善時，才允許 merge 或作為 runtime ensemble 的 tie-breaker。

## 驗證

- `python3 -m py_compile services/games/chess_pipeline.py tests/games/test_games.py`：通過。
- `python3 -m pytest -q tests/games/test_games.py -k pipeline_autorun`：`2 passed`。
