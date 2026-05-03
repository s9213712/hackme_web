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
- 若本次改到認證 / CAPTCHA，至少補：
  - `Turnstile site key` 是否只在 `turnstile` 模式出現
  - 切到 `none / math / image` 後，token 欄位是否會隱藏而不是殘留在畫面上誤導部署者
- 若本次改到設定頁 / feature flags，至少補：
  - `設定已儲存` 成功訊息是否會自動消失，而不是長時間誤導 root 以為目前狀態已再次寫入
  - 功能被擋下時，503 / UI 訊息是否有指出真正被關閉的是哪個父功能，而不是只回一句 generic 的 `root 關閉`
  - 若某個父功能關閉，但其子功能仍已開啟，訊息是否有提醒哪些已開功能會一起受影響
- 若本次改到站點外觀 / 個人外觀，至少補：
  - root 改全站預設後，未登入與一般使用者是否都先看到新預設
  - 一般使用者儲存個人外觀後，重新整理與重新登入是否仍會套用
  - root 關閉 `允許使用者覆寫個人外觀` 後，使用者是否看到明確停用提示，而不是靜默失敗
  - 新增的字體風格、背景風格、面板風格、側邊欄寬度在桌面與手機版是否都沒有把按鈕、訊息或側邊欄擠壞
- 檢查腳本重疊是否已有清楚定位，而不是兩份文件各寫一套不同說法

## 相關文件連結

- [QA_MISSION_FOR_AGENTS.md](QA_MISSION_FOR_AGENTS.md)
- [security/FUNCTIONAL_SMOKE.md](security/FUNCTIONAL_SMOKE.md)
- [security/PENTEST.md](security/PENTEST.md)
- [security/FUNCTIONAL_PERMISSION_PENTEST.md](security/FUNCTIONAL_PERMISSION_PENTEST.md)
- [security/TRADING_STRESS_PENTEST.md](security/TRADING_STRESS_PENTEST.md)
- [security/PRE_RELEASE_CHECKLIST.md](security/PRE_RELEASE_CHECKLIST.md)
- [security/PRODUCTION_SIGNOFF_CHECKLIST.md](security/PRODUCTION_SIGNOFF_CHECKLIST.md)
