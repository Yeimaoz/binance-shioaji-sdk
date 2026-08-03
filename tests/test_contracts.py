"""Tests for binance_shioaji_sdk.contracts."""
from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from binance_shioaji_sdk import Binance, BinanceContract


def test_perp_lookup_returns_binance_contract() -> None:
    bn = Binance(testnet=True)
    c = bn.Contracts.Perp["BTCUSDT"]
    assert isinstance(c, BinanceContract)
    assert c.symbol == "BTCUSDT"
    assert c.market_type == "perp"
    assert c.currency == "USDT"


def test_perp_unknown_symbol_raises_key_error() -> None:
    bn = Binance(testnet=True)
    with pytest.raises(KeyError):
        _ = bn.Contracts.Perp["FOOUSDT"]


def test_perp_tick_size_positive() -> None:
    bn = Binance(testnet=True)
    for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"):
        c = bn.Contracts.Perp[sym]
        assert c.tick_size > 0
        assert c.step_size > 0
        assert c.min_notional > 0


def test_perp_contains_check() -> None:
    bn = Binance(testnet=True)
    assert "BTCUSDT" in bn.Contracts.Perp
    assert "btcusdt" in bn.Contracts.Perp
    assert "FOOUSDT" not in bn.Contracts.Perp
    assert 12345 not in bn.Contracts.Perp


def test_binance_contract_is_frozen() -> None:
    bn = Binance(testnet=True)
    c = bn.Contracts.Perp["BTCUSDT"]
    with pytest.raises(FrozenInstanceError):
        c.tick_size = 999.0  # type: ignore[misc]


# -- 2026-08-03 實盤事故：SPCXUSDT 永遠 KeyError --------------------------------


@pytest.mark.asyncio
async def test_refresh_accepts_tradifi_perpetual_contract_type() -> None:
    """美股代幣化合約（TRADIFI_PERPETUAL）必須被收錄。

    Binance 對股票代幣化永續用獨立的 contractType：
        SPCXUSDT  contractType='TRADIFI_PERPETUAL'  status='TRADING'
        WLDUSDT   contractType='PERPETUAL'          status='TRADING'
    只收 'PERPETUAL' 會把前者全部濾掉 → `Contracts.Perp['SPCXUSDT']` KeyError
    → 用它跑的 bot 完全無法啟動（實盤停機 35 分鐘）。兩者都是 USDM 永續，
    交易語意相同。
    """
    from binance_shioaji_sdk.contracts import Contracts

    class _FakeRest:
        async def get(self, path, **kw):
            return {"symbols": [
                {"symbol": "SPCXUSDT", "contractType": "TRADIFI_PERPETUAL",
                 "status": "TRADING", "pricePrecision": 2, "quantityPrecision": 2,
                 "filters": []},
                {"symbol": "WLDUSDT", "contractType": "PERPETUAL",
                 "status": "TRADING", "pricePrecision": 4, "quantityPrecision": 0,
                 "filters": []},
                {"symbol": "DELIVERUSDT", "contractType": "CURRENT_QUARTER",
                 "status": "TRADING", "pricePrecision": 2, "quantityPrecision": 2,
                 "filters": []},
            ]}

    class _FakeClient:
        def _require_rest(self): return _FakeRest()

    c = Contracts(_FakeClient())
    await c.refresh()

    assert "SPCXUSDT" in c.Perp, "TRADIFI_PERPETUAL 被濾掉了"
    assert "WLDUSDT" in c.Perp, "標準 PERPETUAL 應照舊收錄"
    assert "DELIVERUSDT" not in c.Perp, "交割合約不該被收進永續 registry"


@pytest.mark.asyncio
async def test_login_sets_connected_before_contracts_refresh() -> None:
    """`Contracts.refresh()` 必須在 `_connected = True` **之後**呼叫。

    refresh 走 `_require_rest()`，而它要求 `self._connected`——原順序讓 refresh
    必然拋 "not logged in"，被 `except Exception` 吞成一行 WARNING
    （`exchangeInfo refresh failed (seed only)`），registry 永遠只剩硬編碼
    seed。實盤症狀：所有非 seed symbol 都 KeyError，而且沒有明顯錯誤。
    """
    import inspect
    from binance_shioaji_sdk import client as client_mod

    src = inspect.getsource(client_mod.Binance.login)
    connected_at = src.index("self._connected = True")
    refresh_at = src.index("Contracts.refresh()")
    assert connected_at < refresh_at, (
        "login() 在設定 _connected 之前呼叫 Contracts.refresh()——"
        "refresh 需要 _require_rest()，會必然失敗且被靜默吞掉"
    )
