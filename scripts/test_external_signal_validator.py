import sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
from external_signal_validator import parse,validate_forwarded_text
signal="ENAUSDT LONG\nENTRY $0.189 - $0.194\nSL under 0.182\nTP 0.208++"
p=parse(signal)
assert p["status"]=="PARSED" and p["symbol"]=="ENAUSDT" and p["stopIsThreshold"]
assert p["entryLow"]==0.189 and p["entryHigh"]==0.194
assert validate_forwarded_text(signal)["decision"]=="PERLU_HARGA_BINANCE"
now=int(time.time()*1000)
quote={"source":"BINANCE_USDM_FUTURES","symbol":"ENAUSDT","markPrice":0.19706,"observedAtMs":now}
v=validate_forwarded_text(signal,quote,now)
assert v["decision"]=="JANGAN_KEJAR_ENTRY"
assert v["tradeExecutionEnabled"] is False
quote["markPrice"]=0.191
assert validate_forwarded_text(signal,quote,now)["decision"]=="PERLU_VERIFIKASI_RISIKO"
quote["observedAtMs"]=now-120000
assert validate_forwarded_text(signal,quote,now)["decision"]=="PERLU_HARGA_BINANCE"
assert parse("BTCUSDT SHORT ENTRY 100 - 101 SL 98 TP 90")["status"]=="INVALID_LEVELS"
assert parse("BTCUSDT LONG ENTRY 100 - 101 SL 98 TP 110 ETHUSDT")["status"]=="INCOMPLETE"
print("PASS: human-only external signal validation, stale-price rejection and ENA example")
