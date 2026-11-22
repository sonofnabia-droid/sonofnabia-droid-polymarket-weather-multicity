#!/usr/bin/env python3
"""Exploratory native-METAR context for existing PAPER decisions.

Uses only raw historical METAR rows and indexed read-only SQLite queries.
Observation time is not publication/availability time; Gamma labels are
archived indicators, and price_points are not executable asks.
"""
import csv, datetime as dt, json, math, re, sqlite3
from pathlib import Path
from zoneinfo import ZoneInfo

BASE=Path(__file__).resolve().parent
ROOT=BASE.parents[1]
papers={}
for name in ('paper_market_context.csv','paper_filter_study.csv'):
    papers[name]={ (r['bot'],r['city'],r['day']):r
        for r in csv.DictReader((BASE/name).open(newline='')) }

weather={}
for city in ('lucknow','munich'):
    records=[]
    with (ROOT/'historic_metar'/f'{city}.csv').open(newline='') as f:
        for row in csv.DictReader(f):
            try:
                stamp=dt.datetime.fromisoformat(row['timestamp_utc'].replace('Z','+00:00'))
                if stamp.tzinfo is None: stamp=stamp.replace(tzinfo=dt.timezone.utc)
                temp=float(row['temp_c'])
                records.append((stamp.astimezone(dt.timezone.utc),temp))
            except (ValueError,TypeError): pass
    weather[city]=records

db=sqlite3.connect(f'file:{ROOT / "data/polymarket_weather_2026.sqlite"}?mode=ro',uri=True)
db.execute('PRAGMA query_only=ON')
pat=re.compile(r'(-?\d+)°C(?: or (below|higher))?')
def contains(label,value):
    m=pat.fullmatch(label or '')
    if not m:return False
    n=int(m.group(1)); edge=m.group(2)
    return value<=n if edge=='below' else value>=n if edge=='higher' else value==n

out=csv.writer(__import__('sys').stdout)
out.writerow(['bot','city','day','decision_utc','paper_target','paper_result','paper_target_pricepoint',
 'metar_native_rows','metar_last_obs_utc','metar_max_c','metar_max_rounded_c','metar_bracket',
 'metar_quote','metar_quote_utc','quote_age_sec','gamma_winner_bracket','metar_gamma_winner','metar_gross_proxy',
 'market_ladder_complete','market_quote_span_sec','market_quote_age_max_sec','market_ladder_sync_60s',
 'market_leader','leader_price','leader_gamma_winner','target_is_metar',
 'target_is_leader','label_basis','limitations'])

seen=set()
for key,paper in papers['paper_market_context.csv'].items():
    bot,city,day=key
    if key in seen:continue
    seen.add(key)
    try:
        decision=dt.datetime.fromisoformat(paper['decision_utc'].replace('Z','+00:00')).astimezone(dt.timezone.utc)
    except (ValueError,TypeError):continue
    event=db.execute('SELECT timezone FROM events WHERE city=? AND market_date=? AND status="found" LIMIT 1',(city,day)).fetchone()
    zone=ZoneInfo(event[0]) if event and event[0] else ZoneInfo('Asia/Kolkata' if city=='lucknow' else 'Europe/Berlin')
    local_day=dt.date.fromisoformat(day)
    obs=[(ts,t) for ts,t in weather[city] if ts.astimezone(zone).date()==local_day and ts<=decision]
    if obs:
        peak=max(t for _,t in obs); rounded=math.floor(peak+0.5)
        last=max(ts for ts,_ in obs)
    else: peak=rounded=last=None
    markets=db.execute('''SELECT m.bracket,m.closed,m.outcome_prices,m.raw_json,t.token_id
       FROM markets m JOIN tokens t ON t.market_id=m.market_id
       WHERE m.city=? AND m.market_date=? AND t.outcome='YES' ''',(city,day)).fetchall()
    candidate=next((r[0] for r in markets if contains(r[0],rounded)), '') if rounded is not None else ''
    quotes=[]; winners=[]
    for bracket,closed,prices,raw,token in markets:
        try:
            meta=json.loads(raw); outcomes=meta.get('outcomes',[])
            outcomes=json.loads(outcomes) if isinstance(outcomes,str) else outcomes
            vals=json.loads(prices or '[]'); yi=next(i for i,x in enumerate(outcomes) if str(x).upper()=='YES')
            if closed and float(vals[yi])>=.999: winners.append(bracket)
        except (ValueError,TypeError,KeyError,IndexError,StopIteration):pass
        q=db.execute('SELECT ts,price FROM price_points WHERE token_id=? AND fidelity_minutes=5 AND ts BETWEEN ? AND ? ORDER BY ts DESC LIMIT 1',
            (token,int(decision.timestamp())-600,int(decision.timestamp()))).fetchone()
        if q: quotes.append((bracket,int(q[0]),float(q[1])))
    ladder=len(markets)>0 and len(quotes)==len(markets)
    leader=max(quotes,key=lambda x:x[2]) if ladder and quotes else None
    cq=next((x for x in quotes if x[0]==candidate),None)
    gamma_winner=winners[0] if len(winners)==1 else ''
    pf=papers['paper_filter_study.csv'].get(key,{})
    result=pf.get('result_for_research') or pf.get('ledger_status','')
    out.writerow([bot,city,day,decision.isoformat(),paper.get('target_bracket',''),result,
        paper.get('target_history_price',''),len(obs),last.isoformat() if last else '',peak if peak is not None else '',
        rounded if rounded is not None else '',candidate,cq[2] if cq else '',
        dt.datetime.fromtimestamp(cq[1],dt.timezone.utc).isoformat() if cq else '',
        int(decision.timestamp())-cq[1] if cq else '',gamma_winner,candidate==gamma_winner if candidate and gamma_winner else '',
        (int(candidate==gamma_winner)-cq[2]) if candidate and gamma_winner and cq else '',
        ladder,(max((x[1] for x in quotes),default=0)-min((x[1] for x in quotes),default=0)) if quotes else '',
        max((int(decision.timestamp())-x[1] for x in quotes),default=''),
        bool(ladder and max(x[1] for x in quotes)-min(x[1] for x in quotes)<=60),
        leader[0] if leader else '',leader[2] if leader else '',
        leader[0]==gamma_winner if leader and gamma_winner else '',candidate==paper.get('target_bracket','') if candidate else '',
        paper.get('target_is_leader',''),gamma_winner,'Gamma closed metadata; not independent settlement',
        'native METAR observation time != publication/availability; price_points != ask/fill; PAPER labels previously exposed'])
db.close()
