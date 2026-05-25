"""Tests for binance_shioaji_sdk.market_info.MarketInfo."""
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
        self.calls.append({"method": "GET", "path": path, "params": params, "signed": signed})
        return self._responses[("GET", path)].pop(0)


class _FakeClient:
    def __init__(self) -> None:
        self._rest = _FakeRest()
        self._base_url = "https://fapi.binance.com"


@pytest.mark.asyncio
async def test_funding_rate_happy_path() -> None:
    from binance_shioaji_sdk.market_info import MarketInfo

    client = _FakeClient()
    client._rest.queue(
        "GET",
        "/fapi/v1/premiumIndex",
        {"lastFundingRate": "0.0001", "nextFundingTime": 1700000000000},
    )
    mi = MarketInfo(client)
    out = await mi.funding_rate("BTC")

    # v0.4.0: returns BinanceFundingRate dataclass (was dict). `annualized` removed.
    assert out.code == "BTCUSDT"
    assert out.rate == 0.0001
    assert out.next_funding_time.endswith("+00:00")
    assert client._rest.calls[0]["params"] == {"symbol": "BTCUSDT"}


@pytest.mark.asyncio
async def test_open_interest_happy_path() -> None:
    from binance_shioaji_sdk.market_info import MarketInfo

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

    # v0.4.0: returns BinanceOpenInterest dataclass; timestamp is ISO 8601 str (was int ms)
    assert out.code == "BTCUSDT"
    assert out.open_interest == 12345.5
    assert out.open_interest_usdt == round(12345.5 * 100, 2)
    # timestamp epoch ms 1700000000123 → ISO 8601 UTC
    assert out.timestamp.startswith("2023-11-14") and out.timestamp.endswith("+00:00")


@pytest.mark.asyncio
async def test_funding_rate_history_with_bounds() -> None:
    from binance_shioaji_sdk.market_info import MarketInfo

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

    # v0.4.0: returns list[BinanceFundingRateEntry]; field names rate/mark_price/funding_time (ISO str)
    assert len(out) == 2
    assert out[0].rate == 0.0001
    assert out[1].mark_price == 0.0  # empty string falls back to 0
    sent = client._rest.calls[0]["params"]
    assert sent["limit"] == 1000  # clamped
    assert sent["startTime"] == 1
    assert sent["endTime"] == 2


@pytest.mark.asyncio
async def test_funding_rate_history_raises_on_error() -> None:
    """v0.4.0 BEHAVIORAL BREAK: was silent [] return, now raises typed exception."""
    from binance_shioaji_sdk.market_info import MarketInfo
    from binance_shioaji_sdk.exceptions import BinanceMarketDataError

    client = _FakeClient()
    client._rest.queue("GET", "/fapi/v1/fundingRate", {"error": "HTTP 500"})

    mi = MarketInfo(client)
    with pytest.raises(BinanceMarketDataError):
        await mi.funding_rate_history("BTC")


# ---------------------------------------------------------------------------
# Migrated from upstream TestFundingRate / TestFundingRateHistory /
# TestGetOpenInterest (endpoint behavior — Protocol contract layer stays
# in an upstream broker adapter test).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_funding_rate_symbol_already_usdt_no_double_suffix() -> None:
    from binance_shioaji_sdk.market_info import MarketInfo

    client = _FakeClient()
    client._rest.queue(
        "GET",
        "/fapi/v1/premiumIndex",
        {"lastFundingRate": "0.0002", "nextFundingTime": 1700000000000},
    )
    mi = MarketInfo(client)
    await mi.funding_rate("ETHUSDT")
    sent = client._rest.calls[0]["params"]
    assert sent["symbol"] == "ETHUSDT"  # no double-suffix


@pytest.mark.asyncio
async def test_funding_rate_raises_on_4xx() -> None:
    """v0.4.0: was {error,...} dict return, now raises BinanceMarketDataError."""
    from binance_shioaji_sdk.market_info import MarketInfo
    from binance_shioaji_sdk.exceptions import BinanceMarketDataError

    client = _FakeClient()
    client._rest.queue(
        "GET", "/fapi/v1/premiumIndex", {"error": "HTTP 400", "detail": {"code": -1121}}
    )
    mi = MarketInfo(client)
    with pytest.raises(BinanceMarketDataError):
        await mi.funding_rate("INVALID")


@pytest.mark.asyncio
async def test_funding_rate_history_symbol_normalization() -> None:
    from binance_shioaji_sdk.market_info import MarketInfo

    client = _FakeClient()
    client._rest.queue(
        "GET", "/fapi/v1/fundingRate",
        [{"symbol": "BTCUSDT", "fundingTime": 1700000000000,
          "fundingRate": "0.0001", "markPrice": "50000"}],
    )
    mi = MarketInfo(client)
    await mi.funding_rate_history("BTC", limit=1)
    assert client._rest.calls[0]["params"]["symbol"] == "BTCUSDT"


@pytest.mark.asyncio
async def test_funding_rate_history_limit_minimum_1() -> None:
    from binance_shioaji_sdk.market_info import MarketInfo

    client = _FakeClient()
    client._rest.queue("GET", "/fapi/v1/fundingRate", [])
    mi = MarketInfo(client)
    await mi.funding_rate_history("BTCUSDT", limit=0)
    assert client._rest.calls[0]["params"]["limit"] == 1


@pytest.mark.asyncio
async def test_funding_rate_history_no_time_params_not_forwarded() -> None:
    from binance_shioaji_sdk.market_info import MarketInfo

    client = _FakeClient()
    client._rest.queue("GET", "/fapi/v1/fundingRate", [])
    mi = MarketInfo(client)
    await mi.funding_rate_history("BTCUSDT", limit=5)
    sent = client._rest.calls[0]["params"]
    assert "startTime" not in sent
    assert "endTime" not in sent


@pytest.mark.asyncio
async def test_funding_rate_history_uses_correct_endpoint() -> None:
    from binance_shioaji_sdk.market_info import MarketInfo

    client = _FakeClient()
    client._rest.queue("GET", "/fapi/v1/fundingRate", [])
    mi = MarketInfo(client)
    await mi.funding_rate_history("BTCUSDT", limit=1)
    # First call must hit /fapi/v1/fundingRate, not /premiumIndex
    assert client._rest.calls[0]["path"] == "/fapi/v1/fundingRate"


@pytest.mark.asyncio
async def test_open_interest_symbol_auto_appends_usdt() -> None:
    from binance_shioaji_sdk.market_info import MarketInfo

    client = _FakeClient()
    client._rest.queue(
        "GET", "/fapi/v1/openInterest",
        {"openInterest": "100.0", "time": 1713400000000},
    )
    client._rest.queue("GET", "/fapi/v1/premiumIndex", {"markPrice": "50000.0"})

    mi = MarketInfo(client)
    out = await mi.open_interest("BTC")
    assert out.code == "BTCUSDT"
    # First REST call params symbol must be normalized
    assert client._rest.calls[0]["params"]["symbol"] == "BTCUSDT"


@pytest.mark.asyncio
async def test_open_interest_raises_on_api_error() -> None:
    """v0.4.0: was {error,...} dict, now raises BinanceMarketDataError."""
    from binance_shioaji_sdk.market_info import MarketInfo
    from binance_shioaji_sdk.exceptions import BinanceMarketDataError

    client = _FakeClient()
    client._rest.queue("GET", "/fapi/v1/openInterest",
                       {"error": "HTTP 400", "detail": {"code": -1121}})

    mi = MarketInfo(client)
    with pytest.raises(BinanceMarketDataError):
        await mi.open_interest("INVALID")


@pytest.mark.asyncio
async def test_open_interest_mark_price_failure_yields_zero_usdt() -> None:
    """When premiumIndex fails the OI value is preserved but USDT notional = 0."""
    from binance_shioaji_sdk.market_info import MarketInfo

    client = _FakeClient()
    client._rest.queue(
        "GET", "/fapi/v1/openInterest",
        {"openInterest": "999.0", "time": 1713400000000},
    )
    # Mark price call fails with error dict
    client._rest.queue("GET", "/fapi/v1/premiumIndex", {"error": "HTTP 500"})

    mi = MarketInfo(client)
    out = await mi.open_interest("BTCUSDT")
    assert out.open_interest == 999.0
    # 0.0 fallback (best-effort) when mark price call fails
    assert out.open_interest_usdt == 0.0


@pytest.mark.asyncio
async def test_open_interest_usdt_calculation() -> None:
    """oi_usdt ≈ oi * mark_price (rounded to 2 decimals)."""
    from binance_shioaji_sdk.market_info import MarketInfo

    client = _FakeClient()
    client._rest.queue(
        "GET", "/fapi/v1/openInterest",
        {"openInterest": "100", "time": 0},
    )
    client._rest.queue("GET", "/fapi/v1/premiumIndex", {"markPrice": "60000"})

    mi = MarketInfo(client)
    out = await mi.open_interest("BTCUSDT")
    assert out.open_interest_usdt == round(100 * 60000, 2)


@pytest.mark.asyncio
async def test_funding_rate_history_partial_bad_entry_skipped() -> None:
    from binance_shioaji_sdk.market_info import MarketInfo

    client = _FakeClient()
    client._rest.queue(
        "GET", "/fapi/v1/fundingRate",
        [
            {"symbol": "BTCUSDT", "fundingTime": 1700000000000,
             "fundingRate": "0.0001", "markPrice": "50000"},
            # Bad entry: missing fundingTime
            {"symbol": "BTCUSDT", "fundingRate": "BAD"},
            {"symbol": "BTCUSDT", "fundingTime": 1700028800000,
             "fundingRate": "0.00012", "markPrice": "51000"},
        ],
    )
    mi = MarketInfo(client)
    out = await mi.funding_rate_history("BTCUSDT", limit=3)
    # Bad entry skipped; 2 good ones remain
    # v0.4.0: funding_time is ISO 8601 UTC string (was epoch ms int)
    assert len(out) == 2
    assert out[0].funding_time.startswith("2023-11-14") and out[0].funding_time.endswith("+00:00")
    assert out[1].funding_time.startswith("2023-11-15") and out[1].funding_time.endswith("+00:00")
