"""Read-only Binance Vision USD-M *monthly* closed-candle archive for research.

Only complete prior UTC months, and only symbols explicitly approved for
research. Data is DELAYED and must NEVER be used as a current trade quote.
No Binance REST access, proxies, authentication, or account operations.
"""
from __future__ import annotations
import argparse
import calendar
import csv
import io
import json
import math
import time
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
BASE="https://data.binance.vision/data/futures/um/monthly/klines"
SYMBOLS=("BTCUSDT","ETHUSDT","SOLUSDT")
INTERVALS={"15m":900_000,"1h":3_600_000,"4h":14_400_000}
MAX_ZIP=8_000_000
MAX_CSV=24_000_000

def prev_month(year,month):
    return (year-1,12) if month==1 else (year,month-1)

def target_months(n, now=None):
    if not 1<=n<=12:
        raise ValueError("months must be 1..12")
    now=now or datetime.now(timezone.utc)
    y,m=now.year,now.month
    result=[]
    for _ in range(n):
        y,m=prev_month(y,m)
        result.append((y,m))
    return list(reversed(result))

def utc_month_bounds(year,month):
    begin=int(datetime(year,month,1,tzinfo=timezone.utc).timestamp()*1000)
    ny,nm=(year+1,1) if month==12 else (year,month+1)
    end=int(datetime(ny,nm,1,tzinfo=timezone.utc).timestamp()*1000)
    return begin,end

def monthly_url(symbol,interval,year,month):
    if symbol not in SYMBOLS or interval not in INTERVALS or not 2019<=year<=2100 or not 1<=month<=12:
        raise ValueError("UNSUPPORTED_MONTH_REQUEST")
    m=f"{year:04d}-{month:02d}"
    return f"{BASE}/{symbol}/{interval}/{symbol}-{interval}-{m}.zip"

def download(url):
    r=urllib.request.Request(url,headers={"User-Agent":"WhaleIntelligence-Delayed-Research/2"})
    for attempt in range(2):
        try:
            with urllib.request.urlopen(r,timeout=25) as stream:
                binary=stream.read(MAX_ZIP+1)
                if len(binary)>MAX_ZIP:
                    raise ValueError("MONTHLY_ARCHIVE_TOO_LARGE")
                return binary
        except urllib.error.HTTPError as exc:
            if exc.code in (403,404,451):
                raise RuntimeError(f"ARCHIVE_HTTP_{exc.code}") from exc
            if attempt==1:
                raise RuntimeError(f"ARCHIVE_HTTP_{exc.code}") from exc
        except (TimeoutError,urllib.error.URLError) as exc:
            if attempt==1:
                raise RuntimeError("ARCHIVE_NETWORK_UNAVAILABLE") from exc
        time.sleep(1.5)
    raise RuntimeError("ARCHIVE_UNAVAILABLE")

def parse_month(raw,symbol,interval,year,month):
    label=f"{year:04d}-{month:02d}"
    filename=f"{symbol}-{interval}-{label}.csv"
    if not zipfile.is_zipfile(io.BytesIO(raw)):
        raise ValueError("NOT_ZIP")
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        if z.namelist()!=[filename]:
            raise ValueError("UNEXPECTED_ARCHIVE_CONTENTS")
        if z.getinfo(filename).file_size>MAX_CSV:
            raise ValueError("MONTHLY_CSV_TOO_LARGE")
        with z.open(filename) as f:
            csv_data=f.read(MAX_CSV+1)
        if len(csv_data)>MAX_CSV:
            raise ValueError("MONTHLY_CSV_TOO_LARGE")
    width=INTERVALS[interval]
    start,exclusive_end=utc_month_bounds(year,month)
    candles=[]
    for row in csv.reader(io.StringIO(csv_data.decode("utf-8-sig"))):
        if not row:
            continue
        if row[0].strip().lower() in ("open_time","opentime"):
            continue
        if len(row)<7:
            raise ValueError("MISSING_COLUMNS")
        try:
            op_time,close_time=int(row[0]),int(row[6])
            op,hi,lo,cl,vol=(float(row[i]) for i in (1,2,3,4,5))
        except (ValueError,TypeError,OverflowError) as exc:
            raise ValueError("INVALID_NUMERIC_ROW") from exc
        if not (
            start<=op_time<exclusive_end and op_time%width==0
            and close_time in (op_time+width-1,op_time+width)
            and all(math.isfinite(x) for x in (op,hi,lo,cl,vol))
            and lo>0 and vol>=0 and lo<=min(op,cl)<=max(op,cl)<=hi
        ):
            raise ValueError("INVALID_MONTHLY_CANDLE")
        candles.append({"start":op_time,"end":op_time+width-1,
                        "open":op,"high":hi,"low":lo,"close":cl,"volume":vol})
    count=(exclusive_end-start)//width
    if len(candles)!=count:
        raise ValueError("MONTHLY_CANDLE_COUNT_MISMATCH")
    if (candles[0]["start"]!=start or candles[-1]["start"]!=exclusive_end-width):
        raise ValueError("MONTHLY_BOUNDARY_MISMATCH")
    if any(candles[i]["start"]-candles[i-1]["start"]!=width
           for i in range(1,len(candles))):
        raise ValueError("MONTHLY_GAP_OR_REORDER")
    return candles

def collect(symbols,months,now=None,fetcher=download):
    selected=target_months(months,now)
    datasets={}
    errors=[]
    for symbol in symbols:
        for interval in INTERVALS:
            joined=[]
            for y,m in selected:
                try:
                    joined.extend(parse_month(fetcher(monthly_url(symbol,interval,y,m)),
                                              symbol,interval,y,m))
                except (ValueError,RuntimeError,zipfile.BadZipFile,UnicodeError) as exc:
                    errors.append({"symbol":symbol,"interval":interval,
                                   "month":f"{y:04d}-{m:02d}","reason":str(exc)[:90]})
            width=INTERVALS[interval]
            continuity=bool(joined) and all(
                joined[i]["start"]-joined[i-1]["start"]==width for i in range(1,len(joined)))
            datasets[f"{symbol}:{interval}"]={
                "candles":joined,"contiguous":continuity and not any(
                    x["symbol"]==symbol and x["interval"]==interval for x in errors),
                "count":len(joined),"lastClosedAt":joined[-1]["end"] if joined else None}
    return {"generatedAt":datetime.now(timezone.utc).isoformat(),
            "source":"OFFICIAL_BINANCE_USDM_DELAYED_ARCHIVE",
            "archiveGranularity":"FULL_PREVIOUS_MONTHS",
            "liveTradeReady":False,"symbols":list(symbols),
            "months":[f"{y:04d}-{m:02d}" for y,m in selected],
            "errors":errors,"datasets":datasets,
            "disclaimer":"Retrospective research only; months-old data cannot be used for live trade entries."}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--months",type=int,default=3)
    ap.add_argument("--symbols",nargs="+",choices=SYMBOLS,default=["BTCUSDT","ETHUSDT","SOLUSDT"])
    args=ap.parse_args()
    if not 1<=args.months<=12 or len(set(args.symbols))!=len(args.symbols):
        raise SystemExit("Invalid research selection")
    data=collect(args.symbols,args.months)
    (ROOT/"binance_archive_history.json").write_text(
        json.dumps(data,ensure_ascii=False,separators=(",",":"))+"\n","utf-8")
    stats={"months":data["months"],"counts":{k:v["count"] for k,v in data["datasets"].items()},
           "errors":data["errors"][:10],"errorCount":len(data["errors"]),
           "liveTradeReady":False}
    print(json.dumps(stats,ensure_ascii=False))
    if data["errors"] or any(not v["contiguous"] for v in data["datasets"].values()):
        raise SystemExit("INCOMPLETE_ARCHIVE: research withheld")

if __name__=="__main__":
    main()
