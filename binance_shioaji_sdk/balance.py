"""v0.4.0 BinanceAccountBalance + BinanceMargin — mirror sj.AccountBalance + sj.Margin.

Decomposition follows shioaji: balance (acc_balance) and margin (utilization)
are separate models. Per design §3.1 + §3.2.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BinanceAccountBalance:
    """Mirror of sj.AccountBalance — exact 4 fields.

    Note: Binance source for acc_balance is the `balance` field in the
    per-asset entry from /fapi/v2/balance (NOT `totalWalletBalance` — that
    lives in /fapi/v2/account and is wired through BinanceMargin.today_balance).
    equity / margin info lives in BinanceMargin (separate call).
    """
    acc_balance: float
    date: str           # today's date YYYY-MM-DD
    errmsg: str
    status: str         # "200" on success; HTTP status code on failure


@dataclass(frozen=True)
class BinanceMargin:
    """Mirror of sj.Margin — intentional 8/26 subset (see design §3.2).

    sj.Margin has 25+ fields; we mirror only the essentials with Binance
    equivalents. Out-of-scope shioaji-only fields (collateral_amount,
    deposit_withdrawal, fee, option_*, etc.) are not added (would be faking).
    """
    available_margin: float       # Binance: availableBalance (/fapi/v2/account)
    initial_margin: float          # Binance: totalInitialMargin
    maintenance_margin: float      # Binance: totalMaintMargin
    equity: float                  # Binance: totalMarginBalance (wallet + uPnL)
    equity_amount: float           # alias of equity (shioaji keeps both)
    today_balance: float           # ≈ acc_balance; redundant for shioaji parity
    yesterday_balance: float       # best-effort; Binance doesn't track daily snapshot — may be 0.0
    status: str                    # "200" on success
