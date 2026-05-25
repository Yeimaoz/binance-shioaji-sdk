"""v0.4.0 BinanceFuturePosition tests."""
from __future__ import annotations

import dataclasses
from decimal import Decimal


def test_position_field_names_mirror_shioaji():
    """Per design §3.3: code/direction/id/last_price/pnl/price/quantity (7 fields)."""
    from binance_shioaji_sdk.position import BinanceFuturePosition
    fields = {f.name for f in dataclasses.fields(BinanceFuturePosition)}
    expected = {"code", "direction", "id", "last_price", "pnl", "price", "quantity"}
    assert fields == expected


def test_position_quantity_is_decimal_not_int():
    """Per design §3.3 + H1 reconciliation: Binance allows fractional positions
    (0.001 BTC), so quantity is Decimal not int. Diverges from shioaji."""
    from binance_shioaji_sdk.position import BinanceFuturePosition
    fields = {f.name: f.type for f in dataclasses.fields(BinanceFuturePosition)}
    # Allow either "Decimal" or the actual Decimal class
    qty_type = str(fields["quantity"])
    assert "Decimal" in qty_type, f"expected Decimal, got {qty_type}"


def test_position_construction():
    from binance_shioaji_sdk.position import BinanceFuturePosition
    p = BinanceFuturePosition(
        code="BTCUSDT", direction="Buy", id="BTCUSDT_BOTH",
        last_price=50000.0, pnl=100.0, price=49000.0,
        quantity=Decimal("0.5"),
    )
    assert p.code == "BTCUSDT"
    assert p.quantity == Decimal("0.5")
