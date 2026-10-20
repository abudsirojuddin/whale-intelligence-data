"""Whale Intelligence — independent Telegram signal-text validator, paper analysis only.

Safely parse manually forwarded signal *text*, not private Telegram groups.
This module never calls an exchange, receives bot credentials, or opens orders.
It declines to infer missing entry/stop/TP or a real-time Binance quote.
"""
from __future__ import annotations
import argparse
import json
import math
import re
import sys
from datetime import datetime, timezone

SYMBOL=re.compile(r"(?<![A-Z0-9])(?:\$|#)?([A-Z]{2,15})(?:\s*/\s*|\s*[-_]\s*|)(USDT)(?![A-Z0-9])",re.I)
NUMBER=r"([0-9]+(?:[.,][0-9]+)?)"
ENTRY=re.compile(r"\b(?:entry|entri|buy\s+zone|sell\s+zone|zona\s+entry)\b\s*:?\s*(?:\$?\s*)"+NUMBER+r"\s*(?:-|–|—|to|sampai)\s*\$?\s*"+NUMBER,re.I)
SINGLE_ENTRY=re.compile(r"\b(?:entry|entri)\s*:?\s*\$?\s*"+NUMBER,re.I)
STOP=re.compile(r"\b(?:stop[\s-]*loss|sl)\b\s*:?\s*(below|under|di\s+bawah|above|over|di\s+atas|<|>)?\s*\$?\s*"+NUMBER,re.I)
TP=re.compile(r"\b(?:take[\s-]*profit|tp\s*1?|target\s*1?)\b\s*:?\s*\$?\s*"+NUMBER,re.I)
SIDE=re.compile(r"\b(LONG|SHORT)\b",re.I)
MAX_LEN=3000

def price(token):
    try:
        n=float(token.replace(",","."))
        return n if math.isfinite(n) and n>0 else None
    except (TypeError,ValueError,OverflowError):
        return None

def parse(text):
    if not isinstance(text,str) or len(text)>MAX_LEN:
        return {"status":"INVALID_TEXT","errors":["TEXT_TOO_LONG_OR_INVALID"]}
    # Only extract a single unambiguous instrument and side.
    pairs=set(m.group(1).upper()+"USDT" for m in SYMBOL.finditer(text))
    directions=set(m.group().upper() for m in SIDE.finditer(text))
    problems=[]
    if len(pairs)!=1: problems.append("ONE_SYMBOL_REQUIRED")
    if len(directions)!=1: problems.append("ONE_DIRECTION_REQUIRED")
    zone=ENTRY.search(text)
    single=SINGLE_ENTRY.search(text)
    sl=STOP.search(text)
    target=TP.search(text)
    low=high=None
    if zone:
        a,b=price(zone.group(1)),price(zone.group(2))
        if a is not None and b is not None:
            low,high=sorted((a,b))
    elif single:
        low=high=price(single.group(1))
    stop=price(sl.group(2)) if sl else None
    take=price(target.group(1)) if target else None
    if low is None or high is None:problems.append("ENTRY_NOT_FOUND")
    if stop is None:problems.append("STOP_NOT_FOUND")
    if take is None:problems.append("TAKE_PROFIT_NOT_FOUND")
    if problems:
        return {"status":"INCOMPLETE","errors":problems,"hasStopQualifier":bool(sl and sl.group(1))}
    direction=next(iter(directions))
    if not (stop<low<=high<take if direction=="LONG" else take<low<=high<stop):
        return {"status":"INVALID_LEVELS","errors":["ENTRY_SL_TP_DIRECTION_CONFLICT"]}
    qualifier=(sl.group(1) or "").lower() if sl else ""
    stop_is_threshold=qualifier in ("below","under","di bawah","above","over","di atas","<",">")
    if stop_is_threshold:
        good=(qualifier in ("below","under","di bawah","<") if direction=="LONG"
              else qualifier in ("above","over","di atas",">"))
        if not good:
            return {"status":"INVALID_LEVELS","errors":["STOP_QUALIFIER_CONFLICT"]}
    return {"status":"PARSED","symbol":next(iter(pairs)),"direction":direction,
            "entryLow":low,"entryHigh":high,"stopBoundary":stop,"stopIsThreshold":stop_is_threshold,
            "takeProfit1":take,"errors":[],
            "caution":"Stop below/above a boundary is not an exact stop price." if stop_is_threshold else None}

def estimate_rr(signal,entry):
    sign=1 if signal["direction"]=="LONG" else -1
    reward=sign*(signal["takeProfit1"]-entry)
    risk=sign*(entry-signal["stopBoundary"])
    if reward<=0 or risk<=0:return None
    return round(reward/risk,3)

def validate_forwarded_text(text, quote=None, now_ms=None):
    data=parse(text)
    if data["status"]!="PARSED":
        return {"decision":"TOLAK_DATA","reasonCodes":data["errors"],
                "parsed":data,"tradeExecutionEnabled":False}
    if now_ms is None:now_ms=int(datetime.now(timezone.utc).timestamp()*1000)
    if not isinstance(quote,dict) or quote.get("source")!="BINANCE_USDM_FUTURES" or quote.get("symbol")!=data["symbol"]:
        return {"decision":"PERLU_HARGA_BINANCE","reasonCodes":["LIVE_PRICE_UNVERIFIED"],
                "parsed":data,"tradeExecutionEnabled":False}
    try:
        current=float(quote.get("markPrice"))
        observed=int(quote.get("observedAtMs"))
    except (TypeError,ValueError,OverflowError):
        current=None;observed=0
    if (current is None or not math.isfinite(current) or current<=0 or
            not 0<=now_ms-observed<=60_000):
        return {"decision":"PERLU_HARGA_BINANCE","reasonCodes":["LIVE_PRICE_STALE_OR_INVALID"],
                "parsed":data,"tradeExecutionEnabled":False}
    lo,hi=data["entryLow"],data["entryHigh"]
    direction=data["direction"]
    if (direction=="LONG" and current>hi) or (direction=="SHORT" and current<lo):
        decision="JANGAN_KEJAR_ENTRY"
        reason=["CURRENT_PRICE_PAST_ENTRY_ZONE"]
    elif (direction=="LONG" and current<lo) or (direction=="SHORT" and current>hi):
        decision="TUNGGU_ZONA_ENTRY"
        reason=["CURRENT_PRICE_OUTSIDE_ENTRY_ZONE"]
    else:
        decision="PERLU_VERIFIKASI_RISIKO"
        reason=["IN_ENTRY_ZONE_NOT_EXECUTION_APPROVAL"]
    rr_lo=estimate_rr(data,lo)
    rr_hi=estimate_rr(data,hi)
    best_rr=max((x for x in (rr_lo,rr_hi) if x is not None),default=None)
    worst_rr=min((x for x in (rr_lo,rr_hi) if x is not None),default=None)
    if data["stopIsThreshold"]:
        reason.append("SL_IS_BOUNDARY_NOT_EXACT_PRICE")
    if worst_rr is None or worst_rr<2:
        reason.append("RISK_REWARD_MAY_BE_BELOW_2")
    return {"decision":decision,"reasonCodes":reason,
            "livePrice":current,"rrAtZoneLowAssumingBoundarySL":rr_lo,
            "rrAtZoneHighAssumingBoundarySL":rr_hi,
            "bestZoneRRBoundaryAssumption":best_rr,
            "worstZoneRRBoundaryAssumption":worst_rr,
            "parsed":data,"tradeExecutionEnabled":False,
            "warning":"Scenario only. Group signal is not independently verified; no leverage, fees, slippage or funding assumptions."}

def main():
    p=argparse.ArgumentParser(description="Parse forwarded Telegram text offline; no orders or API.")
    p.add_argument("--text",help="Signal text; omit to paste on stdin")
    args=p.parse_args()
    incoming=args.text if args.text is not None else sys.stdin.read(MAX_LEN+1)
    print(json.dumps(validate_forwarded_text(incoming),ensure_ascii=False,indent=2))

if __name__=="__main__":main()
