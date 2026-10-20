import sys
from datetime import datetime,timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
from intraday_alert_gate import qualified_notification_ids,MAX_PAPER_ALERTS_PER_WIB_DAY
now=int(datetime(2026,10,20,13,0,tzinfo=timezone.utc).timestamp()*1000)
def s(symbol,side,candle,kind="TREND_PULLBACK"):
    return {"symbol":symbol,"direction":side,"strategy":kind,"candleEndMs":candle,
            "id":f"{symbol}-{side}-{kind}-{candle}"}
one=s("BTCUSDT","LONG",now-60_000)
assert qualified_notification_ids([one,one],{},now)==[one]
assert qualified_notification_ids([one],{one["id"]:now-20_000},now)==[]
older=s("BTCUSDT","LONG",now-900_000)
assert qualified_notification_ids([one],{older["id"]:now-900_000},now)==[]
assert qualified_notification_ids([one],{older["id"]:now-4_000_000},now)==[one]
five={f"OTHER{i}-LONG-TREND_PULLBACK-{now-i}":now-i for i in range(MAX_PAPER_ALERTS_PER_WIB_DAY)}
assert qualified_notification_ids([one],five,now)==[]
assert qualified_notification_ids([one],{"OLD":now-86_400_000},now)==[one]
print("Intraday 15-minute alert throttling tests passed")
