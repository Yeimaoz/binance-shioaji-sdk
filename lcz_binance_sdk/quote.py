"""
lcz_binance_sdk/quote.py - Quote namespace (WS multiplexing)
============================================================

Mirrors shioaji `sj.quote.subscribe(contract, quote_type, callback)` shape.

A `Quote` instance lives on `BinanceClient.quote` (wired in by follow-up PR)
and multiplexes four logical WS channels through one combined-stream task per
channel type:

    quote_type='tick' or 'mark_price'  ->  <symbol>@markPrice  (WS task 1)
    quote_type='bookticker'            ->  <symbol>@bookTicker (WS task 2)
    quote_type='kline_1m' / 'kline_5m' / ...  ->  <symbol>@kline_<iv> (WS task 3)
    user data stream                   ->  ws://<listenKey>    (WS task 4)

Logic adapted from lcz-sentinel `python/lib/broker_binance.py`
(`subscribe_tick` / `subscribe_book_ticker` / `subscribe_kline` /
`subscribe_user_stream` / `wait_fill` / `_handle_execution_report`).
"""
from __future__ import annotations

import asyncio
import inspect
import logging
from typing import TYPE_CHECKING, Any, Callable

from lcz_binance_sdk._internal import (
    BinanceWSManager,
    ExecutionReport,
    LISTEN_KEY_KEEPALIVE_INTERVAL,
    VALID_KLINE_INTERVALS,
)

if TYPE_CHECKING:
    from lcz_binance_sdk.client import BinanceClient
    from lcz_binance_sdk.contracts import BinanceContract

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalize_symbol(raw: str) -> str:
    sym = raw.upper()
    if not sym.endswith("USDT"):
        sym += "USDT"
    return sym


def _kline_interval(quote_type: str) -> str | None:
    """Return the Binance interval suffix for a 'kline_<iv>' quote_type, else None."""
    if not quote_type.startswith("kline_"):
        return None
    return quote_type.split("_", 1)[1]


# ---------------------------------------------------------------------------
# Quote namespace
# ---------------------------------------------------------------------------


class Quote:
    """Binance quote namespace, mirrors shioaji `sj.quote`.

    Attach via `BinanceClient.quote = Quote(self)` (wire-in deferred).

    Public surface:
        set_on_tick_callback(cb)        -- global tick callback (parity with shioaji)
        await subscribe(contract, qtype, cb)
        await unsubscribe(contract, qtype)
        await subscribe_user_stream(cb)
        await wait_fill(order_id, timeout=30.0) -> ExecutionReport | None

    Internal state (one map per WS channel):
        _tick_callbacks       : symbol -> list[cb(symbol, mark_price, ts_ns)]
        _book_ticker_callbacks: symbol -> list[cb(symbol, bid, ask, bid_qty, ask_qty)]
        _kline_callbacks      : (symbol, interval) -> cb(bar_dict)
        _user_stream_callbacks: list[cb(ExecutionReport)]
        _execution_reports    : order_id -> latest ExecutionReport (terminal cache)
        _fill_events          : order_id -> asyncio.Event (wait_fill rendezvous)
    """

    def __init__(self, client: "BinanceClient") -> None:
        self._client = client

        # Per-channel callback registries
        self._tick_callbacks: dict[str, list[Callable[..., Any]]] = {}
        self._book_ticker_callbacks: dict[str, list[Callable[..., Any]]] = {}
        self._kline_callbacks: dict[tuple[str, str], Callable[..., Any]] = {}
        self._user_stream_callbacks: list[Callable[[ExecutionReport], Any]] = []

        # Optional global tick callback (parity with shioaji set_on_tick_*)
        self._global_tick_callback: Callable[..., Any] | None = None

        # WS task handles
        self._mark_task: asyncio.Task[None] | None = None
        self._book_task: asyncio.Task[None] | None = None
        self._kline_task: asyncio.Task[None] | None = None
        self._user_stream_task: asyncio.Task[None] | None = None
        self._listen_key_task: asyncio.Task[None] | None = None

        # Stop signal shared by all WS loops
        self._stop_event: asyncio.Event = asyncio.Event()

        # User stream / wait_fill plumbing
        self._listen_key: str | None = None
        self._execution_reports: dict[str, ExecutionReport] = {}
        self._fill_events: dict[str, asyncio.Event] = {}

        # Lazy-import websockets manager — 從 client 拿 ws base URL（mainnet vs testnet）
        ws_base = getattr(client, "_ws_base_url", None) or "wss://fstream.binance.com"
        self._ws_manager = BinanceWSManager(base_url=ws_base)

    # ── Public API ────────────────────────────────────────────────────────

    def set_on_tick_callback(self, callback: Callable[..., Any]) -> None:
        """Register a global tick callback fired on every mark_price / book_ticker event.

        Mirrors shioaji `set_on_tick_fop_v1`. Independent of per-symbol
        `subscribe(...)` callbacks — both fire when applicable.
        """
        self._global_tick_callback = callback

    async def subscribe(
        self,
        contract: "BinanceContract",
        quote_type: str,
        callback: Callable[..., Any],
    ) -> None:
        """Subscribe to a market data channel for one contract.

        quote_type
        ----------
        'tick' or 'mark_price' : starts/joins markPrice combined stream
        'bookticker'           : starts/joins bookTicker combined stream
        'kline_<iv>'           : starts/joins kline combined stream (iv in
                                 VALID_KLINE_INTERVALS, e.g. 'kline_1m')
        """
        sym = _normalize_symbol(contract.symbol)

        if quote_type in ("tick", "mark_price"):
            self._tick_callbacks.setdefault(sym, []).append(callback)
            await self._ensure_mark_price_task()
        elif quote_type == "bookticker":
            self._book_ticker_callbacks.setdefault(sym, []).append(callback)
            await self._ensure_book_ticker_task()
        elif (iv := _kline_interval(quote_type)) is not None:
            if iv not in VALID_KLINE_INTERVALS:
                raise ValueError(
                    f"[Quote] kline interval {iv!r} not supported. "
                    f"Valid: {sorted(VALID_KLINE_INTERVALS)}"
                )
            self._kline_callbacks[(sym, iv)] = callback
            await self._ensure_kline_task()
        else:
            raise ValueError(
                f"[Quote] quote_type {quote_type!r} not supported. "
                f"Valid: 'tick', 'mark_price', 'bookticker', 'kline_<iv>'"
            )

    async def unsubscribe(
        self,
        contract: "BinanceContract",
        quote_type: str,
    ) -> None:
        """Drop callbacks for (symbol, quote_type). WS task keeps running for
        other subscribers; restarting the combined stream is deferred to a
        future PR (idle-cleanup is acceptable for v0.1)."""
        sym = _normalize_symbol(contract.symbol)
        if quote_type in ("tick", "mark_price"):
            self._tick_callbacks.pop(sym, None)
        elif quote_type == "bookticker":
            self._book_ticker_callbacks.pop(sym, None)
        elif (iv := _kline_interval(quote_type)) is not None:
            self._kline_callbacks.pop((sym, iv), None)

    async def subscribe_user_stream(
        self,
        callback: Callable[[ExecutionReport], Any],
    ) -> None:
        """Subscribe to userDataStream (order events). Requires api_key."""
        api_key = getattr(self._client, "api_key", None)
        if not api_key:
            logger.warning("[Quote] subscribe_user_stream: api_key not set, skip")
            return

        self._user_stream_callbacks.append(callback)

        if self._user_stream_task and not self._user_stream_task.done():
            return

        listen_key = await self._create_listen_key()
        if not listen_key:
            logger.error("[Quote] cannot acquire listenKey, userDataStream not started")
            return
        self._listen_key = listen_key

        self._user_stream_task = asyncio.create_task(self._run_user_stream())
        self._listen_key_task = asyncio.create_task(self._run_listen_key_keepalive())

    async def wait_fill(
        self,
        order_id: str,
        timeout: float = 30.0,
    ) -> ExecutionReport | None:
        """Block until `order_id` reaches a terminal state (FILLED/CANCELED/EXPIRED).

        Returns the terminal `ExecutionReport`, or None on timeout. Requires
        `subscribe_user_stream(...)` to be active.
        """
        cached = self._execution_reports.get(order_id)
        if cached and cached.status in {"FILLED", "CANCELED", "EXPIRED"}:
            return cached

        event = self._fill_events.setdefault(order_id, asyncio.Event())
        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning(
                "[Quote] wait_fill timeout (order_id=%s, timeout=%.1fs)", order_id, timeout
            )
            return None

        result = self._execution_reports.get(order_id)
        self._fill_events.pop(order_id, None)
        return result

    # ── Lifecycle ─────────────────────────────────────────────────────────

    async def stop(self) -> None:
        """Signal all WS loops to terminate. Idempotent."""
        self._stop_event.set()
        for task in (
            self._mark_task,
            self._book_task,
            self._kline_task,
            self._user_stream_task,
            self._listen_key_task,
        ):
            if task is not None and not task.done():
                try:
                    await asyncio.wait_for(task, timeout=2.0)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    task.cancel()

    # ── Mark-price WS ─────────────────────────────────────────────────────

    async def _ensure_mark_price_task(self) -> None:
        if self._mark_task and not self._mark_task.done():
            # task already running — symbol set will be picked up on reconnect
            await self._restart_mark_task()
            return
        self._mark_task = asyncio.create_task(self._run_mark_price_loop())

    async def _restart_mark_task(self) -> None:
        if self._mark_task is not None and not self._mark_task.done():
            self._mark_task.cancel()
            try:
                await self._mark_task
            except (asyncio.CancelledError, Exception):
                pass
        self._mark_task = asyncio.create_task(self._run_mark_price_loop())

    async def _run_mark_price_loop(self) -> None:
        streams = [f"{sym.lower()}@markPrice" for sym in self._tick_callbacks]
        if not streams:
            return
        await self._ws_manager.run_combined_stream(
            streams=streams,
            on_message=self._dispatch_mark_price,
            stop_event=self._stop_event,
            log_prefix="[Quote.mark_price]",
        )

    def _dispatch_mark_price(self, data: dict) -> None:
        if data.get("e") != "markPriceUpdate":
            return
        sym = data.get("s", "")
        try:
            mark_price = float(data.get("p", "0"))
        except (TypeError, ValueError):
            return
        if mark_price <= 0:
            return
        ts_ns = int(data.get("E", 0)) * 1_000_000  # event time ms -> ns

        for cb in self._tick_callbacks.get(sym, []):
            try:
                cb(sym, mark_price, ts_ns)
            except Exception as exc:
                logger.warning("[Quote] tick callback error: %s", exc)
        if self._global_tick_callback is not None:
            try:
                self._global_tick_callback(sym, mark_price, ts_ns)
            except Exception as exc:
                logger.warning("[Quote] global tick callback error: %s", exc)

    # ── Book ticker WS ────────────────────────────────────────────────────

    async def _ensure_book_ticker_task(self) -> None:
        if self._book_task and not self._book_task.done():
            await self._restart_book_task()
            return
        self._book_task = asyncio.create_task(self._run_book_ticker_loop())

    async def _restart_book_task(self) -> None:
        if self._book_task is not None and not self._book_task.done():
            self._book_task.cancel()
            try:
                await self._book_task
            except (asyncio.CancelledError, Exception):
                pass
        self._book_task = asyncio.create_task(self._run_book_ticker_loop())

    async def _run_book_ticker_loop(self) -> None:
        streams = [f"{sym.lower()}@bookTicker" for sym in self._book_ticker_callbacks]
        if not streams:
            return
        await self._ws_manager.run_combined_stream(
            streams=streams,
            on_message=self._dispatch_book_ticker,
            stop_event=self._stop_event,
            log_prefix="[Quote.bookticker]",
        )

    def _dispatch_book_ticker(self, data: dict) -> None:
        if "b" not in data or "a" not in data:
            return
        sym = data.get("s", "")
        try:
            bid = float(data["b"])
            ask = float(data["a"])
            bid_qty = float(data.get("B", 0))
            ask_qty = float(data.get("A", 0))
        except (TypeError, ValueError, KeyError):
            return
        if bid <= 0 or ask <= 0:
            return

        for cb in self._book_ticker_callbacks.get(sym, []):
            try:
                cb(sym, bid, ask, bid_qty, ask_qty)
            except Exception as exc:
                logger.warning("[Quote] book_ticker callback error: %s", exc)

        if self._global_tick_callback is not None:
            mid = (bid + ask) / 2.0
            try:
                self._global_tick_callback(sym, mid, mid)
            except Exception as exc:
                logger.warning("[Quote] global tick callback error: %s", exc)

    # ── Kline WS ──────────────────────────────────────────────────────────

    async def _ensure_kline_task(self) -> None:
        if self._kline_task and not self._kline_task.done():
            await self._restart_kline_task()
            return
        self._kline_task = asyncio.create_task(self._run_kline_loop())

    async def _restart_kline_task(self) -> None:
        if self._kline_task is not None and not self._kline_task.done():
            self._kline_task.cancel()
            try:
                await self._kline_task
            except (asyncio.CancelledError, Exception):
                pass
        self._kline_task = asyncio.create_task(self._run_kline_loop())

    async def _run_kline_loop(self) -> None:
        streams = [f"{sym.lower()}@kline_{iv}" for (sym, iv) in self._kline_callbacks]
        if not streams:
            return
        await self._ws_manager.run_combined_stream(
            streams=streams,
            on_message=self._dispatch_kline,
            stop_event=self._stop_event,
            log_prefix="[Quote.kline]",
        )

    async def _dispatch_kline(self, data: dict) -> None:
        if data.get("e") != "kline":
            return
        k = data.get("k", {})
        is_closed = bool(k.get("x", False))
        if not is_closed:
            return
        sym = data.get("s", k.get("s", ""))
        interval = k.get("i", "")
        callback = self._kline_callbacks.get((sym, interval))
        if callback is None:
            return
        try:
            bar_dict = {
                "symbol": sym,
                "interval": interval,
                "time": int(k["t"]) // 1000,
                "open": float(k["o"]),
                "high": float(k["h"]),
                "low": float(k["l"]),
                "close": float(k["c"]),
                "volume": float(k["v"]),
                "closed": is_closed,
            }
        except (TypeError, ValueError, KeyError):
            return

        try:
            if inspect.iscoroutinefunction(callback):
                await callback(bar_dict)
            else:
                callback(bar_dict)
        except Exception as exc:
            logger.warning("[Quote] kline callback error: %s", exc)

    # ── User stream + listenKey ───────────────────────────────────────────

    async def _create_listen_key(self) -> str | None:
        api_key = getattr(self._client, "api_key", None)
        rest = self._get_rest_inner_httpx()
        if not api_key or rest is None:
            return None
        base_url: str = (
            getattr(self._client, "_base_url", None)
            or getattr(self._client, "base_url", "")
            or ""
        )
        return await BinanceWSManager.create_listen_key(rest, api_key, base_url)

    def _get_rest_inner_httpx(self) -> Any | None:
        """Return the inner httpx.AsyncClient owned by the BinanceClient.

        BinanceClient (built by agent A) holds a `BinanceRestClient` exposing
        `._client` once `connect()` ran. We tolerate both
        `BinanceClient._rest` and `.rest` attribute names.
        """
        rest_client = getattr(self._client, "_rest", None) or getattr(
            self._client, "rest", None
        )
        if rest_client is None:
            return None
        return getattr(rest_client, "_client", None)

    async def _run_listen_key_keepalive(self) -> None:
        api_key = getattr(self._client, "api_key", None)
        if not api_key:
            return
        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(
                    asyncio.shield(self._stop_event.wait()),
                    timeout=LISTEN_KEY_KEEPALIVE_INTERVAL,
                )
                break
            except asyncio.TimeoutError:
                pass
            if not self._listen_key:
                break
            rest = self._get_rest_inner_httpx()
            if rest is None:
                break
            base_url: str = (
                getattr(self._client, "_base_url", None)
                or getattr(self._client, "base_url", "")
                or ""
            )
            await BinanceWSManager.keepalive_listen_key(
                rest, api_key, self._listen_key, base_url
            )

    async def _run_user_stream(self) -> None:
        async def _get_key() -> str | None:
            if self._listen_key:
                return self._listen_key
            new_key = await self._create_listen_key()
            self._listen_key = new_key
            return new_key

        def _clear() -> None:
            self._listen_key = None

        await self._ws_manager.run_user_stream(
            get_listen_key=_get_key,
            on_message=self._handle_user_event,
            stop_event=self._stop_event,
            log_prefix="[Quote.user_stream]",
            clear_listen_key_on_disconnect=_clear,
        )

    def _handle_user_event(self, msg: dict) -> None:
        if msg.get("e") != "executionReport":
            return
        try:
            order_id = str(msg["i"])
            report = ExecutionReport(
                order_id=order_id,
                symbol=msg.get("s", ""),
                status=msg.get("X", ""),
                side=msg.get("S", ""),
                order_type=msg.get("o", ""),
                qty=float(msg.get("q", 0) or 0),
                filled_qty=float(msg.get("z", 0) or 0),
                last_filled_price=float(msg.get("L", 0) or 0),
                avg_price=float(msg.get("ap", 0) or 0),
                raw=msg,
            )
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("[Quote] executionReport parse error: %s | msg=%s", exc, msg)
            return

        self._execution_reports[order_id] = report
        for cb in self._user_stream_callbacks:
            try:
                cb(report)
            except Exception as exc:
                logger.warning("[Quote] user_stream callback error: %s", exc)

        if report.status in {"FILLED", "CANCELED", "EXPIRED"}:
            event = self._fill_events.get(order_id)
            if event is not None:
                event.set()


__all__ = ["Quote"]
