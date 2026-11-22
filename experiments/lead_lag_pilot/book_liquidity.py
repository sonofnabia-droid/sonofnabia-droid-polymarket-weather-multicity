#!/usr/bin/env python3
"""Summarize top-of-book availability for a bounded local research window."""
import csv,datetime as dt,sqlite3,statistics
from pathlib import Path
root=Path(__file__).resolve().parents[2]
db=sqlite3.connect(f'file:{root / "data/polymarket_weather_2026.sqlite"}?mode=ro',uri=True); db.execute('PRAGMA query_only=ON')
start=int(dt.datetime.fromisoformat('2026-11-15T08:00:00+00:00').timestamp()); end=int(dt.datetime.fromisoformat('2026-11-15T09:00:00+00:00').timestamp())
w=csv.writer(__import__('sys').stdout); w.writerow(['city','day','bracket','outcome','snapshots','with_bid','with_ask','two_sided','median_spread','median_ask_shares','minimum_ask_shares','first_snapshot','last_snapshot'])
for city in ('lucknow','munich'):
    rows=db.execute("SELECT m.bracket,t.outcome,t.token_id FROM markets m JOIN tokens t ON m.market_id=t.market_id WHERE m.city=? AND m.market_date=?",(city,'2026-11-15')).fetchall()
    for bracket,outcome,token in rows:
        books=db.execute('SELECT sampled_at,best_bid,bid_size,best_ask,ask_size FROM book_snapshots WHERE token_id=? AND sampled_at>=? AND sampled_at<? ORDER BY sampled_at',(token,start,end)).fetchall()
        two=[x for x in books if x[1] is not None and x[3] is not None]; sizes=[x[4] for x in books if x[3] is not None and x[4] is not None]; spreads=[x[3]-x[1] for x in two]
        fmt=lambda n:dt.datetime.fromtimestamp(n,dt.timezone.utc).isoformat() if n is not None else ''
        w.writerow([city,'2026-11-15',bracket,outcome,len(books),sum(x[1] is not None for x in books),sum(x[3] is not None for x in books),len(two),statistics.median(spreads) if spreads else '',statistics.median(sizes) if sizes else '',min(sizes) if sizes else '',fmt(books[0][0]) if books else '',fmt(books[-1][0]) if books else ''])
db.close()
