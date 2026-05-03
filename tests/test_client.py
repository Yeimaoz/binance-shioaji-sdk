"""Tests for lcz_binance_sdk.client.BinanceClient.

Covers: testnet base_url switching, login/logout state, placeholder
NotImplementedError surface, on_session_down hook assignability.

httpx + listenKey creation are mocked — no real network.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from lcz_binance_sdk import BinanceAccount, BinanceClient
from lcz_binance_sdk.client import (
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
        "lcz_binance_sdk.client.BinanceWSManager.create_listen_key",
        new=AsyncMock(return_value="fake_listen_key_xyz"),
    ), patch(
        "lcz_binance_sdk._internal.rest_client.BinanceRestClient.connect",
        new=AsyncMock(return_value=None),
    ), patch(
        "lcz_binance_sdk._internal.rest_client.BinanceRestClient._ensure_client",
        return_value=object(),
    ), patch(
        "lcz_binance_sdk._internal.rest_client.BinanceRestClient.close",
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
async def test_place_order_raises_not_implemented() -> None:
    bn = BinanceClient(testnet=True)
    with pytest.raises(NotImplementedError):
        await bn.place_order(contract=None, order=None)
    with pytest.raises(NotImplementedError):
        await bn.cancel_order("dummy:123")
    with pytest.raises(NotImplementedError):
        await bn.list_trades()
    with pytest.raises(NotImplementedError):
        bn.Order(price=100.0, quantity=1)


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
