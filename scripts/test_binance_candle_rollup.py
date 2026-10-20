import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
from binance_candle_rollup import resample,compare,audit,P15
base=1_800_000_000_000
base=(base//(16*P15))*(16*P15)
bars=[]
for i in range(16):
    start=base+i*P15
    bars.append({"start":start,"end":start+P15-1,
                 "open":100+i,"high":102+i,"low":99+i,"close":101+i,"volume":2})
four,err=resample(bars,"4h")
assert not err and len(four)==1
assert four[0]["volume"]==32
assert four[0]["high"]==117
assert resample(bars[:-1],"4h")[0]==[]
one,err=resample(bars,"1h")
assert len(one)==4 and not err
assert compare(four,four,16*P15)["matchingNative"]==1
different=[dict(four[0],close=111)]
assert compare(four,different,16*P15)["conflictingNative"]==1
assert audit({},base+16*P15)["status"]=="NO_TRADE"
print("PASS: strict 15m roll-up and native candle comparison")
