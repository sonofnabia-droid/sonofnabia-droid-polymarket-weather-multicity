#!/usr/bin/env python3
"""Market leadership before/after distinct METAR crossings, retrospective."""
import csv,datetime as dt,json,sqlite3
from pathlib import Path
root=Path(__file__).resolve().parents[2]; base=root/'experiments/lead_lag_pilot'
db=sqlite3.connect(f'file:{root / "data/polymarket_weather_2026.sqlite"}?mode=ro',uri=True); db.execute('PRAGMA query_only=ON')
events=sorted({(r['city'],r['day'],r['obs_utc']) for r in csv.DictReader((base/'all_crossings.csv').open())})
w=csv.writer(__import__('sys').stdout); w.writerow(['city','day','obs_utc','offset_min','status','n_markets','n_priced','winner','winner_price','leader','leader_price','winner_is_leader'])
for city,day,obs in events:
    markets=db.execute("SELECT m.bracket,m.closed,m.outcome_prices,m.raw_json,t.token_id FROM markets m JOIN tokens t ON m.market_id=t.market_id WHERE m.city=? AND m.market_date=? AND t.outcome='YES'",(city,day)).fetchall(); winners=[]
    for name,closed,prices,raw,token in markets:
        try:
            obj=json.loads(raw); outcomes=obj.get('outcomes',[]); outcomes=json.loads(outcomes) if isinstance(outcomes,str) else outcomes; idx=next(i for i,o in enumerate(outcomes) if str(o).upper()=='YES')
            if closed and float(json.loads(prices)[idx])>=.999: winners.append(name)
        except (ValueError,TypeError,IndexError,StopIteration): pass
    ts=int(dt.datetime.fromisoformat(obs).timestamp())
    for offset in (-10,0,10,30):
        now=ts+offset*60; quotes=[]
        for name,closed,prices,raw,token in markets:
            q=db.execute('SELECT price FROM price_points WHERE token_id=? AND fidelity_minutes=5 AND ts BETWEEN ? AND ? ORDER BY ts DESC LIMIT 1',(token,now-600,now)).fetchone()
            if q: quotes.append((float(q[0]),name))
        status='ok'
        if len(winners)!=1: status='no_unique_gamma_winner'
        elif len(quotes)!=len(markets) or not quotes: status='incomplete_prices'
        elif sum(q[0]==max(p[0] for p in quotes) for q in quotes)!=1: status='tie'
        if status!='ok': w.writerow([city,day,obs,offset,status,len(markets),len(quotes)]); continue
        leader=max(quotes); wp=next(x[0] for x in quotes if x[1]==winners[0])
        w.writerow([city,day,obs,offset,status,len(markets),len(quotes),winners[0],wp,leader[1],leader[0],leader[1]==winners[0]])
db.close()
