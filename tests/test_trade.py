"""v0.4.0 BinanceTrade composite + OrderStatusEnum tests."""
from __future__ import annotations

import dataclasses
import pytest


def test_order_status_enum_mirrors_shioaji_member_names():
    from binance_shioaji_sdk.trade import BinanceOrderStatusEnum
    expected = {"Cancelled", "Failed", "Filled", "Inactive",
                "PartFilled", "PendingSubmit", "PreSubmitted", "Submitted"}
    actual = {m.name for m in BinanceOrderStatusEnum}
    assert actual == expected


def test_order_status_enum_values_are_camel_case_strings():
    from binance_shioaji_sdk.trade import BinanceOrderStatusEnum
    assert BinanceOrderStatusEnum.Submitted.value == "Submitted"
    assert BinanceOrderStatusEnum.PartFilled.value == "PartFilled"
    assert BinanceOrderStatusEnum.Filled.value == "Filled"


def test_trade_status_is_frozen_dataclass():
    from binance_shioaji_sdk.trade import BinanceTradeStatus, BinanceOrderStatusEnum
    s = BinanceTradeStatus(
        id="42",
        status=BinanceOrderStatusEnum.Submitted,
        status_code="",
        order_datetime="2026-05-25T12:00:00+00:00",
    )
    with pytest.raises(Exception):  # FrozenInstanceError
        s.id = "43"  # type: ignore[misc]


def test_trade_status_optional_fields_default_to_none_or_zero():
    """cancel_quantity / order_quantity / deal_quantity are Optional[int]
    matching sj.OrderStatusInfo. modified_price defaults 0.0. msg defaults ''."""
    from binance_shioaji_sdk.trade import BinanceTradeStatus, BinanceOrderStatusEnum
    s = BinanceTradeStatus(
        id="x", status=BinanceOrderStatusEnum.Submitted,
        status_code="", order_datetime="2026-05-25T00:00:00+00:00",
    )
    assert s.deal_quantity is None
    assert s.order_quantity is None
    assert s.cancel_quantity is None
    assert s.modified_price == 0.0
    assert s.msg == ""


def test_trade_composite_structure():
    """BinanceTrade has contract / order / status — mirrors sj.Trade."""
    from binance_shioaji_sdk.trade import BinanceTrade
    fields = {f.name for f in dataclasses.fields(BinanceTrade)}
    assert fields == {"contract", "order", "status"}
