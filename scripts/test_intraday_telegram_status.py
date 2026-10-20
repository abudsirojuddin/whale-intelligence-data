import sys
from pathlib import Path
from datetime import datetime,timezone
sys.path.insert(0,str(Path(__file__).parent))
from intraday_telegram_status import compose_research_status,compose_test, fresh
now=datetime(2026,10,20,13,0,tzinfo=timezone.utc)
s=compose_research_status(now=now)
assert "NO TRADE" in s and "LONG/SHORT" in s
assert "Entry:" not in s and "BUY" not in s
x=compose_research_status(scan={"status":"DATA_UNAVAILABLE","updatedAt":now.isoformat(),
"candidatesAnalyzed":0},now=now)
assert "DATA_UNAVAILABLE" in x and "terkini tidak" in x
assert "TES TELEGRAM" in compose_test(now)
assert not fresh({"updatedAt":"2020-01-01T00:00:00Z"},"updatedAt",now)
print("Intraday Telegram safe message tests passed")
