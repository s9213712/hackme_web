# 12 Troubleshooting

一句話說明：這份文件集中列出新部署者、root、一般使用者最常遇到的錯誤與第一輪排查方式。

## 設計目的

過去錯誤排查散在各功能文件，部署者容易知道「它壞了」但不知道「先去哪一份找解法」。這份文件把常見故障先收斂成運維與使用情境導向的入口。

## 使用方法

### 啟動 / 部署類

#### 1. 服務啟動了但打不開

先檢查：

- host / port 是否正確
- 如果你是直接執行 `python3 server.py`，是否其實應該用
  `https://127.0.0.1:5000/` 而不是 `http://127.0.0.1:5000/`
- port 是否被占用

#### 2. root 上傳大檔時直接出現 HTTP 413

先分清楚這不是雲端硬碟配額，而是伺服器單次 request body 上限。

- 現在 server 會用 `HTML_LEARNING_MAX_CONTENT_MB` 控制這個入口上限
- 預設值是 `1024 MB`
- 若反向代理（例如 nginx）也有限制，還要同步調整 proxy 的 body size

API 會回：

- `error = request_too_large`
- `max_request_mb = ...`

如果 root 明明還有很多容量，但一開始就收到 `413`，先看：

1. `HTML_LEARNING_MAX_CONTENT_MB` 是否太小
2. 代理層是否還卡著較低的 upload cap
3. 這台 runtime 是否其實還跑舊版 server code
- 代理 / HTTPS / cookie 設定是否跟實際部署拓樸一致

#### 2. 頁面正常但登入或寫入 API 全部 `403`

優先看：

- CSRF token 是否失效
- 是否剛改完 bootstrap 密碼；改密碼後舊 session 會立即失效，需重新登入再取新 CSRF token
- 是否剛改密碼 / 登出 / 權限切換 / reset 過
- 是否在舊分頁上送請求

#### 3. 啟動後跑出很多 runtime 檔，不確定能不能 commit

不能。DB、logs、storage、reports、keys、certs 都應留在部署地 runtime。

#### 3-1. root 忘記密碼怎麼辦

不要走登入頁的 `忘記密碼`。

`root` 已刻意排除在一般 web password reset / email token / 管理審核之外。
正式補救方式是到站台實體 runtime 上執行：

```bash
python3 scripts/root_recovery.py --json
```

或互動式輸入新的 root 臨時密碼：

```bash
python3 scripts/root_recovery.py --prompt-password
```

這個 CLI 會：

- 直接重設 root 臨時密碼
- 撤銷 root 現有 session
- 清掉 root 既有 CSRF token
- 強制 `must_change_password=1`
- 盡量寫入離線 recovery 審計紀錄

注意：

- CLI 輸出的臨時密碼只會顯示一次；遺失後只能再次執行工具重設
- 如果你用 `--password ...` 直接帶值，會留在 shell history；正式環境建議用 `--prompt-password` 或讓工具自動產生

### 功能關閉 / 權限類

#### 4. 看到「此功能目前已由 root 關閉」

代表 feature flag 或相依模組未完整開啟，不一定是 bug。先看：

- [03_ADMIN_GUIDE.md](03_ADMIN_GUIDE.md)
- [05_FEATURES_OVERVIEW.md](05_FEATURES_OVERVIEW.md)

新版訊息若有帶出「被關閉的父功能」或「會一起受影響的已開功能」，先照那份提示回頭檢查，不要只看你原本想用的那個頁面開關。

#### 5. 看到權限不足

先分辨：

- 你真的角色不夠
- 該模組需要更高 member level
- root 只開了入口沒開完整底層功能

#### 5-1. 找不到個人外觀，或外觀欄位無法編輯

先分辨：

- 你是不是用自己的帳號開 `修改資料`
- root 是否已關掉 `允許使用者覆寫個人外觀`
- 你是不是只做了預覽、但還沒按儲存
- 想直接回到全站預設時，請用編輯視窗底部的 `恢復全站預設`，再按一次 `儲存`

#### 5-2. 找不到 `Turnstile site key`

先分辨：

- `註冊 CAPTCHA 模式` 是不是 `turnstile`
- 如果目前是 `none / math / image`，這個 token 欄位現在會刻意隱藏
- 你是不是還停在舊快取頁面；先重新整理設定頁

#### 5-3. `設定已儲存` 一直掛著不消失

先分辨：

- 你看到的是不是黃色依賴警告，而不是綠色成功訊息
- 新版綠色 `設定已儲存` 會自動消失；若還一直停著，先重新整理確認是不是舊前端快取
- 若訊息內容有提到 `缺少父功能`，那不是 save 卡住，而是設定已寫入、但功能組合仍不完整

### Cloud Drive / Video / ComfyUI 類

#### 6. 影片或檔案無法預覽 / 播放

常見原因：

- E2EE 檔案無法走 server-side 影片串流
- `server_encrypted` 檔案的舊 key 已不可用
- 檔案被 quarantine / 權限不足 / visibility 不符
- 若音樂檔以前被當成 generic blob type，舊前端快取可能仍無法 inline 預覽；先硬重新整理確認已升到 `2026.05.04-090`

#### 6-a. PDF 預覽打不開

先分辨：

- 你是不是還停在舊前端快取；先硬重新整理確認已升到 `2026.05.05-121`
- 一般 / `server_encrypted` PDF 現在會直接用 `/preview/content` 搭配瀏覽器原生 PDF 檢視器
- strict `e2ee` PDF 仍是瀏覽器端解密；若內嵌檢視器失敗，畫面會提供「在新分頁開啟 PDF」備援
- 若檔名含日文 / 中文，以前某些 header 會讓 PDF viewer 不穩；新版已補 `filename*=` UTF-8 路徑

#### 6-b. 第二個 E2EE 檔案又重新要求輸入密碼

先分辨：

- 新版會先嘗試「這個檔案之前成功過的密碼」以及「本次登入 session 最近成功過的密碼」
- 若仍跳出詢問，通常代表：
  - 兩個檔案不是同一組密碼
  - 你中途已登出 / session 被清掉
  - 或前端仍是舊快取

#### 6-c. 壓縮檔預覽看起來只有一坨文字

先分辨：

- 新版壓縮檔預覽會顯示資料夾 / 檔案清單、大小、壓縮後大小與備註
- 若你還看到單段文字明細，通常是舊前端快取，先硬重新整理確認已升到 `2026.05.05-121`

#### 6-0. Cloud Drive 雙擊資料夾沒有進入

先分辨：

- 你是不是還停在舊前端快取；先硬重新整理確認已升到 `2026.05.04-095`
- 你雙擊的是不是右側 action button 區；雙擊進入只作用在資料夾列本體
- 若滑鼠或觸控板環境不方便雙擊，右側 `開啟` 按鈕仍可作為備援

#### 6-1. 影音自訂封面圖上傳了，但發布後沒有套上

先分辨：

- 你是「直接上傳影音」還是「從雲端硬碟選既有影音檔發布」
- `2026.05.04-090` 之後，這兩條路徑都支援封面上傳；較早版本只會在直接上傳影音時處理 cover
- 封面檔必須是圖片；若誤選非圖片，API 會明確回 `cover_not_image`

#### 6-2. 共享 strict E2EE 影音一直顯示讀取中

先分辨：

- 新版共享頁會依序顯示：
  - `正在讀取 E2EE 分享授權`
  - `正在下載加密影音檔`
  - `正在瀏覽器端解密影音`
- strict E2EE 共享影音仍是舊方法：先下載密文、再在瀏覽器端整檔解密，因此大檔真的會比 HLS 慢
- 若你只看到單句舊版 `讀取中`，多半是前端快取未更新，先硬重新整理確認已升到 `2026.05.05-121`

#### 7. ComfyUI 有頁面但不能下載模型

如果 root 把 ComfyUI 設成 remote API 模式，這是預期限制；模型下載只對
本地模式有意義。設定頁裡的 `Civitai API Key` 也只會在本地模式顯示。

#### 8. ComfyUI 找不到 Embedding / VAE / trigger words

先分辨：

- 頁面標題現在會明確顯示是本地模式還是雲端 / 遠端模式；先確認你看的模式是不是你以為的那個
- `Embedding` / `VAE` 清單是從 ComfyUI API 讀的；如果 ComfyUI 本身沒有列出，
  網頁也不會憑空顯示
- Civitai `trigger words` 只有 root、本地模式、且成功讀到該版本資訊時才會顯示
- LoRA 自動補 trigger words 只對「透過 root 的 Civitai 下載面板下載，且有保存 sidecar metadata」的 LoRA 生效
- `SD1.5`、`Flux`、或沒有 `base_model` metadata 的 LoRA 現在會直接顯示不可用；
  目前生圖頁只允許 `SDXL`、`Pony`、`Illustrious`、`Noob` 系列 LoRA
- 名稱帶 `neg` / `negative` 的 Embedding 快捷按鈕會直接寫進負面提示詞；
  再按一次則會從目前所在的提示詞移除
- ControlNet 類型目前支援 `Canny`、`Depth`、`OpenPose`、`Lineart / Scribble`、`SoftEdge`、`Tile`
- 若頁面直接提示缺少 ControlNet 模型 / node / preprocessor，代表後端能力檢查已拒收這次設定；不是靜默忽略

#### 9. ComfyUI 長任務跑到一半

- 前端會暫停閒置登出；目前包含本地啟動、生圖、root 模型下載
- 若 job 卡住，先看 status / job progress / backend reachability

### 經濟 / 交易類

#### 10. 餘額看起來不對

先驗證：

- PointsChain verify
- 是否為 root 模擬交易餘額而非正式 wallet
- 是否為 restore / recovery 後尚未重建 wallet

#### 11. 交易頁數字正常但成交失敗

先看：

- live price provider 是否失效
- 如果 root 用的是 `融合價格（多交易所加權平均）`，先看是否只剩太少健康來源，或手動權重把有效來源全設成 0
- circuit breaker 是否擋下異常價格
- 餘額 / 借貸池 / 手續費條件是否不足

#### 11-0a. 交易圖表看不到 RSI / KD，或指標線和價格疊在一起看不懂

先分辨：

- 你是不是只開了價格 overlay，沒有勾 `RSI14` 或 `KD(9,3,3)`
- RSI / KD 會畫在副圖，不會和價格共用同一條刻度；若你看到舊版畫面，多半是前端快取沒更新
- `1d` 或資料筆數不足時，部分均線可能暫時還沒有值；這是資料窗口不足，不是 API 壞掉
- 若 tooltip 把 RSI/KD 顯示成金額格式，代表頁面還是舊版快取，先硬重新整理

#### 11-2. ComfyUI 產圖很久才完成，擔心太早逾時

- `2026.05.04-084` 之後，ComfyUI 前後端預設等待上限已提高到 `30 分鐘`
- 若仍看到逾時，先分辨是：
  - ComfyUI 真正在排隊 / 載模型 / 生成太久
  - 還是你目前瀏覽器頁面仍是舊前端快取
- 先硬重新整理；若 log 裡仍是後端先回 `ComfyUI 產圖逾時`，再檢查模型大小、顯卡負載與 ComfyUI 服務本身是否正常

若你看到交易頁的 `目前價格` 已經在跳，但積分錢包裡的現貨 / 進階交易盈虧不動：

- 先確認 server 是否已升到 `2026.05.04-080`
- 確認你停留在 `交易所` 或 `積分錢包` 頁面，而不是其他完全無交易 UI 的模組
- 這一版之後，wallet 浮盈虧會跟著同一輪 `live-price` 每 `2` 秒重算；若仍卡住，多半代表前端還是舊快取，先硬重新整理

#### 11-0. root 找不到交易所融合權重設定，或改了卻沒有生效

先分辨：

- `價格來源` 是否仍是 `融合價格（多交易所加權平均）`
- 只有在 `root 手動權重` 模式下，手動權重輸入框才會生效
- 若你把所有手動權重都設成 0，系統會安全退回自動深度權重，而不是照 0 權重硬算出錯價
- 若某家交易所 API 失效，系統會用剩餘健康來源重算；這不等於設定沒有生效
- 直接看 root 的 `融合價格即時比例` dashboard：
  - 若顯示 `manual weights invalid`，代表目前其實已退回 `auto_depth`
  - 若顯示 `價格來源降級`，代表 order book 已失敗並退回單一 ticker / 保守模式
  - 若 `excluded providers` 有來源，代表那些 API 已 timeout / failed / malformed，不是靜默消失

#### 11-1. 小額交易的手續費和你手算不同

先分辨：

- 你是不是還在用舊版 `ceil` 心智模型手算
- 目前 release 是否已經是 `2026.05.03-063` 之後；新版整數 POINT fee 會用
  `Decimal` 後端計算後四捨五入到最近整點
- 你比較的是 `預估值` 還是實際成交 fill
- 你是不是還把 Grid 手續費當成舊版 `50%` 折扣；目前預設已改成 spot fee 的
  `75%`（也就是 `25%` 折扣）

#### 11-1a. Grid 預覽看起來有價差，但系統卻不讓我建立

先分辨：

- 新版 Grid preview 不是只看 `upper-lower` 價差，而是會先扣掉買入 / 賣出手續費
- `紅燈` 代表扣費後預期虧損，或每格金額太小，連最小資產單位都買不到
- `黃燈` 代表扣費後仍可能賺，但淨利太薄，必須二次確認
- `損益兩平間距` 會直接告訴你至少需要多大 spread；若你的 `每格間距` 沒大過它，這不是 bug，而是設計上阻擋虧損網格

#### 11-2. 定投機器人明明設成 `-1`，卻好像還是停了

先分辨：

- 你看的是否是 DCA 機器人；`-1` 只對定投機器人代表不限制
- 它是不是卡在冷卻時間 / 間隔時間，而不是次數上限
- 若 UI 顯示 `已觸發 x / 不限制`，代表上限邏輯已生效；若仍沒跑，應回頭查餘額、價格區間或功能開關

#### 11-3. 借貸利息看起來變慢了，或小本金 1 天後沒有直接多 1 點

先分辨：

- 目前 release 是否已經是 `2026.05.04-066` 之後；新版會先累積 `interest_carry_micropoints`
  與 `interest_exact_points`，不再把 `0.5` 這種小額利息直接進位成 `1`
- 你比較的是 `interest_points` 還是 `interest_exact_points`
- root 是否把 `borrow_interest_pool_pressure_multiplier` 設成 `0`；新版會尊重這個值，不再偷偷退回預設倍率
- 你看的倉位借的是 `BTC / ETH` 還是 `USDT / POINTS`；現在兩組 APR 是分開的，
  做多與放空可能因此看到不同利率
- 前台是否已有 `累積利息` 與 `下一次計息`；若沒有，代表你看的可能還是舊版頁面或舊快取
- 若你是看 `損益平衡價` 或 `逐倉估算強平價`，要知道這兩個值現在也會跟著
  `累積利息` 一起變動；即使現價不動，只要計息小時數增加，價格門檻也可能改變

#### 11-4. 全年 `1h` 回測以前跑不動，現在還是被擋

先分辨：

- 目前 release 是否已經是 `2026.05.04-067` 之後；新版總上限是 `20,000` 根，不是舊的 `5,000`
  或單批 `10,000`
- 你送的 `candles` 是不是超過 `20,000` 根

#### 11-5. 交易頁目前價格不動、和參考 K 線不同、或突然亮黃燈

先分辨：

- 目前價格卡片現在是每 `2` 秒用 `GET /api/trading/live-price` 更新，不是跟著整個 dashboard 的 `5` 秒刷新頻率
- 買入 / 賣出預估會跟著同一輪 live-price 更新重算；若只有圖表在變但預估沒變，先確認你看的是否是舊前端快取
- 交易卡上的 `目前價格` 是實際交易參考價；參考圖表的最新收盤只是 chart reference，不保證完全相同
- 若看到綠字 / 紅字，表示新版正在用最新一筆價格和上一筆做方向比較
- 若看到黃燈，代表 `live-price` 已回傳 `price_health != healthy`，常見原因是：
  - `fallback_reason` 有值

#### 11-6. 功能套餐按了 `最低維運` 之後，怎麼很多頁面都不見了

先分辨：

- `最低維運` 不是「小幅縮減」，而是直接把站點切回帳號、Audit、健康燈、
  Server Mode、Snapshot 這組最小可維運骨架
- 若你只是想補齊某套服務，應改用 `帳號治理整套`、`社群互動整套`、
  `雲端硬碟整套` 這種加開型套餐
- 套餐按完後還要再按一次 `儲存設定` 才會真的寫入；若只是誤點，可在離開前再切回
  `全開` 或其他套餐
  - `excluded_sources` 不為空
  - order book 已降級成 fallback / cached source
- `GET /api/trading/live-price` 不是純 read-only；它會順便把最新 `manual_price_points / price_source` 快取寫回 DB，方便後端後續撮合共用同一份最新價
- 若是 API 自動抓歷史 K 線，請確認 `start_time / end_time / timeframe` 是否真的落在你想要的區間
- 若是 `10,001 ~ 20,000` 根之間，這已改成後端自動分段續跑，不需要再手動拆兩次回測
- 若你不確定 `20,000` 根到底代表多久，直接看回測頁日期欄位下方提示；
  新版會依目前週期告訴你「若保留開始時間，結束最晚可選到哪裡」或反過來提示開始最早可選日期

#### 11-5. 回測結果看起來像被系統自己換成真實行情

先分辨：

- `2026.05.04-070` 之後，只有在你明確送 `auto_fetch_reference_candles=true`
  時，後端才會自動下載 reference candles
- 若你送的 `candles` 太短、但又沒有 opt-in，預期行為應是拒絕而不是自動改抓 live 行情
- 若你還看到靜默換行情，先確認正在跑的 server 版本是否真的已升到 `2026.05.04-070`

#### 11-6. Bollinger 回測在平盤也亂交易

#### 11-7. BTC_trade 一鍵啟動跑很久，畫面卻以前會直接報 timeout

先分辨：

- 目前 release 是否已經是 `2026.05.04-072` 之後；新版已把 `一鍵啟動預測`
  改成背景工作，root 端只會輪詢 step 狀態，不再把長時間訓練直接視為失敗
- 狀態列是不是停在 `重訓 BTC_trade 模型`
- `update_data.py` / `retrain_models.py` / `hourly_check.py` 是否真的存在於你設定的 BTC_trade 專案目錄
- `runtime/report_log_4h.jsonl` 在預測腳本完成後是否有更新時間或新的 `generated_at`

若仍失敗，應看到的是：

- 腳本缺失
- 腳本實際 return code 非 0
- 或「預測腳本已執行，但在等待時間內沒有看到新的預測資料」

先分辨：

- 目前 release 是否已經是 `2026.05.04-070` 之後；新版 `std=0` 的 flat 序列不應再觸發
  `below_lower` / `above_upper`
- 你的測試資料是否真的全部是同價 flat candles
- 回測結果裡是否已有 `range_warnings` 或其他 warning，表示資料本身被視為異常

### 恢復 / reset 類

#### 12. reset 後資料不見

這通常是預期結果。先找：

- `pre_reset` snapshot
- reset 後是否已重啟

#### 13. restore 完還以為 secrets / certs 會回來

目前的 server snapshot 會一起保存並回放設定好的 runtime secret files。
如果 restore 後這些檔案沒有回來，先看 restore event 是否出現
`runtime secret validation failed`，再檢查 snapshot metadata 內的
`runtime_secret_files` 清單。

## 原理

這些故障大多不是單一頁面的問題，而是：

- runtime 目錄與 repo 混在一起
- feature flags 與底層依賴未成套啟用
- session / CSRF / role / member level 邊界被忽略
- 把 snapshot restore、PointsChain restore、reset 當成同一件事

## 失敗情境與提示

- 問題看起來是 UI，但其實是權限或後端模式：
  先從 feature flags / role / mode / CSRF 開始排。
- 問題看起來是資料壞了，但其實只是顯示舊頁：
  先重新整理、重新登入、重新取 token。
- 問題看起來是功能 bug，但其實是部署拓樸錯誤：
  先檢查 HTTPS、proxy、runtime path、XFF 信任設定。
- 問題看起來像是 QA 腳本互打：
  先確認 smoke 與 pentest 是否共用同一組 smoke 帳密，以及 whole-site gate
  是否已用新版 timeout floor。

## 測試方式

- 把本文件列出的常見錯誤納入 smoke / pentest / 手動 QA
- 驗證錯誤訊息是否能讓使用者知道：
  - 發生什麼事
  - 為什麼可能失敗
  - 下一步可以怎麼做
- 驗證 root 可在 log / audit / job status 中查到原因

## 相關文件連結

- [01_DEPLOY_QUICKSTART.md](01_DEPLOY_QUICKSTART.md)
- [02_DEPLOY_PRODUCTION.md](02_DEPLOY_PRODUCTION.md)
- [03_ADMIN_GUIDE.md](03_ADMIN_GUIDE.md)
- [05_FEATURES_OVERVIEW.md](05_FEATURES_OVERVIEW.md)
- [06_SECURITY_MODEL.md](06_SECURITY_MODEL.md)
- [09_SNAPSHOT_RESET_RESTORE.md](09_SNAPSHOT_RESET_RESTORE.md)
- [11_QA_TESTING.md](11_QA_TESTING.md)
# Troubleshooting

## 聊天附件在哪裡加入？

- 聊天附件不再放在獨立大卡片裡。
- 進聊天室後，直接在訊息輸入框下方用 `上傳附件` 或 `從雲端檔案附加…` 即可。
- 檔案選定後會立即進入待送清單；真正送出是在按 `送出` 訊息時。
- 新上傳的附件在實際使用聊天室 / 私訊 / 公告附件功能時，會寫進你的雲端硬碟 `/attachments/` 路徑，不會再散落在根目錄，也不會預先多建立另一套附件系統。
- `聊天室共用附件` 只會在該聊天室本來就有共用附件時才顯示。
## Repo 根目錄又長出 `.fkey` / `.chain_seed` / `cert.pem`

新版預設會把 DB、logs、storage、runtime secrets、TLS 憑證都收進
`runtime/`。若你仍在 repo 根目錄看到 `.fkey`、`.chain_seed`、`cert.pem`
這類檔案，通常代表：

- 先前是舊版啟動過，殘留在 repo 根目錄
- 或某個腳本仍顯式指定了舊路徑

處理方式：

1. 確認目前沒有流程還在使用 repo 根目錄那份 runtime 狀態
2. 清掉 repo 根目錄殘留的 ignored runtime artifacts
3. 重新啟動後，確認新的 runtime state 已落在 `runtime/`

如果要放到別的位置，請改設 `HACKME_RUNTIME_DIR` 或各個
`HTML_LEARNING_*_DIR` 環境變數。
