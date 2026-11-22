#!/usr/bin/env python3
"""Market-leader exploratory baseline for explicit dates; no holdout dates."""
import argparse,csv,datetime as dt,json,sqlite3
from pathlib import Path
from zoneinfo import ZoneInfo,ZoneInfoNotFoundError
root=Path(__file__).resolve().parents[2]
p=argparse.ArgumentParser(); p.add_argument('--start',required=True); p.add_argument('--end',required=True); a=p.parse_args()
if a.end >= '2026-06-22': raise SystemExit('Reserved period excluded')
db=sqlite3.connect(f'file:{root / "data/polymarket_weather_2026.sqlite"}?mode=ro',uri=True); db.execute('PRAGMA query_only=ON')
w=csv.writer(__import__('sys').stdout); w.writerow(['city','day','hour_local','brackets','priced','leader','leader_price','winner','leader_won','mean_quote_age_min','status'])
events=db.execute("SELECT city,market_date,timezone FROM events WHERE status='found' AND market_date BETWEEN ? AND ? ORDER BY city,market_date",(a.start,a.end)).fetchall()
for city,day,zone in events:
    try: tz=ZoneInfo(zone)
    except (ZoneInfoNotFoundError,TypeError): continue
    rows=db.execute("SELECT m.bracket,m.closed,m.outcome_prices,m.raw_json,t.token_id FROM markets m JOIN tokens t ON t.market_id=m.market_id WHERE m.city=? AND m.market_date=? AND t.outcome='YES'",(city,day)).fetchall()
    wins=[]
    for bracket,closed,prices,raw,token in rows:
        try:
            meta=json.loads(raw); outcomes=meta.get('outcomes',[]); outcomes=json.loads(outcomes) if isinstance(outcomes,str) else outcomes
            ix=next(i for i,x in enumerate(outcomes) if str(x).upper()=='YES'); values=json.loads(prices or '[]')
            if closed and float(values[ix])>=.999: wins.append(bracket)
        except (ValueError,TypeError,IndexError,KeyError,StopIteration): pass
    for hour in (12,15):
        instant=dt.datetime.combine(dt.date.fromisoformat(day),dt.time(hour),tz); ts=int(instant.timestamp()); quotes=[]
        for bracket,_,_,_,token in rows:
            q=db.execute('SELECT ts,price FROM price_points WHERE token_id=? AND fidelity_minutes=5 AND ts BETWEEN ? AND ? ORDER BY ts DESC LIMIT 1',(token,ts-600,ts)).fetchone()
            if q: quotes.append((q[1],bracket,ts-q[0]))
        if len(wins)!=1: status='winner_unverified'
        elif not rows or len(quotes)!=len(rows): status='incomplete_prices'
        elif sum(x[0]==max(q[0] for q in quotes) for x in quotes)>1: status='tied_leaders'
        else: status='exploratory'
        leader=max(quotes) if quotes else None
        w.writerow([city,day,hour,len(rows),len(quotes),leader[1] if leader else '',leader[0] if leader else '',wins[0] if len(wins)==1 else '',leader[1]==wins[0] if leader and len(wins)==1 else '',round(sum(x[2] for x in quotes)/len(quotes)/60,2) if quotes else '',status])
db.close()
