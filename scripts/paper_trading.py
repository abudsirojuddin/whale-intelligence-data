"""Whale Intelligence V4.3: prospective paper-trade evaluation only.
No broker orders, auto-copy trading, or claimed execution fills.
"""
import json
import math
import pathlib
import time
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from market_universe import RESEARCH_COINS

ROOT = pathlib.Path(__file__).resolve().parent.parent
LEDGER = ROOT / "paper_trades.json"
PERFORMANCE = ROOT / "paper_performance.json"
SETUPS = ROOT / "setups.json"
TECHNICAL_SETUPS = ROOT / "technical_setups.json"
API = "https://api.hyperliquid.xyz/info"
MAX_HISTORY_SECONDS = 8 * 3600
MAX_HOLD_SECONDS = 6 * 3600
MAX_LEDGER = 450
FEE_SIDE = 0.0006
SLIPPAGE_SIDE = 0.0005

def when(value):
    try: return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError, OverflowError): return 0

def iso(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat()

def num(value):
    try:
        v = float(value)
        return v if math.isfinite(v) else 0.0
    except (ValueError, TypeError, OverflowError): return 0.0

def read(path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default

def save(path, value):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    tmp.replace(path)

def candles(coin, start_ms, end_ms):
    payload = {"type":"candleSnapshot", "req":{
        "coin":coin, "interval":"1m", "startTime":int(start_ms), "endTime":int(end_ms)}}
    request = urllib.request.Request(API, data=json.dumps(payload).encode(), method="POST",
        headers={"Content-Type":"application/json", "User-Agent":"WhaleIntelligencePaper/4.3"})
    with urllib.request.urlopen(request, timeout=35) as response:
        raw = json.loads(response.read(5000000))
    if not isinstance(raw, list):
        raise ValueError("Unexpected candle response")
    result = []
    for item in raw:
        if not isinstance(item, dict): continue
        stamp = int(num(item.get("t")))
        end = int(num(item.get("T"))) or stamp + 60000
        op, hi, lo, cl = (num(item.get(k)) for k in ("o","h","l","c"))
        if (stamp >= start_ms-60000 and end <= end_ms and stamp>0 and op>0 and lo>0 and
                hi >= max(op,cl,lo) and min(op,cl,hi)>=lo and 30000<=end-stamp<=90000):
            result.append({"start":stamp,"end":end,"o":op,"h":hi,"l":lo,"c":cl})
    return sorted({v["start"]:v for v in result}.values(),key=lambda v:v["start"])

def register(ledger, setups, now):
    if setups.get("status") != "SETUPS_AVAILABLE" or not isinstance(setups.get("setups"),list):
        return 0
    stamp = when(setups.get("updatedAt"))
    if not 0<=now-stamp<=600: return 0
    ids = {x["id"] for x in ledger}
    added = 0
    for s in setups["setups"]:
        strategy = s.get("strategy", "WHALE_CONSENSUS")
        if strategy not in ("WHALE_CONSENSUS", "TECHNICAL_MOMENTUM"): continue
        coin, side = s.get("coin"), s.get("direction")
        if coin not in RESEARCH_COINS or side not in ("LONG","SHORT"): continue
        uid = f"{int(stamp*1000)}:{coin}:{side}:{strategy}"
        if uid in ids: continue
        deadline = when(s.get("expiresAt"))
        lo, hi = num(s.get("entryZoneLow")),num(s.get("entryZoneHigh"))
        stop,tp,mark=num(s.get("stopLoss")),num(s.get("takeProfit1")),num(s.get("markPrice"))
        if not (stamp < deadline <= stamp+1200 and 0<lo<hi and mark>0): continue
        if not (stop<lo<hi<tp if side=="LONG" else tp<lo<hi<stop):continue
        if any(x["coin"]==coin and x.get("strategy","WHALE_CONSENSUS")==strategy and x["status"] in ("WAITING_ENTRY","OPEN") for x in ledger):continue
        ledger.append({"id":uid,"coin":coin,"side":side,"strategy":strategy,"status":"WAITING_ENTRY",
            "sourceCreatedAt":iso(stamp),"firstSeenAt":iso(now),"expiresAt":iso(deadline),
            "entryZoneLow":lo,"entryZoneHigh":hi,"stopLoss":stop,"takeProfit":tp,
            "suggestedMarkPrice":mark,"lastBarEndMs":0,
            "walletConsensus":int(num(s.get("qualifiedWallets")))})
        ids.add(uid)
        added+=1
    return added

def settle(t, outcome, ref, stamp):
    sign = 1 if t["side"]=="LONG" else -1
    entry = t["paperEntryPrice"]
    executed_exit = ref * (1 - sign*SLIPPAGE_SIDE)
    risk = abs(entry-t["stopLoss"])
    if min(entry,executed_exit,risk)<=0:
        t["status"]="DATA_GAP"
        return
    gross=sign*(executed_exit-entry)
    costs=FEE_SIDE*(entry+executed_exit)
    t.update({"status":outcome,"closedAt":iso(stamp),
      "paperExitPrice":round(executed_exit,8),"grossR":round(gross/risk,4),
      "costR":round(costs/risk,4),"netR":round((gross-costs)/risk,4),
      "pnlPerCoinUsd":round(gross-costs,8)})

def progress(t, bars, now):
    if t.get("status") not in ("WAITING_ENTRY","OPEN"):return
    seen = when(t["firstSeenAt"])
    activated = math.ceil(seen/60)*60000  # only fully formed candles AFTER first detection
    deadline = when(t["expiresAt"])
    prev_end=int(num(t.get("lastBarEndMs")))
    if t["status"]=="OPEN" and now-when(t.get("lastEvaluatedAt") or t["openedAt"])>MAX_HISTORY_SECONDS:
        t.update({"status":"DATA_GAP","reason":"Evaluation delay exceeds 8 hours"})
        return
    bars=[b for b in bars if b["start"]>=activated and b["end"]>prev_end]
    if t["status"]=="OPEN":
        last_end=prev_end or int(when(t["openedAt"])*1000)
        if bars and bars[0]["start"]-last_end>180000:
            t.update({"status":"DATA_GAP","reason":"Gap in available candles"})
            return
    elif bars and bars[0]["start"]>activated+180000:
        t.update({"status":"DATA_GAP","reason":"Missing candles at time of setup"})
        return
    for b in bars:
        if t["status"]=="WAITING_ENTRY":
            if b["end"]/1000>deadline:
                t.update({"status":"EXPIRED","closedAt":iso(deadline)})
                break
            if b["l"]<=t["entryZoneHigh"] and b["h"]>=t["entryZoneLow"]:
                sign=1 if t["side"]=="LONG" else -1
                ref=t["entryZoneHigh"] if sign==1 else t["entryZoneLow"]
                entry=ref*(1+sign*SLIPPAGE_SIDE)
                if not (t["stopLoss"]<entry<t["takeProfit"] if sign==1 else t["takeProfit"]<entry<t["stopLoss"]):
                    t["status"]="INVALID_SETUP"
                    break
                t.update({"status":"OPEN","openedAt":iso(b["end"]/1000),"paperEntryPrice":round(entry,8)})
                hit=b["l"]<=t["stopLoss"] if sign==1 else b["h"]>=t["stopLoss"]
                if hit:
                    stop_exit=min(t["stopLoss"],b["o"]) if sign==1 else max(t["stopLoss"],b["o"])
                    settle(t,"CLOSED_STOP",stop_exit,b["end"]/1000)
                    break
                # Never count TP on entry candle: it may have preceded the entry.
        elif t["status"]=="OPEN":
            sign=1 if t["side"]=="LONG" else -1
            sl=b["l"]<=t["stopLoss"] if sign==1 else b["h"]>=t["stopLoss"]
            tp=b["h"]>=t["takeProfit"] if sign==1 else b["l"]<=t["takeProfit"]
            if sl:
                stop_exit=min(t["stopLoss"],b["o"]) if sign==1 else max(t["stopLoss"],b["o"])
                settle(t,"CLOSED_STOP",stop_exit,b["end"]/1000)
                break
            if tp:
                settle(t,"CLOSED_TP1",t["takeProfit"],b["end"]/1000)
                break
            if b["end"]/1000>=when(t["openedAt"])+MAX_HOLD_SECONDS:
                settle(t,"CLOSED_TIME",b["c"],b["end"]/1000)
                break
        t["lastBarEndMs"]=b["end"]
        t["lastEvaluatedAt"]=iso(b["end"]/1000)
    if t["status"]=="WAITING_ENTRY" and now>deadline+120:
        if not bars and now-seen>180:
            t.update({"status":"DATA_GAP","reason":"No candles for entry window"})
        else:
            t.update({"status":"EXPIRED","closedAt":iso(deadline)})

def report(trades, now):
    decided=[t for t in trades if t.get("status") in ("CLOSED_TP1","CLOSED_STOP","CLOSED_TIME") and "netR" in t]
    recent90=[t for t in decided if 0<=now-when(t.get("closedAt"))<90*86400]
    recent30=[t for t in recent90 if now-when(t["closedAt"])<30*86400]
    def metrics(rows):
        nums=[num(t["netR"]) for t in sorted(rows,key=lambda x:x["closedAt"])]
        won=sum(x for x in nums if x>0)
        lost=-sum(x for x in nums if x<0)
        peak=total=max_dd=0.0
        for v in nums:
            total+=v
            peak=max(peak,total)
            max_dd=max(max_dd,peak-total)
        return {"closed":len(nums),"wins":sum(v>0 for v in nums),"losses":sum(v<0 for v in nums),
            "winRate":round(sum(v>0 for v in nums)/len(nums),4) if nums else None,
            "profitFactor":round(won/lost,4) if lost else None,
            "expectancyR":round(sum(nums)/len(nums),4) if nums else None,
            "netTotalR":round(sum(nums),4),"maxDrawdownR":round(max_dd,4)}
    m30,m90=metrics(recent30),metrics(recent90)
    return {"updatedAt":iso(now),"status":"EVIDENCE_AVAILABLE" if m90["closed"]>=50 else "INSUFFICIENT_SAMPLE",
        "metrics30d":m30,"metrics90d":m90,"sampleGoalClosed":50,
        "openTrades":sum(t["status"]=="OPEN" for t in trades),
        "waitingEntry":sum(t["status"]=="WAITING_ENTRY" for t in trades),
        "expiredUnfilled":sum(t["status"]=="EXPIRED" for t in trades),
        "uncertainDataGaps":sum(t["status"]=="DATA_GAP" for t in trades),
        "notes":["Prospective hypothetical fills only, not investment signals.",
          "Uses 1-minute closed candles; ambiguous intrabar outcomes resolve to stop first.",
          "Assumed 0.06% fees + 0.05% adverse slippage PER SIDE, six-hour intraday exit.",
          "Excludes funding, taxes, margin/liquidation and Binance price differences. Drawdown in R, not account equity."]}

def main():
    now=time.time()
    journal=read(LEDGER,{"trades":[]})
    trades=journal.get("trades",[])
    if not isinstance(trades,list): raise ValueError("Invalid paper ledger")
    added=register(trades,read(SETUPS,{"status":"NO_TRADE"}),now)
    added+=register(trades,read(TECHNICAL_SETUPS,{"status":"NO_TRADE"}),now)
    grouped=defaultdict(list)
    for t in trades:
        if t.get("status") in ("WAITING_ENTRY","OPEN"):
            grouped[t["coin"]].append(t)
    for coin,group in grouped.items():
        first=min(max(when(x["firstSeenAt"]),when(x.get("lastEvaluatedAt"))) for x in group)
        if now-first>MAX_HISTORY_SECONDS:
            for t in group:
                t.update({"status":"DATA_GAP","reason":"Evaluation interval beyond eight hours"})
            continue
        try:
            bars=candles(coin,int((first-120)*1000),int(now*1000))
            if not bars and now-first>240:
                raise RuntimeError("No complete candles available")
        except (urllib.error.URLError,TimeoutError,ValueError,RuntimeError) as exc:
            print("Candle unavailable for",coin,type(exc).__name__)
            continue
        for t in group:
            progress(t,bars,now)
    active=[t for t in trades if t["status"] in ("WAITING_ENTRY","OPEN")]
    past=sorted([t for t in trades if t["status"] not in ("WAITING_ENTRY","OPEN")],
                key=lambda t:t.get("closedAt") or t.get("firstSeenAt") or "",reverse=True)
    trades=active+past[:MAX_LEDGER]
    save(LEDGER,{"updatedAt":iso(now),"version":"4.3","newSetups":added,"trades":trades,
        "disclaimer":"Forward-looking PAPER research only, not verified broker executions."})
    summary=report(trades,now)
    summary["byStrategy"]={name:report([t for t in trades if t.get("strategy","WHALE_CONSENSUS")==name],now) for name in ("WHALE_CONSENSUS","TECHNICAL_MOMENTUM")}
    save(PERFORMANCE,summary)
    print("New:",added,"open:",summary["openTrades"],"closed 90d:",summary["metrics90d"]["closed"],
          "quality:",summary["status"])

if __name__=="__main__":
    main()
