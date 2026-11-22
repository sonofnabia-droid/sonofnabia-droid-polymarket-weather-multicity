#!/usr/bin/env python3
"""Audit archived Gamma resolution/updated timestamps; these are proxies only."""
import csv,datetime as dt,json,sqlite3
from pathlib import Path
root=Path(__file__).resolve().parents[2]; base=root/'experiments/lead_lag_pilot'; db=sqlite3.connect(f'file:{root / "data/polymarket_weather_2026.sqlite"}?mode=ro',uri=True); db.execute('PRAGMA query_only=ON')
w=csv.writer(__import__('sys').stdout); w.writerow(['city','day','n_markets','winner_bracket','all_closed_binary','all_uma_resolved','all_updated_timestamps','max_updated_utc','max_closed_utc','status'])
for r in csv.DictReader((base/'legacy_book_dataset.csv').open()):
    if r['status']!='provisional':continue
    markets=db.execute('SELECT bracket,closed,outcome_prices,raw_json FROM markets WHERE city=? AND market_date=?',(r['city'],r['day'])).fetchall(); resolved=0; closed_binary=0; updated=[]; closed_times=[]; winners=[]
    for name,closed,prices,raw in markets:
        try:
            o=json.loads(raw); outs=o.get('outcomes',[]); outs=json.loads(outs) if isinstance(outs,str) else outs; ix=next(i for i,x in enumerate(outs) if str(x).upper()=='YES'); val=float(json.loads(prices)[ix])
            if closed and val in (0,1):closed_binary+=1
            if closed and val==1:winners.append(name)
            if o.get('umaResolutionStatus')=='resolved':resolved+=1
            for field,dest in [('updatedAt',updated),('closedTime',closed_times)]:
                v=o.get(field)
                if v:
                    try:
                        t=dt.datetime.fromisoformat(str(v).replace('Z','+00:00'))
                        if t.tzinfo:dest.append(t.astimezone(dt.timezone.utc))
                    except ValueError:pass
        except (ValueError,TypeError,IndexError,StopIteration):pass
    n=len(markets); complete=bool(n) and closed_binary==n and resolved==n and len(updated)==n and len(winners)==1
    w.writerow([r['city'],r['day'],n,winners[0] if len(winners)==1 else '',bool(n) and closed_binary==n,bool(n) and resolved==n,bool(n) and len(updated)==n,max(updated).isoformat() if updated else '',max(closed_times).isoformat() if closed_times else '', 'proxy_available' if complete else 'incomplete'])
db.close()
