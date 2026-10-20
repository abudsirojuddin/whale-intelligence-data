"""Binance USD-M Futures PUBLIC funding/mark/book snapshot — research only.

Uses Binance documented market-stream and public-stream channels. No API keys,
REST failover, proxies, OI fabrication, trade instructions or exchange orders.
"""
from __future__ import annotations
import json
import math
import time
from datetime import datetime,timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
PAIRS=("BTCUSDT","ETHUSDT","SOLUSDT")
STREAM_MARK="!markPrice@arr@1s"
STREAM_BOOK="!bookTicker"
MAX_AGE_MS=15_000

def positive(x):
    if isinstance(x,bool):return None
    try:
        f=float(x)
        return f if math.isfinite(f) and f>0 else None
    except (TypeError,ValueError,OverflowError):return None

def signed(x):
    if isinstance(x,bool):return None
    try:
        f=float(x)
        return f if math.isfinite(f) else None
    except (TypeError,ValueError,OverflowError):return None

def mark_rows(message,now_ms):
    """MARK stream may deliver a list of updates. Never mistake spot price for futures."""
    if not isinstance(message,dict) or message.get("stream")!=STREAM_MARK:return []
    obj=message.get("data")
    rows=obj if isinstance(obj,list) else [obj]
    result=[]
    for row in rows:
        if not isinstance(row,dict) or row.get("e")!="markPriceUpdate":continue
        symbol=row.get("s")
        event=row.get("E")
        mark=positive(row.get("p"))
        index=positive(row.get("i"))
        funding=signed(row.get("r"))
        if not (symbol in PAIRS and isinstance(event,int) and
            0<=now_ms-event<=MAX_AGE_MS and mark and index and
            funding is not None and abs(funding)<.01):
            continue
        result.append({"symbol":symbol,"markPrice":mark,"indexPrice":index,
                       "lastFundingRate":funding,"eventTimeMs":event})
    return result

def book_rows(message,now_ms):
    if not isinstance(message,dict) or message.get("stream")!=STREAM_BOOK:return []
    data=message.get("data")
    rows=data if isinstance(data,list) else [data]
    found=[]
    for row in rows:
        if not isinstance(row,dict):continue
        symbol=row.get("s")
        bid=positive(row.get("b"))
        ask=positive(row.get("a"))
        evt=row.get("E")
        if not (symbol in PAIRS and bid and ask and ask>bid and
                isinstance(evt,int) and 0<=now_ms-evt<=MAX_AGE_MS):
            continue
        found.append({"symbol":symbol,"bid":bid,"ask":ask,
                     "spreadBps":round((ask-bid)/((bid+ask)/2)*10_000,4),
                     "eventTimeMs":evt})
    return found

def sample(ws_module,path,stream,parser,seconds=12):
    url=f"wss://fstream.binance.com/{path}/stream?streams={stream}"
    ws=None
    started=time.monotonic()
    rows={}
    error=None
    count=0
    try:
        ws=ws_module.create_connection(url,timeout=8,enable_multithread=True)
        ws.settimeout(2)
        while time.monotonic()-started<seconds:
            try:
                message=json.loads(ws.recv())
            except ws_module.WebSocketTimeoutException:
                continue
            except (ValueError,TypeError):
                continue
            for row in parser(message,int(time.time()*1000)):
                count+=1
                rows[row["symbol"]]=row
            if len(rows)==len(PAIRS):
                break
    except Exception as exc:
        error=type(exc).__name__  # avoid leaking credentials or request body
    finally:
        if ws:
            ws.close()
    return rows,{"acceptedRecords":count,"observedPairs":len(rows),"errorType":error}

def assemble(marks,books,now_ms):
    by_symbol={}
    for sym in PAIRS:
        mark,book=marks.get(sym),books.get(sym)
        if not(mark and book):continue
        if not(0<=now_ms-mark["eventTimeMs"]<=MAX_AGE_MS and
               0<=now_ms-book["eventTimeMs"]<=MAX_AGE_MS):
            continue
        by_symbol[sym]={**mark,**book}
    return {"capturedAt":datetime.fromtimestamp(now_ms/1000,timezone.utc).isoformat(),
        "source":"BINANCE_USDM_PUBLIC_MARK_AND_BOOK_WEBSOCKET",
        "market":"Binance USD-M sampled symbols, market-data research",
        "mode":"PAPER_ONLY","tradeReady":False,
        "eligibleForSignal":False,
        "status":"PARTIAL_MARKET_CONTEXT" if by_symbol else "DATA_UNAVAILABLE",
        "symbolContexts":by_symbol,
        "blockingData":["CURRENT_AND_HISTORICAL_OPEN_INTEREST_UNVERIFIED",
                        "EXCHANGE_INFO_TICK_LOT_RULES_UNVERIFIED",
                        "FRESH_CONTIGUOUS_4H_1H_15M_CANDLES_UNVERIFIED"],
        "warning":"Mark/funding and bid/ask are not sufficient evidence for a Binance trade signal."}

def main():
    import websocket
    marks,mc=sample(websocket,"market",STREAM_MARK,mark_rows)
    books,bc=sample(websocket,"public",STREAM_BOOK,book_rows)
    report=assemble(marks,books,int(time.time()*1000))
    report["streams"]={"mark":mc,"book":bc}
    (ROOT/"binance_live_market_context.json").write_text(
        json.dumps(report,ensure_ascii=False,indent=2)+"\n","utf-8")
    print(json.dumps({"status":report["status"],"symbols":list(report["symbolContexts"]),
         "streams":report["streams"],"eligibleForSignal":False,
         "blockingData":report["blockingData"]},ensure_ascii=False))
    if mc["errorType"] or bc["errorType"]:
        raise SystemExit("A market data stream could not be verified")

if __name__=="__main__":main()
