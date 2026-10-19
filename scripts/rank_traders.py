"""V4: rank public Hyperliquid wallets using observable fills.
Metrics are estimates, not verified round-trip trades or investment signals.
No API keys, trades, or account access are used.
"""
import json
import math
import os
import pathlib
import time
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent
INPUT = ROOT / "candidates.json"
OUTPUT = ROOT / "ranking.json"
API = "https://api.hyperliquid.xyz/info"
WINDOW_DAYS = 30
MAX_PAGES = 4
PAGE_SIZE = 2000
MIN_CLOSE_ORDERS = 20
MIN_ACTIVE_DAYS = 7

def safe(value):
    try:
        n = float(value)
        return n if math.isfinite(n) else 0.0
    except (TypeError, ValueError, OverflowError):
        return 0.0

def bounded(value, low=0.0, high=1.0):
    return min(high, max(low, value))

def post_info(payload, attempts=3):
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    req = urllib.request.Request(API, data=body, headers={
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "WhaleIntelligenceResearch/4.0",
    }, method="POST")
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=35) as res:
                return json.loads(res.read(8 * 1024 * 1024))
        except (urllib.error.URLError, TimeoutError, ValueError) as err:
            if attempt == attempts - 1:
                raise RuntimeError(f"Info API unavailable: {type(err).__name__}") from err
            time.sleep(2 * (attempt + 1))

def get_fills(address, since_ms, until_ms):
    # userFillsByTime has <=2000 rows per response and limited retention.
    # Avoid implying full coverage when our page budget is reached.
    unique = {}
    cursor = since_ms
    truncated = False
    for page_index in range(MAX_PAGES):
        page = post_info({
            "type": "userFillsByTime", "user": address,
            "startTime": cursor, "endTime": until_ms,
            "aggregateByTime": False,
        })
        if not isinstance(page, list):
            raise RuntimeError("Unexpected userFillsByTime schema")
        if not page:
            break
        for index, item in enumerate(page):
            if not isinstance(item, dict):
                continue
            stamp = int(safe(item.get("time")))
            if stamp < since_ms or stamp > until_ms:
                continue
            identity = str(item.get("tid") or "") or (
                f"{stamp}:{item.get('oid')}:{item.get('coin')}:{index}:{page_index}"
            )
            unique[identity] = item
        if len(page) < PAGE_SIZE:
            break
        latest = max(int(safe(item.get("time"))) for item in page if isinstance(item, dict))
        # If >2000 fills share the boundary timestamp we cannot paginate safely.
        if latest <= cursor or latest >= until_ms or page_index == MAX_PAGES - 1:
            truncated = True
            break
        cursor = latest + 1
    ordered = sorted(unique.values(), key=lambda x: (int(safe(x.get("time"))), str(x.get("tid", ""))))
    return ordered, truncated

def calculate_metrics(fills, account_value, incomplete=False):
    # fee and closedPnl in USDC are used. Funding is NOT included.
    by_order = defaultdict(float)
    pnl_events = []
    total_closed_gross = 0.0
    fees = 0.0
    active_days = set()
    close_days = set()
    non_usdc_fees = 0
    for fill in fills:
        direction = str(fill.get("dir") or "").lower()
        coin = str(fill.get("coin") or "")
        # Exclude spot fills such as @1 and BTC/USDC.
        if coin.startswith("@") or "/" in coin:
            continue
        if not (("long" in direction or "short" in direction) and coin):
            continue
        timestamp = int(safe(fill.get("time")))
        active_days.add(datetime.fromtimestamp(timestamp / 1000, timezone.utc).date().isoformat())
        fee_token = str(fill.get("feeToken") or "USDC").upper()
        fee = safe(fill.get("fee"))
        if fee_token != "USDC":
            non_usdc_fees += 1
            fee = 0.0
        fees += fee
        realized = safe(fill.get("closedPnl"))
        total_closed_gross += realized
        is_close = ("close" in direction or ">" in direction or abs(realized) > 1e-10)
        if is_close:
            oid = str(fill.get("oid") or fill.get("tid") or timestamp)
            key = (coin, oid, direction)
            by_order[key] += realized
            close_days.add(datetime.fromtimestamp(timestamp / 1000, timezone.utc).date().isoformat())
        pnl_events.append((timestamp, realized - fee))
    results = list(by_order.values())
    wins = [p for p in results if p > 1e-8]
    losses = [p for p in results if p < -1e-8]
    gross_profit = sum(wins)
    gross_loss = -sum(losses)
    win_rate = len(wins) / (len(wins) + len(losses)) if (wins or losses) else None
    pf = gross_profit / gross_loss if gross_loss > 1e-8 else None
    # Drawdown of cumulative REALIZED fill PnL less fees (USDC).
    # Not the true max equity drawdown: ignores open PnL, funding, and cash movements.
    curve = 0.0
    peak = 0.0
    max_drop = 0.0
    for _, value in sorted(pnl_events):
        curve += value
        peak = max(peak, curve)
        max_drop = max(max_drop, peak - curve)
    dd_proxy_ratio = max_drop / account_value if account_value > 0 else None
    net = total_closed_gross - fees
    qualifying = (not incomplete and not non_usdc_fees and
                  len(results) >= MIN_CLOSE_ORDERS and
                  len(close_days) >= MIN_ACTIVE_DAYS and
                  len(wins) >= 1 and len(losses) >= 1)
    score = None
    if qualifying:
        pf_score = 24 * bounded((math.log(max(pf, 0.05)) + 0.5) / 1.9)
        win_score = 20 * bounded((win_rate - 0.35) / 0.45)
        net_score = 18 * bounded((net / max(account_value, 1) + 0.02) / 0.22)
        risk_score = 20 * (1 - bounded((dd_proxy_ratio or 0) / 0.3))
        activity_score = 10 * bounded(len(close_days) / 22)
        sample_score = 8 * bounded(math.log1p(len(results)) / math.log1p(150))
        score = round(pf_score + win_score + net_score + risk_score +
                      activity_score + sample_score, 1)
    return {
        "score": score,
        "quality": "EVALUATED" if qualifying else ("INCOMPLETE" if incomplete else "INSUFFICIENT"),
        "realizedPnl30": round(total_closed_gross, 2),
        "feesUsdc30": round(fees, 2),
        "netRealizedExFunding30": round(net, 2),
        "winRateCloseOrders30": round(win_rate, 4) if win_rate is not None else None,
        "profitFactorCloseOrders30": round(pf, 3) if pf is not None else None,
        "realizedDrawdownProxy30Usd": round(max_drop, 2),
        "realizedDrawdownProxyToEquity": round(dd_proxy_ratio, 4) if dd_proxy_ratio is not None else None,
        "closingOrders30": len(results),
        "activeDays30": len(active_days),
        "closingDays30": len(close_days),
        "fillCount30": len(fills),
        "historyTruncated": bool(incomplete),
        "nonUsdcFeeFills": non_usdc_fees,
    }

def main():
    data = json.loads(INPUT.read_text(encoding="utf-8"))
    wallets = data.get("candidates", [])[:20]
    if not wallets:
        raise RuntimeError("No candidate wallets, run screener first")
    now = datetime.now(timezone.utc)
    until_ms = int(now.timestamp() * 1000)
    since_ms = int((now - timedelta(days=WINDOW_DAYS)).timestamp() * 1000)
    rows, failed = [], 0
    for index, candidate in enumerate(wallets):
        address = str(candidate.get("address") or "")
        if not (address.startswith("0x") and len(address) == 42):
            continue
        record = {
            "address": address, "name": candidate.get("name", ""),
            "leaderboardPnl30": candidate.get("pnl30"),
            "leaderboardRoi30": candidate.get("roi30"),
            "leaderboardPnl7": candidate.get("pnl7"),
            "accountValue": candidate.get("accountValue"),
            "screeningScore": candidate.get("score"),
        }
        try:
            fills, truncated = get_fills(address, since_ms, until_ms)
            record.update(calculate_metrics(fills, safe(candidate.get("accountValue")), truncated))
            print(f"Wallet {index+1}/{len(wallets)}: {address[:10]} "
                  f"{len(fills)} fills, {record['closingOrders30']} closes, "
                  f"quality={record['quality']}, score={record['score']}")
        except Exception as exc:
            failed += 1
            record.update({
                "score": None, "quality": "UNAVAILABLE",
                "error": "Public fill history temporarily unavailable",
            })
            print(f"Wallet {index+1}/{len(wallets)} unavailable: {type(exc).__name__}")
        rows.append(record)
        time.sleep(0.25)
    if failed == len(rows):
        raise RuntimeError("All wallet requests failed; previous ranking preserved")
    # Qualified first, then insufficient rows; never backfill unknown scores with 100.
    rows.sort(key=lambda x: (x.get("score") is not None,
                             x.get("score") if x.get("score") is not None else -1,
                             safe(x.get("netRealizedExFunding30"))), reverse=True)
    snapshot = {
        "updatedAt": now.isoformat(),
        "windowStart": datetime.fromtimestamp(since_ms / 1000, timezone.utc).isoformat(),
        "windowDays": WINDOW_DAYS,
        "sourceCandidatesUpdatedAt": data.get("updatedAt"),
        "evaluatedCount": sum(r.get("quality") == "EVALUATED" for r in rows),
        "insufficientCount": sum(r.get("quality") in ("INCOMPLETE", "INSUFFICIENT") for r in rows),
        "unavailableCount": sum(r.get("quality") == "UNAVAILABLE" for r in rows),
        "methodology": {
            "winRate": "Winning closing orders / (winning + losing closing orders), gross closedPnl; not independent round-trip trade win rate.",
            "profitFactor": "Gross closedPnl of winning closing orders / absolute gross closedPnl of losing closing orders; excludes fees and funding.",
            "netRealized": "Sum closedPnl minus all USDC fill fees in the observed 30-day period; excludes funding, open/unrealized PnL.",
            "drawdown": "Maximum peak-to-trough decline of cumulative realized fill PnL less USDC fees; proxy, not true account/equity max drawdown.",
            "limits": "API 2,000 fills per page, limited history; rankings hidden if <20 closing orders / <7 closing days, missing losses, or capped records. Partial closing fills grouped by order.",
        },
        "ranking": rows,
    }
    OUTPUT.write_text(json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"Ranking updated: {len(rows)} wallets, {snapshot['evaluatedCount']} evaluated, "
          f"{snapshot['unavailableCount']} API failures")

if __name__ == "__main__":
    main()
