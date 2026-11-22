#!/usr/bin/env python3
"""Join target book to earlier observations, with no look-ahead."""
import collections,csv,datetime as dt,math,sqlite3
from pathlib import Path
root=Path(__file__).resolve().parents[2]; base=root/'experiments/lead_lag_pilot'
rows=[r for r in csv.DictReader((base/'legacy_book_dataset.csv').open()) if r['status']=='provisional']; lookup={(r['city'],r['day']):r for r in rows}; candidates=collections.defaultdict(list)
db=sqlite3.connect(f'file:{root / "data/polymarket_weather_2026.sqlite"}?mode=ro',uri=True); db.execute('PRAGMA query_only=ON')
slugs={k:(db.execute('SELECT slug FROM events WHERE city=? AND market_date=?',k).fetchone() or [''])[0] for k in lookup}; db.close()
with (root/'ask_collector_data.csv').open(newline='') as f:
    for row in csv.DictReader(f):
        city=row.get('city')
        if city not in ('lucknow','munich'):continue
        try:
            timestamp=dt.datetime.fromisoformat(row['ts'].replace('Z','+00:00'))
            # Event identity is the exact slug captured in the selected batch;
            # use local date of the sample to identify the same event.
            from zoneinfo import ZoneInfo
            day=timestamp.astimezone(ZoneInfo('Asia/Kolkata' if city=='lucknow' else 'Europe/Berlin')).date().isoformat(); target=lookup.get((city,day))
            if not target or row.get('bracket')!=target['target_bracket'] or row.get('slug')!=slugs[(city,day)]:continue
            decision=dt.datetime.fromisoformat(target['decision_utc']); age=(decision-timestamp).total_seconds()
            # Latest valid observation at least 30 minutes old, at most 90.
            if not 1800<=age<=5400:continue
            bid=float(row['best_bid']); ask=float(row['best_ask']); depth=float(row['ask_depth_usdc'])
            if not (0<bid<=ask<1 and depth>0):continue
            candidates[(city,day)].append((timestamp,bid,ask,depth,row.get('slug','')))
        except (KeyError,ValueError,TypeError):pass
w=csv.writer(__import__('sys').stdout); w.writerow(['city','day','status','decision_utc','prior_quote_utc','prior_age_min','prior_bid','prior_ask','prior_depth_usdc','ask_change','spread_change','logdepth_change'])
for r in rows:
    key=(r['city'],r['day']); options=candidates[key]
    if not options:w.writerow([*key,'missing_prior']);continue
    t,bid,ask,depth,slug=max(options,key=lambda x:x[0]); decision=dt.datetime.fromisoformat(r['decision_utc']); now_bid=float(r['best_bid']); now_ask=float(r['best_ask']); now_depth=float(r['ask_depth_top5_usdc'])
    w.writerow([*key,'provisional',r['decision_utc'],t.isoformat(),round((decision-t).total_seconds()/60,3),bid,ask,depth,round(now_ask-ask,6),round((now_ask-now_bid)-(ask-bid),6),round(math.log1p(now_depth)-math.log1p(depth),6)])
