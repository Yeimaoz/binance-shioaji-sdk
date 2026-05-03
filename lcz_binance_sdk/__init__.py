"""
lcz-binance-sdk — Async Python SDK for Binance Futures.

Mirrors shioaji SDK shape (sj.Contracts.Futures / sj.Order / etc) for use by
lcz-sentinel project.

v0.0.1: bootstrap from lcz-sentinel PR #421 _internal/ extraction.
        Public API (BinanceClient, Order, Contracts, ...) coming in v0.1.x.
"""

__version__ = "0.0.1"

from lcz_binance_sdk._internal import (
    BinanceRestClient,
    BinanceWSManager,
    ExecutionReport,
    sign_request,
    _TokenBucket,
)

__all__ = [
    "BinanceRestClient",
    "BinanceWSManager",
    "ExecutionReport",
    "sign_request",
    "_TokenBucket",
    "__version__",
]
