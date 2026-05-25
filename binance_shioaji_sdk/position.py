"""v0.4.0 BinanceFuturePosition — mirror sj.FuturePosition.

Per design §3.3. Vocabulary rename: code (not symbol), direction "Buy"/"Sell"
(not "long"/"short"), price (not avg_price), pnl (not unrealized_pnl).

Divergence: quantity is Decimal (not int) — Binance allows fractional
positions (0.001 BTC); rounding to int silently loses sub-contract positions.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class BinanceFuturePosition:
    """Mirror of sj.FuturePosition — exact 7 field names.

    Source: Binance /fapi/v2/positionRisk. Sign of positionAmt determines
    direction; abs(positionAmt) becomes quantity. id synthesized as
    f"{symbol}_{positionSide}" (one-way mode positionSide is "BOTH").
    """
    code: str               # Binance symbol → shioaji vocab `code`
    direction: str          # "Buy" / "Sell" (mirror sj.constant.Action vocab)
    id: str                 # synthesized: f"{symbol}_{positionSide}"
    last_price: float       # Binance: markPrice
    pnl: float              # Binance: unRealizedProfit
    price: float            # Binance: entryPrice
    quantity: Decimal       # Decimal (not int) — Binance allows fractional
