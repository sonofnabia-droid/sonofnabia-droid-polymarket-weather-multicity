#!/usr/bin/env python3
"""Price-move slices by pre-crossing target YES price; exploratory only."""
import csv
import datetime as dt
import statistics
from collections import defaultdict
from pathlib import Path

BASE = Path(__file__).resolve().parent
rows = list(csv.DictReader((BASE / 'neighbor_crossing_comparison.csv').open(newline='')))
events = defaultdict(dict)
for row in rows:
    if row['status'] != 'paired':
        continue
    key = row['city'], row['day'], row['obs_utc'], row['target_bracket']
    events[key][int(row['horizon_min'])] = row
out = csv.writer(__import__('sys').stdout)
out.writerow(['city_scope','initial_yes_bin','horizon_min','paired_events','local_days',
              'median_actual_minutes_after_obs','mean_target_delta','median_target_delta',
              'mean_control_delta','mean_target_minus_control','target_down_fraction'])
bins = [('lt_0.05', lambda p:p < .05), ('0.05_0.20', lambda p:.05 <= p < .20),
        ('0.20_0.50', lambda p:.20 <= p < .50), ('ge_0.50', lambda p:p >= .50)]
for city in ('all','lucknow','munich'):
    for label, test in bins:
        for horizon in (5,10,15):
            sample = []
            for key, points in events.items():
                if city != 'all' and key[0] != city:
                    continue
                base, later = points.get(0), points.get(horizon)
                if not base or not later or not base.get('target_price') or not later.get('target_price'):
                    continue
                if not test(float(base['target_price'])):
                    continue
                sample.append((key, base, later))
            if not sample:
                continue
            target_delta = [float(later['target_price'])-float(base['target_price'])
                            for _,base,later in sample]
            control_delta = [float(later['control_price'])-float(base['control_price'])
                             for _,base,later in sample]
            paired = [a-b for a,b in zip(target_delta,control_delta)]
            elapsed = [(dt.datetime.fromisoformat(later['target_price_utc'])-
                        dt.datetime.fromisoformat(key[2])).total_seconds()/60
                       for key,_,later in sample if later['target_price_utc']]
            out.writerow([city,label,horizon,len(sample),len({k[1] for k,_,_ in sample}),
                          round(statistics.median(elapsed),3) if elapsed else '',
                          round(statistics.mean(target_delta),6),round(statistics.median(target_delta),6),
                          round(statistics.mean(control_delta),6),round(statistics.mean(paired),6),
                          round(sum(x<0 for x in target_delta)/len(target_delta),6)])
