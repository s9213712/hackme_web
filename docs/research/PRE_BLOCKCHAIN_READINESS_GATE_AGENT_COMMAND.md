# Agent 指令：Pre-Blockchain Readiness Gate / 全站區塊鏈化前驗車

你是一位專業 QA / Release Gate Engineer。
目標是在 `hackme_web` 進入「全站區塊鏈化」分支前，完整檢查目前所有功能是否已足夠穩定、可驗證、可追溯。

你不能只跑 smoke test。
你不能只看 API 200。
你不能只看畫面有沒有開。
你必須驗證「資料是否正確、權限是否正確、帳本是否可重建、交易是否可重算、錯誤是否有提醒、恢復是否真的成功」。

---

## 絕對限制

1. 不直接污染正式 repo runtime。
2. 不使用正在開發中的 port 5000。
3. 所有測試必須在 `/tmp/hackme_web_prechain_qa_*` 隔離目錄執行。
4. 不可只靠現有腳本，要手動製造例外輸入與失敗情境。
5. 所有 finding 必須有：
   - reproduction
   - expected
   - actual
   - command
   - raw output
   - server log / DB evidence
   - severity
   - 是否阻擋進入全站鏈化分支
6. 若發現 Release Blocker，最終結論必須是：`BLOCK NEXT BRANCH`。

---

## Phase 0：建立隔離 QA workspace

```bash
set -euo pipefail

SRC="${SRC:-$HOME/hackme_web}"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
QA_ROOT="/tmp/hackme_web_prechain_qa_$TS"
REPO="$QA_ROOT/repo"
RUNTIME="$QA_ROOT/runtime"
REPORT="$QA_ROOT/report"

mkdir -p "$QA_ROOT" "$RUNTIME" "$REPORT"

rsync -a --delete \
  --exclude runtime \
  --exclude .git \
  --exclude __pycache__ \
  --exclude .pytest_cache \
  "$SRC/" "$REPO/"

cd "$REPO"

git rev-parse --abbrev-ref HEAD | tee "$REPORT/branch.txt" || true
git rev-parse HEAD | tee "$REPORT/commit.txt" || true

mkdir -p "$RUNTIME/database" "$RUNTIME/logs" "$RUNTIME/storage" "$RUNTIME/chats" "$RUNTIME/reports"

echo "$QA_ROOT" | tee /tmp/prechain_qa_root.txt
echo "$REPO" | tee /tmp/prechain_qa_repo.txt
echo "$RUNTIME" | tee /tmp/prechain_qa_runtime.txt
echo "$REPORT" | tee /tmp/prechain_qa_report.txt
```

---

## Phase 1：啟動隔離伺服器

不可用 5000。自動找空 port。

```bash
set -euo pipefail

REPO="$(cat /tmp/prechain_qa_repo.txt)"
RUNTIME="$(cat /tmp/prechain_qa_runtime.txt)"
REPORT="$(cat /tmp/prechain_qa_report.txt)"

cd "$REPO"

PORT="$(python3 - <<'PY'
import socket
s=socket.socket()
s.bind(("127.0.0.1",0))
print(s.getsockname()[1])
s.close()
PY
)"

export HACKME_RUNTIME_DIR="$RUNTIME"
export FLASK_ENV=testing
export PYTHONUNBUFFERED=1

python3 server.py --host 127.0.0.1 --port "$PORT" \
  > "$REPORT/server.out" 2> "$REPORT/server.err" &

SERVER_PID=$!
echo "$SERVER_PID" | tee "$REPORT/server.pid"
echo "http://127.0.0.1:$PORT" | tee "$REPORT/base_url.txt"

sleep 3

BASE="$(cat "$REPORT/base_url.txt")"
curl -ksS "$BASE/" -o "$REPORT/home.html" -w "%{http_code}\n" | tee "$REPORT/home.status"

if ! kill -0 "$SERVER_PID" 2>/dev/null; then
  echo "SERVER FAILED TO START"
  cat "$REPORT/server.err"
  exit 1
fi
```

---

## Phase 2：Smoke Gate

必須驗證：

- server starts
- root login works
- CSRF token works
- trading page loads
- DB writable
- 沒有 fatal server error

```bash
set -euo pipefail

BASE="$(cat "$(cat /tmp/prechain_qa_report.txt)/base_url.txt")"
REPORT="$(cat /tmp/prechain_qa_report.txt)"
COOK="$REPORT/root.cookie"

curl -ksS -c "$COOK" "$BASE/api/csrf-token" | tee "$REPORT/csrf.json"

TOK="$(python3 - <<PY
import json
print(json.load(open("$REPORT/csrf.json")).get("csrf_token",""))
PY
)"

test -n "$TOK"

curl -ksS -b "$COOK" -c "$COOK" \
  -H "Content-Type: application/json" \
  -H "X-CSRF-Token: $TOK" \
  -d '{"username":"root","password":"root"}' \
  "$BASE/api/login" | tee "$REPORT/root_login.json"

curl -ksS -b "$COOK" "$BASE/" -o "$REPORT/root_home.html"
curl -ksS -b "$COOK" "$BASE/trading" -o "$REPORT/trading_page.html" || true

grep -Ei "error|traceback|exception|fatal" "$REPORT/server.err" \
  > "$REPORT/server_error_scan.txt" || true
```

若 smoke 失敗：

```text
Verdict: BLOCKED
Reason: 基礎環境或登入失敗，不能進入後續驗車
```

---

## Phase 3：權限 / 角色 / CSRF 測試

必測：

```text
root
admin
normal user
newbie
disabled user
banned user
tester token
shadow role
maintenance bypass token
```

攻擊測試：

```text
一般用戶呼叫 admin API
admin 呼叫 root-only API
disabled user 下單 / 發文 / 消費積分
缺 CSRF 呼叫寫入 API
改 user_id 操作別人資料
path traversal
```

檢查指令範例：

```bash
set -euo pipefail

BASE="$(cat "$(cat /tmp/prechain_qa_report.txt)/base_url.txt")"
REPORT="$(cat /tmp/prechain_qa_report.txt)"

mkdir -p "$REPORT/permission"

# 無 CSRF 嘗試寫入，必須被拒絕
curl -ksS -X POST \
  -H "Content-Type: application/json" \
  -d '{"title":"csrf bypass test"}' \
  "$BASE/api/posts" \
  -w "\nHTTP:%{http_code}\n" \
  | tee "$REPORT/permission/no_csrf_post.txt"

# 未登入呼叫 admin API，必須被拒絕
curl -ksS "$BASE/api/admin/users" \
  -w "\nHTTP:%{http_code}\n" \
  | tee "$REPORT/permission/anonymous_admin_users.txt"

# path traversal 測試，必須被拒絕
curl -ksS "$BASE/api/cloud-drive/files?path=../../../../etc/passwd" \
  -w "\nHTTP:%{http_code}\n" \
  | tee "$REPORT/permission/path_traversal.txt"
```

Release Blocker：

```text
任意越權成功
root-only 被 admin 使用
未登入可寫入
缺 CSRF 可寫入
disabled/banned user 仍可交易、發文、上傳、消費
```

---

## Phase 4：Points / Wallet / Ledger Replay Gate

必須確認：

```text
wallet balance 可由 ledger replay 重建
每筆 wallet 變動都有 ledger event
每筆 ledger event 都有原因
不能有幽靈積分
不能有負數積分，除非設計明確允許
商城 / 影片投幣 / 平台抽成 / 獎勵 / 退款都有紀錄
```

請寫或執行 replay 腳本，至少輸出：

```text
user_id
wallet_balance_db
wallet_balance_replayed
difference
ledger_event_count
orphan_wallet_delta_count
orphan_ledger_count
```

參考指令：

```bash
set -euo pipefail

REPO="$(cat /tmp/prechain_qa_repo.txt)"
RUNTIME="$(cat /tmp/prechain_qa_runtime.txt)"
REPORT="$(cat /tmp/prechain_qa_report.txt)"

cd "$REPO"
mkdir -p "$REPORT/ledger"

python3 - <<'PY' | tee "$REPORT/ledger/replay_check.txt"
import os, sqlite3, json, glob
runtime=os.environ.get("HACKME_RUNTIME_DIR") or open("/tmp/prechain_qa_runtime.txt").read().strip()
dbs=glob.glob(runtime+"/**/*.db", recursive=True)+glob.glob(runtime+"/database/*.sqlite*", recursive=True)
print("DB candidates:", dbs)
if not dbs:
    raise SystemExit("NO_DB_FOUND")
db=dbs[0]
print("Using DB:", db)
con=sqlite3.connect(db)
con.row_factory=sqlite3.Row
cur=con.cursor()

tables=[r[0] for r in cur.execute("select name from sqlite_master where type='table'")]
print("Tables:", tables)

for required in ["points_wallets","points_ledger"]:
    if required not in tables:
        print("MISSING_TABLE", required)

if "points_wallets" in tables and "points_ledger" in tables:
    wallets=cur.execute("select * from points_wallets").fetchall()
    for w in wallets:
        uid=w["user_id"] if "user_id" in w.keys() else w[0]
        dbbal=w["balance"] if "balance" in w.keys() else None
        rows=cur.execute("select * from points_ledger where user_id=?", (uid,)).fetchall()
        total=0
        for r in rows:
            keys=r.keys()
            if "amount" in keys:
                total += float(r["amount"])
        print(json.dumps({
            "user_id": uid,
            "wallet_balance_db": dbbal,
            "wallet_balance_replayed": total,
            "difference": None if dbbal is None else float(dbbal)-total,
            "ledger_event_count": len(rows),
        }, ensure_ascii=False))
PY
```

Release Blocker：

```text
wallet != ledger replay
ledger event 缺失
points 無來源增加
退款重複發放
trial_credit 混入正式 points
```

---

## Phase 5：交易系統 Gate

必測：

```text
現貨買入
現貨賣出
掛單
撤單
成交
手續費
PnL
position
DCA bot
grid bot
workflow bot
價格融合
order book fallback
stale price
trial credit
zero wallet
```

必打對抗輸入：

```text
負價格
0 價格
NaN
Infinity
極小數
極大數
過期價格
timestamp reversal
duplicate timestamp
manual weights 全 0
order book 全失敗
交易所 API 掛掉
```

要求：

```text
所有 money / price / qty / fee / PnL 都必須用 Decimal 重算。
不准只看 API 200。
```

測試輸出至少包含：

```text
order_id
expected_notional
actual_notional
expected_fee
actual_fee
expected_pnl
actual_pnl
wallet_before
wallet_after
position_before
position_after
```

Release Blocker：

```text
金額算錯
手續費算錯
PnL 算錯
wallet / position / fills 不一致
fallback 靜默發生
invalid input 被接受
```

---

## Phase 6：Trading Bot Audit Gate

必須測：

```text
定時巡檢是否執行
手動立即稽核
歷史訂單重算
觸發條件重算
手續費重算
PnL 重算
wallet / ledger replay
異常分級
safe mode
訂單旁綠燈 / 黃燈
提交 bug 按鈕
```

UI 必須檢查：

```text
稽核通過 → 機器人訂單旁顯示綠燈
稽核失敗 → 顯示黃燈
黃燈旁必須有「提交 bug」按鈕
提交 bug 內容必須包含：
- bot_id
- order_id
- user_id
- expected
- actual
- difference
- evidence
```

Release Blocker：

```text
稽核失敗卻顯示綠燈
稽核異常沒有提醒
safe mode 沒啟動
BLOCKER 後 bot 仍可新下單
bug 按鈕送出資料不完整
```

---

## Phase 7：Snapshot / Restore / Reset Gate

必須跑完整流程：

```text
1. 啟動隔離 runtime
2. 登入 root
3. 建立 baseline post
4. 建立 baseline wallet / ledger / order / file
5. 建立 snapshot
6. 建立 residual post / order / file / points delta
7. restore snapshot
8. 驗證 residual 全部消失
9. 驗證 baseline 保留
10. reset server
11. 驗證 runtime 清空
```

Release Blocker：

```text
restore 回傳成功但 DB 沒回滾
reset 後仍有資料殘留
ledger 與 wallet 不一致
restore 失敗未提醒
restore 失敗未進 incident_lockdown
```

---

## Phase 8：Server Mode / Production Gate

必測模式：

```text
production
preprod
internal_test
test
superweak
maintenance
incident_lockdown
```

必須確認：

```text
模式切換有 hash chain log
superweak 離開後 rollback
test/superweak 資料不污染正式資料
production gate 會檢查 QA 報告
fake report / replay report / missing report 會被拒絕
incident_lockdown 會阻止交易與危險操作
```

Release Blocker：

```text
production gate 可被假報告通過
superweak 資料污染正式環境
模式切換 log 可被竄改
incident_lockdown 仍可下單
```

---

## Phase 9：UI / Mobile / Fail-state Gate

必測：

```text
手機版首頁
手機版論壇
手機版交易頁
手機版機器人頁
手機版稽核中心
手機版商城
手機版雲端檔案
錯誤提示
loading state
failed state
disabled state
```

必須確認：

```text
失敗不能靜默
不要使用一般用戶看不懂的費率縮寫，請直接換算成百分比說明
百分比直接顯示百分比
小數不能被顯示成 0
利息 / 計時 / 手續費 / PnL 前台可見
disabled 功能保留說明，不要整個消失
```

Release Blocker：

```text
財務資訊錯誤或不可見
交易失敗沒提示
稽核異常沒提示
手機版主要流程不可用
```

---

## Phase 10：文件 / README / 測試腳本同步 Gate

檢查：

```bash
set -euo pipefail

REPO="$(cat /tmp/prechain_qa_repo.txt)"
REPORT="$(cat /tmp/prechain_qa_report.txt)"
cd "$REPO"

mkdir -p "$REPORT/docs"

find . -maxdepth 3 \( -name "README.md" -o -path "./docs/*" -o -path "./tests/*" -o -path "./scripts/*" \) \
  | sort | tee "$REPORT/docs/doc_test_inventory.txt"

for f in \
  README.md \
  docs/ADMIN_GUIDE.md \
  docs/TRADING_ENGINE.md \
  docs/POINTS_CHAIN.md \
  docs/SNAPSHOT_RESTORE.md \
  docs/SERVER_MODES.md \
  docs/QA_RUNBOOK.md \
  docs/TRADING_BOT_AUDIT.md
do
  if [ ! -f "$f" ]; then
    echo "MISSING_DOC $f" | tee -a "$REPORT/docs/missing_docs.txt"
  fi
done
```

必須確認：

```text
新增功能有 README
有 API 說明
有錯誤情境
有測試方法
有手動驗證方法
有 safe mode 操作方式
有 restore 操作方式
有鏈化前限制
```

Release Blocker：

```text
新增功能沒有 README
沒有測試腳本
文件與實作矛盾
失敗情境沒有提示說明
```

---

## Phase 11：Final Report

最後產出：

```text
$REPORT/PRE_BLOCKCHAIN_READINESS_REPORT.md
```

格式必須是：

```md
# Pre-Blockchain Readiness Gate Report

## Verdict

PASS / FAIL / BLOCKED

## Branch

## Commit

## QA Workspace

## Server URL

## Release Decision

ALLOW NEXT BRANCH / BLOCK NEXT BRANCH

## Summary

## Release Blockers

| ID | Area | Severity | Summary | Evidence |
|---|---|---|---|---|

## High Severity Findings

## Medium / Low Findings

## False Positives

## Coverage Matrix

| Area | Tested | Result | Evidence |
|---|---|---|---|
| Smoke | yes/no | pass/fail | path |
| Permission | yes/no | pass/fail | path |
| Wallet/Ledger | yes/no | pass/fail | path |
| Trading | yes/no | pass/fail | path |
| Bot Audit | yes/no | pass/fail | path |
| Snapshot/Restore | yes/no | pass/fail | path |
| Server Modes | yes/no | pass/fail | path |
| UI/Mobile | yes/no | pass/fail | path |
| Docs/Tests | yes/no | pass/fail | path |

## Required Fixes Before Blockchain Branch

## Raw Evidence Index

## Final Decision

如果存在任何 Release Blocker：

BLOCK NEXT BRANCH

如果沒有 Release Blocker，但有 High：

CONDITIONAL BLOCK，需 root 決定

只有 Medium/Low 且都有 issue：

ALLOW WITH RISKS
```

---

## 最終判定規則

直接阻擋下一分支：

```text
wallet != ledger replay
交易金額 / 手續費 / PnL 錯
restore 假成功
reset 殘留資料
權限越權
CSRF 繞過
silent fallback
invalid input 被接受
production gate 可被假報告通過
incident_lockdown 仍可交易
bot 稽核失敗卻顯示綠燈
BLOCKER 後 bot 仍可下單
新增功能無文件或無測試
```

允許進入下一分支：

```text
無 Release Blocker
wallet 可由 ledger replay 重建
所有交易訂單可重算
bot 稽核燈號正確
snapshot restore 真正回滾
server mode gate 不可繞過
權限測試無越權
所有失敗都有提醒
手機版主要流程可用
README / docs / tests 已同步
```

---

## 最重要原則

全站區塊鏈化前，先證明目前資料可信。

不要把錯誤上鏈。
不要把錯誤永久化。
不要讓區塊鏈變成 bug 的永久保存器。
