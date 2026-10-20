"""Quality-audited Binance USDT-M candle consolidation; PAPER-ONLY.

Resample ONLY continuous, FINALIZED 15m public Futures candles to cross-check
native 1h/4h frames. Never invent missing bars or mark an incomplete interval
as closed. This is a diagnostic; it does not manufacture trade entry signals.
"""
from __future__ import annotations
import json
import math
import time
from pathlib import Path
from datetime import datetime,timezone

ROOT=Path(__file__).resolve().parent.parent
P15=900000
TARGETS={"1h":4,"4h":16}
SYMBOLS=("BTCUSDT","ETHUSDT","SOLUSDT")

def good_candle(c,width):
    if not isinstance(c,dict):
        return False
    try:
        start,end=int(c["start"]),int(c["end"])
        vals=[float(c[k]) for k in ("open","high","low","close","volume")]
    except (KeyError,ValueError,OverflowError,TypeError):
        return False
    o,h,l,close,v=vals
    return (start>=0 and start%width==0 and end==start+width-1
            and all(math.isfinite(x) for x in vals)
            and l>0 and l<=min(o,close)<=max(o,close)<=h and v>=0)

def resample(rows, target):
    if target not in TARGETS:
        raise ValueError("UNSUPPORTED_INTERVAL")
    need=TARGETS[target]
    width=need*P15
    if not isinstance(rows,list):
        return [],["INVALID_SERIES"]
    parsed={}
    errors=[]
    for row in rows:
        if not good_candle(row,P15):
            errors.append("INVALID_15M_CANDLE")
            continue
        start=row["start"]
        if start in parsed and row!=parsed[start]:
            errors.append("CONFLICTING_15M_DUPLICATE")
            continue
        parsed[start]=row
    grouped={}
    for t,bar in parsed.items():
        bucket=(t//width)*width
        grouped.setdefault(bucket,[]).append(bar)
    out=[]
    for begin,bars in sorted(grouped.items()):
        bars.sort(key=lambda c:c["start"])
        # Do not fill an incomplete hour with estimated prices or volume.
        if len(bars)!=need:
            continue
        if any(bars[i]["start"]!=begin+i*P15 for i in range(need)):
            continue
        o=bars[0]["open"]
        close=bars[-1]["close"]
        high=max(b["high"] for b in bars)
        low=min(b["low"] for b in bars)
        volume=sum(b["volume"] for b in bars)
        out.append({"start":begin,"end":begin+width-1,
                    "open":o,"high":high,"low":low,
                    "close":close,"volume":volume})
    return out,sorted(set(errors))

def compare(derived,native,width):
    """Exact candle time with tolerant numeric comparison, never silently overwrite."""
    existing={row["start"]:row for row in native
              if good_candle(row,width)}
    mismatches=[]
    matches=0
    for candle in derived:
        original=existing.get(candle["start"])
        if not original:
            continue
        if all(math.isclose(float(candle[k]),float(original[k]),
                            rel_tol=1e-7,abs_tol=1e-8)
               for k in ("open","high","low","close","volume")):
            matches+=1
        else:
            mismatches.append(candle["start"])
    return {"matchingNative":matches,"conflictingNative":len(mismatches),
            "conflictStarts":mismatches[:10]}

def audit(state,now_ms):
    out={"updatedAt":datetime.fromtimestamp(now_ms/1000,timezone.utc).isoformat(),
         "source":"BINANCE_USDM_PUBLIC_WEBSOCKET",
         "mode":"PAPER_ONLY","tradeReady":False,"status":"NO_TRADE",
         "timeframes":{},"warnings":[]}
    if not isinstance(state,dict) or state.get("source")!="BINANCE_USDM_PUBLIC_WEBSOCKET":
        out["warnings"].append("LIVE_COLLECTOR_SOURCE_NOT_VERIFIED")
        return out
    raw=state.get("series",{})
    if not isinstance(raw,dict):
        out["warnings"].append("MALFORMED_SERIES")
        return out
    all_good=True
    for sym in SYMBOLS:
        c15=raw.get(f"{sym}:15m",[])
        for frame,n in TARGETS.items():
            assembled,issues=resample(c15,frame)
            width=P15*n
            native=raw.get(f"{sym}:{frame}",[])
            if not isinstance(native,list):
                native=[]
                issues.append("MALFORMED_NATIVE_SERIES")
            matched=compare(assembled,native,width)
            last=assembled[-1] if assembled else None
            fresh=bool(last and 0<=now_ms-last["end"]<=width+180000)
            status=("CONFLICT" if issues or matched["conflictingNative"] else
                    "READY" if len(assembled)>=70 and fresh else
                    "WARMING_UP" if len(assembled)<70 else "STALE")
            out["timeframes"][f"{sym}:{frame}"]={
                "status":status,"derivedClosedCandles":len(assembled),
                "lastClosedAtMs":last["end"] if last else None,
                "fresh":fresh,"issues":issues,**matched}
            all_good&=(status=="READY")
    out["status"]="RESEARCH_CANDLES_READY" if all_good else "NO_TRADE"
    if not all_good:
        out["warnings"].append("Do not publish a trading signal from incomplete or mismatched market data.")
    return out

def main():
    src=ROOT/"binance_live_candles.json"
    try:
        state=json.loads(src.read_text("utf-8"))
    except (FileNotFoundError,ValueError):
        state={}
    result=audit(state,int(time.time()*1000))
    (ROOT/"binance_candle_rollup_quality.json").write_text(
        json.dumps(result,indent=2,ensure_ascii=False)+"\n","utf-8")
    print(json.dumps({"status":result["status"],"timeframes":{
        k:{"status":v["status"],"derived":v["derivedClosedCandles"],
           "nativeConflicts":v["conflictingNative"]}
        for k,v in result["timeframes"].items()
    }},ensure_ascii=False))

if __name__=="__main__":
    main()
