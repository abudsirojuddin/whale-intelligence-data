"""V4.7: multi-coin technical screening with explicit failure reasons.

Observational research only. No wallet copying, order placement, or guaranteed
trading signals. A technical pass does NOT mean whale consensus exists.
"""
import json
import math
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from market_universe import RESEARCH_COINS, MIN_24H_VOLUME_USD, MAX_BID_ASK_SPREAD_BPS

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "market_scan.json"
API = "https://api.hyperliquid.xyz/info"
TIMEOUT_SECONDS = 18
TTL_SECONDS = 300
INTERVALS = (("15m", 900_000), ("1h", 3_600_000))

def numeric(x):
    try:
        v = float(x)
        return v if math.isfinite(v) else 0.0
    except (TypeError, ValueError, OverflowError):
        return 0.0

def at(t):
    return datetime.fromtimestamp(t, timezone.utc).isoformat()

def call(payload):
    request = urllib.request.Request(
        API, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "WhaleIntelligence/4.7"},
        method="POST",
    )
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as resp:
                return json.loads(resp.read(4_000_000))
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504) or attempt == 2:
                raise
        except (urllib.error.URLError, TimeoutError, ValueError):
            if attempt == 2:
                raise
        time.sleep(1.5 * (attempt + 1))
    raise RuntimeError("Exchange request failed")

def ema(prices, period):
    if len(prices) < period:
        raise ValueError("Not enough bars for EMA")
    x = sum(prices[:period]) / period
    for p in prices[period:]:
        x += (p - x) * (2 / (period + 1))
    return x

def extract_bars(raw, now_ms, interval_ms):
    if not isinstance(raw, list):
        raise ValueError("Bad candle schema")
    bars = []
    for b in raw:
        if not isinstance(b, dict):
            continue
        end = int(numeric(b.get("T")))
        op, hi, lo, close = (numeric(b.get(k)) for k in ("o", "h", "l", "c"))
        if (end <= 0 or end > now_ms or op <= 0 or close <= 0 or lo <= 0
                or hi < max(op, close, lo) or lo > min(op, close, hi)):
            continue
        bars.append((end, op, hi, lo, close))
    bars = sorted(set(bars), key=lambda b: b[0])[-75:]
    if len(bars) < 65:
        raise ValueError("INSUFFICIENT_CANDLES")
    if now_ms - bars[-1][0] > interval_ms + 120_000:
        raise ValueError("STALE_CANDLES")
    return bars

def assess_market(coin, ctx, now, requester=call):
    out = {"coin": coin, "status": "REJECTED",
           "reasons": [], "liquidity": {}, "trend": {}, "paperScenarios": {}}
    mark = numeric(ctx.get("markPx"))
    volume = numeric(ctx.get("dayNtlVlm"))
    out["liquidity"]["volume24hUsd"] = round(volume, 2)
    if mark <= 0:
        out["reasons"].append("INVALID_MARK_PRICE")
        return out
    out["markPrice"] = mark
    if volume < MIN_24H_VOLUME_USD:
        out["reasons"].append("LOW_24H_VOLUME")
        return out
    try:
        book = requester({"type": "l2Book", "coin": coin})
        levels = book.get("levels", [])
        if not isinstance(levels, list) or len(levels) < 2 or not levels[0] or not levels[1]:
            raise ValueError("NO_ORDER_BOOK")
        bid = numeric(levels[0][0].get("px"))
        ask = numeric(levels[1][0].get("px"))
        if not (0 < bid < ask):
            raise ValueError("INVALID_BID_ASK")
        mid = (bid + ask) / 2
        spread = (ask - bid) / mid * 10_000
        out["liquidity"]["spreadBps"] = round(spread, 3)
        if spread > MAX_BID_ASK_SPREAD_BPS:
            raise ValueError("SPREAD_TOO_WIDE")
        # A grossly stale mark is not a current entry price.
        if abs(mark - mid) / mid > 0.02:
            raise ValueError("MARK_BOOK_MISMATCH")
        bars = {}
        for interval, millis in INTERVALS:
            raw = requester({"type": "candleSnapshot", "req": {
                "coin": coin, "interval": interval,
                "startTime": int(now * 1000) - 78 * millis,
                "endTime": int(now * 1000),
            }})
            bars[interval] = extract_bars(raw, int(now * 1000), millis)
        close15 = [b[4] for b in bars["15m"]]
        close1h = [b[4] for b in bars["1h"]]
        f15, s15 = ema(close15, 21), ema(close15, 50)
        f1h, s1h = ema(close1h, 21), ema(close1h, 50)
        trend = ("LONG" if close15[-1] > f15 > s15 and f1h > s1h
                 else "SHORT" if close15[-1] < f15 < s15 and f1h < s1h
                 else "MIXED")
        out["trend"] = {"direction": trend,
                        "ema21_15m": round(f15, 6), "ema50_15m": round(s15, 6),
                        "ema21_1h": round(f1h, 6), "ema50_1h": round(s1h, 6)}
        tr = [max(
            bars["15m"][i][2] - bars["15m"][i][3],
            abs(bars["15m"][i][2] - bars["15m"][i-1][4]),
            abs(bars["15m"][i][3] - bars["15m"][i-1][4]),
        ) for i in range(1, len(bars["15m"]))]
        atr = sum(tr[-14:]) / 14
        if not 0.0018 <= atr / mark <= 0.027:
            raise ValueError("VOLATILITY_OUT_OF_RANGE")
        if abs(mark - close15[-1]) > 0.8 * atr or abs(mark - f15) > 1.2 * atr:
            raise ValueError("PRICE_TOO_FAR_FROM_TREND")
        risk = 1.2 * atr
        if not 0.0025 <= risk / mark <= 0.025:
            raise ValueError("STOP_DISTANCE_OUT_OF_RANGE")
        effective_rr = (2 * risk - 0.002 * mark) / (risk + 0.002 * mark)
        if effective_rr < 1.55:
            raise ValueError("RISK_REWARD_TOO_LOW")
        if trend == "MIXED":
            raise ValueError("TREND_NOT_ALIGNED")
        direction = 1 if trend == "LONG" else -1
        area_low = mark - 0.15 * atr
        area_high = mark + 0.15 * atr
        stop = mark - direction * risk
        tp1 = mark + direction * 2 * risk
        tp2 = mark + direction * 3 * risk
        if not (stop < area_low < area_high < tp1 if direction == 1
                else tp1 < area_low < area_high < stop):
            raise ValueError("INVALID_PRICE_ORDER")
        out["status"] = "TECHNICAL_PASS"
        out["paperScenarios"][trend] = {
            "markPrice": round(mark, 8), "entryZoneLow": round(area_low, 8),
            "entryZoneHigh": round(area_high, 8), "stopLoss": round(stop, 8),
            "takeProfit1": round(tp1, 8), "takeProfit2": round(tp2, 8),
            "estimatedNetRR": round(effective_rr, 3),
            "spreadBps": round(spread, 3), "expiresAt": at(now + 900),
        }
    except (ValueError, KeyError, TypeError) as exc:
        out["reasons"].append(str(exc))
    except (urllib.error.URLError, TimeoutError, OSError):
        out["reasons"].append("EXCHANGE_API_UNAVAILABLE")
    return out

def main():
    now = time.time()
    markets = []
    source_ok = True
    try:
        info = call({"type": "metaAndAssetCtxs"})
        if not isinstance(info, list) or len(info) < 2:
            raise ValueError("Invalid metaAndAssetCtxs")
        universe = info[0].get("universe", [])
        contexts = info[1]
        contexts_by_coin = {m.get("name"): contexts[i] for i,m in enumerate(universe)
                            if isinstance(m, dict) and i < len(contexts)}
    except (urllib.error.URLError, TimeoutError, ValueError, OSError, KeyError) as exc:
        print("Market metadata unavailable", type(exc).__name__)
        contexts_by_coin = {}
        source_ok = False
    for coin in sorted(RESEARCH_COINS):
        if coin not in contexts_by_coin:
            markets.append({"coin": coin, "status": "UNAVAILABLE",
                            "reasons": ["ASSET_OR_META_UNAVAILABLE"], "paperScenarios": {}})
            continue
        result = assess_market(coin, contexts_by_coin[coin], now)
        markets.append(result)
        time.sleep(0.12)
    successful = [m for m in markets if m.get("status") == "TECHNICAL_PASS"]
    result = {
        "updatedAt": at(now), "expiresAt": at(now + TTL_SECONDS),
        "apiHealthy": source_ok, "assetsChecked": len(markets),
        "technicalPassCount": len(successful), "coins": markets,
        "disclaimer": "Technical observation only, NOT an executable trade signal. Exchange snapshots and prices may differ from Binance."
    }
    # Explicitly mark unavailable data; never reuse a silently stale older pass.
    OUT.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print("Multi-coin scan",len(markets),"technical passes",len(successful),"apiHealthy",source_ok)

if __name__ == "__main__":
    main()
