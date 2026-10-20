import importlib.util
from pathlib import Path
from datetime import datetime,timezone
spec=importlib.util.spec_from_file_location("n",Path(__file__).with_name("notify_paper_setups.py"))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
now=datetime(2026,10,20,5,tzinfo=timezone.utc).timestamp()
t={"id":"paper-test","coin":"ARB","side":"LONG","strategy":"TECHNICAL_MOMENTUM",
"status":"WAITING_ENTRY","firstSeenAt":m.iso(now-30),"expiresAt":m.iso(now+700),
"entryZoneLow":0.199,"entryZoneHigh":0.20,"stopLoss":0.197,"takeProfit":0.205}
assert m.eligible(t,now)
assert not m.eligible({**t,"expiresAt":m.iso(now-1)},now)
assert not m.eligible({**t,"status":"CLOSED_TP1"},now)
assert not m.eligible({**t,"stopLoss":0.201},now)
assert "BUKAN SINYAL EKSEKUSI" in m.format_message(t)
print("V5 paper-only Telegram tests PASS")
