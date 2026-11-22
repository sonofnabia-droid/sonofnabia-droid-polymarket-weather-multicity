#!/usr/bin/env python3
"""Inventory archived contract metadata, without querying historical prices."""
import csv, json, sqlite3
from pathlib import Path

root=Path(__file__).resolve().parents[2]
db=sqlite3.connect(f'file:{root / "data/polymarket_weather_2026.sqlite"}?mode=ro',uri=True)
db.execute('PRAGMA query_only=ON')
w=csv.writer(__import__('sys').stdout)
w.writerow(['city','day','partition','markets','wu_source_all','whole_celsius_all','closed_all','unique_yes_winner','winner_bracket','interpretation'])
for r in csv.DictReader((root/'experiments/lead_lag_pilot/weekly_preliminary.csv').open()):
    if not r['preliminary_day']: continue
    city,day=r['city'],r['preliminary_day']
    rows=db.execute('SELECT bracket,closed,outcome_prices,raw_json FROM markets WHERE city=? AND market_date=?',(city,day)).fetchall()
    wu=[]; precision=[]; closed=[]; winners=[]
    for bracket,is_closed,prices,raw in rows:
        try:
            meta=json.loads(raw); desc=(meta.get('description') or '').lower(); source=(meta.get('resolutionSource') or '').lower()
            wu.append('wunderground' in desc or 'wunderground' in source)
            precision.append('whole degrees celsius' in desc)
            closed.append(bool(is_closed))
            outcomes=meta.get('outcomes',[]); outcomes=json.loads(outcomes) if isinstance(outcomes,str) else outcomes
            vals=json.loads(prices or '[]'); ix=next(i for i,x in enumerate(outcomes) if str(x).upper()=='YES')
            if is_closed and float(vals[ix])>=0.999: winners.append(bracket)
        except (ValueError,TypeError,KeyError,StopIteration,IndexError):
            pass
    w.writerow([city,day,r['partition'],len(rows),len(wu)==len(rows) and all(wu) and bool(rows),len(precision)==len(rows) and all(precision) and bool(rows),len(closed)==len(rows) and all(closed) and bool(rows),len(winners)==1,winners[0] if len(winners)==1 else '', 'archived metadata only; official source finalization unverified'])
db.close()
