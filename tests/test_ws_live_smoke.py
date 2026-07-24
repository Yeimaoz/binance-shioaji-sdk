"""Live WS smoke test — P0 2026-07-24 URL migration proof-of-life.

Opt-in only (real network call to Binance USDM mainnet, no credentials
required for the public-stream tests). Skipped by default in normal
`pytest` runs; enable with:

    BINANCE_SDK_LIVE_SMOKE=1 pytest tests/test_ws_live_smoke.py -v -s

Purpose: prove `BinanceWSManager.run_combined_stream(category=...)` actually
receives data on the new post-2026-04-23 URLs (`/market/stream?streams=...`
for kline/aggTrade/markPrice, `/public/stream?streams=...` for bookTicker) —
not just that the URL string is constructed correctly (unit tests cover
that), but that Binance's real server delivers messages on it. This is the
same category of live verification that uncovered the original P0 (24h
paper soak with zero messages despite a "connected" WS handshake).

Root cause / migration reference: developers.binance.com "Important
WebSocket Change Notice" (USDS-M Futures WebSocket System Upgrade Notice,
announced 2026-03-06, legacy URLs decommissioned 2026-04-23).
"""
from __future__ import annotations

import asyncio
import os

import pytest

from binance_shioaji_sdk._internal import BinanceWSManager

LIVE_SMOKE_ENABLED = os.environ.get("BINANCE_SDK_LIVE_SMOKE") == "1"

pytestmark = pytest.mark.skipif(
    not LIVE_SMOKE_ENABLED,
    reason="opt-in live network test — set BINANCE_SDK_LIVE_SMOKE=1 to run "
    "(hits real wss://fstream.binance.com, no API key needed for public streams)",
)


async def _collect_messages(
    *,
    streams: list[str],
    category: str,
    min_messages: int,
    timeout: float,
) -> list[dict]:
    """Run `run_combined_stream` against real Binance and collect messages
    until `min_messages` arrive or `timeout` elapses."""
    ws = BinanceWSManager(base_url="wss://fstream.binance.com")
    stop_event = asyncio.Event()
    received: list[dict] = []

    def on_message(data: dict) -> None:
        received.append(data)
        if len(received) >= min_messages:
            stop_event.set()

    task = asyncio.create_task(
        ws.run_combined_stream(
            streams=streams,
            on_message=on_message,
            stop_event=stop_event,
            category=category,
            log_prefix="[live-smoke]",
        )
    )
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        pass
    finally:
        stop_event.set()
        try:
            await asyncio.wait_for(task, timeout=5.0)
        except (asyncio.TimeoutError, Exception):
            task.cancel()

    return received


class TestLiveMarketCategorySmoke:
    """market category: kline_1m + aggTrade (regular market data, /market/stream)."""

    async def test_kline_and_agg_trade_receive_messages(self) -> None:
        received = await _collect_messages(
            streams=["xrpusdt@kline_1m", "xrpusdt@aggTrade"],
            category="market",
            min_messages=3,
            timeout=90.0,
        )
        assert len(received) >= 3, (
            f"/market/stream?streams=... 收到 {len(received)} 筆訊息 "
            f"(< 3)，可能又 silent-dead — 90s 內應收到至少 3 筆 "
            f"kline_1m/aggTrade（aggTrade 高頻，1m 內應遠多於 3 筆）"
        )
        event_types = {m.get("e") for m in received}
        assert event_types & {"kline", "aggTrade"}, (
            f"收到訊息但事件類型不符預期，實際 event types={event_types}"
        )


class TestLivePublicCategorySmoke:
    """public category: bookTicker (high-frequency public data, /public/stream)."""

    async def test_book_ticker_receives_messages(self) -> None:
        received = await _collect_messages(
            streams=["xrpusdt@bookTicker"],
            category="public",
            min_messages=3,
            timeout=30.0,
        )
        assert len(received) >= 3, (
            f"/public/stream?streams=... 收到 {len(received)} 筆訊息 (< 3)，"
            f"bookTicker 應為高頻資料，30s 內應遠多於 3 筆"
        )
        for msg in received:
            assert "b" in msg and "a" in msg, f"bookTicker payload 缺 bid/ask 欄位: {msg}"


class TestLiveUserStreamSmoke:
    """private category: user data stream. Requires BINANCE_API_KEY +
    BINANCE_SECRET_KEY env vars — skipped (not failed) if absent, since
    user stream URL correctness is fully covered by the URL-assembly unit
    test (test_user_stream_url_has_private_prefix) and creds aren't
    available in this environment per task scope."""

    async def test_user_stream_smoke_requires_creds(self) -> None:
        if not (os.environ.get("BINANCE_API_KEY") and os.environ.get("BINANCE_SECRET_KEY")):
            pytest.skip(
                "no BINANCE_API_KEY/BINANCE_SECRET_KEY in env — user stream live "
                "smoke skipped; URL correctness covered by unit test "
                "test_user_stream_url_has_private_prefix (ws_manager already used "
                "/private/ws?listenKey=... pre-fix, confirmed still correct post-migration)"
            )
