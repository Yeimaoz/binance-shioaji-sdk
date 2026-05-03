"""
lcz-binance-sdk — Async Python SDK for Binance Futures.

Mirrors shioaji SDK shape (sj.Contracts.Futures / sj.Order / etc) for use by
lcz-sentinel project.

Public API:
    from lcz_binance_sdk import BinanceClient
    bn = BinanceClient(testnet=False)
    await bn.login(api_key, secret_key)
    contract = bn.Contracts.Perp["BTCUSDT"]
    order = bn.Order(price=50000, quantity=1, action="long", price_type="LMT")
    resp = await bn.place_order(contract, order)
    await bn.quote.subscribe(contract, "tick", on_tick)
    fr = await bn.market_info.funding_rate("BTCUSDT")
    await bn.logout()
"""

__version__ = "0.1.0"

from lcz_binance_sdk._internal.types import ExecutionReport
from lcz_binance_sdk.account import BinanceAccount
from lcz_binance_sdk.client import BinanceClient
from lcz_binance_sdk.contracts import BinanceContract, Contracts
from lcz_binance_sdk.market_info import MarketInfo
from lcz_binance_sdk.order import Order, OrderResponse
from lcz_binance_sdk.quote import Quote

__all__ = [
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
