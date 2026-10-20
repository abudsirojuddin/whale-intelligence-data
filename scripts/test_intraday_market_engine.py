import sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
import intraday_market_engine as m
now=int(time.time()*1000)
out=m.assess({}, {}, {}, {}, now)
assert out["status"]=="NO_TRADE" and out["newSignals"]==[]
assert out["rejectionCounts"]["OPEN_INTEREST_UNVERIFIED"]==3
assert m.accepted_instrument({}, "BTCUSDT", now) is None
assert m.oi_history({}, "BTCUSDT", now) is None
assert m.market_context({}, "BTCUSDT", now) is None
assert m.bars_from_bridge({}, "BTCUSDT", now) is None
print("PASS: Full Binance intraday engine fails closed on absent live context")
