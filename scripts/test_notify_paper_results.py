import importlib.util
from pathlib import Path
from datetime import datetime, timezone
spec = importlib.util.spec_from_file_location("results",Path(__file__).with_name("notify_paper_results.py"))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
now=datetime(2026,10,20,5,tzinfo=timezone.utc).timestamp()
iso=m.iso
base={"id":"test:ARB","coin":"ARB","side":"LONG","strategy":"TECHNICAL_MOMENTUM",
"closedAt":iso(now-45),"status":"CLOSED_TP1","netR":1.4}
assert m.recent_finished(base,now)
assert "1.400 R" in m.message(base)
assert not m.recent_finished({**base,"closedAt":iso(now-901)},now)
assert not m.recent_finished({**base,"status":"OPEN"},now)
assert not m.recent_finished({**base,"netR":None},now)
assert m.recent_finished({**base,"status":"EXPIRED"},now)
assert "Tidak ada entry" in m.message({**base,"status":"EXPIRED"})
print("V5.1 paper-result notification tests PASS")
