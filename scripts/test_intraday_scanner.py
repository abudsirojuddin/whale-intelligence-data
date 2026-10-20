"""Deterministic offline tests for the independent Binance intraday scanner."""
import importlib.util
from pathlib import Path
from unittest.mock import patch

spec=importlib.util.spec_from_file_location("intraday",Path(__file__).with_name("intraday_scanner.py"))
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

assert abs(mod.ema([2.0]*70,20)[-1]-2.0)<1e-10
assert mod.number("NaN") is None
assert mod.number(None) is None
assert mod.rsi([float(i+1) for i in range(70)])==100

now=1_800_000_000_000
def fake_bars(interval, count=100):
    length=mod.PERIODS[interval]
    # Last fully closed kline ends 5 seconds before the present.
    start=now-5_000-count*length
    return [[start+i*length,"100","102","99","101","1500",
             start+(i+1)*length-1] for i in range(count)]
for interval in ("15m","1h","4h"):
    bars=mod.candles(fake_bars(interval),interval,now)
    assert len(bars)==100
    # An in-progress candle cannot affect the result.
    data=fake_bars(interval)+[[now-1,"100","9000","1","9000","100",now+1000]]
    assert len(mod.candles(data,interval,now))==100

exchange={"symbols":[{"symbol":"BTCUSDT","contractType":"PERPETUAL",
    "status":"TRADING","quoteAsset":"USDT","onboardDate":0},
    {"symbol":"LOWUSDT","contractType":"PERPETUAL","status":"TRADING",
     "quoteAsset":"USDT","onboardDate":0}]}
ticks=[{"symbol":"BTCUSDT","quoteVolume":"800000000","priceChangePercent":"4"},
       {"symbol":"LOWUSDT","quoteVolume":"1000","priceChangePercent":"4"}]
books=[{"symbol":"BTCUSDT","bidPrice":"100","askPrice":"100.01"},
       {"symbol":"LOWUSDT","bidPrice":"1","askPrice":"1.01"}]
funding=[{"symbol":"BTCUSDT","lastFundingRate":".0001"}]
chosen, _, _=mod.shortlist(exchange,ticks,books,funding,now)
assert chosen==["BTCUSDT"]
# No directional alignment => no research signal.
flat=[{"open":100,"high":101,"low":99,"close":100,"volume":100,
       "start":i*900000,"end":(i+1)*900000-1} for i in range(100)]
try:
    mod.analyze("BTCUSDT",{"15m":flat,"1h":flat,"4h":flat},
                books[0],funding[0],[],now)
except ValueError as e:
    assert str(e)=="TREND_NOT_ALIGNED"
else:
    raise AssertionError("Expected fail-closed rejection")
with patch.dict("os.environ",{},clear=True):
    assert mod.telegram("test")==False
print("Intraday offline tests passed")
