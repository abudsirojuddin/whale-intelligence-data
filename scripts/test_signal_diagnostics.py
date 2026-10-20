import importlib.util
from pathlib import Path
from datetime import datetime, timezone
sp=importlib.util.spec_from_file_location("diag",Path(__file__).with_name("signal_diagnostics.py"))
diag=importlib.util.module_from_spec(sp)
sp.loader.exec_module(diag)
now=datetime.now(timezone.utc).timestamp()
iso=lambda x:datetime.fromtimestamp(x,timezone.utc).isoformat()
addr="0x"+"a"*40
row={"address":addr,"quality":"EVALUATED","score":75,"netRealizedExFunding30":5000,
      "profitFactorCloseOrders30":2,"realizedDrawdownProxyToEquity":.04,
      "closingDays30":12,"closingOrders30":45,"historyTruncated":False,"checkedAt":iso(now-100)}
pos={"wallets":{addr:{"BTC":{"side":"LONG","notional":90000}}},
     "checkedAtByWallet":{addr:iso(now-100)}}
events={"events":[{"id":"e1","address":addr,"coin":"BTC","side":"LONG","event":"OPEN","notional":90000,"time":iso(now-120)}]}
stage,reasons,samples=diag.evaluate(pos,{"ranking":[row]},events,{"setups":[]},now)
assert stage["qualifiedWalletsWithFreshSnapshots"]==1
assert reasons["NO_QUALIFIED_CONSENSUS"]==1
assert stage["paperSetupsGenerated"]==0
row2={**row,"address":"0x"+"b"*40}
pos["wallets"][row2["address"]]={"BTC":{"side":"LONG","notional":60000}}
pos["checkedAtByWallet"][row2["address"]]=iso(now-100)
stage,reasons,samples=diag.evaluate(pos,{"ranking":[row,row2]},events,{},now)
assert stage["eventsWithQualifiedConsensus"]==1
assert reasons["TECHNICAL_VALIDATION_REQUIRED"]==1
events["events"][0]["coin"]="UNKNOWN"
stage,reasons,samples=diag.evaluate(pos,{"ranking":[row,row2]},events,{},now)
assert reasons["OUTSIDE_RESEARCH_UNIVERSE"]==1
print("V4.6 diagnostic offline tests PASS")
