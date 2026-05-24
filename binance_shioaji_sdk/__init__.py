"""
binance-shioaji-sdk — Async Python SDK for Binance Futures.

Mirrors shioaji SDK shape (sj.Contracts.Futures / sj.Order / etc) for use by
parent project.

Public API:
    from binance_shioaji_sdk import BinanceClient
    bn = BinanceClient(testnet=False)
    await bn.login(api_key, secret_key)
    contract = bn.Contracts.Perp["BTCUSDT"]
    order = bn.Order(price=50000, quantity=1, action="long", price_type="LMT")
    resp = await bn.place_order(contract, order)
    await bn.quote.subscribe(contract, "tick", on_tick)
    fr = await bn.market_info.funding_rate("BTCUSDT")
    await bn.logout()
"""

__version__ = "0.2.1"

from binance_shioaji_sdk._internal.types import BinanceAuthError, ExecutionReport
from binance_shioaji_sdk.account import BinanceAccount
from binance_shioaji_sdk.client import BinanceClient
from binance_shioaji_sdk.contracts import BinanceContract, Contracts
from binance_shioaji_sdk.market_info import MarketInfo
from binance_shioaji_sdk.order import Order, OrderResponse
from binance_shioaji_sdk.quote import Quote

__all__ = [
    "BinanceAuthError",
    "BinanceClient",
    "BinanceAccount",
    "BinanceContract",
    "Contracts",
    "Order",
    "OrderResponse",
    "Quote",
    "MarketInfo",
    "ExecutionReport",
    "__version__",
]
