#!/usr/bin/env python3
"""Bridge BTC_trade runtime trade events into hackme_web simulated spot orders.

This script lives in hackme_web so the integration does not depend on a helper
file inside the external BTC_trade project. BTC_trade remains an optional data
source: configure its project path, then run this script after BTC_trade updates
its runtime files.
"""

import argparse
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.btc_trade_bridge import BtcTradeBridge, btc_trade_status


def _default_btc_trade_dir():
    return os.environ.get("BTC_TRADE_DIR") or os.environ.get("HACKME_BTC_TRADE_DIR") or ""


def main():
    parser = argparse.ArgumentParser(description="BTC_trade -> hackme_web spot trading bridge")
    parser.add_argument("--btc-trade-dir", default=_default_btc_trade_dir(), help="BTC_trade project root")
    parser.add_argument("--hackme-dir", default=str(ROOT), help="hackme_web project root")
    parser.add_argument("--bridge-username", default=os.environ.get("BTC_TRADE_BRIDGE_USERNAME", "btc_bridge"))
    parser.add_argument("--market-symbol", default=os.environ.get("BTC_TRADE_BRIDGE_MARKET", "BTC/USDT"))
    parser.add_argument("--quantity-scale", type=float, default=float(os.environ.get("BTC_TRADE_BRIDGE_QUANTITY_SCALE", "1.0")))
    parser.add_argument("--min-btc-quantity", type=float, default=float(os.environ.get("BTC_TRADE_BRIDGE_MIN_BTC", "0.000001")))
    parser.add_argument("--status", action="store_true", help="print BTC_trade signal status and exit")
    parser.add_argument("--dry-run", action="store_true", help="read pending trade events without placing orders")
    args = parser.parse_args()

    if args.status:
        print(json.dumps(btc_trade_status(args.btc_trade_dir), ensure_ascii=False, indent=2))
        return 0

    bridge = BtcTradeBridge(
        hackme_dir=args.hackme_dir,
        btc_trade_dir=args.btc_trade_dir,
        bridge_username=args.bridge_username,
        market_symbol=args.market_symbol,
        quantity_scale=args.quantity_scale,
        min_btc_quantity=args.min_btc_quantity,
    )
    result = bridge.run(dry_run=args.dry_run)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
