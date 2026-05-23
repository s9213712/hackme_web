# PointsChain Governance / Dispute Work Table

| Item | Status | Enforcement / UI |
| --- | --- | --- |
| 疑義交易申報 | Implemented | 交易管理每筆交易提供「疑義交易」按鈕；建立 case，不直接 rollback 或補償。 |
| 疑義交易審核 | Implemented | manager+ 可核准、駁回、核准並建立 recovery governance proposal。 |
| 審核成立同步標記 / 凍結 | Implemented | 核准並提案會同步建立 `ROLLBACK_BRANCH`、`MARK_SCAM`、`FREEZE_ADDRESS` 三個治理案；正式標記 / 正式凍結仍須公共治理通過。 |
| root 審核短期止血凍結 | Implemented | 核准疑義案時對 suspect address 建立 24h provisional freeze，立即阻擋轉出；若要繼續凍結必須執行 `FREEZE_ADDRESS` 治理案。 |
| Recovery 方案二選一 | Implemented | rollback vote 可帶 `recovery_choice`；執行時以通過選項為準。 |
| 官方補缺 | Implemented | 適用 protocol/exchange/treasury fault；官方 treasury 承擔 shortfall。 |
| 用戶自負責 | Implemented | 適用 phishing/private key leak；只退駭客尚未花出的 tainted remainder，不追善意下游收款者。 |
| 多受害者分配 | Implemented | 只納入 manager+ 審核為 approved 的 claims，按 claim amount 比例分配未花餘額。 |
| 緊急鎖定提案 | Implemented | Governance UI 新增 `EMERGENCY_LOCKDOWN` 提案入口。 |
| Mint 申請 | Implemented | Governance UI 新增 `MINT_REQUEST` 入口；仍須官方財庫治理與多簽。 |
| 參數 / 功能 / 銷毀政策 | Implemented | Governance UI 新增 `PARAMETER_CHANGE`、`FEATURE_ACTIVATION`、`AUTO_BURN_POLICY` 入口。 |
| 財庫撥補交易所基金 | Implemented | `EXCHANGE_FUND_REPLENISH` 自動鎖定 EXCHANGE Fund 地址；後端也拒絕非該地址。 |
| 治理與 Explorer 分頁分離 | Implemented | 新增「治理提案」分頁，Explorer 僅保留查鏈功能。 |
| 提案取消 | Implemented | manager+ 可取消未執行提案，寫入 governance audit hash chain。 |
| 倉位管理遺留入口 | Cleaned in UI | 積分錢包頁不再顯示舊倉位 / 資金池頁籤；交易所頁保留下單、倉位與 root 交易管理。 |
| HLS QA 壞檔 | Fixed in runtime | `/tmp/hackme_web_isolated_54343/.../social_profile_video_share.mp4` 已替換為有效 H.264/AAC MP4。 |

Targeted checks:

| Check | Result |
| --- | --- |
| `python3 -m py_compile services/points_chain/service.py routes/economy.py` | pass |
| `node --check public/js/55-economy.js` | pass |
| `pytest -q tests/points/test_governance_branch.py` | pass, 26 tests |
| `ffprobe ... social_profile_video_share.mp4` | pass |
| `pointschain_dispute_api_probe_after_provisional_freeze.json` | pass, recovery / scam label / freeze proposal + provisional freeze all created |
| `pointschain_realistic_recovery_drill_after_metadata_fix.json` | pass, theft + attacker spend + immediate freeze + governance recovery + formal scam/freeze |
| `pointschain_governance_dispute_probe_after_metadata_fix.json` | pass, Playwright governance/dispute UI |
| direct verify | pass, `verify_chain=true`, `governance_audit=true`, canonical branch `pcbranch:c16a3ca7-7746-438d-8689-0b11019ec1f5` |
