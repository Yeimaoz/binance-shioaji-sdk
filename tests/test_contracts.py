"""Tests for binance_shioaji_sdk.contracts."""
from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from binance_shioaji_sdk import BinanceClient, BinanceContract


def test_perp_lookup_returns_binance_contract() -> None:
    bn = BinanceClient(testnet=True)
    c = bn.Contracts.Perp["BTCUSDT"]
    assert isinstance(c, BinanceContract)
    assert c.symbol == "BTCUSDT"
    assert c.market_type == "perp"
    assert c.currency == "USDT"


def test_perp_unknown_symbol_raises_key_error() -> None:
    bn = BinanceClient(testnet=True)
    with pytest.raises(KeyError):
        _ = bn.Contracts.Perp["FOOUSDT"]


def test_perp_tick_size_positive() -> None:
    bn = BinanceClient(testnet=True)
    for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"):
        c = bn.Contracts.Perp[sym]
        assert c.tick_size > 0
        assert c.step_size > 0
        assert c.min_notional > 0


def test_perp_contains_check() -> None:
    bn = BinanceClient(testnet=True)
    assert "BTCUSDT" in bn.Contracts.Perp
    assert "btcusdt" in bn.Contracts.Perp
    assert "FOOUSDT" not in bn.Contracts.Perp
    assert 12345 not in bn.Contracts.Perp


def test_binance_contract_is_frozen() -> None:
    bn = BinanceClient(testnet=True)
    c = bn.Contracts.Perp["BTCUSDT"]
    with pytest.raises(FrozenInstanceError):
        c.tick_size = 999.0  # type: ignore[misc]
