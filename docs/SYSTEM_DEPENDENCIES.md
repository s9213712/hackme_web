# System Dependencies

一句話說明：這份文件集中列出 `hackme_web` 的 Python 套件、系統 binary、
外部服務與環境變數依賴，讓部署者不用在 README、Quickstart、部署腳本與功能文件之間來回拼湊。

## 1. Python Dependencies

安裝方式：

```bash
python3 -m pip install -r requirements.txt
```

目前 `requirements.txt` 會安裝：

- `flask`
- `cryptography`
- `flask-talisman`
- `argon2-cffi`
- `gunicorn`
- `python-chess`
- `websocket-client`

## 2. Required System Binaries

這些是「沒有就會直接少能力，或部署/驗證流程不完整」的系統層依賴。

### 2.1 Core Deploy / Verification

- `python3`
- `git`
- `curl`

用途：

- 建立虛擬環境、啟動站點
- clone / update repo
- 驗證 `/api/version`、跑 smoke / pentest 類腳本

### 2.2 Video / HLS

- `ffmpeg`
- `ffprobe`

用途：

- 影音 metadata 偵測
- HLS 衍生檔生成
- 串流準備流程

缺少時的行為：

- 一般站點仍可啟動
- 影音平台會降級成較少能力的模式
- `./one_click_setup.sh --check` 會明確警告，不是靜默失敗

## 3. Optional Feature Binaries

### 3.1 BT / Magnet Remote Download

- `aria2c`

用途：

- Cloud Drive 的 BT / magnet 下載

缺少時的行為：

- 一般 HTTP/HTTPS 遠端下載仍可用
- BT / magnet 會被明確拒絕，並回覆安裝指引

### 3.2 Malware Scanning

- `clamscan` 或 `clamdscan`

用途：

- Upload security / 惡意檔案掃描

注意：

- 目前設定只接受 `clamscan` / `clamdscan` 這兩個命令名，不接受自訂路徑或參數
- 若部署者啟用掃描但系統沒有安裝對應 binary，掃描能力會失效或被拒絕啟用

## 4. External Services / Integrations

### 4.1 ComfyUI

可選外部服務，不是第一步部署阻塞項。

用途：

- 本地或遠端生成工作流
- 模型管理與 root-only 工具

相關文件：

- [COMFYUI_ADMIN.md](comfyui/COMFYUI_ADMIN.md)
- [WEB.md](WEB.md)

### 4.2 Civitai

需要：

- `CIVITAI_API_KEY`

用途：

- root-only Civitai 搜尋 / 下載

缺少時的行為：

- 本地 ComfyUI 與本地模型上傳仍可用
- 只有 Civitai 搜尋 / 下載能力停用

## 5. Runtime Files And Paths

這些不是 repo 應追蹤的靜態檔，而是啟動後才在本機生成的 runtime 資料：

- `runtime/database/`
- `runtime/storage/`
- `runtime/chats/`
- `runtime/logs/`
- `runtime/anchors/`
- `runtime/reports/`
- `runtime/database/chess_experiment.db`
- `runtime/.chain_seed`
- `runtime/.csrfkey`
- `runtime/.fkey`
- `runtime/.filekey`
- `runtime/.integrity_key`
- `runtime/integrity_manifest.json`
- `runtime/cert.pem`
- `runtime/key.pem`

Legacy repo-root 目錄如 `attachments/`、`avatars/`、`media/`、`uploads/`
不再是 canonical runtime home；若在 repo root 看到它們，應視為歷史殘留或
舊 restore 路徑的副產物，而不是新的正式放置位置。

若要覆寫西洋棋 `experiment` 學習資料庫位置，請使用：

- `HTML_LEARNING_CHESS_ENGINE_DB_PATH`

## 6. Failure Semantics

### 6.1 Fail Closed

這些情境應被視為阻擋或明確拒絕，而不是偷偷降級：

- 交易 risk-grade price 不足以支撐高風險動作
- 嚴格 E2EE 分享缺少必要 fragment / envelope
- Upload security 設定非法 scanner command
- BT 下載要求 `aria2c` 但系統未安裝

### 6.2 Degraded But Explicit

這些情境可以降級，但必須有明確提示：

- 缺少 `ffmpeg` / `ffprobe`
- 缺少 `CIVITAI_API_KEY`
- 剛部署後尚未 rebaseline 的 `integrity_guard` 健康狀態

## 7. Recommended Operator Flow

第一次部署建議順序：

1. 看 [00_START_HERE.md](00_START_HERE.md)
2. 跑 [01_DEPLOY_QUICKSTART.md](01_DEPLOY_QUICKSTART.md)
3. 若要 production，再看 [02_DEPLOY_PRODUCTION.md](02_DEPLOY_PRODUCTION.md)
4. 若要精準知道哪些能力依賴哪些 binary / key，就回到這份文件

## 8. Related Docs

- [README.md](../README.md)
- [01_DEPLOY_QUICKSTART.md](01_DEPLOY_QUICKSTART.md)
- [DEPLOYMENT.md](DEPLOYMENT.md)
- [RELEASE_LAYOUT.md](RELEASE_LAYOUT.md)
- [REPOSITORY_STRUCTURE.md](REPOSITORY_STRUCTURE.md)
