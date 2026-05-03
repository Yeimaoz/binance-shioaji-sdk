"""Tests for lcz_binance_sdk.quote.Quote namespace."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest


class _FakeContract:
    def __init__(self, symbol: str) -> None:
        self.symbol = symbol


class _FakeClient:
    """Stub BinanceClient: only what Quote needs."""

    def __init__(self, api_key: str | None = None, base_url: str = "https://fapi.binance.com") -> None:
        self.api_key = api_key
        self._base_url = base_url

        class _RestStub:
            def __init__(self) -> None:
                self._client = object()  # placeholder httpx-like

        self._rest = _RestStub()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_subscribe_registers_tick_callback_and_starts_task(monkeypatch: pytest.MonkeyPatch) -> None:
    from lcz_binance_sdk.quote import Quote

    q = Quote(_FakeClient())
    # Replace the WS task body with a no-op so create_task doesn't dial out
    monkeypatch.setattr(Quote, "_run_mark_price_loop", AsyncMock(return_value=None))

    received: list[tuple] = []
    await q.subscribe(_FakeContract("BTC"), "tick", lambda *a: received.append(a))

    assert "BTCUSDT" in q._tick_callbacks
    assert len(q._tick_callbacks["BTCUSDT"]) == 1
    assert q._mark_task is not None

    # Dispatch a synthetic markPriceUpdate
    q._dispatch_mark_price({"e": "markPriceUpdate", "s": "BTCUSDT", "p": "50000.5", "E": 1700000000000})
    assert received and received[0][0] == "BTCUSDT" and received[0][1] == 50000.5


@pytest.mark.asyncio
async def test_dispatch_mark_price_drops_invalid_payloads(monkeypatch: pytest.MonkeyPatch) -> None:
    from lcz_binance_sdk.quote import Quote

    q = Quote(_FakeClient())
    monkeypatch.setattr(Quote, "_run_mark_price_loop", AsyncMock(return_value=None))

    seen: list = []
    await q.subscribe(_FakeContract("ETH"), "mark_price", lambda *a: seen.append(a))

    # wrong event type
    q._dispatch_mark_price({"e": "kline", "s": "ETHUSDT", "p": "10"})
    # negative price
    q._dispatch_mark_price({"e": "markPriceUpdate", "s": "ETHUSDT", "p": "-1"})
    # malformed
    q._dispatch_mark_price({"e": "markPriceUpdate", "s": "ETHUSDT", "p": "not-a-num"})

    assert seen == []


@pytest.mark.asyncio
async def test_global_tick_callback_path(monkeypatch: pytest.MonkeyPatch) -> None:
    from lcz_binance_sdk.quote import Quote

    q = Quote(_FakeClient())
    monkeypatch.setattr(Quote, "_run_mark_price_loop", AsyncMock(return_value=None))
    monkeypatch.setattr(Quote, "_run_book_ticker_loop", AsyncMock(return_value=None))

    global_seen: list = []
    q.set_on_tick_callback(lambda *a: global_seen.append(a))

    await q.subscribe(_FakeContract("SOL"), "tick", lambda *a: None)
    q._dispatch_mark_price({"e": "markPriceUpdate", "s": "SOLUSDT", "p": "100", "E": 0})
    assert len(global_seen) == 1
    assert global_seen[0][0] == "SOLUSDT"

    # Book ticker also fires global cb (with mid price)
    await q.subscribe(_FakeContract("SOL"), "bookticker", lambda *a: None)
    q._dispatch_book_ticker({"s": "SOLUSDT", "b": "99.0", "a": "101.0", "B": "5", "A": "7"})
    assert len(global_seen) == 2
    sym, mid, mid2 = global_seen[1]
    assert sym == "SOLUSDT"
    assert mid == 100.0


@pytest.mark.asyncio
async def test_subscribe_kline_validates_interval(monkeypatch: pytest.MonkeyPatch) -> None:
    from lcz_binance_sdk.quote import Quote

    q = Quote(_FakeClient())
    monkeypatch.setattr(Quote, "_run_kline_loop", AsyncMock(return_value=None))

    bars: list[dict] = []
    await q.subscribe(_FakeContract("BTC"), "kline_1m", lambda b: bars.append(b))
    assert ("BTCUSDT", "1m") in q._kline_callbacks

    with pytest.raises(ValueError):
        await q.subscribe(_FakeContract("BTC"), "kline_2s", lambda b: None)

    # synthetic closed bar
    await q._dispatch_kline(
        {
            "e": "kline",
            "s": "BTCUSDT",
            "k": {
                "x": True, "i": "1m", "s": "BTCUSDT",
                "t": 1700000000000,
                "o": "1", "h": "2", "l": "0.5", "c": "1.5", "v": "10",
            },
        }
    )
    assert bars and bars[0]["close"] == 1.5 and bars[0]["closed"] is True

    # open bar must be skipped
    await q._dispatch_kline(
        {
            "e": "kline",
            "s": "BTCUSDT",
            "k": {"x": False, "i": "1m", "s": "BTCUSDT", "t": 0, "o": "1", "h": "2", "l": "0", "c": "1", "v": "0"},
        }
    )
    assert len(bars) == 1


@pytest.mark.asyncio
async def test_subscribe_unknown_quote_type_raises() -> None:
    from lcz_binance_sdk.quote import Quote

    q = Quote(_FakeClient())
    with pytest.raises(ValueError):
        await q.subscribe(_FakeContract("BTC"), "level2", lambda *a: None)


@pytest.mark.asyncio
async def test_subscribe_user_stream_skips_without_api_key() -> None:
    from lcz_binance_sdk.quote import Quote

    q = Quote(_FakeClient(api_key=None))
    await q.subscribe_user_stream(lambda r: None)
    assert q._user_stream_task is None
    assert q._user_stream_callbacks == []


@pytest.mark.asyncio
async def test_subscribe_user_stream_starts_tasks(monkeypatch: pytest.MonkeyPatch) -> None:
    from lcz_binance_sdk.quote import Quote

    q = Quote(_FakeClient(api_key="key123"))
    monkeypatch.setattr(Quote, "_create_listen_key", AsyncMock(return_value="LK_AAA"))
    monkeypatch.setattr(Quote, "_run_user_stream", AsyncMock(return_value=None))
    monkeypatch.setattr(Quote, "_run_listen_key_keepalive", AsyncMock(return_value=None))

    seen: list = []
    await q.subscribe_user_stream(lambda r: seen.append(r))
    assert q._listen_key == "LK_AAA"
    assert q._user_stream_task is not None
    assert q._listen_key_task is not None
    # second subscribe just adds callback, no new task
    await q.subscribe_user_stream(lambda r: seen.append(r))
    assert len(q._user_stream_callbacks) == 2
    # let tasks complete (they are no-op AsyncMocks)
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_handle_user_event_routes_and_triggers_wait_fill() -> None:
    from lcz_binance_sdk.quote import Quote

    q = Quote(_FakeClient(api_key="k"))
    received: list = []
    q._user_stream_callbacks.append(lambda r: received.append(r))

    # waiter starts before fill
    fill_task = asyncio.create_task(q.wait_fill("42", timeout=1.0))
    await asyncio.sleep(0)  # let wait_fill register the Event

    q._handle_user_event(
        {
            "e": "executionReport",
            "i": 42, "s": "BTCUSDT", "X": "FILLED", "S": "BUY", "o": "MARKET",
            "q": "1", "z": "1", "L": "50000", "ap": "50000",
        }
    )

    result = await fill_task
    assert result is not None
    assert result.status == "FILLED"
    assert received and received[0].order_id == "42"


@pytest.mark.asyncio
async def test_wait_fill_returns_cached_terminal() -> None:
    from lcz_binance_sdk._internal import ExecutionReport
    from lcz_binance_sdk.quote import Quote

    q = Quote(_FakeClient(api_key="k"))
    q._execution_reports["7"] = ExecutionReport(
        order_id="7", symbol="BTCUSDT", status="CANCELED", side="BUY",
        order_type="LIMIT", qty=1, filled_qty=0, last_filled_price=0, avg_price=0,
    )
    out = await q.wait_fill("7", timeout=0.1)
    assert out is not None
    assert out.status == "CANCELED"


@pytest.mark.asyncio
async def test_wait_fill_timeout_returns_none() -> None:
    from lcz_binance_sdk.quote import Quote

    q = Quote(_FakeClient(api_key="k"))
    out = await q.wait_fill("does-not-exist", timeout=0.05)
    assert out is None
