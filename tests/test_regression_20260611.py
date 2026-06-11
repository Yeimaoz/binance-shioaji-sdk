"""Regression tests for code-review-20260611 fixes.

Finding 1: executed_qty truncated to int for fractional crypto
Finding 2: POST retry reuses stale signature, risks duplicate orders
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest


# ---------------------------------------------------------------------------
# Fakes / helpers (copied from test_order.py to keep tests DAMP)
# ---------------------------------------------------------------------------


class _FakeContract:
    def __init__(self, symbol: str = "BTCUSDT") -> None:
        self.symbol = symbol


class _FakeRest:
    """Minimal async REST stub. Records every call; response queue per (method, path)."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self._responses: dict[tuple[str, str], list[Any]] = {}

    def queue(self, method: str, path: str, *responses: Any) -> None:
        self._responses.setdefault((method.upper(), path), []).extend(responses)

    def _next(self, method: str, path: str) -> Any:
        bucket = self._responses.get((method, path), [])
        if not bucket:
            raise AssertionError(f"No response queued for {method} {path}")
        return bucket.pop(0)

    async def get(self, path: str, params: dict | None = None, signed: bool = False, weight: int = 1) -> Any:
        self.calls.append({"method": "GET", "path": path, "params": params, "signed": signed})
        return self._next("GET", path)

    async def post(self, path: str, params: dict | None = None, signed: bool = False, weight: int = 1, idempotent: bool = True) -> Any:
        self.calls.append({"method": "POST", "path": path, "params": params, "signed": signed})
        return self._next("POST", path)

    async def delete(self, path: str, params: dict | None = None, signed: bool = False, weight: int = 1) -> Any:
        self.calls.append({"method": "DELETE", "path": path, "params": params, "signed": signed})
        return self._next("DELETE", path)


def _make_rest_client(api_key: str = "k", secret_key: str = "s"):
    from binance_shioaji_sdk._internal import BinanceRestClient
    return BinanceRestClient(
        base_url="https://testnet.binancefuture.com",
        api_key=api_key,
        secret_key=secret_key,
    )


# ---------------------------------------------------------------------------
# Finding 1: executedQty truncated to int for fractional crypto
# incident: code-review-20260611-finding-1
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_place_order_executed_qty_btc_fractional_not_truncated() -> None:
    """BTC fill of 0.001 BTC must survive as Decimal, not be truncated to 0.

    incident: code-review-20260611-finding-1
    """
    # Arrange
    from binance_shioaji_sdk.order import Order, place_order_via

    rest = _FakeRest()
    rest.queue(
        "POST",
        "/fapi/v1/order",
        {
            "orderId": 101,
            "clientOrderId": "btc-frac",
            "status": "FILLED",
            "avgPrice": "65000.0",
            "executedQty": "0.001",  # fractional BTC — previously truncated to 0
        },
    )
    order = Order(price=65000.0, quantity=Decimal("0.001"), action="long", price_type="LMT")

    # Act
    resp = await place_order_via(rest, _FakeContract("BTCUSDT"), order)

    # Assert — must NOT be 0 (the regression)
    assert resp.filled_quantity != 0, (
        "filled_quantity was 0 — executedQty '0.001' got truncated (int cast bug)"
    )
    assert resp.filled_quantity == Decimal("0.001"), (
        f"Expected Decimal('0.001'), got {resp.filled_quantity!r}"
    )


@pytest.mark.asyncio
async def test_place_order_executed_qty_eth_fractional_not_truncated() -> None:
    """ETH fill of 0.01 ETH must survive as Decimal.

    incident: code-review-20260611-finding-1
    """
    from binance_shioaji_sdk.order import Order, place_order_via

    rest = _FakeRest()
    rest.queue(
        "POST",
        "/fapi/v1/order",
        {
            "orderId": 202,
            "clientOrderId": "eth-frac",
            "status": "FILLED",
            "avgPrice": "3500.0",
            "executedQty": "0.01",
        },
    )
    order = Order(price=3500.0, quantity=Decimal("0.01"), action="long", price_type="LMT")
    resp = await place_order_via(rest, _FakeContract("ETHUSDT"), order)

    assert resp.filled_quantity == Decimal("0.01"), (
        f"Expected Decimal('0.01'), got {resp.filled_quantity!r}"
    )


@pytest.mark.asyncio
async def test_list_trades_via_executed_qty_fractional_not_truncated() -> None:
    """list_trades_via must also preserve fractional executedQty as Decimal.

    incident: code-review-20260611-finding-1
    """
    from binance_shioaji_sdk.order import list_trades_via

    rest = _FakeRest()
    rest.queue(
        "GET",
        "/fapi/v1/allOrders",
        [
            {
                "orderId": 301,
                "clientOrderId": "c1",
                "symbol": "BTCUSDT",
                "status": "FILLED",
                "avgPrice": "64000.0",
                "executedQty": "0.001",
            },
        ],
    )
    out = await list_trades_via(rest, "BTC")

    assert len(out) == 1
    assert out[0].filled_quantity != 0, (
        "filled_quantity was 0 — list_trades_via executedQty '0.001' got truncated"
    )
    assert out[0].filled_quantity == Decimal("0.001"), (
        f"Expected Decimal('0.001'), got {out[0].filled_quantity!r}"
    )


def test_order_response_filled_quantity_type_is_decimal() -> None:
    """OrderResponse.filled_quantity default must be Decimal, not int.

    incident: code-review-20260611-finding-1
    """
    from binance_shioaji_sdk.order import OrderResponse

    resp = OrderResponse(
        order_id="1",
        client_order_id="c",
        symbol="BTCUSDT",
        status="FILLED",
    )
    assert isinstance(resp.filled_quantity, Decimal), (
        f"Expected Decimal default, got {type(resp.filled_quantity).__name__}"
    )
    assert resp.filled_quantity == Decimal("0")


def test_binance_trade_status_deal_quantity_type_is_decimal() -> None:
    """BinanceTradeStatus.deal_quantity must accept Decimal (not truncate to int).

    incident: code-review-20260611-finding-1
    """
    from binance_shioaji_sdk.trade import BinanceTradeStatus, BinanceOrderStatusEnum

    status = BinanceTradeStatus(
        id="42",
        status=BinanceOrderStatusEnum.Filled,
        status_code="FILLED",
        order_datetime="2026-06-11T00:00:00Z",
        deal_quantity=Decimal("0.001"),
    )
    assert status.deal_quantity == Decimal("0.001"), (
        f"Expected Decimal('0.001'), got {status.deal_quantity!r}"
    )
    # Must not be silently truncated
    assert status.deal_quantity != 0


# ---------------------------------------------------------------------------
# Finding 2: POST retry reuses stale signature
# incident: code-review-20260611-finding-2
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_retry_uses_fresh_timestamp_on_each_attempt() -> None:
    """On network-error retry, each attempt must call sign() again with a fresh timestamp.

    Stale signature risk: if timestamp is fixed outside the retry loop,
    retries share the same timestamp+signature and may cause duplicate orders.

    incident: code-review-20260611-finding-2
    """
    from unittest.mock import MagicMock

    client = _make_rest_client()
    await client.connect()

    sign_call_count = 0
    timestamps_seen: list[int] = []
    original_sign = client.sign

    def tracking_sign(params: dict) -> dict:
        nonlocal sign_call_count
        sign_call_count += 1
        result = original_sign(params)
        timestamps_seen.append(result["timestamp"])
        return result

    client.sign = tracking_sign  # type: ignore[method-assign]

    # First two attempts: network error; third: success
    ok_resp = MagicMock(spec=httpx.Response)
    ok_resp.status_code = 200
    ok_resp.json.return_value = {"orderId": 99}
    ok_resp.headers = {"content-type": "application/json"}

    call_count = 0

    async def side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise httpx.ReadTimeout("timeout")
        return ok_resp

    with patch.object(client._client, "post", side_effect=side_effect), \
         patch("asyncio.sleep", new_callable=AsyncMock):
        await client.post("/fapi/v1/order", params={"symbol": "BTCUSDT"}, signed=True)

    # sign() must have been called once per attempt (3 calls for 3 attempts)
    assert sign_call_count == 3, (
        f"sign() called {sign_call_count} times — expected 3 (once per retry attempt). "
        "Stale signature bug: sign() was called only once before the loop."
    )
    await client.close()


@pytest.mark.asyncio
async def test_post_idempotent_false_does_not_retry_on_network_error() -> None:
    """When idempotent=False, a network error must raise immediately (no retry).

    Non-idempotent operations (e.g. /fapi/v1/order) must not silently
    retry on network error — that risks duplicate orders.

    incident: code-review-20260611-finding-2
    """
    client = _make_rest_client()
    await client.connect()

    call_count = 0

    async def always_timeout(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        raise httpx.ReadTimeout("timeout")

    with patch.object(client._client, "post", side_effect=always_timeout), \
         patch("asyncio.sleep", new_callable=AsyncMock):
        with pytest.raises(httpx.ReadTimeout):
            await client.post(
                "/fapi/v1/order",
                params={"symbol": "BTCUSDT"},
                signed=True,
                idempotent=False,
            )

    # Must NOT retry — only 1 call
    assert call_count == 1, (
        f"post(idempotent=False) made {call_count} HTTP call(s) — "
        "expected exactly 1 (no retry for non-idempotent operation)"
    )
    await client.close()


@pytest.mark.asyncio
async def test_post_idempotent_true_still_retries_on_network_error() -> None:
    """When idempotent=True (default), network errors should still retry as before.

    incident: code-review-20260611-finding-2
    """
    client = _make_rest_client()
    await client.connect()

    with patch.object(
        client._client,
        "post",
        new_callable=AsyncMock,
        side_effect=httpx.ReadTimeout("timeout"),
    ) as mock_post, patch("asyncio.sleep", new_callable=AsyncMock):
        result = await client.post("/fapi/v1/order", signed=True, idempotent=True)

    assert "error" in result
    # With idempotent=True, should retry 3 times total
    assert mock_post.call_count == 3, (
        f"Expected 3 retry attempts with idempotent=True, got {mock_post.call_count}"
    )
    await client.close()


@pytest.mark.asyncio
async def test_place_order_via_passes_idempotent_false_to_post() -> None:
    """place_order_via must call rest_client.post with idempotent=False.

    This ensures the order endpoint never retries on network error.
    incident: code-review-20260611-finding-2
    """
    # We test via a fake rest that records the idempotent kwarg
    from binance_shioaji_sdk.order import Order, place_order_via

    idempotent_values: list[bool | None] = []

    class _RecordingRest:
        async def post(self, path: str, params: dict | None = None, signed: bool = False,
                       weight: int = 1, idempotent: bool = True) -> Any:
            idempotent_values.append(idempotent)
            return {
                "orderId": 1,
                "clientOrderId": "x",
                "status": "FILLED",
                "avgPrice": "50000",
                "executedQty": "1",
            }

    order = Order(price=50000.0, quantity=Decimal("1"), action="long", price_type="LMT")
    await place_order_via(_RecordingRest(), _FakeContract("BTCUSDT"), order)

    assert len(idempotent_values) == 1
    assert idempotent_values[0] is False, (
        f"place_order_via passed idempotent={idempotent_values[0]!r} — "
        "expected False to prevent duplicate-order retry"
    )
