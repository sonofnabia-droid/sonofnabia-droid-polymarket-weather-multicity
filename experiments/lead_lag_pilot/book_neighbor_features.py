#!/usr/bin/env python3
"""Use only same-batch prior CLOB quotes for the next bracket above target."""
import collections,csv,datetime as dt,re,sqlite3
from pathlib import Path
from zoneinfo import ZoneInfo
root=Path(__file__).resolve().parents[2]; base=root/'experiments/lead_lag_pilot'
db=sqlite3.connect(f'file:{root / "data/polymarket_weather_2026.sqlite"}?mode=ro',uri=True); db.execute('PRAGMA query_only=ON')
rows=[r for r in csv.DictReader((base/'legacy_book_dataset.csv').open()) if r['status']=='provisional']; targets={}
for r in rows:
    city,day=r['city'],r['day']; event=db.execute('SELECT slug FROM events WHERE city=? AND market_date=?',(city,day)).fetchone(); markets=db.execute('SELECT bracket FROM markets WHERE city=? AND market_date=?',(city,day)).fetchall(); parsed=[]
    for (name,) in markets:
        m=re.fullmatch(r'(-?\d+)°C(?: or (below|higher))?',name or '')
        if m:parsed.append((int(m.group(1)),name,m.group(2)))
    parsed.sort(); ix=next((i for i,x in enumerate(parsed) if x[1]==r['target_bracket']),None)
    targets[(city,day)]={'row':r,'slug':event[0] if event else '', 'neighbor':parsed[ix+1][1] if ix is not None and ix+1<len(parsed) else ''}
db.close(); quotes=collections.defaultdict(list)
with (root/'ask_collector_data.csv').open(newline='') as f:
    for x in csv.DictReader(f):
        city=x.get('city')
        if city not in ('lucknow','munich'):continue
        try:
            ts=dt.datetime.fromisoformat(x['ts'].replace('Z','+00:00')); zone=ZoneInfo('Asia/Kolkata' if city=='lucknow' else 'Europe/Berlin'); day=ts.astimezone(zone).date().isoformat(); info=targets.get((city,day))
            if not info or not info['neighbor'] or x.get('bracket')!=info['neighbor'] or x.get('slug')!=info['slug']:continue
            decision=dt.datetime.fromisoformat(info['row']['decision_utc']); age=(decision-ts).total_seconds()
            if not 0<=age<=300:continue
            bid=float(x['best_bid']); ask=float(x['best_ask']); depth=float(x['ask_depth_usdc'])
            if not (0<bid<=ask<1 and depth>0):continue
            quotes[(city,day)].append((ts,bid,ask,depth))
        except (KeyError,ValueError,TypeError):pass
w=csv.writer(__import__('sys').stdout); w.writerow(['city','day','status','decision_utc','neighbor','neighbor_quote_utc','neighbor_age_sec','neighbor_bid','neighbor_ask','neighbor_depth_usdc','neighbor_minus_target_mid'])
for key,info in sorted(targets.items()):
    row=info['row']; options=quotes[key]
    if not info['neighbor']:w.writerow([*key,'no_higher_bracket']);continue
    if not options:w.writerow([*key,'no_valid_neighbor_quote']);continue
    ts,bid,ask,depth=max(options,key=lambda q:q[0]); decision=dt.datetime.fromisoformat(row['decision_utc']); targetmid=(float(row['best_bid'])+float(row['best_ask']))/2
    w.writerow([*key,'provisional',row['decision_utc'],info['neighbor'],ts.isoformat(),round((decision-ts).total_seconds(),3),bid,ask,depth,round((bid+ask)/2-targetmid,6)])
