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
- workflow preset / workflow JSON 匯入仍要通過 sanitize，不能接受本機絕對路徑、外部 URL、shell / exec 類節點

## 深層參考

- [WEB.md](../WEB.md)
- [For_developer.md](../For_developer.md)
- [12_TROUBLESHOOTING.md](../12_TROUBLESHOOTING.md)
