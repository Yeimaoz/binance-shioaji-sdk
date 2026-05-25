"""v0.4.0 BinanceAccountBalance + BinanceMargin tests."""
from __future__ import annotations

import dataclasses
import pytest


def test_account_balance_is_frozen_dataclass():
    from binance_shioaji_sdk.balance import BinanceAccountBalance
    b = BinanceAccountBalance(acc_balance=1000.0, date="2026-05-25",
                               errmsg="", status="200")
    with pytest.raises(Exception):
        b.acc_balance = 999.0  # type: ignore[misc]


def test_account_balance_field_names_mirror_shioaji():
    """Per design §3.1: acc_balance/date/errmsg/status (4 fields)."""
    from binance_shioaji_sdk.balance import BinanceAccountBalance
    fields = {f.name for f in dataclasses.fields(BinanceAccountBalance)}
    assert fields == {"acc_balance", "date", "errmsg", "status"}


def test_margin_field_names_subset_of_shioaji():
    """Per design §3.2: 8 fields, all subset of sj.Margin."""
    from binance_shioaji_sdk.balance import BinanceMargin
    fields = {f.name for f in dataclasses.fields(BinanceMargin)}
    expected = {"available_margin", "initial_margin", "maintenance_margin",
                "equity", "equity_amount", "today_balance", "yesterday_balance",
                "status"}
    assert fields == expected


def test_margin_is_frozen():
    from binance_shioaji_sdk.balance import BinanceMargin
    m = BinanceMargin(available_margin=500.0, initial_margin=500.0,
                       maintenance_margin=100.0, equity=1000.0,
                       equity_amount=1000.0, today_balance=1000.0,
                       yesterday_balance=0.0, status="200")
    with pytest.raises(Exception):
        m.equity = 999.0  # type: ignore[misc]
