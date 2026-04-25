# hackme_web — 帳號登入系統

## 功能

- ✅ 帳號註冊（密碼需 8+ 字元，含大小寫字母及符號）
- ✅ 登入 / 登出
- ✅ 密碼使用 **Argon2id** 雜湊儲存（密碼學上更優於加密）
- ✅ 同一 IP 連續輸入錯誤 3 次 → 鎖定 10 分鐘
- ✅ 預設帳號：`root` / `Admin@1234`

## 環境

```
pip install -r requirements.txt
```

## 啟動

```bash
python server.py
# 開啟 http://localhost:5000
```

## 資料庫

- `database.db` — SQLite，密碼欄位經 Argon2id 雜湊
- `blocked_ips.json` — 被鎖定的 IP 列表
- `fail_log.json` — 登入失敗計數

## API

| Method | Endpoint       | 說明 |
|--------|----------------|------|
| POST   | /api/register  | 註冊帳號 |
| POST   | /api/login     | 登入 |
| POST   | /api/logout    | 登出 |

## 密碼規則

- 至少 8 個字元
- 包含至少一個大寫字母
- 包含至少一個小寫字母
- 包含至少一個符號：`!@#$%^&*()_+\-=\[\]{};':"\\|,.<>\/?`
