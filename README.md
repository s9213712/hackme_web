# hackme_web — Hardened Flask Auth Server

A production-oriented single-page authentication server built with Flask, featuring defense-in-depth security controls, role-based access control (RBAC), tamper-evident audit logging, and automated violation tracking.

> 本系統為 html_learning (https://github.com/s9213712/html_learning) 專案的核心認證與管理後端，經歷紅隊滲透測試驗證。

## 系統定位
專為「練習滲透測試」場景設計的合法目標系統。系統本身具備完整防御機制，但刻意保留若干可探測的安全邊界，供學習者練習識別與修補。

## 安全機制
- Argon2id 密碼雜湊（time_cost=3, memory=64MB, parallelism=4）+ fake hash 防時序攻擊 + 計時模糊化
- CSRF：Double-submit cookie + 一次性 token + DB 持久化 + GET 端點用 @require_csrf_safe 不消耗 token
- Session：Fernet 加密 + DB 追蹤 + 一次性 logout
- 速率限制：register 10次/分鐘、login 30次/分鐘、3次失敗封鎖10分鐘
- 帳號枚舉防護：統一錯誤訊息
- CSP via Flask-Talisman（含 unsafe-inline 供 inline JS）
- 3NF 正規化 + HMAC-SHA256 hash chain 稽核日誌

## 角色權限
- super_admin（root，最多1人）：全部權限，含密碼複雜度繞過
- manager（最多5人）：查看審計日誌/違規計次、刪除一般用戶、建立用戶
- user（不限）：基本操作

## 違規處理
- 管理者：3次降級→再犯刪除
- 一般用戶：5次直接刪除

## 快速啟動
pip install -r requirements.txt
~/.pyenv/versions/3.10.14/bin/python3 server.py
預設帳號：root / Admin@1234

## API（部分）
公開：GET /api/csrf-token、POST /api/register、POST /api/login、POST /api/logout
管理（需 manager+）：GET /api/admin/users、POST /api/admin/users、PUT/DELETE /api/admin/users/<id>、POST /api/admin/users/<id>/promote、POST /api/admin/users/<id>/demote、GET /api/admin/violations、POST /api/admin/users/<id>/violation、POST /api/admin/users/<id>/reset-violations、GET /api/admin/audit、GET/PUT /api/admin/settings、POST /api/admin/restart

## 滲透測試結果
XFF IP 分片分片繞過：⚠️ 已知限制（本機可控）
Malformed JSON 不入 fail_log：⚠️ 已知限制
Type confusion → HTTP 500：✅ 已緩解
CSRF/SQLi/帳號枚舉/Session篡改/密碼儲存：✅ 已緩解
詳見 攻防紀錄.md

## 專案結構
server.py、public/index.html（SPA 4-tab 管理介面）、database/database.db（SQLite）、.chain_seed（HMAC seed）、requirements.txt、README.md、SECURITY.md、攻防紀錄.md、attack_test/red_team_report.md、attack_test/blue_team_report.md，以及專用資料夾 `logs/` 下的 audit.log / server.log
