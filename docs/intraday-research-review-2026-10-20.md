# Whale Intelligence V2 — Research Release Review

This is a **Binance Futures USD-M historical research experiment**, not a working intraday trading signal engine.

## Findings on 20 October 2026

- The 30-day BTCUSD-M Futures archive supplied 2880 closed 15m bars, 720 1h bars and 180 4h bars without gaps.
- Technical historical experiment: 9 BTC pullback patterns and **no** qualifying breakout/retest patterns. Its *hypothetical* average R was **-0.6269**, win rate 2/9, profit factor 0.3546. This is a tiny sample and lacks execution/funding/open-interest data.
- The chronological 30% time-based holdout had only **3** patterns. Never report its profit factor as evidence of profitable performance.
- GitHub runners observed Binance REST HTTP 451. Market WebSocket connection was proven for kline, mark price, and bookTicker public events using official endpoints. A short 90-second collector run captured **zero candle closes**, thus no continuous live history was established.
- Data bridge correctly returned **NO_TRADE** when archives were two days delayed and live continuity was missing.
- Multi-asset 30-day review is provided by `.github/workflows/binance-multi-asset-research.yml` on a separate development branch. It downloads only delayed public archives, does not generate Telegram signals, and never trades.

## Safety and release criteria

**Block live signals and production merge** until: reliable permitted live data access, continuous gap-free 4H/1H/15m candles, instrument metadata/filters, current spread/book, funding and OI, representative paper-trading records including realistic fees/slippage, meaningful evaluation periods and out-of-sample evidence, and explicit manual sign-off.

Model score (0–100) indicates rule matching, **not** win probability. No historical simulation constitutes investment advice. The current public repo is not suitable for API credentials, trading secrets, or execution.

**Warning:** A passing GitHub Actions job means the program ran; it does not imply positive profitability or data sufficiency.

## Dashboard

The existing Cloudflare Worker continues to show V1 / Hyperliquid-oriented data. No deployment or dashboard integration was attempted by this development branch. No automated Binance orders or live trading alerts are enabled.
