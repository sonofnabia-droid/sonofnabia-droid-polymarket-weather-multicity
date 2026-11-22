#!/usr/bin/env python3
"""Exploratory market rotation towards WU observed running-high bracket."""
import collections,csv,datetime as dt,json,re,sqlite3
from pathlib import Path
root=Path(__file__).resolve().parents[2]; base=root/'experiments/lead_lag_pilot'
db=sqlite3.connect(f'file:{root / "data/polymarket_weather_2026.sqlite"}?mode=ro',uri=True); db.execute('PRAGMA query_only=ON')
events={}
for r in csv.DictReader((base/'all_crossings_wu_through_july17.csv').open()):
    key=(r['city'],r['day'],r['obs_utc']); bound=int(re.match(r'(-?\d+)',r['bracket']).group())
    if key not in events or bound>events[key][0]: events[key]=(bound,r)
w=csv.writer(__import__('sys').stdout); w.writerow(['city','day','obs_utc','crossed_bracket','new_temp','target_bracket','target_winner_indicated','target_m10','target_0','target_10','crossed_0','quote_m10_utc','quote_10_utc','status'])
for (city,day,obs),(_,r) in sorted(events.items()):
    temp=float(r['temp']); markets=db.execute("SELECT m.bracket,m.closed,m.outcome_prices,m.raw_json,t.token_id FROM markets m JOIN tokens t ON m.market_id=t.market_id WHERE m.city=? AND m.market_date=? AND t.outcome='YES'",(city,day)).fetchall(); candidates=[]
    for name,closed,prices,raw,token in markets:
        m=re.fullmatch(r'(-?\d+)°C(?: or (below|higher))?',name or '')
        if not m or not temp.is_integer(): continue
        n=int(m.group(1)); side=m.group(2)
        if (side is None and temp==n) or (side=='below' and temp<=n) or (side=='higher' and temp>=n): candidates.append((name,closed,prices,raw,token))
    if len(candidates)!=1: w.writerow([city,day,obs,r['bracket'],temp,'','','','','',r['yes0'],'','','ambiguous_target']); continue
    name,closed,prices,raw,token=candidates[0]; win='unknown'
    try:
        obj=json.loads(raw); outcomes=obj.get('outcomes',[]); outcomes=json.loads(outcomes) if isinstance(outcomes,str) else outcomes; ix=next(i for i,x in enumerate(outcomes) if str(x).upper()=='YES'); v=float(json.loads(prices)[ix])
        if closed and v in (0,1): win=int(v)
    except (ValueError,TypeError,IndexError,StopIteration): pass
    ts=int(dt.datetime.fromisoformat(obs).timestamp()); quotes=[]
    for off in (-10,0,10):
        t=ts+off*60; quotes.append(db.execute('SELECT ts,price FROM price_points WHERE token_id=? AND fidelity_minutes=5 AND ts BETWEEN ? AND ? ORDER BY ts DESC LIMIT 1',(token,t-600,t)).fetchone())
    fmt=lambda x:dt.datetime.fromtimestamp(x[0],dt.timezone.utc).isoformat() if x else ''
    w.writerow([city,day,obs,r['bracket'],temp,name,win,*[x[1] if x else '' for x in quotes],r['yes0'],fmt(quotes[0]),fmt(quotes[2]),'descriptive' if all(quotes) else 'missing_quotes'])
db.close()
