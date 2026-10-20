import importlib.util
from pathlib import Path
m_spec=importlib.util.spec_from_file_location("bridge",Path(__file__).with_name("binance_data_bridge.py"))
m=importlib.util.module_from_spec(m_spec);m_spec.loader.exec_module(m)
now=2_000_000_000_000
for interval,width in m.INTERVAL_MS.items():
    end_slot=(now//width)-1
    rows=[{"start":(end_slot-75+i)*width,"end":(end_slot-74+i)*width-1,
           "open":100.,"high":102.,"low":99.,"close":101.,"volume":150.} for i in range(75)]
    assert m.join_series(rows[:-5],rows[-5:],interval,now)["status"]=="READY"
    assert m.join_series(rows[:-6],rows[-5:],interval,now)["status"]=="MISSING_CANDLES"
    assert m.join_series(rows[:20],[],interval,now)["status"]=="INSUFFICIENT_HISTORY"
    modified=[dict(rows[-5],close=200.)]+rows[-4:]
    assert m.join_series(rows,modified,interval,now)["status"]=="CONFLICTING_OVERLAP"
    assert m.join_series(rows[:-5],[],interval,now)["status"]=="STALE_LAST_CANDLE"
    assert m.join_series(rows[:-5],[dict(rows[-5],end=rows[-5]["end"]+100)],interval,now)["status"]=="INVALID_CLOSED_CANDLE"
archive={"source":m.SOURCE_ARCHIVE,"datasets":{}}
live={"source":m.SOURCE_WS,"series":{}}
assert m.assemble(archive,live,("BTCUSDT",),now)["status"]=="NO_TRADE"
assert m.assemble({},live,("BTCUSDT",),now)["warnings"][0]=="SOURCE_MISSING_OR_UNVERIFIED"
print("Binance data bridge offline tests passed")
