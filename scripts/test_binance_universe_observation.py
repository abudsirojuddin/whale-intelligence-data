import importlib.util,sys,time
from pathlib import Path
s=importlib.util.spec_from_file_location("obs",Path(__file__).with_name("binance_universe_observation.py"))
m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
now=int(time.time()*1000)
ticker={"stream":"!ticker@arr","data":[{"e":"24hrTicker","s":"BTCUSDT","E":now,"q":"800000000",
    "P":"2","c":"80000"},{"e":"24hrTicker","s":"ALTUSDT","E":now,"q":"10000","P":"1","c":"2"}]}
rec=m.parse_ticker(ticker,now)
assert len(rec)==2
book={"stream":"!bookTicker","data":{"s":"BTCUSDT","b":"80000","a":"80001","E":now}}
b=m.parse_book(book,now)
assert b and b["spreadBps"]<15
top,checks=m.rank({r["symbol"]:r for r in rec},{"BTCUSDT":b},now)
assert [x["symbol"] for x in top]==["BTCUSDT"],top
assert checks["commonSymbols"]==1
assert m.parse_ticker(ticker,now+50000)==[]
assert m.parse_book(book,now+50000) is None
print("Binance market breadth offline tests passed")
