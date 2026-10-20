import io,sys,zipfile
from pathlib import Path
import importlib.util
from datetime import datetime,timezone
p=importlib.util.spec_from_file_location("month",Path(__file__).with_name("binance_monthly_archive.py"))
m=importlib.util.module_from_spec(p);p.loader.exec_module(m)
assert m.target_months(2,datetime(2026,1,20,tzinfo=timezone.utc))==[(2025,11),(2025,12)]
assert m.target_months(1,datetime(2026,10,20,tzinfo=timezone.utc))==[(2026,9)]
start,end=m.utc_month_bounds(2026,9)
width=m.INTERVALS["4h"]
name="BTCUSDT-4h-2026-09.csv"
rows=[]
for t in range(start,end,width):
    rows.append(f"{t},100,102,99,101,50,{t+width-1}")
buf=io.BytesIO()
with zipfile.ZipFile(buf,"w") as z:z.writestr(name,"\n".join(rows))
parsed=m.parse_month(buf.getvalue(),"BTCUSDT","4h",2026,9)
assert len(parsed)==180
assert parsed[-1]["end"]==end-1
bad=io.BytesIO()
with zipfile.ZipFile(bad,"w") as z:z.writestr(name,"\n".join(rows[:-1]))
try:m.parse_month(bad.getvalue(),"BTCUSDT","4h",2026,9)
except ValueError as e:assert "COUNT" in str(e)
else:raise AssertionError("incomplete monthly archive accepted")
print("Binance monthly offline integrity tests passed")
