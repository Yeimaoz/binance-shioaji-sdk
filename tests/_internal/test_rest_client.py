"""Tests for binance_shioaji_sdk._internal.rest_client.

Covers sign_request (HMAC-SHA256), BinanceRestClient HTTP methods (GET/POST/DELETE),
and _TokenBucket rate-limiting. Mirrors an upstream adapter test suite
TestSign / TestHttpMethods / TestTokenBucket migrated to SDK internals.
"""
from __future__ import annotations

import hashlib
import hmac
import time
from unittest.mock import AsyncMock, patch
from urllib.parse import urlencode

import httpx
import pytest

from binance_shioaji_sdk._internal import (
    BinanceRestClient,
    _ENDPOINT_WEIGHTS,
    _TokenBucket,
    _WEIGHT_LIMIT_PER_MIN,
    sign_request,
)


# ---------------------------------------------------------------------------
# Smoke / public surface
# ---------------------------------------------------------------------------


def test_public_top_level_imports() -> None:
    # v0.4.0: ExecutionReport / OrderResponse removed from static imports
    # (still accessible via __getattr__ DeprecationWarning hook — see test_deprecation.py)
    from binance_shioaji_sdk import (
        BinanceAccount,
        Binance,
        BinanceContract,
        BinanceFillReport,
        BinanceTrade,
        Contracts,
        MarketInfo,
        Order,
        Quote,
        __version__,
    )

    assert __version__.startswith("0.")
    for cls in (Binance, BinanceAccount, BinanceContract, Contracts,
                Order, BinanceTrade, Quote, MarketInfo, BinanceFillReport):
        assert cls is not None


def test_internal_imports() -> None:
    assert _WEIGHT_LIMIT_PER_MIN == 2400
    assert isinstance(_ENDPOINT_WEIGHTS, dict)
    assert BinanceRestClient is not None
    assert _TokenBucket is not None
    assert callable(sign_request)


def test_fill_report_dataclass() -> None:
    """v0.4.0: ExecutionReport renamed to BinanceFillReport (H-1 exemption — fields verbatim)."""
    from binance_shioaji_sdk import BinanceFillReport

    rpt = BinanceFillReport(
        order_id="123",
        symbol="BTCUSDT",
        status="FILLED",
        side="BUY",
        order_type="MARKET",
        qty=1.0,
        filled_qty=1.0,
        last_filled_price=50000.0,
        avg_price=50000.0,
    )
    assert rpt.order_id == "123"
    assert rpt.raw == {}


# ---------------------------------------------------------------------------
# sign_request (was BinanceAdapter._sign in the parent project)
# ---------------------------------------------------------------------------


class TestSignRequest:
    def test_adds_timestamp_and_signature(self) -> None:
        params = {"symbol": "BTCUSDT", "quantity": "0.001"}
        signed = sign_request("secret123", params)
        assert "timestamp" in signed
        assert "signature" in signed
        assert len(signed["signature"]) == 64  # SHA256 hex = 64 chars

    def test_signature_correct_hmac(self) -> None:
        params = {"symbol": "BTCUSDT"}
        signed = sign_request("my_secret", params)
        query = urlencode({k: v for k, v in signed.items() if k != "signature"})
        expected = hmac.new(b"my_secret", query.encode(), hashlib.sha256).hexdigest()
        assert signed["signature"] == expected

    def test_sign_does_not_mutate_original(self) -> None:
        original = {"symbol": "BTCUSDT"}
        signed = sign_request("s", original)
        assert "timestamp" not in original
        assert "signature" not in original
        assert "timestamp" in signed

    def test_sign_raises_without_secret(self) -> None:
        with pytest.raises(ValueError, match="api_secret"):
            sign_request("", {"symbol": "BTCUSDT"})

    def test_sign_raises_with_none_secret(self) -> None:
        # type: ignore[arg-type]
        with pytest.raises(ValueError):
            sign_request(None, {"symbol": "BTCUSDT"})  # type: ignore[arg-type]

    def test_pure_function_format(self) -> None:
        out = sign_request("test_secret", {"symbol": "BTCUSDT"})
        assert all(c in "0123456789abcdef" for c in out["signature"])
        assert isinstance(out["timestamp"], int)


# ---------------------------------------------------------------------------
# BinanceRestClient HTTP methods
# ---------------------------------------------------------------------------


def _make_client(api_key: str = "test_key", secret_key: str = "test_secret") -> BinanceRestClient:
    return BinanceRestClient(
        base_url="https://testnet.binancefuture.com",
        api_key=api_key,
        secret_key=secret_key,
    )


class TestGet:
    async def test_get_public_happy_path(self, make_response) -> None:
        client = _make_client()
        await client.connect()
        mock_resp = make_response(200, {"lastFundingRate": "0.0001"})
        with patch.object(client._client, "get", new_callable=AsyncMock, return_value=mock_resp):
            result = await client.get("/fapi/v1/premiumIndex", params={"symbol": "BTCUSDT"})
        assert result["lastFundingRate"] == "0.0001"
        await client.close()

    async def test_get_signed_adds_api_key_header(self, make_response) -> None:
        client = _make_client()
        await client.connect()
        mock_resp = make_response(200, [{"asset": "USDT", "balance": "100"}])
        with patch.object(
            client._client, "get", new_callable=AsyncMock, return_value=mock_resp
        ) as mock_get:
            await client.get("/fapi/v2/balance", signed=True)
        call_kwargs = mock_get.call_args.kwargs
        assert call_kwargs["headers"].get("X-MBX-APIKEY") == "test_key"
        await client.close()

    async def test_get_4xx_returns_error_no_retry(self, make_response) -> None:
        client = _make_client()
        await client.connect()
        mock_resp = make_response(400, {"code": -1121, "msg": "Invalid symbol"})
        with patch.object(
            client._client, "get", new_callable=AsyncMock, return_value=mock_resp
        ) as mock_get:
            result = await client.get("/fapi/v1/premiumIndex", params={"symbol": "INVALID"})
        assert "error" in result
        assert mock_get.call_count == 1  # no retry on 4xx

    async def test_get_network_error_retries_3_times(self) -> None:
        client = _make_client()
        await client.connect()
        with patch.object(
            client._client,
            "get",
            new_callable=AsyncMock,
            side_effect=httpx.ReadTimeout("timeout"),
        ) as mock_get, patch("asyncio.sleep", new_callable=AsyncMock):
            result = await client.get("/fapi/v1/premiumIndex")
        assert "error" in result
        assert mock_get.call_count == 3

    async def test_get_2_errors_then_success(self, make_response) -> None:
        client = _make_client()
        await client.connect()
        ok_resp = make_response(200, {"price": "50000"})
        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise httpx.ReadTimeout("timeout")
            return ok_resp

        with patch.object(client._client, "get", side_effect=side_effect), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            result = await client.get("/fapi/v1/premiumIndex")
        assert result == {"price": "50000"}
        assert call_count == 3

    async def test_get_no_api_key_signed_returns_error(self) -> None:
        client = BinanceRestClient(base_url="https://x", api_key=None, secret_key="s")
        await client.connect()
        result = await client.get("/fapi/v2/balance", signed=True)
        assert "error" in result
        await client.close()


class TestPost:
    async def test_post_happy_path(self, make_response) -> None:
        client = _make_client()
        await client.connect()
        order_resp = {"orderId": 99999, "status": "NEW", "avgPrice": "0"}
        mock_resp = make_response(200, order_resp)
        with patch.object(client._client, "post", new_callable=AsyncMock, return_value=mock_resp):
            result = await client.post(
                "/fapi/v1/order", params={"symbol": "BTCUSDT"}, signed=True
            )
        assert result["orderId"] == 99999
        await client.close()

    async def test_post_4xx_no_retry(self, make_response) -> None:
        client = _make_client()
        await client.connect()
        mock_resp = make_response(400, {"code": -2019, "msg": "Margin insufficient"})
        with patch.object(
            client._client, "post", new_callable=AsyncMock, return_value=mock_resp
        ) as mock_post:
            result = await client.post("/fapi/v1/order", params={}, signed=True)
        assert "error" in result
        assert mock_post.call_count == 1
        await client.close()

    async def test_post_signed_adds_api_key_header(self, make_response) -> None:
        client = _make_client()
        await client.connect()
        mock_resp = make_response(200, {"orderId": 1})
        with patch.object(
            client._client, "post", new_callable=AsyncMock, return_value=mock_resp
        ) as mock_post:
            await client.post("/fapi/v1/order", params={"symbol": "BTCUSDT"}, signed=True)
        assert mock_post.call_args.kwargs["headers"].get("X-MBX-APIKEY") == "test_key"
        await client.close()

    async def test_post_network_error_retries_3_times(self) -> None:
        client = _make_client()
        await client.connect()
        with patch.object(
            client._client,
            "post",
            new_callable=AsyncMock,
            side_effect=httpx.ReadTimeout("timeout"),
        ) as mock_post, patch("asyncio.sleep", new_callable=AsyncMock):
            result = await client.post("/fapi/v1/order", signed=True)
        assert "error" in result
        assert mock_post.call_count == 3


class TestDelete:
    async def test_delete_happy_path(self, make_response) -> None:
        client = _make_client()
        await client.connect()
        cancel_resp = {"orderId": 888, "status": "CANCELED"}
        mock_resp = make_response(200, cancel_resp)
        with patch.object(client._client, "delete", new_callable=AsyncMock, return_value=mock_resp):
            result = await client.delete(
                "/fapi/v1/order", params={"symbol": "BTCUSDT", "orderId": 888}, signed=True
            )
        assert result["status"] == "CANCELED"
        await client.close()

    async def test_delete_4xx_returns_error(self, make_response) -> None:
        client = _make_client()
        await client.connect()
        mock_resp = make_response(400, {"code": -2011, "msg": "Unknown order"})
        with patch.object(client._client, "delete", new_callable=AsyncMock, return_value=mock_resp):
            result = await client.delete(
                "/fapi/v1/order", params={"symbol": "BTCUSDT", "orderId": 1}, signed=True
            )
        assert "error" in result
        await client.close()

    async def test_delete_no_api_key_signed_returns_error(self) -> None:
        client = BinanceRestClient(base_url="https://x", api_key=None, secret_key="s")
        await client.connect()
        result = await client.delete("/fapi/v1/order", signed=True)
        assert "error" in result
        await client.close()


class TestLifecycle:
    async def test_connect_idempotent(self) -> None:
        client = _make_client()
        await client.connect()
        client_id = id(client._client)
        await client.connect()  # second call no-op
        assert id(client._client) == client_id
        await client.close()

    async def test_close_idempotent(self) -> None:
        client = _make_client()
        await client.connect()
        await client.close()
        await client.close()  # should not raise
        assert client._client is None

    async def test_get_without_connect_raises(self) -> None:
        client = _make_client()
        with pytest.raises(RuntimeError):
            await client.get("/fapi/v1/premiumIndex")

    def test_sign_method_delegates(self) -> None:
        client = _make_client(secret_key="s")
        out = client.sign({"symbol": "BTCUSDT"})
        assert "signature" in out
        assert "timestamp" in out


# ---------------------------------------------------------------------------
# _TokenBucket
# ---------------------------------------------------------------------------


class TestTokenBucket:
    def test_initial_capacity(self) -> None:
        bucket = _TokenBucket(capacity=100, window_seconds=10.0)
        assert bucket.capacity == 100
        assert bucket._tokens == 100.0

    async def test_consume_does_not_block_when_full(self) -> None:
        bucket = _TokenBucket(capacity=100, window_seconds=60.0)
        start = time.monotonic()
        await bucket.consume(1)
        elapsed = time.monotonic() - start
        assert elapsed < 0.5

    async def test_consume_blocks_when_empty(self) -> None:
        bucket = _TokenBucket(capacity=5, window_seconds=60.0)
        await bucket.consume(5)  # drain
        slept: list[float] = []

        async def fake_sleep(secs: float) -> None:
            slept.append(secs)
            bucket._tokens = 5  # manually refill to break loop

        with patch("asyncio.sleep", side_effect=fake_sleep):
            await bucket.consume(1)
        assert len(slept) >= 1

    async def test_rate_limiter_applied_in_get(self, make_response) -> None:
        client = _make_client()
        await client.connect()
        consumed: list[int] = []

        async def tracking_consume(weight: int = 1) -> None:
            consumed.append(weight)
            client._bucket._tokens = client._bucket.capacity

        client._bucket.consume = tracking_consume  # type: ignore[method-assign]
        mock_resp = make_response(200, {"lastFundingRate": "0.0001"})
        with patch.object(client._client, "get", new_callable=AsyncMock, return_value=mock_resp):
            await client.get("/fapi/v1/premiumIndex")
        assert len(consumed) == 1
        # premiumIndex is in the endpoint-weight map (weight 1)
        assert consumed[0] == _ENDPOINT_WEIGHTS["/fapi/v1/premiumIndex"]
        await client.close()

    async def test_endpoint_weight_lookup_overrides_default(self, make_response) -> None:
        client = _make_client()
        await client.connect()
        consumed: list[int] = []

        async def tracking_consume(weight: int = 1) -> None:
            consumed.append(weight)
            client._bucket._tokens = client._bucket.capacity

        client._bucket.consume = tracking_consume  # type: ignore[method-assign]
        mock_resp = make_response(200, [])
        with patch.object(client._client, "get", new_callable=AsyncMock, return_value=mock_resp):
            await client.get("/fapi/v2/balance", signed=True, weight=99)
        # /fapi/v2/balance is registered with weight 5, overrides caller weight=99
        assert consumed == [_ENDPOINT_WEIGHTS["/fapi/v2/balance"]]
