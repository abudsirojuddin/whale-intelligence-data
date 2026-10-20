"""Whale Intelligence V2 — end-to-end Binance Futures intraday read-only gate.

Integrates separate Binance-only data integrity, live mark/funding/book,
perpetual-contract rules and open-interest history. Missing or stale data
ALWAYS yields NO_TRADE; never replace any missing field with spot/Hyperliquid
data, old price, guessed OI or synthetic exchange metadata.

Only prospective PAPER research is emitted to local json, never to Telegram.
"""
from __future__ import annotations

import json
import math
import time
from datetime import datetime,timezone
from pathlib import Path
from intraday_scanner import analyze

ROOT=Path(__file__).resolve().parent.parent
WATCH=("BTCUSDT","ETHUSDT","SOLUSDT")
FRAMES=("15m","1h","4h")
SOURCE_CONTEXT="BINANCE_USDM_PUBLIC_MARK_AND_BOOK_WEBSOCKET"
SOURCE_META="OFFICIAL_BINANCE_USDM_EXCHANGE_INFO"
SOURCE_OI="OFFICIAL_BINANCE_USDM_OPEN_INTEREST_HIST"

def read(name):
    try:
        p=json.loads((ROOT/name).read_text(encoding="utf-8"))
        return p if isinstance(p,dict) else {}
    except (FileNotFoundError,ValueError,OSError):
        return {}

def number(value):
    if isinstance(value,bool):
        return None
    try:
        v=float(value)
        return v if math.isfinite(v) else None
    except (ValueError,TypeError,OverflowError):
        return None

def accepted_instrument(meta,symbol,now_ms):
    """Official source provenance + active PERPETUAL and tick/lot filters."""
    if not(isinstance(meta,dict) and meta.get("source")==SOURCE_META):
        return None
    checked=number(meta.get("capturedAtMs"))
    if checked is None or not 0<=now_ms-checked<=24*3600_000:
        return None
    symbols=meta.get("symbols",{})
    if not isinstance(symbols,dict):
        return None
    spec=symbols.get(symbol)
    if not isinstance(spec,dict):
        return None
    if (spec.get("symbol")!=symbol or spec.get("contractType")!="PERPETUAL"
        or spec.get("status")!="TRADING" or spec.get("quoteAsset")!="USDT"):
        return None
    tick=number(spec.get("tickSize"))
    step=number(spec.get("stepSize"))
    minimum=number(spec.get("minNotional"))
    if None in (tick,step,minimum) or min(tick,step,minimum)<=0:
        return None
    return spec

def market_context(context,symbol,now_ms):
    if not(isinstance(context,dict) and context.get("source")==SOURCE_CONTEXT):
        return None
    if context.get("status")!="PARTIAL_MARKET_CONTEXT":
        return None
    found=context.get("symbolContexts",{})
    obj=found.get(symbol) if isinstance(found,dict) else None
    if not isinstance(obj,dict) or obj.get("symbol")!=symbol:
        return None
    marker=number(obj.get("eventTimeMs"))
    mark_time=number(obj.get("markEventTimeMs"))
    book_time=number(obj.get("bookEventTimeMs"))
    bid,ask,mark,rate=(number(obj.get(x)) for x in
                       ("bid","ask","markPrice","lastFundingRate"))
    if (None in (marker,mark_time,book_time,bid,ask,mark,rate)
        or not 0<=now_ms-marker<=60_000 or
        not 0<=now_ms-mark_time<=60_000 or
        not 0<=now_ms-book_time<=60_000
        or not (0<bid<ask and mark>0) or abs(rate)>.0015
        or (ask-bid)/((bid+ask)/2)*10000>15):
        return None
    return {"bidPrice":bid,"askPrice":ask,"lastFundingRate":rate}

def oi_history(oi,symbol,now_ms):
    if not(isinstance(oi,dict) and oi.get("source")==SOURCE_OI):
        return None
    series=oi.get("symbols",{})
    rows=series.get(symbol) if isinstance(series,dict) else None
    if not isinstance(rows,list) or len(rows)<2 or len(rows)>500:
        return None
    clean=[]
    for r in rows:
        if not isinstance(r,dict):
            return None
        value=number(r.get("sumOpenInterestValue"))
        timestamp=number(r.get("timestamp"))
        if (value is None or timestamp is None or value<=0
                or timestamp>now_ms+10_000 or now_ms-timestamp>60*60_000):
            return None
        clean.append({"sumOpenInterestValue":value,"timestamp":int(timestamp)})
    if not all(clean[i]["timestamp"]>clean[i-1]["timestamp"]
               for i in range(1,len(clean))):
        return None
    return clean

def bars_from_bridge(bridge,symbol,now_ms):
    if (not isinstance(bridge,dict) or bridge.get("status")!="RESEARCH_DATA_READY"
        or bridge.get("mode")!="PAPER_ONLY"):
        return None
    datasets=bridge.get("datasets",{})
    quality=bridge.get("quality",{})
    if not isinstance(datasets,dict) or not isinstance(quality,dict):
        return None
    frames={}
    for tf in FRAMES:
        key=f"{symbol}:{tf}"
        if quality.get(key,{}).get("status")!="READY":
            return None
        rows=datasets.get(key)
        if not isinstance(rows,list) or len(rows)<70:
            return None
        frame_len={"15m":900000,"1h":3600000,"4h":14400000}[tf]
        recent=rows[-70:]
        try:
            for c in recent:
                start,end=int(c["start"]),int(c["end"])
                prices=[number(c[k]) for k in ("open","high","low","close","volume")]
                if (start%frame_len or end!=start+frame_len-1 or
                    None in prices or min(prices[:4])<=0 or prices[4]<0 or
                    not prices[2]<=min(prices[0],prices[3])<=max(prices[0],prices[3])<=prices[1]):
                    return None
            if any(recent[i]["start"]-recent[i-1]["start"]!=frame_len
                   for i in range(1,len(recent))):
                return None
            if not 0<=now_ms-recent[-1]["end"]<=frame_len+180_000:
                return None
        except (KeyError,TypeError,ValueError,IndexError):
            return None
        frames[tf]=rows
    return frames

def assess(bridge,context,meta,oi,now_ms, symbols=WATCH):
    out={"updatedAt":datetime.fromtimestamp(now_ms/1000,timezone.utc).isoformat(),
         "source":"Binance USDT-M","mode":"PAPER_ONLY",
         "status":"NO_TRADE","newSignals":[],"rejectionCounts":{},
         "candidatesAnalyzed":len(symbols),"eligibleUniverse":0,
         "disclaimer":"Research only. No live signal evidence; no trading advice."}
    for symbol in symbols:
        reasons=[]
        bars=bars_from_bridge(bridge,symbol,now_ms)
        if bars is None:
            reasons.append("MISSING_FRESH_CONTIGUOUS_CANDLES")
        spec=accepted_instrument(meta,symbol,now_ms)
        if spec is None:
            reasons.append("BINANCE_INSTRUMENT_FILTERS_UNVERIFIED")
        quote=market_context(context,symbol,now_ms)
        if quote is None:
            reasons.append("LIVE_MARK_FUNDING_BOOK_UNVERIFIED")
        interest=oi_history(oi,symbol,now_ms)
        if interest is None:
            reasons.append("OPEN_INTEREST_UNVERIFIED")
        if reasons:
            for reason in reasons:
                out["rejectionCounts"][reason]=out["rejectionCounts"].get(reason,0)+1
            continue
        out["eligibleUniverse"]+=1
        try:
            signal=analyze(symbol,bars,
                {"bidPrice":quote["bidPrice"],"askPrice":quote["askPrice"]},
                {"lastFundingRate":quote["lastFundingRate"]},
                interest,now_ms)
            signal["createdAt"]=out["updatedAt"]
            signal["expiresAt"]=datetime.fromtimestamp(
                (now_ms+30*60000)/1000,timezone.utc).isoformat()
            signal["id"]=f"{symbol}-{signal['direction']}-{signal['strategy']}-{signal['candleEndMs']}"
            signal["status"]="PAPER_ONLY"
            signal["instrumentRulesVerified"]=True
            # Note: tick/step sizing verification needed at order-time;
            # the paper-only research model never creates Binance orders.
            out["newSignals"].append(signal)
        except (ValueError,KeyError,IndexError,TypeError,ZeroDivisionError) as exc:
            why=str(exc) if isinstance(exc,ValueError) else "INCOMPLETE_ANALYSIS"
            out["rejectionCounts"][why]=out["rejectionCounts"].get(why,0)+1
    if out["newSignals"]:
        out["status"]="PAPER_SETUPS_FOUND"
    return out

def main():
    report=assess(read("binance_dataset_readiness.json"),
        read("binance_live_market_context.json"),
        read("binance_exchange_info_verified.json"),
        read("binance_open_interest_verified.json"),
        int(time.time()*1000))
    (ROOT/"intraday_scan.json").write_text(json.dumps(
        report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"status":report["status"],"candidatesAnalyzed":report["candidatesAnalyzed"],
        "eligibleUniverse":report["eligibleUniverse"],
        "newSetups":len(report["newSignals"]),
        "rejections":report["rejectionCounts"]},ensure_ascii=False))
    return report

if __name__=="__main__":main()
