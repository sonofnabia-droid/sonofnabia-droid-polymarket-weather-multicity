#!/usr/bin/env python3
"""Exploratory METAR-crossed brackets, not proven official elimination."""
import csv, datetime as dt, re, sqlite3
from pathlib import Path
root=Path(__file__).resolve().parents[2]
db=sqlite3.connect(f'file:{root / "data/polymarket_weather_2026.sqlite"}?mode=ro',uri=True)
db.execute('PRAGMA query_only=ON')
w=csv.writer(__import__('sys').stdout)
w.writerow(['city','day','observation_utc','temp_c','bracket','minutes','price','price_utc','age_min','book_ask','book_ask_size','book_utc'])
for r in csv.DictReader((root/'experiments/lead_lag_pilot/development.csv').open()):
    if r['status'] not in ('descriptive','window_missing'): continue
    t=int(dt.datetime.fromisoformat(r['observation_utc']).timestamp()); temp=float(r['temp_c'])
    if not temp.is_integer(): continue
    markets=db.execute("SELECT m.bracket,t.token_id FROM markets m JOIN tokens t ON t.market_id=m.market_id WHERE m.city=? AND m.market_date=? AND t.outcome='YES'",(r['city'],r['date'])).fetchall()
    parsed=[]
    for name,token in markets:
        m=re.fullmatch(r'(-?\d+)°C(?: or (below|higher))?',name or '')
        if m and m.group(2)!='higher' and int(m.group(1))<temp: parsed.append((int(m.group(1)),name,token))
    if not parsed: continue
    _,bracket,token=max(parsed)
    for shift in (-30,0,15,30,60):
        at=t+shift*60
        price=db.execute('SELECT ts,price FROM price_points WHERE token_id=? AND fidelity_minutes=5 AND ts BETWEEN ? AND ? ORDER BY ts DESC LIMIT 1',(token,at-600,at)).fetchone()
        book=db.execute('SELECT sampled_at,best_ask,ask_size FROM book_snapshots WHERE token_id=? AND sampled_at BETWEEN ? AND ? ORDER BY sampled_at DESC LIMIT 1',(token,at-600,at)).fetchone()
        w.writerow([r['city'],r['date'],r['observation_utc'],temp,bracket,shift,price[1] if price else '',dt.datetime.fromtimestamp(price[0],dt.timezone.utc).isoformat() if price else '',round((at-price[0])/60,2) if price else '',book[1] if book else '',book[2] if book else '',dt.datetime.fromtimestamp(book[0],dt.timezone.utc).isoformat() if book else ''])
db.close()
