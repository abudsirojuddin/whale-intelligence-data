"""Historical *technical-pattern* diagnostic, NOT a Binance live trading signal.

Backtests patterns from closed USD-M archive candles. No historical spread, funding
or OI was acquired; all such mandatory live gates remain UNVERIFIED. Not
a strategy profitability validation. Entries are at next 15m candle open,
with adverse spread/slippage/fees; dual TP/SL touches are resolved as SL.
"""
import json
import math
from bisect import bisect_right
from pathlib import Path
from intraday_scanner import setup_direction, detect_pattern, atr, rsi

ROOT=Path(__file__).resolve().parent.parent
COST_PER_SIDE=.0011
HOLD_BARS=24

def history_at(series,timestamp):
    ends=[x["end"] for x in series]
    return series[:bisect_right(ends,timestamp)]

def simulate(bars,i,side,risk):
    """Uses only future bars, never an entry on the setup candle."""
    sign=1 if side=="LONG" else -1
    after=bars[i+1:i+1+HOLD_BARS]
    if not after:
        return None
    entry=after[0]["open"]*(1+sign*COST_PER_SIDE)
    stop=entry-sign*risk
    take=entry+sign*3*risk
    outcome="TIME"
    raw_exit=after[-1]["close"]
    for bar in after:
        stop_hit=bar["low"]<=stop if sign==1 else bar["high"]>=stop
        take_hit=bar["high"]>=take if sign==1 else bar["low"]<=take
        if stop_hit:
            outcome="STOP"
            raw_exit=min(stop,bar["open"]) if sign==1 else max(stop,bar["open"])
            break
        if take_hit:
            outcome="TARGET"
            raw_exit=take
            break
    exit_price=raw_exit*(1-sign*COST_PER_SIDE)
    net_r=sign*(exit_price-entry)/risk
    return {"outcome":outcome,"netR":round(net_r,4)}

def evaluate(dataset,symbol="BTCUSDT"):
    assert dataset.get("source")=="OFFICIAL_BINANCE_USDM_DELAYED_ARCHIVE"
    data=dataset.get("datasets",{})
    markets={}
    for tf in ("15m","1h","4h"):
        item=data.get(f"{symbol}:{tf}",{})
        if item.get("contiguous") is not True or item.get("count",0)<70:
            return {"status":"INSUFFICIENT_ARCHIVE","symbol":symbol}
        markets[tf]=item["candles"]
    candles=markets["15m"]
    rows=[]
    rejection={}
    next_allowed=0
    for i in range(220,len(candles)-HOLD_BARS):
        if i<next_allowed:
            continue
        t=candles[i]["end"]
        short=candles[:i+1]
        h1=history_at(markets["1h"],t)
        h4=history_at(markets["4h"],t)
        if min(len(short),len(h1),len(h4))<70:
            continue
        if (t-h1[-1]["end"]>3600000 or t-h4[-1]["end"]>14400000):
            continue
        try:
            side,ema20=setup_direction(short,h1,h4)
            if not side:
                reason="TREND_MIXED"
            else:
                a=atr(short)
                pattern=detect_pattern(short,ema20,a,side)
                close=short[-1]["close"]
                momentum=rsi([b["close"] for b in short])
                volume=short[-1]["volume"]/max(1e-9,sum(b["volume"] for b in short[-21:-1])/20)
                if not pattern:
                    reason="NO_PATTERN"
                elif not .002<=a/close<=.04:
                    reason="VOLATILITY"
                elif not ((52<=momentum<=72) if side=="LONG" else (28<=momentum<=48)):
                    reason="MOMENTUM"
                elif volume<1.10:
                    reason="VOLUME"
                else:
                    risk=1.5*a
                    if not .004<=risk/close<=.025:
                        reason="RISK_DISTANCE"
                    else:
                        result=simulate(candles,i,side,risk)
                        if result:
                            rows.append({"signalCandleEndMs":t,"symbol":symbol,
                                "side":side,"pattern":pattern,**result})
                            next_allowed=i+HOLD_BARS+1
                        continue
            rejection[reason]=rejection.get(reason,0)+1
        except (ValueError,KeyError,IndexError,ZeroDivisionError):
            rejection["INDICATOR_ERROR"]=rejection.get("INDICATOR_ERROR",0)+1
    net=[r["netR"] for r in rows]
    wins=sum(v>0 for v in net)
    positive=sum(v for v in net if v>0)
    negative=-sum(v for v in net if v<0)
    return {"status":"HISTORICAL_TECHNICAL_ONLY",
        "symbol":symbol,"evaluatedCandles":len(candles),
        "completedPaperPatterns":len(rows),"wins":wins,
        "winRate":round(wins/len(net),4) if net else None,
        "meanNetR":round(sum(net)/len(net),4) if net else None,
        "profitFactor":round(positive/negative,4) if negative else None,
        "rejections":rejection,"examples":rows[-15:],
        "tradeReady":False,
        "missingCriticalInputs":["historical executable spread","funding","open interest",
                                 "realtime close-to-alert delay","liquidation/margin simulation"],
        "disclaimer":"Historical pattern diagnostic, NOT a valid live-signal win-rate claim."}

def main():
    source=ROOT/"binance_archive_history.json"
    if not source.exists():
        raise SystemExit("Missing verified archive, no results published.")
    obj=json.loads(source.read_text("utf-8"))
    result=evaluate(obj)
    (ROOT/"intraday_historical_diagnostic.json").write_text(
        json.dumps(result,ensure_ascii=False,indent=2)+"\n","utf-8")
    print(json.dumps({k:result.get(k) for k in ("status","completedPaperPatterns",
          "meanNetR","tradeReady","missingCriticalInputs")},ensure_ascii=False))

if __name__=="__main__":
    main()
