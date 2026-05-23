# Wallet Payment Model Cleanup

Date: 2026-05-22

Scope:
- Removed the legacy wallet-management default payment wallet UI.
- Replaced the old single-wallet-era "wallet mode" summary card with wallet count + primary address summary.
- Moved fast-path default payment wallet selection to the trading UI only.
- Added paid creation for second and later wallets.

Rules implemented:
- Wallet management no longer sets a global default payment wallet.
- Normal paid features ask for a wallet during their own payment flow.
- Trading keeps a local default payment wallet selector in the trading form because order entry is time-sensitive.
- First wallet is free.
- Wallet number 2+ charges: `min(25 * 2^(existing_wallet_count - 1), 100000)` points.
- Wallet creation fee is charged from an existing active wallet in the same transaction as the wallet bind/create.
- Wallet creation fee destination is `official_treasury`.
- Self-custody fee source requires local wallet service-fee signature.
- Multisig wallet cannot be used as the immediate wallet-creation fee source until the multisig payment flow is implemented.
- Bad quote, insufficient balance, inactive source wallet, and wrong source wallet reject with visible errors.

Legacy findings:
- Removed `economy-spend-source-wallet` from wallet management.
- Removed `renderEconomySpendWalletOptions`.
- Removed user-facing "錢包模式" card text.
- Kept `read/writeEconomyDefaultSpendWalletAddress` as a local preference primitive for trading and payment prompts.
- Kept internal `is_primary` wallet identity because replay, initial grants, lost-wallet reassignment, and default fallback still need a primary identity. It is not a payment selection UI.

QA:
- `python3 -m py_compile services/points_chain/schema.py services/points_chain/service.py services/points_chain/wallet_identity.py services/trading/reporting.py routes/economy.py`
- `node --check public/js/55-economy.js`
- `node --check public/js/56-trading.js`
- `python3 -m pytest -q tests/frontend/trading/test_frontend_economy.py`
- `python3 -m pytest -q tests/points/test_wallet_identity.py`
- `python3 -m pytest -q tests/trading/core/test_trading_engine.py`
- `python3 -m pytest -q tests/points/test_points_chain.py`
- `python3 -m pytest -q tests/points/test_governance_branch.py`
- `python3 -m pytest -q tests/points/test_points_explorer.py -k "governance or official_wallet_grant or transfer"`
- `git diff --check` on touched wallet/trading/PointsChain files
- `python3 /tmp/pointschain_wallet_ui_probe.py`

Browser artifact:
- `/tmp/pointschain_wallet_ui_probe/result.json`
- `/tmp/pointschain_wallet_ui_probe/wallet_trading_selector.png`
