import importlib.util,io,csv,zipfile
from pathlib import Path
from datetime import date,datetime,timezone
s=importlib.util.spec_from_file_location("h",Path(__file__).with_name("binance_history_collector.py"))
m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
day=date(2026,10,15)
start=int(datetime(2026,10,15,tzinfo=timezone.utc).timestamp()*1000)
for interval,width in m.INTERVAL_MS.items():
    buf=io.BytesIO()
    filename=f"BTCUSDT-{interval}-{day}.csv"
    with zipfile.ZipFile(buf,"w",compression=zipfile.ZIP_DEFLATED) as z:
        rows=[]
        for i in range(86400000//width):
            ts=start+i*width
            rows.append([str(ts),"100","102","99","101","123",str(ts+width-1)])
        z.writestr(filename,"\n".join(",".join(row) for row in rows))
    parsed=m.parse_zip(buf.getvalue(),"BTCUSDT",interval,day)
    assert len(parsed)==86400000//width
    assert parsed[0]["start"]==start
    assert parsed[-1]["end"]==start+86400000-1
    with zipfile.ZipFile(io.BytesIO(buf.getvalue()),"r") as z:
        first=z.read(filename).decode().splitlines()
    first.pop(1)
    bad=io.BytesIO()
    with zipfile.ZipFile(bad,"w") as z:
        z.writestr(filename,"\n".join(first))
    try:m.parse_zip(bad.getvalue(),"BTCUSDT",interval,day)
    except ValueError:pass
    else:raise AssertionError("missing candle did not fail")
print("Binance archive offline parser tests passed")
