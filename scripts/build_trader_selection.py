"""Create auditable V4.4 trader selection, no automatic signal or execution."""
import json
from datetime import datetime, timezone
from pathlib import Path
from selection_rules import is_qualified, activity_profile, review_tier, time_of

ROOT=Path(__file__).resolve().parent.parent
def load(name): return json.loads((ROOT/name).read_text(encoding="utf-8"))
def main():
    ranking=load("ranking.json")
    now=datetime.now(timezone.utc).timestamp()
    candidates=ranking.get("ranking",[])
    results=[]
    for row in candidates:
        checked=row.get("checkedAt")
        age_hours=round((now-time_of(checked))/3600,2) if checked and time_of(checked) else None
        results.append({
            "address":row.get("address"),"qualityStatus":row.get("quality","PENDING"),
            "reviewTier":review_tier(row,now),
            "activityProfile":activity_profile(row),
            "score":row.get("score") if row.get("quality")=="EVALUATED" else None,
            "checkedAt":checked,"ageHours":age_hours,
            "netRealizedExFunding30":row.get("netRealizedExFunding30"),
            "profitFactorCloseOrders30":row.get("profitFactorCloseOrders30"),
            "winRateCloseOrders30":row.get("winRateCloseOrders30"),
            "closingOrders30":row.get("closingOrders30"),"closingDays30":row.get("closingDays30"),
            "dataIncomplete":bool(row.get("historyTruncated")),
        })
    results.sort(key=lambda x:(x["reviewTier"]=="RESEARCH_PRIORITY",x["score"] if x["score"] is not None else -1),reverse=True)
    priorities=[x for x in results if x["reviewTier"]=="RESEARCH_PRIORITY"]
    out={"updatedAt":datetime.now(timezone.utc).isoformat(),
        "rankingUpdatedAt":ranking.get("updatedAt"),
        "totalCandidates":len(results),"priorityCount":len(priorities),
        "watchlist":[x["address"] for x in priorities[:20]],
        "traders":results,
        "methodology":"Closing-order quality and observation frequency, NOT actual intraday holding period. Watchlist is research only.",
        "caution":"A good historic ranking cannot guarantee a profitable trade; no automatic trade entries."}
    (ROOT/"trader_selection.json").write_text(json.dumps(out,ensure_ascii=False,separators=(",",":"))+"\n",encoding="utf-8")
    print(f"Selection: {len(results)} wallets, {len(priorities)} research-priority, {len(out['watchlist'])} watchlist.")
if __name__=="__main__": main()
