# BLOCKCHAIN/origin/ — Historical drafts only (NON-CANONICAL)

> ⚠️ **This folder contains historical drafts and source prompts only.**
> **Canonical specs are the markdown files directly under `docs/BLOCKCHAIN/`.**
> **Do not implement from `origin/`.**

> ⚠️ **此資料夾只保留歷史草稿與原始指令，不是正式規格。**
> **正式規格以 `docs/BLOCKCHAIN/` 根目錄下文件為準。**
> **禁止動工 agent 直接依 `origin/` 內容實作。**

---

## What lives here

| File | What it was |
|---|---|
| `POINTSCHAIN_V2_BLOCKCHAINIZATION_PLAN.md` | early-2026-05 root prompt that initiated PointsChain v2 |
| `POINTS_MINING_REWARDS_PLAN.md` | early QA mining design proposal (now superseded by `../POINTS_MINING_REWARDS.md`) |
| `PRE_BLOCKCHAIN_READINESS_GATE_AGENT_COMMAND.md` | original agent command for Phase 0 cleanup gate (now superseded by `../PHASE_0_CLEANUP_GATE.md`) |
| `QA Mining.txt` | raw research note kept for traceability |
| `blockchain.txt` | raw research note kept for traceability |

---

## Canonical specs (use these instead)

| Topic | Canonical file |
|---|---|
| Whitepaper / user-facing design | [`../POINTSCHAIN_WHITEPAPER.md`](../POINTSCHAIN_WHITEPAPER.md) |
| Engineering schema / API / phases | [`../POINTSCHAIN_ENGINEERING.md`](../POINTSCHAIN_ENGINEERING.md) |
| QA gates per phase | [`../POINTSCHAIN_QA.md`](../POINTSCHAIN_QA.md) |
| Phase 0 cleanup gate | [`../PHASE_0_CLEANUP_GATE.md`](../PHASE_0_CLEANUP_GATE.md) |
| Implementation guide / authorization | [`../IMPLEMENTATION_GUIDE.md`](../IMPLEMENTATION_GUIDE.md) |
| Address scheme | [`../POINTS_WALLET_ADDRESSING.md`](../POINTS_WALLET_ADDRESSING.md) |
| Transfer API | [`../POINTS_TRANSFER_API.md`](../POINTS_TRANSFER_API.md) |
| Multisig (official addresses only) | [`../MULTISIG_WALLETS.md`](../MULTISIG_WALLETS.md) |
| QA Mining / contribution rewards | [`../POINTS_MINING_REWARDS.md`](../POINTS_MINING_REWARDS.md) |
| Folder index | [`../README.md`](../README.md) |

---

## Why this folder still exists

- **Audit trail** — root prompts that originated PointsChain v2 + QA Mining are kept verbatim so future reviewers can reproduce the decision context.
- **Diff source** — the canonical specs are diffable against these originals if anyone needs to verify intent.
- **Not implementable** — the originals were superseded by the canonical files; building from the originals will conflict with what the canonical specs say.

If you find yourself reaching for files in this folder during implementation, **stop** and consult the canonical file from the table above instead.
