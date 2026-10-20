"""V4.9 rolling top-five research watchlist.

This board always ranks up to five *observations* from the 10-asset scanner.
It NEVER fabricates five executable trade signals or stop/entry levels.
"""
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
REASONS={
  "LOW_24H_VOLUME":"Volume 24 jam belum memenuhi batas",
  "TREND_NOT_ALIGNED":"Tren 15 menit dan 1 jam belum selaras",
  "RISK_REWARD_TOO_LOW":"Rasio risiko/hasil setelah biaya belum cukup",
  "PRICE_TOO_FAR_FROM_TREND":"Harga terlalu jauh dari tren",
  "VOLATILITY_OUT_OF_RANGE":"Volatilitas di luar rentang",
  "SPREAD_TOO_WIDE":"Spread terlalu lebar",
  "TECHNICAL_VALIDATION_REQUIRED":"Konfirmasi teknikal belum selesai",
  "ASSET_OR_META_UNAVAILABLE":"Data pasar belum tersedia",
  "EXCHANGE_API_UNAVAILABLE":"API bursa tidak tersedia",
  "STALE_CANDLES":"Data candle terlambat",
  "INSUFFICIENT_CANDLES":"Riwayat candle belum memadai",
}
def num(value):
    try:
        v=float(value)
        return v if math.isfinite(v) and v>=0 else 0.0
    except (TypeError,ValueError,OverflowError): return 0.0
def when(s):
    try:return datetime.fromisoformat(str(s).replace("Z","+00:00")).timestamp()
    except (TypeError,ValueError,OverflowError):return 0.0
def iso(t):return datetime.fromtimestamp(t,timezone.utc).isoformat()
def load(name,default):
    path=ROOT/name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default
def make(scan,overview,technical,whales,now):
    updated=when(scan.get("updatedAt"))
    source_healthy=scan.get("apiHealthy") is True and 0<=now-updated<=20*60
    totals={str(r.get("coin")):r for r in overview.get("coins",[]) if isinstance(r,dict)}
    proposals={}
    for strategy,doc in (("TECHNICAL_MOMENTUM",technical),("WHALE_CONSENSUS",whales)):
        for s in doc.get("setups",[]):
            if not isinstance(s,dict):continue
            if (doc.get("status")!="SETUPS_AVAILABLE" or now>=when(s.get("expiresAt"))
                  or now<when(doc.get("updatedAt")) or now-when(doc.get("updatedAt"))>5*60):
                continue
            proposals[(str(s.get("coin")),str(s.get("direction")),strategy)]=s
    rows=[]
    for m in scan.get("coins",[]):
        if not isinstance(m,dict): continue
        coin=str(m.get("coin",""))[:15]
        if not coin:continue
        status=str(m.get("status","UNAVAILABLE"))
        direction=m.get("trend",{}).get("direction","MIXED") if isinstance(m.get("trend"),dict) else "MIXED"
        if direction not in ("LONG","SHORT"):direction="MIXED"
        volume=num(m.get("liquidity",{}).get("volume24hUsd"))
        spread=m.get("liquidity",{}).get("spreadBps")
        quality=totals.get(coin,{})
        long=int(num(quality.get("qualityLongWallets")))
        short=int(num(quality.get("qualityShortWallets")))
        aligned=(long if direction=="LONG" else short) if direction!="MIXED" else 0
        opposite=(short if direction=="LONG" else long) if direction!="MIXED" else 0
        technical_pass=status=="TECHNICAL_PASS"
        # Only ranking; no invented success probability or artificial signal quota.
        rank=(100 if technical_pass else 0)+(28 if direction!="MIXED" else 0)
        rank+=min(20,5*math.log10(max(1,volume)/1e6)) if volume>1e6 else 0
        rank+=min(20,aligned*10)-min(10,opposite*5)
        if spread is not None and num(spread)>0:
            rank+=max(0,12-min(num(spread),12))
        setup=None
        strat=None
        if source_healthy:
            for candidate in ("WHALE_CONSENSUS","TECHNICAL_MOMENTUM"):
                possible=proposals.get((coin,direction,candidate))
                if possible and technical_pass and now<when(possible.get("expiresAt")):
                    setup=possible;strat=candidate;break
        if setup:
            level={k:setup.get(k) for k in (
                "entryZoneLow","entryZoneHigh","stopLoss","takeProfit1","takeProfit2","expiresAt")}
            tier="PAPER_ONLY"
        else:level=None;tier="WATCH_ONLY" if source_healthy else "DATA_STALE"
        reasons=[REASONS.get(x,str(x).replace("_"," ").title()) for x in m.get("reasons",[])][:3]
        if not reasons and tier=="WATCH_ONLY":
            reasons=["Setup tidak lolos validasi terbaru"]
        if tier=="DATA_STALE":reasons=["Data perlu diperbarui; bukan kondisi pasar langsung"]
        rows.append({
            "coin":coin,"direction":direction,"tier":tier,"strategy":strat,
            "technicalPass":technical_pass,"rankScore":round(rank,2),
            "markPrice":num(m.get("markPrice")) or None,
            "volume24hUsd":round(volume,2),
            "spreadBps":spread,"qualityWhalesSameSide":aligned,
            "qualityWhalesOppositeSide":opposite,
            "reasons":reasons,"paperLevels":level
        })
    rows.sort(key=lambda r:(r["tier"]=="PAPER_ONLY",r["rankScore"],r["volume24hUsd"]),reverse=True)
    result={
      "version":"4.9","updatedAt":iso(now),"marketScanAt":scan.get("updatedAt"),
      "watchlistFresh":source_healthy,
      "expiresAt":iso(min(now+20*60,updated+20*60)) if source_healthy else None,
      "targetWatchCount":5,"actualWatchCount":min(len(rows),5),
      "paperOnlyCount":sum(x["tier"]=="PAPER_ONLY" for x in rows[:5]),
      "readyForLiveExecutionCount":0,
      "topFive":rows[:5],"allMarkets":rows,
      "message":"Lima kandidat teratas bukan lima sinyal siap eksekusi. Skenario belum terbukti menguntungkan.",
      "disclaimer":"Bukan instruksi jual-beli. Harga Hyperliquid dapat berbeda dari Binance; review risiko sendiri."
    }
    return result
def main():
    now=time.time()
    output=make(load("market_scan.json",{}),load("market_overview.json",{}),
                load("technical_setups.json",{}),load("setups.json",{}),now)
    (ROOT/"signal_board.json").write_text(
        json.dumps(output,ensure_ascii=False,separators=(",",":"))+"\n",encoding="utf-8")
    print("Signal watchlist:",output["actualWatchCount"],"paper research:",output["paperOnlyCount"],
          "source fresh:",output["watchlistFresh"])
if __name__=="__main__":main()
