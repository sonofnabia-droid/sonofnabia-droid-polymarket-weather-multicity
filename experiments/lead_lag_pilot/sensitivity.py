#!/usr/bin/env python3
"""Development-only price changes under hypothetical observation delays."""
import csv, datetime as dt, sqlite3
from pathlib import Path
root=Path(__file__).resolve().parents[2]
db=sqlite3.connect(f'file:{root / "data/polymarket_weather_2026.sqlite"}?mode=ro',uri=True)
db.execute('PRAGMA query_only=ON')
w=csv.writer(__import__('sys').stdout)
w.writerow(['city','day','bracket','hypothetical_delay_min','price_before','price_after','change_pp','before_utc','after_utc','status'])
for row in csv.DictReader((root/'experiments/lead_lag_pilot/development.csv').open()):
    if row['status'] not in ('descriptive','window_missing'): continue
    t=int(dt.datetime.fromisoformat(row['observation_utc']).timestamp())
    token=db.execute("SELECT t.token_id FROM markets m JOIN tokens t ON m.market_id=t.market_id WHERE m.city=? AND m.market_date=? AND m.bracket=? AND t.outcome='YES'",(row['city'],row['date'],row['candidate'])).fetchone()
    if not token: continue
    for delay in (0,15,30,60):
        points=[]
        for offset in (-30,30):
            at=t+(delay+offset)*60
            points.append(db.execute('SELECT ts,price FROM price_points WHERE token_id=? AND fidelity_minutes=5 AND ts BETWEEN ? AND ? ORDER BY ts DESC LIMIT 1',(token[0],at-600,at)).fetchone())
        if all(points):
            w.writerow([row['city'],row['date'],row['candidate'],delay,points[0][1],points[1][1],round((points[1][1]-points[0][1])*100,3),dt.datetime.fromtimestamp(points[0][0],dt.timezone.utc).isoformat(),dt.datetime.fromtimestamp(points[1][0],dt.timezone.utc).isoformat(),'descriptive'])
        else: w.writerow([row['city'],row['date'],row['candidate'],delay,'','','','','','missing'])
db.close()
