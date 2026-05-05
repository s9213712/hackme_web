# 11 QA Testing

一句話說明：這份文件把部署者、root、QA 與開發者最常需要的驗證路線收斂成一份分層測試地圖。

## 設計目的

原本 QA / 測試資訊散在：

- `QA_MISSION_FOR_AGENTS.md`
- `docs/security/FUNCTIONAL_SMOKE.md`
- `docs/security/PENTEST.md`
- `docs/security/FUNCTIONAL_PERMISSION_PENTEST.md`
- `docs/security/TRADING_STRESS_PENTEST.md`
- `docs/security/PRE_RELEASE_CHECKLIST.md`

這份文件的目標不是取代它們，而是先回答「我要驗什麼、該先跑哪個、哪些其實是 wrapper、哪些是深層 runbook」。

## 使用方法

### 最常用的測試層級

#### 1. Repo / 快速 gate

```bash
python3 scripts/pre_push_checks.py
```

如果有安裝 `hooks/pre-push`，push 前也會先自動執行一輪 `--clean --yes
--ci`：先清掉 repo 內的 Python 快取與誤生在 repo 根目錄的 `runtime/`，
再進 blocking gate。

#### 2. 全量 pytest

```bash
PYTHONPATH=. python3 -m pytest -q tests
```

#### 3. 功能 smoke

```bash
security/run_functional_smoke.sh --port 50741
```

`tests/smoke_suite.py`、`security/run_functional_smoke.sh`、`security/run_pentest.sh`
的 smoke 預設帳密現在已對齊為
`RootSmoke123! / ManagerSmoke123! / TestSmoke123!`。

#### 4. 權限與安全掃描

```bash
security/run_pentest.sh --target https://127.0.0.1:5000
```

若只跑 `whole-site-production-gate`，wrapper 會自動把 timeout floor 拉高到
`900s`，避免舊版預設 `180s` 永遠先把 gate timeout 掉。

#### 5. 角色 / 權限專測

```bash
security/run_pentest.sh --target https://127.0.0.1:5000 --only functional-permissions
```

#### 6. 交易壓力 / 正確性

```bash
PYTHONPATH=. python3 security/trading_stress_pentest.py --target https://127.0.0.1:5000
```

若這次改到交易價格融合或定投上限，另外補跑：

```bash
PYTHONPATH=. python3 -m pytest -q tests/test_trading_engine.py tests/test_trading_reference_prices.py
python3 security/trading_exchange_validation.py --out /tmp/trading_exchange_validation_followup
```

若這次改到 workflow / Grid / backtest 驗證腳本本身，另外補跑：

```bash
PYTHONPATH=. python3 security/trading_workflow_template_validation.py --no-download --limit 200 --out /tmp/trading_workflow_validation_followup
PYTHONPATH=. python3 scripts/trading_backtest_20000_probe.py --include-route --json-out /tmp/trading_backtest_20000_followup.json
```

### 腳本關係

- `scripts/pre_push_checks.py`
  是本機快速 gate，不預設啟 server。
- `security/run_functional_smoke.sh`
  是隔離 runtime 的主要功能回歸；它會保留自己的 `/tmp` runtime 邊界。
- `security/run_pentest.sh`
  是外層 orchestrator，會呼叫多種檢查，包含 `functional-permissions`、
  server-mode-v2、whole-site-production-gate 等子檢查；whole-site gate 會套
  額外 timeout floor。
- `security/functional_permission_pentest.py`
  是權限濫用 / 角色矩陣專測，不是一般 port scanner。
- `tests/smoke_suite.py`
  是極薄的 Python smoke；它現在會在跑完後把暫時打開的 feature flags 還原，
  避免污染同一個測試 runtime。
- `QA_MISSION_FOR_AGENTS.md`
  是 agent 深度 QA runbook，包含人工逐步測試、DB 對帳、異常輸入矩陣與直接修正模式。
- `CLI_ADMIN_PLAYBOOK.md`
  是正式的 `curl` / shell 管理與 API 驗證手冊，適合 root / admin / developer
  在隔離 runtime 直接操作網站。
- `docs/AGENTS/TRADING_QA_REGRESSION_MATRIX.md`
  是交易系統專用的固定回歸清單；只要改到 backtest / workflow / grid / DCA / liquidation /
  融合價格，就不能只跑 `test_trading_engine.py` 或歷史回測。

## 原理

- 不是所有測試都在做一樣的事。
- `smoke_suite.py`、focused pytest、functional smoke、pentest、trading stress
  彼此有交集，但測的是不同層：
  - pytest 偏單元 / 回歸
  - functional smoke 偏隔離 runtime 的實際操作
  - pentest 偏外部攻擊面與權限濫用
  - QA runbook 偏人工逐步驗證
- 因此不要用單一腳本通過就宣稱功能完整。

## 失敗情境與提示

- 只跑 pytest 就想宣稱上線可用：
  不夠，至少還要 functional smoke 與對應安全檢查。
- 想測 production host 卻沒授權：
  不要執行 pentest / stress。
- 測試污染 repo runtime：
  請改用隔離 `/tmp` runtime，參考 `run_functional_smoke.sh` 與 `QA_MISSION_FOR_AGENTS.md`。
- `whole-site-production-gate` 還是被 wrapper 提前 timeout：
  先確認是不是舊版腳本；新版會自動給 `900s` floor。若仍不夠，再明確調高
  `--tool-timeout`。
- 看起來像重複腳本：
  先看這份文件的「腳本關係」；`run_pentest.sh` 多半是 wrapper，不等於和子腳本重複。

## 測試方式

- 確認 README、Start Here、Feature Overview 都把這份文件列為測試主入口
- 若改到 Cloud Drive 檔案瀏覽器，至少手動確認資料夾單擊不誤開、雙擊可進入、右側 `開啟` 按鈕仍可用，且雙擊不會誤觸刪除/下載等 action button
- 確認功能新增後，同步更新 smoke / pentest / QA runbook / troubleshooting
- 若本次改到 ComfyUI，至少補：
  - 設定頁的 `Civitai API Key` 與 root 本地模型下載工具，是否真的只在 `local` 模式出現；切到 `remote` 時不應殘留可操作入口
  - model list 是否回傳 `models / loras / embeddings / vaes`
  - LoRA metadata / `trained_words` 是否會在重新整理後仍存在，不是只在下載當下有
  - 使用者加入 LoRA 時，是否只會補上缺少的 trigger words，而不會每次重複疊加
  - prompt helper 是否能把 Embedding token 正確送進後端
  - custom VAE 是否真的改到 workflow，而不是只有 UI 多一個欄位
  - Civitai inspect / download 是否顯示 trigger words，且 remote mode 不會誤顯示本地下載工具
  - 生圖、本地啟動、模型下載進行中時，閒置登出倒數是否改成暫停，而不是做到一半被踢出
- 若本次改到影音串流 / E2EE 分享，至少補：
  - Safari 是否仍走原生 HLS，而不是被 `hls.js` 蓋掉
  - 桌機 Chrome / Firefox / Edge 是否能載入同源 `hls.js` 並播放 prepared HLS
  - `hls.js` 初始化或 fatal error 時，是否會自動退回 direct `/stream` 並顯示人性化錯誤
  - strict `e2ee` 是否仍只走瀏覽器端解密播放，不可偷偷走伺服器端 HLS
  - `持連結可看` 的 E2EE 影音分享管理面板，是否會顯示分享狀態、剩餘觀看次數、到期日、分享密碼狀態與重新產生 / 撤銷入口
  - manager/root 若能管理 unlisted 影音分享，是否能更新或撤銷 share-link，不可只在 UI 顯示按鈕卻在後端被 owner-only 擋掉
  - 分享頁若沒有 fragment，是否會明確提示「無法復原，只能重新產生分享」
  - 分享頁若有第二層密碼，是否正確要求「完整連結 + 分享密碼」
  - 分享頁若 wrapped file key 被竄改，是否顯示人性化錯誤，不可把原始 exception 直接丟給使用者
  - 手機版播放頁 / 分享頁是否仍能看到播放狀態、錯誤提示與主要按鈕，不可被播放器擠掉
- 若本次改到認證 / CAPTCHA，至少補：
  - `Turnstile site key` 是否只在 `turnstile` 模式出現
  - 切到 `none / math / image` 後，token 欄位是否會隱藏而不是殘留在畫面上誤導部署者
- 若本次改到公告 / 社群編輯流程，至少補：
  - manager/root 是否可直接編輯既有公告，不必刪除重發
  - 一般使用者是否仍會被 `403` 擋下，不能偷改公告
  - 前端是否正確切到編輯模式，按鈕文案會從 `發布公告` 變成 `更新公告`
  - 取消編輯後，公告表單是否恢復成新增模式，而不是把舊內容殘留到下一次發布
- 若本次改到設定頁 / feature flags，至少補：
  - `全開` 是否真的把全部 feature flag 勾開，而不是只補勾目前畫面可見那幾個欄位
  - `最低維運` 是否會把站點收斂到帳號、Audit、健康燈、Server Mode、Snapshot 這組最小骨架，而不是保留舊勾選殘值
  - `設定已儲存` 成功訊息是否會自動消失，而不是長時間誤導 root 以為目前狀態已再次寫入
  - 功能被擋下時，503 / UI 訊息是否有指出真正被關閉的是哪個父功能，而不是只回一句 generic 的 `root 關閉`
  - 若某個父功能關閉，但其子功能仍已開啟，訊息是否有提醒哪些已開功能會一起受影響
- 若本次改到交易價格來源 / 交易所備援，至少補：
  - `融合價格（多交易所加權平均）` 是否真會抓多家交易所，而不是只回單一來源
  - `自動依深度權重` 是否會在單一 API 掛掉時自動用剩餘來源重算，不會整個交易頁直接停擺
  - `root 手動權重` 是否能個別調整 Binance / OKX / Coinbase / Kraken / Gemini / Bitstamp 占比
  - 所有手動權重設成 0 時，是否會安全退回自動深度權重，且 root dashboard / log 會明確標成 `manual weights invalid`
  - root-only `融合價格即時比例` dashboard 是否會列出實際 normalized weights、excluded source 與 `價格來源降級`
  - order book 全失敗時，是否明確標示 fallback source，且不把它當成正常 fused price
  - `GET /api/trading/live-price` 是否每 `2` 秒更新目前價格、漲綠跌紅，且在 fallback / excluded source 時亮黃燈
  - 買入 / 賣出預估是否會跟著同一輪 `live-price` 更新節奏同步重算，而不是停留在舊價
  - 積分錢包裡的現貨 / 進階交易浮盈虧、root 虛擬總額是否也跟著同一輪 `live-price` 更新，而不是等 full dashboard reload
  - `live-price` 回應是否含 `price_health / fallback_reason / excluded_sources / defaulted_market`
  - `live-price` 是否會同步刷新 DB 內 `trading_markets.manual_price_points / price_source` 快取，文件也要寫清楚這不是純 read-only API
  - `security/trading_exchange_validation.py` 是否已和目前引擎結果同步，不再出現過時 expected value
  - `security/trading_exchange_validation.py` 是否會額外檢查連續加倉後 `avg_cost_points` 仍維持合理，不會悄悄爆成異常大值
- 若本次改到交易圖表 / 技術指標，至少補：
  - 參考 K 線圖的 checkbox 是否有同步接進前端事件，不是只有 HTML 多了控制項
  - `MA10 / MA30 / EMA50 / RSI14 / KD(9,3,3)` 是否真的會進入 chart render，而不是只出現在 legend
  - `RSI / KD` 是否走副圖刻度，不可直接沿用價格軸
  - tooltip 是否對價格線與震盪指標用不同格式顯示，不可把 RSI/KD 顯示成 `$54.3`
  - 手機版下指標列是否仍可橫向滑動，不會因新增控制項直接換行爆版
- 若本次改到借貸利息 / backtest 上限，至少補：
  - 現貨 fee 預設 `0.10%`、Grid fee 預設為 spot fee 的 `75%`（25% 折扣）時，
    spot / grid / backtest / 預估 UI 是否全部一致
  - 若本次改到交易市場定義或 provider 對應，至少補 `tests/test_trading_markets.py`
    與 `tests/test_trading_reference_prices.py`，確認 market catalog、display alias、
    live/reference provider id 與 route normalization 都一致
  - `BTC / ETH 8% APR`、`USDT / POINTS 10% APR` 是否會依實際借入資產正確套用，
    而不是所有倉位都吃同一組利率
  - 每 `1` 小時計息、不足 `1` 小時以 `1` 小時計時，前台是否顯示 `累積利息`、
    `已實扣`、`下一次計息`
  - `principal=50, daily_rate=1%, 24h` 是否改成保留 `0.5` 點殘值，而不是直接記成 `1`
  - root 把 `borrow_interest_pool_pressure_multiplier` 設成 `0` 時，實際利率是否真的不再被額外放大
  - 現貨 / 借貸成交後，`volume_stats` 與 root report `volume_summary` 是否同步增加，
    供後續 VIP 系統使用
  - `BTC/USDT 2024-01-01 ~ 2024-12-31 @ 1h` 是否可直接回測，不再被 `5000` 根上限擋住
  - 回測頁在使用者選 `start_time / end_time / timeframe` 時，是否會直接提示另一側日期最遠可設到哪裡，而不是只丟出 `20,000` 根上限
  - 改變 `timeframe` 後，開始 / 結束日期欄位的 `min / max` 是否同步更新
  - `candles < 2` 不可再靜默覆蓋成 live public history；只能在明確 opt-in 時抓 reference candles
  - flat Bollinger 序列不應誤觸發
  - 異常 jump / outlier candle 不能靜默吃成正常高報酬
- 若本次改到 DCA 機器人，至少補：
  - `max_runs=-1` 是否會被正確保存為不限制，而不是被前端或後端偷偷改回 1
  - 跑過一次後再 backdate/重啟，是否仍可繼續執行，不會被誤判為已達上限
  - 不限制模式下 UI 是否不再顯示「增加次數」這種多餘操作
- 若本次改到 BTC_trade 整合，至少補：
  - root 設定 `repo / branch / project path` 後，`檢查 BTC_trade` 是否會正確列出腳本缺漏與資料 / 模型 / 預測狀態
  - `一鍵啟動預測` 是否先檢查資料過期與模型新舊，再決定是否補跑 `update_data.py` / `retrain_models.py`
  - 訓練很久時是否改成背景工作持續輪詢，而不是直接因 timeout 顯示失敗
  - `hourly_check.py` 跑完後是否真的等到新的 `runtime/report_log_4h.jsonl`，或至少明確說明沿用的是仍有效期內的既有預測
  - 長時間執行中途重新整理頁面後，root 是否仍可從背景工作狀態知道目前停在哪個 step
- 若本次改到任何交易核心邏輯，另外強制補：
  - Grid Bot preview 是否同時顯示每格毛利、每格手續費、每格扣費後淨利、
    損益兩平間距與紅 / 黃 / 綠燈，而不是只顯示毛利價差
  - `grid spacing <= break-even spread` 是否會被標成紅燈並阻擋建立
  - `0 < net spread < 0.10%` 是否會變成黃燈並要求二次確認
  - `NaN / Infinity` 是否被 preview API 拒絕
  - `empty candles`、`single candle`、`negative / zero / NaN / missing tick` 是否被正確拒絕或明確標示略過
  - workflow `flat sequence` 是否仍不會誤觸發
  - `security/trading_workflow_template_validation.py` 是否仍包含 workflow `flat sequence` guard，且不再用過時 replay oracle 誤判 graph workflow
  - workflow `stop_loss_percent` 是否使用 scan window low、`take_profit_percent`
    是否使用 scan window high，且目前只標示 long-only 語義
  - `100 -> 10 -> 150` 類 jump / gap collapse 是否有風險警示或 filter，不會製造不真實回測幻覺
  - `full tick [100,80,120]` 與 `sampled [100,120]` 是否仍會出現 stop-loss / liquidation 漏觸發
  - `wallet=0 + trial_credit_only` 與小本金利息案例是否仍維持正確帳務
  - `scripts/trading_backtest_20000_probe.py` 的 Grid 20k case、single-candle reject、outlier skip、flat Bollinger guard 是否都與目前引擎一致
  - 詳細清單見 `docs/AGENTS/TRADING_QA_REGRESSION_MATRIX.md`
- 若本次改到站點外觀 / 個人外觀，至少補：
  - root 改全站預設後，未登入與一般使用者是否都先看到新預設
  - 一般使用者儲存個人外觀後，重新整理與重新登入是否仍會套用
  - 一般使用者按 `恢復全站預設` 後，是否立即預覽 root 的全站外觀，且按 `儲存` 後會真的清掉個人 appearance override
  - root 關閉 `允許使用者覆寫個人外觀` 後，使用者是否看到明確停用提示，而不是靜默失敗
  - 新增的字體風格、背景風格、面板風格、側邊欄寬度在桌面與手機版是否都沒有把按鈕、訊息或側邊欄擠壞
- 檢查腳本重疊是否已有清楚定位，而不是兩份文件各寫一套不同說法

## 相關文件連結

- [QA_MISSION_FOR_AGENTS.md](QA_MISSION_FOR_AGENTS.md)
- [AGENTS/TRADING_QA_REGRESSION_MATRIX.md](AGENTS/TRADING_QA_REGRESSION_MATRIX.md)
- [security/FUNCTIONAL_SMOKE.md](security/FUNCTIONAL_SMOKE.md)
- [security/PENTEST.md](security/PENTEST.md)
- [security/FUNCTIONAL_PERMISSION_PENTEST.md](security/FUNCTIONAL_PERMISSION_PENTEST.md)
- [security/TRADING_STRESS_PENTEST.md](security/TRADING_STRESS_PENTEST.md)
- [security/PRE_RELEASE_CHECKLIST.md](security/PRE_RELEASE_CHECKLIST.md)
- [security/PRODUCTION_SIGNOFF_CHECKLIST.md](security/PRODUCTION_SIGNOFF_CHECKLIST.md)
