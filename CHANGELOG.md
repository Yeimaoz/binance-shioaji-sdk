# Changelog

All notable changes to `binance-shioaji-sdk` are documented here.
Format loosely follows [Keep a Changelog](https://keepachangelog.com/).

## [0.5.10] - 2026-07-24

### Fixed — P0 silent-dead WS URLs (kline / markPrice / user stream)

Binance USDM futures decommissioned the legacy WebSocket URLs
(`wss://fstream.binance.com/ws`, `/stream`) on **2026-04-23**
(official notice: [Important WebSocket Change Notice](https://developers.binance.com/docs/derivatives/usds-margined-futures/websocket-market-streams/Important-WebSocket-Change-Notice)).
Post-migration, connections use one of three category-prefixed base URLs:

- `wss://fstream.binance.com/public/...` — high-frequency public data
  (bookTicker, depth)
- `wss://fstream.binance.com/market/...` — regular market data
  (markPrice, kline, aggTrade, ticker, forceOrder)
- `wss://fstream.binance.com/private/...` — user data stream

`v0.5.9` migrated `run_combined_stream`'s URL back to a bare
`/stream?streams=...` (no category prefix) to fix a *different*, earlier
P0 (bookTicker silent-dead against `/market/stream` pre-migration). That
bare URL happened to still deliver bookTicker (`public`-category) data
during the 2026-04-23 decommission grace period, which masked the fact
that `markPrice` and `kline` (`market`-category) streams were already
receiving **zero messages** — WS handshake succeeds, `ping`/`pong` is
healthy, but no data ever arrives. Live XRPUSDT deployment testing
confirmed: bookTicker had messages; kline/aggTrade/markPrice had zero
messages over 135s; swapping through 8 edge IPs made no difference;
SPOT (different WS domain) was unaffected.

- `BinanceWSManager.run_combined_stream()` gains a required-in-practice
  `category: Literal["public", "market"] = "market"` keyword arg. URL is
  now built as `{base}/{category}/stream?streams=...`. Invalid category
  raises `ValueError` (fail fast instead of silently connecting to a dead
  path).
- `Quote._run_mark_price_loop` (markPrice) → `category="market"`
- `Quote._run_kline_loop` (kline) → `category="market"`
- `Quote._run_book_ticker_loop` (bookTicker) → `category="public"`
  (unchanged behavior, now explicit instead of relying on the bare-URL
  default)
- `BinanceWSManager.run_user_stream()` — audited, **no change**. It has
  used `wss://fstream.binance.com/private/ws?listenKey=...&events=ORDER_TRADE_UPDATE`
  since the 2024-02-29 migration, which is still the correct `/private`
  path under the new scheme.

### Testing

- Unit: exact-URL assertions for `category="market"` (markPrice, kline),
  `category="public"` (bookTicker), invalid-category `ValueError`, and
  default-category value — `tests/_internal/test_ws_manager.py`.
- Live opt-in smoke (`tests/test_ws_live_smoke.py`, skipped by default,
  `BINANCE_SDK_LIVE_SMOKE=1` to run): connects real mainnet
  `wss://fstream.binance.com/market/stream?streams=xrpusdt@kline_1m/xrpusdt@aggTrade`
  and `.../public/stream?streams=xrpusdt@bookTicker`, asserts ≥3 messages
  received. Verified 2026-07-24: both passed in ~12.5s (market: kline_1m +
  aggTrade messages arrived; public: bookTicker messages arrived).
  User-stream live smoke is present but self-skips without
  `BINANCE_API_KEY`/`BINANCE_SECRET_KEY` — URL correctness for that path
  is covered by the unit test.

## [0.5.9] - 2026-06-12

`run_combined_stream` combined-stream URL fixed from `/market/stream` to
bare `/stream` (P0 bookTicker/markPrice silent-dead against pre-migration
Binance behavior). See commit `4b46ace` (#22). *(Superseded by 0.5.10 —
see above; that fix was correct for its time window but not for the
post-2026-04-23 URL scheme.)*
