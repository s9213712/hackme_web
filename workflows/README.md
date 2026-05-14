# Trading Workflow Files

All trading workflow files live under this directory.

- `workflows/trading_bot/`: built-in templates tracked by Git.
- `runtime/workflows/custom/`: user-created templates generated at runtime and ignored by Git.

Custom templates are stored per user under `runtime/workflows/custom/<username>/`.

---

## System Templates (`workflows/trading_bot/`)

目前保留 **11 個** system templates，目的是讓使用者拿到「**完整風格光譜**」而不是只有
正式對戰冠軍。對抗加賽落敗、偏弱、或重複的候選都已退場。

選擇背後的考量（**Plan B**）：

- 新手在 1 年橫盤行情下需要 dd<10% 的保守選項
- 長期持倉者需要單純 trend-follower（ma200 / ma_pullback）
- 進階使用者要看 head-to-head 決賽冠軍長什麼樣
- 出場策略要可以**獨立**作為教學模板（不混在 entry 內）

### 排名與保留依據

排名公式：時段 1y(30%) + 3y(40%) + 5y(30%) × interval 15m(30%) + 1h(40%) + 4h(30%)，
基於歸檔競賽資料 `docs/archive/competition_2026-05-06/` 的 BTC 單一資產資料；
頭兩個冠亞軍另外採用 `head_to_head_rev3.json` 5 資產 5y 參數調優資料。

| # | 檔案 | 角色 | 平均報酬 | 最大回撤 | 風格 |
|---|------|------|------:|------:|------|
| 1 | `dipbuy_rsi35_70_size99_late_tp15_nopyr_codex.json` | **最終冠軍 / 建議預設** | **+64.40%** | 81.7% | head-to-head 決賽冠軍（Codex，5 資產 5y）|
| 2 | `auto_search_winner_claude_rev3_return.json` | 決賽對照組 | **+60.75%** | 81.8% | head-to-head 決賽亞軍（Claude rev3）|
| 3 | `ma200_trend_entry.json` | 長期趨勢追隨 | +14.07% | 23.1% | ★ 牛市冠軍（3y +29%）|
| 4 | `breakout_buy.json` | 突破追進 | +13.31% | 22.7% | ★ 牛市並列冠軍（3y +29%）|
| 5 | `ma_pullback.json` | 趨勢回踩 | +11.97% | 19.9% | ★ 趨勢追隨（3y +24%）|
| 6 | `dip_buy.json` | 保守逢低買入 | +8.38% | 17.1% | 中段趨勢 |
| 7 | `kd_momentum.json` | KD 動能 | +8.26% | 17.0% | 中段趨勢 |
| 8 | `bollinger_reversion.json` | 布林反轉 | +4.20% | 9.8% | 中庸保守（dd<10%）|
| 9 | `risk_guard.json` | 風控止損 | 0% | 0% | exit-only 工具 |
| 10 | `staged_profit_taking.json` | 分批獲利了結 | 0% | 0% | exit-only 工具 |
| 11 | `stop_loss.json` | 持倉止損 | 0% | 0% | exit-only 工具 |

> exit-only 三件式（#9-11）獨立回測一定 0%（沒有持倉沒事可做），這是預期行為。
> 它們設計為**搭配進場 workflow 一起使用**的範例。
>
> 最終排名與對戰結論見：
> [`docs/archive/competition_2026-05-06/FINAL_HEAD_TO_HEAD_REPORT.md`](../docs/archive/competition_2026-05-06/FINAL_HEAD_TO_HEAD_REPORT.md)

### 已退場的候選

以下模板曾經存在但因為**綜合表現顯著輸給上面 11 個**而退場：

| 退場類別 | 模板 | 退場理由 |
|---|---|---|
| 重複（合併到代表者）| `rsi_scale` | 表現幾乎等於 `bollinger_reversion`（+4.04% vs +4.20%）|
| 重複 | `swing_bb_ma50` | 風險高 dd 17.9% 但報酬僅 +3.49%；方向類似 `bollinger_reversion`|
| 1y 強但長期負 | `full_entry_exit` | 1y +12% 漂亮，但 3y/5y 全 -8%；牛市出場邏輯吃虧 |
| head-to-head 第三 | `auto_search_winner_claude_rev2` | 已被 `_rev3_return` 取代 |
| 對戰中間迭代 | `dipbuy_..._late_tp15_codex` | 含金字塔加碼版；最終冠軍是 `_nopyr` 不加碼版 |
| 對戰中間迭代 | `dipbuy_..._very_late_tp10_codex` | 早期 exploration |
| 顯著負報酬（≤ -0.13%）| 11 個（adaptive/bb_breakout/bb_rsi/breakout_guarded/golden_cross/kd_trend/ma200_rsi_reclaim/trend_floor/trend_pyramid/triple_confirmation/triple_trend_recovery）| 加權 PnL 全部負；保留只會誤導使用者 |

這些結果仍保留在競賽報告與 commit history 中，需要回顧時可見：

- [`docs/archive/competition_2026-05-06/report.md`](../docs/archive/competition_2026-05-06/report.md)
- [`docs/archive/competition_2026-05-06/FINAL_HEAD_TO_HEAD_REPORT.md`](../docs/archive/competition_2026-05-06/FINAL_HEAD_TO_HEAD_REPORT.md)
- [`docs/archive/competition_2026-05-06/REV2_STANDALONE_REPORT.md`](../docs/archive/competition_2026-05-06/REV2_STANDALONE_REPORT.md)

### 欄位說明

每個 JSON 檔包含：

```json
{
  "id":          "唯一識別碼（與檔名一致）",
  "label":       "顯示名稱",
  "description": "一行簡述",
  "scope":       "system",
  "explanation": {
    "purpose":           "策略設計目的",
    "entry_conditions":  ["條件列表"],
    "actions":           ["動作說明"],
    "risk_notes":        ["注意事項"],
    "best_for":          ["適用場景"],
    "tuning":            ["調參建議"]
  },
  "workflow": { ... }
}
```

`workflow` 採用 `strategy_kind: "workflow_graph"`，由 `nodes` + `edges` 描述節點連線圖。

---

## 新增自訂模板

1. 在 `runtime/workflows/custom/<username>/` 下新增 JSON 檔（格式同上，`"scope": "custom"`）。
2. 系統模板（`scope: system`）由 Git 管理，請勿直接修改，需要客製請複製到 custom 目錄。
