"""V5 paper-only Telegram notifications for newly registered forward research setups.
Never creates market orders, and never labels a historical simulation as execution-ready.
"""
import json,os,time,urllib.request,urllib.error
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent

def read(name,default):
    p=ROOT/name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default

def stamp(x):
    try:return datetime.fromisoformat(str(x).replace("Z","+00:00")).timestamp()
    except (ValueError,TypeError,OverflowError):return 0

def iso(t):return datetime.fromtimestamp(t,timezone.utc).isoformat()

def send(message):
    token=os.getenv("TELEGRAM_BOT_TOKEN","").strip()
    chat=os.getenv("TELEGRAM_CHAT_ID","").strip()
    if not(token and chat):print("Telegram not configured");return False
    if "/" in token or "\n" in token or ":" not in token or not chat.lstrip("-").isdigit():
        print("Invalid Telegram configuration");return False
    payload=json.dumps({"chat_id":chat,"text":message[:3900],"disable_web_page_preview":True}).encode()
    req=urllib.request.Request("https://api.telegram.org/bot"+token+"/sendMessage",
        data=payload,headers={"Content-Type":"application/json"},method="POST")
    try:
        with urllib.request.urlopen(req,timeout=15) as resp:
            return json.loads(resp.read(50000)).get("ok") is True
    except (urllib.error.URLError,TimeoutError,ValueError) as exc:
        print("Telegram send unsuccessful:",type(exc).__name__);return False

def eligible(trade,now):
    return (trade.get("status") in ("WAITING_ENTRY","OPEN")
        and trade.get("strategy") in ("TECHNICAL_MOMENTUM","WHALE_CONSENSUS")
        and trade.get("side") in ("LONG","SHORT")
        and 0<=now-stamp(trade.get("firstSeenAt"))<=180
        and now<stamp(trade.get("expiresAt"))
        and all(isinstance(trade.get(k),(int,float)) and trade[k]>0
                for k in ("entryZoneLow","entryZoneHigh","stopLoss","takeProfit"))
        and (trade["stopLoss"]<trade["entryZoneLow"]<trade["entryZoneHigh"]<trade["takeProfit"]
             if trade["side"]=="LONG" else
             trade["takeProfit"]<trade["entryZoneLow"]<trade["entryZoneHigh"]<trade["stopLoss"]))

def format_message(t):
    strategy="Teknikal Momentum" if t["strategy"]=="TECHNICAL_MOMENTUM" else "Konsensus Whale"
    return ("🟠 WHALE INTELLIGENCE — PAPER ONLY\n"
        "⚠️ SIMULASI / BUKAN SINYAL EKSEKUSI\n\n"
        f"Aset: {t['coin']} | {t['side']}\n"
        f"Strategi: {strategy}\n"
        f"Area entry simulasi (Hyperliquid): {t['entryZoneLow']} – {t['entryZoneHigh']}\n"
        f"Stop-loss simulasi: {t['stopLoss']}\n"
        f"Take-profit simulasi: {t['takeProfit']}\n"
        f"Whale berkualitas searah: {t.get('walletConsensus',0)}\n"
        f"Berlaku sampai UTC: {t['expiresAt']}\n"
        "Jurnal hanya menghitung candle masa depan dan asumsi biaya/slippage.\n"
        "Harga Binance dapat berbeda. Jangan mengeksekusi berdasarkan pesan simulasi.")

def main():
    now=time.time()
    journal=read("paper_trades.json",{"trades":[]})
    state=read("paper_notification_state.json",{"sent":{}})
    sent=state.get("sent",{})
    sent={k:v for k,v in sent.items() if 0<=now-stamp(v)<=14*86400}
    ok=0
    for t in journal.get("trades",[]):
        identity=t.get("id","")
        if not identity or identity in sent or not eligible(t,now):continue
        if send(format_message(t)):
            sent[identity]=iso(now)
            ok+=1
    (ROOT/"paper_notification_state.json").write_text(json.dumps({
        "updatedAt":iso(now),"sent":sent,
        "disclaimer":"Messages are hypothetical research setups, never execution signals."
    },ensure_ascii=False,separators=(",",":"))+"\n",encoding="utf-8")
    print("Paper-only Telegram notifications sent:",ok)

if __name__=="__main__":main()
