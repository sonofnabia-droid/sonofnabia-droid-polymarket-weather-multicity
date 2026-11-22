#!/usr/bin/env python3
"""Ask-only upper ladder; missing quotes never filled with zero."""
import collections,csv,datetime as dt,re,sqlite3
from pathlib import Path
from zoneinfo import ZoneInfo
root=Path(__file__).resolve().parents[2]; base=root/'experiments/lead_lag_pilot'; db=sqlite3.connect(f'file:{root / "data/polymarket_weather_2026.sqlite"}?mode=ro',uri=True); db.execute('PRAGMA query_only=ON')
rows=[r for r in csv.DictReader((base/'legacy_book_dataset.csv').open()) if r['status']=='provisional']; info={}
for r in rows:
    key=(r['city'],r['day']); event=db.execute('SELECT slug FROM events WHERE city=? AND market_date=?',key).fetchone(); markets=db.execute('SELECT bracket FROM markets WHERE city=? AND market_date=?',key).fetchall(); parsed=[]
    for (name,) in markets:
        m=re.fullmatch(r'(-?\d+)°C(?: or (below|higher))?',name or '')
        if m:parsed.append((int(m.group(1)),name,m.group(2)))
    parsed.sort(); ix=next((i for i,x in enumerate(parsed) if x[1]==r['target_bracket']),None); info[key]={'row':r,'slug':event[0] if event else '','markets':markets,'parsed':parsed,'ix':ix}
db.close(); quotes=collections.defaultdict(dict)
with (root/'ask_collector_data.csv').open(newline='') as f:
    for r in csv.DictReader(f):
        city=r.get('city')
        if city not in ('lucknow','munich'):continue
        try:
            ts=dt.datetime.fromisoformat(r['ts'].replace('Z','+00:00')); tz=ZoneInfo('Asia/Kolkata' if city=='lucknow' else 'Europe/Berlin'); day=ts.astimezone(tz).date().isoformat(); key=(city,day); meta=info.get(key)
            if not meta or r.get('slug')!=meta['slug']:continue
            decision=dt.datetime.fromisoformat(meta['row']['decision_utc']); age=(decision-ts).total_seconds()
            if not 0<=age<=300:continue
            ask=float(r['best_ask'])
            if not 0<ask<1:continue
            label=r.get('bracket',''); old=quotes[key].get(label)
            if old is None or ts>old[0]:quotes[key][label]=(ts,ask)
        except (KeyError,TypeError,ValueError):pass
w=csv.writer(__import__('sys').stdout); w.writerow(['city','day','status','decision_utc','n_markets','n_asks','n_above','n_above_asks','above_ask_sum','above_ask_max','oldest_quote_sec'])
for key,meta in sorted(info.items()):
    row=meta['row']; parsed=meta['parsed']; ix=meta['ix']; q=quotes[key]; decision=dt.datetime.fromisoformat(row['decision_utc']); names=[x[1] for x in parsed]
    if ix is None or len(names)!=len(meta['markets']):w.writerow([*key,'unparsed_market']);continue
    above=names[ix+1:]; vals=[q[n] for n in above if n in q]
    if len(vals)!=len(above):w.writerow([*key,'incomplete_above',row['decision_utc'],len(names),len(q),len(above),len(vals)]);continue
    w.writerow([*key,'above_asks_complete',row['decision_utc'],len(names),len(q),len(above),len(vals),round(sum(x[1] for x in vals),6),max((x[1] for x in vals),default=0),round(max(((decision-x[0]).total_seconds() for x in vals),default=0),3)])
