"""V4.2 research overview; snapshots, no invented entry recommendations."""
import json, math, os, time, urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from selection_rules import is_qualified
from market_universe import RESEARCH_COINS

ROOT=Path(__file__).resolve().parent.parent
def read(name, default):
    p=ROOT/name
    return json.loads(p.read_text()) if p.exists() else default
def write(name,data):
    (ROOT/name).write_text(json.dumps(data,ensure_ascii=False,separators=(',',':'))+'\n')
def ts(value):
    try: return datetime.fromisoformat(str(value).replace('Z','+00:00')).timestamp()
    except (ValueError,TypeError,AttributeError): return 0
def n(x):
    try:
        v=float(x)
        return v if math.isfinite(v) else 0.0
    except (TypeError,ValueError): return 0.0
def iso(now): return datetime.fromtimestamp(now,timezone.utc).isoformat()
def api(data):
    req=urllib.request.Request('https://api.hyperliquid.xyz/info',data=json.dumps(data).encode(),
      headers={'Content-Type':'application/json','User-Agent':'WhaleIntelligenceResearch/4.2'})
    with urllib.request.urlopen(req,timeout=18) as resp: return json.loads(resp.read(3000000))
def ema(prices,p):
    result=sum(prices[:p])/p
    for v in prices[p:]: result+=(v-result)*2/(p+1)
    return result
def get_setup(coin,side,now):
    # Only the deepest core markets, to avoid thin altcoin spreads.
    if coin not in RESEARCH_COINS: return None
    meta=api({'type':'metaAndAssetCtxs'})
    if not isinstance(meta,list) or len(meta)<2:return None
    universe=meta[0].get('universe',[])
    idx=next((i for i,x in enumerate(universe) if x.get('name')==coin),None)
    if idx is None or idx>=len(meta[1]):return None
    ctx=meta[1][idx]; mark=n(ctx.get('markPx')); vol=n(ctx.get('dayNtlVlm'))
    if not mark or vol<20000000:return None
    book=api({'type':'l2Book','coin':coin}); levels=book.get('levels',[])
    if len(levels)!=2 or not levels[0] or not levels[1]: return None
    bid=n(levels[0][0].get('px')); ask=n(levels[1][0].get('px'))
    if not bid or ask<=bid: return None
    spread=10000*(ask-bid)/((bid+ask)/2)
    if spread>12 or not bid*.98<=mark<=ask*1.02: return None
    bars=[]
    for interval,millis in [('15m',900000),('1h',3600000)]:
        raw=api({'type':'candleSnapshot','req':{'coin':coin,'interval':interval,
            'startTime':int(now*1000)-75*millis,'endTime':int(now*1000)}})
        # Reject unfinished bars and stale candles
        series=sorted([{'c':n(b.get('c')),'h':n(b.get('h')),'l':n(b.get('l')),
                  'T':int(b.get('T',0))} for b in raw if int(b.get('T',0))<int(now*1000)],key=lambda b:b['T'])
        if len(series)<65 or now*1000-series[-1]['T']>millis+90000:return None
        bars.append(series[-65:])
    c15=[x['c'] for x in bars[0]]; c1h=[x['c'] for x in bars[1]]
    f15,s15=ema(c15,21),ema(c15,50);f1,s1=ema(c1h,21),ema(c1h,50)
    aligned=(c15[-1]>f15>s15 and f1>s1) if side=='LONG' else (c15[-1]<f15<s15 and f1<s1)
    if not aligned:return None
    tr=[max(bars[0][i]['h']-bars[0][i]['l'],abs(bars[0][i]['h']-bars[0][i-1]['c']),
         abs(bars[0][i]['l']-bars[0][i-1]['c'])) for i in range(1,len(bars[0]))]
    atr=sum(tr[-14:])/14
    if atr<=0 or not .0018<=atr/mark<=.027 or abs(mark-c15[-1])>.8*atr or abs(mark-f15)>1.2*atr:return None
    risk=1.2*atr
    if not .0025<=risk/mark<=.025:return None
    after_cost_rr=(2*risk-.002*mark)/(risk+.002*mark)
    if after_cost_rr<1.55:return None
    sign=1 if side=='LONG' else -1
    return {'markPrice':round(mark,6),'entryZoneLow':round(mark-.15*atr,6),
        'entryZoneHigh':round(mark+.15*atr,6),'stopLoss':round(mark-sign*risk,6),
        'takeProfit1':round(mark+sign*2*risk,6),'takeProfit2':round(mark+sign*3*risk,6),
        'estimatedNetRR':round(after_cost_rr,2),'spreadBps':round(spread,2),
        'expiresAt':iso(now+900)}
def main():
    now=time.time();state=read('position_state.json',{});ranking=read('ranking.json',{})
    scan=read('market_scan.json',{})
    scan_fresh=(0<=now-ts(scan.get('updatedAt'))<=300 and now<=ts(scan.get('expiresAt')) and scan.get('apiHealthy') is True)
    passes={m.get('coin'):m for m in scan.get('coins',[]) if m.get('status')=='TECHNICAL_PASS'} if scan_fresh else {}
    alerts=read('alerts.json',{});past=read('setups.json',{})
    quality={r['address'].lower():r for r in ranking.get('ranking',[]) if isinstance(r.get('address'),str)}
    totals=defaultdict(lambda:{'longWallets':0,'shortWallets':0,'longNotionalUsd':0,'shortNotionalUsd':0,'qualityLongWallets':0,'qualityShortWallets':0})
    consensus=defaultdict(lambda:{'LONG':set(),'SHORT':set()})
    timestamps=state.get('checkedAtByWallet',{});wallets=state.get('wallets',{})
    fresh=0;eligible_count=0
    for addr,positions in wallets.items():
        if not isinstance(positions,dict):continue
        if not 0<=now-ts(timestamps.get(addr) or state.get('lastRun'))<=1800:continue
        fresh+=1;rank=quality.get(addr.lower(),{})
        eligible=is_qualified(rank,now)
        if eligible:eligible_count+=1
        for coin,pos in positions.items():
            side=pos.get('side');notional=n(pos.get('notional'))
            if side not in ('LONG','SHORT') or notional<=0:continue
            key=side.lower();totals[coin][key+'Wallets']+=1;totals[coin][key+'NotionalUsd']+=notional
            if eligible and notional>=50000:
                totals[coin]['quality'+side.title()+'Wallets']+=1;consensus[coin][side].add(addr.lower())
    coins=[dict(coin=c,**{k:round(v,2) if isinstance(v,float) else v for k,v in d.items()})
           for c,d in totals.items()]
    coins.sort(key=lambda x:x['longNotionalUsd']+x['shortNotionalUsd'],reverse=True)
    stale=not (0<=now-ts(state.get('lastRun'))<=1800)
    overview={'updatedAt':iso(now),'positionsLastCheckedAt':state.get('lastRun'),'stale':stale,
       'monitoredWallets':len(wallets),'freshWallets':fresh,'eligibleQualityWallets':eligible_count,
       'coins':coins[:40],'disclaimer':'Only selected public wallets; does not measure global market positioning.'}
    setups=[];events=alerts.get('events',[])
    if not stale:
        for coin,sides in consensus.items():
            if coin not in RESEARCH_COINS:continue
            for side in ('LONG','SHORT'):
                cohort=sides[side]
                if len(cohort)<2 or len(cohort)/max(1,len(sides['LONG']|sides['SHORT']))<.7:continue
                recent=any(e.get('coin')==coin and e.get('side')==side and
                  e.get('event') in ('OPEN','INCREASE','REVERSE') and e.get('address','').lower() in cohort
                  and 0<=now-ts(e.get('time'))<=1200 for e in events)
                if not recent:continue
                # Only accept a fresh, complete multi-coin scan; do not fall back
                # to ad-hoc unverified prices or stale cached levels.
                levels=passes.get(coin,{}).get('paperScenarios',{}).get(side)
                if levels and 0 < ts(levels.get('expiresAt'))-now <= 900:
                    setups.append(dict(coin=coin,direction=side,qualifiedWallets=len(cohort),
                        status='CONDITIONAL_RESEARCH_ONLY',**levels))
    notified=past.get('notified',{});notified={k:v for k,v in notified.items() if 0<=now-ts(v)<=172800}
    # Telegram alerts are disabled for proposals until paper-trade evaluation.
    # This prevents a backtested-looking setup being misrepresented as a recommendation.
    result={'updatedAt':iso(now),'status':'SETUPS_AVAILABLE' if setups else 'NO_TRADE',
        'setups':setups[:5],'notified':notified,'maxRiskPerIdeaIdr':5000,
        'disclaimer':'Research scenarios only, using fresh multi-coin technical scan. No trade recommendation until paper-trading validation.'}
    write('market_overview.json',overview);write('setups.json',result)
    print('Assets',len(coins),'eligibleWallets',eligible_count,'paperSetups',len(setups))
if __name__=='__main__':main()
