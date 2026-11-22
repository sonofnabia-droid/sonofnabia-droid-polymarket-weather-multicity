#!/usr/bin/env python3
"""Read-only daily coverage for legacy sampled CLOB ask collector."""
import collections,csv,datetime as dt,sqlite3
from pathlib import Path
from zoneinfo import ZoneInfo
root=Path(__file__).resolve().parents[2]; db=sqlite3.connect(f'file:{root / "data/polymarket_weather_2026.sqlite"}?mode=ro',uri=True); db.execute('PRAGMA query_only=ON')
groups=collections.defaultdict(lambda:{'rows':0,'bids':0,'asks':0,'two':0,'times':set(),'slugs':set(),'ages15':[],'ages60':[],'brackets':set()})
with (root/'ask_collector_data.csv').open(newline='') as f:
    for r in csv.DictReader(f):
        city=r.get('city'); zone={'lucknow':'Asia/Kolkata','munich':'Europe/Berlin'}.get(city)
        if not zone:continue
        try:
            t=dt.datetime.fromisoformat(r['ts'].replace('Z','+00:00'))
            if not t.tzinfo:continue
            local=t.astimezone(ZoneInfo(zone)); day=local.date();
            if day>dt.date(2026,11,14):continue
            key=(city,day.isoformat()); g=groups[key]; g['rows']+=1; g['times'].add(t.isoformat()); g['slugs'].add(r.get('slug','')); g['brackets'].add(r.get('bracket',''))
            bid=float(r['best_bid']) if r.get('best_bid') else None; ask=float(r['best_ask']) if r.get('best_ask') else None
            g['bids']+=bid is not None; g['asks']+=ask is not None; g['two']+=bid is not None and ask is not None
            cutoff=dt.datetime.combine(day,dt.time(15),ZoneInfo(zone)); age=(cutoff-local).total_seconds()
            if ask is not None and 0<=age<=900:g['ages15'].append(r.get('bracket',''))
            if ask is not None and 0<=age<=3600:g['ages60'].append(r.get('bracket',''))
        except (ValueError,TypeError,KeyError):continue
w=csv.writer(__import__('sys').stdout); w.writerow(['city','day','rows','bid_rows','ask_rows','two_sided_rows','distinct_sample_times','distinct_brackets','event_status','event_slug_matches','markets_count','15h_ask_brackets_15min','15h_ask_brackets_60min'])
for (city,day),g in sorted(groups.items()):
    event=db.execute('SELECT status,slug FROM events WHERE city=? AND market_date=?',(city,day)).fetchone(); n=db.execute('SELECT COUNT(*) FROM markets WHERE city=? AND market_date=?',(city,day)).fetchone()[0]
    w.writerow([city,day,g['rows'],g['bids'],g['asks'],g['two'],len(g['times']),len(g['brackets']),event[0] if event else 'absent',bool(event) and g['slugs']=={event[1]},n,len(set(g['ages15'])),len(set(g['ages60']))])
db.close()
