# Whale Intelligence — Public Research Tracker

A read-only Hyperliquid wallet-research experiment. **Not investment advice, copy trading, or a signal provider.**

## V4.1 backend

- `Update Smart Money Candidates`: discovers up to **100** candidates from the public leaderboard. The top 20 remain stable for backwards-compatible V3 monitoring; 80 additional wallets are selected with volume diversification.
- `Update Trader Quality Ranking`: processes **20 of 100 wallets per run**, rotating through batches approximately every six hours. Full initial coverage takes up to **five successful runs (~30 hours)**. A result may be **PENDING**, **INSUFFICIENT**, **INCOMPLETE**, **UNAVAILABLE**, or **EVALUATED**. Old checked results may be stale, so see `checkedAt`.
- `Monitor Whale Positions`: checks approximately every ten minutes (GitHub Actions scheduling is best-effort) and writes `alerts.json`. Telegram notifications are restricted to previously **EVALUATED** wallets with score >=60 and `checkedAt` <48 hours, and position changes must also pass the normal threshold. Activity from other wallets may appear on the public dashboard as research data, but no high-confidence Telegram signal is implied.

**Important:** The public `userFillsByTime` API has pagination and history-availability limitations. The ranking deliberately refuses a numeric score when historical evidence is insufficient. Win rate is from observed **closing orders** (not completed round-trip trades). Profit factor is based on observed closing-order realized PnL; realized PnL net excludes funding. Drawdown is a **realized-PnL curve proxy**, not account equity drawdown. Equity and leaderboard return figures need not reconcile due to open positions, funding, deposits/withdrawals, history windows and missing fills.

### Dashboard compatibility
The existing Cloudflare Worker V4 remains deployed independently. It displays only the first 20 ranking results and the older Finder still uses an initial screening score (which may show 100/100). **Do not interpret the old Finder score as the V4.1 trader-quality score.** Updating Cloudflare requires a separate deployment.

### Files
- `candidates.json`: auto-updated public candidate shortlist.
- `ranking.json`: rotated evaluations, including `batchIndex`, `pendingCount`, and `checkedAt` for newly evaluated wallets.
- `position_state.json` and `alerts.json`: best-effort position snapshots.
- Secrets `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are stored in GitHub Actions Secrets, not in the repository.


## V4.2 — Whale Market Overview / conditional paper setups

Workflow: `Build Whale Market Overview` (`.github/workflows/market-overview.yml`).
Produces `market_overview.json` with counts and approximate notional LONG/SHORT positions for observed wallets (not all traders), and `setups.json` with either `NO_TRADE` or carefully limited conditional research scenarios.

**No automatic LONG/SHORT recommendation is sent.** Trading suggestions are deliberately withheld from Telegram until a prospective paper-trading period establishes signal quality after spreads, exchange fees, realistic delays and adverse fills.

Research setup requires: at least two separately addressed wallets with recent EVALUATED ranking score >=65, positive observed net realized PnL, observed closing-order profit factor >=1.5, drawdown proxy <=10% and >=10 closing days; a recent qualifying opening/increase; synchronized not-stale snapshots; BTC/ETH/SOL market only; 24-hour volume >=$20m, spread <=12bps, two-timeframe EMA trend agreement, and ATR-based stop and target with modeled net RR >=1.55. **Two addresses do not prove two independently owned traders.**

Entry levels are an indicative *snapshot from Hyperliquid at validation*, not a guaranteed executable Binance quote. A 15-minute expiry is attached. Per-idea risk cap in the hypothetical Rp500,000 bankroll is Rp5,000; no automatic trading, leverage or broker order instruction is implemented. In normal operation NO_TRADE may be frequent (and desirable).
