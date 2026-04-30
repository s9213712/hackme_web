# Functional Smoke Script

Canonical documentation lives at
[`docs/security/FUNCTIONAL_SMOKE.md`](../docs/security/FUNCTIONAL_SMOKE.md).

The current script verifies startup, login, major feature flows,
snapshot/restore/reset, TLS file regeneration, storage upgrade visibility,
PointsChain backup/recovery status, and reset restart timing.

Key reset timing expectations:

- `RESET_OFFLINE_TIMEOUT`: 20 秒內必須觀察到連線失敗
- `RESET_RECONNECT_TIMEOUT`: 3 分鐘內重新連線
