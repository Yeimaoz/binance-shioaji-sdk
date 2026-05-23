"""Tests for binance_shioaji_sdk.quote.Quote namespace."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest


class _FakeContract:
    def __init__(self, symbol: str) -> None:
        self.symbol = symbol


class _FakeClient:
    """Stub BinanceClient: only what Quote needs."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = "https://fapi.binance.com",
        ws_base_url: str = "wss://fstream.binance.com",
    ) -> None:
        self.api_key = api_key
        self._base_url = base_url
        self._ws_base_url = ws_base_url

        class _RestStub:
            def __init__(self) -> None:
                self._client = object()  # placeholder httpx-like

        self._rest = _RestStub()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_subscribe_registers_tick_callback_and_starts_task(monkeypatch: pytest.MonkeyPatch) -> None:
    from binance_shioaji_sdk.quote import Quote

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
async def test_quote_propagates_testnet_ws_base_url() -> None:
    """v0.2.1 regression: Quote 應從 client._ws_base_url 拿 testnet WS URL，
    傳給 BinanceWSManager。Pre-fix bug：Quote 用 hardcode mainnet URL。"""
    from binance_shioaji_sdk.quote import Quote

    testnet_client = _FakeClient(ws_base_url="wss://stream.binancefuture.com")
    q = Quote(testnet_client)

    assert q._ws_manager.base_url == "wss://stream.binancefuture.com"

    mainnet_client = _FakeClient(ws_base_url="wss://fstream.binance.com")
    q2 = Quote(mainnet_client)
    assert q2._ws_manager.base_url == "wss://fstream.binance.com"


@pytest.mark.asyncio
async def test_dispatch_mark_price_drops_invalid_payloads(monkeypatch: pytest.MonkeyPatch) -> None:
    from binance_shioaji_sdk.quote import Quote

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
    from binance_shioaji_sdk.quote import Quote

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
    from binance_shioaji_sdk.quote import Quote

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
    from binance_shioaji_sdk.quote import Quote

    q = Quote(_FakeClient())
    with pytest.raises(ValueError):
        await q.subscribe(_FakeContract("BTC"), "level2", lambda *a: None)


@pytest.mark.asyncio
async def test_subscribe_user_stream_skips_without_api_key() -> None:
    from binance_shioaji_sdk.quote import Quote

    q = Quote(_FakeClient(api_key=None))
    await q.subscribe_user_stream(lambda r: None)
    assert q._user_stream_task is None
    assert q._user_stream_callbacks == []


@pytest.mark.asyncio
async def test_subscribe_user_stream_starts_tasks(monkeypatch: pytest.MonkeyPatch) -> None:
    from binance_shioaji_sdk.quote import Quote

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
    from binance_shioaji_sdk.quote import Quote

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
    from binance_shioaji_sdk._internal import ExecutionReport
    from binance_shioaji_sdk.quote import Quote

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
    from binance_shioaji_sdk.quote import Quote

    q = Quote(_FakeClient(api_key="k"))
    out = await q.wait_fill("does-not-exist", timeout=0.05)
    assert out is None


# ---------------------------------------------------------------------------
# Migrated from upstream TestSubscribeBookTicker / TestSubscribeBars
# (dispatch-only behaviour — adapter wiring tests stay in the parent project)
# ---------------------------------------------------------------------------


class TestDispatchBookTicker:
    def test_dispatch_book_ticker_happy_path(self) -> None:
        from binance_shioaji_sdk.quote import Quote

        q = Quote(_FakeClient())
        received: list[tuple] = []

        def cb(sym, bid, ask, bid_qty, ask_qty):
            received.append((sym, bid, ask, bid_qty, ask_qty))

        q._book_ticker_callbacks["BTCUSDT"] = [cb]
        q._dispatch_book_ticker(
            {"s": "BTCUSDT", "b": "49999.5", "B": "1.234", "a": "50000.0", "A": "0.567"}
        )
        assert len(received) == 1
        sym, bid, ask, bid_qty, ask_qty = received[0]
        assert sym == "BTCUSDT"
        assert bid == 49999.5
        assert ask == 50000.0
        assert bid_qty == 1.234
        assert ask_qty == 0.567

    def test_dispatch_book_ticker_skips_zero_bid(self) -> None:
        from binance_shioaji_sdk.quote import Quote

        q = Quote(_FakeClient())
        received: list = []
        q._book_ticker_callbacks["BTCUSDT"] = [lambda *a: received.append(1)]
        q._dispatch_book_ticker({"s": "BTCUSDT", "b": "0", "a": "50000.0", "B": "1", "A": "1"})
        assert received == []

    def test_dispatch_book_ticker_skips_zero_ask(self) -> None:
        from binance_shioaji_sdk.quote import Quote

        q = Quote(_FakeClient())
        received: list = []
        q._book_ticker_callbacks["BTCUSDT"] = [lambda *a: received.append(1)]
        q._dispatch_book_ticker({"s": "BTCUSDT", "b": "50000.0", "a": "0", "B": "1", "A": "1"})
        assert received == []

    def test_dispatch_book_ticker_parse_error_skipped(self) -> None:
        from binance_shioaji_sdk.quote import Quote

        q = Quote(_FakeClient())
        received: list = []
        q._book_ticker_callbacks["BTCUSDT"] = [lambda *a: received.append(1)]
        # Missing "a" key entirely
        q._dispatch_book_ticker({"s": "BTCUSDT", "b": "50000.0"})
        assert received == []

    def test_dispatch_book_ticker_routes_to_correct_symbol(self) -> None:
        from binance_shioaji_sdk.quote import Quote

        q = Quote(_FakeClient())
        btc_received: list = []
        eth_received: list = []
        q._book_ticker_callbacks["BTCUSDT"] = [lambda *a: btc_received.append(a)]
        q._book_ticker_callbacks["ETHUSDT"] = [lambda *a: eth_received.append(a)]
        q._dispatch_book_ticker({"s": "BTCUSDT", "b": "50000", "a": "50001", "B": "1", "A": "1"})
        assert len(btc_received) == 1
        assert len(eth_received) == 0

    def test_dispatch_book_ticker_callback_exception_does_not_crash(self) -> None:
        from binance_shioaji_sdk.quote import Quote

        q = Quote(_FakeClient())

        def bad_cb(*a):
            raise RuntimeError("callback exploded")

        q._book_ticker_callbacks["BTCUSDT"] = [bad_cb]
        # Must not raise
        q._dispatch_book_ticker({"s": "BTCUSDT", "b": "50000", "a": "50001", "B": "1", "A": "1"})

    def test_dispatch_book_ticker_unparseable_floats_skipped(self) -> None:
        from binance_shioaji_sdk.quote import Quote

        q = Quote(_FakeClient())
        received: list = []
        q._book_ticker_callbacks["BTCUSDT"] = [lambda *a: received.append(1)]
        # Malformed bid value
        q._dispatch_book_ticker({"s": "BTCUSDT", "b": "not-a-number", "a": "50000", "B": "1", "A": "1"})
        assert received == []

    def test_dispatch_book_ticker_no_registered_symbol_is_noop(self) -> None:
        from binance_shioaji_sdk.quote import Quote

        q = Quote(_FakeClient())
        # No callback for SOLUSDT; must not raise / log noisily
        q._dispatch_book_ticker({"s": "SOLUSDT", "b": "100", "B": "10", "a": "101", "A": "5"})


class TestDispatchKline:
    @pytest.mark.asyncio
    async def test_dispatch_kline_bar_dict_correct(self) -> None:
        from binance_shioaji_sdk.quote import Quote

        q = Quote(_FakeClient())
        received: list[dict] = []
        q._kline_callbacks[("BTCUSDT", "1m")] = lambda b: received.append(b)
        await q._dispatch_kline(
            {
                "e": "kline",
                "s": "BTCUSDT",
                "k": {
                    "t": 1713400000000,
                    "T": 1713400059999,
                    "s": "BTCUSDT",
                    "i": "1m",
                    "o": "50000.0",
                    "h": "50500.0",
                    "l": "49800.0",
                    "c": "50200.0",
                    "v": "12.345",
                    "x": True,
                },
            }
        )
        assert len(received) == 1
        bar = received[0]
        assert bar["open"] == 50000.0
        assert bar["high"] == 50500.0
        assert bar["low"] == 49800.0
        assert bar["close"] == 50200.0
        assert bar["volume"] == 12.345
        assert bar["closed"] is True
        assert bar["interval"] == "1m"
        assert bar["symbol"] == "BTCUSDT"

    @pytest.mark.asyncio
    async def test_dispatch_kline_open_bar_skipped(self) -> None:
        """Open (not yet closed) bars are filtered out by _dispatch_kline."""
        from binance_shioaji_sdk.quote import Quote

        q = Quote(_FakeClient())
        received: list = []
        q._kline_callbacks[("BTCUSDT", "1m")] = lambda b: received.append(b)
        await q._dispatch_kline(
            {
                "e": "kline",
                "s": "BTCUSDT",
                "k": {"t": 0, "T": 0, "s": "BTCUSDT", "i": "1m",
                      "o": "1", "h": "1", "l": "1", "c": "1", "v": "1", "x": False},
            }
        )
        assert received == []

    @pytest.mark.asyncio
    async def test_dispatch_kline_bad_payload_skipped(self) -> None:
        from binance_shioaji_sdk.quote import Quote

        q = Quote(_FakeClient())
        received: list = []
        q._kline_callbacks[("BTCUSDT", "1m")] = lambda b: received.append(b)
        # Missing "k" key entirely
        await q._dispatch_kline({"e": "kline", "s": "BTCUSDT"})
        assert received == []

    @pytest.mark.asyncio
    async def test_dispatch_kline_wrong_event_type_skipped(self) -> None:
        from binance_shioaji_sdk.quote import Quote

        q = Quote(_FakeClient())
        received: list = []
        q._kline_callbacks[("BTCUSDT", "1m")] = lambda b: received.append(b)
        await q._dispatch_kline({"e": "trade", "s": "BTCUSDT"})
        assert received == []

    @pytest.mark.asyncio
    async def test_dispatch_kline_unregistered_pair_skipped(self) -> None:
        from binance_shioaji_sdk.quote import Quote

        q = Quote(_FakeClient())
        # Never registered (BTCUSDT, 5m); must not raise
        await q._dispatch_kline(
            {
                "e": "kline",
                "s": "BTCUSDT",
                "k": {"t": 0, "T": 0, "s": "BTCUSDT", "i": "5m",
                      "o": "1", "h": "1", "l": "1", "c": "1", "v": "1", "x": True},
            }
        )

    @pytest.mark.asyncio
    async def test_dispatch_kline_async_callback_supported(self) -> None:
        from binance_shioaji_sdk.quote import Quote

        q = Quote(_FakeClient())
        received: list = []

        async def async_cb(b):
            received.append(b)

        q._kline_callbacks[("BTCUSDT", "1m")] = async_cb
        await q._dispatch_kline(
            {
                "e": "kline",
                "s": "BTCUSDT",
                "k": {"t": 0, "T": 0, "s": "BTCUSDT", "i": "1m",
                      "o": "1", "h": "2", "l": "0.5", "c": "1.5", "v": "10", "x": True},
            }
        )
        assert len(received) == 1
        assert received[0]["close"] == 1.5

    @pytest.mark.asyncio
    async def test_dispatch_kline_callback_exception_does_not_crash(self) -> None:
        from binance_shioaji_sdk.quote import Quote

        q = Quote(_FakeClient())

        def bad_cb(b):
            raise RuntimeError("kline cb crashed")

        q._kline_callbacks[("BTCUSDT", "1m")] = bad_cb
        await q._dispatch_kline(
            {
                "e": "kline",
                "s": "BTCUSDT",
                "k": {"t": 0, "T": 0, "s": "BTCUSDT", "i": "1m",
                      "o": "1", "h": "2", "l": "0.5", "c": "1.5", "v": "10", "x": True},
            }
        )


# ---------------------------------------------------------------------------
# Migrated from upstream TestExecutionReport (handler logic)
# Note: an upstream broker adapter calls this `_handle_execution_report`; SDK
# Quote names it `_handle_user_event` and parses the same executionReport
# shape into ExecutionReport.
# ---------------------------------------------------------------------------


class TestHandleUserEvent:
    def test_filled_triggers_event_and_calls_callbacks(self) -> None:
        from binance_shioaji_sdk.quote import Quote

        q = Quote(_FakeClient(api_key="k"))
        received: list = []
        q._user_stream_callbacks.append(lambda r: received.append(r))
        event = asyncio.Event()
        q._fill_events["123"] = event

        q._handle_user_event(
            {
                "e": "executionReport",
                "i": 123, "s": "BTCUSDT", "X": "FILLED",
                "S": "BUY", "o": "MARKET",
                "q": "0.001", "z": "0.001",
                "L": "50000.0", "ap": "50000.0",
            }
        )

        assert len(received) == 1
        report = received[0]
        assert report.status == "FILLED"
        assert report.filled_qty == 0.001
        assert event.is_set()

    def test_partially_filled_does_not_trigger_event(self) -> None:
        from binance_shioaji_sdk.quote import Quote

        q = Quote(_FakeClient(api_key="k"))
        received: list = []
        q._user_stream_callbacks.append(lambda r: received.append(r))
        event = asyncio.Event()
        q._fill_events["456"] = event

        q._handle_user_event(
            {
                "e": "executionReport",
                "i": 456, "s": "BTCUSDT", "X": "PARTIALLY_FILLED",
                "S": "BUY", "o": "LIMIT",
                "q": "0.010", "z": "0.005",
                "L": "49990.0", "ap": "0",
            }
        )

        assert len(received) == 1
        assert not event.is_set()  # non-terminal

    def test_canceled_triggers_event(self) -> None:
        from binance_shioaji_sdk.quote import Quote

        q = Quote(_FakeClient(api_key="k"))
        event = asyncio.Event()
        q._fill_events["789"] = event

        q._handle_user_event(
            {
                "e": "executionReport",
                "i": 789, "s": "ETHUSDT", "X": "CANCELED",
                "S": "SELL", "o": "LIMIT",
                "q": "0.1", "z": "0.0", "L": "0", "ap": "0",
            }
        )

        assert event.is_set()
        report = q._execution_reports.get("789")
        assert report is not None
        assert report.status == "CANCELED"

    def test_expired_triggers_event(self) -> None:
        from binance_shioaji_sdk.quote import Quote

        q = Quote(_FakeClient(api_key="k"))
        event = asyncio.Event()
        q._fill_events["999"] = event

        q._handle_user_event(
            {
                "e": "executionReport",
                "i": 999, "s": "BTCUSDT", "X": "EXPIRED",
                "S": "BUY", "o": "MARKET",
                "q": "0.001", "z": "0", "L": "0", "ap": "0",
            }
        )
        assert event.is_set()

    def test_parse_error_does_not_crash(self) -> None:
        from binance_shioaji_sdk.quote import Quote

        q = Quote(_FakeClient(api_key="k"))
        # Missing required "i" -> parse error logged, no raise
        q._handle_user_event({"e": "executionReport", "s": "BTCUSDT", "X": "FILLED"})

    def test_wrong_event_type_skipped(self) -> None:
        from binance_shioaji_sdk.quote import Quote

        q = Quote(_FakeClient(api_key="k"))
        event = asyncio.Event()
        q._fill_events["111"] = event
        q._handle_user_event({"e": "ACCOUNT_UPDATE", "i": 111, "X": "FILLED"})
        assert not event.is_set()
        assert "111" not in q._execution_reports

    def test_stores_latest_report_in_dict(self) -> None:
        from binance_shioaji_sdk.quote import Quote

        q = Quote(_FakeClient(api_key="k"))
        q._handle_user_event(
            {
                "e": "executionReport",
                "i": 111, "s": "BTCUSDT", "X": "NEW",
                "S": "BUY", "o": "LIMIT",
                "q": "0.001", "z": "0", "L": "0", "ap": "0",
            }
        )
        assert "111" in q._execution_reports
        assert q._execution_reports["111"].status == "NEW"

    def test_callback_exception_does_not_crash(self) -> None:
        from binance_shioaji_sdk.quote import Quote

        q = Quote(_FakeClient(api_key="k"))
        event = asyncio.Event()
        q._fill_events["222"] = event

        def bad_cb(report):
            raise ValueError("cb crashed")

        good_received: list = []
        q._user_stream_callbacks.append(bad_cb)
        q._user_stream_callbacks.append(lambda r: good_received.append(r))

        q._handle_user_event(
            {
                "e": "executionReport",
                "i": 222, "s": "BTCUSDT", "X": "FILLED",
                "S": "BUY", "o": "MARKET",
                "q": "0.001", "z": "0.001", "L": "50000", "ap": "50000",
            }
        )
        assert len(good_received) == 1
        assert event.is_set()

    def test_no_event_registered_does_not_raise(self) -> None:
        from binance_shioaji_sdk.quote import Quote

        q = Quote(_FakeClient(api_key="k"))
        # Terminal status without any wait_fill registered — must not raise
        q._handle_user_event(
            {
                "e": "executionReport",
                "i": 9999, "s": "BTCUSDT", "X": "FILLED",
                "S": "BUY", "o": "MARKET",
                "q": "0.001", "z": "0.001", "L": "50000", "ap": "50000",
            }
        )


# ---------------------------------------------------------------------------
# Migrated from upstream TestWaitFill — terminal-state rendezvous
# ---------------------------------------------------------------------------


class TestWaitFillExtended:
    @pytest.mark.asyncio
    async def test_wait_fill_event_triggered(self) -> None:
        from binance_shioaji_sdk.quote import Quote

        q = Quote(_FakeClient(api_key="k"))

        async def trigger() -> None:
            await asyncio.sleep(0.05)
            q._handle_user_event(
                {
                    "e": "executionReport",
                    "i": 888, "s": "BTCUSDT", "X": "FILLED",
                    "S": "BUY", "o": "MARKET",
                    "q": "0.001", "z": "0.001", "L": "50100", "ap": "50100",
                }
            )

        trigger_task = asyncio.create_task(trigger())
        result = await q.wait_fill("888", timeout=2.0)
        await trigger_task
        assert result is not None
        assert result.status == "FILLED"
        assert result.avg_price == 50100.0

    @pytest.mark.asyncio
    async def test_wait_fill_cleans_up_event_after_fill(self) -> None:
        from binance_shioaji_sdk.quote import Quote

        q = Quote(_FakeClient(api_key="k"))

        async def trigger() -> None:
            await asyncio.sleep(0.02)
            q._handle_user_event(
                {
                    "e": "executionReport",
                    "i": 555, "s": "BTCUSDT", "X": "FILLED",
                    "S": "BUY", "o": "MARKET",
                    "q": "0.001", "z": "0.001", "L": "50000", "ap": "50000",
                }
            )

        asyncio.create_task(trigger())
        await q.wait_fill("555", timeout=1.0)
        assert "555" not in q._fill_events

    @pytest.mark.asyncio
    async def test_wait_fill_canceled_order_returns_report(self) -> None:
        from binance_shioaji_sdk.quote import Quote

        q = Quote(_FakeClient(api_key="k"))

        async def trigger() -> None:
            await asyncio.sleep(0.02)
            q._handle_user_event(
                {
                    "e": "executionReport",
                    "i": 333, "s": "ETHUSDT", "X": "CANCELED",
                    "S": "SELL", "o": "LIMIT",
                    "q": "0.1", "z": "0.0", "L": "0", "ap": "0",
                }
            )

        asyncio.create_task(trigger())
        result = await q.wait_fill("333", timeout=1.0)
        assert result is not None
        assert result.status == "CANCELED"
