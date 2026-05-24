"""
binance_shioaji_sdk/client.py — Binance top-level entry

Mirrors shioaji `sj.Shioaji(simulation=...)` shape:
    bn = Binance(testnet=False)
    await bn.login(api_key, secret_key)
    contract = bn.Contracts.Perp["BTCUSDT"]
    order = bn.Order(price=50000, quantity=1, action="long", price_type="LMT")
    resp = await bn.place_order(contract, order)
    positions = await bn.list_positions(bn.futures_account)
    balance = await bn.account_balance()
    await bn.logout()
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Optional

from binance_shioaji_sdk._internal import (
    BinanceRestClient,
    BinanceWSManager,
    LISTEN_KEY_KEEPALIVE_INTERVAL,
)
from binance_shioaji_sdk.account import BinanceAccount
from binance_shioaji_sdk.contracts import BinanceContract, Contracts
from binance_shioaji_sdk.market_info import MarketInfo
from binance_shioaji_sdk.order import (
    Order as _Order,
    OrderResponse,
    cancel_order_via,
    list_trades_via,
    place_order_via,
)
from binance_shioaji_sdk.quote import Quote

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

BINANCE_FUTURES_BASE = "https://fapi.binance.com"
BINANCE_FUTURES_TESTNET = "https://testnet.binancefuture.com"
BINANCE_WS_BASE = "wss://fstream.binance.com"
BINANCE_WS_TESTNET = "wss://stream.binancefuture.com"


# ---------------------------------------------------------------------------
# Binance
# ---------------------------------------------------------------------------


class Binance:
    """Binance Futures SDK top-level client.

    Lifecycle:
        bn = Binance(testnet=True)
        await bn.login(api_key, secret_key)
        ...
        await bn.logout()

    Owns:
        - BinanceRestClient (httpx + signing, lazily created in login())
        - BinanceWSManager  (WS + listen_key keepalive, lazily wired)
        - Contracts namespace (Perp[symbol] dot-access)
        - futures_account property -> BinanceAccount
        - quote / market_info / Order / place_order / cancel_order /
          list_trades placeholders (companion-PR scope)
    """

    def __init__(self, testnet: bool = False) -> None:
        self.testnet = testnet
        self._base_url = BINANCE_FUTURES_TESTNET if testnet else BINANCE_FUTURES_BASE
        self._ws_base_url = BINANCE_WS_TESTNET if testnet else BINANCE_WS_BASE

        # Credentials populated by login()
        self.api_key: str | None = None
        self.secret_key: str | None = None

        # Lazy: created in login(), torn down in logout()
        self._rest: BinanceRestClient | None = None
        self._ws: BinanceWSManager | None = None
        self._listen_key: str | None = None
        self._listen_key_task: asyncio.Task | None = None
        self._connected = False

        # Public namespaces
        self.Contracts = Contracts(self)
        self.quote = Quote(self)
        self.market_info = MarketInfo(self)
        # Order builder — bn.Order(...) returns Order dataclass instance
        self.Order = _Order

        # Hooks
        self.on_session_down: Optional[Callable[[], None]] = None

        logger.debug("[Binance] init testnet=%s", testnet)

    # ── Account property ─────────────────────────────────────────────────

    @property
    def futures_account(self) -> BinanceAccount:
        """Mirror of shioaji `sj.futopt_account`. Stable across calls."""
        return BinanceAccount(client_ref=self, account_type="futures")

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def ws_base_url(self) -> str:
        return self._ws_base_url

    # ── Lifecycle ────────────────────────────────────────────────────────

    async def login(self, api_key: str, secret_key: str) -> None:
        """Set credentials, open REST client, create listenKey, start keepalive.

        Idempotent: calling login twice with the same keys is a no-op after the
        first; calling with new keys swaps credentials but keeps the connection.
        """
        if not api_key or not secret_key:
            raise ValueError("[Binance] api_key / secret_key 皆必填。")

        self.api_key = api_key
        self.secret_key = secret_key

        if self._rest is None:
            self._rest = BinanceRestClient(
                base_url=self._base_url,
                api_key=api_key,
                secret_key=secret_key,
            )
            await self._rest.connect()
        else:
            # Update credentials on existing REST client
            self._rest.api_key = api_key
            self._rest.secret_key = secret_key

        if self._ws is None:
            self._ws = BinanceWSManager(base_url=self._ws_base_url)

        # listenKey creation: best-effort for transient errors (5xx / network)
        # — REST queries still work without user stream. Auth failure
        # (401/403) propagates as BinanceAuthError so caller fails fast on
        # bad credentials instead of getting a half-connected client.
        await self._create_listen_key()
        if self._listen_key and self._listen_key_task is None:
            self._listen_key_task = asyncio.create_task(self._listen_key_keepalive_loop())

        self._connected = True
        logger.info("[Binance] login OK (testnet=%s)", self.testnet)

    async def logout(self) -> None:
        """Stop keepalive, close REST. Idempotent."""
        if self._listen_key_task is not None and not self._listen_key_task.done():
            self._listen_key_task.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(self._listen_key_task), timeout=2.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass
        self._listen_key_task = None
        self._listen_key = None

        if self._rest is not None:
            await self._rest.close()
            self._rest = None

        self._ws = None
        self._connected = False
        logger.info("[Binance] logout OK")

    # ── Private: listenKey lifecycle ─────────────────────────────────────

    async def _create_listen_key(self) -> None:
        """Best-effort listenKey POST. Stores result in self._listen_key."""
        if self._rest is None or self._ws is None or not self.api_key:
            return
        try:
            client = self._rest._ensure_client()
        except RuntimeError:
            return
        self._listen_key = await self._ws.create_listen_key(
            client, self.api_key, self._base_url
        )

    async def _listen_key_keepalive_loop(self) -> None:
        """Background task: PUT /fapi/v1/listenKey every 30 min."""
        try:
            while self._connected:
                await asyncio.sleep(LISTEN_KEY_KEEPALIVE_INTERVAL)
                if not self._connected or self._rest is None or self._ws is None:
                    return
                if not self._listen_key or not self.api_key:
                    return
                try:
                    client = self._rest._ensure_client()
                except RuntimeError:
                    return
                ok = await self._ws.keepalive_listen_key(
                    client, self.api_key, self._listen_key, self._base_url
                )
                if not ok:
                    logger.warning("[Binance] listenKey keepalive failed; clearing")
                    self._listen_key = None
                    if self.on_session_down is not None:
                        try:
                            self.on_session_down()
                        except Exception as exc:  # noqa: BLE001
                            logger.error("[Binance] on_session_down hook raised: %s", exc)
        except asyncio.CancelledError:
            return

    # ── Account / position queries ───────────────────────────────────────

    async def list_positions(self, account: BinanceAccount) -> list[dict]:
        """Query open positions for the given account.

        Mirrors `sj.list_positions(account)`. Account is a thin handle; in
        Binance there is exactly one futures account per API key, but we
        accept the parameter for shape parity.

        Returns
        -------
        list of normalized position dicts. Empty list when API errors or
        when no positions are open.
        """
        if account.account_type != "futures":
            raise ValueError(
                f"[Binance] list_positions: only 'futures' supported, "
                f"got account_type={account.account_type!r}"
            )
        rest = self._require_rest()
        raw = await rest.get("/fapi/v2/positionRisk", signed=True)
        if isinstance(raw, dict) and "error" in raw:
            logger.warning("[Binance] list_positions failed: %s", raw)
            return []
        if not isinstance(raw, list):
            return []

        result: list[dict] = []
        for p in raw:
            qty = float(p.get("positionAmt", 0))
            if qty == 0:
                continue
            result.append({
                "symbol": p.get("symbol", ""),
                "direction": "long" if qty > 0 else "short",
                "quantity": abs(qty),
                "avg_price": float(p.get("entryPrice", 0)),
                "unrealized_pnl": float(p.get("unRealizedProfit", 0)),
            })
        return result

    async def account_balance(self) -> dict:
        """Query USDT futures wallet balance.

        Mirrors `sj.account_balance()`. Returns dict with at least:
        equity / available / initial_margin / maintenance_margin keys.
        """
        rest = self._require_rest()
        raw = await rest.get("/fapi/v2/balance", signed=True)
        if isinstance(raw, dict) and "error" in raw:
            logger.warning("[Binance] account_balance failed: %s", raw)
            return {
                "equity": 0.0,
                "available": 0.0,
                "initial_margin": 0.0,
                "maintenance_margin": 0.0,
            }

        usdt: dict[str, Any] = {}
        if isinstance(raw, list):
            for b in raw:
                if b.get("asset") == "USDT":
                    usdt = b
                    break
        return {
            "equity": float(usdt.get("balance", 0.0)),
            "available": float(usdt.get("availableBalance", 0.0)),
            "initial_margin": float(usdt.get("initialMargin", 0.0)),
            "maintenance_margin": float(usdt.get("maintMargin", 0.0)),
        }

    # ── Order placement / cancellation / query ───────────────────────────

    async def place_order(
        self, contract: BinanceContract, order: _Order
    ) -> OrderResponse:
        """Mirror shioaji `sj.place_order(contract, order)`."""
        return await place_order_via(
            self._require_rest(), contract, order, base_url=self._base_url
        )

    async def cancel_order(self, symbol: str, order_id: str) -> bool:
        """Mirror shioaji `sj.cancel_order(trade)` (Binance needs symbol + order_id)."""
        return await cancel_order_via(self._require_rest(), symbol, order_id)

    async def list_trades(
        self, symbol: str | None = None, limit: int = 500
    ) -> list[OrderResponse]:
        """Mirror shioaji `sj.list_trades()`."""
        return await list_trades_via(self._require_rest(), symbol=symbol, limit=limit)

    # ── Helpers ──────────────────────────────────────────────────────────

    def _require_rest(self) -> BinanceRestClient:
        if self._rest is None or not self._connected:
            raise RuntimeError(
                "[Binance] not logged in; call await bn.login(api_key, secret_key) first."
            )
        return self._rest
