import sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
import intraday_alert_gate as g
now=int(time.time()*1000)
assert g.eligible({}, {}, now)[0]==[]
assert g.validate_signal({},now)=="UNVERIFIED_INSTRUMENT"
assert g.run(now=now,persist=False)["messageCount"]==0
assert g.PAPER_ALERT_EXPLICITLY_DISABLED is True
print("PASS: no fabricated, stale or unverified Binance V2 trade alert")
