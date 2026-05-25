"""Tests for binance_shioaji_sdk.client.Binance.

Covers: testnet base_url switching, login/logout state, placeholder
NotImplementedError surface, on_session_down hook assignability.

httpx + listenKey creation are mocked — no real network.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from binance_shioaji_sdk import BinanceAccount, Binance
from binance_shioaji_sdk.client import (
    BINANCE_FUTURES_BASE,
    BINANCE_FUTURES_TESTNET,
    BINANCE_WS_BASE,
    BINANCE_WS_TESTNET,
)


def test_testnet_flag_swaps_base_url() -> None:
    bn_test = Binance(testnet=True)
    bn_prod = Binance(testnet=False)
    assert bn_test.base_url == BINANCE_FUTURES_TESTNET
    assert "testnet" in bn_test.base_url
    assert bn_prod.base_url == BINANCE_FUTURES_BASE
    assert bn_test.ws_base_url == BINANCE_WS_TESTNET
    assert bn_prod.ws_base_url == BINANCE_WS_BASE


def test_is_connected_false_before_login() -> None:
    bn = Binance(testnet=True)
    assert bn.is_connected is False


@pytest.mark.asyncio
async def test_login_sets_connected_true_and_logout_resets() -> None:
    bn = Binance(testnet=True)

    with patch(
        "binance_shioaji_sdk.client.BinanceWSManager.create_listen_key",
        new=AsyncMock(return_value="fake_listen_key_xyz"),
    ), patch(
        "binance_shioaji_sdk._internal.rest_client.BinanceRestClient.connect",
        new=AsyncMock(return_value=None),
    ), patch(
        "binance_shioaji_sdk._internal.rest_client.BinanceRestClient._ensure_client",
        return_value=object(),
    ), patch(
        "binance_shioaji_sdk._internal.rest_client.BinanceRestClient.close",
        new=AsyncMock(return_value=None),
    ):
        assert bn.is_connected is False
        await bn.login("test_key", "test_secret")
        assert bn.is_connected is True
        assert bn.api_key == "test_key"
        assert bn.secret_key == "test_secret"
        # listen_key task should have been started
        assert bn._listen_key == "fake_listen_key_xyz"
        assert bn._listen_key_task is not None

        await bn.logout()
        assert bn.is_connected is False
        assert bn._listen_key is None


@pytest.mark.asyncio
async def test_login_rejects_empty_credentials() -> None:
    bn = Binance(testnet=True)
    with pytest.raises(ValueError):
        await bn.login("", "secret")
    with pytest.raises(ValueError):
        await bn.login("key", "")


@pytest.mark.asyncio
async def test_login_raises_auth_error_on_bad_credentials() -> None:
    """Bad keys cause listenKey 401 → BinanceAuthError propagates from login().

    Before fix: login() returned cleanly with is_connected=True even when
    credentials were rejected (silent half-connected state).
    """
    from binance_shioaji_sdk import BinanceAuthError

    bn = Binance(testnet=True)

    async def _raise_auth(*_args, **_kwargs):
        raise BinanceAuthError("POST /fapi/v1/listenKey HTTP 401 — credentials rejected by Binance")

    with patch(
        "binance_shioaji_sdk.client.BinanceWSManager.create_listen_key",
        new=AsyncMock(side_effect=_raise_auth),
    ), patch(
        "binance_shioaji_sdk._internal.rest_client.BinanceRestClient.connect",
        new=AsyncMock(return_value=None),
    ), patch(
        "binance_shioaji_sdk._internal.rest_client.BinanceRestClient._ensure_client",
        return_value=object(),
    ), patch(
        "binance_shioaji_sdk._internal.rest_client.BinanceRestClient.close",
        new=AsyncMock(return_value=None),
    ):
        with pytest.raises(BinanceAuthError, match="HTTP 401"):
            await bn.login("bad_key", "bad_secret")
        # Important: connected flag stays False; caller can retry with good keys
        assert bn.is_connected is False


@pytest.mark.asyncio
async def test_order_methods_require_login() -> None:
    """Wire-in: place_order/cancel_order/list_trades raise RuntimeError when not logged in."""
    bn = Binance(testnet=True)
    contract = bn.Contracts.Perp["BTCUSDT"]
    order = bn.Order(price=50000, quantity=1, action="long", price_type="LMT")
    with pytest.raises(RuntimeError, match="not logged in"):
        await bn.place_order(contract, order)
    with pytest.raises(RuntimeError, match="not logged in"):
        await bn.cancel_order("BTCUSDT", "123")
    with pytest.raises(RuntimeError, match="not logged in"):
        await bn.list_trades()


def test_quote_marketinfo_namespaces_wired() -> None:
    """Wire-in: quote / market_info / Order all live and callable from Binance."""
    bn = Binance(testnet=True)
    from binance_shioaji_sdk import MarketInfo, Order, Quote
    assert isinstance(bn.quote, Quote)
    assert isinstance(bn.market_info, MarketInfo)
    assert bn.Order is Order
    o = bn.Order(price=100, quantity=1, action="long", price_type="LMT")
    assert o.price == 100 and o.quantity == 1


def test_on_session_down_callback_assignable() -> None:
    bn = Binance(testnet=True)
    assert bn.on_session_down is None

    called: list[bool] = []

    def cb() -> None:
        called.append(True)

    bn.on_session_down = cb
    assert bn.on_session_down is cb
    bn.on_session_down()
    assert called == [True]


def test_futures_account_returns_binance_account() -> None:
    bn = Binance(testnet=True)
    acct = bn.futures_account
    assert isinstance(acct, BinanceAccount)
    assert acct.account_type == "futures"
    assert acct.client_ref is bn


# ---------------------------------------------------------------------------
# Task 13b: v0.4.0 method coverage — account_balance / margin / list_positions
# / place_order (incl. error classification).
#
# Tests bypass real login: set bn._connected = True + inject fake _rest.
# ---------------------------------------------------------------------------


class _FakeRest:
    """Queue-based fake REST client matching BinanceRestClient surface."""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self._responses: dict[tuple[str, str], list] = {}

    def queue(self, method: str, path: str, *responses) -> None:
        self._responses.setdefault((method.upper(), path), []).extend(responses)

    async def get(self, path: str, params=None, signed: bool = False, weight: int = 1):
        self.calls.append({"method": "GET", "path": path, "params": params, "signed": signed})
        return self._responses[("GET", path)].pop(0)


def _make_connected_bn(rest: _FakeRest) -> "Binance":
    """Construct a Binance instance + skip login, inject fake REST."""
    bn = Binance(testnet=True)
    bn._connected = True
    bn._rest = rest  # type: ignore[assignment]
    return bn


# ── account_balance ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_account_balance_returns_dataclass_from_usdt_entry():
    from binance_shioaji_sdk import BinanceAccountBalance
    rest = _FakeRest()
    rest.queue("GET", "/fapi/v2/balance", [
        {"asset": "BNB", "balance": "0.5"},
        {"asset": "USDT", "balance": "1234.56"},
    ])
    bn = _make_connected_bn(rest)
    out = await bn.account_balance()
    assert isinstance(out, BinanceAccountBalance)
    assert out.acc_balance == 1234.56
    assert out.status == "200"


@pytest.mark.asyncio
async def test_account_balance_raises_on_rest_error():
    from binance_shioaji_sdk import BinanceAccountError
    rest = _FakeRest()
    rest.queue("GET", "/fapi/v2/balance", {"error": "HTTP 500", "detail": "broker down"})
    bn = _make_connected_bn(rest)
    with pytest.raises(BinanceAccountError, match="REST failed"):
        await bn.account_balance()


@pytest.mark.asyncio
async def test_account_balance_raises_when_usdt_missing():
    from binance_shioaji_sdk import BinanceAccountError
    rest = _FakeRest()
    rest.queue("GET", "/fapi/v2/balance", [{"asset": "BTC", "balance": "1.0"}])
    bn = _make_connected_bn(rest)
    with pytest.raises(BinanceAccountError, match="USDT asset not found"):
        await bn.account_balance()


# ── margin (new method) ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_margin_returns_dataclass_from_account_endpoint():
    from binance_shioaji_sdk import BinanceMargin
    rest = _FakeRest()
    rest.queue("GET", "/fapi/v2/account", {
        "availableBalance": "500.0",
        "totalInitialMargin": "300.0",
        "totalMaintMargin": "100.0",
        "totalMarginBalance": "1000.0",
        "totalWalletBalance": "900.0",
    })
    bn = _make_connected_bn(rest)
    out = await bn.margin(bn.futures_account)
    assert isinstance(out, BinanceMargin)
    assert out.available_margin == 500.0
    assert out.initial_margin == 300.0
    assert out.maintenance_margin == 100.0
    assert out.equity == 1000.0
    assert out.equity_amount == 1000.0
    assert out.today_balance == 900.0
    assert out.yesterday_balance == 0.0  # Binance doesn't track
    assert out.status == "200"


@pytest.mark.asyncio
async def test_margin_raises_on_rest_error():
    from binance_shioaji_sdk import BinanceAccountError
    rest = _FakeRest()
    rest.queue("GET", "/fapi/v2/account", {"error": "HTTP 500"})
    bn = _make_connected_bn(rest)
    with pytest.raises(BinanceAccountError, match="REST failed"):
        await bn.margin(bn.futures_account)


@pytest.mark.asyncio
async def test_margin_rejects_non_futures_account():
    from binance_shioaji_sdk import BinanceAccount
    bn = _make_connected_bn(_FakeRest())
    spot_acct = BinanceAccount(account_type="spot", client_ref=bn)
    with pytest.raises(ValueError, match="only 'futures' supported"):
        await bn.margin(spot_acct)


# ── list_positions ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_positions_filters_zero_qty_and_uses_shioaji_vocab():
    """Zero-qty entries omitted (§3.2.2); direction Buy/Sell (shioaji vocab)."""
    from binance_shioaji_sdk import BinanceFuturePosition
    from decimal import Decimal
    rest = _FakeRest()
    rest.queue("GET", "/fapi/v2/positionRisk", [
        {"symbol": "BTCUSDT", "positionAmt": "0.5", "positionSide": "BOTH",
         "markPrice": "50000", "unRealizedProfit": "100", "entryPrice": "49000"},
        {"symbol": "ETHUSDT", "positionAmt": "-2.0", "positionSide": "BOTH",
         "markPrice": "3000", "unRealizedProfit": "-50", "entryPrice": "3025"},
        # zero-qty entries should be filtered:
        {"symbol": "BNBUSDT", "positionAmt": "0", "positionSide": "BOTH",
         "markPrice": "500", "unRealizedProfit": "0", "entryPrice": "0"},
    ])
    bn = _make_connected_bn(rest)
    out = await bn.list_positions(bn.futures_account)
    assert len(out) == 2  # zero-qty BNBUSDT filtered
    assert all(isinstance(p, BinanceFuturePosition) for p in out)
    btc = next(p for p in out if p.code == "BTCUSDT")
    eth = next(p for p in out if p.code == "ETHUSDT")
    assert btc.direction == "Buy"  # shioaji vocab not "long"
    assert eth.direction == "Sell"  # shioaji vocab not "short"
    from decimal import Decimal as D
    assert btc.quantity == D("0.5")
    assert eth.quantity == D("2.0")  # abs
    assert btc.id == "BTCUSDT_BOTH"


@pytest.mark.asyncio
async def test_list_positions_raises_on_rest_error():
    from binance_shioaji_sdk import BinanceAccountError
    rest = _FakeRest()
    rest.queue("GET", "/fapi/v2/positionRisk", {"error": "HTTP 500"})
    bn = _make_connected_bn(rest)
    with pytest.raises(BinanceAccountError, match="REST failed"):
        await bn.list_positions(bn.futures_account)


@pytest.mark.asyncio
async def test_list_positions_rejects_non_futures_account():
    from binance_shioaji_sdk import BinanceAccount
    bn = _make_connected_bn(_FakeRest())
    spot_acct = BinanceAccount(account_type="spot", client_ref=bn)
    with pytest.raises(ValueError, match="only 'futures' supported"):
        await bn.list_positions(spot_acct)


# ── place_order (success + error classification) ────────────────────────


@pytest.mark.asyncio
async def test_place_order_returns_binance_trade_on_success():
    from binance_shioaji_sdk import (
        BinanceTrade, BinanceTradeStatus, BinanceOrderStatusEnum,
    )
    from binance_shioaji_sdk.order import OrderResponse
    from unittest.mock import AsyncMock, patch
    bn = _make_connected_bn(_FakeRest())
    contract = bn.Contracts.Perp["BTCUSDT"]
    order = bn.Order(price=50000, quantity=1, action="long", price_type="LMT")
    fake_resp = OrderResponse(
        order_id="42", client_order_id="cid", symbol="BTCUSDT",
        status="NEW", filled_quantity=0, avg_filled_price=None,
        raw={"binance_orderId": 42},
    )
    with patch(
        "binance_shioaji_sdk.client.place_order_via",
        new=AsyncMock(return_value=fake_resp),
    ):
        trade = await bn.place_order(contract, order)
    assert isinstance(trade, BinanceTrade)
    assert isinstance(trade.status, BinanceTradeStatus)
    assert trade.status.id == "42"
    assert trade.status.status == BinanceOrderStatusEnum.Submitted
    assert trade.status.order_quantity == 1
    assert trade.status.modified_price == 0.0
    assert trade.contract is contract
    assert trade.order is order


@pytest.mark.asyncio
async def test_place_order_raises_auth_error_on_2014():
    """M-3: REJECTED with detail.code -2014 → BinanceAuthError."""
    from binance_shioaji_sdk import BinanceAuthError
    from binance_shioaji_sdk.order import OrderResponse
    from unittest.mock import AsyncMock, patch
    bn = _make_connected_bn(_FakeRest())
    contract = bn.Contracts.Perp["BTCUSDT"]
    order = bn.Order(price=50000, quantity=1, action="long", price_type="MKT")
    rejected = OrderResponse(
        order_id="", client_order_id="", symbol="BTCUSDT",
        status="REJECTED", filled_quantity=0, avg_filled_price=None,
        raw={"error": "HTTP 401", "detail": {"code": -2014, "msg": "Bad API-key format."}},
    )
    with patch(
        "binance_shioaji_sdk.client.place_order_via",
        new=AsyncMock(return_value=rejected),
    ):
        with pytest.raises(BinanceAuthError):
            await bn.place_order(contract, order)


@pytest.mark.asyncio
async def test_place_order_raises_account_error_on_rate_limit():
    """M-3: REJECTED with detail.code -1003 (rate limit) → BinanceAccountError."""
    from binance_shioaji_sdk import BinanceAccountError
    from binance_shioaji_sdk.order import OrderResponse
    from unittest.mock import AsyncMock, patch
    bn = _make_connected_bn(_FakeRest())
    contract = bn.Contracts.Perp["BTCUSDT"]
    order = bn.Order(price=50000, quantity=1, action="long", price_type="MKT")
    rejected = OrderResponse(
        order_id="", client_order_id="", symbol="BTCUSDT",
        status="REJECTED", filled_quantity=0, avg_filled_price=None,
        raw={"error": "HTTP 429", "detail": {"code": -1003, "msg": "Too many requests"}},
    )
    with patch(
        "binance_shioaji_sdk.client.place_order_via",
        new=AsyncMock(return_value=rejected),
    ):
        with pytest.raises(BinanceAccountError, match="rate limited"):
            await bn.place_order(contract, order)


@pytest.mark.asyncio
async def test_place_order_raises_account_error_on_generic_reject():
    """M-3: REJECTED with non-classified code → generic BinanceAccountError."""
    from binance_shioaji_sdk import BinanceAccountError
    from binance_shioaji_sdk.order import OrderResponse
    from unittest.mock import AsyncMock, patch
    bn = _make_connected_bn(_FakeRest())
    contract = bn.Contracts.Perp["BTCUSDT"]
    order = bn.Order(price=50000, quantity=1, action="long", price_type="MKT")
    rejected = OrderResponse(
        order_id="", client_order_id="", symbol="BTCUSDT",
        status="REJECTED", filled_quantity=0, avg_filled_price=None,
        raw={"error": "HTTP 400", "detail": {"code": -1121, "msg": "Invalid symbol."}},
    )
    with patch(
        "binance_shioaji_sdk.client.place_order_via",
        new=AsyncMock(return_value=rejected),
    ):
        with pytest.raises(BinanceAccountError, match="rejected"):
            await bn.place_order(contract, order)


@pytest.mark.asyncio
async def test_place_order_raises_on_filled_with_zero_price():
    """Design §3.2.3: FILLED + modified_price == 0.0 → broker data corruption."""
    from binance_shioaji_sdk import BinanceAccountError
    from binance_shioaji_sdk.order import OrderResponse
    from unittest.mock import AsyncMock, patch
    bn = _make_connected_bn(_FakeRest())
    contract = bn.Contracts.Perp["BTCUSDT"]
    order = bn.Order(price=50000, quantity=1, action="long", price_type="MKT")
    bad_resp = OrderResponse(
        order_id="999", client_order_id="", symbol="BTCUSDT",
        status="FILLED",  # claims FILLED…
        filled_quantity=1, avg_filled_price=0,  # …but price = 0
        raw={"weird": True},
    )
    with patch(
        "binance_shioaji_sdk.client.place_order_via",
        new=AsyncMock(return_value=bad_resp),
    ):
        with pytest.raises(BinanceAccountError, match="FILLED with zero price"):
            await bn.place_order(contract, order)
