import importlib.util,time
from pathlib import Path
s=importlib.util.spec_from_file_location("collector",Path(__file__).with_name("binance_live_collector.py"))
m=importlib.util.module_from_spec(s)
s.loader.exec_module(m)
now=int(time.time()*1000)
width=m.PERIOD["15m"]
start=(now//width-1)*width
def evt(start,closed=True):
    return {"stream":"btcusdt@kline_15m","data":{"e":"kline","E":start+width,
        "s":"BTCUSDT","k":{"s":"BTCUSDT","i":"15m","t":start,"T":start+width-1,
        "o":"100","h":"102","l":"99","c":"101","v":"100","x":closed}}}
assert m.parse_closed_kline(evt(start,False),start+width+500) is None
bar=m.parse_closed_kline(evt(start),start+width+500)
assert bar is not None
st=m.empty_state()
assert m.append_closed(st,bar)=="APPENDED"
assert m.append_closed(st,bar)=="DUPLICATE"
future=dict(bar,start=bar["start"]+width,end=bar["end"]+width)
assert m.append_closed(st,future)=="APPENDED"
gap=dict(bar,start=bar["start"]+3*width,end=bar["end"]+3*width)
assert m.append_closed(st,gap)=="GAP_DETECTED"
assert st["gaps"]["BTCUSDT:15m"][-1]["missingIntervals"]==1
assert m.append_closed(st,future)=="OLD_EVENT"
assert m.series_quality(st["series"]["BTCUSDT:15m"],"15m",now)=="WARMING_UP"
fresh=[dict(start=i*width,end=(i+1)*width-1) for i in range(71)]
assert m.series_quality(fresh,"15m",fresh[-1]["end"]+200)=="READY"
fresh[30]["start"]+=2
assert m.series_quality(fresh,"15m",fresh[-1]["end"]+200)=="GAPPED"
print("Closed Binance candle collector offline tests passed")
