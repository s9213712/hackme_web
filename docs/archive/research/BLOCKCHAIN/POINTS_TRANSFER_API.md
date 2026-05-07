# PointsChain Transfer API v1

> **狀態：設計已拍板（root, 2026-05-04），尚未實作完成。**
> 屬於 [POINTSCHAIN_ENGINEERING.md](POINTSCHAIN_ENGINEERING.md) Phase 3 規格。

---

## 1. 設計目的

讓用戶之間能互轉積分，並符合下列拍板原則：

- **Phase 3 僅支援 custodial 模式**；self-custody 簽章在 Phase 5
- **nonce = client UUID + per-address unique + timestamp window**，禁止單調 integer
- **fee 路徑必須完整**（fee_pool / preview / event / 前台顯示），但第一版 fee_rate=0
- **不可轉給自己**；admin 用途走 admin_adjustment
- **不可轉給 burn / mint**；要燒毀走獨立 burn API

---

## 2. API

| Method | Path | 用途 | 角色 |
|---|---|---|---|
| POST | `/api/points/transfer/preview` | 不寫帳，回 fee / 對方類型 / 警告 / 預估餘額 | logged-in |
| POST | `/api/points/transfer` | 真實寫入，需 client_nonce | logged-in |
| GET | `/api/points/transfers` | 自己的轉帳紀錄（incoming + outgoing） | logged-in |
| GET | `/api/points/tx/<event_id>` | 查單筆 event 詳情（自己的或公開的官方地址）| 視來源 |
| GET | `/api/points/tx/<event_id>/proof` | merkle proof | 同上 |

---

## 3. Request / Response

### 3.1 Preview

```http
POST /api/points/transfer/preview
Content-Type: application/json
X-CSRF-Token: ...

{
  "to_address": "PNT1xyz...",
  "amount": "100",
  "currency_type": "soft",
  "memo": "thanks"
}
```

Response 200：

```json
{
  "ok": true,
  "preview": {
    "from_address": "PNT1abc...",
    "to_address": "PNT1xyz...",
    "to_address_type": "custodial",
    "to_address_label": null,
    "amount": "100",
    "fee_amount": "0",
    "currency_type": "soft",
    "estimated_balance_after": "4910",
    "warnings": [],
    "expires_in_seconds": 60
  }
}
```

### 3.2 Final transfer

```http
POST /api/points/transfer
Content-Type: application/json
X-CSRF-Token: ...

{
  "to_address": "PNT1xyz...",
  "amount": "100",
  "currency_type": "soft",
  "memo": "thanks",
  "client_nonce": "550e8400-e29b-41d4-a716-446655440000",
  "timestamp": "2026-05-04T08:00:00Z"
}
```

Response 200：

```json
{
  "ok": true,
  "events": [
    {
      "event_id": "uuid",
      "event_type": "transfer_out",
      "amount": "100",
      "balance_after": "4910"
    },
    {
      "event_id": "uuid",
      "event_type": "transfer_in",
      "amount": "100"
    }
  ],
  "block_id": null,
  "block_pending": true
}
```

`block_pending=true` 表示尚未進 chain block；client 之後可呼叫 `/api/points/tx/<event_id>` 查 block 歸屬。

---

## 4. 拍板規則

### 4.1 來源限制

- `from_address` 必須 = caller `primary_address`
- caller wallet `status='active'`；frozen / revoked 拒絕
- caller wallet 必須有足夠 free balance（不算 frozen / locked）

### 4.2 目標限制

- `to_address` 必須存在 + `status='active'`
- `to_address` **不可** 是 caller 自己的任何 address
- `to_address` **不可** 是 `OFFICIAL_BURN`（要燒毀走 `/api/points/burn`，獨立 API）
- `to_address` **不可** 是 `OFFICIAL_MINT`（mint 永遠不可被轉入）
- `to_address` 是 `multisig` / `official` 類別 → preview 顯示 badge + 警告

### 4.3 金額限制

- `amount` 為 string-encoded integer（與 DB 一致）
- `amount > 0`
- `amount + fee ≤ free_balance`
- `currency_type ∈ {soft, hard}`；不可混用（一筆 transfer 只能是其中一種）

### 4.4 Nonce / Replay

- `client_nonce` 必須是 UUID 格式（v4 推薦）
- per-address 唯一：DB UNIQUE(`from_address`, `nonce`)
- `timestamp` 與 server time 偏離 > 5 分鐘 → reject 「請求過期或時間異常」
- `payload_hash` 不重複（DB level 額外 unique）

### 4.5 Memo

- memo 不直存 DB；存 `memo_hash = sha256(memo).hexdigest()`
- memo 長度上限 256 字元；超過 reject
- memo 不影響 hash chain（避免 sensitive content 被永久寫入）

---

## 5. Ledger Events

一筆成功 transfer 會在 `points_ledger_v2` 產生：

| 順序 | event_type | from_address | to_address | amount | fee_amount |
|---|---|---|---|---|---|
| 1 | `transfer_out` | sender | receiver | amount | 0 |
| 2 | `transfer_in` | sender | receiver | amount | 0 |
| 3（如有 fee） | `transfer_fee` | sender | OFFICIAL_FEE_POOL | fee | fee |
| 4（如有 fee） | `fee_pool_income` | sender | OFFICIAL_FEE_POOL | fee | 0 |

> 第一版 `fee_rate=0`，event 3/4 不會產生；但 service 層代碼必須完整支援，未來改費率不需要 schema migration。

每筆 event 帶相同 `nonce`、不同 `event_id`。`payload_hash` 對每筆獨立計算。

---

## 6. Invariant

每筆 transfer 必須維持：

```
Δ(from)        = -(amount + fee)
Δ(to)          = +amount
Δ(fee_pool)    = +fee
Δ(supply)      = 0
```

寫入後立即 verify：

```python
assert wallet[from].balance_before - wallet[from].balance_after == amount + fee
assert wallet[to].balance_after - wallet[to].balance_before == amount
assert wallet[fee_pool].balance_after - wallet[fee_pool].balance_before == fee
assert supply_state_unchanged()
```

任一不過 → 整 transaction rollback + 進 incident_lockdown 並觸發告警。

---

## 7. UI / UX

### 7.1 轉帳頁（mobile RWD 必過）

| 欄位 | 必填 | 行為 |
|---|---|---|
| 收款地址 | ✅ | 即時 checksum verify；顯示對方類型 badge |
| 金額 | ✅ | 即時驗 ≤ free_balance；超過顯示「餘額不足」 |
| 備註 (memo) | ❌ | 上限 256 字元 |
| 預估手續費 | (顯示) | preview API 算 |
| 轉帳後餘額 | (顯示) | preview API 算 |
| 不可逆警告 prompt | ✅ | 永遠顯示「轉帳一旦送出無法撤回」 |

### 7.2 高風險警告

| 對象 | 警告 |
|---|---|
| 轉到 burn 地址 | 直接拒絕並指引「燒毀請走 /points/burn 頁」 |
| 轉到 mint 地址 | 直接拒絕「不可轉入此地址」 |
| 轉到 multisig / official | 黃色警告「目標為官方/多簽地址，請確認用途」 |
| 轉到 self-custody | 警告「對方是自主錢包，請確認地址正確」 |
| 大額（> 1000 POINTS） | 紅色警告 + 二次確認勾選 |
| 轉到陌生地址（caller 從未交易過） | 黃色警告「未交易過的地址」 |

### 7.3 失敗訊息

| 情境 | 訊息 |
|---|---|
| 餘額不足 | 「餘額不足，需要 X 點，可用 Y 點」 |
| 地址 checksum 錯 | 「地址 checksum 錯誤，請檢查是否打錯字」 |
| nonce replay | 「此次轉帳已送出過，請刷新後再試」 |
| timestamp 偏離 > 5 分鐘 | 「請求時間異常，請重新嘗試」 |
| 轉給自己 | 「不可轉給自己」 |
| 對方 frozen | 「目標地址目前已凍結」 |
| 系統進 incident_lockdown | 「系統暫停金流，請稍後再試或聯絡客服」 |

---

## 8. 成功 / 失敗 audit

| 情境 | 寫入 |
|---|---|
| 成功 transfer | `secure_audit` event `POINTS_TRANSFER_OK` + 2-4 筆 `points_ledger_v2` event |
| 失敗（餘額不足）| `secure_audit` event `POINTS_TRANSFER_INSUFFICIENT` |
| 失敗（nonce replay）| `secure_audit` event `POINTS_TRANSFER_NONCE_REPLAY` |
| 失敗（invariant fail）| `secure_audit` event `POINTS_TRANSFER_INVARIANT_FAIL` + 自動進 incident_lockdown + 通知 root |

---

## 9. QA Gate（細項 [POINTSCHAIN_QA.md §3](POINTSCHAIN_QA.md)）

- [ ] 自動 100 筆 nonce replay 全拒
- [ ] burn / mint / 自己 / 不存在地址 / disabled 地址全拒
- [ ] preview vs final 結果一致（amount / fee / balance_after）
- [ ] 1000 並發 transfer 無 invariant 破壞 + 無重複 event_id
- [ ] 大額 / 官方 / 陌生地址 UI 警告皆觸發
- [ ] 手機版 RWD 通過所有 breakpoint
- [ ] memo 256+ 字元被拒
- [ ] timestamp 偏離 > 5 分鐘被拒
- [ ] currency_type 混用被拒（soft + hard 同筆）
- [ ] event_id / payload_hash 全部 unique（10k 樣本驗證）

---

## 10. 相關文件

- [POINTSCHAIN_WHITEPAPER.md](POINTSCHAIN_WHITEPAPER.md)
- [POINTSCHAIN_ENGINEERING.md](POINTSCHAIN_ENGINEERING.md) §5
- [POINTS_WALLET_ADDRESSING.md](POINTS_WALLET_ADDRESSING.md)
- [MULTISIG_WALLETS.md](MULTISIG_WALLETS.md)
- [POINTSCHAIN_QA.md](POINTSCHAIN_QA.md)
