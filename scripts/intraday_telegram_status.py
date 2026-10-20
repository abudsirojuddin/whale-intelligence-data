"""Whale Intelligence V2 — Telegram SAFE research/status notifier.

No trading instructions or historic-entry suggestions are ever transmitted.
The default CLI mode is preview only. Actual delivery requires explicit
--send-test AND confirmation env, or --send-status AND confirmation env;
neither is scheduled or enabled by the development workflow.
"""
from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
WIB = ZoneInfo("Asia/Jakarta")
MAX_STATUS_AGE_HOURS = 6

def read(name):
    try:
        v=json.loads((ROOT / name).read_text(encoding="utf-8"))
        return v if isinstance(v, dict) else {}
    except (FileNotFoundError, ValueError):
        return {}

def utc_time(value):
    if not isinstance(value,str):return None
    try:
        moment=datetime.fromisoformat(value.replace("Z","+00:00"))
        return moment.astimezone(timezone.utc) if moment.tzinfo else None
    except (ValueError, OverflowError):return None

def fresh(d, key, now=None):
    now=now or datetime.now(timezone.utc)
    check=utc_time(d.get(key))
    return bool(check and 0<=(now-check).total_seconds()<=MAX_STATUS_AGE_HOURS*3600)

def safe_text(value, limit=80):
    """Strip control characters; never trust external JSON as Telegram markup."""
    return "".join(c for c in str(value) if c.isprintable() and c not in "\r\n")[:limit]

def compose_research_status(research=None, data_quality=None, scan=None, now=None):
    now=now or datetime.now(timezone.utc)
    research=research or {}
    data_quality=data_quality or {}
    scan=scan or {}
    lines=[
        "🐋 WHALE INTELLIGENCE V2 — LAPORAN RISET",
        "🔴 STATUS: NO TRADE — BUKAN SINYAL EKSEKUSI",
        f"Waktu laporan: {now.astimezone(WIB):%d/%m/%Y %H:%M} WIB",
        "",
    ]
    if fresh(scan,"updatedAt",now):
        lines.append("Scanner Binance: "+safe_text(scan.get("status","UNKNOWN")))
        lines.append("Kandidat dianalisis: "+str(max(0,int(scan.get("candidatesAnalyzed",0)))))
        if scan.get("status")=="DATA_UNAVAILABLE":
            lines.append("Data Futures terkini tidak dapat diverifikasi.")
    else:
        lines.append("Scanner Binance: TIDAK ADA DATA TERBARU / BELUM AKTIF.")
    if fresh(data_quality,"generatedAt",now):
        verified=data_quality.get("status")=="RESEARCH_DATA_READY"
        lines.append("Kualitas candle 15m/1h/4h: "+
                     ("RIWAYAT TEKNIKAL TERSEDIA, BUKAN SINYAL" if verified
                      else "BELUM LENGKAP / NO TRADE"))
    else:
        lines.append("Kualitas candle: DATA TERBARU BELUM TERSEDIA.")
    if fresh(research,"generatedAt",now):
        total=research.get("summary",{}).get("totalObservedPatterns")
        if type(total) is int and 0<=total<=100000:
            lines.append(f"Penelitian historis (bukan live): {total} pola teramati.")
        lines.append("Hasil historis tidak membuktikan profitabilitas.")
    else:
        lines.append("Penelitian historis: laporan terbaru belum tersedia.")
    lines += ["","⚠️ Tidak ada rekomendasi LONG/SHORT, entry, SL atau TP.",
             "Data live, OI, funding, dan paper trading belum tervalidasi.",
             "Jangan gunakan pesan ini untuk membuka posisi Futures."]
    return "\n".join(lines)

def compose_test(now=None):
    now=now or datetime.now(timezone.utc)
    return ("\N{TEST TUBE} WHALE INTELLIGENCE V2 — TES TELEGRAM\n"
            f"Waktu: {now.astimezone(WIB):%d/%m/%Y %H:%M} WIB\n"
            "✅ Ini hanya tes pengiriman pesan, bukan sinyal trading.\n"
            "⚠️ Sistem Intraday masih dalam penelitian; tidak ada entry LONG/SHORT.")

def send(text):
    token=os.environ.get("TELEGRAM_BOT_TOKEN","").strip()
    chat=os.environ.get("TELEGRAM_CHAT_ID","").strip()
    if not(token and chat and ":" in token and "/" not in token and
           "\n" not in token and chat.lstrip("-").isdigit()):
        print("STATUS: TELEGRAM_CONFIGURATION_MISSING_OR_INVALID")
        return False
    payload=json.dumps({"chat_id":chat,"text":text[:3900],
                        "disable_web_page_preview":True}).encode("utf-8")
    req=urllib.request.Request(
        "https://api.telegram.org/bot"+token+"/sendMessage",
        data=payload,headers={"Content-Type":"application/json"},
        method="POST")
    try:
        with urllib.request.urlopen(req,timeout=18) as resp:
            result=json.loads(resp.read(50000))
        return result.get("ok") is True
    except urllib.error.HTTPError as exc:
        print("STATUS: TELEGRAM_HTTP_"+str(exc.code))
        return False
    except (urllib.error.URLError,TimeoutError,ValueError,OSError):
        print("STATUS: TELEGRAM_DELIVERY_FAILED")
        return False

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--mode",choices=("preview","test","status"),default="preview")
    args=p.parse_args()
    if args.mode=="test":
        content=compose_test()
    else:
        content=compose_research_status(
            read("intraday_multi_asset_research.json"),
            read("binance_dataset_readiness.json"),
            read("intraday_scan.json"))
    if args.mode=="preview":
        print(content)
        print("\n[DRY RUN — tidak ada pesan yang dikirim]")
        return 0
    if os.environ.get("CONFIRM_INTRADAY_TELEGRAM_SEND")!="YES":
        print("BLOCKED: CONFIRM_INTRADAY_TELEGRAM_SEND=YES must be explicitly set.")
        return 2
    ok=send(content)
    print("Telegram test/status message API accepted." if ok
          else "Telegram message NOT confirmed.")
    return 0 if ok else 1

if __name__=="__main__":
    raise SystemExit(main())
