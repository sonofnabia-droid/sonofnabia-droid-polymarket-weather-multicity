#!/usr/bin/env python3
"""Date-cluster summary of synchronized pre/post crossing price spreads."""
import csv
import datetime as dt
import random
import statistics
from collections import defaultdict
from pathlib import Path

BASE=Path(__file__).resolve().parent
rows=list(csv.DictReader((BASE/'crossing_placebo_event_study.csv').open(newline='')))
events=defaultdict(dict)
for row in rows:
    events[(row['city'],row['day'],row['obs_utc'],row['target_bracket'])][int(row['offset_min'])]=row
out=csv.writer(__import__('sys').stdout)
out.writerow(['city_scope','offset_min','paired_events_with_m15_base','local_days',
              'median_actual_target_quote_min','mean_spread_change_from_m15',
              'median_spread_change_from_m15','bootstrap95_low','bootstrap95_high',
              'mean_target_price_change','mean_control_price_change','mean_target_minus_control_spread',
              'median_target_minus_control_spread'])
rng=random.Random(15112026)
for offset in (-15,-10,-5,0,5,10,15,30):
    for scope in ('all','lucknow','munich'):
        sample=[]
        for key,series in events.items():
            if scope!='all' and key[0]!=scope: continue
            base,current=series.get(-15),series.get(offset)
            if not base or not current or base['status']!='paired' or current['status']!='paired': continue
            if not base['target_minus_control'] or not current['delta_difference_from_m15']: continue
            sample.append((key,base,current))
        by_day=defaultdict(list)
        for key,base,current in sample:
            by_day[key[1]].append(float(current['delta_difference_from_m15']))
        daily=[statistics.mean(v) for v in by_day.values()]
        point=statistics.mean(daily) if daily else 0
        boots=[]
        for _ in range(5000):
            draw=[rng.choice(daily) for _ in daily]
            boots.append(statistics.mean(draw))
        boots.sort()
        target_moves=[float(cur['target_price'])-float(base['target_price']) for _,base,cur in sample]
        control_moves=[float(cur['control_price'])-float(base['control_price']) for _,base,cur in sample]
        spreads=[float(cur['target_minus_control']) for _,base,cur in sample]
        elapsed=[(dt.datetime.fromisoformat(cur['target_price_utc'])-
                  dt.datetime.fromisoformat(key[2])).total_seconds()/60 for key,_,cur in sample]
        out.writerow([scope,offset,len(sample),len(by_day),
                      round(statistics.median(elapsed),3) if elapsed else '',round(point,6),
                      round(statistics.median(float(cur['delta_difference_from_m15']) for _,_,cur in sample),6) if sample else '',
                      round(boots[int(.025*len(boots))],6) if boots else '',
                      round(boots[int(.975*len(boots))-1],6) if boots else '',
                      round(statistics.mean(target_moves),6) if sample else '',
                      round(statistics.mean(control_moves),6) if sample else '',
                      round(statistics.mean(spreads),6) if sample else '',
                      round(statistics.median(spreads),6) if sample else ''])
