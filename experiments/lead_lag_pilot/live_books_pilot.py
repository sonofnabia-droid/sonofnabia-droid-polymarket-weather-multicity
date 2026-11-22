#!/usr/bin/env python3
"""Observed archived books around METAR highs, descriptive and provisional."""
import collections,csv,datetime as dt,re,sqlite3
from pathlib import Path
from zoneinfo import ZoneInfo
root=Path(__file__).resolve().parents[2]; db=sqlite3.connect(f'file:{root / "data/polymarket_weather_2026.sqlite"}?mode=ro',uri=True); db.execute('PRAGMA query_only=ON')
w=csv.writer(__import__('sys').stdout); w.writerow(['city','day','observed_utc','temp','bracket','delay_minutes','yes_bid','yes_bid_size','yes_sampled_utc','no_ask','no_ask_size','no_sampled_utc','status'])
for city,zone in [('munich','Europe/Berlin'),('lucknow','Asia/Kolkata')]:
    tz=ZoneInfo(zone); obs=[]
    with (root/'historic_metar'/f'{city}.csv').open(newline='') as f:
        for r in csv.DictReader(f):
            try:
                t=dt.datetime.fromisoformat(r['timestamp_utc']).replace(tzinfo=dt.timezone.utc)
                if t.astimezone(tz).date().isoformat()=='2026-11-15' and r['temp_c']: obs.append((t,float(r['temp_c'])))
            except (KeyError,ValueError): pass
    peak=None
    for t,temp in sorted(obs):
        increase=peak is not None and temp>peak; peak=temp if peak is None else max(peak,temp)
        if not increase or not temp.is_integer(): continue
        rows=db.execute('SELECT m.bracket,t.outcome,t.token_id FROM markets m JOIN tokens t ON m.market_id=t.market_id WHERE m.city=? AND m.market_date=?',(city,'2026-11-15')).fetchall(); groups=collections.defaultdict(dict)
        for name,outcome,token in rows:
            m=re.fullmatch(r'(-?\d+)°C(?: or (below|higher))?',name or '')
            if m and m.group(2)!='higher' and int(m.group(1))<temp: groups[(int(m.group(1)),name)][outcome.upper()]=token
        if not groups:
            w.writerow([city,'2026-11-15',t.isoformat(),temp,'','','','','','','','','no_lower_bracket']); continue
        key=max(groups); name=key[1]; tokens=groups[key]
        for delay in (0,5,10,15):
            at=int(t.timestamp())+delay*60; data=[]
            for outcome in ('YES','NO'):
                token=tokens.get(outcome)
                data.append(db.execute('SELECT sampled_at,best_bid,bid_size,best_ask,ask_size FROM book_snapshots WHERE token_id=? AND sampled_at BETWEEN ? AND ? ORDER BY sampled_at DESC LIMIT 1',(token,at-600,at)).fetchone() if token else None)
            yes,no=data; fmt=lambda row:dt.datetime.fromtimestamp(row[0],dt.timezone.utc).isoformat() if row else ''
            val=lambda row,index: row[index] if row and row[index] is not None else ''
            w.writerow([city,'2026-11-15',t.isoformat(),temp,name,delay,val(yes,1),val(yes,2),fmt(yes),val(no,3),val(no,4),fmt(no),'descriptive_no_verified_publication'])
db.close()
