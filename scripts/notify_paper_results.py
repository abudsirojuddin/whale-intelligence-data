"""Send recent completed PAPER-trading results to Telegram (never real executions).
Deduplicated by ledger ID and final status. Missing or stale data is NOT a win.
"""
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from notify_paper_setups import read, send, stamp, iso

ROOT = Path(__file__).resolve().parent.parent
TERMINAL = {"CLOSED_TP1": "TARGET TERKENA",
            "CLOSED_STOP": "STOP-LOSS TERKENA",
            "CLOSED_TIME": "DITUTUP OLEH BATAS WAKTU",
            "EXPIRED": "ENTRY TIDAK TERSENTUH"}
WINDOW_SECONDS = 900  # 15m: no retroactive alerts for old trades
KEEP_SECONDS = 14 * 86400

def recent_finished(row, now):
    if not isinstance(row,dict) or row.get("status") not in TERMINAL:
        return False
    if not row.get("id") or row.get("strategy") not in ("TECHNICAL_MOMENTUM","WHALE_CONSENSUS"):
        return False
    elapsed = now - stamp(row.get("closedAt"))
    if not 0 <= elapsed <= WINDOW_SECONDS:
        return False
    if row.get("status") != "EXPIRED":
        v = row.get("netR")
        if not isinstance(v,(float,int)) or isinstance(v,bool) or not math.isfinite(v):
            return False
    return True

def message(row):
    result = TERMINAL[row["status"]]
    strategy = ("Technical Momentum" if row["strategy"] == "TECHNICAL_MOMENTUM"
                else "Whale Consensus")
    closed = datetime.fromtimestamp(stamp(row["closedAt"]), ZoneInfo("Asia/Jakarta"))
    lines = [
        "📊 WHALE INTELLIGENCE — HASIL SIMULASI",
        "⚠️ PAPER TRADING, BUKAN TRANSAKSI NYATA",
        f"{row['coin']} | {row['side']} | {strategy}",
        f"Status: {result}",
        f"Waktu simulasi: {closed:%d/%m/%Y %H:%M} WIB",
    ]
    if row["status"] == "EXPIRED":
        lines.append("Tidak ada entry simulasi, tidak dihitung sebagai menang/kalah.")
    else:
        lines += [
            f"Hasil bersih simulasi: {row['netR']:+.3f} R",
            "R = hasil relatif terhadap jarak entry simulasi ke stop-loss.",
            "Sudah memakai asumsi biaya dan slippage, belum termasuk funding, pajak,",
            "margin, likuidasi atau perbedaan harga Binance.",
        ]
    lines.append("Evaluasi prospektif hipotetis; bukan bukti profit trading langsung.")
    return "\n".join(lines)

def run(now=None, do_send=send):
    now = time.time() if now is None else now
    ledger = read("paper_trades.json", {"trades":[]})
    previous = read("paper_result_state.json", {"sent":{}})
    sent = {k:v for k,v in previous.get("sent",{}).items()
            if isinstance(k,str) and 0 <= now - stamp(v) < KEEP_SECONDS}
    count = 0
    for trade in ledger.get("trades",[]):
        if not recent_finished(trade,now):
            continue
        key = str(trade["id"]) + ":" + trade["status"]
        if key in sent:continue
        if do_send(message(trade)):
            sent[key] = iso(now)
            count += 1
    state = {
        "updatedAt":iso(now), "sent":sent,
        "notes":"Paper results only; Telegram failures are retried within 15 minutes."
    }
    (ROOT/"paper_result_state.json").write_text(
        json.dumps(state, ensure_ascii=False,separators=(",",":"))+"\n",encoding="utf-8")
    print("Recent paper result alerts delivered:",count)
    return count

if __name__ == "__main__":
    run()
