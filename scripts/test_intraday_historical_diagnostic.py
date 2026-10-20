import importlib.util
from pathlib import Path
s=importlib.util.spec_from_file_location("diag",Path(__file__).with_name("intraday_historical_diagnostic.py"))
import sys
sys.path.insert(0,str(Path(__file__).parent))
m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
assert m.performance([])["closed"]==0
rows=[{"signalCandleEndMs":i*1000,"netR":v,"pattern":"TREND_PULLBACK","side":"LONG"}
      for i,v in enumerate([2.0,-1.0,1.0,-1.5])]
metrics=m.performance(rows)
assert metrics["closed"]==4 and metrics["winRate"]==.5
assert metrics["meanNetR"]==.125
assert metrics["maxDrawdownR"]==1.5
split=m.partition_summary(rows,0,4000)
assert split["developmentPeriod"]["closed"]==3
assert split["untouchedTimeHoldout"]["closed"]==1
bar={"open":100,"high":102,"low":98,"close":101}
past=[bar,{"open":100,"high":111,"low":88,"close":101}]
both=m.simulate(past,0,"LONG",1.0)
assert both["outcome"]=="STOP", both
assert both["netR"]<0
print("Intraday historical stratification tests passed")
