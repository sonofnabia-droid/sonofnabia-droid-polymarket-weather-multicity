#!/usr/bin/env python3
"""One pre-specified first afternoon METAR new high per day, descriptive."""
import collections,csv,datetime as dt,re,sqlite3
from pathlib import Path
from zoneinfo import ZoneInfo
root=Path(__file__).resolve().parents[2]; db=sqlite3.connect(f'file:{root / "data/polymarket_weather_2026.sqlite"}?mode=ro',uri=True); db.execute('PRAGMA query_only=ON')
w=csv.writer(__import__('sys').stdout); w.writerow(['city','date','status','obs_utc','temp','bracket','yes_before','yes_15_after','no_before','no_15_after','yes_before_time','no_before_time'])
for city,zone in [('lucknow','Asia/Kolkata'),('munich','Europe/Berlin')]:
    tz=ZoneInfo(zone); days=collections.defaultdict(list)
    with (root/'historic_metar'/f'{city}.csv').open(newline='') as f:
        for r in csv.DictReader(f):
            try:
                stamp=dt.datetime.fromisoformat(r['timestamp_utc']).replace(tzinfo=dt.timezone.utc); local=stamp.astimezone(tz); day=local.date().isoformat()
                if '2026-03-05'<=day<='2026-06-21' and r['temp_c']: days[day].append((stamp,float(r['temp_c'])))
            except (KeyError,ValueError): pass
    for day,obs in sorted(days.items()):
        peak=None; event=None
        for stamp,temp in sorted(obs):
            increase=peak is not None and temp>peak; peak=temp if peak is None else max(peak,temp)
            if increase and stamp.astimezone(tz).hour>=12: event=(stamp,temp); break
        if not event: w.writerow([city,day,'no_new_high']); continue
        stamp,temp=event; markets=db.execute("SELECT m.bracket,t.outcome,t.token_id FROM markets m JOIN tokens t ON m.market_id=t.market_id WHERE m.city=? AND m.market_date=?",(city,day)).fetchall(); grouped=collections.defaultdict(dict)
        for bracket,outcome,token in markets:
            m=re.fullmatch(r'(-?\d+)°C(?: or (below|higher))?',bracket or '')
            if m and m.group(2)!='higher' and temp.is_integer() and int(m.group(1))<temp: grouped[(int(m.group(1)),bracket)][outcome.upper()]=token
        if not grouped: w.writerow([city,day,'no_lower_bracket',stamp.isoformat(),temp]); continue
        _,bracket=max(grouped); tokens=grouped[(_,bracket)]; prices=[]
        for outcome,shift in [('YES',0),('YES',15),('NO',0),('NO',15)]:
            at=int(stamp.timestamp())+shift*60; token=tokens.get(outcome)
            q=db.execute('SELECT ts,price FROM price_points WHERE token_id=? AND fidelity_minutes=5 AND ts BETWEEN ? AND ? ORDER BY ts DESC LIMIT 1',(token,at-600,at)).fetchone() if token else None
            prices.append(q)
        val=lambda q:q[1] if q else ''
        time=lambda q:dt.datetime.fromtimestamp(q[0],dt.timezone.utc).isoformat() if q else ''
        w.writerow([city,day,'complete' if all(prices) else 'missing_prices',stamp.isoformat(),temp,bracket,*[val(q) for q in prices],time(prices[0]),time(prices[2])])
db.close()
