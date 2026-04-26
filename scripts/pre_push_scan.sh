#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

echo "=== Architecture Scan: $(date '+%F %T') ==="

printf '\n[1/6] 大檔追蹤（> 1200 行）\n'
wc -l server.py public/index.html public/app.js public/styles.css public/js/*.js routes/*.py services/*.py 2>/dev/null | sort -nr | sed -n '1,20p'

printf '\n[2/6] README 與 SECURITY 關鍵字同步檢查\n'
grep -nE "root\s*/\s*root|Flask-Talisman|CSP|unsafe-inline|pre-push|smoke" README.md README.zh-TW.md SECURITY.md 2>/dev/null || true

printf '\n[3/6] inline 事件處理檢查（應為 0）\n'
rg -n "\\bon[a-z]+\\s*=\\s*['\"]|onclick=|onchange=|oninput=|onsubmit=" public/index.html public/app.js || true

printf '\n[4/6] 重複 TODO/FIXME 檢查\n'
rg -n "TODO|FIXME|XXX|HACK" server.py public/*.js public/js/*.js public/*.css README.md README.zh-TW.md SECURITY.md scripts/*.sh scripts/*.py routes/*.py services/*.py 2>/dev/null || true

printf '\n[5/6] 路由與授權一致性快速檢查\n'
rg -n "@app\.route\(\"/api/admin|role_rank\(actor_role\)|actor\[\"username\"\] == \"root\"|unsafe-inline" routes/*.py server.py 2>/dev/null || true

printf '\n[6/6] 檔名/目錄乾淨度檢查\n'
rg --files | sort

printf '\n[7/7] smoke + security pre-push 測試\n'
python3 scripts/pre_push_checks.py

printf '\n=== Scan complete ===\n'
