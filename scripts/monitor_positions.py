"""Observe snapshots of public Hyperliquid positions (not a copy-trading service).
Run every ~10 minutes; no alerts during the initial baseline.
GitHub Actions timing is best effort, so this is NOT a realtime trading feed.
"""
import json
import math
import os
from pathlib import Path
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from selection_rules import is_qualified

ROOT = Path(__file__).resolve().parent.parent
CANDIDATES = ROOT / "candidates.json"
STATE = ROOT / "position_state.json"
ALERTS = ROOT / "alerts.json"
API = "https://api.hyperliquid.xyz/info"
WATCH_TOP_N = max(1, min(40, int(os.getenv("WATCH_TOP_N", "20"))))
MIN_NOTIONAL = max(0, float(os.getenv("MIN_ALERT_NOTIONAL_USD", "10000")))
MIN_CHANGE = 0.10

def now():
    return datetime.now(timezone.utc).isoformat()

def read_json(path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))

def number(value):
    try:
        v = float(value)
        return v if math.isfinite(v) else 0.0
    except (ValueError, TypeError, OverflowError):
        return 0.0

def positions_for(address):
    body = json.dumps({"type": "clearinghouseState", "user": address}).encode()
    request = urllib.request.Request(API, data=body, headers={
        "Content-Type": "application/json",
        "User-Agent": "WhaleIntelligenceMonitor/3.0",
    })
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                obj = json.loads(response.read(3 * 1024 * 1024))
            if not isinstance(obj, dict) or not isinstance(obj.get("assetPositions"), list):
                raise RuntimeError("Invalid clearinghouseState payload")
            result = {}
            for row in obj["assetPositions"]:
                p = row.get("position", {}) if isinstance(row, dict) else {}
                coin = str(p.get("coin", ""))
                size = number(p.get("szi"))
                if not coin or not size:
                    continue
                result[coin] = {
                    "side": "LONG" if size > 0 else "SHORT",
                    "size": round(abs(size), 9),
                    "entry": number(p.get("entryPx")),
                    "notional": abs(number(p.get("positionValue"))),
                }
            return result
        except (urllib.error.URLError, TimeoutError, ValueError, RuntimeError) as exc:
            print(f"INFO {address[:10]} attempt {attempt + 1}: {exc}")
            if attempt == 2:
                raise
            time.sleep(1 + attempt * 2)

def change_events(address, previous, current):
    events = []
    for coin in sorted(set(previous) | set(current)):
        before, after = previous.get(coin), current.get(coin)
        ref = after or before
        notional = max(number(before.get("notional")) if before else 0,
                       number(after.get("notional")) if after else 0)
        if notional < MIN_NOTIONAL:
            continue
        if before is None:
            kind = "OPEN"
        elif after is None:
            kind = "CLOSE"
        elif before["side"] != after["side"]:
            kind = "REVERSE"
        else:
            old = number(before.get("size"))
            new = number(after.get("size"))
            if old <= 0 or abs(new - old) / old < MIN_CHANGE:
                continue
            kind = "INCREASE" if new > old else "DECREASE"
        events.append({
            "id": f"{address.lower()}:{coin}:{kind}:{now()}",
            "time": now(), "address": address, "coin": coin, "event": kind,
            "side": ref["side"], "sizeBefore": number(before.get("size")) if before else 0,
            "sizeAfter": number(after.get("size")) if after else 0,
            "notional": round(notional, 2),
            "entry": number(after.get("entry")) if after else 0,
        })
    return events

def telegram_send(message):
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token and not chat_id:
        print("Telegram not configured: alerts saved to JSON only.")
        return
    if not token or not chat_id:
        raise RuntimeError("Both TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are required")
    if "\n" in token or "/" in token or ":" not in token:
        raise RuntimeError("Invalid Telegram token format")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps({
        "chat_id": chat_id,
        "text": message[:4000],
        "disable_web_page_preview": True,
    }).encode()
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=25) as response:
            result = json.loads(response.read(200000))
        if result.get("ok") is not True:
            raise RuntimeError("Telegram returned ok=false")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Telegram HTTP {exc.code} (check secret configuration)") from exc

def main():
    snapshot = read_json(CANDIDATES, {})
    if not isinstance(snapshot.get("candidates"), list):
        raise RuntimeError("Candidates are not available: run Update Smart Money Candidates first")
    updated = datetime.fromisoformat(snapshot["updatedAt"].replace("Z", "+00:00"))
    if (datetime.now(timezone.utc) - updated).total_seconds() > 72 * 3600:
        raise RuntimeError("Candidate list older than 72 hours: refusing stale monitoring")
    # Research-qualified wallets first; fill remaining slots from the screener.
    # Re-evaluate criteria at runtime rather than trusting a stale static watchlist.
    ranking_rows = read_json(ROOT / "ranking.json", {"ranking": []}).get("ranking", [])
    priority_addresses = [r.get("address", "") for r in ranking_rows if is_qualified(r)]
    addresses = []
    combined = [{"address": a} for a in priority_addresses] + snapshot["candidates"]
    for candidate in combined:
        address = candidate.get("address", "")
        if isinstance(address, str) and len(address) == 42 and address.startswith("0x"):
            try:
                int(address[2:], 16)
            except ValueError:
                continue
            if address.lower() not in [a.lower() for a in addresses]:
                addresses.append(address)
        if len(addresses) == WATCH_TOP_N:
            break
    if not addresses:
        raise RuntimeError("No valid addresses to monitor")

    old = read_json(STATE, {"wallets": {}})
    old_wallets = old.get("wallets", {})
    if not isinstance(old_wallets, dict):
        raise RuntimeError("Unexpected state format")
    observed = dict(old_wallets)
    # Keep per-wallet timestamps, so stale holdings are not counted as live.
    checked_at = dict(old.get('checkedAtByWallet', {}))
    fresh_events = []
    succeeded = 0
    for addr in addresses:
        key = addr.lower()
        try:
            current = positions_for(addr)
            succeeded += 1
            if key in old_wallets and isinstance(old_wallets[key], dict):
                fresh_events.extend(change_events(addr, old_wallets[key], current))
            else:
                print("Baseline created for wallet:", addr[:10])
            observed[key] = current
            checked_at[key] = now()
        except Exception as exc:
            print("WARNING wallet temporarily unavailable", addr[:10], str(exc))
        time.sleep(0.18)
    if succeeded < max(1, len(addresses) // 2):
        raise RuntimeError("Too many API failures; do not overwrite snapshots")

    observed = {address.lower(): observed[address.lower()] for address in addresses if address.lower() in observed}
    timestamp = now()
    checked_at = {a:checked_at.get(a) for a in observed if checked_at.get(a)}
    STATE.write_text(json.dumps({"lastRun": timestamp, "wallets": observed,
                                "checkedAtByWallet": checked_at},
                                separators=(",", ":"), ensure_ascii=False) + "\n", encoding="utf-8")
    existing = read_json(ALERTS, {"events": []})
    history = existing.get("events", [])
    if not isinstance(history, list):
        history = []
    alerts = (fresh_events + history)[:50]
    ALERTS.write_text(json.dumps({
        "updatedAt": timestamp, "monitoredWallets": len(addresses),
        "checkedWallets": succeeded, "events": alerts,
        "disclaimer": "Snapshot-based; delayed/missed changes possible. Not a trading signal.",
    }, separators=(",", ":"), ensure_ascii=False) + "\n", encoding="utf-8")
    # V4.1 safety: low-quality / insufficient history activity is still logged
    # on the dashboard, but never presented as a high-confidence Telegram alert.
    rankings = read_json(ROOT / "ranking.json", {"ranking": []}).get("ranking", [])
    eligible = {str(item["address"]).lower() for item in rankings if is_qualified(item)}
    priority_events = [event for event in fresh_events if event["address"].lower() in eligible]
    print(f"Quality-gated Telegram: {len(priority_events)}/{len(fresh_events)} priority events; {len(eligible)} eligible wallets.")
    if priority_events:
        entries = []
        for ev in priority_events[:8]:
            entries.append(f"{ev['event']} {ev['coin']} {ev['side']} | {ev['address'][:10]}… "
                           f"| approx. ${ev['notional']:,.0f}")
        note = "🐋 Whale Intelligence — position changes\n" + "\n".join(entries)
        note += "\n\nSnapshot detection, delayed; not a trade signal."
        telegram_send(note)
    print(f"Checked {succeeded}/{len(addresses)} wallets; {len(fresh_events)} events.")

if __name__ == "__main__":
    main()
