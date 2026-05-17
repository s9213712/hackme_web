# Game Area Playability Audit

Date: 2026-05-17
Branch: 03.Points

## Scope

實際登入測試站並啟動遊戲區 18 款遊戲，檢查美術觀感、手機觸控、操作提示、可玩性、明顯 UI 遮擋與前端錯誤。

## Fixed Findings

- 手機版快速操作列會浮在遊戲畫面上方，捲動到棋盤或 3D 遊戲中段時遮住提示、按鈕與畫面。已改成手機版頁面流內工具列，不再覆蓋遊戲。
- 遊戲區頂部文案像功能清單，玩家入口感不足。已改成短提示，並新增每款遊戲切換時的操作 / 目標提示。
- 彈幕遊戲雖有畫出判定點，但頁面外層看不到明確說明。已新增「黃點=中彈判定；藍圈=擦彈範圍」提示。
- 真實版俄羅斯方塊狀態列顯示小數分數，玩家讀起來像 debug 數值。已改為整數分數顯示。
- 開放世界步行缺少落地感。已加入玩家地面影子、腳步擺動、手臂反向擺動與步行 bob，降低漂浮感。
- 圍棋 / 五子棋在手機上格子過小。已讓棋盤在手機保持可點擊尺寸，並由棋盤容器水平滑動，不造成整頁橫向溢出。

## Verification

- Playwright 實玩回歸：18 款遊戲全數啟動與基本互動通過。
- Mobile Playwright：彈幕、開放世界、FPS 無橫向溢出；圍棋 / 五子棋棋盤容器可水平滑動，body scrollWidth 維持 viewport 寬度。
- Syntax / whitespace:
  - `node --check public/js/38-games.js`
  - `node --check public/js/games/open-world.js`
  - `node --check public/js/games/real-tetris.js`
  - `node --check public/js/games/bullet-hell.js`
  - `git diff --check`

Artifacts:

- `/tmp/hackme_game_play_audit_20260517/game_regression_after_fixes.json`
- `/tmp/hackme_game_play_audit_20260517/game_experience_after.png`
- `/tmp/hackme_game_play_audit_20260517/mobile_actionbar_fixed.png`
