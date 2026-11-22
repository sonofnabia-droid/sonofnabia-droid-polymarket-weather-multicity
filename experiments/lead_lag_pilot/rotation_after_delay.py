#!/usr/bin/env python3
"""One first WU high/day, candidate vs leader at hypothetical +15 min."""
import csv,datetime as dt,json,sqlite3
from pathlib import Path
from zoneinfo import ZoneInfo
root=Path(__file__).resolve().parents[2]; base=root/'experiments/lead_lag_pilot'; db=sqlite3.connect(f'file:{root / "data/polymarket_weather_2026.sqlite"}?mode=ro',uri=True); db.execute('PRAGMA query_only=ON')
first={}
for r in csv.DictReader((base/'crossing_rotation.csv').open()):
    tz=ZoneInfo('Asia/Kolkata' if r['city']=='lucknow' else 'Europe/Berlin')
    if dt.datetime.fromisoformat(r['obs_utc']).astimezone(tz).hour>=12: first.setdefault((r['city'],r['day']),r)
w=csv.writer(__import__('sys').stdout); w.writerow(['city','day','obs_utc','status','target','target_price','target_won','leader','leader_price','leader_won','same','oldest_quote_age_sec'])
for (city,day),r in sorted(first.items()):
    markets=db.execute("SELECT m.bracket,m.closed,m.outcome_prices,m.raw_json,t.token_id FROM markets m JOIN tokens t ON m.market_id=t.market_id WHERE m.city=? AND m.market_date=? AND t.outcome='YES'",(city,day)).fetchall(); at=int(dt.datetime.fromisoformat(r['obs_utc']).timestamp())+900; quotes=[]; winner=[]
    for name,closed,prices,raw,token in markets:
        q=db.execute('SELECT ts,price FROM price_points WHERE token_id=? AND fidelity_minutes=5 AND ts BETWEEN ? AND ? ORDER BY ts DESC LIMIT 1',(token,at-600,at)).fetchone()
        if q: quotes.append((float(q[1]),name,q[0]))
        try:
            obj=json.loads(raw); outcomes=obj.get('outcomes',[]); outcomes=json.loads(outcomes) if isinstance(outcomes,str) else outcomes; idx=next(i for i,x in enumerate(outcomes) if str(x).upper()=='YES')
            if closed and float(json.loads(prices)[idx])>=.999: winner.append(name)
        except (ValueError,TypeError,IndexError,StopIteration): pass
    if not markets or len(quotes)!=len(markets) or len(winner)!=1 or sum(x[0]==max(q[0] for q in quotes) for x in quotes)!=1 or not r['target_bracket']:
        w.writerow([city,day,r['obs_utc'],'incomplete']); continue
    target=next((x for x in quotes if x[1]==r['target_bracket']),None)
    if target is None: w.writerow([city,day,r['obs_utc'],'missing_target']); continue
    leader=max(quotes); w.writerow([city,day,r['obs_utc'],'descriptive',target[1],target[0],int(target[1]==winner[0]),leader[1],leader[0],int(leader[1]==winner[0]),target[1]==leader[1],max(at-x[2] for x in quotes)])
db.close()
