"""v0.4.0 Binance-only market data — shioaji coding style (§3.7).

Funding rate / open interest don't exist in shioaji (TW futures don't have
funding). Per design two-axis principle: keep the feature, mimic shioaji
coding style (frozen dataclass, attr access, short shioaji-vocab field names,
ISO datetime strings).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BinanceFundingRate:
    """Current funding rate snapshot. Shioaji-styled fields (code not symbol)."""
    code: str                   # e.g. "BTCUSDT"
    rate: float                 # current period funding rate (0.0001 = 0.01%)
    next_funding_time: str      # ISO 8601 UTC


@dataclass(frozen=True)
class BinanceFundingRateEntry:
    """One historical funding rate entry — returned in list."""
    code: str
    rate: float
    funding_time: str           # ISO 8601 UTC (when this rate applied)
    mark_price: float           # mark price at funding (Binance returns; useful for analysis)


@dataclass(frozen=True)
class BinanceOpenInterest:
    """Open interest snapshot."""
    code: str
    open_interest: float        # contracts (BTC for BTCUSDT etc)
    open_interest_usdt: float   # USDT notional value
    timestamp: str              # ISO 8601 UTC
