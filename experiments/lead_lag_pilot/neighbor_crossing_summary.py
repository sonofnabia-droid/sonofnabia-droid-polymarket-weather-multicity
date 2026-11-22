#!/usr/bin/env python3
"""Summarize paired crossing moves with date-cluster bootstrap intervals."""
import csv
import random
import statistics
import datetime as dt
from collections import defaultdict
from pathlib import Path

BASE = Path(__file__).resolve().parent
rows = list(csv.DictReader((BASE / 'neighbor_crossing_comparison.csv').open(newline='')))
out = csv.writer(__import__('sys').stdout)
out.writerow(['city_scope','horizon_min','paired_events','local_days','mean_target_delta',
              'median_target_delta','mean_control_delta','median_control_delta',
              'mean_paired_difference','bootstrap95_low','bootstrap95_high',
              'target_down_fraction','control_up_fraction','median_actual_quote_min_after_obs',
              'target_quotes_fresh_le_600s'])
rng = random.Random(15112026)
for horizon in (5, 10, 15):
    for city in ('all', 'lucknow', 'munich'):
        sample = [r for r in rows if int(r['horizon_min']) == horizon
                  and r['status'] == 'paired' and (city == 'all' or r['city'] == city)]
        by_day = defaultdict(list)
        for row in sample:
            by_day[row['day']].append((float(row['target_delta_from_0']),
                                       float(row['control_delta_from_0']),
                                       float(row['paired_delta_difference'])))
        day_values = [tuple(sum(x[i] for x in events)/len(events) for i in range(3))
                      for events in by_day.values()]
        means = [sum(x[i] for x in day_values)/len(day_values) for i in range(3)]
        boots = []
        for _ in range(5000):
            draw = [rng.choice(day_values) for _ in day_values]
            boots.append(sum(x[2] for x in draw)/len(draw))
        boots.sort()
        n = len(sample)
        elapsed = [(dt.datetime.fromisoformat(r['target_price_utc'])-
                    dt.datetime.fromisoformat(r['obs_utc'])).total_seconds()/60
                   for r in sample if r['target_price_utc']]
        out.writerow([city, horizon, n, len(by_day), round(means[0], 6),
                      round(statistics.median(float(r['target_delta_from_0']) for r in sample), 6),
                      round(means[1], 6),
                      round(statistics.median(float(r['control_delta_from_0']) for r in sample), 6),
                      round(means[2], 6), round(boots[int(.025*len(boots))], 6),
                      round(boots[int(.975*len(boots))-1], 6),
                      round(sum(float(r['target_delta_from_0']) < 0 for r in sample)/n, 6),
                      round(sum(float(r['control_delta_from_0']) > 0 for r in sample)/n, 6),
                      round(statistics.median(elapsed),3) if elapsed else '',
                      sum(int(r['target_age_sec']) <= 600 for r in sample)])
