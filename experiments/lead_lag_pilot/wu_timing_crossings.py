#!/usr/bin/env python3
"""Compare retrospective local WU observation timestamps to METAR crossings."""
import collections,csv,datetime as dt,re
from pathlib import Path
from zoneinfo import ZoneInfo
root=Path(__file__).resolve().parents[2]; base=root/'experiments/lead_lag_pilot'
rows=list(csv.DictReader((base/'all_crossings.csv').open())); w=csv.writer(__import__('sys').stdout)
w.writerow(['city','day','bracket','metar_obs_utc','yes0','no0','wu_crossing_obs_utc','wu_minus_metar_min','classification','gamma_closed_yes_price'])
for city,zone in [('lucknow','Asia/Kolkata'),('munich','Europe/Berlin')]:
    tz=ZoneInfo(zone); obs=collections.defaultdict(list); wanted={r['day'] for r in rows if r['city']==city}
    with (root/'historic'/f'{city}.csv').open(newline='') as f:
        for x in csv.DictReader(f):
            try:
                stamp=dt.datetime.fromisoformat(x['timestamp_utc']); stamp=stamp.replace(tzinfo=dt.timezone.utc) if stamp.tzinfo is None else stamp.astimezone(dt.timezone.utc); day=stamp.astimezone(tz).date().isoformat()
                if day in wanted and x['temp_c']: obs[day].append((stamp,float(x['temp_c'])))
            except (ValueError,KeyError): pass
    for r in rows:
        if r['city']!=city: continue
        upper=int(re.match(r'(-?\d+)',r['bracket']).group()); metar=dt.datetime.fromisoformat(r['obs_utc']); qualifying=sorted((t,v) for t,v in obs[r['day']] if v>upper)
        first=qualifying[0][0] if qualifying else None
        delta=round((first-metar).total_seconds()/60,2) if first else ''
        classification=('no_wu_crossing' if first is None else 'wu_before' if first<metar else 'same_observed_time' if first==metar else 'wu_after')
        w.writerow([city,r['day'],r['bracket'],r['obs_utc'],r['yes0'],r['no0'],first.isoformat() if first else '',delta,classification,r['gamma_closed_yes_price']])
