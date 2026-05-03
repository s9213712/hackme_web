# 04 User Guide

一句話說明：這份文件給一般使用者，說明登入後主要功能怎麼用、哪些情況是正常限制、看到錯誤時該怎麼理解。

## 設計目的

部署者與管理員需要一份可以直接給使用者的精簡指南，而不是把 `WEB.md`
整份丟給對方。這份文件保留核心操作流程，讓一般人先能用，再需要時才進深層說明。

## 使用方法

### 使用者登入後通常會做的事

- 修改個人資料與密碼
- 依自己的喜好調整個人外觀，但不影響其他人
- 加入聊天室 / 社群 / 公告 / 討論區
- 使用 Cloud Drive、相簿、影片
- 視站點是否啟用，使用 ComfyUI、PointsChain、交易、遊戲
- 若收到治理通知或處分，可到 Appeals / Notices 檢視

### 最常見功能路線

#### 聊天 / 社群

- 建房、加房、發文、回覆、檢舉
- 權限由角色與 member level 決定

#### Cloud Drive / 相簿 / 影片

- 先上傳檔案，再管理 visibility / albums / share link
- 影片是建立在 Cloud Drive 上，不是第二套儲存系統

#### ComfyUI

- 選模型、提示詞、LoRA、參數後產圖
- 產圖完成後可儲存到 Cloud Drive、分享到論壇或丟棄
- 頁面會明確顯示目前是本地模式還是遠端模式

#### 個人外觀

- 到 `修改資料 -> 個人外觀`
- 可以改字體風格、背景風格、面板風格、側邊欄寬度、顏色、密度、圓角、字級與內容寬度
- 這些設定只改你的畫面；root 設的全站預設仍是其他人的基準

#### PointsChain / Trading

- 站內點數、影片打賞、交易模組都走 PointsChain
- 交易是模擬與驗證用途，不是實盤交易所

## 原理

- 許多使用者操作最後都會落到權限、PointsChain、Cloud Drive、或 feature flag 檢查。
- 因此「看得到按鈕」不等於一定有權限；真正可信的是後端重新驗證後的結果。
- 站點也會依 root 設定顯示或隱藏可選模組，所以不同部署的功能頁面可能不完全相同。

## 失敗情境與提示

- 顯示「此功能目前已由 root 關閉」：
  代表該模組未啟用，或你的角色不足。
- 個人外觀欄位是灰的，或儲存時被拒絕：
  代表 root 暫時關掉了個人外觀覆寫；你的既有個人外觀若先前有存，仍可能繼續套用。
- 顯示權限不足：
  代表後端驗證沒有通過，不是單純前端顯示問題。
- 影片、檔案或預覽打不開：
  可能是 visibility、加密模式、權限、檔案狀態或舊 key 無法解密。
- ComfyUI 產圖中：
  頁面會維持進度與狀態；若 root 設的是遠端 API，模型下載工具本來就不會出現。

## 測試方式

- 以一般使用者身分依序測聊天、發文、上傳、影片、ComfyUI、通知、Appeals
- 驗證未登入、權限不足、功能關閉、資料不存在時的 UI 訊息
- 用 [11_QA_TESTING.md](11_QA_TESTING.md) 的手動逐步測試格式記錄頁面 / API / DB 對帳

## 相關文件連結

- [05_FEATURES_OVERVIEW.md](05_FEATURES_OVERVIEW.md)
- [12_TROUBLESHOOTING.md](12_TROUBLESHOOTING.md)
- [WEB.md](WEB.md)
- [VIDEO_PLATFORM.md](VIDEO_PLATFORM.md)
- [08_TRADING_ENGINE.md](08_TRADING_ENGINE.md)
