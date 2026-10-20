"""Aggregate delayed Binance USD-M closed-candle strategy diagnostics.

For research only: no live OI, funding, order book/spread data in these
historical simulations. Outputs do not authorize trading or Telegram signals.
"""
from __future__ import annotations
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from intraday_historical_diagnostic import evaluate, performance

ROOT=Path(__file__).resolve().parent.parent
ALLOWED_SYMBOLS=("BTCUSDT","ETHUSDT","SOLUSDT")
MIN_SAMPLES_PER_STRATEGY=100

def _as_number(value):
    try:
        val=float(value)
        return val if math.isfinite(val) else None
    except (ValueError,TypeError,OverflowError):
        return None

def check_archives(data,symbols):
    if (not isinstance(data,dict) or
        data.get("source")!="OFFICIAL_BINANCE_USDM_DELAYED_ARCHIVE" or
        data.get("liveTradeReady") is not False or
        data.get("errors") or not isinstance(data.get("datasets"),dict)):
        return False,"UNVERIFIED_OR_PARTIAL_ARCHIVE"
    for symbol in symbols:
        for timeframe in ("15m","1h","4h"):
            item=data["datasets"].get(symbol+":"+timeframe)
            if (not isinstance(item,dict) or item.get("contiguous") is not True
                    or not isinstance(item.get("candles"),list)
                    or item.get("count",0) < len(item["candles"])
                    or len(item["candles"])<70):
                return False,"ARCHIVE_INSUFFICIENT_"+symbol+":"+timeframe
    return True,None

def aggregate(data,symbols=ALLOWED_SYMBOLS):
    valid,issue=check_archives(data,symbols)
    report={"generatedAt":datetime.now(timezone.utc).isoformat(),
            "source":"OFFICIAL_BINANCE_USDM_DELAYED_ARCHIVE",
            "evaluationMode":"RETROSPECTIVE_TECHNICAL_ONLY",
            "tradeReady":False,"telegramSignalAllowed":False,
            "symbolReports":{},"summary":{},"qualityStatus":"NO_TRADE",
            "blockingReasons":[],
            "limitations":[
                "This is retrospective, not prospective out-of-sample trading.",
                "Funding, Open Interest and historic executable bid/ask are unavailable.",
                "Fills are hypothetical, with assumed costs; real Binance fills differ.",
                "Risk and outcomes across correlated coins cannot be added as portfolio returns.",
                "Scores and results are not probabilities of a winning trade."
            ]}
    if not valid:
        report["blockingReasons"].append(issue)
        return report
    events=[]
    for symbol in symbols:
        report["symbolReports"][symbol]=evaluate(data,symbol)
        result=report["symbolReports"][symbol]
        if result.get("status")!="HISTORICAL_TECHNICAL_ONLY":
            report["blockingReasons"].append("STRATEGY_EVALUATION_FAILED_"+symbol)
        for row in result.get("examples",[]):
            # Examples are ONLY the last few rows, and MUST NOT be used for
            # aggregate metrics. The detailed events were intentionally not
            # exported by the historical evaluator.
            if not isinstance(row,dict):
                report["blockingReasons"].append("INVALID_EXAMPLE")
    for strategy in ("TREND_PULLBACK","BREAKOUT_RETEST"):
        samples=sum(r.get("byPattern",{}).get(strategy,{}).get("closed",0)
                    for r in report["symbolReports"].values())
        report["summary"][strategy]={
            "observedExamplesAcrossSymbols":samples,
            "preliminarySampleThreshold":MIN_SAMPLES_PER_STRATEGY,
            "hasEnoughExamples":samples>=MIN_SAMPLES_PER_STRATEGY,
            "tradeReady":False}
        if samples < MIN_SAMPLES_PER_STRATEGY:
            report["blockingReasons"].append("INSUFFICIENT_"+strategy+"_SAMPLE")
    report["summary"]["totalObservedPatterns"]=sum(
        r.get("completedPaperPatterns",0) for r in report["symbolReports"].values())
    report["summary"]["symbolsEvaluated"]=len(report["symbolReports"])
    report["summary"]["totalNetRNotAggregated"]=True
    # Even if enough samples, full live derivatives gates and prospective
    # paper outcomes are still mandatory and unavailable.
    report["blockingReasons"].extend([
        "MISSING_DERIVATIVES_CONTEXT",
        "MISSING_PROSPECTIVE_PAPER_PERFORMANCE",
        "NO_CONTINUOUS_RECENT_BINANCE_FUTURES_CANDLES",
        "BINANCE_FUTURES_REST_HTTP_451"
    ])
    report["qualityStatus"]="HISTORICAL_RESEARCH_ONLY"
    return report

def as_markdown(result):
    lines=["# Whale Intelligence V2 — Binance Futures Historical Research",
           "","**Mode: paper-only historical technical patterns — NOT live trading signals.**",
           "",f"Generated (UTC): {result['generatedAt']}","",
           "| Coin | Observed patterns | Win rate | Mean net R | Profit factor | Holdout patterns |",
           "|---|---:|---:|---:|---:|---:|"]
    for symbol,stat in result["symbolReports"].items():
        def fmt(x):
            return "n/a" if x is None else str(x)
        hold=stat.get("chronologicalHoldout",{}).get("untouchedTimeHoldout",{})
        lines.append(f"| {symbol} | {stat.get('completedPaperPatterns',0)} | "
                     f"{fmt(stat.get('winRate'))} | {fmt(stat.get('meanNetR'))} | "
                     f"{fmt(stat.get('profitFactor'))} | {hold.get('closed',0)} |")
    lines+=["","## Why this is NOT trade-ready",""]
    for reason in result["blockingReasons"]:
        lines.append("- "+reason.replace("_"," "))
    lines+=["","## Research constraints",""]
    for warning in result["limitations"]:
        lines.append("- "+warning)
    lines+=["","Data is historical and deliberately withheld from automated trade alerts."]
    return "\n".join(lines)+"\n"

def main():
    source=ROOT/"binance_archive_history.json"
    if not source.exists():
        raise SystemExit("No validated Binance historical dataset.")
    data=json.loads(source.read_text("utf-8"))
    report=aggregate(data)
    (ROOT/"intraday_multi_asset_research.json").write_text(
        json.dumps(report,ensure_ascii=False,indent=2)+"\n","utf-8")
    (ROOT/"intraday_multi_asset_research.md").write_text(as_markdown(report),"utf-8")
    print(json.dumps({
        "qualityStatus":report["qualityStatus"],
        "tradeReady":report["tradeReady"],
        "totalPatterns":report["summary"].get("totalObservedPatterns",0),
        "byCoin":{k:{"patterns":v.get("completedPaperPatterns"),
                     "meanNetR":v.get("meanNetR"),
                     "holdoutCount":v.get("chronologicalHoldout",{}).get(
                          "untouchedTimeHoldout",{}).get("closed")} for k,v in report["symbolReports"].items()},
        "blockingReasons":report["blockingReasons"]
    },ensure_ascii=False))
    if report["qualityStatus"]!="HISTORICAL_RESEARCH_ONLY":
        raise SystemExit("No trustworthy historical research available.")

if __name__=="__main__":
    main()
