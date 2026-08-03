"""
binance_shioaji_sdk/contracts.py — Binance contract specifications
==============================================================

Mirrors shioaji `sj.Contracts.Futures.<key>` dot-access shape:
  bn.Contracts.Perp["BTCUSDT"] -> BinanceContract

v0.1: hardcoded registry of 8 USDM perpetuals
      (AVAXUSDT / BNBUSDT / BTCUSDT / DOGEUSDT / ETHUSDT / LINKUSDT / SOLUSDT / XRPUSDT).
v0.2: dynamic /fapi/v1/exchangeInfo refresh on login — all 500+ USDM perps available.
      Call ``await bn.Contracts.refresh()`` after ``bn.login()`` to populate the registry.

數值來源：Binance USDM exchangeInfo（截至 2026-05）。Spot 留 v0.3。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterator

if TYPE_CHECKING:
    from binance_shioaji_sdk.client import Binance

logger = logging.getLogger(__name__)


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
# Hardcoded seed registry (v0.1 — guaranteed offline)
# ---------------------------------------------------------------------------

# Keyed by symbol; maps to BinanceContract.
# tick_size / step_size / min_notional from Binance USDM exchangeInfo (2026-05).
# This is the SEED — runtime registries copy it on init so refresh() can add
# more without mutating the module-level constant.
_PERP_SEED: dict[str, BinanceContract] = {
    "AVAXUSDT": BinanceContract(
        symbol="AVAXUSDT", market_type="perp",
        tick_size=0.001, step_size=1.0, min_notional=5.0, leverage_max=50,
    ),
    "BNBUSDT": BinanceContract(
        symbol="BNBUSDT", market_type="perp",
        tick_size=0.01, step_size=0.01, min_notional=5.0, leverage_max=75,
    ),
    "BTCUSDT": BinanceContract(
        symbol="BTCUSDT", market_type="perp",
        tick_size=0.1, step_size=0.001, min_notional=5.0, leverage_max=125,
    ),
    "DOGEUSDT": BinanceContract(
        symbol="DOGEUSDT", market_type="perp",
        tick_size=0.00001, step_size=1.0, min_notional=5.0, leverage_max=25,
    ),
    "ETHUSDT": BinanceContract(
        symbol="ETHUSDT", market_type="perp",
        tick_size=0.01, step_size=0.001, min_notional=5.0, leverage_max=100,
    ),
    "LINKUSDT": BinanceContract(
        symbol="LINKUSDT", market_type="perp",
        tick_size=0.001, step_size=0.01, min_notional=20.0, leverage_max=50,
    ),
    "SOLUSDT": BinanceContract(
        symbol="SOLUSDT", market_type="perp",
        tick_size=0.001, step_size=1.0, min_notional=5.0, leverage_max=50,
    ),
    "XRPUSDT": BinanceContract(
        symbol="XRPUSDT", market_type="perp",
        tick_size=0.0001, step_size=1.0, min_notional=5.0, leverage_max=75,
    ),
}


# ---------------------------------------------------------------------------
# Namespace classes
# ---------------------------------------------------------------------------


class _ContractsNamespace:
    """Dict-like namespace for one market_type (e.g. Perp).

    Seed symbols (v0.1) are always available.  Call ``refresh_from_exchange()``
    once after login to discover all remaining Binance perpetuals.
    """

    def __init__(self, client: "Binance", market_type: str) -> None:
        self._client = client
        self._market_type = market_type
        if market_type == "perp":
            self._registry: dict[str, BinanceContract] = dict(_PERP_SEED)
        else:
            raise ValueError(
                f"[Contracts] market_type {market_type!r} not supported; "
                f"only 'perp' is available."
            )
        self._refreshed = False

    async def refresh_from_exchange(self) -> int:
        """Discover all trading USDM perpetuals from Binance exchangeInfo.

        Called once after login. Only *adds* symbols not already in the
        registry (never overwrites the v0.1 seed).  Returns the number of
        new symbols added.

        Leverage max defaults to 25x (conservative) because exchangeInfo
        doesn't include it — callers that need exact leverage should fetch
        ``/fapi/v1/leverageBracket`` separately.
        """
        if self._refreshed:
            return 0
        self._refreshed = True

        if self._market_type != "perp":
            return 0

        try:
            rest = self._client._require_rest()
            data = await rest.get("/fapi/v1/exchangeInfo")
        except Exception as exc:
            logger.warning(
                "[Contracts] exchangeInfo refresh failed (seed only): %s", exc
            )
            return 0

        if not isinstance(data, dict) or "symbols" not in data:
            logger.warning("[Contracts] exchangeInfo returned unexpected shape")
            return 0

        added = 0
        for s in data["symbols"]:
            if s.get("contractType") != "PERPETUAL":
                continue
            if s.get("status") != "TRADING":
                continue
            sym = s["symbol"]
            if sym in self._registry:
                continue

            # Parse filters
            tick_size = 0.01
            step_size = 1.0
            min_notional = 5.0
            for f in s.get("filters", []):
                ft = f.get("filterType", "")
                if ft == "PRICE_FILTER":
                    tick_size = float(f.get("tickSize", tick_size))
                elif ft == "LOT_SIZE":
                    step_size = float(f.get("stepSize", step_size))
                elif ft == "MIN_NOTIONAL":
                    min_notional = float(f.get("notional", min_notional))

            contract = BinanceContract(
                symbol=sym,
                market_type="perp",
                tick_size=tick_size,
                step_size=step_size,
                min_notional=min_notional,
                leverage_max=25,  # conservative default
            )
            self._registry[sym] = contract
            added += 1

        logger.info(
            "[Contracts] exchangeInfo refresh: +%d symbols (total=%d)",
            added, len(self._registry),
        )
        return added

    def __getitem__(self, symbol: str) -> BinanceContract:
        key = symbol.upper() if symbol.isascii() else symbol
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
        key = symbol.upper() if symbol.isascii() else symbol
        return key in self._registry

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

    Spot lookup arrives in v0.3.
    """

    def __init__(self, client: "Binance") -> None:
        self.Perp = _ContractsNamespace(client, "perp")

    async def refresh(self) -> int:
        """Refresh all market-types from exchangeInfo.  Call once after login."""
        return await self.Perp.refresh_from_exchange()
