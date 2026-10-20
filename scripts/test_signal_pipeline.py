"""Offline V4.5 quality and alert gating tests."""
import importlib.util
from pathlib import Path
from datetime import datetime, timezone, timedelta
spec=importlib.util.spec_from_file_location("sp",Path(__file__).with_name("signal_pipeline.py"))
sp=importlib.util.module_from_spec(spec)
spec.loader.exec_module(sp)
now=datetime.now(timezone.utc).timestamp()
def iso(t):return sp.now_iso(t)
row={"address":"0x"+"a"*40,"quality":"EVALUATED","score":83,"netRealizedExFunding30":300,
     "profitFactorCloseOrders30":2,"realizedDrawdownProxyToEquity":.03,
     "closingDays30":15,"closingOrders30":80,"historyTruncated":False,"checkedAt":iso(now-100)}
row2={**row,"address":"0x"+"b"*40}
assert not sp.paper_has_edge({"status":"INSUFFICIENT_SAMPLE"})
assert not sp.paper_has_edge({"status":"EVIDENCE_AVAILABLE","metrics90d":{"closed":50,
"winRate":.5,"profitFactor":1.6,"expectancyR":.2},"metrics30d":{"closed":40}})
assert sp.paper_has_edge({"status":"EVIDENCE_AVAILABLE","metrics90d":{"closed":55,
"winRate":.57,"profitFactor":1.6,"expectancyR":.2,"maxDrawdownR":4},
"metrics30d":{"closed":34},"uncertainDataGaps":0})
addresses=[row["address"],row2["address"]]
positions={"BTC":{"side":"LONG","notional":150000}}
state={"wallets":{a:positions for a in addresses},"checkedAtByWallet":{a:iso(now-60) for a in addresses}}
event={"id":"test-event","time":iso(now-100),"address":row["address"],"coin":"BTC","side":"LONG",
       "event":"OPEN","notional":150000}
events,quality,cons=sp.opportunity_events({"events":[event]},state,{"ranking":[row,row2]},now)
assert len(events)==1 and events[0]["tier"]=="CONSENSUS_WATCH"
state["checkedAtByWallet"][row["address"]]=iso(now-2000)
events,quality,cons=sp.opportunity_events({"events":[event]},state,{"ranking":[row,row2]},now)
assert not events
print("V4.5 offline tests passed")
