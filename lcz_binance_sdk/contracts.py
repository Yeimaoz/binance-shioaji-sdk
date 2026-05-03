"""
lcz_binance_sdk/contracts.py — Binance contract specifications
==============================================================

Mirrors shioaji `sj.Contracts.Futures.<key>` dot-access shape:
  bn.Contracts.Perp["BTCUSDT"] -> BinanceContract

v0.1: hardcoded registry of 5 commonly-used USDM perpetuals
      (BTCUSDT / ETHUSDT / SOLUSDT / BNBUSDT / XRPUSDT).
v0.2: dynamic /fapi/v1/exchangeInfo refresh.

數值來源：lcz-sentinel python/lib/contracts_crypto.py + Binance USDM exchangeInfo
（截至 2026-05）。Spot 留 v0.2。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterator

if TYPE_CHECKING:
    from lcz_binance_sdk.client import BinanceClient


@dataclass(frozen=True)
class BinanceContract:
    """Binance USDM perpetual contract spec (frozen).

    Mirrors shioaji.Contracts.Futures item shape — rich object, not raw spec.

    Attributes
    ----------
    symbol         : Binance symbol (e.g. "BTCUSDT")
    market_type    : "perp" (v0.1 only)
    tick_size      : minimum price increment (USDT)
    step_size      : minimum quantity increment (base asset)
    min_notional   : minimum order notional value (USDT)
    multiplier     : contract multiplier (USDM perp = 1)
    currency       : quote currency (USDT)
    leverage_max   : exchange max leverage cap
    """

    symbol: str
    market_type: str
    tick_size: float
    step_size: float
    min_notional: float
    multiplier: int = 1
    currency: str = "USDT"
    leverage_max: int = 125


# ---------------------------------------------------------------------------
# Hardcoded registry (v0.1)
# ---------------------------------------------------------------------------

# Keyed by market_type; each maps symbol -> BinanceContract.
# tick_size / step_size 對齊 lcz-sentinel/lib/contracts_crypto.py 既有值；
# SOLUSDT / BNBUSDT 取自 Binance USDM exchangeInfo (2026-05)。
_PERP_REGISTRY: dict[str, BinanceContract] = {
    "BTCUSDT": BinanceContract(
        symbol="BTCUSDT",
        market_type="perp",
        tick_size=0.1,
        step_size=0.001,
        min_notional=5.0,
        leverage_max=125,
    ),
    "ETHUSDT": BinanceContract(
        symbol="ETHUSDT",
        market_type="perp",
        tick_size=0.01,
        step_size=0.001,
        min_notional=5.0,
        leverage_max=100,
    ),
    "SOLUSDT": BinanceContract(
        symbol="SOLUSDT",
        market_type="perp",
        tick_size=0.001,
        step_size=1.0,
        min_notional=5.0,
        leverage_max=50,
    ),
    "BNBUSDT": BinanceContract(
        symbol="BNBUSDT",
        market_type="perp",
        tick_size=0.01,
        step_size=0.01,
        min_notional=5.0,
        leverage_max=75,
    ),
    "XRPUSDT": BinanceContract(
        symbol="XRPUSDT",
        market_type="perp",
        tick_size=0.0001,
        step_size=1.0,
        min_notional=5.0,
        leverage_max=75,
    ),
}


# ---------------------------------------------------------------------------
# Namespace classes
# ---------------------------------------------------------------------------


class _ContractsNamespace:
    """Dict-like namespace for one market_type (e.g. Perp)."""

    def __init__(self, client: "BinanceClient", market_type: str) -> None:
        self._client = client
        self._market_type = market_type
        if market_type == "perp":
            self._registry = _PERP_REGISTRY
        else:
            raise ValueError(
                f"[Contracts] market_type {market_type!r} not supported in v0.1; "
                f"only 'perp' is available."
            )

    def __getitem__(self, symbol: str) -> BinanceContract:
        key = symbol.upper()
        if key not in self._registry:
            raise KeyError(
                f"[Contracts.{self._market_type.capitalize()}] "
                f"symbol {symbol!r} not registered. "
                f"Supported: {sorted(self._registry.keys())}"
            )
        return self._registry[key]

    def __contains__(self, symbol: object) -> bool:
        if not isinstance(symbol, str):
            return False
        return symbol.upper() in self._registry

    def __iter__(self) -> Iterator[str]:
        return iter(sorted(self._registry.keys()))

    def __len__(self) -> int:
        return len(self._registry)

    def keys(self) -> list[str]:
        return sorted(self._registry.keys())


class Contracts:
    """Top-level contracts namespace, mirrors shioaji `sj.Contracts`.

    Usage:
        bn.Contracts.Perp["BTCUSDT"]    # -> BinanceContract
        "BTCUSDT" in bn.Contracts.Perp  # -> True

    Spot lookup arrives in v0.2.
    """

    def __init__(self, client: "BinanceClient") -> None:
        self.Perp = _ContractsNamespace(client, "perp")
        # Spot: v0.2
