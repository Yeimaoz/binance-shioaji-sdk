"""Tests for binance_shioaji_sdk.client.BinanceClient.

Covers: testnet base_url switching, login/logout state, placeholder
NotImplementedError surface, on_session_down hook assignability.

httpx + listenKey creation are mocked — no real network.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from binance_shioaji_sdk import BinanceAccount, BinanceClient
from binance_shioaji_sdk.client import (
    BINANCE_FUTURES_BASE,
    BINANCE_FUTURES_TESTNET,
    BINANCE_WS_BASE,
    BINANCE_WS_TESTNET,
)


def test_testnet_flag_swaps_base_url() -> None:
    bn_test = BinanceClient(testnet=True)
    bn_prod = BinanceClient(testnet=False)
    assert bn_test.base_url == BINANCE_FUTURES_TESTNET
    assert "testnet" in bn_test.base_url
    assert bn_prod.base_url == BINANCE_FUTURES_BASE
    assert bn_test.ws_base_url == BINANCE_WS_TESTNET
    assert bn_prod.ws_base_url == BINANCE_WS_BASE


def test_is_connected_false_before_login() -> None:
    bn = BinanceClient(testnet=True)
    assert bn.is_connected is False


@pytest.mark.asyncio
async def test_login_sets_connected_true_and_logout_resets() -> None:
    bn = BinanceClient(testnet=True)

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
    bn = BinanceClient(testnet=True)
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

    bn = BinanceClient(testnet=True)

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
    bn = BinanceClient(testnet=True)
    contract = bn.Contracts.Perp["BTCUSDT"]
    order = bn.Order(price=50000, quantity=1, action="long", price_type="LMT")
    with pytest.raises(RuntimeError, match="not logged in"):
        await bn.place_order(contract, order)
    with pytest.raises(RuntimeError, match="not logged in"):
        await bn.cancel_order("BTCUSDT", "123")
    with pytest.raises(RuntimeError, match="not logged in"):
        await bn.list_trades()


def test_quote_marketinfo_namespaces_wired() -> None:
    """Wire-in: quote / market_info / Order all live and callable from BinanceClient."""
    bn = BinanceClient(testnet=True)
    from binance_shioaji_sdk import MarketInfo, Order, Quote
    assert isinstance(bn.quote, Quote)
    assert isinstance(bn.market_info, MarketInfo)
    assert bn.Order is Order
    o = bn.Order(price=100, quantity=1, action="long", price_type="LMT")
    assert o.price == 100 and o.quantity == 1


def test_on_session_down_callback_assignable() -> None:
    bn = BinanceClient(testnet=True)
    assert bn.on_session_down is None

    called: list[bool] = []

    def cb() -> None:
        called.append(True)

    bn.on_session_down = cb
    assert bn.on_session_down is cb
    bn.on_session_down()
    assert called == [True]


def test_futures_account_returns_binance_account() -> None:
    bn = BinanceClient(testnet=True)
    acct = bn.futures_account
    assert isinstance(acct, BinanceAccount)
    assert acct.account_type == "futures"
    assert acct.client_ref is bn
