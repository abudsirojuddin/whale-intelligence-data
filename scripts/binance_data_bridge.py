"""Validate/merge Binance USD-M archive + WS candles for PAPER research only.

Archive (2+ days delayed) is historical; WS may leave time gaps.
Only closed, continuous, fresh candles can become technical inputs.
NO_TRADING decisions if ANY required timeframe fails.
"""
from __future__ import annotations
import json
import math
import time
from pathlib import Path
from datetime import datetime, timezone

ROOT=Path(__file__).resolve().parent.parent
INTERVAL_MS={"15m":900000,"1h":3600000,"4h":14400000}
SOURCE_ARCHIVE="OFFICIAL_BINANCE_USDM_DELAYED_ARCHIVE"
SOURCE_WS="BINANCE_USDM_PUBLIC_WEBSOCKET"
REQUIRED_BARS=70
MAX_BARS=240

def load(name, fallback):
    try:
        return json.loads((ROOT/name).read_text(encoding="utf-8"))
    except (FileNotFoundError,ValueError):
        return fallback

def save(name, obj):
    (ROOT/name).write_text(json.dumps(obj,ensure_ascii=False,separators=(",",":"))+"\n","utf-8")

def parse_row(row,width,now_ms):
    if not isinstance(row,dict):
        raise ValueError("BAD_ROW")
    try:
        start,end=int(row["start"]),int(row["end"])
        o,h,l,c,v=[float(row[k]) for k in ("open","high","low","close","volume")]
    except (KeyError,ValueError,TypeError,OverflowError):
        raise ValueError("BAD_ROW_DATA")
    if (start<0 or start%width!=0 or end!=start+width-1 or
            end>=now_ms or not all(math.isfinite(x) for x in (o,h,l,c,v)) or
            not (0<l<=min(o,c)<=max(o,c)<=h and v>=0)):
        raise ValueError("INVALID_CLOSED_CANDLE")
    return {"start":start,"end":end,"open":o,"high":h,"low":l,
            "close":c,"volume":v}

def join_series(archive_rows,ws_rows,interval,now_ms,minimum=REQUIRED_BARS):
    """Never invent missing candle time or treat archive as recent live data."""
    width=INTERVAL_MS[interval]
    allrows={}
    for source,rows in (("ARCHIVE",archive_rows),("LIVE_WS",ws_rows)):
        if not isinstance(rows,list):
            return {"status":"BAD_SCHEMA","source":source,"candles":[]}
        try:
            for row in rows:
                parsed=parse_row(row,width,now_ms)
                old=allrows.get(parsed["start"])
                if old is not None and old!=parsed:
                    return {"status":"CONFLICTING_OVERLAP","candles":[]}
                allrows[parsed["start"]]=parsed
        except ValueError as e:
            return {"status":str(e),"source":source,"candles":[]}
    candles=sorted(allrows.values(),key=lambda x:x["start"])[-MAX_BARS:]
    if len(candles)<minimum:
        return {"status":"INSUFFICIENT_HISTORY","have":len(candles),
                "required":minimum,"candles":[]}
    last=candles[-minimum:]
    breaks=sum(1 for i in range(1,len(last))
        if last[i]["start"]-last[i-1]["start"]!=width)
    if breaks:
        return {"status":"MISSING_CANDLES","gaps":breaks,"candles":[]}
    age_ms=now_ms-last[-1]["end"]
    if age_ms>width+180000:
        return {"status":"STALE_LAST_CANDLE","ageMs":age_ms,"candles":[]}
    return {"status":"READY","count":len(candles),"lastClosedAt":last[-1]["end"],
            "lastCandleAgeMs":age_ms,"candles":candles}

def assemble(archive,live,symbols,now_ms):
    out={"generatedAt":datetime.fromtimestamp(now_ms/1000,timezone.utc).isoformat(),
         "mode":"PAPER_ONLY","liveOrderReady":False,"status":"NO_TRADE",
         "source":{"historical":"BINANCE_VISION_ARCHIVE","recent":"BINANCE_PUBLIC_WS"},
         "datasets":{},"quality":{},
         "warnings":[]}
    if not(isinstance(archive,dict) and archive.get("source")==SOURCE_ARCHIVE
            and isinstance(live,dict) and live.get("source")==SOURCE_WS):
        out["warnings"].append("SOURCE_MISSING_OR_UNVERIFIED")
        return out
    good=True
    for symbol in symbols:
        for interval in INTERVAL_MS:
            key=symbol+":"+interval
            a=archive.get("datasets",{}).get(key,{})
            ar=a.get("candles",[]) if a.get("contiguous") is True else []
            # Do not treat a partially downloaded archive as complete.
            if ar and not isinstance(ar,list):
                ar=[]
            ws=live.get("series",{}).get(key,[])
            checked=join_series(ar,ws,interval,now_ms)
            out["quality"][key]={k:v for k,v in checked.items() if k!="candles"}
            if checked["status"]=="READY":
                out["datasets"][key]=checked["candles"]
            else:
                good=False
    if good and out["quality"]:
        out["status"]="RESEARCH_DATA_READY"
        # Technical engine still needs separate validated setup/risk logic.
    out["warnings"].append("Read-only quality gate. No entry or order instructions.")
    return out

def main():
    archive=load("binance_archive_history.json",{})
    live=load("binance_live_candles.json",{})
    output=assemble(archive,live,("BTCUSDT","ETHUSDT","SOLUSDT"),int(time.time()*1000))
    save("binance_dataset_readiness.json",output)
    print(json.dumps({"status":output["status"],"quality":output["quality"],
                      "warnings":output["warnings"]},ensure_ascii=False))
    # Data gaps are expected while warming up and should NOT fail CI:
    # Never silently promote such data to actionable signals.

if __name__=="__main__":
    main()
