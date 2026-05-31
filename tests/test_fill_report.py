"""
tests/test_fill_report.py — unit tests for binance_shioaji_sdk.fill_report
===========================================================================

Task 5: 3 smoke tests per plan.
  1. Module file exists at expected path.
  2. BinanceFillReport is a frozen dataclass.
  3. Class docstring mentions vocabulary exemption (H-1 / §3.7).
"""
import importlib
import inspect
from pathlib import Path
from dataclasses import fields


def test_module_file_exists():
    """fill_report.py must be present under the package root."""
    pkg_root = Path(__file__).parent.parent / "binance_shioaji_sdk"
    module_path = pkg_root / "fill_report.py"
    assert module_path.exists(), f"Expected {module_path} to exist"


def test_binance_fill_report_is_frozen_dataclass():
    """BinanceFillReport must be a frozen dataclass — declared + runtime check (L-1 + I-3)."""
    from binance_shioaji_sdk.fill_report import BinanceFillReport
    import dataclasses
    import pytest as _pt

    assert dataclasses.is_dataclass(BinanceFillReport), "BinanceFillReport must be a dataclass"
    params = BinanceFillReport.__dataclass_params__
    assert params.frozen, "BinanceFillReport must be frozen"

    # Runtime mutation must raise (post-construction assignment) — I-3 fix
    report = BinanceFillReport(
        order_id="X", symbol="BTCUSDT", status="NEW", side="BUY",
        order_type="LIMIT", qty=1.0, filled_qty=0.0,
        last_filled_price=0.0, avg_price=0.0,
    )
    with _pt.raises(dataclasses.FrozenInstanceError):
        report.status = "FILLED"  # type: ignore[misc]


def test_class_docstring_mentions_vocabulary_exemption():
    """Class docstring must mention H-1 vocabulary exemption per design §3.7."""
    from binance_shioaji_sdk.fill_report import BinanceFillReport

    doc = BinanceFillReport.__doc__ or ""
    assert "H-1" in doc or "§3.7" in doc or "vocabulary exemption" in doc, (
        "Class docstring must reference H-1 vocabulary exemption or §3.7"
    )


def test_fill_report_has_per_fill_fields_with_defaults():
    """v0.5.3: per-fill 欄位 (last_qty/exec_type/trade_id) 有 default — 向下相容。"""
    from binance_shioaji_sdk.fill_report import BinanceFillReport
    r = BinanceFillReport(
        order_id="1", symbol="BTCUSDT", status="FILLED", side="BUY",
        order_type="MARKET", qty=0.001, filled_qty=0.001,
        last_filled_price=65000.0, avg_price=65000.0,
    )
    assert r.last_qty == 0.0
    assert r.exec_type == ""
    assert r.trade_id == ""
    r2 = BinanceFillReport(
        order_id="1", symbol="BTCUSDT", status="PARTIALLY_FILLED", side="BUY",
        order_type="LIMIT", qty=0.001, filled_qty=0.0005,
        last_filled_price=65000.0, avg_price=65000.0,
        last_qty=0.0005, exec_type="TRADE", trade_id="999",
    )
    assert r2.last_qty == 0.0005
    assert r2.exec_type == "TRADE"
    assert r2.trade_id == "999"
