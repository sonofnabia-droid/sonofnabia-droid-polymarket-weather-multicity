#!/usr/bin/env python3
"""Inspect original METAR timestamp density on development days only."""
import csv,datetime as dt
from collections import defaultdict
from pathlib import Path
from zoneinfo import ZoneInfo
root=Path(__file__).resolve().parents[2]; base=root/'experiments/lead_lag_pilot'
wanted=defaultdict(set)
for r in csv.DictReader((base/'weekly_preliminary.csv').open()):
    if r['partition']=='development': wanted[r['city']].add(r['preliminary_day'])
out=csv.writer(__import__('sys').stdout)
out.writerow(['city','day','rows','unique_times','duplicates','first_local','last_local','max_gap_minutes','afternoon_observations'])
for city,zone in [('lucknow','Asia/Kolkata'),('munich','Europe/Berlin')]:
    tz=ZoneInfo(zone); days=defaultdict(list)
    with (root/'historic_metar'/f'{city}.csv').open(newline='') as f:
        for r in csv.DictReader(f):
            try:
                t=dt.datetime.fromisoformat(r['timestamp_utc']).replace(tzinfo=dt.timezone.utc).astimezone(tz)
                if t.date().isoformat() in wanted[city] and r['temp_c']: days[t.date().isoformat()].append(t)
            except (KeyError,ValueError): pass
    for day in sorted(wanted[city]):
        times=sorted(days[day]); unique=sorted(set(times)); gaps=[(b-a).total_seconds()/60 for a,b in zip(unique,unique[1:])]
        out.writerow([city,day,len(times),len(unique),len(times)-len(unique),unique[0].isoformat() if unique else '',unique[-1].isoformat() if unique else '',max(gaps) if gaps else '',sum(12<=x.hour<18 for x in unique)])
