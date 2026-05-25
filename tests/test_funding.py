"""v0.4.0 Binance-only data structures (shioaji coding style mimic — §3.7)."""
from __future__ import annotations

import dataclasses


def test_funding_rate_shape():
    from binance_shioaji_sdk.funding import BinanceFundingRate
    fields = {f.name for f in dataclasses.fields(BinanceFundingRate)}
    # shioaji vocab: code (not symbol), rate (not lastFundingRate), ISO datetime str
    assert fields == {"code", "rate", "next_funding_time"}


def test_funding_rate_entry_shape():
    from binance_shioaji_sdk.funding import BinanceFundingRateEntry
    fields = {f.name for f in dataclasses.fields(BinanceFundingRateEntry)}
    assert fields == {"code", "rate", "funding_time", "mark_price"}


def test_open_interest_shape():
    from binance_shioaji_sdk.funding import BinanceOpenInterest
    fields = {f.name for f in dataclasses.fields(BinanceOpenInterest)}
    assert fields == {"code", "open_interest", "open_interest_usdt", "timestamp"}


def test_funding_rate_uses_code_not_symbol():
    """Naming convention test: §3.7 binance-only mimicry rule —
    must use shioaji vocab `code` not raw Binance `symbol`."""
    from binance_shioaji_sdk.funding import (
        BinanceFundingRate, BinanceFundingRateEntry, BinanceOpenInterest,
    )
    for cls in (BinanceFundingRate, BinanceFundingRateEntry, BinanceOpenInterest):
        names = {f.name for f in dataclasses.fields(cls)}
        assert "symbol" not in names, f"{cls.__name__} uses raw Binance 'symbol'; should be 'code'"
        assert "code" in names, f"{cls.__name__} missing shioaji-style 'code'"
