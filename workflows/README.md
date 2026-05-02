# Trading Workflow Files

All trading workflow files live under this directory.

- `workflows/system/`: built-in templates tracked by Git.
- `workflows/custom/`: user-created templates generated at runtime and ignored by Git.

Custom templates are stored per user under `workflows/custom/<username>/`.

---

## System Templates (`workflows/system/`)

| 檔案 | 名稱 | 策略類型 | 條件 | 動作 |
|------|------|----------|------|------|
| `dip_buy.json` | 保守逢低買入 | 單條件進場 | price_below + 冷卻 | buy 10% |
| `breakout_buy.json` | 突破追價買入 | 多條件進場 | price_above AND MA50↑ | buy 15% |
| `ma_pullback.json` | MA 趨勢回踩 | 多條件進場+冷卻 | MA50↑ AND RSI≤45 + 冷卻4h | buy 12% |
| `kd_momentum.json` | KD 動能追蹤 | 多條件進場 | KD≥60 AND MA20↑ | buy 10% |
| `ma200_trend_entry.json` | MA200 長線趨勢進場 | 長線過濾進場 | MA200↑ AND MA50↑ AND RSI≤60 + 冷卻6h | buy 15% |
| `rsi_scale.json` | RSI 分批買賣 | 雙向策略 | RSI≤30→買 / RSI≥70+持倉→賣 | buy 10% / sell 50% |
| `bollinger_reversion.json` | 布林通道均值回歸 | 均值回歸 | BB下軌→買 / BB中線+持倉→賣 | buy 10% / sell 50% |
| `swing_bb_ma50.json` | 布林波段+MA50 支撐 | 波段+風控 | BB下軌+MA50↑+空倉→買 / BB上軌+持倉→賣 / SL 7% | buy 20% / sell 50% / close_all |
| `stop_loss.json` | 持倉跌破停損 | 純風控 | has_position AND price≤門檻 | close_all (P100) |
| `risk_guard.json` | 停利停損風控 | 純風控 | SL 5%→全平 / TP 10%→賣半 | close_all (P100) / sell 50% (P50) |
| `full_entry_exit.json` | 完整進出場策略 | 進場+風控 | price≤門檻+空倉→買 / SL 10%→全平 / TP 15%→全平 | buy 80% / close_all |
| `staged_profit_taking.json` | 分批獲利了結 | 分批出場+風控 | SL 8%→全平 / TP 20%→全平 / TP 10%+持倉→賣40% | close_all / sell 40% |

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

1. 在 `workflows/custom/<username>/` 下新增 JSON 檔（格式同上，`"scope": "custom"`）。
2. 系統模板（`scope: system`）由 Git 管理，請勿直接修改，需要客製請複製到 custom 目錄。
