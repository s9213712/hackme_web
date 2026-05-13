# 2026-05-13 Exp5 模型快照與高階引擎化路線

## 目前模型快照

已保存目前 exp5 模型檔：

- 原始模型：`services/games/models/chess_experiment_5_nnue.json`
- 快照檔：`docs/games/model_snapshots/2026-05-13_exp5_nnue_conversion_88464dba7e3497e7.json`
- sha256：`88464dba7e3497e7be7474e0aae4272801fb2e98838985740e530f592f2ff992`
- 大小：約 `20KB`
- 架構：`nnue-like-sparse-accumulator-v1`
- sample_count：`1837`
- updated_at：`2026-05-13T14:23:10.607868`
- opening overlay：enabled，`exact_position_book_prior`，`31` positions，max fullmove `12`

快照代表「殘局轉換補強後」的基準狀態。當前驗證：

- exp5 score probe：`40.00/40`
- fixed probes：`14.40/14.40`
- 100-case holdout：`100/100`
- complete reviewer games：`2W/3D/0L`
- live smoke：pass，board AI `9/9`，chess practice `12/12`
- 粗略棋力估計：`Elo 1500-1800；非高階引擎`

## 目前不是高階引擎的原因

目前 exp5 已是可用的低中級到中級對手，但離高階引擎仍有明確差距：

- 搜尋深度太淺：預設 balanced 是 depth 2 / qsearch 2 / 320ms。這不足以穩定看穿 4-8 手戰術。
- 評估函數仍偏手工 heuristic：材料、稀疏權重、中心、行動力、王安全、殘局轉換，還缺 pawn structure、king attack、space、piece coordination、rook activity 等完整項。
- 沒有完整 perpetual / fortress / tablebase 級殘局知識：能避免部分三次重複，但還不會系統性地轉化所有勝勢。
- opening book 太小：目前是少量 replay prior 和 overlay，不是完整開局庫。
- 訓練資料尚未嚴格分 train/validation/test：雖然有 100 題 holdout，但還不到真正防過擬合的棋力驗證規模。
- 對手基線弱：目前主要是 fixed probes、random sparring、transparent reviewer policy。要宣稱高階，必須打更強基線。

## 高階引擎化路線

### Phase 1：先穩定到 Elo 1800 附近

目標是讓 exp5 不只是通過固定題，而是在完整局裡穩定贏弱到中等 heuristic 對手。

優先事項：

1. 加入 check extension、recapture extension、passed-pawn-promotion extension。
2. 加入 static exchange evaluation，避免用一手 material-drop filter 取代真正交換判斷。
3. 擴充 repetition handling：領先時避免允許對手 perpetual；落後時允許守和。
4. 補 rook ending / queen ending 基本規則：主動王、切王、側面將、推通路兵、避免無限將。
5. 建立完整局 regression pool：至少 50-100 局，包含白黑雙方、不同開局、不同 reviewer policy。

完成條件：

- fixed probes 維持 `100%`
- 100-case holdout 維持 `>= 95%`
- reviewer 完整局對弱 heuristic 至少 `70%+` 勝率
- 對 stronger heuristic / shallow alpha-beta 至少不低於 `50%`

### Phase 2：往 Elo 2000+ 靠近

這一階需要把它從 heuristic bot 變成比較完整的 Python engine。

優先事項：

1. 搜尋升級：
   - PVS / negamax 保留；
   - transposition table 擴大；
   - null-move pruning；
   - late move reductions；
   - futility pruning；
   - killer/history heuristic 調參；
   - aspiration window 與 time manager 更穩。
2. 評估升級：
   - pawn structure：孤兵、疊兵、通路兵、保護通路兵、後翼多數兵；
   - piece-square tables 分 opening/middlegame/endgame；
   - bishop pair、knight outpost、rook on open file、queen activity；
   - king safety：pawn shield、open file near king、attacker count；
   - mobility 分棋子類型，而不是單一 legal move count。
3. 建立 teacher-labeled dataset：
   - 用下載 PGN 產生真實人類局面；
   - 用強引擎做賽後標註，不在 live 對局代打；
   - 儲存 best move、centipawn eval、WDL、mate distance。
4. 訓練真正的 policy/value/NNUE：
   - train/val/test split；
   - 按開局、中局、殘局分桶；
   - human probes 不進訓練，只當 holdout。

完成條件：

- 100 題擴到 500-1000 題，holdout `>= 90%`
- 對 internal shallow engine 明顯勝出
- 對 Stockfish 低等級或等效 UCI teacher 的限制級別有可重現勝率/和率
- 完整局不再主要靠 repetition 守成

### Phase 3：挑戰高階引擎感

若目標是「像高階引擎」而不是「強一點的網頁 AI」，需要更大的架構調整。

必要項：

1. UCI-compatible engine harness，讓 exp5 可與 Stockfish、其他本地 engine 做自動賽。
2. 多時間控制測試：bullet-like、rapid-like、fixed depth。
3. 開局庫：Polyglot 或等價格式，並有 book exit safety。
4. Endgame tablebase 或 tablebase-like probes：至少 KQK、KRK、KPK、rook pawn endings 的 deterministic solver。
5. 大規模回歸：
   - tactical suite；
   - endgame suite；
   - opening trap suite；
   - human blunder probes；
   - anti-overfitting holdout；
   - full-game gauntlet。
6. 強制產出可解釋紀錄：每一步的 PV、score、depth、nodes、qnodes、tt hit、理由分類。

完成條件：

- 能用同一套 gauntlet 穩定重現提升；
- 能對更強 sparring engine 有非偶然結果；
- 不再需要大量手寫特例才能通過新題；
- 棋力估計才有資格往 `Elo 1800-2200` 或更高討論。

## 下一步建議

最務實的下一步不是繼續加單點 heuristic，而是先做「高階驗證與訓練基礎設施」：

1. 建立 `scripts/games/chess_exp5_gauntlet.py`：完整局 gauntlet，支援多 reviewer policy、多 seed、多 opening start position。
2. 建立 `scripts/games/chess_exp5_tactical_suite.py`：至少 300 題，分 tactic/endgame/opening/repetition/human_probe。
3. 建立 UCI teacher adapter：只用於離線標註與賽後分析，不用於 live move。
4. 實作 SEE 與 search extensions，先不動模型訓練。
5. 每次改動都跑：unit tests、score probe、100/500 holdout、complete gauntlet、live smoke。

這樣做的原因很直接：現在 exp5 分數已接近目前測試上限，繼續只修固定題會失去鑑別度。要變成高階引擎，必須先把測試上限拉高，再讓 engine 在更強、更廣的對局中持續勝出。

## Phase 1 進度追記

已完成第一輪 engine upgrade，詳見：

- `docs/games/2026-05-13_exp5_phase1_engine_upgrade.md`

完成內容：

- 加入 SEE。
- 加入 exp5 搜尋 extension。
- 建立 300 題 tactical suite。
- 建立 16 局多開局 gauntlet。
- score probe 維持 `40.00/40`。
- 300 題 suite `300/300`。
- 16 局 gauntlet `7W/9D/0L`。

下一個瓶頸已從「固定題是否會漏簡單戰術」轉為「完整局能否減少三次重複並提高勝率」。下一輪應處理 pruning/search depth、perpetual-check planning 與 rook/pawn endgame technique。
