"""
binance_sdk/_internal/rest_client.py — Binance REST protocol-level plumbing
===========================================================================

抽自 broker_binance.py（PR-1 of Binance SDK mirror design）：
  - _TokenBucket：weight-based rate limiter（2400 weight / 60s）
  - sign_request：HMAC-SHA256 簽名（純 function，無 side effect）
  - BinanceRestClient：httpx.AsyncClient + 4 種 request method（get / post / put / delete）
    - 業務錯誤（4xx）：不重試，回傳 {"error": ..., "detail": ...}
    - 網路錯誤（httpx.HTTPError / ReadTimeout / OSError）：最多重試 3 次，指數退避

Public API stability：本 module 為 _internal，不對外公開。
broker_binance.py 仍 re-export _TokenBucket / _sign（method）/ _get / _post / _delete，
全部委派給 BinanceRestClient instance。

設計原則：
  1. 與 BinanceAdapter 解耦 — 不知道 ContractSpec / Position / OrderAck
  2. 透過 dependency injection 拿 api_key / api_secret，不自己 load env
  3. timestamp / signature 計算純粹 stateless（time.time() + HMAC）
  4. retry 策略硬編碼（3 attempts, exp backoff），不暴露 config
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import time
from typing import Any
from urllib.parse import urlencode

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants（從 broker_binance.py 搬遷）
# ---------------------------------------------------------------------------
_WEIGHT_LIMIT_PER_MIN = 2400
_ENDPOINT_WEIGHTS: dict[str, int] = {
    "/fapi/v1/premiumIndex": 1,
    "/fapi/v2/premiumIndex": 1,
    "/fapi/v1/ticker/price": 1,
    "/fapi/v2/balance": 5,
    "/fapi/v2/account": 5,
    "/fapi/v2/positionRisk": 5,
    "/fapi/v1/order": 1,
    "/fapi/v1/allOpenOrders": 1,
    # R4 endpoints
    "/fapi/v1/listenKey": 1,
    "/fapi/v1/openInterest": 1,
    "/fapi/v1/fundingRate": 1,
}


# ---------------------------------------------------------------------------
# Token Bucket（rate limit 主動管理）
# ---------------------------------------------------------------------------


class _TokenBucket:
    """Weight-based token bucket for Binance rate limiting.

    capacity       : 2400 weight per 60s window
    window_seconds : rolling window length in seconds
    """

    def __init__(self, capacity: int = _WEIGHT_LIMIT_PER_MIN, window_seconds: float = 60.0) -> None:
        self.capacity = capacity
        self.window_seconds = window_seconds
        self._tokens: float = float(capacity)
        self._last_refill = time.monotonic()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        refill = (elapsed / self.window_seconds) * self.capacity
        self._tokens = min(self.capacity, self._tokens + refill)
        self._last_refill = now

    async def consume(self, weight: int = 1) -> None:
        """Consume weight tokens; sleep if insufficient."""
        while True:
            self._refill()
            if self._tokens >= weight:
                self._tokens -= weight
                return
            # Need to wait for refill
            deficit = weight - self._tokens
            wait_secs = (deficit / self.capacity) * self.window_seconds
            logger.debug("[TokenBucket] Rate limit: wait %.2fs for %d weight", wait_secs, weight)
            await asyncio.sleep(wait_secs)


# ---------------------------------------------------------------------------
# HMAC-SHA256 簽名
# ---------------------------------------------------------------------------


def sign_request(secret_key: str, params: dict) -> dict:
    """Binance HMAC-SHA256 簽名（純 function，無 side effect）。

    回傳新 dict（含 timestamp 與 signature），不修改原 params。

    Args:
        secret_key: Binance API secret
        params    : 原始 query params

    Returns:
        新 dict，含原 params + timestamp + signature

    Raises:
        ValueError: secret_key 為 None / 空字串
    """
    if not secret_key:
        raise ValueError("[BinanceRestClient] api_secret 未設定，無法簽名。")
    signed = dict(params)
    signed["timestamp"] = int(time.time() * 1000)
    query_string = urlencode(signed)
    signature = hmac.new(
        secret_key.encode("utf-8"),
        query_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    signed["signature"] = signature
    return signed


# ---------------------------------------------------------------------------
# BinanceRestClient
# ---------------------------------------------------------------------------


class BinanceRestClient:
    """Binance USDM Futures REST protocol-level client。

    封裝：
      - httpx.AsyncClient 生命週期
      - Token bucket rate limiting
      - HMAC-SHA256 簽名
      - 4xx 不重試 / 網路錯誤指數退避重試 3 次

    使用方式：
        client = BinanceRestClient(base_url="https://fapi.binance.com",
                                   api_key="...", api_secret="...")
        await client.connect()  # or 直接 use（lazy via _ensure_client）
        data = await client.get("/fapi/v1/premiumIndex", params={"symbol": "BTCUSDT"})
        await client.close()
    """

    def __init__(
        self,
        base_url: str,
        api_key: str | None = None,
        secret_key: str | None = None,
        timeout: float = 10.0,
    ) -> None:
        self.base_url = base_url
        self.api_key = api_key
        self.secret_key = secret_key
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None
        self._bucket = _TokenBucket()

    # ── Lifecycle ─────────────────────────────────────────────────────────

    async def connect(self) -> None:
        """建立 httpx.AsyncClient。冪等：已連線時呼叫不拋錯。"""
        if self._client is not None:
            return
        self._client = httpx.AsyncClient(timeout=self.timeout)

    async def close(self) -> None:
        """關閉 httpx.AsyncClient。冪等：未連線時呼叫不拋錯。"""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError(
                "[BinanceRestClient] 未連線，請先呼叫 connect() 或讓 BinanceAdapter 管理。"
            )
        return self._client

    # ── Sign helper（thin wrapper to standalone function）────────────────

    def sign(self, params: dict) -> dict:
        """委派給 standalone sign_request()；保留為 method 以利測試 patch。"""
        return sign_request(self.secret_key or "", params)

    # ── HTTP methods ─────────────────────────────────────────────────────

    async def get(
        self,
        path: str,
        params: dict | None = None,
        signed: bool = False,
        weight: int = 1,
    ) -> Any:
        """
        GET request with rate limit + retry.

        業務錯誤（4xx）：不重試，回傳 {"error": str, "detail": ...}
        網路錯誤（httpx.HTTPError / ReadTimeout / OSError）：最多重試 3 次，指數退避
        """
        client = self._ensure_client()
        url = self.base_url + path
        params = params or {}
        headers: dict[str, str] = {}

        if signed:
            if not self.api_key:
                logger.warning("[BinanceRestClient] api_key 未設定，跳過 signed GET: %s", path)
                return {"error": "api_key not set", "path": path}
            params = self.sign(params)
            headers["X-MBX-APIKEY"] = self.api_key

        effective_weight = _ENDPOINT_WEIGHTS.get(path, weight)
        await self._bucket.consume(effective_weight)

        for attempt in range(3):
            try:
                resp = await client.get(url, params=params, headers=headers)
                if resp.status_code >= 400:
                    body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
                    logger.warning("[BinanceRestClient] GET %s -> HTTP %d: %s", path, resp.status_code, body)
                    return {"error": f"HTTP {resp.status_code}", "detail": body}
                return resp.json()
            except (httpx.HTTPError, httpx.ReadTimeout, OSError) as exc:
                wait = 2 ** attempt
                logger.warning(
                    "[BinanceRestClient] GET %s 網路錯誤（attempt %d/3）: %s，%.1fs 後重試",
                    path, attempt + 1, exc, wait,
                )
                if attempt < 2:
                    await asyncio.sleep(wait)
            except Exception as exc:
                logger.error("[BinanceRestClient] GET %s 未預期錯誤: %s", path, exc)
                return {"error": str(exc)}

        return {"error": f"GET {path} 重試 3 次均失敗"}

    async def post(
        self,
        path: str,
        params: dict | None = None,
        signed: bool = False,
        weight: int = 1,
    ) -> Any:
        """POST request with rate limit + retry（邏輯同 get）。"""
        client = self._ensure_client()
        url = self.base_url + path
        params = params or {}
        headers: dict[str, str] = {}

        if signed:
            if not self.api_key:
                logger.warning("[BinanceRestClient] api_key 未設定，跳過 signed POST: %s", path)
                return {"error": "api_key not set", "path": path}
            params = self.sign(params)
            headers["X-MBX-APIKEY"] = self.api_key

        effective_weight = _ENDPOINT_WEIGHTS.get(path, weight)
        await self._bucket.consume(effective_weight)

        for attempt in range(3):
            try:
                resp = await client.post(url, params=params, headers=headers)
                if resp.status_code >= 400:
                    body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
                    logger.warning("[BinanceRestClient] POST %s -> HTTP %d: %s", path, resp.status_code, body)
                    return {"error": f"HTTP {resp.status_code}", "detail": body}
                return resp.json()
            except (httpx.HTTPError, httpx.ReadTimeout, OSError) as exc:
                wait = 2 ** attempt
                logger.warning(
                    "[BinanceRestClient] POST %s 網路錯誤（attempt %d/3）: %s，%.1fs 後重試",
                    path, attempt + 1, exc, wait,
                )
                if attempt < 2:
                    await asyncio.sleep(wait)
            except Exception as exc:
                logger.error("[BinanceRestClient] POST %s 未預期錯誤: %s", path, exc)
                return {"error": str(exc)}

        return {"error": f"POST {path} 重試 3 次均失敗"}

    async def delete(
        self,
        path: str,
        params: dict | None = None,
        signed: bool = False,
        weight: int = 1,
    ) -> Any:
        """DELETE request（cancel order）."""
        client = self._ensure_client()
        url = self.base_url + path
        params = params or {}
        headers: dict[str, str] = {}

        if signed:
            if not self.api_key:
                return {"error": "api_key not set", "path": path}
            params = self.sign(params)
            headers["X-MBX-APIKEY"] = self.api_key

        await self._bucket.consume(_ENDPOINT_WEIGHTS.get(path, weight))

        try:
            resp = await client.delete(url, params=params, headers=headers)
            if resp.status_code >= 400:
                body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
                return {"error": f"HTTP {resp.status_code}", "detail": body}
            return resp.json()
        except Exception as exc:
            return {"error": str(exc)}
