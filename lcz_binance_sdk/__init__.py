"""
lcz-binance-sdk — Async Python SDK for Binance Futures.

Mirrors shioaji SDK shape (sj.Contracts.Futures / sj.Order / etc) for use by
lcz-sentinel project.

v0.0.1: bootstrap from lcz-sentinel PR #421 _internal/ extraction.
v0.1.0: half public API — BinanceClient + Contracts + BinanceAccount.
        Order / Quote / MarketInfo arrive in companion PR.
"""

__version__ = "0.1.0"

from lcz_binance_sdk._internal import (
    BinanceRestClient,
    BinanceWSManager,
    ExecutionReport,
    sign_request,
    _TokenBucket,
)
from lcz_binance_sdk.account import BinanceAccount
from lcz_binance_sdk.client import BinanceClient
from lcz_binance_sdk.contracts import BinanceContract, Contracts

__all__ = [
    "BinanceClient",
    "BinanceAccount",
    "BinanceContract",
    "Contracts",
    "BinanceRestClient",
    "BinanceWSManager",
    "ExecutionReport",
    "sign_request",
    "_TokenBucket",
    "__version__",
]
