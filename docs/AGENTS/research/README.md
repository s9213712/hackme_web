# hackme_web Research Plans

本資料夾放置後續可實作功能的獨立研究與規劃文件。這些文件不是立即開工承諾，而是用來定義功能邊界、資料模型、安全要求、分期路線與驗收標準。

## 建議優先順序

1. [JOB_CENTER.md](JOB_CENTER.md)：統一背景任務中心。
2. [NOTIFICATION_CENTER.md](NOTIFICATION_CENTER.md)：統一通知中心。
3. [FRONTEND_HEALTH_CHECK.md](FRONTEND_HEALTH_CHECK.md)：前端健康檢查與 UI smoke test。
4. [SHARE_LINK_MANAGEMENT.md](SHARE_LINK_MANAGEMENT.md)：分享連結管理中心。
5. [TRADING_ASSET_OVERVIEW.md](TRADING_ASSET_OVERVIEW.md)：交易所與積分資產總覽強化。
6. [BLOCKCHAIN/](BLOCKCHAIN/README.md)：PointsChain v2 Phase 1 / 1A / 2。
7. [LLM_WEBCHAT/](LLM_WEBCHAT/README.md) 與 [AI_WEBCHAT_READONLY_MVP.md](AI_WEBCHAT_READONLY_MVP.md)：AI WebChat read-only MVP。
8. [AI_manage_WEB/](AI_manage_WEB/README.md)：AI 管理控制台。
9. [DISCORD/](DISCORD/README.md)：Discord 同步。

Other research proposals:

- [POINTS_ONRAMP_BSC_USDT_PROPOSAL.md](POINTS_ONRAMP_BSC_USDT_PROPOSAL.md)：BSC USDT 進入 Points 的外部金流研究；不是目前部署功能。

## 共通原則

- 不繞過既有 RBAC、CSRF、Server Mode、audit log 與資料隔離規則。
- 先做 read-only / observable / preview，再做 write / execution。
- 背景長任務必須可追蹤、可取消、可重試、可審計。
- 錯誤不可靜默失敗，必須在使用者可見的位置顯示明確階段與原因。
- 手機版必須可用，不得出現水平捲動或不可點擊的小控制項。
