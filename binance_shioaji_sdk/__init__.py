"""
binance-shioaji-sdk — Async Python SDK for Binance Futures.

Mirrors shioaji SDK shape (sj.Contracts.Futures / sj.Order / sj.Trade /
sj.AccountBalance / sj.Margin / sj.FuturePosition / sj.OrderStatus) for use by
downstream symmetric broker adapters.

Public API:
    from binance_shioaji_sdk import Binance
    api = Binance(testnet=False)
    await api.login(api_key, secret_key)
    contract = api.Contracts.Perp["BTCUSDT"]
    order = api.Order(price=50000, quantity=1, action="long", price_type="LMT")
    trade = await api.place_order(contract, order)   # → BinanceTrade
    print(trade.status.id)                            # broker order id (mirrors sj.Trade.status.id)
    await api.logout()
"""
__version__ = "0.5.0"

# v0.4.0 dataclass returns + exception hierarchy.
from binance_shioaji_sdk.exceptions import (
    BinanceSDKError,
    BinanceMarketDataError,
    BinanceAccountError,
    BinanceAuthError,
)
from binance_shioaji_sdk.balance import BinanceAccountBalance, BinanceMargin
from binance_shioaji_sdk.position import BinanceFuturePosition
from binance_shioaji_sdk.trade import (
    BinanceTrade,
    BinanceTradeStatus,
    BinanceOrderStatusEnum,
)
from binance_shioaji_sdk.fill_report import BinanceFillReport
from binance_shioaji_sdk.funding import (
    BinanceFundingRate,
    BinanceFundingRateEntry,
    BinanceOpenInterest,
)

# Existing v0.3.x exports (unchanged)
from binance_shioaji_sdk.account import BinanceAccount
from binance_shioaji_sdk.client import Binance
from binance_shioaji_sdk.contracts import BinanceContract, Contracts
from binance_shioaji_sdk.market_info import MarketInfo
from binance_shioaji_sdk.order import Order
from binance_shioaji_sdk.quote import Quote

__all__ = [
    "__version__",
    "Binance",
    "BinanceContract",
    "Contracts",
    "BinanceAccount",
    "MarketInfo",
    "Order",
    "Quote",
    # v0.4.0 additions
    "BinanceSDKError",
    "BinanceMarketDataError",
    "BinanceAccountError",
    "BinanceAuthError",
    "BinanceAccountBalance",
    "BinanceMargin",
    "BinanceFuturePosition",
    "BinanceTrade",
    "BinanceTradeStatus",
    "BinanceOrderStatusEnum",
    "BinanceFillReport",
    "BinanceFundingRate",
    "BinanceFundingRateEntry",
    "BinanceOpenInterest",
]

