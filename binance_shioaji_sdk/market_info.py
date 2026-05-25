"""
binance_shioaji_sdk/market_info.py - MarketInfo namespace (crypto-only)
===================================================================

Mirrors an upstream shioaji-style broker adapter's `get_funding_rate` /
`get_funding_rate_history` / `get_open_interest` surface, packaged as a
crypto-only namespace (shioaji has no equivalent).

A `MarketInfo` instance lives on `Binance.market_info` (wired in by
follow-up PR).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from binance_shioaji_sdk.client import Binance

logger = logging.getLogger(__name__)


def _normalize_symbol(raw: str) -> str:
    sym = raw.upper()
    if not sym.endswith("USDT"):
        sym += "USDT"
    return sym


class MarketInfo:
    """Crypto-specific market data namespace.

    Public surface (v0.4.0):
        await funding_rate(symbol) -> BinanceFundingRate
        await funding_rate_history(symbol, limit=100, start_time=None, end_time=None) -> list[BinanceFundingRateEntry]
        await open_interest(symbol) -> BinanceOpenInterest

    All three raise BinanceMarketDataError on REST failure (v0.4.0
    behavioral break — v0.3.x silently returned dict/[]).
    """

    def __init__(self, client: "Binance") -> None:
        self._client = client

    # ── helpers ──────────────────────────────────────────────────────────

    def _rest(self) -> Any:
        rest = getattr(self._client, "_rest", None) or getattr(
            self._client, "rest", None
        )
        if rest is None:
            raise RuntimeError(
                "[MarketInfo] Binance missing rest client; "
                "call client.connect() first"
            )
        return rest

    # ── funding rate ─────────────────────────────────────────────────────

    async def funding_rate(self, symbol: str) -> "BinanceFundingRate":
        """Current funding rate snapshot. v0.4.0: returns BinanceFundingRate.

        Raises BinanceMarketDataError on REST failure or parse error.
        Note: `annualized` field removed in v0.4.0 (Binance API doesn't return it;
        was computed in v0.3.x; consumer can compute rate * 3 * 365 if needed).
        """
        from binance_shioaji_sdk.funding import BinanceFundingRate
        from binance_shioaji_sdk.exceptions import BinanceMarketDataError
        sym = _normalize_symbol(symbol)
        raw = await self._rest().get(
            "/fapi/v1/premiumIndex",
            params={"symbol": sym},
        )
        if isinstance(raw, dict) and "error" in raw:
            raise BinanceMarketDataError(f"funding_rate({sym}) REST failed: {raw}")
        try:
            rate = float(raw.get("lastFundingRate", 0) or 0)
            next_ts_ms = int(raw.get("nextFundingTime", 0) or 0)
        except (TypeError, ValueError) as e:
            raise BinanceMarketDataError(
                f"funding_rate({sym}) parse failed: {raw!r}"
            ) from e
        next_dt = datetime.fromtimestamp(next_ts_ms / 1000, tz=timezone.utc).isoformat()
        return BinanceFundingRate(code=sym, rate=rate, next_funding_time=next_dt)

    async def funding_rate_history(
        self,
        symbol: str,
        limit: int = 100,
        start_time: int | None = None,
        end_time: int | None = None,
    ) -> "list[BinanceFundingRateEntry]":
        """Historical funding rate entries. v0.4.0: returns list[dataclass].

        BEHAVIORAL BREAK: v0.3.x silently returned [] on error; v0.4.0 raises
        BinanceMarketDataError. funding_time type changed from epoch ms int to
        ISO 8601 UTC string.

        Args:
            symbol     : 'BTCUSDT' or 'BTC' (auto-suffixed)
            limit      : 1..1000 (Binance hard cap)
            start_time : Unix ms inclusive (optional)
            end_time   : Unix ms inclusive (optional)
        """
        from binance_shioaji_sdk.funding import BinanceFundingRateEntry
        from binance_shioaji_sdk.exceptions import BinanceMarketDataError
        sym = _normalize_symbol(symbol)
        params: dict[str, Any] = {
            "symbol": sym,
            "limit": min(max(1, limit), 1000),
        }
        if start_time is not None:
            params["startTime"] = start_time
        if end_time is not None:
            params["endTime"] = end_time

        raw = await self._rest().get("/fapi/v1/fundingRate", params=params)

        if isinstance(raw, dict) and "error" in raw:
            raise BinanceMarketDataError(
                f"funding_rate_history({sym}) REST failed: {raw}"
            )
        if not isinstance(raw, list):
            raise BinanceMarketDataError(
                f"funding_rate_history({sym}) unexpected response: {raw!r}"
            )

        out: list[BinanceFundingRateEntry] = []
        for entry in raw:
            try:
                mark_raw = entry.get("markPrice", "0") or "0"
                ts_ms = int(entry["fundingTime"])
                iso = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).isoformat()
                out.append(BinanceFundingRateEntry(
                    code=entry.get("symbol", sym),
                    rate=float(entry["fundingRate"]),
                    funding_time=iso,
                    mark_price=float(mark_raw),
                ))
            except (TypeError, ValueError, KeyError):
                continue
        return out

    # ── open interest ────────────────────────────────────────────────────

    async def open_interest(self, symbol: str) -> "BinanceOpenInterest":
        """Current open interest snapshot. v0.4.0: returns BinanceOpenInterest.

        BEHAVIORAL BREAK: v0.3.x returned {error, ...} dict on REST failure;
        v0.4.0 raises BinanceMarketDataError. timestamp type changed from
        epoch ms int to ISO 8601 UTC string.

        Note: Binance /fapi/v1/openInterest only returns contract qty; this
        method makes a second call to /fapi/v1/premiumIndex for mark price,
        used to compute open_interest_usdt notional. Mark price call failure
        does not block (open_interest_usdt = 0.0 in that case).
        """
        from binance_shioaji_sdk.funding import BinanceOpenInterest
        from binance_shioaji_sdk.exceptions import BinanceMarketDataError
        sym = _normalize_symbol(symbol)
        raw = await self._rest().get(
            "/fapi/v1/openInterest",
            params={"symbol": sym},
        )
        if isinstance(raw, dict) and "error" in raw:
            raise BinanceMarketDataError(f"open_interest({sym}) REST failed: {raw}")

        try:
            oi = float(raw.get("openInterest", 0) or 0)
            ts_ms = int(raw.get("time", 0) or 0)
        except (TypeError, ValueError) as e:
            raise BinanceMarketDataError(
                f"open_interest({sym}) parse failed: {raw!r}"
            ) from e

        # Second call for mark price → USDT notional (failure does not block)
        oi_usdt = 0.0
        try:
            price_raw = await self._rest().get(
                "/fapi/v1/premiumIndex", params={"symbol": sym}
            )
            if isinstance(price_raw, dict) and "markPrice" in price_raw:
                oi_usdt = round(oi * float(price_raw["markPrice"]), 2)
        except Exception:
            pass

        iso = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).isoformat()
        return BinanceOpenInterest(
            code=sym,
            open_interest=oi,
            open_interest_usdt=oi_usdt,
            timestamp=iso,
        )


__all__ = ["MarketInfo"]
