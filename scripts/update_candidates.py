"""Read-only screening of public Hyperliquid leaderboard wallets.
Not a win-rate measure, verified perp-only performance, or trade recommendation.
"""
import json
import math
import pathlib
import time
import urllib.request
from datetime import datetime, timezone

SOURCE = "https://stats-data.hyperliquid.xyz/Mainnet/leaderboard"
OUTPUT = pathlib.Path(__file__).resolve().parent.parent / "candidates.json"

def numeric(value):
    try:
        number = float(value)
        return number if math.isfinite(number) else 0.0
    except (ValueError, TypeError, OverflowError):
        return 0.0

def clamp(value, lo=0.0, hi=1.0):
    return max(lo, min(hi, value))

def get_rows():
    for attempt in range(3):
        try:
            req = urllib.request.Request(SOURCE, headers={
                "User-Agent": "WhaleIntelligenceResearch/2.0",
                "Accept": "application/json",
            })
            with urllib.request.urlopen(req, timeout=90) as response:
                raw = response.read(100 * 1024 * 1024 + 1)
                if len(raw) > 100 * 1024 * 1024:
                    raise RuntimeError("Leaderboard size exceeds 100 MB")
            data = json.loads(raw)
            rows = data.get("leaderboardRows")
            if not isinstance(rows, list):
                raise RuntimeError("Leaderboard schema changed: leaderboardRows missing")
            return rows
        except Exception as exc:
            print(f"Attempt {attempt+1} failed: {exc}")
            if attempt == 2:
                raise
            time.sleep(3 + attempt * 5)

def screen(row):
    address = row.get("ethAddress")
    if not isinstance(address, str) or len(address) != 42 or not address.startswith("0x"):
        return None
    try:
        int(address[2:], 16)
    except ValueError:
        return None

    windows = {}
    for item in row.get("windowPerformances") or []:
        if isinstance(item, (list, tuple)) and len(item) == 2:
            name, values = item
            if isinstance(name, str) and isinstance(values, dict):
                windows[name] = values
    month, week, lifetime = (windows.get(key, {}) for key in ("month", "week", "allTime"))
    pnl30, pnl7 = numeric(month.get("pnl")), numeric(week.get("pnl"))
    roi30, roi7 = numeric(month.get("roi")), numeric(week.get("roi"))
    volume30 = numeric(month.get("vlm"))
    equity = numeric(row.get("accountValue"))
    all_pnl = numeric(lifetime.get("pnl"))
    # These coarse thresholds exclude obvious low-activity/anomalous accounts.
    if not (equity >= 2000 and pnl30 >= 500 and pnl7 > 0 and
            0.03 <= roi30 <= 1.5 and volume30 >= 10000 and all_pnl >= 0):
        return None
    score = round(
        25 * clamp(roi30 / 0.5) +
        20 * clamp(roi7 / 0.2) +
        20 +
        15 * clamp(math.log10(volume30 + 1) / 7) +
        10 * clamp(math.log10(equity + 1) / 6) +
        (10 if all_pnl > 0 else 0)
    )
    return {
        "address": address, "name": str(row.get("displayName") or "")[:50],
        "score": score, "pnl30": round(pnl30, 2), "roi30": round(roi30, 5),
        "pnl7": round(pnl7, 2), "roi7": round(roi7, 5),
        "accountValue": round(equity, 2), "vol30": round(volume30, 2),
    }

def main():
    rows = get_rows()
    selected = []
    for row in rows:
        if isinstance(row, dict):
            item = screen(row)
            if item:
                selected.append(item)
    selected.sort(key=lambda item: (item["score"], item["pnl30"]), reverse=True)
    # Preserve the established top 20 so existing V3 monitoring has stable identities.
    # Diversify the remaining 80 by observed volume to find accounts whose recent
    # fills have a better chance of being fully available from the public API.
    top, seen = [], set()
    def add(items, limit):
        for item in items:
            if len(top) >= limit:
                break
            address = item["address"].lower()
            if address in seen:
                continue
            seen.add(address)
            top.append(item)
            if len(top) >= limit:
                break

    add(selected, 20)
    smaller = [r for r in selected if 10000 <= r["vol30"] <= 5000000]
    mid = [r for r in selected if 5000000 < r["vol30"] <= 50000000]
    large = [r for r in selected if r["vol30"] > 50000000]
    # A diversity heuristic, not proof that fills will be available.
    add(smaller, 55)
    add(mid, 85)
    add(large, 100)
    add(selected, 100)
    if not top:
        raise RuntimeError("No candidates qualified; preserve previous snapshot")
    snapshot = {
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "source": "Hyperliquid public leaderboard (stats endpoint)",
        "dataDisclaimer": "Account-level heuristic; NOT verified Futures-only PnL, win rate, or prediction.",
        "rowsProcessed": len(rows), "filterQualified": len(selected),
        "selectionMethod": "Top 20 original + 80 diversified by monthly traded volume; all unverified candidates",
        "candidateLimit": 100,
        "candidates": top,
    }
    OUTPUT.write_text(json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"Saved {len(top)} candidates from {len(rows)} leaderboard accounts")

if __name__ == "__main__":
    main()
