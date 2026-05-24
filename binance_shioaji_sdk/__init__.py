"""
binance-shioaji-sdk — Async Python SDK for Binance Futures.

Mirrors shioaji SDK shape (sj.Contracts.Futures / sj.Order / etc) for use by
parent project.

Public API:
    from binance_shioaji_sdk import Binance
    api = Binance(testnet=False)
    await api.login(api_key, secret_key)
    contract = api.Contracts.Perp["BTCUSDT"]
    order = api.Order(price=50000, quantity=1, action="long", price_type="LMT")
    resp = await api.place_order(contract, order)
    await api.quote.subscribe(contract, "tick", on_tick)
    fr = await api.market_info.funding_rate("BTCUSDT")
    await api.logout()
"""

__version__ = "0.3.0"

from binance_shioaji_sdk._internal.types import BinanceAuthError, ExecutionReport
from binance_shioaji_sdk.account import BinanceAccount
from binance_shioaji_sdk.client import Binance
from binance_shioaji_sdk.contracts import BinanceContract, Contracts
from binance_shioaji_sdk.market_info import MarketInfo
from binance_shioaji_sdk.order import Order, OrderResponse
from binance_shioaji_sdk.quote import Quote

__all__ = [
    "BinanceAuthError",
    "Binance",
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
