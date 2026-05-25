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
    """BinanceFillReport must be a frozen dataclass."""
    from binance_shioaji_sdk.fill_report import BinanceFillReport
    import dataclasses

    assert dataclasses.is_dataclass(BinanceFillReport), "BinanceFillReport must be a dataclass"
    params = BinanceFillReport.__dataclass_params__
    assert params.frozen, "BinanceFillReport must be frozen"


def test_class_docstring_mentions_vocabulary_exemption():
    """Class docstring must mention H-1 vocabulary exemption per design §3.7."""
    from binance_shioaji_sdk.fill_report import BinanceFillReport

    doc = BinanceFillReport.__doc__ or ""
    assert "H-1" in doc or "§3.7" in doc or "vocabulary exemption" in doc, (
        "Class docstring must reference H-1 vocabulary exemption or §3.7"
    )
