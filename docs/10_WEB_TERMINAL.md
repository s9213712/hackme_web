# 10 Web Terminal

一句話說明：WebTerminal 不是 `hackme_web` active main line 的現行功能，現在只保留歷史設計封存供比對與重新設計參考。

## 設計目的

過去曾嘗試 Docker 與 QEMU/libvirt 版 WebTerminal。這些內容對產品歷史與
架構決策有價值，但如果放在部署主線文件裡，會讓新部署者誤以為目前 repo
仍然要一併部署 terminal runtime。

## 使用方法

- 若你只是部署 `hackme_web` 主站：這份文件可以不看。
- 若你在追設計歷史或要重新評估 terminal 類功能：先看本頁，再進
  `docs/archive/webterminal/`。

## 原理

- active main line 沒有現行 WebTerminal routes、settings、frontend 入口或營運腳本
- archive 的角色是保存決策脈絡，不是提供現成部署方案
- 未來若要重啟 terminal 類功能，應開新設計審查，而不是直接復活舊分支

## 失敗情境與提示

- 找不到 terminal 入口頁、設定開關或服務：
  這是正常狀態。
- 以為 `02-WebTerminal-*` 分支可以直接 merge 回 main：
  不建議，應視為歷史資料。

## 測試方式

- 確認 active main line 沒有對外暴露 WebTerminal UI / API
- 確認 archive 仍可被文件導航找到
- 確認新部署者不會在 quickstart / production guide 中誤以為需要部署 terminal

## 相關文件連結

- [docs/archive/webterminal/README.md](archive/webterminal/README.md)
- [VERSION_STORY.md](VERSION_STORY.md)
- [05_FEATURES_OVERVIEW.md](05_FEATURES_OVERVIEW.md)
