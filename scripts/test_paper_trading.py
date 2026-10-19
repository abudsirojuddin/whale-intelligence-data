"""Basic offline tests for paper evaluation without exchange or Telegram access."""
import importlib.util
from datetime import datetime, timezone
from pathlib import Path
spec=importlib.util.spec_from_file_location("paper",Path(__file__).with_name("paper_trading.py"))
paper=importlib.util.module_from_spec(spec)
spec.loader.exec_module(paper)
base=datetime(2026,10,19,5,tzinfo=timezone.utc).timestamp()
def item(side="LONG"):
    lo,hi,stop,tp=(100,101,99,105) if side=="LONG" else (100,101,103,96)
    return {"coin":"BTC","side":side,"status":"WAITING_ENTRY","firstSeenAt":paper.iso(base),
       "expiresAt":paper.iso(base+900),"entryZoneLow":lo,"entryZoneHigh":hi,
       "stopLoss":stop,"takeProfit":tp,"lastBarEndMs":0}
def bar(index,op,high,low,close):
    start=int((base+index*60)*1000)
    return {"start":start,"end":start+60000,"o":op,"h":high,"l":low,"c":close}
t=item()
paper.progress(t,[bar(1,100.5,102,100,101),bar(2,103,106,101,105)],base+240)
assert t["status"]=="CLOSED_TP1" and t["netR"]>0
t=item()
paper.progress(t,[bar(1,100.5,106,98,101)],base+240)
assert t["status"]=="CLOSED_STOP" and t["netR"]<0
t=item("SHORT")
paper.progress(t,[bar(1,100.2,101,99,100),bar(2,99,100,95,96)],base+240)
assert t["status"]=="CLOSED_TP1" and t["netR"]>0
t=item("SHORT")
paper.progress(t,[bar(1,100.5,101,100,100),bar(2,110,110,99,105)],base+240)
assert t["status"]=="CLOSED_STOP" and t["paperExitPrice"]>103
t=item()
paper.progress(t,[bar(i,106,107,106,106) for i in range(1,18)],base+1200)
assert t["status"]=="EXPIRED"
s={"status":"SETUPS_AVAILABLE","updatedAt":paper.iso(base),"setups":[{
    "coin":"BTC","direction":"LONG","entryZoneLow":100,"entryZoneHigh":101,
    "stopLoss":99,"takeProfit1":105,"markPrice":100.5,
    "expiresAt":paper.iso(base+900),"qualifiedWallets":2
}]}
ledger=[]
assert paper.register(ledger,s,base+90)==1
assert paper.register(ledger,s,base+91)==0
assert paper.register([],s,base+700)==0
assert paper.report([],base)["status"]=="INSUFFICIENT_SAMPLE"
print("Offline simulation tests: PASS")
