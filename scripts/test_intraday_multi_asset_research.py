import importlib.util,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
spec=importlib.util.spec_from_file_location("multi",Path(__file__).with_name("intraday_multi_asset_research.py"))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
bad=m.aggregate({})
assert bad["tradeReady"] is False and bad["qualityStatus"]=="NO_TRADE"
assert bad["blockingReasons"]==["UNVERIFIED_OR_PARTIAL_ARCHIVE"]
assert "NOT live trading signals" in m.as_markdown(bad)
data={"source":"OFFICIAL_BINANCE_USDM_DELAYED_ARCHIVE","liveTradeReady":False,
      "errors":[],"datasets":{}}
for sym in m.ALLOWED_SYMBOLS:
    for tf in ("15m","1h","4h"):
        data["datasets"][sym+":"+tf]={"contiguous":True,"count":70,"candles":[{}]*70}
valid,reason=m.check_archives(data,m.ALLOWED_SYMBOLS)
assert valid is True and reason is None
data["errors"].append({"symbol":"BTCUSDT","error":"MISSING_ARCHIVE_CANDLE"})
assert m.check_archives(data,m.ALLOWED_SYMBOLS)[0] is False
print("Multi-asset research release gates passed")
