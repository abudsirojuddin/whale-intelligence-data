# Intraday V2 release gates — 20 Oct 2026

## Findings verified in GitHub Actions
- Binance USD-M REST `fapi.binance.com` returns HTTP 451 from this GitHub runner: do not route around restrictions.
- Binance USD-M public WebSocket `fstream.binance.com` delivers validated BTC/ETH kline updates, mark-price and bookTicker (different documented channels).
- Binance Vision USD-M daily ZIP is reachable and a one-day BTC dataset passed 15m/1h/4h completeness checks.
- The 75-second streaming collector completed without exceptions but captured **zero closed candles**. This is possible when no candle closes during a short collection window; it is NOT continuous coverage.
- Data bridge is deliberately fail-closed when archive+live series are insufficient/stale/missing. The bridge's offline tests pass.

## Blocking issues for automatic signals
1. **No continuous archival collector yet.** Short, best-effort scheduled GitHub jobs cannot guarantee every 15-minute close or instantly recover service interruption. An uninterrupted feed or reliable approved historical backfill is required.
2. **No approved live REST route.** HTTP 451 cannot be bypassed. Spot prices and delayed archives cannot substitute for current Binance USD-M executable prices.
3. **Derivatives metrics incomplete:** historical OI/current depth and spreads must be verified before mandatory filters may pass.
4. **No audited per-strategy forward performance:** quality score is rule compliance, NOT predicted win rate. No executable LONG/SHORT Telegram messages.
5. **No tested tick/step filter compliance, latency measurements, live strategy state machine or authenticated order checks.**
6. Production Cloudflare dashboard and legacy Hyperliquid signals remain untouched.

## E2E test
The workflow `.github/workflows/intraday-data-e2e.yml` obtains a 14-day **delayed** archive and a 90-second read-only WS sample, joins datasets, logs freshness/gap diagnostics and safely outputs NO_TRADE unless continuity is proven. It is a diagnostic, not a deployable signal scheduler. It must be reviewed before merging to main.

## Recommendation
Only activate scheduled (paper-only) market scanning after solving authorized data access + continuous closed-candle recording, verifying all data gates and performing reproducible prospective paper trials. Never convert missing data into assumed prices or dummy candles.
