# hackme_web 文件入口

[English README](../README.md)

目前 Release ID：`2026.05.13-157`

這份文件只做導覽，不放功能流水帳。近期變更看
[UPDATE_SUMMARY.md](UPDATE_SUMMARY.md)，完整英文索引看
[README.md](README.md)。

## 先從這裡開始

| 你要做什麼 | 先讀 |
|---|---|
| 第一次接手 repo | [00_START_HERE.md](00_START_HERE.md) |
| 本機或 staging 啟動 | [01_DEPLOY_QUICKSTART.md](01_DEPLOY_QUICKSTART.md) |
| production 上線 | [02_DEPLOY_PRODUCTION.md](02_DEPLOY_PRODUCTION.md) |
| root/admin 維運 | [03_ADMIN_GUIDE.md](03_ADMIN_GUIDE.md) |
| 一般使用者教學 | [04_USER_GUIDE.md](04_USER_GUIDE.md) |
| 功能總覽 | [05_FEATURES_OVERVIEW.md](05_FEATURES_OVERVIEW.md) |
| QA / 驗證 | [11_QA_TESTING.md](11_QA_TESTING.md) |
| 故障排查 | [12_TROUBLESHOOTING.md](12_TROUBLESHOOTING.md) |

## 最短啟動

```bash
python3 server.py --doctor
python3 server.py
./test_for_develop.sh --port 50785
```

原則：

- 正式啟動前先跑 `python3 server.py --doctor`。
- 開發測試優先用 `./test_for_develop.sh`，它會在 `/tmp` 建隔離副本。
- 不要直接把 runtime、cache、pytest 產物留在 repo 工作樹。

## 主題路線

| 主題 | 文件 |
|---|---|
| 安全模型 | [06_SECURITY_MODEL.md](06_SECURITY_MODEL.md), [SECURITY.md](SECURITY.md) |
| PointsChain | [07_POINTSCHAIN.md](07_POINTSCHAIN.md) |
| Trading | [08_TRADING_ENGINE.md](08_TRADING_ENGINE.md), [trading/README.md](trading/README.md) |
| Snapshot / Reset / Restore | [09_SNAPSHOT_RESET_RESTORE.md](09_SNAPSHOT_RESET_RESTORE.md), [ops_boundaries/README.md](ops_boundaries/README.md) |
| ComfyUI | [comfyui/README.md](comfyui/README.md) |
| Games / AI | [games/README.md](games/README.md) |
| Video | [video/README.md](video/README.md) |
| Server Mode v2 | [server_mode_v2/README.md](server_mode_v2/README.md) |
| Agent QA / research | [AGENTS/README.md](AGENTS/README.md) |

Trading 背景常駐引擎設計入口：
[trading/TRADING_BACKGROUND_ENGINE.md](trading/TRADING_BACKGROUND_ENGINE.md)。

## 深層參考

- [For_developer.md](For_developer.md)
- [API_REFERENCE.md](API_REFERENCE.md)
- [CLI_ADMIN_PLAYBOOK.md](CLI_ADMIN_PLAYBOOK.md)
- [WEB.md](WEB.md)
- [DEPLOYMENT.md](DEPLOYMENT.md)
- [SYSTEM_DEPENDENCIES.md](SYSTEM_DEPENDENCIES.md)
- [RELEASE_LAYOUT.md](RELEASE_LAYOUT.md)
- [REPOSITORY_STRUCTURE.md](REPOSITORY_STRUCTURE.md)
- [ARCHIVE_INDEX.md](ARCHIVE_INDEX.md)
