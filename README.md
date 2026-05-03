# lcz-binance-sdk

Async Python SDK for Binance Futures, mirroring shioaji SDK shape.

> **Status**: Early stage (v0.0.x). Internal use for lcz-sentinel project.

## Install

```bash
# Editable install during dev:
pip install -e /path/to/lcz-binance-sdk

# Git URL pin (for stable use):
pip install git+https://github.com/Yeimaoz/lcz-binance-sdk.git@v0.1.0
```

## Quick Start

```python
from lcz_binance_sdk import BinanceClient

bn = BinanceClient(testnet=True)
await bn.login(api_key="...", secret_key="...")

contract = bn.Contracts.Perp["BTCUSDT"]
order = bn.Order(price=50000, quantity=1, action="long", price_type="LMT")
resp = await bn.place_order(contract, order)
```

## Design philosophy

Mirrors shioaji SDK API shape (sj.Contracts.Futures.X / sj.place_order / sj.Order / etc) so lcz-sentinel can use uniform adapter pattern across vendors.

See `python/docs/standards/binance_sdk_design.md` in lcz-sentinel for full design study.

## License

Apache-2.0
