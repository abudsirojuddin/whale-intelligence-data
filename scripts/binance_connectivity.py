"""Read-only connectivity diagnostic for DOCUMENTED Binance public data sources.

Deliberately uses no proxy, VPN, regional spoofing, API keys, or order endpoint.
Returns HTTP/WS status and dataset family; archive/spot/demo are NOT live futures data.
"""
import json
import ssl
import socket
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
TIMEOUT=9

def https_check(name, url, method="GET"):
    started=time.monotonic()
    req=urllib.request.Request(url,method=method,headers={"User-Agent":"WhaleIntelligence-Diagnostics/1"})
    try:
        with urllib.request.urlopen(req,timeout=TIMEOUT) as resp:
            code=resp.status
            # GET only enough bytes for schema check; HEAD for large archive.
            snippet=resp.read(640) if method=="GET" else b""
            return {"source":name,"status":"AVAILABLE","httpStatus":code,
                    "latencyMs":round((time.monotonic()-started)*1000),
                    "jsonLike":snippet.startswith((b"{",b"[")) if method=="GET" else None}
    except urllib.error.HTTPError as e:
        # 451 is a deliberate access restriction, not a transient network error.
        return {"source":name,"status":"LEGAL_RESTRICTION" if e.code==451 else "HTTP_ERROR",
                "httpStatus":e.code,"latencyMs":round((time.monotonic()-started)*1000)}
    except (TimeoutError, urllib.error.URLError, OSError, ssl.SSLError) as e:
        return {"source":name,"status":"NETWORK_ERROR","errorType":type(e).__name__,
                "latencyMs":round((time.monotonic()-started)*1000)}

def websocket_check():
    """Probe handshake only against Binance's documented public Futures market stream."""
    import base64, os
    host="fstream.binance.com"
    started=time.monotonic()
    try:
        ctx=ssl.create_default_context()
        with socket.create_connection((host,443),timeout=TIMEOUT) as raw:
            with ctx.wrap_socket(raw,server_hostname=host) as ws:
                ws.settimeout(TIMEOUT)
                key=base64.b64encode(os.urandom(16)).decode()
                handshake=(
                    "GET /ws/btcusdt@markPrice HTTP/1.1\r\n"
                    f"Host: {host}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                    f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n"
                    "User-Agent: WhaleIntelligence-Diagnostics/1\r\n\r\n"
                )
                ws.sendall(handshake.encode("ascii"))
                first=ws.recv(1024).decode("ascii","replace").split("\r\n",1)[0]
                code=int(first.split(" ")[1]) if first.startswith("HTTP/") else None
                return {"source":"Futures market WebSocket (live)","status":
                        "AVAILABLE" if code==101 else "LEGAL_RESTRICTION" if code==451 else "HANDSHAKE_REJECTED",
                        "httpStatus":code,"latencyMs":round((time.monotonic()-started)*1000)}
    except (TimeoutError, OSError, ssl.SSLError, ValueError, IndexError) as e:
        return {"source":"Futures market WebSocket (live)","status":"NETWORK_ERROR",
                "errorType":type(e).__name__,"latencyMs":round((time.monotonic()-started)*1000)}

def main():
    # Use archive from two days earlier to allow Binance's daily publication delay.
    day=(datetime.now(timezone.utc)-timedelta(days=2)).strftime("%Y-%m-%d")
    file=f"BTCUSDT-15m-{day}.zip"
    report=[
        https_check("Binance USDT-M REST exchangeInfo (live)",
                    "https://fapi.binance.com/fapi/v1/exchangeInfo"),
        https_check("Binance USDT-M REST BTC kline (live)",
                    "https://fapi.binance.com/fapi/v1/klines?symbol=BTCUSDT&interval=15m&limit=2"),
        websocket_check(),
        https_check("Binance public spot data API (SPOT, not Futures)",
                    "https://data-api.binance.vision/api/v3/time"),
        https_check("Binance Vision USDT-M Futures DAILY ARCHIVE (DELAYED)",
                    f"https://data.binance.vision/data/futures/um/daily/klines/BTCUSDT/15m/{file}",
                    "HEAD"),
    ]
    live=[x for x in report[:3] if x["status"]=="AVAILABLE"]
    result={"testedAt":datetime.now(timezone.utc).isoformat(),
            "probeEnvironment":"GitHub Actions runner",
            "checks":report,
            "canRunLiveBinanceFutures":bool(live),
            "canRunFullRESTScanner":all(x["status"]=="AVAILABLE" for x in report[:2]),
            "notes":[
                "HTTP 451 means access restriction. No routing around the restriction was attempted.",
                "An accessible WebSocket alone does not make the REST scanner operational.",
                "Spot prices and delayed archive CANNOT substitute for live USDT-M perpetuals.",
                "No authentication, withdrawals, orders or trading credentials were used."
            ]}
    (ROOT/"binance_connectivity.json").write_text(
        json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"canRunFullRESTScanner":result["canRunFullRESTScanner"],
          "checks":report},ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
