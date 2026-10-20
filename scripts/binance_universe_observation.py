"""Read-only breadth diagnostic for PUBLIC Binance USD-M market WebSocket.

Observes best-bid/ask and 24h stats across markets. The stream only transmits
changed symbols, so coverage is a PARTIAL, non-exhaustive sample; does not
replace exchangeInfo / instrument rules or historical candle backfill.

Never authenticates, opens positions, sends research alerts, or circumvents
HTTP 451 access restrictions. For feasibility testing only.
"""
import json
import math
import time
from datetime import datetime,timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
MAX_OBSERVATIONS=2000
MAX_SPREAD_BPS=15
MIN_QUOTE_VOLUME_USDT=20_000_000
MAX_AGE_SECONDS=45
TOP_N=25

def numeric(x):
    try:
        v=float(x)
        return v if math.isfinite(v) else None
    except (ValueError,TypeError,OverflowError):
        return None

def valid_symbol(s):
    return isinstance(s,str) and s.isascii() and s.endswith("USDT") and s.isalnum() and len(s)<=24

def parse_ticker(message,now_ms):
    """Accept current per-symbol 24hTicker records, including all-market arrays."""
    if not isinstance(message,dict) or message.get("stream")!="!ticker@arr":
        return []
    data=message.get("data")
    if isinstance(data,dict):data=[data]
    if not isinstance(data,list):return []
    found=[]
    for row in data:
        if not isinstance(row,dict) or row.get("e")!="24hrTicker":
            continue
        s=row.get("s")
        event_time=row.get("E")
        vol=numeric(row.get("q"))
        change=numeric(row.get("P"))
        close=numeric(row.get("c"))
        if not (valid_symbol(s) and isinstance(event_time,int)
                and 0<=now_ms-event_time<20_000 and vol is not None and vol>=0
                and change is not None and close is not None and close>0):
            continue
        found.append({"symbol":s,"volume24hUsdt":vol,
                      "change24hPct":change,"lastPrice":close,"eventTimeMs":event_time})
    return found

def parse_book(message,now_ms):
    if not isinstance(message,dict) or message.get("stream")!="!bookTicker":
        return None
    data=message.get("data")
    if not isinstance(data,dict):return None
    s=data.get("s")
    bid=numeric(data.get("b"))
    ask=numeric(data.get("a"))
    event_time=data.get("E")
    if not (valid_symbol(s) and bid and ask and 0<bid<ask
            and isinstance(event_time,int) and 0<=now_ms-event_time<20_000):
        return None
    return {"symbol":s,"bid":bid,"ask":ask,"spreadBps":(ask-bid)/((ask+bid)/2)*10000,
            "eventTimeMs":event_time}

def rank(tickers,books,now_ms):
    result=[]
    checks={"observedTickerPairs":len(tickers),"observedBookPairs":len(books),
            "commonSymbols":0,"filteredLowVolume":0,"filteredSpread":0,
            "filteredStale":0,"eligible":0}
    for sym,t in tickers.items():
        b=books.get(sym)
        if not b:continue
        checks["commonSymbols"]+=1
        if not (0<=now_ms-t["eventTimeMs"]<=MAX_AGE_SECONDS*1000
                and 0<=now_ms-b["eventTimeMs"]<=MAX_AGE_SECONDS*1000):
            checks["filteredStale"]+=1
            continue
        if t["volume24hUsdt"]<MIN_QUOTE_VOLUME_USDT:
            checks["filteredLowVolume"]+=1
            continue
        if b["spreadBps"]>MAX_SPREAD_BPS:
            checks["filteredSpread"]+=1
            continue
        item={"symbol":sym,"quoteVolume24hUsdt":round(t["volume24hUsdt"],2),
            "priceChange24hPct":round(t["change24hPct"],2),
            "lastPrice":t["lastPrice"],"bid":b["bid"],"ask":b["ask"],
            "spreadBps":round(b["spreadBps"],3),
            "tickerAgeMs":now_ms-t["eventTimeMs"],"bookAgeMs":now_ms-b["eventTimeMs"]}
        result.append(item)
    result.sort(key=lambda x:(-x["quoteVolume24hUsdt"],x["symbol"]))
    checks["eligible"]=len(result)
    return result[:TOP_N],checks

def observe(ws_module,stream,path,seconds):
    """Observe a public stream for a short bounded period; no persistent claims."""
    url=f"wss://fstream.binance.com/{path}/stream?streams={stream}"
    ws=None
    counts={"frames":0,"validRecords":0,"schemaErrors":0}
    observed={}
    error=None
    start=time.monotonic()
    try:
        ws=ws_module.create_connection(url,timeout=8,enable_multithread=True)
        ws.settimeout(2.5)
        while time.monotonic()-start<seconds:
            try:
                msg=json.loads(ws.recv())
                counts["frames"]+=1
            except ws_module.WebSocketTimeoutException:
                continue
            except (ValueError,TypeError):
                counts["schemaErrors"]+=1
                continue
            now_ms=int(time.time()*1000)
            records=(parse_ticker(msg,now_ms) if stream=="!ticker@arr" else
                     [parse_book(msg,now_ms)])
            for item in records:
                if not item:continue
                observed[item["symbol"]]=item
                counts["validRecords"]+=1
            # Fixed cap in case a feed sends an unexpectedly large universe.
            if len(observed)>MAX_OBSERVATIONS:
                error="TOO_MANY_OBSERVED_SYMBOLS"
                break
    except Exception as exc:
        error=type(exc).__name__  # Do not expose server credentials or URLs.
    finally:
        if ws:ws.close()
    return observed,counts,error

def main():
    import websocket
    # Separate stream sessions avoid flooding the 24-hour ticker receiver
    # with book updates. Short windows only show recently changed symbols.
    books,bc,be=observe(websocket,"!bookTicker","public",18)
    tickers,tc,te=observe(websocket,"!ticker@arr","market",18)
    checked_ms=int(time.time()*1000)
    top,checks=rank(tickers,books,checked_ms)
    report={"checkedAt":datetime.now(timezone.utc).isoformat(),
        "source":"BINANCE_USDM_PUBLIC_WEBSOCKET",
        "market":"USDT-suffixed contracts observed; perpetual status UNVERIFIED",
        "mode":"RESEARCH_ONLY","tradeReady":False,"telegramSignalAllowed":False,
        "bookFeed":{"counts":bc,"error":be},
        "tickerFeed":{"counts":tc,"error":te},
        "coverage":checks,"candidates":top,
        "readyForTechnicalScanner":False,
        "limitations":[
            "Only recently changed pairs observed; NOT all Binance Futures contracts.",
            "USDT suffix is not proof of perpetual contract or active instrument.",
            "No exchangeInfo rules, lot/tick sizes, open interest, or funding.",
            "No current multi-timeframe closed candles nor live trading edge.",
            "No proxy or bypass for restricted Binance REST access."
        ]}
    if not top:
        report["status"]="NO_ELIGIBLE_MATCHES"
    else:
        report["status"]="UNVERIFIED_RESEARCH_CANDIDATES"
    (ROOT/"binance_universe_observation.json").write_text(
        json.dumps(report,ensure_ascii=False,indent=2)+"\n","utf-8")
    print(json.dumps({"status":report["status"],"bookFeed":bc,"tickerFeed":tc,
          "errors":[be,te],"coverage":checks,"topPairs":[r["symbol"] for r in top[:8]]},
          ensure_ascii=False))
    if be or te:
        raise SystemExit("A public Binance stream could not be fully sampled.")

if __name__=="__main__":main()
