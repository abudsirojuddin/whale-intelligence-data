"""V4.6 diagnostics only: account for why opportunities fail.
No recommendation, notification, or paper trade is generated here.
"""
import json
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from selection_rules import is_qualified, time_of, number
from market_universe import RESEARCH_COINS, MIN_24H_VOLUME_USD

ROOT=Path(__file__).resolve().parent.parent
def load(name,default):
    p=ROOT/name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default
def save(name,data):
    (ROOT/name).write_text(json.dumps(data,ensure_ascii=False,separators=(",",":"))+"\n",encoding="utf-8")
def reason(event,rank,watched,now):
    flags=[]
    address=str(event.get("address","")).lower()
    if not is_qualified(rank.get(address),now):flags.append("WALLET_NOT_QUALIFIED")
    if event.get("coin") not in RESEARCH_COINS:flags.append("OUTSIDE_RESEARCH_UNIVERSE")
    if event.get("event") not in ("OPEN","INCREASE","REVERSE"):flags.append("NOT_OPEN_OR_INCREASE")
    if not 0<=now-time_of(event.get("time"))<=1200:flags.append("EVENT_STALE")
    if number(event.get("notional"))<50000:flags.append("NOTIONAL_BELOW_THRESHOLD")
    active=watched.get(address,{}).get(event.get("coin"),{})
    if active.get("side")!=event.get("side") or not active:
        flags.append("CURRENT_POSITION_NOT_CONFIRMED")
    return flags
def evaluate(position,ranking,alerts,market,now):
    qualified={str(row.get("address","")).lower():row for row in ranking.get("ranking",[]) if is_qualified(row,now)}
    watches=position.get("wallets",{})
    checked=position.get("checkedAtByWallet",{})
    active={}
    eligible_fresh={}
    for a,poses in watches.items():
        if a.lower() not in qualified or not isinstance(poses,dict):continue
        if not 0<=now-time_of(checked.get(a) or checked.get(a.lower()))<=1200:continue
        eligible_fresh[a.lower()]=qualified[a.lower()]
        for coin,p in poses.items():
            if p.get("side") in ("LONG","SHORT") and number(p.get("notional"))>=50000:
                active.setdefault((coin,p["side"]),set()).add(a.lower())
    counts=Counter(); sample=[]; qualified_events=0; consensus_events=0
    for ev in alerts.get("events",[])[:100]:
        if not isinstance(ev,dict):continue
        flags=reason(ev,qualified,watches,now)
        if not flags:
            a=str(ev["address"]).lower()
            if a not in eligible_fresh:flags.append("WALLET_SNAPSHOT_STALE")
            coin,side=ev["coin"],ev["side"]
            same=active.get((coin,side),set())
            opposite=active.get((coin,"SHORT" if side=="LONG" else "LONG"),set())
            if a in eligible_fresh:qualified_events+=1
            if len(same)<2 or len(same)/max(1,len(same|opposite))<0.7:
                flags.append("NO_QUALIFIED_CONSENSUS")
            else:consensus_events+=1
        if not flags:
            # This stage only says an API-based technical validation is needed;
            # it does not claim liquidity or trend checks passed.
            flags.append("TECHNICAL_VALIDATION_REQUIRED")
        counts.update(flags)
        if len(sample)<30:
            sample.append({"id":str(ev.get("id","")),"coin":ev.get("coin"),
                "side":ev.get("side"),"occurredAt":ev.get("time"),
                "reasons":flags})
    stage={
        "totalCandidateWallets":len(ranking.get("ranking",[])),
        "historicallyEvaluatedWallets":sum(x.get("quality")=="EVALUATED" for x in ranking.get("ranking",[])),
        "qualifiedWalletsInRanking":len(qualified),
        "qualifiedWalletsWithFreshSnapshots":len(eligible_fresh),
        "observedPositionPairsWithTwoQualifiedWallets":sum(len(v)>=2 for v in active.values()),
        "loggedEventsConsidered":sum(counts.values()) and min(len(alerts.get("events",[])),100) or 0,
        "qualifiedRecentEvents":qualified_events,
        "eventsWithQualifiedConsensus":consensus_events,
        "paperSetupsGenerated":len(market.get("setups",[])),
    }
    return stage,dict(counts),sample

def main():
    now=time.time()
    overview=load("setups.json",{})
    stages,reasons,examples=evaluate(load("position_state.json",{}),
        load("ranking.json",{}),load("alerts.json",{}),overview,now)
    past=load("signal_diagnostics_history.json",{"snapshots":[]})
    snapshots=past.get("snapshots",[])
    snapshots.append({"at":datetime.fromtimestamp(now,timezone.utc).isoformat(),
        "stages":stages,"reasons":reasons})
    snapshots=snapshots[-144:]
    save("signal_diagnostics_history.json",{"updatedAt":snapshots[-1]["at"],"snapshots":snapshots})
    save("signal_diagnostics.json",{"updatedAt":snapshots[-1]["at"],"stages":stages,
        "rejectionReasons":reasons,"samples":examples,
        "dailySignalTarget":5,"executionSignalsPromised":False,
        "notes":["Counts may overlap because one event can fail multiple criteria.",
                 "Historical event count is not a unique number of daily opportunities.",
                 "Liquidity/spread/trend are not marked passed without a live exchange check.",
                 "Use diagnostic results to plan research, not to bypass quality controls."]})
    print("V4.6 diagnostics:",stages,"reasonCounts:",reasons)

if __name__=="__main__":main()
