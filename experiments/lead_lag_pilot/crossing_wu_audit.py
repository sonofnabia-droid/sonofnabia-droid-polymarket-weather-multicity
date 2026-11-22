#!/usr/bin/env python3
"""Exploratory WU observation agreement and archived outcome for high-price cases."""
import collections,csv,datetime as dt,json,sqlite3
from pathlib import Path
root=Path(__file__).resolve().parents[2]; base=root/'experiments/lead_lag_pilot'
db=sqlite3.connect(f'file:{root / "data/polymarket_weather_2026.sqlite"}?mode=ro',uri=True); db.execute('PRAGMA query_only=ON')
rows=[r for r in csv.DictReader((base/'crossings_daily.csv').open()) if r['status']=='complete' and float(r['yes_before'])>=.05]
wu=collections.defaultdict(list)
for city in ('lucknow','munich'):
    wanted={r['obs_utc'][:10] for r in rows if r['city']==city}
    with (root/'historic'/f'{city}.csv').open(newline='') as f:
        for x in csv.DictReader(f):
            try:
                t=dt.datetime.fromisoformat(x['timestamp_utc']).replace(tzinfo=dt.timezone.utc)
                if t.date().isoformat() in wanted and x['temp_c']: wu[(city,t.date().isoformat())].append((t,float(x['temp_c'])))
            except (ValueError,KeyError): pass
w=csv.writer(__import__('sys').stdout); w.writerow(['city','date','bracket','metar_time_utc','metar_temp','yes_before','no_before','wu_same_time_temp','bracket_yes_final','official_wu_verified'])
for r in rows:
    t=dt.datetime.fromisoformat(r['obs_utc']); matches=[v for stamp,v in wu[(r['city'],t.date().isoformat())] if stamp==t]
    market=db.execute('SELECT closed,outcome_prices,raw_json FROM markets WHERE city=? AND market_date=? AND bracket=?',(r['city'],r['date'],r['bracket'])).fetchone(); result='unknown'
    if market:
        try:
            meta=json.loads(market[2]); outcomes=meta.get('outcomes',[]); outcomes=json.loads(outcomes) if isinstance(outcomes,str) else outcomes; ix=next(i for i,x in enumerate(outcomes) if str(x).upper()=='YES'); prices=json.loads(market[1]); result=prices[ix] if market[0] else 'open'
        except (ValueError,IndexError,TypeError,StopIteration): pass
    w.writerow([r['city'],r['date'],r['bracket'],r['obs_utc'],r['temp'],r['yes_before'],r['no_before'],matches[0] if len(matches)==1 else 'missing_or_duplicate',result,'no'])
db.close()
