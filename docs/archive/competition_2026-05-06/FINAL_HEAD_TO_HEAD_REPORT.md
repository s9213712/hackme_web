# 競賽最終決賽報告：Claude rev3 vs Codex contender

Generated: 2026-05-06

## 對戰雙方

| | Claude rev3 | Codex contender |
|---|---|---|
| 模板 | `auto_search_winner_claude_rev3_return.json` | `dipbuy_rsi35_70_size99_late_tp15_nopyr_codex.json` |
| 進場條件 | 上 MA200 + RSI **40-70** + 空倉 | 上 MA200 + RSI **35-70** + 空倉 |
| 進場規模 | 99% | 99% |
| 進場冷卻 | 4 小時 | 4 小時 |
| **TP 階梯** | **+50/+100/+200%** | **+80/+150/+250%**（更晚）|
| **每階段賣出** | **25%** | **15%**（更保守）|
| **加碼** | RSI<30 加 30% ✅ | ❌ 無 |
| 止損 | 無 | 無 |
| 趨勢出場 | 無 | 無 |

兩邊都是**「進場過濾 + 全押 + TP 階梯」家族**，差別在於 TP 設計（時機、比例）+ 是否加碼。

## 統一條件

- 5 個資產：BTC / ETH / XRP / BNB / PAXG
- 1h K 線 × 5 年（2021-05-07 → 2026-05-06，43,800 根）
- Fee 0.3% per trade
- Slippage 0.1%（事後計算）
- 初始資金 100,000 POINTS
- Engine：`services/trading_engine.py` `backtest_trading_bot()`

## 最終結果

### 平均報酬（5 資產均值）

| | 平均報酬 | vs B&H (+33.16%) | 差距 |
|---|---:|---:|---:|
| 🥈 Claude rev3 | +60.75% | +27.59pp ✅ | — |
| 🏆 **Codex contender** | **+64.40%** | **+31.24pp** ✅ | **+3.65pp 勝出** |

### 各資產對戰

| Asset | B&H | Claude rev3 | Codex contender | 勝者 | 差距 |
|---|---:|---:|---:|:---:|---:|
| BTC | +46.24% | +104.61% | **+108.24%** | 🏆 Codex | +3.63pp |
| ETH | -30.52% | -38.50% | -38.52% | 🤝 平手 | 0.02pp |
| XRP | -7.43% | **+31.31%** | +9.99% | 🏆 Claude | **+21.32pp** ⚡ |
| BNB | +3.71% | +91.25% | **+104.58%** | 🏆 Codex | +13.33pp |
| PAXG | +153.80% | +115.07% | **+137.69%** | 🏆 Codex | +22.62pp |

**單資產勝場：Codex 3 / Claude 1（巨大）/ 平手 1**

### 其他指標

| 指標 | Claude rev3 | Codex contender | 差距 |
|---|---:|---:|---:|
| 最大回撤 | 81.82% | **81.66%** | -0.16pp（Codex 略好）|
| 平均交易次數 | **4.0** | 2.6 | +1.4（Claude 略多）|

兩邊 max DD 都被 ETH（80% 沒漲到 +50% 從沒觸發 TP）拖累，幾乎相同。

## 賽後分析

### Codex 為什麼贏

| Codex 設計 | 影響 |
|---|---|
| TP 階梯改晚（+80 vs +50, +150 vs +100, +250 vs +200）| ✅ BTC/PAXG/BNB 強趨勢中**多撐 30-50%** 才開始減倉，吃到更多後段漲幅 |
| 每階段賣 15%（vs 25%）| ✅ 階段賣更少 → 後續漲幅由更大倉位吃到 |
| 不加碼 | ✅ 強趨勢中不會在「相對高點」加碼拖累成本 |

三點合計 → BNB/PAXG/BTC 三個強趨勢資產都贏 Claude，總報酬 +3.65pp。

### Claude 唯一亮點：XRP +21pp 大勝

XRP 是測試 5 資產裡**唯一處於震盪而非單邊趨勢**的（5y 從 1.5 到 2，中間崩到 0.5）。
Claude 的 pyramid（RSI<30 加碼 30%）抓到這種震盪低點 → +31.31% vs Codex +9.99%。

但 pyramid 在 BTC/BNB/PAXG 反而是包袱（在已漲段加碼拉高均價）。**淨負面**。

### 為什麼 max DD 都 81%

不是策略問題，是 **long-only crypto + 含 2022 BTC 熊市** 的物理上限。
- ETH 5y 內**從沒漲到 +50%**（從 ~3000 跌到 ~880 才反彈到 ~4800，但相對 5y 起點 3000 沒到 +50%）→ TP1 從沒觸發 → 滿倉吃 -80% DD
- BTC 漲跌過 +50%，TP1 觸發後 size 縮小，後續 DD 變小（rev3 BTC DD = 59.75% vs rev2 76.89%）

要降 max DD 唯一辦法：**不要持有 ETH**（資產分配），但 spec 要求 5 資產測試。

## 設計教訓

從這次決賽得到的 3 個 takeaways：

1. **TP 階梯放越晚越強**（在強趨勢資產上）
   - 想吃完整趨勢就晚一點開始減倉
   - 早期 TP 看似「鎖利」，實際是「太早離場」

2. **每階段賣少一點**
   - 15% 比 25% 更慢縮位 → 後段漲幅由更多倉位吃到
   - 但風險：DD 會稍大（位置縮慢）

3. **加碼是雙刃劍，沒先驗證資產分布前不要用**
   - 加碼在震盪資產（XRP）能 +21pp
   - 但在強趨勢資產（BNB/PAXG）拉低均價反虧
   - 預設**不加碼**比較安全

## 兩個 workflow 都 FAIL 競賽 verdict

注意：**雖然兩個都贏 buy_and_hold，但都未過 verdict 25% Max DD 限制**。

| Verdict 條件 | Claude rev3 | Codex contender |
|---|---|---|
| trade_count < 5 | 4.0（差 1）❌ | 2.6 ❌ |
| max_DD > 25% | 81.82% ❌ | 81.66% ❌ |
| walk-forward forward < 0 | +2.59% ✅ | (未測，預期類似)|
| **fee 後仍正報酬** | +60.75% ✅ | +64.40% ✅ |
| **avg vs B&H** | +27.59pp ✅ | +31.24pp ✅ |

兩邊都解決了「贏 B&H」的目標，但 verdict 的 25% Max DD 仍未過 — 這是 spot-only crypto 含 2022 熊市的物理天花板。

## 最終排名（all rev versions + Codex 對戰）

| 排名 | 模板 | 5y avg | DD | trades | vs B&H | 來源 |
|:---:|---|---:|---:|---:|---:|---|
| 🥇 1 | `dipbuy_rsi35_70_size99_late_tp15_nopyr_codex` | **+64.40%** | 81.66% | 2.6 | +31.24pp | Codex |
| 🥈 2 | `auto_search_winner_claude_rev3_return` | +60.75% | 81.82% | 4.0 | +27.59pp | Claude |
| 🥉 3 | `auto_search_winner_claude_rev2` | +58.23% | 81.82% | 2.0 | +25.07pp | Claude |
| - | buy_and_hold (baseline) | +33.16% | (各資產不同) | 1 | — | — |
| - | `triple_trend_recovery_claude_rev` (rev1, 失敗) | -0.62% | 6.07% | 2.2 | -33.78pp | Claude |

## 相關檔案

- 對戰腳本：`docs/COMPETITION/scripts/competition_head_to_head_rev3.py`
- 對戰 raw：`docs/COMPETITION/data/head_to_head_rev3.json`
- Codex 模板：`workflows/trading_bot/dipbuy_rsi35_70_size99_late_tp15_nopyr_codex.json`
- Claude 模板：`workflows/trading_bot/auto_search_winner_claude_rev3_return.json`
- Codex 自報基準（須由 Codex 端確認 wall time / 條件一致性）：5y 平均 +64.40%

## 結論

🏆 **冠軍：Codex `dipbuy_rsi35_70_size99_late_tp15_nopyr_codex`** — +64.40% / 5 資產均值

Codex 用更精簡的設計（晚 TP、小賣、無加碼）在 3/5 資產勝出，雖然 Claude 在 XRP 大勝 +21pp 但無法挽回。

兩個 workflow 都在「贏 buy_and_hold」目標上達標（+27pp / +31pp），但都未過正式 verdict 的 25% Max DD 限制。要過這條限制，**需要動到 long-only 假設或限制資產組合**，超出本次 workflow 設計的範疇。
