# binance-shioaji-sdk

[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)

Async Python SDK for Binance USDM-M Futures, **mirroring the [shioaji](https://github.com/Sinopac-Innovation/Shioaji) SDK API shape**.

If you already trade 台股期貨 via shioaji (永豐金), this gives you Binance crypto with the **exact same API surface** — same `Contracts.Perp["BTCUSDT"]`, same `Order(action="long")`, same `place_order()`. Switch contracts, keep your strategy code.

## Why this vs `python-binance` / `binance-connector`?

| | python-binance | binance-connector | **binance-shioaji-sdk** |
|---|---|---|---|
| API shape | Binance-native | Binance-native | **shioaji-mirrored** |
| Async | partial | sync-only | **async-first** |
| TW quant familiar | ❌ | ❌ | **✅** |
| Code reuse with shioaji strategies | ❌ | ❌ | **✅** |

Pick this if you have shioaji muscle memory and want zero-friction crypto execution.

## Install

```bash
pip install git+https://github.com/Yeimaoz/binance-shioaji-sdk.git@v0.4.0
```

## Quickstart

```python
import asyncio
from binance_shioaji_sdk import Binance

async def main():
    api = Binance(testnet=True)
    await api.login(api_key="...", secret_key="...")

    # Identical to shioaji's api.Contracts.Futures[...] pattern
    contract = api.Contracts.Perp["BTCUSDT"]

    # Same Order construction
    order = api.Order(price=50000, quantity=1, action="long", price_type="LMT")
    trade = await api.place_order(contract, order)   # → BinanceTrade composite
    print(f"order_id: {trade.status.id}")              # mirrors sj.Trade.status.id
    print(f"status:   {trade.status.status}")          # BinanceOrderStatusEnum.Submitted

    # NEW in v0.4.0: margin breakdown (mirror sj.margin())
    account = api.futures_account
    mg = await api.margin(account)
    print(f"available_margin: {mg.available_margin}")

asyncio.run(main())
```

## v0.4.0 Migration (breaking)

- `account_balance()` returns `BinanceAccountBalance` (was `dict`)
- `list_positions()` returns `list[BinanceFuturePosition]` (was `list[dict]`)
- `place_order()` returns `BinanceTrade` composite (was `OrderResponse` — alias kept one release with `DeprecationWarning` via `__init__.py.__getattr__`)
- `funding_rate / funding_rate_history / open_interest` return typed dataclasses (were `dict`)
- All methods raise typed exceptions on REST failure (no silent zero-filled returns or `[]`); new hierarchy `BinanceSDKError → {BinanceMarketDataError, BinanceAccountError, BinanceAuthError}`
- NEW `margin(account) -> BinanceMargin` method (mirror `sj.margin()`)
- `ExecutionReport` renamed `BinanceFillReport` (alias kept one release)
- Order id moves from `trade.order.id` style to `trade.status.id` (mirrors shioaji exactly)
- **`open_interest().timestamp` and `funding_rate_history[i].funding_time` type changed from `int` (epoch ms) to `str` (ISO 8601 UTC)** — downstream code doing `int(t)` must migrate to `datetime.fromisoformat(t)`
- `BinanceAuthError` reparented from bare `Exception` to `BinanceSDKError` subclass (unified `except BinanceSDKError` catches all SDK errors)

## Design philosophy

This SDK exists so that one strategy file can work across **TW futures (via shioaji)** and **Binance perps (via this lib)** without rewriting order / contract / quote glue code. The internal Binance REST + WebSocket implementation is hidden behind a shioaji-shaped facade.

## Status

`v0.2.x` — Working for testnet + mainnet futures. Login, contracts, market info, quotes, orders, account, async WS streaming.

Not yet implemented (open to PRs):
- Spot trading (futures-first for now)
- Sub-account / portfolio margin
- Options

## Contributing

Issues + PRs welcome. The API contract is **shioaji parity**: if shioaji has `api.foo(...)`, this should provide `bn.foo(...)` with semantically equivalent behaviour where it makes sense for crypto futures.

## License

Apache-2.0
