from datetime import datetime, timezone
from selection_rules import is_qualified, activity_profile, review_tier

now=datetime(2026,10,19,6,tzinfo=timezone.utc).timestamp()
row={"quality":"EVALUATED","score":72,"netRealizedExFunding30":3000,
     "profitFactorCloseOrders30":1.7,"realizedDrawdownProxyToEquity":0.05,
     "closingDays30":12,"closingOrders30":120,"historyTruncated":False,
     "checkedAt":datetime.fromtimestamp(now-3600,timezone.utc).isoformat()}
assert is_qualified(row,now)
assert review_tier(row,now)=="RESEARCH_PRIORITY"
assert activity_profile(row)=="HIGH_FREQUENCY_ACTIVITY"
for patch in ({"score":64},{"historyTruncated":True},{"profitFactorCloseOrders30":1.2},
              {"closingDays30":5},{"checkedAt":datetime.fromtimestamp(now-60*3600,timezone.utc).isoformat()},
              {"netRealizedExFunding30":-1}):
    edited={**row,**patch}
    assert not is_qualified(edited,now),patch
assert activity_profile({"quality":"INSUFFICIENT"})=="UNKNOWN"
print("Selection quality gate tests passed")
