"""Validate actual PUBLIC Binance USD-M Futures market-stream payloads.

Read-only diagnostic. Does not fall back to proxy, VPN, or alternate identity.
Handshake success is not sufficient: validate event data and freshness.
"""
from __future__ import annotations
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import websocket

ROOT=Path(__file__).resolve().parent.parent
STREAMS=("btcusdt@kline_15m","ethusdt@kline_1h","btcusdt@bookTicker","btcusdt@markPrice@1s")
URL="wss://fstream.binance.com/stream?streams="+"/".join(STREAMS)
EXPECTED={
    "btcusdt@kline_15m":("kline", "BTCUSDT", "15m"),
    "ethusdt@kline_1h":("kline", "ETHUSDT", "1h"),
    "btcusdt@bookTicker":("bookTicker", "BTCUSDT", None),
    "btcusdt@markPrice@1s":("markPriceUpdate", "BTCUSDT", None),
}
def validate_event(message,now_ms):
    if not isinstance(message,dict):return None
    stream=message.get("stream")
    payload=message.get("data")
    if stream not in EXPECTED or not isinstance(payload,dict):return None
    typ,symbol,interval=EXPECTED[stream]
    if payload.get("e")!=typ or payload.get("s")!=symbol:return None
    event_time=payload.get("E")
    if not isinstance(event_time,int) or abs(now_ms-event_time)>30_000:return None
    if interval:
        k=payload.get("k")
        if not isinstance(k,dict) or k.get("i")!=interval or k.get("s")!=symbol:return None
        if not all(k.get(key) is not None for key in ("t","T","o","h","l","c","v","x")):return None
        if not isinstance(k["x"],bool):return None
        try:
            low,high,close=map(float,(k["l"],k["h"],k["c"]))
            if not (0<low<=close<=high):return None
        except (TypeError,ValueError):return None
        return {"symbol":symbol,"eventType":typ,"interval":interval,
                "candleClosed":k["x"],"eventDelayMs":now_ms-event_time}
    if typ=="bookTicker":
        try:
            bid,ask=float(payload["b"]),float(payload["a"])
            if not(0<bid<=ask):return None
        except (KeyError,ValueError,TypeError):return None
    if typ=="markPriceUpdate":
        try:
            if float(payload["p"])<=0:return None
        except (KeyError,ValueError,TypeError):return None
    return {"symbol":symbol,"eventType":typ,"eventDelayMs":now_ms-event_time}

def main():
    observed={}
    counts={name:0 for name in STREAMS}
    error=None
    ws=None
    started=time.monotonic()
    try:
        ws=websocket.create_connection(URL,timeout=7,enable_multithread=True,
                                       header={"User-Agent":"WhaleIntelligence-ReadOnly/2"})
        ws.settimeout(3)
        while time.monotonic()-started<25 and not all(counts.values()):
            try:
                msg=json.loads(ws.recv())
            except websocket.WebSocketTimeoutException:
                continue
            result=validate_event(msg,int(time.time()*1000))
            if result:
                stream=msg["stream"]
                counts[stream]+=1
                observed[stream]=result
    except Exception as exc:
        error=type(exc).__name__ # never leak request headers or credentials
    finally:
        if ws is not None:
            ws.close()
    result={
        "testedAt":datetime.now(timezone.utc).isoformat(),
        "source":"Binance USD-M Futures PUBLIC WebSocket fstream.binance.com",
        "environment":"GitHub Actions",
        "success":all(counts.values()),
        "observed":observed,"counts":counts,"errorType":error,
        "comments":[
            "Verified public events are NOT proof all market datasets are available.",
            "No closed candles expected in short probe; a 15m kline update is not a closed candle.",
            "No API credentials, trading, proxy, or access-control bypass."
        ]}
    (ROOT/"binance_ws_probe.json").write_text(
        json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(result,ensure_ascii=False))
    if not result["success"]:
        raise SystemExit("WebSocket data schema/freshness validation incomplete")

if __name__=="__main__":
    main()
