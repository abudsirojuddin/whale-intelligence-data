from pathlib import Path
import importlib.util
import time
s=importlib.util.spec_from_file_location("probe",Path(__file__).with_name("binance_ws_probe.py"))
m=importlib.util.module_from_spec(s)
s.loader.exec_module(m)
now=int(time.time()*1000)
k={"stream":"btcusdt@kline_15m","data":{"e":"kline","s":"BTCUSDT","E":now,
    "k":{"s":"BTCUSDT","i":"15m","t":now-30000,"T":now+120000,
         "o":"100","h":"102","l":"99","c":"101","v":"200","x":False}}}
assert m.validate_event(k,now)["candleClosed"] is False
assert m.validate_event(k,now+60000) is None
assert m.validate_event({"stream":"wrong","data":k["data"]},now) is None
assert m.validate_event({"stream":"btcusdt@bookTicker","data":{"e":"bookTicker","s":"BTCUSDT","E":now,"b":"100","a":"100.2"}},now) is not None
bad=dict(k["data"],k=dict(k["data"]["k"],x="false"))
assert m.validate_event({"stream":k["stream"],"data":bad},now) is None
print("Binance WS offline payload tests passed")
