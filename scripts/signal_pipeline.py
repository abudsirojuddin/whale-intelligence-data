"""V4.5: quality-gated whale alerts and prospective signal funnel.

Research alerts are NOT instructions to trade. A conditional price setup may only
be promoted for manual consideration after a minimum prospective paper sample.
"""
import json
import math
import os
from pathlib import Path
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from urllib import request, error
from selection_rules import is_qualified, number, time_of

ROOT = Path(__file__).resolve().parent.parent
JAKARTA = ZoneInfo("Asia/Jakarta")
TARGET_SIGNALS_DAILY = 5  # aspirational observation target; NEVER a minimum enforced quota
MAX_RESEARCH_MESSAGES_PER_DAY = 12
MAX_ENTRY_AGE_SECONDS = 25 * 60
MAX_POSITION_AGE_SECONDS = 20 * 60
MIN_OBSERVED_NOTIONAL = 50000
MAX_PAPER_DATA_GAPS = 3

def read(name, default):
    p = ROOT / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default

def save(name, value):
    p = ROOT / name
    p.write_text(json.dumps(value, separators=(",", ":"), ensure_ascii=False) + "\n", encoding="utf-8")

def now_iso(timestamp):
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()

def local_day(timestamp):
    return datetime.fromtimestamp(timestamp, JAKARTA).date().isoformat()

def paper_has_edge(performance):
    """Predeclared *minimum* gate, not proof of a repeatable profitable strategy."""
    if performance.get("status") != "EVIDENCE_AVAILABLE":
        return False
    m30, m90 = performance.get("metrics30d", {}), performance.get("metrics90d", {})
    return (
        number(m90.get("closed")) >= 50
        and number(m30.get("closed")) >= 30
        and number(m90.get("winRate")) >= 0.52
        and number(m90.get("profitFactor")) >= 1.4
        and number(m90.get("expectancyR")) >= 0.15
        and 0 <= number(m90.get("maxDrawdownR")) <= 7
        and number(performance.get("uncertainDataGaps")) <= MAX_PAPER_DATA_GAPS
    )

def qualified_positions(snapshot, ranking, timestamp):
    eligible = {str(r.get("address", "")).lower(): r for r in ranking.get("ranking", [])
                if is_qualified(r, timestamp)}
    eligible_current = {}
    consensus = {}
    per_wallet_checks = snapshot.get("checkedAtByWallet", {})
    for address, positions in snapshot.get("wallets", {}).items():
        key = address.lower()
        if key not in eligible or not isinstance(positions, dict):
            continue
        checked = time_of(per_wallet_checks.get(address) or per_wallet_checks.get(key))
        if not 0 <= timestamp - checked <= MAX_POSITION_AGE_SECONDS:
            continue
        eligible_current[key] = eligible[key]
        for coin, position in positions.items():
            side = position.get("side")
            if side not in ("LONG", "SHORT") or number(position.get("notional")) < MIN_OBSERVED_NOTIONAL:
                continue
            consensus.setdefault(coin, {"LONG": set(), "SHORT": set()})[side].add(key)
    return eligible_current, consensus

def opportunity_events(alerts, state, ranking, timestamp):
    eligible, consensus = qualified_positions(state, ranking, timestamp)
    output = []
    for ev in alerts.get("events", []):
        if not isinstance(ev, dict) or ev.get("event") not in ("OPEN", "INCREASE", "REVERSE"):
            continue
        if not 0 <= timestamp - time_of(ev.get("time")) <= MAX_ENTRY_AGE_SECONDS:
            continue
        key = str(ev.get("address", "")).lower()
        if key not in eligible or number(ev.get("notional")) < MIN_OBSERVED_NOTIONAL:
            continue
        coin, side = str(ev.get("coin", "")), ev.get("side")
        current = state.get("wallets", {}).get(key, {}).get(coin, {})
        if side not in ("LONG", "SHORT") or current.get("side") != side:
            continue
        if number(current.get("notional")) < MIN_OBSERVED_NOTIONAL:
            continue
        same = consensus.get(coin, {}).get(side, set())
        opposite = consensus.get(coin, {}).get("SHORT" if side == "LONG" else "LONG", set())
        cons = len(same) >= 2 and len(same) / max(1, len(same) + len(opposite)) >= 0.7
        output.append({
            "eventId":str(ev.get("id","")),
            "occurredAt":ev.get("time"),
            "coin":coin, "side":side, "event":ev["event"],
            "address":key,"qualityScore":number(eligible[key].get("score")),
            "notionalUsd":round(number(current.get("notional")),2),
            "sameSideQualifiedWallets":len(same),
            "oppositeQualifiedWallets":len(opposite),
            "tier":"CONSENSUS_WATCH" if cons else "QUALIFIED_ACTIVITY",
            "tradeReady":False
        })
    unique = {e["eventId"]: e for e in output if e["eventId"]}
    return sorted(unique.values(),key=lambda e:e["occurredAt"],reverse=True), eligible, consensus

def matching_setup(event, setups, timestamp):
    if setups.get("status") != "SETUPS_AVAILABLE":
        return None
    if not 0 <= timestamp - time_of(setups.get("updatedAt")) <= 600:
        return None
    for s in setups.get("setups", []):
        if (event["coin"] != s.get("coin") or event["side"] != s.get("direction")
                or event["tier"] != "CONSENSUS_WATCH"
                or not 0 < time_of(s.get("expiresAt")) - timestamp <= 900):
            continue
        lo, hi = number(s.get("entryZoneLow")),number(s.get("entryZoneHigh"))
        stop, tp = number(s.get("stopLoss")),number(s.get("takeProfit1"))
        if not (0 < lo < hi and (stop < lo < hi < tp if event["side"]=="LONG" else tp < lo < hi < stop)):
            continue
        return s
    return None

def telegram_send(message):
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not (token and chat):
        print("INFO: No Telegram secrets; public signal data updated without message.")
        return False
    if "/" in token or "\n" in token or ":" not in token or not chat.lstrip("-").isdigit():
        print("WARNING: Invalid Telegram secret configuration.")
        return False
    url = "https://api.telegram.org/bot" + token + "/sendMessage"
    req = request.Request(url,data=json.dumps({"chat_id":chat,"text":message[:3900],
        "disable_web_page_preview":True}).encode("utf-8"),
        headers={"Content-Type":"application/json"},method="POST")
    try:
        with request.urlopen(req,timeout=20) as response:
            obj=json.loads(response.read(50000))
        return obj.get("ok") is True
    except error.HTTPError as exc:
        print("WARNING: Telegram HTTP",exc.code)
        return False
    except (error.URLError,TimeoutError,ValueError):
        print("WARNING: Telegram delivery failed without revealing secrets.")
        return False

def message_for(event, setup, validated):
    intro=("🟢 SETUP TERVERIFIKASI SECARA SIMULASI — TETAP CEK MANUAL" if validated
           else ("🟠 PAPER SETUP — BUKAN SINYAL EKSEKUSI" if setup
                 else "🐋 PEMANTAUAN WHALE — BELUM ADA ENTRY"))
    lines=[intro, f"{event['coin']} · {event['side']} · {event['event']}",
      f"Trader: {event['address'][:10]}… · Skor historis {event['qualityScore']:.1f}/100",
      f"Wallet berkualitas searah: {event['sameSideQualifiedWallets']}; berlawanan: {event['oppositeQualifiedWallets']}",
      f"Nilai posisi teramati: ${event['notionalUsd']:,.0f}",
      f"Waktu aktivitas (UTC): {event['occurredAt']}"]
    if setup:
        lines += [
           f"Entry indikatif Hyperliquid: {setup['entryZoneLow']} – {setup['entryZoneHigh']}",
           f"Stop-loss simulasi: {setup['stopLoss']}",
           f"Take-profit simulasi: {setup['takeProfit1']}",
           f"Kadaluarsa (UTC): {setup['expiresAt']}",
           "⚠️ Harga Binance, biaya, dan risiko likuidasi perlu diverifikasi kembali.",
        ]
    else:
        lines.append("Status: PANTAU / NO TRADE. Belum ada konfirmasi teknikal yang lengkap.")
    lines.append("Peringatan: data dompet bersifat terlambat dan tidak menjamin hasil trading.")
    return "\n".join(lines)

def main():
    timestamp=datetime.now(timezone.utc).timestamp()
    state=read("signal_state.json", {"sent":{}})
    position=read("position_state.json",{})
    ranking=read("ranking.json",{})
    alerts=read("alerts.json",{})
    setups=read("setups.json",{})
    perf=read("paper_performance.json",{})
    opportunities, eligible, consensus=opportunity_events(alerts,position,ranking,timestamp)
    # Never approve whale alerts from pooled results of an unrelated strategy.
    # Pre-V4.8 journals without independent metrics deliberately fail closed.
    paper_ok=paper_has_edge(perf.get('byStrategy',{}).get('WHALE_CONSENSUS',{}))
    stamp=local_day(timestamp)
    sent={key:value for key,value in state.get("sent",{}).items() if
          0<=timestamp-time_of(value.get("sentAt"))<=3*86400}
    already=sum(1 for v in sent.values() if v.get("day")==stamp and v.get("kind")=="RESEARCH")
    sent_today=sum(1 for v in sent.values() if v.get("day")==stamp and v.get("kind")=="TRADE")
    signal_opportunities=[]
    for ev in opportunities:
        setup=matching_setup(ev,setups,timestamp)
        validated=bool(setup and paper_ok)
        entry=dict(ev)
        entry["tier"]=("TRADE_CONSIDERATION" if validated else ("PAPER_ONLY" if setup else ev["tier"]))
        entry["paperSetup"]=setup
        entry["tradeReady"]=validated
        signal_opportunities.append(entry)
        # Never force a minimum alert count. One event only notified once.
        if entry["eventId"] in sent:continue
        kind="TRADE" if validated else "RESEARCH"
        if kind=="RESEARCH" and already>=MAX_RESEARCH_MESSAGES_PER_DAY:continue
        if telegram_send(message_for(entry,setup,validated)):
            sent[entry["eventId"]]={"sentAt":now_iso(timestamp),"day":stamp,"kind":kind}
            if kind=="RESEARCH":already+=1
            else:sent_today+=1
    save("signal_state.json",{"updatedAt":now_iso(timestamp),"sent":sent})
    summary={
        "updatedAt":now_iso(timestamp),
        "dateJakarta":stamp,
        "targetTradeIdeasPerDay":TARGET_SIGNALS_DAILY,
        "researchAlertsSentToday":already,
        "validatedTradeAlertsSentToday":sent_today,
        "qualityWalletsMonitored":len(eligible),
        "observedConsensusPairs":sum(
            any(len(s[side])>=2 and len(s[side])/max(1,len(s['LONG']|s['SHORT']))>=0.7
                for side in ("LONG","SHORT")) for s in consensus.values()),
        "hasValidatedPaperHistory":paper_ok,
        "activeObservations":signal_opportunities[:25],
        "status":"TRADE_RESEARCH_AVAILABLE" if any(x["tradeReady"] for x in signal_opportunities)
            else ("MONITORING_ONLY" if signal_opportunities else "NO_TRADE"),
        "disclaimer":"Five per day is a research target, never an enforced signal quota. No guaranteed outcomes."
    }
    save("signal_intelligence.json", summary)
    print("V4.5:",summary["status"],"eligibleWallets",len(eligible),
          "events",len(opportunities),"researchSent",already,"validatedSent",sent_today)

if __name__=="__main__":
    main()
