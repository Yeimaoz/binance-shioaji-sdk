"""
binance_sdk/_internal/ws_manager.py — Binance WebSocket protocol-level plumbing
================================================================================

抽自 broker_binance.py（PR-1 of Binance SDK mirror design）。

提供 WS 連線層共用工具：
  - create_listen_key / keepalive_listen_key：listenKey REST 互動
  - connect_combined_stream：通用「連 combined stream → loop messages → 自動重連」框架
  - LISTEN_KEY_KEEPALIVE_INTERVAL / WS_RECONNECT_BASE / WS_RECONNECT_MAX：reconnect 常數

設計原則：
  1. 不持有 callback dict — 由 caller（broker_binance.BinanceAdapter）保留 callback 清單
  2. 透過 dependency injection 拿 BinanceRestClient / stop_event
  3. message handler 透過 callback 注入，本 module 不解析 payload
  4. listenKey REST 請求繞過 BinanceRestClient.post 的 retry（保留原 broker_binance 行為）
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants（從 broker_binance.py 搬遷）
# ---------------------------------------------------------------------------

# Reconnect backoff for WS
WS_RECONNECT_BASE = 1.0
WS_RECONNECT_MAX = 60.0

# listenKey keepalive interval（Binance 要求每 < 60 分鐘 PUT 一次，取 30 分鐘安全邊距）
LISTEN_KEY_KEEPALIVE_INTERVAL = 30 * 60  # seconds

# Valid kline intervals（Binance USDM 支援清單，避免打錯送到交易所）
VALID_KLINE_INTERVALS = frozenset([
    "1m", "3m", "5m", "15m", "30m",
    "1h", "2h", "4h", "6h", "8h", "12h",
    "1d", "3d", "1w", "1M",
])


# ---------------------------------------------------------------------------
# BinanceWSManager
# ---------------------------------------------------------------------------


class BinanceWSManager:
    """Binance WebSocket protocol-level helper（無狀態 utilities）。

    本 class 不持有 callback dict — caller（broker_binance.BinanceAdapter）保留
    自己的 callback registry，本 class 只提供：
      1. listenKey REST 互動（create / keepalive）
      2. 通用 combined stream 連線迴圈框架（reconnect / backoff / stop signal）

    使用方式：
        ws_mgr = BinanceWSManager(base_url="wss://fstream.binance.com")
        listen_key = await ws_mgr.create_listen_key(rest_client)
        await ws_mgr.run_combined_stream(
            streams=["btcusdt@bookTicker", "ethusdt@bookTicker"],
            on_message=adapter._dispatch_book_ticker,
            stop_event=adapter._ws_stop,
        )
    """

    def __init__(self, base_url: str = "wss://fstream.binance.com") -> None:
        self.base_url = base_url

    # ── listenKey REST 互動 ───────────────────────────────────────────────

    @staticmethod
    async def create_listen_key(
        client: Any,  # httpx.AsyncClient
        api_key: str,
        rest_base_url: str,
    ) -> str | None:
        """POST /fapi/v1/listenKey 取得新的 listenKey。

        注意：直接走 httpx.AsyncClient（繞過 BinanceRestClient.post 的 retry），
        以保留原 broker_binance 行為（單次嘗試 + 失敗回 None + log warning）。
        """
        if not api_key:
            return None
        url = rest_base_url + "/fapi/v1/listenKey"
        headers = {"X-MBX-APIKEY": api_key}
        try:
            resp = await client.post(url, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                return data.get("listenKey")
            logger.warning("[BinanceWSManager] POST /fapi/v1/listenKey -> HTTP %d", resp.status_code)
        except Exception as exc:
            logger.error("[BinanceWSManager] 取得 listenKey 失敗: %s", exc)
        return None

    @staticmethod
    async def keepalive_listen_key(
        client: Any,  # httpx.AsyncClient
        api_key: str,
        listen_key: str,
        rest_base_url: str,
    ) -> bool:
        """PUT /fapi/v1/listenKey 延長 listenKey 有效期。回傳 True 成功 / False 失敗。"""
        try:
            resp = await client.put(
                rest_base_url + "/fapi/v1/listenKey",
                headers={"X-MBX-APIKEY": api_key},
                params={"listenKey": listen_key},
            )
            if resp.status_code == 200:
                logger.debug("[BinanceWSManager] listenKey keepalive OK")
                return True
            logger.warning("[BinanceWSManager] listenKey keepalive HTTP %d", resp.status_code)
        except Exception as exc:
            logger.warning("[BinanceWSManager] listenKey keepalive 失敗: %s", exc)
        return False

    # ── 通用 combined stream 連線迴圈 ─────────────────────────────────────

    async def run_combined_stream(
        self,
        streams: list[str],
        on_message: Callable[[dict], None | Awaitable[None]],
        stop_event: asyncio.Event,
        *,
        log_prefix: str = "[BinanceWSManager]",
        reconnect_max: float = WS_RECONNECT_MAX,
        max_attempts: int | None = None,
    ) -> None:
        """通用 Binance combined stream 接收迴圈。

        - 連 wss://fstream.binance.com/stream?streams=<stream1>/<stream2>/...
        - 收到 message 解 json，把 data 部分傳給 on_message
        - 心跳由 websockets 庫 ping_interval=30s 處理
        - 斷線指數退避重連，stop_event.set() 後跳出
        - max_attempts: None=無限重連；正整數=超過後停止（subscribe_kline 用 5）

        Args:
            streams      : Binance stream 名稱清單，e.g. ["btcusdt@bookTicker"]
            on_message   : 每筆 message 的 data dict 呼叫，可 sync 或 async
            stop_event   : 外部 stop signal
            log_prefix   : log 標題
            reconnect_max: 重連退避上限（秒）
            max_attempts : 重連次數上限（None=無限）
        """
        try:
            import websockets
            from websockets.exceptions import ConnectionClosedError, ConnectionClosedOK
        except ImportError:
            logger.error("%s websockets 套件未安裝", log_prefix)
            return

        attempt = 0
        import inspect
        is_coro = inspect.iscoroutinefunction(on_message)

        while not stop_event.is_set():
            if not streams:
                await asyncio.sleep(1.0)
                continue

            url = f"{self.base_url.rstrip('/')}/stream?streams={'/'.join(streams)}"
            logger.info("%s WS 連接: %d streams (base=%s)", log_prefix, len(streams), self.base_url)

            try:
                async with websockets.connect(
                    url,
                    ping_interval=30,
                    ping_timeout=10,
                    close_timeout=5,
                ) as ws:
                    attempt = 0
                    logger.info("%s WS 已連接", log_prefix)
                    async for raw in ws:
                        if stop_event.is_set():
                            break
                        try:
                            msg = json.loads(raw)
                            data = msg.get("data", msg)
                            if is_coro:
                                await on_message(data)
                            else:
                                on_message(data)
                        except (json.JSONDecodeError, KeyError):
                            pass

            except (ConnectionClosedOK,):
                if stop_event.is_set():
                    break
            except (ConnectionClosedError, OSError, Exception) as exc:
                logger.warning("%s WS 斷線（attempt %d）: %s", log_prefix, attempt, exc)

            if stop_event.is_set():
                break

            if max_attempts is not None and attempt >= max_attempts:
                logger.warning("%s 重連次數達上限 %d，停止", log_prefix, max_attempts)
                break

            delay = min(WS_RECONNECT_BASE * (2 ** attempt), reconnect_max)
            logger.info("%s WS %.1fs 後重連", log_prefix, delay)
            try:
                await asyncio.wait_for(asyncio.shield(stop_event.wait()), timeout=delay)
            except asyncio.TimeoutError:
                pass
            attempt += 1

        logger.info("%s WS task 結束", log_prefix)

    async def run_user_stream(
        self,
        get_listen_key: Callable[[], Awaitable[str | None]],
        on_message: Callable[[dict], None],
        stop_event: asyncio.Event,
        *,
        log_prefix: str = "[BinanceWSManager]",
        clear_listen_key_on_disconnect: Callable[[], None] | None = None,
    ) -> None:
        """User data stream 接收迴圈（特別處理：斷線後 listenKey 失效，需重取）。

        Args:
            get_listen_key : async callable 取 listenKey；本 manager 不知 listenKey 從哪來
            on_message     : 每筆 raw message dict 呼叫
            stop_event     : 外部 stop signal
            log_prefix     : log 標題
            clear_listen_key_on_disconnect: 斷線時清掉 caller 端 listenKey 快取
        """
        try:
            import websockets
            from websockets.exceptions import ConnectionClosedError, ConnectionClosedOK
        except ImportError:
            logger.error("%s websockets 未安裝", log_prefix)
            return

        attempt = 0
        while not stop_event.is_set():
            listen_key = await get_listen_key()
            if not listen_key:
                logger.error("%s 無法取得 listenKey，停止重連", log_prefix)
                break

            url = f"{self.base_url.rstrip('/')}/ws/{listen_key}"
            logger.info("%s WS 連接 (attempt %d, base=%s)", log_prefix, attempt, self.base_url)

            try:
                async with websockets.connect(
                    url,
                    ping_interval=30,
                    ping_timeout=10,
                    close_timeout=5,
                ) as ws:
                    attempt = 0
                    logger.info("%s WS 已連接", log_prefix)
                    async for raw in ws:
                        if stop_event.is_set():
                            break
                        try:
                            msg = json.loads(raw)
                            on_message(msg)
                        except (json.JSONDecodeError, KeyError):
                            pass

            except (ConnectionClosedOK,):
                if stop_event.is_set():
                    break
            except (ConnectionClosedError, OSError, Exception) as exc:
                logger.warning("%s WS 斷線（attempt %d）: %s", log_prefix, attempt, exc)
                # 斷線後 listenKey 可能失效，清掉讓下次重新取
                if clear_listen_key_on_disconnect is not None:
                    clear_listen_key_on_disconnect()

            if stop_event.is_set():
                break
            delay = min(WS_RECONNECT_BASE * (2 ** attempt), WS_RECONNECT_MAX)
            logger.info("%s WS %.1fs 後重連", log_prefix, delay)
            try:
                await asyncio.wait_for(asyncio.shield(stop_event.wait()), timeout=delay)
            except asyncio.TimeoutError:
                pass
            attempt += 1

        logger.info("%s WS task 結束", log_prefix)
