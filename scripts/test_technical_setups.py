"""Offline forward-only checks for independent technical paper proposals."""
import importlib.util
from pathlib import Path
from datetime import datetime,timezone
path=Path(__file__).with_name("build_technical_setups.py")
spec=importlib.util.spec_from_file_location("bts",path)
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
now=datetime(2026,10,20,4,0,tzinfo=timezone.utc).timestamp()
at=lambda v:datetime.fromtimestamp(v,timezone.utc).isoformat()
example={"coin":"ARB","status":"TECHNICAL_PASS","trend":{"direction":"LONG"},
"paperScenarios":{"LONG":{"entryZoneLow":100,"entryZoneHigh":101,"stopLoss":98,
"takeProfit1":106,"markPrice":100.5,"estimatedNetRR":1.7,"expiresAt":at(now+600)}}}
data={"apiHealthy":True,"updatedAt":at(now-30),"expiresAt":at(now+270),"coins":[example]}
assert len(mod.extract(data,now))==1
assert mod.extract(data,now+400)==[]
assert mod.extract({**data,"apiHealthy":False},now)==[]
bad={**example,"paperScenarios":{"LONG":{**example["paperScenarios"]["LONG"],"stopLoss":110}}}
assert mod.extract({**data,"coins":[bad]},now)==[]
print("V4.8 offline tests passed")
