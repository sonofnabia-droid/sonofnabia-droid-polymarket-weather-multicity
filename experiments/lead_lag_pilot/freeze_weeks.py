#!/usr/bin/env python3
"""Freeze preliminary weekly sample using daily coverage only; no price values."""
import csv, datetime as dt
from collections import defaultdict
from pathlib import Path

p=Path(__file__).resolve().parent
groups=defaultdict(list)
for r in csv.DictReader((p/'coverage.csv').open()):
    day=dt.date.fromisoformat(r['day']); groups[(r['city'],day.isocalendar()[:2])].append(r)
selected=[]
for (city,week), rows in sorted(groups.items()):
    eligible=[r for r in rows if r['event_status']=='found' and int(r['weather_observations'])>0 and int(r['markets'])>0 and r['markets']==r['yes_tokens_with_price']]
    selected.append((city,week,eligible[0]['day'] if eligible else ''))
w=csv.writer(__import__('sys').stdout); w.writerow(['city','iso_week','preliminary_day','partition'])
for city in ('lucknow','munich'):
    cityrows=[r for r in selected if r[0]==city]
    held={week for _,week,day in [x for x in cityrows if x[2]][-4:]}
    for _,week,day in cityrows:
        w.writerow([city,f'{week[0]}-W{week[1]:02}',day,'holdout' if week in held else ('development' if day else 'no_candidate')])
