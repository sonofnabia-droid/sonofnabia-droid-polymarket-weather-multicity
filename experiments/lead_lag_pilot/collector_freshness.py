#!/usr/bin/env python3
"""Audit whether a new target CLOB observation exists after a decision."""
import collections,csv,datetime as dt,sqlite3
from pathlib import Path
from zoneinfo import ZoneInfo
root=Path(__file__).resolve().parents[2]; base=root/'experiments/lead_lag_pilot'; db=sqlite3.connect(f'file:{root / "data/polymarket_weather_2026.sqlite"}?mode=ro',uri=True); db.execute('PRAGMA query_only=ON')
rows=[r for r in csv.DictReader((base/'legacy_book_dataset.csv').open()) if r['status']=='provisional']; info={}
for r in rows:
    key=(r['city'],r['day']); event=db.execute('SELECT slug FROM events WHERE city=? AND market_date=?',key).fetchone(); info[key]=(r,event[0] if event else '')
db.close(); candidates=collections.defaultdict(list)
with (root/'ask_collector_data.csv').open(newline='') as f:
    for r in csv.DictReader(f):
        city=r.get('city')
        if city not in ('lucknow','munich'):continue
        try:
            t=dt.datetime.fromisoformat(r['ts'].replace('Z','+00:00')); day=t.astimezone(ZoneInfo('Asia/Kolkata' if city=='lucknow' else 'Europe/Berlin')).date().isoformat(); key=(city,day); meta=info.get(key)
            if not meta or r.get('slug')!=meta[1] or r.get('bracket')!=meta[0]['target_bracket']:continue
            decision=dt.datetime.fromisoformat(meta[0]['decision_utc']); age=(t-decision).total_seconds()
            if not -600<=age<=3600:continue
            ask=float(r['best_ask'])
            if not 0<ask<1:continue
            candidates[key].append((t,ask))
        except (KeyError,TypeError,ValueError):pass
w=csv.writer(__import__('sys').stdout); w.writerow(['city','day','decision_utc','delay_min','status','quote_utc','quote_age_sec','ask','new_quote_after_decision'])
for (city,day),(r,slug) in sorted(info.items()):
    decision=dt.datetime.fromisoformat(r['decision_utc'])
    for delay in (0,5,10,15,30,60):
        cutoff=decision+dt.timedelta(minutes=delay); valid=[x for x in candidates[(city,day)] if 0<=(cutoff-x[0]).total_seconds()<=600]
        if not valid:w.writerow([city,day,r['decision_utc'],delay,'no_recent_quote']); continue
        t,ask=max(valid,key=lambda x:x[0]); w.writerow([city,day,r['decision_utc'],delay,'recent_quote',t.isoformat(),round((cutoff-t).total_seconds(),2),ask,t>decision])
