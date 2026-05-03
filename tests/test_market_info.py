"""Tests for lcz_binance_sdk.market_info.MarketInfo."""
from __future__ import annotations

from typing import Any

import pytest


class _FakeRest:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self._responses: dict[tuple[str, str], list[Any]] = {}

    def queue(self, method: str, path: str, *responses: Any) -> None:
        self._responses.setdefault((method.upper(), path), []).extend(responses)

    async def get(self, path: str, params: dict | None = None, signed: bool = False, weight: int = 1) -> Any:
        self.calls.append({"method": "GET", "path": path, "params": params})
        return self._responses[("GET", path)].pop(0)


class _FakeClient:
    def __init__(self) -> None:
        self._rest = _FakeRest()
        self._base_url = "https://fapi.binance.com"


@pytest.mark.asyncio
async def test_funding_rate_happy_path() -> None:
    from lcz_binance_sdk.market_info import MarketInfo

    client = _FakeClient()
    client._rest.queue(
        "GET",
        "/fapi/v1/premiumIndex",
        {"lastFundingRate": "0.0001", "nextFundingTime": 1700000000000},
    )
    mi = MarketInfo(client)
    out = await mi.funding_rate("BTC")

    assert out["symbol"] == "BTCUSDT"
    assert out["rate"] == 0.0001
    assert out["annualized"] == round(0.0001 * 3 * 365, 6)
    assert "next_settlement" in out and out["next_settlement"].endswith("+00:00")
    assert client._rest.calls[0]["params"] == {"symbol": "BTCUSDT"}


@pytest.mark.asyncio
async def test_open_interest_happy_path() -> None:
    from lcz_binance_sdk.market_info import MarketInfo

    client = _FakeClient()
    # First call: openInterest. Second: premiumIndex (for USDT notional)
    client._rest.queue(
        "GET",
        "/fapi/v1/openInterest",
        {"openInterest": "12345.5", "time": 1700000000123},
    )
    client._rest.queue("GET", "/fapi/v1/premiumIndex", {"markPrice": "100"})

    mi = MarketInfo(client)
    out = await mi.open_interest("BTCUSDT")

    assert out["symbol"] == "BTCUSDT"
    assert out["open_interest"] == 12345.5
    assert out["open_interest_usdt"] == round(12345.5 * 100, 2)
    assert out["timestamp"] == 1700000000123


@pytest.mark.asyncio
async def test_funding_rate_history_with_bounds() -> None:
    from lcz_binance_sdk.market_info import MarketInfo

    client = _FakeClient()
    client._rest.queue(
        "GET",
        "/fapi/v1/fundingRate",
        [
            {"symbol": "BTCUSDT", "fundingTime": 1700000000000, "fundingRate": "0.0001", "markPrice": "50000"},
            {"symbol": "BTCUSDT", "fundingTime": 1700001000000, "fundingRate": "0.00012", "markPrice": ""},
            # malformed entry should be skipped
            {"symbol": "BTCUSDT"},
        ],
    )
    mi = MarketInfo(client)
    out = await mi.funding_rate_history(
        "BTC", limit=2000, start_time=1, end_time=2,
    )

    assert len(out) == 2
    assert out[0]["fundingRate"] == 0.0001
    assert out[1]["markPrice"] == 0.0  # empty string falls back to 0
    sent = client._rest.calls[0]["params"]
    assert sent["limit"] == 1000  # clamped
    assert sent["startTime"] == 1
    assert sent["endTime"] == 2


@pytest.mark.asyncio
async def test_funding_rate_history_returns_empty_on_error() -> None:
    from lcz_binance_sdk.market_info import MarketInfo

    client = _FakeClient()
    client._rest.queue("GET", "/fapi/v1/fundingRate", {"error": "HTTP 500"})

    mi = MarketInfo(client)
    out = await mi.funding_rate_history("BTC")
    assert out == []
