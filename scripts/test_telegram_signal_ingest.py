import sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
from telegram_signal_ingest import interpret,format_reply
now=int(time.time())
base={"update_id":42,"message":{"date":now,"chat":{"id":111,"type":"private"},"photo":[{"file_id":"safe-photo"}],"caption":"ENAUSDT LONG ENTRY 0.189 - 0.194 SL under 0.182 TP 0.208"}}
r=interpret(base,[111],now)
assert r["status"]=="REQUIRES_BINANCE_PRICE_CHECK"
assert r["imageAttached"] is True and r["imageReadByAI"] is False
assert r["priceVerified"] is False and r["tradeExecutionEnabled"] is False
assert "PERLU CEK HARGA" in format_reply(r)
assert interpret(base,[999],now)["status"]=="REJECTED"
photo_only={"update_id":44,"message":{"date":now,"chat":{"id":111,"type":"private"},"photo":[{"file_id":"p"}]}}
assert interpret(photo_only,[111],now)["status"]=="NEEDS_CAPTION"
missing_direction={"update_id":45,"message":{"date":now,"chat":{"id":111,"type":"private"},"caption":"ENAUSDT ENTRY 0.189 - 0.194 SL under 0.182 TP 0.208","photo":[{"file_id":"p"}]}}
assert interpret(missing_direction,[111],now)["status"]=="NEEDS_DIRECTION_CONFIRMATION"
expired={"update_id":46,"message":dict(base["message"],forward_origin={"type":"channel","date":now-7*3600})}
assert interpret(expired,[111],now)["status"]=="OLD_SOURCE"
assert interpret({"update_id":47,"message":dict(base["message"],chat={"id":111,"type":"group"})},[111],now)["status"]=="REJECTED"
print("PASS: captioned Telegram forward ingestion, chat allowlist, photo handling and no trade")
