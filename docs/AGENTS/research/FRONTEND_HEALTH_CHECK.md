# Frontend Health Check 前端健康檢查規劃

## 結論

專案功能面已經很廣，最容易出現的問題不是單一 API 壞掉，而是前端按鈕沒反應、錯誤靜默失敗、表格爆版、手機版不易操作、進度不顯示、訊息跑到頁底。需要建立一套可留存腳本的前端健康檢查。

## 目標

- 用 Playwright 或等效工具跑完整 UI smoke test。
- 測試登入、管理、論壇、雲端硬碟、影音、分享、E2EE、交易所、積分錢包、ComfyUI、遊戲區、上線前檢查。
- 檢查功能是否可操作，也檢查 UI 是否人性化。
- 測試腳本留存備查。

## 測試範圍

```text
login/register
admin settings
member management
forum
chat/direct messages
cloud drive
E2EE flows
video upload/playback/HLS/share
share password/session/view limit
trading order/portfolio/margin
points wallet
ComfyUI settings/search/workflow/generation
games/chess
preflight checks
Job Center
Notification Center
```

## UI 品質檢查

- 按鈕點擊後必須有 loading / success / error。
- 錯誤訊息必須在操作區附近顯示。
- 不得有水平捲動。
- 表格在手機版要可讀。
- modal 不可超出螢幕。
- checkbox/radio 不可異常放大。
- 進度型操作必須有進度或階段。
- HLS/影音播放失敗需顯示原因。

## 建議腳本

```text
scripts/testing/playwright_platform_health_check.py
scripts/testing/playwright_deep_site_check.py
scripts/testing/playwright_full_site_check.py
scripts/testing/playwright_visual_health_check.py
scripts/testing/playwright_mobile_viewports.py
```

目前已先保留 `scripts/testing/playwright_platform_health_check.py` 作為平台中心檢查入口；它委派既有 deep-site checker，並保留 `--interactive-comfyui` 讓測試者自行輸入 ComfyUI / Civitai 設定，不把 API key 寫入腳本或 repo。

已新增 `scripts/testing/run_playwright_acceptance.sh` 作為本機與 CI 可共用入口：

```bash
bash scripts/testing/run_playwright_acceptance.sh
```

預設執行：

- `scripts/testing/playwright_comfyui_workflow_builder_check.py`
- `scripts/testing/playwright_platform_health_check.py`

深度全站檢查需明確開啟，避免每次 CI 跑過長：

```bash
RUN_DEEP_PLAYWRIGHT=1 bash scripts/testing/run_playwright_acceptance.sh
```

此入口會使用 `/tmp/hackme_web_playwright_acceptance_*` 隔離 runtime，不使用 port 5000，也不寫入 repo 的 `runtime/` 或 `storage/`。

GitHub Actions workflow 範本留在 `scripts/testing/playwright-qa.workflow.yml`。目前 GitHub token 若缺少 `workflow` scope，不能直接 push `.github/workflows/*.yml`；補權限後可把該範本複製到 `.github/workflows/playwright-qa.yml` 啟用。

## 測試 viewport

```text
360x800
390x844
430x932
768x1024
1366x768
1920x1080
```

## 互動測試案例

- 登入 root、manager、一般 user。
- 管理設定修改後顯示成功或錯誤。
- 交易下單失敗時在表單附近顯示錯誤。
- 影音上傳顯示進度。
- HLS 不能播放時顯示明確原因。
- 分享到期後顯示分享已結束。
- ComfyUI Civitai 搜索顯示縮圖、網址、模型類型過濾。
- ComfyUI workflow editor 節點可拖動、線在線上。
- 雲端硬碟上傳/預覽/分享可操作。
- E2EE 不把明文交給 server-only 功能。

## 驗收標準

- 腳本可本地一鍵執行。
- 失敗時產生 screenshot、trace、console log、network error summary。
- 測試報告列出 bug、UI 問題、效能瓶頸與靜默失敗。
- 測試不污染 production runtime。
- 可選擇是否輸入 ComfyUI URL、Civitai API key 等外部服務資訊。
