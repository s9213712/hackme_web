# ComfyUI Admin

一句話說明：這份文件只處理 `root/admin` 角度的 ComfyUI / Civitai 管理操作，不重複一般生圖介面教學。

## 先看這份的時機

當你要做以下事情時再打開：

- 決定 ComfyUI 用 `local` 還是 `remote`
- 管理 root-only Civitai 搜尋 / inspect / 下載
- 管理本地模型匯入、VAE、LoRA、ControlNet、workflow preset
- 排查 ComfyUI 能力缺失、下載權限或工作流匯入問題

## 管理順序

1. 先確認站點已正常部署：
   [01_DEPLOY_QUICKSTART.md](../01_DEPLOY_QUICKSTART.md)
2. 再看 root/admin 操作入口：
   [03_ADMIN_GUIDE.md](../03_ADMIN_GUIDE.md)
3. 最後才進 ComfyUI 細節：
   [WEB.md](../WEB.md)

## 重要邊界

- `remote` 模式只負責生圖，不負責把模型下載回本站主機
- `Civitai API Key` 與 root-only 下載工具只在 `local` 模式有意義
- `ComfyUI Account API Key` 只用於官方付費 / API nodes。Key 由 root 在伺服器設定中輸入，前端 workflow JSON、匯出檔與 audit 不可保存明文 key
- workflow preset / workflow JSON 匯入仍要通過 sanitize，不能接受本機絕對路徑、外部 URL、shell / exec 類節點

## 付費 / API nodes

ComfyUI 官方 API nodes 需要 ComfyUI Account API Key。本站的安全邊界是：

- root 必須先在「伺服器設定 / ComfyUI 連線與模型」啟用「允許 ComfyUI 付費 / API nodes」
- `ComfyUI Account API Key` 留空儲存代表不變更；勾選清除才會刪除已保存 key
- `/api/admin/settings` 只回傳 `comfyui_account_api_key_configured`，不回傳明文 key
- 後續執行 workflow 時，後端只在送往本地 ComfyUI `/prompt` 的 payload 補入 `extra_data.api_key_comfy_org`
- 若 workflow JSON、layout JSON 或匯出檔包含明文 key，視為缺陷，必須修正

ComfyUI credit balance 目前沒有穩定官方 REST endpoint 可依賴。第一版只顯示 key 是否已設定與 API node 使用風險；實際點數請在 ComfyUI UI 的 Settings / Credits 中查看。

## 深層參考

- [WEB.md](../WEB.md)
- [For_developer.md](../For_developer.md)
- [12_TROUBLESHOOTING.md](../12_TROUBLESHOOTING.md)
