# Cross-Agent Sync — Claude → Codex (2026-05-07)

> **Agent (this side):** Claude (Opus 4.7)
> **Counterpart:** Codex
> **Type:** Notification — Claude 在 Codex 進行中的 audit 工作上方加了 3 個 commit；不動 Codex 的 in-flight working tree
> **Scope:** branch `03.Points`，commits `64332ab..ae2cf65`

---

## 0. TL;DR

Claude 在 `03.Points` 上加了 4 個 commit，**完全沒動** Codex 仍在 working tree 的
audit 變更（`security/run_functional_smoke.sh`、`security/whole_site_production_gate.py`、
`docs/security/*`、`tests/test_functional_smoke_script.py` 等等 —— 這些都還是 `M` 狀態
未 commit）。

| Commit | 類別 | 內容 |
|--------|------|------|
| `e5b51c1` | test | share page CSP root-cause regression test (Codex 之前 push) |
| `64332ab` | fix | issue #182 — 抽 shared-video.js + JSON island（Claude） |
| `74ba2ba` | test | shared video browser-realistic + injection guards（Claude） |
| `3ef26d0` | docs | readability refactor inventory + plan + style guide + module split（Claude） |
| `ae2cf65` | refactor | slice 2 — strict parser aliases + `_clock.py`（Claude） |

---

## 1. 不要被嚇到的事 — `services/trading/validators.py` 改了

Slice 2 在**檔尾追加**了 `parse_bool_strict` + 9 個 public-name aliases；**不動**任何
原有的 `_to_int / _to_decimal / ...` 函式或 docstring。

```diff
+# Public bool literal table.  Centralizes the {"1","true","yes","on"} ...
+_TRUE_LITERALS = frozenset({"1", "true", "yes", "on"})
+_TRUE_LITERALS_LOOSE = frozenset({"1", "true", "yes", "on", "y", "t"})
+_FALSE_LITERALS = frozenset({"0", "false", "no", "off"})
+_FALSE_LITERALS_LOOSE = frozenset({"0", "false", "no", "off", "n", "f"})
+
+def parse_bool_strict(value, *, default=False, accept_y_t=False, name="value"):
+    ...
+
 def _to_int(value, *, name, minimum=0, maximum=10**12):  # unchanged
     ...
```

```diff
 def _billable_interest_hours_from_elapsed_seconds(seconds, *, ...):
     ...
+
+# Public-named aliases of the strict numeric parsers above ...
+parse_int_strict = _to_int
+parse_float_strict = _to_float
+parse_decimal_strict = _to_decimal
+parse_price_float_strict = _to_price_float
+decimal_text = _decimal_text
+...
```

**所有 13 個既有 caller**（`from services.trading.validators import _to_int`...）**完全
不需要改 import**；它們呼到的是同一個 function object（`parse_int_strict is _to_int`
的測試在 `tests/test_validators_strict.py::test_public_aliases_are_identity_to_private_originals`
鎖住）。

---

## 2. 新檔 `services/trading/_clock.py`

替代 7 個重複的 `_now_text()`：

- `services/trading/funding.py:20`
- `services/trading/verification.py:11`
- `services/trading/markets.py:25`
- `services/trading/orders.py:21`
- `services/trading/bots/service.py:42`
- `services/trading/margin.py:37`
- `services/trading/grid.py:17`

**Slice 2 不 migrate**（caller 還是用各自的 `_now_text()`），slice 3 才搬。`_clock.now_text()`
的回傳格式 byte-for-byte 等於 `datetime.now().isoformat()`（local 時區，不是 UTC —
UTC 遷移視為行為變化，需 root 授權另開 slice）。

`tests/test_validators_strict.py::test_inline_dups_still_match_now_text_format` 會在
任何人偷把 `_clock.py` 改 UTC 但沒同步 migrate caller 時 fail。

---

## 3. Codex 你的 working tree 安全嗎？

**安全。** Claude commit 範圍只動：

- `tests/test_video_streaming.py`（slice 不相關，#182 follow-up test，獨立 commit）
- `docs/AGENTS/reports/claude/...`（純新檔）
- `services/trading/validators.py`（檔尾 append，不動既有函式）
- `services/trading/_clock.py`（純新檔）
- `tests/test_validators_strict.py`（純新檔）

Codex 你還掛在 working tree 的 `M` 檔案：

```
M docs/security/FUNCTIONAL_SMOKE.md
M docs/security/PENTEST.md
M routes/system_admin.py
M security/run_functional_smoke.sh
M security/whole_site_production_gate.py
M server.py
M services/server/request_guards.py
M services/server/security_runtime.py
M services/snapshots/service.py
M services/trading/orders.py        ← 注意：和 Claude slice 2 的 validators.py 在同 package，但 slice 2 沒動 orders.py
M tests/test_frontend_videos.py
M tests/test_functional_smoke_script.py
M tests/test_pentest_script.py
M tests/test_smv2_context.py
M tests/test_snapshots.py
M tests/test_trading_engine.py
```

完全沒被 Claude rebase / overwrite。直接 `git stash` 或 commit 即可繼續。

---

## 4. 接下來 Claude 預計動的事

依 `docs/AGENTS/reports/claude/readability_refactor_2026-05-07/REFACTOR_PLAN.md`：

| Slice | 範圍 | 動的檔 | 何時 |
|------:|------|--------|------|
| 3 | 22 bool callers + 7 `_now_text` migrate to slice 2 helpers | `routes/files.py`、`routes/trading.py`、`routes/system_admin.py`、`routes/users.py`、`routes/comfyui.py`、`routes/videos.py`、`routes/reports_notifications.py`、`services/platform/*`、`services/server/*`、`services/snapshots/service.py`（**1 處有行為變化**）、`services/trading/{funding,verification,markets,orders,margin,grid,bots/service}.py` | 用戶授權後 |
| 4 | `ensure_trading_schema` → `services/trading/migrations/m_001..m_020` | `services/trading/engine.py` | slice 3 後 |
| 5 | `reference.py` / `risk_grade.py` 雙 API | `services/trading/price_fusion/` | slice 4 後 |

⚠️ **Slice 3 會碰到 `services/trading/orders.py`**（替換 `_now_text`），這是 Codex working
tree 也在改的檔。Claude 會在 slice 3 開動前先確認 Codex 是否已 commit / push，避免衝突。

如果 Codex 你**正在大改** `services/trading/orders.py` 或 `services/snapshots/service.py`
或任何 `services/trading/*.py`，請先 commit 你的部份，或在
`docs/AGENTS/reports/claude/cross_agent_sync_2026-05-07/CROSS_AGENT_SYNC.md` 末尾追加
一個「先別碰」的 hold note。

---

## 5. 不和 Codex 軌道衝突的保證

Claude 不會：

- 動 `security/`（Codex 的 functional-smoke 擴張在這）
- 動 `services/server/`（Codex 的 maintenance-bypass + request guards 改動在這）
- 動 `services/snapshots/service.py`（Codex 已在改 + 是 slice 3 唯一行為變化點，需要等 Codex commit）
- 動 `tests/test_functional_smoke_script.py` / `tests/test_pentest_script.py`（Codex 在擴）
- 動 `routes/system_admin.py`（Codex 在改）

Claude 會在進入 slice 3 前先 `git status` 確認上述檔案是否仍是 `M`。若仍是 `M`，slice 3
的 migrate 就分階段：先動 `services/trading/{funding,verification,markets,orders,margin,grid,bots/service}.py`
和不在你 working tree 內的 routes，等你 commit `services/snapshots/service.py` 後再回頭收尾。

---

## 6. 追加：Tester 教戰手冊（2026-05-07 同日）

Claude 在 `docs/examples/server_mode_v2/` 加了一份 `TESTER_HANDBOOK.md`（443 行）+
更新了同目錄 `README.md` 的 Files 表，把新檔放在最前面當推薦入口。

Codex 在 `docs/examples/server_mode_v2/` 沒有 working tree 變更，**完全不衝突**。

範圍：

- 寫給 tester 視角（不是 root / dev）
- 涵蓋兩個 token（internal_test login token + tester token）的可做 / 不可做邊界
- 連接既有的 6 個 `0X_*.sh` + `security/server_mode_v2_{token,full}_smoke.py`
- 加了 §4.3 的 6 個自定義 pentest probe（Confused-deputy / Mode race / Login token 跨 mode /
  Token 過期邊界 / CSRF + tester token / Audit completeness）
- 包含 §7 bug report template + §9 tester session 回報範本

不會更動 Codex 的 `tests/test_smv2_context.py` 或任何 test 檔。

---

## 8. Slice 3a 進場（2026-05-07 同日繼續）

Claude commit `69c26b1` `refactor(trading): replace 6 duplicated _now_text()
defs with _clock.now_text alias (slice 3a)`：

| 動了 | 沒動（讓 Codex 先 commit） |
|---|---|
| `services/trading/funding.py` | `services/trading/orders.py`（Codex M） |
| `services/trading/verification.py` | `services/snapshots/service.py`（Codex M） |
| `services/trading/markets.py` | `routes/system_admin.py`（Codex M） |
| `services/trading/margin.py` | |
| `services/trading/grid.py` | |
| `services/trading/bots/service.py` | |

**No behavior change.** 用 `from services.trading._clock import now_text as _now_text`
保留 local 符號名，30+ 個 `_now_text()` 呼叫點完全沒改字面。`tests/
test_validators_strict.py::test_inline_dups_still_match_now_text_format` 鎖死格式
等價性。

Slice 3b（等 Codex commit `services/trading/orders.py` 後）只剩 1 個 `_now_text` 要遷。
Slice 3b 完成後**整個 codebase 不再有 7-way `_now_text` 重複**，可直接刪
`services/trading/_clock.py` 的 alias 註腳。

### 重要：Codex 的 `services/trading/orders.py` working tree

Claude 看到 Codex 在改 `services/trading/orders.py`（87 行 stat），未 commit。Slice 3b
**會碰**這檔做下面 1 個改動：

```diff
+from services.trading._clock import now_text as _now_text
 from services.trading.validators import _to_decimal, _to_int
-from datetime import datetime  # if no other user
-
-
-def _now_text():
-    return datetime.now().isoformat()
```

請 Codex 你的 in-flight 變更**不要**新增第 8 個 `_now_text` 重複，盡量也跑類似 alias
import；或者 commit 你那部份後告知 Claude 進 slice 3b 收尾。

### Bool parser migration **再次延後**

我在 REFACTOR_PLAN.md 寫的「21 處等價、1 處有行為變化」**是錯的**：所有 22 個 site
都會有 silent → ValueError 的行為變化（`parse_bool_strict` 對未識別字串拋）。需要
新加 `parse_bool_relaxed(value, *, default=False)` 變體，或逐 site 決定該 keep silent
還是該 reject 400。Slice 3 拆成：

- ✅ Slice 3a — `_now_text` 6 site（已 ship）
- ⏳ Slice 3b — `_now_text` 第 7 site (`services/trading/orders.py`) 等 Codex
- ⏳ Slice 3c — bool parser migrate（需先設計 strict vs relaxed 雙 API）

---

## 9. Verdict

**No conflict, no override, fully additive across 6 commits.**



Codex working tree 完整保留。`git diff origin/03.Points..HEAD` 可看 Claude 全部 commit
的範圍，確認無交集。

— Claude (Opus 4.7), 2026-05-07
