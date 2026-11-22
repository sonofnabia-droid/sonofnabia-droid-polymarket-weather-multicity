#!/usr/bin/env python3
"""Measure first sampled historical YES decline; no causal attribution."""
import csv,datetime as dt,sqlite3
from pathlib import Path
root=Path(__file__).resolve().parents[2]; base=root/'experiments/lead_lag_pilot'
db=sqlite3.connect(f'file:{root / "data/polymarket_weather_2026.sqlite"}?mode=ro',uri=True); db.execute('PRAGMA query_only=ON')
w=csv.writer(__import__('sys').stdout); w.writerow(['city','day','bracket','obs_utc','initial_yes','samples_30m','first_post_utc','first_post_yes','first_below_5c_utc','first_below_5c_minutes','first_below_1c_utc','first_below_1c_minutes','last_post_utc'])
for r in csv.DictReader((base/'all_crossings.csv').open()):
    if not r['yes0'] or not r['no0'] or float(r['yes0'])<.05: continue
    row=db.execute("SELECT t.token_id FROM markets m JOIN tokens t ON m.market_id=t.market_id WHERE m.city=? AND m.market_date=? AND m.bracket=? AND t.outcome='YES'",(r['city'],r['day'],r['bracket'])).fetchone()
    if not row: continue
    stamp=dt.datetime.fromisoformat(r['obs_utc']); at=int(stamp.timestamp())
    quotes=db.execute('SELECT ts,price FROM price_points WHERE token_id=? AND fidelity_minutes=5 AND ts>? AND ts<=? ORDER BY ts',(row[0],at,at+1800)).fetchall()
    under5=next((x for x in quotes if x[1]<.05),None); under1=next((x for x in quotes if x[1]<.01),None)
    fmt=lambda x:dt.datetime.fromtimestamp(x[0],dt.timezone.utc).isoformat() if x else ''
    delta=lambda x:round((x[0]-at)/60,2) if x else ''
    w.writerow([r['city'],r['day'],r['bracket'],r['obs_utc'],r['yes0'],len(quotes),fmt(quotes[0]) if quotes else '',quotes[0][1] if quotes else '',fmt(under5),delta(under5),fmt(under1),delta(under1),fmt(quotes[-1]) if quotes else ''])
db.close()
