#!/usr/bin/env python3
"""Build reduced causal-order weather features; publication remains unknown."""
import collections,csv,datetime as dt
from pathlib import Path
from zoneinfo import ZoneInfo
root=Path(__file__).resolve().parents[2]; base=root/'experiments/lead_lag_pilot'
rows=[r for r in csv.DictReader((base/'legacy_book_dataset.csv').open()) if r['status']=='provisional']; lookup={(r['city'],r['day']):r for r in rows}; observed=collections.defaultdict(list)
for city,zone in [('lucknow','Asia/Kolkata'),('munich','Europe/Berlin')]:
    tz=ZoneInfo(zone)
    with (root/'historic_metar'/f'{city}.csv').open(newline='') as f:
        for r in csv.DictReader(f):
            try:
                ts=dt.datetime.fromisoformat(r['timestamp_utc']); ts=ts.replace(tzinfo=dt.timezone.utc) if ts.tzinfo is None else ts.astimezone(dt.timezone.utc); day=ts.astimezone(tz).date().isoformat()
                if (city,day) in lookup and r['temp_c']:observed[(city,day)].append((ts,float(r['temp_c'])))
            except (ValueError,TypeError,KeyError):pass
w=csv.writer(__import__('sys').stdout); w.writerow(['city','day','status','decision_utc','last_obs_utc','previous_1h_obs_utc','last_temp','running_max','temp_below_max','warming_1h','minutes_since_last_max','observations'])
for r in rows:
    key=(r['city'],r['day']); decision=dt.datetime.fromisoformat(r['decision_utc']); available=sorted((t,v) for t,v in observed[key] if t<=decision-dt.timedelta(minutes=15))
    if len(available)<4:w.writerow([*key,'insufficient_observations']);continue
    last_t,last_temp=available[-1]; previous=[(t,v) for t,v in available if last_t-dt.timedelta(minutes=90)<=t<=last_t-dt.timedelta(minutes=60)]
    if not previous:w.writerow([*key,'missing_hour_lag']);continue
    prev_t,prev_temp=previous[-1]; maximum=max(v for t,v in available); last_max=max(t for t,v in available if v==maximum)
    w.writerow([*key,'provisional',decision.isoformat(),last_t.isoformat(),prev_t.isoformat(),last_temp,maximum,round(last_temp-maximum,4),round(last_temp-prev_temp,4),round((last_t-last_max).total_seconds()/60,2),len(available)])
