"""V4.8 independent technical-momentum PAPER research proposals.

Produces an observation snapshot only. It never requests market orders and it
does not imply approval for manual futures execution. Whale strategy remains
separate in setups.json.
"""
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path
from market_universe import RESEARCH_COINS

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "technical_setups.json"

def parse_time(x):
    try: return datetime.fromisoformat(str(x).replace("Z","+00:00")).timestamp()
    except (ValueError,TypeError,OverflowError): return 0.0

def finite_positive(x):
    try:
        f=float(x)
        return f if math.isfinite(f) and f>0 else 0.0
    except (ValueError,TypeError,OverflowError): return 0.0

def extract(scan, now):
    """Only current complete exchange snapshots; never reuse expired proposals."""
    if not isinstance(scan,dict) or scan.get("apiHealthy") is not True:
        return []
    stamp=parse_time(scan.get("updatedAt"))
    end=parse_time(scan.get("expiresAt"))
    if not 0<=now-stamp<=300 or not now<end:
        return []
    result=[]
    for item in scan.get("coins",[]):
        coin=item.get("coin")
        if coin not in RESEARCH_COINS or item.get("status")!="TECHNICAL_PASS":
            continue
        direction=item.get("trend",{}).get("direction")
        if direction not in ("LONG","SHORT"): continue
        levels=item.get("paperScenarios",{}).get(direction,{})
        lo,hi=(finite_positive(levels.get(k)) for k in ("entryZoneLow","entryZoneHigh"))
        stop=finite_positive(levels.get("stopLoss"))
        target=finite_positive(levels.get("takeProfit1"))
        mark=finite_positive(levels.get("markPrice"))
        deadline=parse_time(levels.get("expiresAt"))
        if not (0<lo<hi and mark>0 and 0<deadline-now<=900):continue
        if not (stop<lo<hi<target if direction=="LONG" else target<lo<hi<stop):
            continue
        if finite_positive(levels.get("estimatedNetRR"))<1.55: continue
        result.append({
            "coin":coin, "direction":direction, "strategy":"TECHNICAL_MOMENTUM",
            "status":"PAPER_RESEARCH_ONLY",
            "markPrice":mark, "entryZoneLow":lo,"entryZoneHigh":hi,
            "stopLoss":stop,"takeProfit1":target,
            "takeProfit2":finite_positive(levels.get("takeProfit2")),
            "estimatedNetRR":finite_positive(levels.get("estimatedNetRR")),
            "spreadBps":levels.get("spreadBps"),"expiresAt":levels["expiresAt"],
            "qualifiedWallets":0,
            "sourceScanAt":scan["updatedAt"],
            "condition":"Live multi-coin trend+spread+volume+ATR; no whale confirmation"
        })
    return result

def main():
    now=time.time()
    source=ROOT/"market_scan.json"
    scan=json.loads(source.read_text(encoding="utf-8")) if source.exists() else {}
    scenarios=extract(scan,now)
    result={
        "updatedAt":datetime.fromtimestamp(now,timezone.utc).isoformat(),
        "strategy":"TECHNICAL_MOMENTUM",
        "status":"SETUPS_AVAILABLE" if scenarios else "NO_TRADE",
        "setups":scenarios,
        "disclaimer":"Research scenarios for prospective paper testing only. Not qualified whale consensus, not a verified trading signal."
    }
    OUT.write_text(json.dumps(result,ensure_ascii=False,separators=(",",":"))+"\n",encoding="utf-8")
    print("V4.8 technical research scenarios:",len(scenarios))

if __name__=="__main__":
    main()
