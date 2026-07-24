"""Tests for binance_shioaji_sdk._internal.ws_manager.

Covers BinanceWSManager.create_listen_key / keepalive_listen_key REST
interactions, plus reconnect / stop_event behaviour of run_combined_stream
and run_user_stream loops. Mirrors an upstream broker adapter
TestSubscribeUserStream._create_listen_key / _listen_key_keepalive_loop /
_ws_user_stream_loop migrated to SDK internals.
"""
from __future__ import annotations

import asyncio
import contextlib
import sys
import types
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from binance_shioaji_sdk._internal import (
    BinanceAuthError,
    BinanceWSManager,
    LISTEN_KEY_KEEPALIVE_INTERVAL,
    VALID_KLINE_INTERVALS,
    WS_RECONNECT_BASE,
    WS_RECONNECT_MAX,
)


# ---------------------------------------------------------------------------
# Shared helper — patch `websockets.connect` to capture the URL it's called with
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def _patched_websockets_capturing_urls():
    """Patch `sys.modules["websockets"]` so `websockets.connect(url, ...)` is
    intercepted; yields (captured_urls, stop_evt). The fake connection raises
    StopAsyncIteration on first `__anext__`, which also sets stop_evt so the
    run_combined_stream / run_user_stream loop exits after one connect call."""
    captured_urls: list[str] = []
    stop_evt = asyncio.Event()

    class _FakeCtx:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        def __aiter__(self):
            return self

        async def __anext__(self):
            stop_evt.set()
            raise StopAsyncIteration

    def _fake_connect(url: str, **kwargs):  # noqa: ARG001
        captured_urls.append(url)
        return _FakeCtx()

    orig_ws = sys.modules.get("websockets")
    orig_exc = sys.modules.get("websockets.exceptions")
    sys.modules["websockets"] = types.SimpleNamespace(connect=_fake_connect)  # type: ignore[assignment]
    sys.modules["websockets.exceptions"] = types.SimpleNamespace(
        ConnectionClosedError=type("CCE", (Exception,), {}),
        ConnectionClosedOK=type("CCO", (Exception,), {}),
    )
    try:
        yield captured_urls, stop_evt
    finally:
        if orig_ws is not None:
            sys.modules["websockets"] = orig_ws
        else:
            sys.modules.pop("websockets", None)
        if orig_exc is not None:
            sys.modules["websockets.exceptions"] = orig_exc
        else:
            sys.modules.pop("websockets.exceptions", None)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class TestWSBaseURL:
    """v0.2.1 regression: testnet WS URL must thread through ws_manager.

    Pre-fix bug: client.py 算對 _ws_base_url 但 BinanceWSManager 內部 hardcode
    `wss://fstream.binance.com`，導致 testnet=True 時還是連 mainnet → testnet
    pricefeed 收不到 tick。
    """

    def test_default_base_url_is_mainnet(self) -> None:
        ws = BinanceWSManager()
        assert ws.base_url == "wss://fstream.binance.com"

    def test_explicit_testnet_base_url_stored(self) -> None:
        ws = BinanceWSManager(base_url="wss://stream.binancefuture.com")
        assert ws.base_url == "wss://stream.binancefuture.com"

    async def test_combined_stream_uses_instance_base_url(self) -> None:
        """run_combined_stream 應使用 self.base_url 構造 URL，不再 hardcode mainnet。"""
        ws = BinanceWSManager(base_url="wss://stream.binancefuture.com")
        with _patched_websockets_capturing_urls() as (captured_urls, stop_evt):
            await asyncio.wait_for(
                ws.run_combined_stream(
                    streams=["btcusdt@bookTicker"],
                    on_message=lambda d: None,
                    stop_event=stop_evt,
                    category="public",
                    max_attempts=1,
                ),
                timeout=2.0,
            )

        assert captured_urls, "websockets.connect 必須被呼叫"
        assert captured_urls[0].startswith("wss://stream.binancefuture.com/public/stream"), (
            f"testnet base_url 沒被使用或 URL 格式錯誤，實際 URL={captured_urls[0]}"
        )

    async def test_combined_stream_market_category_url(self) -> None:
        """P0 2026-07-24: run_combined_stream(category='market') 必須使用
        /market/stream?streams= 路徑（Binance 2026-04-23「Important WebSocket Change
        Notice」新制：market 類 stream 走 /market，legacy 無 category prefix 的
        /stream 已淘汰）。

        Bug history: v0.5.9 把 combined stream URL 統一改回無 category 的
        /stream?streams=（當時針對 bookTicker 的 P0 修復），但 2026-04-23 legacy
        URL 全面淘汰後，markPrice / kline 這類「一般市場資料」改須明確帶 /market
        prefix，否則握手成功但零訊息推送（silent-dead）。bookTicker 因屬於
        /public 分類，在淘汰過渡期恰好還能收到資料，掩蓋了 market 類早已失效的事實。
        Reference: developers.binance.com "Important WebSocket Change Notice"
        （USDS-M Futures WebSocket System Upgrade Notice, 2026-03-06 公告，
        2026-04-23 生效）。
        """
        ws = BinanceWSManager(base_url="wss://fstream.binance.com")
        with _patched_websockets_capturing_urls() as (captured_urls, stop_evt):
            await asyncio.wait_for(
                ws.run_combined_stream(
                    streams=["dogeusdt@markPrice"],
                    on_message=lambda d: None,
                    stop_event=stop_evt,
                    category="market",
                    max_attempts=1,
                ),
                timeout=2.0,
            )

        assert captured_urls, "websockets.connect 必須被呼叫"
        assert captured_urls[0] == "wss://fstream.binance.com/market/stream?streams=dogeusdt@markPrice", (
            f"combined stream URL 錯誤，實際={captured_urls[0]}"
        )

    async def test_combined_stream_public_category_url(self) -> None:
        """P0 2026-07-24 regression: bookTicker（高頻公開流）必須走
        /public/stream?streams=，不得落回 legacy 無 prefix 的 /stream（2026-04-23
        起已淘汰）也不得誤用 /market（bookTicker 不屬於 market 分類）。"""
        ws = BinanceWSManager(base_url="wss://fstream.binance.com")
        with _patched_websockets_capturing_urls() as (captured_urls, stop_evt):
            await asyncio.wait_for(
                ws.run_combined_stream(
                    streams=["xrpusdt@bookTicker", "btcusdt@bookTicker"],
                    on_message=lambda d: None,
                    stop_event=stop_evt,
                    category="public",
                    max_attempts=1,
                ),
                timeout=2.0,
            )

        assert captured_urls, "websockets.connect 必須被呼叫"
        assert captured_urls[0] == (
            "wss://fstream.binance.com/public/stream?streams=xrpusdt@bookTicker/btcusdt@bookTicker"
        ), f"combined stream URL 錯誤，實際={captured_urls[0]}"

    async def test_combined_stream_default_category_is_market(self) -> None:
        """category 未指定時預設 'market'（呼叫端仍應明確指定；此測試只鎖定預設值本身不漂移）。"""
        ws = BinanceWSManager(base_url="wss://fstream.binance.com")
        with _patched_websockets_capturing_urls() as (captured_urls, stop_evt):
            await asyncio.wait_for(
                ws.run_combined_stream(
                    streams=["ethusdt@kline_1m"],
                    on_message=lambda d: None,
                    stop_event=stop_evt,
                    max_attempts=1,
                ),
                timeout=2.0,
            )

        assert captured_urls, "websockets.connect 必須被呼叫"
        assert captured_urls[0].startswith("wss://fstream.binance.com/market/stream"), (
            f"預設 category 應為 market，實際 URL={captured_urls[0]}"
        )

    async def test_combined_stream_invalid_category_raises(self) -> None:
        """category 不在 {'public', 'market'} 時必須 fail fast（避免打錯路徑又
        silent-dead——這正是本次 P0 bug 的根因型態，寧可炸在呼叫端也不要吞掉）。"""
        stop_evt = asyncio.Event()
        with pytest.raises(ValueError, match="category"):
            await BinanceWSManager().run_combined_stream(
                streams=["btcusdt@bookTicker"],
                on_message=lambda d: None,
                stop_event=stop_evt,
                category="private",  # not a valid combined-stream category
            )

    async def test_user_stream_url_has_private_prefix(self) -> None:
        """run_user_stream 的 URL 必須含 /private/ prefix（2024-02-29 Binance 新 API，
        並在 2026-04-23「Important WebSocket Change Notice」新制中確認仍是正確路徑 —
        本次 P0 URL 巡查（kline/markPrice/user stream silent-dead）複查後 user stream
        本身不需要改動，此測試鎖定其現況不漂移）。

        舊 URL /ws/{listenKey} 握手成功但 Binance 靜默不推 ORDER_TRADE_UPDATE；
        新 URL /private/ws/{listenKey} 才能收到 user data events。
        """
        ws = BinanceWSManager(base_url="wss://fstream.binance.com")
        with _patched_websockets_capturing_urls() as (captured_urls, stop_evt):
            await asyncio.wait_for(
                ws.run_user_stream(
                    get_listen_key=AsyncMock(return_value="test-listen-key"),
                    on_message=lambda d: None,
                    stop_event=stop_evt,
                ),
                timeout=2.0,
            )

        assert captured_urls, "websockets.connect 必須被呼叫"
        assert "/private/ws?" in captured_urls[0] and "listenKey=" in captured_urls[0], (
            f"URL 格式錯誤（應為 /private/ws?listenKey=...），實際={captured_urls[0]}"
        )
        assert "events=ORDER_TRADE_UPDATE" in captured_urls[0], (
            f"URL 缺少 events=ORDER_TRADE_UPDATE 參數，實際={captured_urls[0]}"
        )


class TestConstants:
    def test_constants_values(self) -> None:
        assert LISTEN_KEY_KEEPALIVE_INTERVAL == 30 * 60
        assert WS_RECONNECT_BASE == 1.0
        assert WS_RECONNECT_MAX == 60.0
        assert "1m" in VALID_KLINE_INTERVALS
        assert "5m" in VALID_KLINE_INTERVALS
        assert "1h" in VALID_KLINE_INTERVALS
        assert "1d" in VALID_KLINE_INTERVALS
        # Bogus intervals should NOT be present
        assert "2m" not in VALID_KLINE_INTERVALS
        assert "99x" not in VALID_KLINE_INTERVALS


# ---------------------------------------------------------------------------
# create_listen_key
# ---------------------------------------------------------------------------


class TestCreateListenKey:
    async def test_happy_path_returns_listen_key(self, make_response) -> None:
        client = MagicMock()
        client.post = AsyncMock(return_value=make_response(200, {"listenKey": "LK_ABC"}))
        key = await BinanceWSManager.create_listen_key(
            client, "api_key_xxx", "https://fapi.binance.com"
        )
        assert key == "LK_ABC"
        # Verify call shape: POST {base}/fapi/v1/listenKey + X-MBX-APIKEY header
        call_args = client.post.call_args
        assert call_args.args[0] == "https://fapi.binance.com/fapi/v1/listenKey"
        assert call_args.kwargs["headers"] == {"X-MBX-APIKEY": "api_key_xxx"}

    async def test_http_401_raises_auth_error(self, make_response) -> None:
        """401 = credentials rejected; fail fast, not silent None."""
        client = MagicMock()
        client.post = AsyncMock(
            return_value=make_response(401, {"code": -2014, "msg": "API-key format invalid"})
        )
        with pytest.raises(BinanceAuthError, match="HTTP 401"):
            await BinanceWSManager.create_listen_key(
                client, "api_key", "https://fapi.binance.com"
            )

    async def test_http_403_raises_auth_error(self, make_response) -> None:
        """403 = credentials forbidden (e.g. wrong permission / IP); fail fast."""
        client = MagicMock()
        client.post = AsyncMock(
            return_value=make_response(403, {"code": -2015, "msg": "Invalid API-key, IP, or permissions"})
        )
        with pytest.raises(BinanceAuthError, match="HTTP 403"):
            await BinanceWSManager.create_listen_key(
                client, "api_key", "https://fapi.binance.com"
            )

    async def test_http_5xx_returns_none(self, make_response) -> None:
        """Transient server error stays best-effort: log + None (caller proceeds)."""
        client = MagicMock()
        client.post = AsyncMock(
            return_value=make_response(503, {"code": -1, "msg": "Service Unavailable"})
        )
        key = await BinanceWSManager.create_listen_key(
            client, "api_key", "https://fapi.binance.com"
        )
        assert key is None

    async def test_no_api_key_returns_none(self) -> None:
        client = MagicMock()
        client.post = AsyncMock()
        key = await BinanceWSManager.create_listen_key(
            client, "", "https://fapi.binance.com"
        )
        assert key is None
        # Empty api_key short-circuits without REST call
        client.post.assert_not_called()

    async def test_exception_returns_none(self) -> None:
        client = MagicMock()
        client.post = AsyncMock(side_effect=httpx.ConnectError("no route"))
        key = await BinanceWSManager.create_listen_key(
            client, "api_key", "https://fapi.binance.com"
        )
        assert key is None

    async def test_response_missing_listen_key_field(self, make_response) -> None:
        client = MagicMock()
        client.post = AsyncMock(return_value=make_response(200, {"unrelated": 1}))
        key = await BinanceWSManager.create_listen_key(
            client, "k", "https://fapi.binance.com"
        )
        assert key is None  # data.get("listenKey") returns None


# ---------------------------------------------------------------------------
# keepalive_listen_key
# ---------------------------------------------------------------------------


class TestKeepaliveListenKey:
    async def test_keepalive_happy_path(self, make_response) -> None:
        client = MagicMock()
        client.put = AsyncMock(return_value=make_response(200, {}))
        ok = await BinanceWSManager.keepalive_listen_key(
            client, "api_key", "LK_ABC", "https://fapi.binance.com"
        )
        assert ok is True
        call_args = client.put.call_args
        assert call_args.args[0] == "https://fapi.binance.com/fapi/v1/listenKey"
        assert call_args.kwargs["headers"] == {"X-MBX-APIKEY": "api_key"}
        assert call_args.kwargs["params"] == {"listenKey": "LK_ABC"}

    async def test_keepalive_http_error_returns_false(self, make_response) -> None:
        client = MagicMock()
        client.put = AsyncMock(return_value=make_response(401, {"code": -2014}))
        ok = await BinanceWSManager.keepalive_listen_key(
            client, "api_key", "LK_BAD", "https://fapi.binance.com"
        )
        assert ok is False

    async def test_keepalive_exception_returns_false(self) -> None:
        client = MagicMock()
        client.put = AsyncMock(side_effect=httpx.ReadTimeout("timeout"))
        ok = await BinanceWSManager.keepalive_listen_key(
            client, "api_key", "LK_ABC", "https://fapi.binance.com"
        )
        assert ok is False


# ---------------------------------------------------------------------------
# run_combined_stream — reconnect / stop_event
# ---------------------------------------------------------------------------


class _FakeWSContext:
    """Mimic websockets.connect() async context manager."""

    def __init__(self, messages: list[str], raise_after: Exception | None = None) -> None:
        self._messages = messages
        self._raise_after = raise_after

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def __aiter__(self):
        async def gen():
            for m in self._messages:
                yield m
            if self._raise_after is not None:
                raise self._raise_after

        return gen()


class TestRunCombinedStream:
    async def test_stop_event_set_breaks_loop(self) -> None:
        stop = asyncio.Event()
        stop.set()  # already set -> loop must exit immediately

        async def cb(_):
            raise AssertionError("on_message must not fire when stop is preset")

        # Should return without trying to connect
        await BinanceWSManager().run_combined_stream(
            streams=["btcusdt@bookTicker"],
            on_message=cb,
            stop_event=stop,
        )

    async def test_empty_streams_yields_to_loop(self) -> None:
        stop = asyncio.Event()

        async def stop_after_brief() -> None:
            await asyncio.sleep(0.05)
            stop.set()

        # streams=[] -> goes through `await asyncio.sleep(1.0)` branch; we cancel via stop
        task = asyncio.create_task(
            BinanceWSManager().run_combined_stream(
                streams=[],
                on_message=lambda d: None,
                stop_event=stop,
            )
        )
        await stop_after_brief()
        await asyncio.wait_for(task, timeout=2.0)

    async def test_dispatches_messages_through_on_message(self) -> None:
        stop = asyncio.Event()
        received: list[dict] = []

        def on_message(data: dict) -> None:
            received.append(data)
            if len(received) >= 2:
                stop.set()

        # Two messages on the wire — second sets stop
        ctx = _FakeWSContext(
            ['{"data":{"e":"bookTicker","s":"BTCUSDT"}}',
             '{"data":{"e":"bookTicker","s":"ETHUSDT"}}'],
        )

        # Patch the websockets module that ws_manager imports lazily
        import sys
        fake_ws = MagicMock()
        fake_ws.connect = MagicMock(return_value=ctx)

        class _CCErr(Exception):
            pass

        class _CCOk(Exception):
            pass

        fake_exc = MagicMock()
        fake_exc.ConnectionClosedError = _CCErr
        fake_exc.ConnectionClosedOK = _CCOk
        _orig_ws4 = sys.modules.get("websockets")
        _orig_exc4 = sys.modules.get("websockets.exceptions")
        sys.modules["websockets"] = fake_ws
        sys.modules["websockets.exceptions"] = fake_exc

        try:
            await asyncio.wait_for(
                BinanceWSManager().run_combined_stream(
                    streams=["btcusdt@bookTicker"],
                    on_message=on_message,
                    stop_event=stop,
                ),
                timeout=2.0,
            )
        finally:
            if _orig_ws4 is not None:
                sys.modules["websockets"] = _orig_ws4
            else:
                sys.modules.pop("websockets", None)
            if _orig_exc4 is not None:
                sys.modules["websockets.exceptions"] = _orig_exc4
            else:
                sys.modules.pop("websockets.exceptions", None)

        assert len(received) == 2
        assert received[0]["s"] == "BTCUSDT"
        assert received[1]["s"] == "ETHUSDT"

    async def test_websockets_import_error_returns_cleanly(self) -> None:
        """If websockets package import fails the loop logs and returns
        without raising. We simulate this by stashing a fake module that
        raises ImportError on attribute access."""
        import sys

        class _BadModule:
            def __getattr__(self, name):
                raise ImportError("simulated missing dep")

        # Force the import inside run_combined_stream to fail
        _orig_ws5 = sys.modules.get("websockets")
        _orig_exc5 = sys.modules.get("websockets.exceptions")
        sys.modules.pop("websockets", None)
        sys.modules.pop("websockets.exceptions", None)
        sys.modules["websockets"] = _BadModule()  # type: ignore[assignment]

        try:
            stop = asyncio.Event()
            await asyncio.wait_for(
                BinanceWSManager().run_combined_stream(
                    streams=["btcusdt@bookTicker"],
                    on_message=lambda _: None,
                    stop_event=stop,
                    max_attempts=1,
                ),
                timeout=2.0,
            )
        finally:
            if _orig_ws5 is not None:
                sys.modules["websockets"] = _orig_ws5
            else:
                sys.modules.pop("websockets", None)
            if _orig_exc5 is not None:
                sys.modules["websockets.exceptions"] = _orig_exc5
            else:
                sys.modules.pop("websockets.exceptions", None)


# ---------------------------------------------------------------------------
# run_user_stream — reconnect after disconnect; clear listen_key
# ---------------------------------------------------------------------------


class TestRunUserStream:
    async def test_no_listen_key_breaks(self) -> None:
        stop = asyncio.Event()
        get_lk = AsyncMock(return_value=None)
        on_msg = MagicMock()

        await BinanceWSManager().run_user_stream(
            get_listen_key=get_lk,
            on_message=on_msg,
            stop_event=stop,
        )

        on_msg.assert_not_called()
        get_lk.assert_called()  # was queried at least once

    async def test_user_stream_websockets_import_error_returns_cleanly(self) -> None:
        """If websockets package import fails inside run_user_stream the
        loop logs and returns. The fake-listen-key callable is queried
        once to enter the loop body."""
        import sys

        class _BadModule:
            def __getattr__(self, name):
                raise ImportError("simulated missing dep")

        _orig_ws6 = sys.modules.get("websockets")
        _orig_exc6 = sys.modules.get("websockets.exceptions")
        sys.modules.pop("websockets", None)
        sys.modules.pop("websockets.exceptions", None)
        sys.modules["websockets"] = _BadModule()  # type: ignore[assignment]

        stop = asyncio.Event()
        get_lk = AsyncMock(return_value="LK_ABC")
        on_msg = MagicMock()

        try:
            await asyncio.wait_for(
                BinanceWSManager().run_user_stream(
                    get_listen_key=get_lk,
                    on_message=on_msg,
                    stop_event=stop,
                    clear_listen_key_on_disconnect=MagicMock(),
                ),
                timeout=2.0,
            )
        finally:
            if _orig_ws6 is not None:
                sys.modules["websockets"] = _orig_ws6
            else:
                sys.modules.pop("websockets", None)
            if _orig_exc6 is not None:
                sys.modules["websockets.exceptions"] = _orig_exc6
            else:
                sys.modules.pop("websockets.exceptions", None)

        # ImportError aborts before any message dispatch
        on_msg.assert_not_called()
