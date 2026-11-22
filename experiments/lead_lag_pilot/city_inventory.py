#!/usr/bin/env python3
"""Index-directed city/day/token inventory; no global scan of price tables."""
import argparse,csv,datetime as dt,json,sqlite3
from pathlib import Path
root=Path(__file__).resolve().parents[2]
p=argparse.ArgumentParser(); p.add_argument('--start',required=True); p.add_argument('--end',required=True); args=p.parse_args()
db=sqlite3.connect(f'file:{root / "data/polymarket_weather_2026.sqlite"}?mode=ro',uri=True); db.execute('PRAGMA query_only=ON')
out=csv.writer(__import__('sys').stdout)
out.writerow(['city','day','event_status','markets','tokens','tokens_with_prices','price_min_utc','price_max_utc','fidelities','sources','tokens_with_books','book_min_utc','book_max_utc'])
events=db.execute('SELECT city,market_date,status FROM events WHERE market_date BETWEEN ? AND ? ORDER BY city,market_date',(args.start,args.end)).fetchall()
for city,day,status in events:
    markets=db.execute('SELECT market_id FROM markets WHERE city=? AND market_date=?',(city,day)).fetchall()
    tokens=db.execute('SELECT t.token_id FROM markets m JOIN tokens t ON m.market_id=t.market_id WHERE m.city=? AND m.market_date=?',(city,day)).fetchall()
    price_count=book_count=0; pmin=pmax=bmin=bmax=None; fidelities=set(); sources=set()
    for (token,) in tokens:
        # MIN/MAX use the token-prefixed primary key. Separate fidelity/source probe
        # reads only one token at a time and reports observed combinations.
        pr=db.execute('SELECT MIN(ts),MAX(ts) FROM price_points WHERE token_id=?',(token,)).fetchone()
        if pr[0] is not None:
            price_count+=1; pmin=min(pmin,pr[0]) if pmin is not None else pr[0]; pmax=max(pmax,pr[1]) if pmax is not None else pr[1]
            for f,s in db.execute('SELECT DISTINCT fidelity_minutes,source FROM price_points WHERE token_id=?',(token,)): fidelities.add(f); sources.add(s)
        br=db.execute('SELECT MIN(sampled_at),MAX(sampled_at) FROM book_snapshots WHERE token_id=?',(token,)).fetchone()
        if br[0] is not None:
            book_count+=1; bmin=min(bmin,br[0]) if bmin is not None else br[0]; bmax=max(bmax,br[1]) if bmax is not None else br[1]
    fmt=lambda t:dt.datetime.fromtimestamp(t,dt.timezone.utc).isoformat() if t is not None else ''
    out.writerow([city,day,status,len(markets),len(tokens),price_count,fmt(pmin),fmt(pmax),','.join(map(str,sorted(fidelities))),','.join(sorted(sources)),book_count,fmt(bmin),fmt(bmax)])
db.close()
