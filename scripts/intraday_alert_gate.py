"""V2 Binance-only conditional Telegram PAPER alert safety gate.

Only a NEW, recent, internally consistent, exchange-verified research setup
may become a PAPER alert. A 'NO_TRADE' status MUST never be converted to a
fabricated LONG/SHORT. This module does NOT open Binance orders.

Run --dry-run by default. Optional live delivery needs explicit operator
environment opt-in and existing bot credentials; keep disabled until full
continuous-data ingestion and a verified paper sample are available.
"""
from __future__ import annotations
import argparse
import json
import math
import os
import time
from datetime import datetime,timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
PAIRS={"BTCUSDT","ETHUSDT","SOLUSDT"}
INTERVALS=("15m","1h","4h")
MIN_SCORE=85
MIN_NET_RR=2.0
MAX_AGE_MS=180_000
MAX_RISK_IDR=5_000
MAX_MARGIN_IDR=100_000
MAX_PAPER_ALERTS_PER_WIB_DAY=5  # ceiling only, not a quota or guarantee
SYMBOL_ALERT_COOLDOWN_MS=60*60*1000
PAPER_ALERT_EXPLICITLY_DISABLED=True

def time_ms(value):
    try:
        t=datetime.fromisoformat(str(value).replace("Z","+00:00"))
        if t.tzinfo is None:return None
        return int(t.timestamp()*1000)
    except (TypeError,ValueError,OverflowError):
        return None

def num(value):
    if isinstance(value,bool):return None
    try:
        n=float(value)
        return n if math.isfinite(n) else None
    except (TypeError,ValueError,OverflowError):
        return None

def recent(timestamp, now_ms, age_ms=MAX_AGE_MS):
    v=time_ms(timestamp)
    return v is not None and 0<=now_ms-v<=age_ms

def load(name):
    try:
        obj=json.loads((ROOT/name).read_text(encoding="utf-8"))
        return obj if isinstance(obj,dict) else {}
    except (FileNotFoundError,ValueError):
        return {}

def validate_signal(s,now_ms):
    if not isinstance(s,dict):return "MALFORMED_SIGNAL"
    if s.get("symbol") not in PAIRS:return "UNVERIFIED_INSTRUMENT"
    if s.get("status")!="PAPER_ONLY":return "NOT_PAPER_RESEARCH"
    direction=s.get("direction")
    if direction not in ("LONG","SHORT"):return "INVALID_DIRECTION"
    if s.get("strategy") not in ("TREND_PULLBACK","BREAKOUT_RETEST"):
        return "INVALID_STRATEGY"
    if num(s.get("score")) is None or num(s["score"])<MIN_SCORE:
        return "QUALITY_BELOW_GATE"
    if num(s.get("netRR")) is None or num(s["netRR"])<MIN_NET_RR:
        return "NET_RR_BELOW_GATE"
    if s.get("timeframe")!="15m":return "INVALID_TIMEFRAME"
    candle_ms=num(s.get("candleEndMs"))
    if candle_ms is None or not 0<=now_ms-candle_ms<=18*60_000:
        return "CANDLE_NOT_RECENT"
    if not recent(s.get("createdAt"),now_ms):
        return "STALE_RESEARCH_SETUP"
    exp=time_ms(s.get("expiresAt"))
    if exp is None or not now_ms<exp<=now_ms+35*60_000:
        return "EXPIRED_SETUP"
    entry,sl,tp=[num(s.get(name)) for name in ("entry","stopLoss","takeProfit1")]
    if None in (entry,sl,tp) or min(entry,sl,tp)<=0:
        return "BAD_PRICE"
    if not (sl<entry<tp if direction=="LONG" else tp<entry<sl):
        return "INVALID_RISK_ORDER"
    risk=num(s.get("maxEstimatedRiskIdr"))
    margin=num(s.get("assumedMarginIdr"))
    if (risk is None or margin is None or not 0<risk<=MAX_RISK_IDR
            or not 0<margin<=MAX_MARGIN_IDR):
        return "POSITION_RISK_INVALID"
    oi=num(s.get("openInterestChange"))
    funding=num(s.get("fundingRate"))
    spread=num(s.get("spreadBps"))
    if (oi is None or funding is None or spread is None or
            abs(funding)>.0015 or not 0<=spread<=15):
        return "DERIVATIVES_OR_SPREAD_UNVERIFIED"
    return None

def eligible(scan,readiness,now_ms):
    reasons=[]
    if (scan.get("status")!="PAPER_SETUPS_FOUND" or
            scan.get("mode")!="PAPER_ONLY" or
            scan.get("source")!="Binance USDT-M" or
            not recent(scan.get("updatedAt"),now_ms)):
        reasons.append("SCANNER_NOT_LIVE_OR_NO_SIGNALS")
    if readiness.get("status")!="RESEARCH_DATA_READY" or readiness.get("mode")!="PAPER_ONLY":
        reasons.append("MULTI_TIMEFRAME_DATA_NOT_READY")
    if not recent(readiness.get("generatedAt"),now_ms):
        reasons.append("DATA_READINESS_STALE")
    if reasons:
        return [],reasons
    signals=scan.get("newSignals",[])
    if not isinstance(signals,list):
        return [],["BAD_SIGNAL_SCHEMA"]
    approved=[]
    for signal in signals[:25]:
        reason=validate_signal(signal,now_ms)
        if reason:
            reasons.append(reason)
            continue
        sym=signal["symbol"]
        if not all(readiness.get("quality",{}).get(sym+":"+tf,{}).get("status")=="READY"
                   for tf in INTERVALS):
            reasons.append("SYMBOL_TIMEFRAME_NOT_READY")
            continue
        approved.append(signal)
    return approved,reasons

def qualified_notification_ids(candidates, sent_ids, now_ms):
    """Throttle strictly without inventing opportunities or sending stale repeats.

    Returns only candidates not already delivered. Max five paper notifications
    per WIB calendar day, and at least one hour between notifications for the
    same symbol+direction. The scanner itself can evaluate every 15 minutes.
    """
    jakarta_day=(datetime.fromtimestamp(now_ms/1000,timezone.utc)
                 .astimezone(__import__("datetime").timezone(__import__("datetime").timedelta(hours=7)))
                 .date())
    daily=0
    for when in sent_ids.values():
        if (type(when) in (int,float) and when<=now_ms and
            datetime.fromtimestamp(when/1000,timezone.utc)
            .astimezone(__import__("datetime").timezone(__import__("datetime").timedelta(hours=7))).date()==jakarta_day):
            daily+=1
    available=max(0,MAX_PAPER_ALERTS_PER_WIB_DAY-daily)
    result=[]
    for s in candidates:
        key=str(s.get("id",""))
        if not key or key in sent_ids:
            continue
        expected=f"{s['symbol']}-{s['direction']}-{s['strategy']}-{int(s['candleEndMs'])}"
        if key!=expected:
            continue
        label=f"{s['symbol']}-{s['direction']}-"
        if any(x.startswith(label) and type(t) in (int,float)
               and 0<=now_ms-t<SYMBOL_ALERT_COOLDOWN_MS for x,t in sent_ids.items()):
            continue
        if any(row['symbol']==s['symbol'] and row['direction']==s['direction'] for row in result):
            continue
        if len(result)>=available:
            break
        result.append(s)
    return result


def paper_message(s):
    return ("\N{TEST TUBE} WHALE INTELLIGENCE V2 | PAPER SETUP\n"
            "⚠️ SIMULASI — BUKAN REKOMENDASI TRANSAKSI BINANCE\n"
            f"{s['symbol']} {s['direction']} | {s['strategy']} | 15M\n"
            f"Entry simulasi {s['entry']}\nSL simulasi {s['stopLoss']}\n"
            f"TP simulasi {s['takeProfit1']}\n"
            f"RR bersih asumsi: {s['netRR']}:1\n"
            f"Skor aturan {s['score']}/100 — bukan peluang profit\n"
            f"Risiko asumsi: Rp{s['maxEstimatedRiskIdr']:,} | "
            f"Margin simulasi Rp{s['assumedMarginIdr']:,}\n"
            f"Terbit UTC {s['createdAt']} | Berlaku hingga UTC {s['expiresAt']}\n"
            "Tidak ada order otomatis. Verifikasi kondisi pasar langsung sebelum keputusan apa pun.")

def run(now=None,deliver=None,persist=True):
    from intraday_telegram_status import send as real_send
    now_ms=int(time.time()*1000) if now is None else now
    scan=load("intraday_scan.json")
    readiness=load("binance_dataset_readiness.json")
    candidates,reasons=eligible(scan,readiness,now_ms)
    state=load("intraday_alert_gate_state.json")
    done=state.get("sentIds",{})
    if not isinstance(done,dict):
        done={}
    done={k:v for k,v in done.items() if isinstance(v,(int,float)) and 0<=now_ms-v<7*86400000}
    # Explicitly do not send until a full prospective paper pilot has been
    # authorized and the continuously collected Binance data path works.
    sending_enabled=(
        not PAPER_ALERT_EXPLICITLY_DISABLED
        and os.environ.get("ENABLE_BINANCE_V2_PAPER_DELIVERY")=="YES")
    count=0
    pending=qualified_notification_ids(candidates,done,now_ms)
    would_send=len(pending)
    for s in pending:
        key=str(s["id"])
        if sending_enabled and (deliver or real_send)(paper_message(s)):
            done[key]=now_ms
            count+=1
    status={"checkedAt":datetime.fromtimestamp(now_ms/1000,timezone.utc).isoformat(),
        "source":"Binance USDT-M","mode":"PAPER_ONLY","status":
        "DELIVERED_PAPER_SETUP" if count else
        "VALID_RESEARCH_PENDING_ENABLEMENT" if would_send else "NO_TRADE",
        "signalsQualified":len(candidates),"messageCount":count,
        "unnotifiedQualified":would_send,
        "sendingEnabled":sending_enabled,
        "reasons":sorted(set(reasons)),
        "notes":"A valid research scenario is not proof of profitable live Binance trading."}
    if persist:
        (ROOT/"intraday_alert_gate_status.json").write_text(
            json.dumps(status,ensure_ascii=False,indent=2)+"\n","utf-8")
        (ROOT/"intraday_alert_gate_state.json").write_text(
            json.dumps({"sentIds":done},separators=(",",":"))+"\n","utf-8")
    print(json.dumps(status,ensure_ascii=False))
    return status

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--dry-run",action="store_true",default=True)
    run()
