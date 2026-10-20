import sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
from binance_derivatives_snapshot import mark_rows,book_rows,assemble
now=int(time.time()*1000)
mark={"stream":"!markPrice@arr@1s","data":[{"e":"markPriceUpdate","s":"BTCUSDT","E":now,"p":"81000","i":"81002","r":"0.0001"}]}
book={"stream":"!bookTicker","data":{"s":"BTCUSDT","E":now,"b":"80999","a":"81001"}}
a=mark_rows(mark,now);b=book_rows(book,now)
assert a and b
assert not mark_rows(mark,now+60000)
assert not book_rows(book,now+60000)
s=assemble({"BTCUSDT":a[0]},{"BTCUSDT":b[0]},now)
assert s["status"]=="PARTIAL_MARKET_CONTEXT"
assert s["eligibleForSignal"] is False and s["tradeReady"] is False
assert assemble({}, {}, now)["status"]=="DATA_UNAVAILABLE"
print("PASS: Binance USD-M mark/book safety tests")
