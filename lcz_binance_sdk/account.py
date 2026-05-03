"""
lcz_binance_sdk/account.py — Binance account placeholder
========================================================

Mirrors shioaji `sj.futopt_account` placeholder shape — used as a parameter
identity object passed to e.g. `bn.list_positions(account)`. Binance only
exposes one futures account per API key, so this object is mostly symbolic.

`account_id` is derived from md5(api_key)[:8] for stable, masked identification
in logs / structured output (never exposes the raw key).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lcz_binance_sdk.client import BinanceClient


@dataclass(frozen=True)
class BinanceAccount:
    """Binance futures account placeholder.

    Mirrors shioaji futopt_account: a thin handle the user passes back to
    SDK methods that operate on a specific account. Binance has one futures
    account per API key, so this object's main job is to provide a stable
    masked identifier (no raw key leak) and parity with shioaji shape.

    Attributes
    ----------
    client_ref   : owning BinanceClient (so account_id can derive from key)
    account_type : "futures" (v0.1 only); "spot" / "delivery" reserved.
    """

    client_ref: "BinanceClient"
    account_type: str = "futures"

    @property
    def account_id(self) -> str:
        """Stable masked id derived from md5(api_key)[:8].

        Returns "anon" when api_key not yet set (pre-login). Never exposes
        the raw secret.
        """
        api_key = getattr(self.client_ref, "api_key", None)
        if not api_key:
            return "anon"
        digest = hashlib.md5(api_key.encode("utf-8")).hexdigest()
        return digest[:8]

    def __repr__(self) -> str:
        return f"BinanceAccount(account_type={self.account_type!r}, account_id={self.account_id!r})"
