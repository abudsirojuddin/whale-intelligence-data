"""Binance Futures public WS closed-candle collector (PAPER RESEARCH ONLY).

Uses only official, public USD-M Futures market streams on /market/stream.
Does not authenticate or submit exchange orders. No stale/incomplete series
may be used as a live signal. GitHub Actions is best effort, not a 24h daemon.
"""
from __future__ import annotations
import argparse
import json
import math
import time
from datetime import datetime,timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
STATE=ROOT/"binance_live_candles.json"
DIAGNOSTICS=ROOT/"binance_live_diagnostics.json"
PERIOD={"15m":900_000,"1h":3_600_000,"4h":14_400_000}
SYMBOLS=("BTCUSDT","ETHUSDT","SOLUSDT")
MIN_CANDLES=70
MAX_CANDLES=240
MAX_EVENT_LAG_MS=5*60_000

def now_iso():
    return datetime.now(timezone.utc).isoformat()

def finite_positive(x,zero_allowed=False):
    try:
        v=float(x)
        return v if math.isfinite(v) and (v>=0 if zero_allowed else v>0) else None
    except (ValueError,TypeError,OverflowError):
        return None

def parse_closed_kline(message,now_ms):
    """Return an immutable closed candle, never a still forming update."""
    if not isinstance(message,dict):return None
    stream=message.get("stream")
    data=message.get("data")
    if not isinstance(stream,str) or not isinstance(data,dict):return None
    k=data.get("k")
    if data.get("e")!="kline" or not isinstance(k,dict) or k.get("x") is not True:
        return None
    symbol=k.get("s")
    interval=k.get("i")
    if symbol not in SYMBOLS or interval not in PERIOD:return None
    if stream != symbol.lower()+"@kline_"+interval or data.get("s")!=symbol:return None
    try:
        opened,closed,event_at=(int(k["t"]),int(k["T"]),int(data["E"]))
    except (ValueError,KeyError,TypeError):return None
    width=PERIOD[interval]
    if opened%width!=0 or closed!=opened+width-1:return None
    # No future candle, no ancient replayed data.
    if not(0<=now_ms-event_at<=MAX_EVENT_LAG_MS and 0<=now_ms-closed<=MAX_EVENT_LAG_MS):
        return None
    o,h,l,c,v=[finite_positive(k.get(field),field=="v") for field in ("o","h","l","c","v")]
    if None in (o,h,l,c,v) or not (l<=min(o,c)<=max(o,c)<=h):return None
    return {"symbol":symbol,"interval":interval,"start":opened,"end":closed,
            "open":o,"high":h,"low":l,"close":c,"volume":v}

def empty_state():
    return {"version":1,"source":"BINANCE_USDM_PUBLIC_WEBSOCKET",
            "mode":"PAPER_ONLY","updatedAt":None,"series":{},"gaps":{}}

def normalized_state(raw):
    if not isinstance(raw,dict) or raw.get("version")!=1:
        return empty_state()
    series=raw.get("series")
    gaps=raw.get("gaps")
    if not isinstance(series,dict) or not isinstance(gaps,dict):
        return empty_state()
    return {"version":1,"source":"BINANCE_USDM_PUBLIC_WEBSOCKET",
            "mode":"PAPER_ONLY","updatedAt":raw.get("updatedAt"),
            "series":series,"gaps":gaps}

def append_closed(state,candle):
    """Append or deduplicate. Mark gaps, never pretend missing candles exist."""
    key=candle["symbol"]+":"+candle["interval"]
    prev=state["series"].setdefault(key,[])
    if not isinstance(prev,list):
        state["series"][key]=[]
        prev=state["series"][key]
    last=prev[-1] if prev else None
    if last and candle["start"] < last["start"]:
        return "OLD_EVENT"
    if last and candle["start"] == last["start"]:
        # A duplicate closed candle must not revise already archived data.
        return "DUPLICATE" if last=={k:v for k,v in candle.items() if k not in ("symbol","interval")} else "CONFLICT"
    width=PERIOD[candle["interval"]]
    if last and candle["start"]-last["start"]!=width:
        entry={"after":last["start"],"before":candle["start"],
               "missingIntervals":(candle["start"]-last["start"])//width-1}
        state["gaps"].setdefault(key,[]).append(entry)
        state["gaps"][key]=state["gaps"][key][-100:]
        action="GAP_DETECTED"
    else:
        action="APPENDED"
    prev.append({k:v for k,v in candle.items() if k not in ("symbol","interval")})
    state["series"][key]=prev[-MAX_CANDLES:]
    state["updatedAt"]=now_iso()
    return action

def series_quality(rows,interval,now_ms):
    """Only a contiguous fresh and sufficiently deep set is usable."""
    width=PERIOD[interval]
    if len(rows)<MIN_CANDLES:return "WARMING_UP"
    recent=rows[-MIN_CANDLES:]
    if any(recent[i]["start"]-recent[i-1]["start"]!=width
           for i in range(1,len(recent))):
        return "GAPPED"
    if now_ms-recent[-1]["end"]>width+MAX_EVENT_LAG_MS:
        return "STALE"
    return "READY"

def run(seconds, symbols=SYMBOLS, websocket_module=None):
    import websocket as default_ws
    ws_module=websocket_module or default_ws
    state=normalized_state(json.loads(STATE.read_text("utf-8"))) if STATE.exists() else empty_state()
    streams=[s.lower()+"@kline_"+interval for s in symbols for interval in PERIOD]
    # Max 9 symbols/channels on a single official market WebSocket request.
    url="wss://fstream.binance.com/market/stream?streams="+"/".join(streams)
    report={"checkedAt":now_iso(),"liveBrokerExecutable":False,
            "source":"BINANCE_USDM_PUBLIC_WEBSOCKET","secondsRequested":seconds,
            "eventCounts":{"received":0,"closed":0,"invalidOrOpen":0},
            "writes":{"APPENDED":0,"GAP_DETECTED":0,"DUPLICATE":0,
                      "CONFLICT":0,"OLD_EVENT":0},
            "errors":[],"quality":{}}
    ws=None
    start=time.monotonic()
    try:
        ws=ws_module.create_connection(url,timeout=8,enable_multithread=True)
        ws.settimeout(3)
        while time.monotonic()-start<seconds:
            try:
                event=json.loads(ws.recv())
                report["eventCounts"]["received"]+=1
            except ws_module.WebSocketTimeoutException:
                continue
            except (ValueError,TypeError) as exc:
                report["errors"].append(type(exc).__name__)
                continue
            parsed=parse_closed_kline(event,int(time.time()*1000))
            if parsed is None:
                report["eventCounts"]["invalidOrOpen"]+=1
                continue
            report["eventCounts"]["closed"]+=1
            action=append_closed(state,parsed)
            report["writes"][action]+=1
    except Exception as exc:
        report["errors"].append(type(exc).__name__)
    finally:
        if ws:
            ws.close()
    now_ms=int(time.time()*1000)
    for symbol in symbols:
        for interval in PERIOD:
            key=symbol+":"+interval
            report["quality"][key]=series_quality(state["series"].get(key,[]),
                                                   interval,now_ms)
    report["readyForTechnicalAnalysis"]=all(v=="READY" for v in report["quality"].values())
    report["finishedAt"]=now_iso()
    # State is always paper research, even if all feeds are healthy.
    STATE.write_text(json.dumps(state,ensure_ascii=False,separators=(",",":"))+"\n","utf-8")
    DIAGNOSTICS.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n","utf-8")
    print(json.dumps({"closedEvents":report["eventCounts"]["closed"],
                      "dataQuality":report["quality"],
                      "readyForTechnicalAnalysis":report["readyForTechnicalAnalysis"],
                      "errors":report["errors"]}))
    return report

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--seconds",type=int,default=75)
    p.add_argument("--symbols",nargs="+",choices=SYMBOLS,default=list(SYMBOLS))
    args=p.parse_args()
    if not 3<=args.seconds<=140:raise SystemExit("seconds must be 3..140")
    if len(set(args.symbols))!=len(args.symbols):raise SystemExit("duplicate symbols")
    run(args.seconds,tuple(args.symbols))

if __name__=="__main__":main()
