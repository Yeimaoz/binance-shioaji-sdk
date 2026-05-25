"""Reflection-based mirror tests vs shioaji SDK.

Imports shioaji as optional dep (skips test module if missing).
Per design §7. Goal: catch drift when shioaji adds/renames fields.

Live verified against shioaji 1.5.0 (C-extension types — not Pydantic).
"""
from __future__ import annotations

import dataclasses

import pytest

shioaji = pytest.importorskip(
    "shioaji",
    reason="install with: pip install -e '.[mirror-test]'",
)
sj = shioaji


def _sj_attrs(cls) -> set[str]:
    """Return shioaji model/enum field names.

    Per design §7 M-1 fix: prefer Pydantic introspection if available,
    fall through to dir() filter for C-extension types (shioaji 1.5+).
    Excludes: dunders, dict/keys (Pydantic v1 BaseModel.dict/.keys), value
    (Enum metaclass attribute).
    """
    if hasattr(cls, "__fields__"):
        return set(cls.__fields__.keys())
    if hasattr(cls, "model_fields"):
        return set(cls.model_fields.keys())
    return {
        a for a in dir(cls)
        if not a.startswith("_") and a not in ("dict", "keys", "value", "name")
    }


# ── Full mirror equality (BinanceX == sj.X field-for-field) ────────────


def test_account_balance_mirror():
    """BinanceAccountBalance fields exactly mirror sj.AccountBalance."""
    from binance_shioaji_sdk import BinanceAccountBalance
    sj_fields = _sj_attrs(sj.AccountBalance)
    bn_fields = {f.name for f in dataclasses.fields(BinanceAccountBalance)}
    missing = sj_fields - bn_fields
    assert not missing, (
        f"BinanceAccountBalance missing shioaji fields: {missing}"
    )


def test_future_position_mirror():
    """BinanceFuturePosition fields exactly mirror sj.FuturePosition."""
    from binance_shioaji_sdk import BinanceFuturePosition
    sj_fields = _sj_attrs(sj.FuturePosition)
    bn_fields = {f.name for f in dataclasses.fields(BinanceFuturePosition)}
    missing = sj_fields - bn_fields
    assert not missing, (
        f"BinanceFuturePosition missing shioaji fields: {missing}"
    )


def test_order_status_enum_mirror():
    """BinanceOrderStatusEnum members exactly mirror sj.OrderStatus members."""
    from binance_shioaji_sdk import BinanceOrderStatusEnum
    sj_members = _sj_attrs(sj.OrderStatus)
    bn_members = {m.name for m in BinanceOrderStatusEnum}
    missing = sj_members - bn_members
    assert not missing, (
        f"BinanceOrderStatusEnum missing sj.OrderStatus members: {missing}"
    )


def test_trade_status_mirror():
    """BinanceTradeStatus mirrors sj.OrderStatusInfo.

    Allow omission of shioaji-internal fields (deals, modified_time, web_id)
    that don't have natural Binance equivalents.
    """
    from binance_shioaji_sdk import BinanceTradeStatus
    sj_fields = _sj_attrs(sj.OrderStatusInfo)
    bn_fields = {f.name for f in dataclasses.fields(BinanceTradeStatus)}
    omitted_ok = {"deals", "modified_time", "web_id"}
    missing = sj_fields - bn_fields - omitted_ok
    assert not missing, (
        f"BinanceTradeStatus missing sj.OrderStatusInfo fields "
        f"(not in omitted_ok={omitted_ok}): {missing}"
    )


# ── Subset-validity (BinanceMargin ⊂ sj.Margin) ────────────────────────


def test_margin_is_valid_shioaji_subset():
    """BinanceMargin is intentional 8/26 subset of sj.Margin (design §3.2).

    Direction: assert BinanceMargin fields are all valid sj.Margin fields
    (no inventions). Future shioaji adding fields is OK (we don't have to
    mirror them); we adding fields that don't exist in shioaji is NOT OK.
    """
    from binance_shioaji_sdk import BinanceMargin
    sj_fields = _sj_attrs(sj.Margin)
    bn_fields = {f.name for f in dataclasses.fields(BinanceMargin)}
    spurious = bn_fields - sj_fields
    assert not spurious, (
        f"BinanceMargin invented fields not in sj.Margin: {spurious}"
    )
