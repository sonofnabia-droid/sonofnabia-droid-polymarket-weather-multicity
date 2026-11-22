#!/usr/bin/env python3
"""Historical YES/NO as-of samples after the observation, not execution."""
import csv,datetime as dt,sqlite3
from pathlib import Path
root=Path(__file__).resolve().parents[2]; p=root/'experiments/lead_lag_pilot'
db=sqlite3.connect(f'file:{root / "data/polymarket_weather_2026.sqlite"}?mode=ro',uri=True); db.execute('PRAGMA query_only=ON')
w=csv.writer(__import__('sys').stdout); w.writerow(['city','day','bracket','delay_min','yes','no','yes_timestamp','no_timestamp','book_yes_bid','book_no_ask','book_no_ask_size'])
for r in csv.DictReader((p/'crossings_daily.csv').open()):
    if r['status'] not in ('complete','missing_prices'): continue
    t=int(dt.datetime.fromisoformat(r['obs_utc']).timestamp()); tokens=dict(db.execute("SELECT t.outcome,t.token_id FROM markets m JOIN tokens t ON m.market_id=t.market_id WHERE m.city=? AND m.market_date=? AND m.bracket=?",(r['city'],r['date'],r['bracket'])).fetchall())
    for delay in (0,5,10,15,30,60):
        at=t+delay*60; prices=[]; books=[]
        for outcome in ('YES','NO'):
            token=tokens.get(outcome)
            prices.append(db.execute('SELECT ts,price FROM price_points WHERE token_id=? AND fidelity_minutes=5 AND ts BETWEEN ? AND ? ORDER BY ts DESC LIMIT 1',(token,at-600,at)).fetchone() if token else None)
            books.append(db.execute('SELECT sampled_at,best_bid,best_ask,ask_size FROM book_snapshots WHERE token_id=? AND sampled_at BETWEEN ? AND ? ORDER BY sampled_at DESC LIMIT 1',(token,at-600,at)).fetchone() if token else None)
        fmt=lambda q:dt.datetime.fromtimestamp(q[0],dt.timezone.utc).isoformat() if q else ''
        w.writerow([r['city'],r['date'],r['bracket'],delay,prices[0][1] if prices[0] else '',prices[1][1] if prices[1] else '',fmt(prices[0]),fmt(prices[1]),books[0][1] if books[0] and books[0][1] is not None else '',books[1][2] if books[1] and books[1][2] is not None else '',books[1][3] if books[1] and books[1][3] is not None else ''])
db.close()
