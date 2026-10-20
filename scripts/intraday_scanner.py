"""Intraday Intelligence V2: Binance USDT-M paper-only research scanner.

Public market data; never authenticates or places orders.
A high rule score is NOT a probability of winning.
"""
from __future__ import annotations

import json
import math
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = "https://fapi.binance.com"
MIN_VOLUME_USDT = 20_000_000
MAX_SPREAD_BPS = 15
MAX_CANDIDATES = 20
MAX_DAILY_NOTICES = 5
FEE_SLIPPAGE_ROUNDTRIP = .0022
BANKROLL_IDR = 500_000
MAX_RISK_IDR = 5_000
MAX_MARGIN_IDR = 100_000
LEVERAGE_ASSUMED = 3
PERIODS = {"15m": 900_000, "1h": 3_600_000, "4h": 14_400_000}


def number(x, fallback=None):
    try:
        value = float(x)
        return value if math.isfinite(value) else fallback
    except (ValueError, TypeError, OverflowError):
        return fallback


def iso(ts=None):
    return datetime.fromtimestamp(time.time() if ts is None else ts, timezone.utc).isoformat()


def read(name, fallback):
    try:
        return json.loads((ROOT / name).read_text("utf-8"))
    except (FileNotFoundError, ValueError):
        return fallback


def write(name, data):
    (ROOT / name).write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n", "utf-8")


def get_json(path, params=None, retries=2):
    url = BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "WhaleIntelligence-Intraday/2"})
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=18) as response:
                return json.loads(response.read(5_000_000))
        except urllib.error.HTTPError as exc:
            if exc.code not in (418, 429, 500, 502, 503, 504) or attempt == retries:
                raise RuntimeError(f"BINANCE_HTTP_{exc.code}_AT_{path}") from exc
        except (TimeoutError, urllib.error.URLError, ValueError):
            if attempt == retries:
                raise
        time.sleep(1.25 * (attempt + 1))
    raise RuntimeError("Unavailable")


def ema(values, n):
    if len(values) < n:
        raise ValueError("SHORT_EMA_HISTORY")
    result = sum(values[:n]) / n
    out = [None] * (n - 1) + [result]
    for value in values[n:]:
        result += (value - result) * 2 / (n + 1)
        out.append(result)
    return out


def rsi(closes, n=14):
    moves = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    if len(moves) < n + 1:
        raise ValueError("SHORT_RSI_HISTORY")
    gain = sum(max(x, 0) for x in moves[:n]) / n
    loss = sum(max(-x, 0) for x in moves[:n]) / n
    for x in moves[n:]:
        gain = (gain * (n - 1) + max(x, 0)) / n
        loss = (loss * (n - 1) + max(-x, 0)) / n
    return 100 if loss == 0 else 100 - 100 / (1 + gain / loss)


def atr(bars, n=14):
    ranges = [max(
        b["high"] - b["low"], abs(b["high"] - bars[i-1]["close"]),
        abs(b["low"] - bars[i-1]["close"])
    ) for i, b in enumerate(bars) if i]
    if len(ranges) < n:
        raise ValueError("SHORT_ATR_HISTORY")
    return sum(ranges[-n:]) / n


def candles(raw, interval, now_ms):
    if not isinstance(raw, list):
        raise ValueError("BAD_KLINES")
    result = []
    for row in raw:
        if not isinstance(row, list) or len(row) < 7:
            continue
        start, end = int(row[0]), int(row[6])
        op, high, low, close, vol = [number(row[i]) for i in (1, 2, 3, 4, 5)]
        if (end >= now_ms or None in (op, high, low, close, vol)
                or min(op, high, low, close) <= 0 or high < max(op, close)
                or low > min(op, close) or vol < 0):
            continue  # Never use a still-forming candle.
        result.append({"start": start, "end": end, "open": op, "high": high,
                       "low": low, "close": close, "volume": vol})
    result.sort(key=lambda b: b["start"])
    if len(result) < 70:
        raise ValueError("INSUFFICIENT_CLOSED_CANDLES")
    if now_ms - result[-1]["end"] > PERIODS[interval] + 180_000:
        raise ValueError("STALE_CANDLES")
    if any(result[i]["start"] - result[i-1]["start"] != PERIODS[interval]
           for i in range(len(result) - 59, len(result))):
        raise ValueError("GAPPED_CANDLES")
    return result


def setup_direction(b15, b1h, b4h):
    c15 = [b["close"] for b in b15]
    c1 = [b["close"] for b in b1h]
    c4 = [b["close"] for b in b4h]
    e15, e1, e4 = ema(c15, 20), ema(c1, 20), ema(c4, 20)
    s15, s1, s4 = ema(c15, 50), ema(c1, 50), ema(c4, 50)
    long = (c4[-1] > e4[-1] > s4[-1] and c1[-1] > e1[-1] > s1[-1]
            and c15[-1] > e15[-1] > s15[-1])
    short = (c4[-1] < e4[-1] < s4[-1] and c1[-1] < e1[-1] < s1[-1]
             and c15[-1] < e15[-1] < s15[-1])
    return ("LONG" if long else "SHORT" if short else None), e15


def detect_pattern(b, ema20, a, direction):
    current, prev = b[-1], b[-2]
    s = 1 if direction == "LONG" else -1
    pullback = (
        (prev["low"] <= ema20[-2] + .35 * a if s == 1
         else prev["high"] >= ema20[-2] - .35 * a)
        and s * (current["close"] - current["open"]) > 0
        and s * (current["close"] - ema20[-1]) > 0
        and s * (current["close"] - prev["close"]) > 0
    )
    if pullback:
        return "TREND_PULLBACK"
    previous = b[-17:-2]
    if len(previous) < 14:
        return None
    level = max(x["high"] for x in previous) if s == 1 else min(x["low"] for x in previous)
    breakout = (s * (prev["close"] - level) > .001 * level
                and (current["low"] <= level + .25*a if s == 1
                     else current["high"] >= level - .25*a)
                and s * (current["close"] - level) > 0
                and s * (current["close"] - current["open"]) > 0)
    return "BREAKOUT_RETEST" if breakout else None


def analyze(symbol, bars, book, funding, oi_rows, now_ms):
    b15, b1, b4 = bars["15m"], bars["1h"], bars["4h"]
    direction, ema20 = setup_direction(b15, b1, b4)
    if not direction:
        raise ValueError("TREND_NOT_ALIGNED")
    s = 1 if direction == "LONG" else -1
    last = b15[-1]
    a = atr(b15)
    if not .002 <= a / last["close"] <= .04:
        raise ValueError("VOLATILITY_OUT_OF_RANGE")
    pattern = detect_pattern(b15, ema20, a, direction)
    if not pattern:
        raise ValueError("NO_CONFIRMED_SETUP")
    strength = rsi([x["close"] for x in b15])
    if not ((52 <= strength <= 72) if s == 1 else (28 <= strength <= 48)):
        raise ValueError("RSI_MOMENTUM_NOT_CONFIRMED")
    vol_ratio = last["volume"] / max(1e-12, sum(x["volume"] for x in b15[-21:-1]) / 20)
    if vol_ratio < 1.10:
        raise ValueError("VOLUME_NOT_CONFIRMED")
    rate = number(funding.get("lastFundingRate"))
    if rate is None or abs(rate) > .0015:
        raise ValueError("FUNDING_RISK_OR_UNAVAILABLE")
    if not isinstance(oi_rows, list) or len(oi_rows) < 2:
        raise ValueError("OI_NOT_AVAILABLE")
    oi_old = number(oi_rows[0].get("sumOpenInterestValue"))
    oi_new = number(oi_rows[-1].get("sumOpenInterestValue"))
    latest_oi = number(oi_rows[-1].get("timestamp"))
    if (not oi_old or not oi_new or oi_old <= 0 or oi_new <= 0
            or latest_oi is None or now_ms - latest_oi > 50 * 60_000):
        raise ValueError("OI_STALE_OR_INVALID")
    oi_change = oi_new / oi_old - 1
    if oi_change < -.03:
        raise ValueError("OI_CONTRACTING")
    bid, ask = number(book.get("bidPrice")), number(book.get("askPrice"))
    if not bid or not ask or bid >= ask:
        raise ValueError("INVALID_ORDER_BOOK")
    spread = (ask - bid) / ((bid + ask) / 2) * 10_000
    if spread > MAX_SPREAD_BPS:
        raise ValueError("SPREAD_TOO_WIDE")
    entry = ask if s == 1 else bid
    if abs(entry - last["close"]) / last["close"] > max(.004, .6 * a / last["close"]):
        raise ValueError("PRICE_MOVED_SINCE_CANDLE")
    swing = (min(x["low"] for x in b15[-6:]) - .2 * a if s == 1
             else max(x["high"] for x in b15[-6:]) + .2 * a)
    stop = (min(swing, entry - 1.25*a) if s == 1
            else max(swing, entry + 1.25*a))
    distance = abs(entry - stop)
    risk_pct = distance / entry
    if not .004 <= risk_pct <= .025:
        raise ValueError("STOP_DISTANCE_OUT_OF_RANGE")
    target = entry + s * 3.0 * distance
    rr_net = (3.0*distance - FEE_SLIPPAGE_ROUNDTRIP*entry) / (
        distance + FEE_SLIPPAGE_ROUNDTRIP*entry)
    if rr_net < 2.0:
        raise ValueError("NET_RR_TOO_LOW")
    score = (20 + 20
             + (15 if 55 <= strength <= 68 else 10)
             + (15 if vol_ratio >= 1.5 else 10)
             + (15 if oi_change >= 0 else 10)
             + (15 if .005 <= risk_pct <= .018 else 10))
    if score < 85:
        raise ValueError("QUALITY_SCORE_TOO_LOW")
    risk_fraction_including_cost = risk_pct + FEE_SLIPPAGE_ROUNDTRIP
    notional_idr = min(MAX_MARGIN_IDR * LEVERAGE_ASSUMED,
                       MAX_RISK_IDR / risk_fraction_including_cost)
    risk_idr = round(notional_idr * risk_fraction_including_cost)
    return {
        "symbol": symbol, "direction": direction, "strategy": pattern,
        "score": score, "timeframe": "15m", "candleEndMs": last["end"],
        "entry": round(entry, 9), "stopLoss": round(stop, 9),
        "takeProfit1": round(target, 9), "netRR": round(rr_net, 2),
        "spreadBps": round(spread, 2), "rsi14": round(strength, 1),
        "volumeRatio": round(vol_ratio, 2), "openInterestChange": round(oi_change, 4),
        "fundingRate": rate, "riskPct": round(risk_pct * 100, 2),
        "assumedPositionIdr": round(notional_idr), "assumedMarginIdr": round(notional_idr/LEVERAGE_ASSUMED),
        "maxEstimatedRiskIdr": risk_idr,
        "status": "PAPER_ONLY", "exchange": "Binance USDT-M",
        "notes": "Simulation, not an executable order. No fills or profitability proven."
    }


def shortlist(exchange, tickers, books, funding, now_ms):
    valid = {x.get("symbol"): x for x in exchange.get("symbols", [])
             if x.get("contractType") == "PERPETUAL" and x.get("status") == "TRADING"
             and x.get("quoteAsset") == "USDT" and x.get("symbol", "").endswith("USDT")
             and now_ms - (number(x.get("onboardDate"), 0) or 0) > 30 * 86400_000}
    by_book = {x.get("symbol"): x for x in books if isinstance(x, dict)}
    by_fund = {x.get("symbol"): x for x in funding if isinstance(x, dict)}
    ranked = []
    for t in tickers:
        symbol = t.get("symbol")
        if symbol not in valid or symbol not in by_book or symbol not in by_fund:
            continue
        volume = number(t.get("quoteVolume"), 0)
        change = abs(number(t.get("priceChangePercent"), 0))
        bid = number(by_book[symbol].get("bidPrice"))
        ask = number(by_book[symbol].get("askPrice"))
        if not (volume >= MIN_VOLUME_USDT and bid and ask and 0 < bid < ask):
            continue
        spread = (ask-bid)/((ask+bid)/2)*10_000
        if spread > MAX_SPREAD_BPS or change > 25:
            continue
        rank = math.log10(volume) * 2 + min(change, 12)/3
        ranked.append((rank, symbol))
    ranked.sort(reverse=True)
    return [s for _, s in ranked[:MAX_CANDIDATES]], by_book, by_fund


def fetch_bars(symbol, now_ms):
    return {interval: candles(
        get_json("/fapi/v1/klines", {"symbol": symbol, "interval": interval, "limit": 120}),
        interval, now_ms) for interval in ("4h", "1h", "15m")}


def telegram(message):
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if os.getenv("ENABLE_INTRADAY_PAPER_ALERTS") != "true":
        return False
    if not (token and chat and ":" in token and "/" not in token and chat.lstrip("-").isdigit()):
        return False
    req = urllib.request.Request(
        "https://api.telegram.org/bot" + token + "/sendMessage",
        data=json.dumps({"chat_id": chat, "text": message[:3900]}).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            return json.loads(response.read(50000)).get("ok") is True
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError, TimeoutError):
        print("Telegram notification unavailable (no credentials logged).")
        return False


def message(s):
    return ("\U0001f9ea WHALE INTELLIGENCE — PAPER SETUP (BUKAN ENTRY NYATA)\n"
            f"{s['symbol']} {s['direction']} | {s['strategy']}\n"
            f"Skor aturan {s['score']}/100 (bukan probabilitas menang)\n"
            f"Entry indikatif {s['entry']}\nSL simulasi {s['stopLoss']}\n"
            f"TP simulasi {s['takeProfit1']} | Est. RR bersih {s['netRR']}\n"
            f"Risiko simulasi ~Rp{s['maxEstimatedRiskIdr']:,} | "
            f"Margin simulasi ~Rp{s['assumedMarginIdr']:,}\n"
            f"Kadaluarsa UTC {s['expiresAt']}\n"
            "Belum tervalidasi melalui paper trading. Jangan salin otomatis.")


def main():
    now = time.time()
    now_ms = int(now * 1000)
    state = read("intraday_state.json", {"sent": {}})
    sent = {k: v for k, v in state.get("sent", {}).items()
            if isinstance(v, dict) and now - number(v.get("at"), 0) < 7 * 86400}
    history = read("intraday_signals.json", {"signals": []}).get("signals", [])
    if not isinstance(history, list):
        history = []
    status = {"updatedAt": iso(now), "source": "Binance USDT-M",
              "mode": "PAPER_ONLY", "status": "NO_TRADE", "eligibleUniverse": 0,
              "candidatesAnalyzed": 0, "rejectionCounts": {}, "newSignals": [],
              "disclaimer": "Rules-based research only. No automatic trading, no demonstrated edge."}
    try:
        exchange = get_json("/fapi/v1/exchangeInfo")
        tickers = get_json("/fapi/v1/ticker/24hr")
        books = get_json("/fapi/v1/ticker/bookTicker")
        funding = get_json("/fapi/v1/premiumIndex")
        if not (isinstance(exchange, dict) and isinstance(tickers, list)
                and isinstance(books, list) and isinstance(funding, list)):
            raise ValueError("Bad Binance API metadata")
        selected, by_book, by_fund = shortlist(exchange, tickers, books, funding, now_ms)
        status["eligibleUniverse"] = len(selected)
        for symbol in selected:
            status["candidatesAnalyzed"] += 1
            try:
                bars = fetch_bars(symbol, now_ms)
                oi_rows = get_json("/futures/data/openInterestHist",
                                   {"symbol": symbol, "period": "15m", "limit": 3})
                signal = analyze(symbol, bars, by_book[symbol], by_fund[symbol], oi_rows, now_ms)
                signal["createdAt"] = iso()
                signal["expiresAt"] = iso(time.time() + 30 * 60)
                signal["id"] = ("%s-%s-%s-%s" % (symbol, signal["direction"],
                            signal["strategy"], signal["candleEndMs"]))
                if signal["id"] not in sent:
                    status["newSignals"].append(signal)
                    sent[signal["id"]] = {"at": now, "notified": False}
                    history.append(signal)
            except (ValueError, KeyError, TypeError, IndexError, RuntimeError, urllib.error.HTTPError,
                    urllib.error.URLError, TimeoutError, OSError) as exc:
                why = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
                status["rejectionCounts"][why] = status["rejectionCounts"].get(why, 0) + 1
        if status["newSignals"]:
            status["status"] = "PAPER_SETUPS_FOUND"
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ValueError, RuntimeError, OSError) as exc:
        status["status"] = "DATA_UNAVAILABLE"
        status["error"] = str(exc)[:100] if isinstance(exc, RuntimeError) else ("INVALID_METADATA" if isinstance(exc, ValueError) else "BINANCE_API_UNAVAILABLE")
        print("Fail closed: Binance data unavailable", status["error"])
    day = datetime.fromtimestamp(now, timezone(timedelta(hours=7))).date().isoformat()
    # Up to five paper research notifications each Jakarta day. No quota to fill.
    notices = sum(1 for v in sent.values() if v.get("notified")
                  and datetime.fromtimestamp(v["at"], timezone(timedelta(hours=7))).date().isoformat() == day)
    for signal in status["newSignals"]:
        if notices >= MAX_DAILY_NOTICES:
            break
        if telegram(message(signal)):
            sent[signal["id"]]["notified"] = True
            notices += 1
    write("intraday_state.json", {"updatedAt": iso(), "sent": sent})
    write("intraday_signals.json", {"updatedAt": iso(), "signals": history[-300:],
          "mode": "PAPER_ONLY"})
    write("intraday_scan.json", status)
    print("Intraday:", status["status"], "checked", status["candidatesAnalyzed"],
          "new", len(status["newSignals"]), "rejections", status["rejectionCounts"])


if __name__ == "__main__":
    main()
