"""Official Binance Vision USD-M Futures archive collector (DELAYED candles).

Research/backtesting only: public daily ZIP files, never used for live entries.
No proxy, identity change, or restricted REST access is attempted.
"""
import argparse
import csv
import io
import json
import math
import time
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
HOST="https://data.binance.vision"
INTERVAL_MS={"15m":900000,"1h":3600000,"4h":14400000}
APPROVED_SYMBOLS=("BTCUSDT","ETHUSDT","SOLUSDT")
MAX_ZIP_BYTES=8_000_000
MAX_UNZIPPED_BYTES=15_000_000

def daily_url(symbol,interval,day):
    if symbol not in APPROVED_SYMBOLS or interval not in INTERVAL_MS:
        raise ValueError("Invalid archive request")
    d=day.strftime("%Y-%m-%d")
    return (f"{HOST}/data/futures/um/daily/klines/{symbol}/{interval}/"
            f"{symbol}-{interval}-{d}.zip")

def fetch_archive(url,attempts=2):
    req=urllib.request.Request(url,headers={"User-Agent":"WhaleIntelligence-PaperArchive/1"})
    for i in range(attempts):
        try:
            with urllib.request.urlopen(req,timeout=20) as r:
                # Content-length is not always available; enforce hard read limits.
                data=r.read(MAX_ZIP_BYTES+1)
                if len(data)>MAX_ZIP_BYTES:
                    raise ValueError("ARCHIVE_TOO_LARGE")
                return data
        except urllib.error.HTTPError as e:
            if e.code in (403,404,451):
                raise RuntimeError(f"ARCHIVE_HTTP_{e.code}") from e
            if i==attempts-1:
                raise RuntimeError(f"ARCHIVE_HTTP_{e.code}") from e
        except (urllib.error.URLError,TimeoutError):
            if i==attempts-1:
                raise RuntimeError("ARCHIVE_NETWORK_ERROR")
        time.sleep(1.5*(i+1))
    raise RuntimeError("ARCHIVE_UNAVAILABLE")

def parse_zip(data,symbol,interval,day):
    expected=f"{symbol}-{interval}-{day.strftime('%Y-%m-%d')}.csv"
    if not zipfile.is_zipfile(io.BytesIO(data)):
        raise ValueError("BAD_ZIP")
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names=z.namelist()
        if names!=[expected]:
            raise ValueError("UNEXPECTED_ZIP_CONTENT")
        info=z.getinfo(expected)
        if info.file_size>MAX_UNZIPPED_BYTES:
            raise ValueError("UNCOMPRESSED_TOO_LARGE")
        with z.open(expected) as fh:
            raw=fh.read(MAX_UNZIPPED_BYTES+1)
    if len(raw)>MAX_UNZIPPED_BYTES:
        raise ValueError("UNCOMPRESSED_TOO_LARGE")
    parsed=[]
    day_start=int(datetime(day.year,day.month,day.day,tzinfo=timezone.utc).timestamp()*1000)
    width=INTERVAL_MS[interval]
    for row in csv.reader(io.StringIO(raw.decode("utf-8-sig"))):
        if not row:continue
        # Some published archives have a descriptive header row.
        if row[0].strip().lower() in ("open_time","opentime"):continue
        if len(row)<7:raise ValueError("BAD_CSV_COLUMNS")
        try:
            start=int(row[0]);close_time=int(row[6])
            op,high,low,close,vol=(float(row[i]) for i in (1,2,3,4,5))
        except (ValueError,OverflowError) as e:
            raise ValueError("BAD_CSV_VALUE") from e
        if not(all(math.isfinite(x) for x in (op,high,low,close,vol))
            and 0<low<=min(op,close)<=max(op,close)<=high and vol>=0):
            raise ValueError("INVALID_CANDLE")
        if not (day_start<=start<day_start+86400000 and start%width==0
                and close_time in (start+width-1,start+width)):
            raise ValueError("INVALID_CANDLE_TIME")
        parsed.append({"start":start,"end":start+width-1,"open":op,
                       "high":high,"low":low,"close":close,"volume":vol})
    if not parsed:
        raise ValueError("ARCHIVE_EMPTY")
    parsed.sort(key=lambda x:x["start"])
    if len({x["start"] for x in parsed})!=len(parsed):
        raise ValueError("DUPLICATE_CANDLE")
    if any(parsed[i]["start"]-parsed[i-1]["start"]!=width
           for i in range(1,len(parsed))):
        raise ValueError("MISSING_ARCHIVE_CANDLE")
    if parsed[0]["start"]!=day_start or parsed[-1]["start"]!=day_start+86400000-width:
        raise ValueError("INCOMPLETE_ARCHIVE_DAY")
    return parsed

def collect(symbols,days,now=None,downloader=fetch_archive):
    now=now or datetime.now(timezone.utc)
    cutoff=now.date()-timedelta(days=2)
    data={}
    errors=[]
    for symbol in symbols:
        for interval in INTERVAL_MS:
            rows=[]
            for offset in range(days-1,-1,-1):
                d=cutoff-timedelta(days=offset)
                try:
                    url=daily_url(symbol,interval,d)
                    rows+=parse_zip(downloader(url),symbol,interval,d)
                except (ValueError,RuntimeError,zipfile.BadZipFile,UnicodeError) as e:
                    errors.append({"symbol":symbol,"interval":interval,
                                   "day":str(d),"error":str(e)[:80]})
            name=f"{symbol}:{interval}"
            width=INTERVAL_MS[interval]
            contiguous=bool(rows and all(
                rows[i]["start"]-rows[i-1]["start"]==width
                for i in range(1,len(rows))))
            data[name]={"candles":rows[-5000:],"count":len(rows),
                        "contiguous":contiguous,"lastClosedAt":rows[-1]["end"] if rows else None}
    return {"generatedAt":now.isoformat(),"source":"OFFICIAL_BINANCE_USDM_DELAYED_ARCHIVE",
            "liveTradeReady":False,"symbols":list(symbols),
            "daysRequested":days,"errors":errors,"datasets":data,
            "disclaimer":"Historical delayed candles only; cannot validate intraday entries or live signals."}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--symbols",nargs="+",choices=APPROVED_SYMBOLS,default=["BTCUSDT"])
    p.add_argument("--days",type=int,default=1)
    args=p.parse_args()
    if not 1<=args.days<=35:raise SystemExit("days must be 1..35")
    out=collect(args.symbols,args.days)
    output=ROOT/"binance_archive_history.json"
    output.write_text(json.dumps(out,ensure_ascii=False,separators=(",",":"))+"\n",encoding="utf-8")
    print(json.dumps({"source":out["source"],"liveTradeReady":False,
                      "candles":{k:v["count"] for k,v in out["datasets"].items()},
                      "errorCount":len(out["errors"]),"errors":out["errors"][:5]}))
    if out["errors"] or not all(d["contiguous"] for d in out["datasets"].values()):
        raise SystemExit("ARCHIVE_UNVERIFIED: no assumptions about missing data")

if __name__=="__main__":
    main()
