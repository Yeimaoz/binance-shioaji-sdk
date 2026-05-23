"""
binance_shioaji_sdk/market_info.py - MarketInfo namespace (crypto-only)
===================================================================

Mirrors an upstream shioaji-style broker adapter's `get_funding_rate` /
`get_funding_rate_history` / `get_open_interest` surface, packaged as a
crypto-only namespace (shioaji has no equivalent).

A `MarketInfo` instance lives on `BinanceClient.market_info` (wired in by
follow-up PR).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from binance_shioaji_sdk.client import BinanceClient

logger = logging.getLogger(__name__)


def _normalize_symbol(raw: str) -> str:
    sym = raw.upper()
    if not sym.endswith("USDT"):
        sym += "USDT"
    return sym


class MarketInfo:
    """Crypto-specific market data namespace.

    Public surface:
        await funding_rate(symbol) -> dict
        await funding_rate_history(symbol, limit=100, start_time=None, end_time=None) -> list[dict]
        await open_interest(symbol) -> dict
    """

    def __init__(self, client: "BinanceClient") -> None:
        self._client = client

    # ── helpers ──────────────────────────────────────────────────────────

    def _rest(self) -> Any:
        rest = getattr(self._client, "_rest", None) or getattr(
            self._client, "rest", None
        )
        if rest is None:
            raise RuntimeError(
                "[MarketInfo] BinanceClient missing rest client; "
                "call client.connect() first"
            )
        return rest

    # ── funding rate ─────────────────────────────────────────────────────

    async def funding_rate(self, symbol: str) -> dict:
        """Return current funding rate snapshot.

        On API error, returns the raw {error, detail} dict (parity with
        the underlying REST client behavior).
        """
        sym = _normalize_symbol(symbol)
        raw = await self._rest().get(
            "/fapi/v1/premiumIndex",
            params={"symbol": sym},
        )
        if isinstance(raw, dict) and "error" in raw:
            return raw

        try:
            rate = float(raw.get("lastFundingRate", 0) or 0)
            next_ts_ms = int(raw.get("nextFundingTime", 0) or 0)
        except (TypeError, ValueError):
            return {"error": "parse error", "raw": raw}

        next_dt = datetime.fromtimestamp(next_ts_ms / 1000, tz=timezone.utc).isoformat()
        return {
            "symbol": sym,
            "rate": rate,
            "next_settlement": next_dt,
            "annualized": round(rate * 3 * 365, 6),
        }

    async def funding_rate_history(
        self,
        symbol: str,
        limit: int = 100,
        start_time: int | None = None,
        end_time: int | None = None,
    ) -> list[dict]:
        """Return historical funding rate entries (oldest first).

        Args:
            symbol     : 'BTCUSDT' or 'BTC' (auto-suffixed)
            limit      : 1..1000 (Binance hard cap)
            start_time : Unix ms inclusive (optional)
            end_time   : Unix ms inclusive (optional)

        Returns []  on error (warning logged) or non-list response.
        """
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
            logger.warning("[MarketInfo] funding_rate_history failed: %s", raw)
            return []
        if not isinstance(raw, list):
            return []

        out: list[dict] = []
        for entry in raw:
            try:
                mark_raw = entry.get("markPrice", "0") or "0"
                out.append({
                    "symbol": entry.get("symbol", sym),
                    "fundingTime": int(entry["fundingTime"]),
                    "fundingRate": float(entry["fundingRate"]),
                    "markPrice": float(mark_raw),
                })
            except (TypeError, ValueError, KeyError):
                continue
        return out

    # ── open interest ────────────────────────────────────────────────────

    async def open_interest(self, symbol: str) -> dict:
        """Return current open interest snapshot.

        Returns:
            { symbol, open_interest, open_interest_usdt, timestamp }

        On API error returns the raw {error, ...} dict.
        """
        sym = _normalize_symbol(symbol)
        raw = await self._rest().get(
            "/fapi/v1/openInterest",
            params={"symbol": sym},
        )
        if isinstance(raw, dict) and "error" in raw:
            return raw

        try:
            oi = float(raw.get("openInterest", 0) or 0)
            ts = int(raw.get("time", 0) or 0)
        except (TypeError, ValueError):
            return {"error": "parse error", "raw": raw}

        # Best-effort USDT notional via mark price (failure does not block)
        oi_usdt = 0.0
        try:
            price_raw = await self._rest().get(
                "/fapi/v1/premiumIndex", params={"symbol": sym}
            )
            if isinstance(price_raw, dict) and "markPrice" in price_raw:
                oi_usdt = round(oi * float(price_raw["markPrice"]), 2)
        except Exception:
            pass

        return {
            "symbol": sym,
            "open_interest": oi,
            "open_interest_usdt": oi_usdt,
            "timestamp": ts,
        }


__all__ = ["MarketInfo"]
