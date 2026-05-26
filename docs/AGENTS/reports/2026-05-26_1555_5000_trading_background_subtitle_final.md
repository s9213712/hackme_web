# 2026-05-26 15:55 - Trading Background and Subtitle Final Check

## Scope

- Continued QA on the live `https://127.0.0.1:5000` server.
- Rechecked server-owned trading background jobs without active member browser sessions.
- Rechecked the large encrypted/E2EE video server on `https://127.0.0.1:51475`.
- Left both servers running for manual inspection.

## Findings

No product defect remains confirmed from this pass.

The first trading probe exposed a QA harness setup problem: the liquidation test account received the normal 100-point signup bonus, and cross-margin correctly counted that available hot-wallet balance as free margin. That prevented the deliberately weak position from being liquidated. I updated `scripts/testing/playwright_trading_background_correctness.py` so the liquidation seed account drains excess pc0 hot-wallet balance through an append-only `pc0 -> burn` wallet transaction instead of mutating balances directly.

I also added a short retry around the probe login navigation after one Playwright-only `ERR_NETWORK_CHANGED`. The server stayed up and `curl` returned `HTTP 200` in `0.018s`, so this was treated as a local browser/network transient rather than a server failure.

## Validation

- `python3 -m py_compile scripts/testing/playwright_trading_background_correctness.py`: passed.
- `scripts/testing/playwright_trading_background_correctness.py` against `:5000`: passed.
  - checks: `58`
  - failures: `0`
  - trigger mode: `auto`
  - settings restored after probe: `true`
  - artifacts:
    - `/tmp/hackme_web_qa_5000_trading_background_correctness_1558/trading_background_correctness.json`
    - `/tmp/hackme_web_qa_5000_trading_background_correctness_1558/trading_background_correctness.md`

Trading coverage that passed:

- governed Treasury grants into pc0 official hot wallets
- spot market buy with stop-loss and take-profit
- limit order matching by background worker
- margin open, interest accrual, take-profit, liquidation
- workflow/conditional bot
- DCA bot
- grid bot
- root background job UI/API
- concurrent order stress burst
- `trading verify_state`
- `PointsChain verify`
- non-negative wallet/frozen/spot lock checks

## Subtitle Check

Final Playwright subtitle check on the large shared video passed:

- URL: `https://127.0.0.1:51475/shared/videos/cH-WHf4PoOWr4sKdlVYNLF7vNZk4_RumLz3-Gl-3dec`
- player tag: `VIDEO`
- HLS source: loaded
- subtitle track: attached
- track label: `JPSC`
- srclang: `chi`
- text track mode: `showing`
- cue count: `45,800`
- cue samples include Chinese and Japanese subtitle lines
- subtitle time-shift controls are visible

Artifacts:

- `/tmp/hackme_web_real_hls_20260526_encrypted/shared_video_subtitle_frontend_check_final_1559.json`
- `/tmp/hackme_web_real_hls_20260526_encrypted/shared_video_subtitle_frontend_check_final_1559.png`

## Servers Left Running

- `:5000`: master PID `1279448`, workers `1279506`, `1279507`, `1279526`, `1279527`
- `:51475`: master PID `1077386`, workers `1126219`, `1126262`, `1126292`, `1126310`

