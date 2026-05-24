"""Tests for binance_shioaji_sdk.account.BinanceAccount."""
from __future__ import annotations

from binance_shioaji_sdk import BinanceAccount, Binance


def test_binance_account_creates_ok() -> None:
    bn = Binance(testnet=True)
    acct = BinanceAccount(client_ref=bn)
    assert acct.client_ref is bn


def test_account_id_is_string() -> None:
    bn = Binance(testnet=True)
    acct = BinanceAccount(client_ref=bn)
    # No api_key yet -> "anon"
    assert acct.account_id == "anon"
    # Once key is set, masked stable hash
    bn.api_key = "test_api_key_abc"
    assert isinstance(acct.account_id, str)
    assert len(acct.account_id) == 8
    assert acct.account_id != "anon"
    # Stable across reads
    assert acct.account_id == acct.account_id


def test_default_account_type_is_futures() -> None:
    bn = Binance(testnet=True)
    acct = BinanceAccount(client_ref=bn)
    assert acct.account_type == "futures"
