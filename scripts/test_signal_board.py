import importlib.util
from pathlib import Path
from datetime import datetime,timezone
spec=importlib.util.spec_from_file_location("board",Path(__file__).with_name("build_signal_board.py"))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
now=datetime(2026,10,20,5,tzinfo=timezone.utc).timestamp()
iso=m.iso
scan={"apiHealthy":True,"updatedAt":iso(now-20),"coins":[{"coin":c,"status":"REJECTED","reasons":["TREND_NOT_ALIGNED"],"markPrice":10,"trend":{"direction":"MIXED"},"liquidity":{"volume24hUsd":50e6,"spreadBps":1}} for c in ("BTC","ETH","SOL","ARB","HYPE","XRP")]}
x=m.make(scan,{},{"status":"NO_TRADE","setups":[]},{"status":"NO_TRADE","setups":[]},now)
assert x["actualWatchCount"]==5 and x["readyForLiveExecutionCount"]==0
assert all(e["tier"]=="WATCH_ONLY" and e["paperLevels"] is None for e in x["topFive"])
assert all(e["tier"]=="DATA_STALE" for e in m.make(scan,{}, {},{},now+1500)["topFive"])
print("V4.9 offline board tests PASS")
