#!/usr/bin/env python3
"""Historical YES sums with quote timestamps; not an arbitrage test."""
import csv,datetime as dt,sqlite3,statistics
from pathlib import Path
from zoneinfo import ZoneInfo
root=Path(__file__).resolve().parents[2]; base=root/'experiments/lead_lag_pilot'; db=sqlite3.connect(f'file:{root / "data/polymarket_weather_2026.sqlite"}?mode=ro',uri=True); db.execute('PRAGMA query_only=ON')
w=csv.writer(__import__('sys').stdout); w.writerow(['city','day','hour','status','token_count','price_count','sum_yes','max_age_sec','timestamp_range_sec'])
rows=list(csv.DictReader((base/'rmax_market_compare_delay15_through_july17.csv').open()))
for r in rows:
    if r['status']!='descriptive': continue
    city,day,hour=r['city'],r['day'],int(r['hour']); tz=ZoneInfo('Asia/Kolkata' if city=='lucknow' else 'Europe/Berlin'); now=int(dt.datetime.combine(dt.date.fromisoformat(day),dt.time(hour),tz).timestamp())
    tokens=db.execute("SELECT t.token_id FROM markets m JOIN tokens t ON m.market_id=t.market_id WHERE m.city=? AND m.market_date=? AND t.outcome='YES'",(city,day)).fetchall(); q=[]
    for (token,) in tokens:
        p=db.execute('SELECT ts,price FROM price_points WHERE token_id=? AND fidelity_minutes=5 AND ts BETWEEN ? AND ? ORDER BY ts DESC LIMIT 1',(token,now-600,now)).fetchone()
        if p: q.append(p)
    complete=bool(tokens) and len(q)==len(tokens)
    w.writerow([city,day,hour,'descriptive' if complete else 'missing',len(tokens),len(q),round(sum(x[1] for x in q),5) if complete else '',max(now-x[0] for x in q) if q else '',max(x[0] for x in q)-min(x[0] for x in q) if q else ''])
db.close()
