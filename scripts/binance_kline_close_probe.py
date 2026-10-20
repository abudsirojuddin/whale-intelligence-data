"""Probe final kline messages from Binance USD-M official public stream.

Uses BTCUSDT 1m stream solely to test that x=true final messages are
delivered at minute boundaries. It is NOT a 15m or trade-ready price feed.
"""
from __future__ import annotations
import json
import time
from datetime import datetime, timezone
from pathlib import Path
import websocket

PATH=Path(__file__).resolve().parent.parent/"binance_kline_close_probe.json"
URL="wss://fstream.binance.com/market/stream?streams=btcusdt@kline_1m"

def classify(obj,now_ms):
    if not isinstance(obj,dict) or obj.get("stream")!="btcusdt@kline_1m":
        return None
    data=obj.get("data")
    if not isinstance(data,dict) or data.get("e")!="kline" or data.get("s")!="BTCUSDT":
        return None
    k=data.get("k")
    if not isinstance(k,dict) or k.get("i")!="1m":
        return None
    try:
        opened,closed,stamp=int(k["t"]),int(k["T"]),int(data["E"])
    except (KeyError, ValueError, TypeError):
        return None
    if opened%60000 or closed!=opened+59999:
        return None
    if not 0<=now_ms-stamp<=30000:
        return None
    return {"openTimeMs":opened,"closeTimeMs":closed,
            "eventLagMs":now_ms-stamp,"closeLagMs":now_ms-closed,
            "isFinal":k.get("x") is True,"eventTimeMs":stamp}

def main():
    observed=[]
    count=0
    errors=[]
    started=time.monotonic()
    ws=None
    try:
        ws=websocket.create_connection(URL,timeout=10,enable_multithread=True)
        ws.settimeout(3)
        while time.monotonic()-started<90:
            try:
                msg=json.loads(ws.recv())
            except websocket.WebSocketTimeoutException:
                continue
            except (ValueError,TypeError):
                continue
            x=classify(msg,int(time.time()*1000))
            if not x:
                continue
            count+=1
            if x["isFinal"]:
                observed.append(x)
                break
    except Exception as exc:
        errors.append(type(exc).__name__)
    finally:
        if ws:
            ws.close()
    result={"checkedAt":datetime.now(timezone.utc).isoformat(),
            "framesClassified":count,"finalCandlesObserved":len(observed),
            "finalCandleExamples":observed[:2],"errors":errors,
            "connectionHealthy":not bool(errors),
            "note":"Only confirms 1-minute final-close event availability; does not qualify trade data."}
    PATH.write_text(json.dumps(result,indent=2)+"\n","utf-8")
    print(json.dumps(result))
    if errors or not observed:
        raise SystemExit("NO_FINAL_CANDLE_SEEN")

if __name__=="__main__":
    main()
