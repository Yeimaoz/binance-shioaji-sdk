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

    async def list_positions(self, account: BinanceAccount) -> "list[BinanceFuturePosition]":
        """Query open positions. v0.4.0: returns list[BinanceFuturePosition].

        Mirrors `sj.list_positions(account)`. Zero-qty entries omitted
        (design §3.2.2). Direction uses shioaji vocab ("Buy"/"Sell")
        not Binance ("long"/"short"). Position id synthesized as
        f"{symbol}_{positionSide}".

        Raises BinanceAccountError on REST failure (v0.4.0 behavioral change —
        v0.3.x returned [] on error).
        """
        from binance_shioaji_sdk.position import BinanceFuturePosition
        from binance_shioaji_sdk.exceptions import BinanceAccountError
        from decimal import Decimal
        if account.account_type != "futures":
            raise ValueError(
                f"[Binance] list_positions: only 'futures' supported, "
                f"got account_type={account.account_type!r}"
            )
        rest = self._require_rest()
        raw = await rest.get("/fapi/v2/positionRisk", signed=True)
        if isinstance(raw, dict) and "error" in raw:
            logger.warning("[Binance] list_positions failed: %s", raw)
            raise BinanceAccountError(f"list_positions REST failed: {raw}")
        if not isinstance(raw, list):
            raise BinanceAccountError(f"list_positions: unexpected response shape: {raw!r}")

        result: list[BinanceFuturePosition] = []
        for p in raw:
            try:
                amt = Decimal(str(p.get("positionAmt", 0)))
            except Exception:
                continue
            if amt == Decimal(0):
                continue
            symbol = p.get("symbol", "")
            position_side = p.get("positionSide", "BOTH")
            direction = "Buy" if amt > Decimal(0) else "Sell"
            result.append(BinanceFuturePosition(
                code=symbol,
                direction=direction,
                id=f"{symbol}_{position_side}",
                last_price=float(p.get("markPrice", 0) or 0),
                pnl=float(p.get("unRealizedProfit", 0) or 0),
                price=float(p.get("entryPrice", 0) or 0),
                quantity=abs(amt),
            ))
        return result

    async def account_balance(self) -> "BinanceAccountBalance":
        """Query USDT futures wallet balance. v0.4.0: returns BinanceAccountBalance.

        Mirrors `sj.account_balance()`. acc_balance maps to the wallet
        balance ("balance" field in /fapi/v2/balance USDT entry). Margin
        breakdown lives in separate `margin(account)` call.

        Raises BinanceAccountError on REST failure (v0.4.0 behavioral change —
        v0.3.x returned zero-filled dict).
        """
        from binance_shioaji_sdk.balance import BinanceAccountBalance
        from binance_shioaji_sdk.exceptions import BinanceAccountError
        from datetime import date as _date
        rest = self._require_rest()
        raw = await rest.get("/fapi/v2/balance", signed=True)
        if isinstance(raw, dict) and "error" in raw:
            logger.warning("[Binance] account_balance failed: %s", raw)
            raise BinanceAccountError(f"account_balance REST failed: {raw}")
        if isinstance(raw, list):
            for b in raw:
                if b.get("asset") == "USDT":
                    return BinanceAccountBalance(
                        acc_balance=float(b.get("balance", 0) or 0),
                        date=_date.today().isoformat(),
                        errmsg="",
                        status="200",
                    )
        raise BinanceAccountError(
            f"account_balance: USDT asset not found in response: {raw!r}"
        )

    async def margin(self, account: BinanceAccount) -> "BinanceMargin":
        """Query margin breakdown. NEW in v0.4.0 — mirrors `sj.margin(account)`.

        shioaji decomposes balance vs margin into two models / two calls.
        Binance's /fapi/v2/account endpoint returns the margin fields;
        /fapi/v2/balance returns wallet balance (account_balance() uses that).

        Raises BinanceAccountError on REST failure.
        """
        from binance_shioaji_sdk.balance import BinanceMargin
        from binance_shioaji_sdk.exceptions import BinanceAccountError
        if account.account_type != "futures":
            raise ValueError(
                f"[Binance] margin: only 'futures' supported, "
                f"got account_type={account.account_type!r}"
            )
        rest = self._require_rest()
        raw = await rest.get("/fapi/v2/account", signed=True)
        if isinstance(raw, dict) and "error" in raw:
            logger.warning("[Binance] margin failed: %s", raw)
            raise BinanceAccountError(f"margin REST failed: {raw}")
        eq = float(raw.get("totalMarginBalance", 0) or 0)
        return BinanceMargin(
            available_margin=float(raw.get("availableBalance", 0) or 0),
            initial_margin=float(raw.get("totalInitialMargin", 0) or 0),
            maintenance_margin=float(raw.get("totalMaintMargin", 0) or 0),
            equity=eq,
            equity_amount=eq,
            today_balance=float(raw.get("totalWalletBalance", 0) or 0),
            yesterday_balance=0.0,  # Binance doesn't track daily snapshot
            status="200",
        )

    # ── Order placement / cancellation / query ───────────────────────────

    async def place_order(
        self, contract: BinanceContract, order: _Order
    ) -> "BinanceTrade":
        """Submit order. v0.4.0: returns BinanceTrade composite.

        Mirror shioaji `sj.place_order(contract, order)`. Order id lives at
        `trade.status.id` (mirrors sj.OrderStatusInfo.id) — NOT on `trade.order`.

        Raises BinanceAuthError on auth failure (codes -2014/-2015 or msg
        contains "signature"/"api-key"/"auth"); BinanceAccountError on other
        REST failures including rate-limit (-1003).
        """
        from binance_shioaji_sdk.trade import (
            BinanceTrade, BinanceTradeStatus, BinanceOrderStatusEnum,
        )
        from binance_shioaji_sdk.exceptions import (
            BinanceAuthError, BinanceAccountError,
        )
        from datetime import datetime, timezone
        rest = self._require_rest()
        resp = await place_order_via(rest, contract, order, base_url=self._base_url)
        # M-3 fix: place_order_via does NOT raise on REST error — returns
        # OrderResponse(status="REJECTED", raw={"error":..., "detail":...}).
        # Inspect status + classify before converting to BinanceTrade.
        if str(getattr(resp, "status", "")).upper() == "REJECTED":
            raw_err = getattr(resp, "raw", {}) or {}
            detail = raw_err.get("detail") if isinstance(raw_err, dict) else {}
            code = detail.get("code", "") if isinstance(detail, dict) else ""
            msg = (detail.get("msg", "") if isinstance(detail, dict) else str(raw_err)).lower()
            # Binance Futures auth codes: -2014 (invalid key format), -2015 (invalid key/secret/permissions)
            if code in (-2014, -2015) or "signature" in msg or "api-key" in msg or "auth" in msg:
                raise BinanceAuthError(f"place_order auth failure: {raw_err}")
            if code == -1003 or "rate" in msg:
                raise BinanceAccountError(f"place_order rate limited: {raw_err}")
            raise BinanceAccountError(f"place_order rejected: {raw_err}")
        # Success path — convert OrderResponse → BinanceTrade
        status_map = {
            "NEW": BinanceOrderStatusEnum.Submitted,
            "PARTIALLY_FILLED": BinanceOrderStatusEnum.PartFilled,
            "FILLED": BinanceOrderStatusEnum.Filled,
            "CANCELED": BinanceOrderStatusEnum.Cancelled,
            "REJECTED": BinanceOrderStatusEnum.Failed,
            "EXPIRED": BinanceOrderStatusEnum.Cancelled,
        }
        binance_status = status_map.get(
            str(resp.status).upper(), BinanceOrderStatusEnum.Submitted,
        )
        avg = getattr(resp, "avg_filled_price", None)
        modified_price = float(avg) if avg else 0.0
        # Filled-with-zero-price → broker data corruption per design §3.2.3
        if binance_status == BinanceOrderStatusEnum.Filled and modified_price == 0.0:
            raise BinanceAccountError(
                f"binance returned FILLED with zero price (broker data corruption): {resp.raw!r}"
            )
        status_obj = BinanceTradeStatus(
            id=str(resp.order_id),
            status=binance_status,
            status_code="",
            order_datetime=datetime.now(timezone.utc).isoformat(),
            deal_quantity=int(getattr(resp, "filled_quantity", 0)) if getattr(resp, "filled_quantity", None) is not None else None,
            order_quantity=int(order.quantity) if hasattr(order, "quantity") else None,
            cancel_quantity=None,
            modified_price=modified_price,
            msg="",
        )
        return BinanceTrade(contract=contract, order=order, status=status_obj)

    async def cancel_order(self, symbol: str, order_id: str) -> bool:
        """Mirror shioaji `sj.cancel_order(trade)` (Binance needs symbol + order_id)."""
        return await cancel_order_via(self._require_rest(), symbol, order_id)

    async def list_trades(
        self, symbol: str | None = None, limit: int = 500
    ) -> list[OrderResponse]:
        """Mirror shioaji `sj.list_trades()`.

        NOTE (code-review H-1): v0.4.0 DEFERS list_trades return-type
        migration to v0.5.0. Design §3.6 specified `list[BinanceTrade]` with
        synthetic stub `BinanceContract(symbol=...)` for history entries, but
        §2 in-scope + §6 acceptance criteria did not mandate it. Implementer
        followed §2/§6 over §3.6 to keep v0.4.0 scope tight. Tracked for
        v0.5.0 in design §9 follow-ups.
        """
        return await list_trades_via(self._require_rest(), symbol=symbol, limit=limit)

    # ── Helpers ──────────────────────────────────────────────────────────

    def _require_rest(self) -> BinanceRestClient:
        if self._rest is None or not self._connected:
            raise RuntimeError(
                "[Binance] not logged in; call await bn.login(api_key, secret_key) first."
            )
        return self._rest
