# Intraday Intelligence V2 (experimental)

Separate from the legacy Hyperliquid whale trackers. Binance USDT-M market data; multi-timeframe 4H/1H/15M; shortlist top 20 liquid perpetual pairs; two entry-pattern hypotheses; derivatives context; 1% of a hypothetical Rp500,000 bankroll as maximum estimated risk (including simple fee/slippage estimate). Scores reflect RULE MATCHING, not win probability.

- `scripts/intraday_scanner.py` — standalone research engine
- `scripts/test_intraday_scanner.py` — offline, deterministic tests
- `.github/workflows/intraday-intelligence.yml` — best-effort 15-min GitHub schedule
- `intraday_scan.json` / `intraday_signals.json` / `intraday_state.json` — generated only when a run occurs.

**Not an execution signal.** No broker keys, no account orders, and no copy-trading. The scanner produces `PAPER_ONLY` hypothetical setups; no claims of backtested profitability. Fees/slippage are assumptions and real stop-loss losses can be larger. Futures leverage and liquidation risk remain substantial.

**Activation:** workflow runs only after this development branch is merged into the default branch. Paper Telegram notices are disabled unless repo Actions variable `ENABLE_INTRADAY_PAPER_ALERTS` is set to `true` and existing Telegram secrets are valid. Do not switch this on until reviewed. Scheduled runs on GitHub are best-effort and may be delayed or skipped.

**Risk constraints:** fails closed on stale/incomplete API data, unconfirmed pattern, misaligned trends, low volume, overly wide spreads, excessive volatility/funding, missing OI, or unattractive net R:R. Candidate set is not a complete deep-scan of all assets every cycle. Generated notices are *research hypotheses* only.

**Known next work before production:** exchange timestamp synchronization, quantization to Binance tick/step sizes, minimum quantity checks, stronger support/resistance target validation, reproducible backtests with walk-forward splits, performance journaling for *this* strategy only, expired alert state machine, live data quality monitoring, and a dashboard view. Signals should not be used with real funds until paper evidence has been independently examined.
