#!/usr/bin/env python3
"""Date-cluster inference for a three-rung price transfer event study."""
import csv
import datetime as dt
import random
import statistics
from collections import defaultdict
from pathlib import Path

BASE=Path(__file__).resolve().parent
rows=list(csv.DictReader((BASE/'crossing_upper_ladder_event_study.csv').open(newline='')))
events=defaultdict(dict)
for r in rows:
    events[(r['city'],r['day'],r['obs_utc'],r['crossed_bracket'])][int(r['offset_min'])]=r
out=csv.writer(__import__('sys').stdout)
out.writerow(['city_scope','offset_min','paired_events_with_m15_base','local_days',
              'median_actual_quote_min_after_obs','mean_change_crossed_minus_next',
              'ci95_tn_low','ci95_tn_high','mean_change_next_minus_second',
              'ci95_nu_low','ci95_nu_high','mean_localized_transfer_tn_minus_nu',
              'ci95_localized_low','ci95_localized_high','tn_spread_down_fraction',
              'nu_spread_up_fraction'])
for offset in (-15,-10,-5,0,5,10,15,30):
    for scope in ('all','lucknow','munich'):
        sample=[]
        for key,path in events.items():
            if scope!='all' and key[0]!=scope: continue
            base,current=path.get(-15),path.get(offset)
            if not base or not current or base['status']!='paired' or current['status']!='paired': continue
            if not current['spread_change_from_m15_crossed_next'] or not current['spread_change_from_m15_next_second']: continue
            sample.append((key,current))
        by_day=defaultdict(list)
        for key,r in sample:
            by_day[key[1]].append((float(r['spread_change_from_m15_crossed_next']),
                                  float(r['spread_change_from_m15_next_second'])))
        daily=[(statistics.mean(v[0] for v in values),statistics.mean(v[1] for v in values))
               for values in by_day.values()]
        means=[statistics.mean(v[i] for v in daily) for i in range(2)] if daily else [0,0]
        boots=[[],[],[]]; rng=random.Random(15112026+offset+(0 if scope=='all' else 1 if scope=='lucknow' else 2))
        for _ in range(5000):
            draw=[rng.choice(daily) for _ in daily]
            v1=statistics.mean(x[0] for x in draw); v2=statistics.mean(x[1] for x in draw)
            for i,v in enumerate((v1,v2,v1-v2)): boots[i].append(v)
        for b in boots: b.sort()
        spread1=[float(r['crossed_minus_next']) for _,r in sample]
        spread2=[float(r['next_minus_second']) for _,r in sample]
        elapsed=[(dt.datetime.fromisoformat(r['crossed_utc'])-
                  dt.datetime.fromisoformat(key[2])).total_seconds()/60 for key,r in sample]
        out.writerow([scope,offset,len(sample),len(by_day),
            round(statistics.median(elapsed),3) if elapsed else '',round(means[0],6),
            round(boots[0][int(.025*len(boots[0]))],6) if boots[0] else '',
            round(boots[0][int(.975*len(boots[0]))-1],6) if boots[0] else '',round(means[1],6),
            round(boots[1][int(.025*len(boots[1]))],6) if boots[1] else '',
            round(boots[1][int(.975*len(boots[1]))-1],6) if boots[1] else '',
            round(means[0]-means[1],6),round(boots[2][int(.025*len(boots[2]))],6) if boots[2] else '',
            round(boots[2][int(.975*len(boots[2]))-1],6) if boots[2] else '',
            round(sum(x<0 for x in spread1)/len(spread1),6) if spread1 else '',
            round(sum(x>0 for x in spread2)/len(spread2),6) if spread2 else ''])
