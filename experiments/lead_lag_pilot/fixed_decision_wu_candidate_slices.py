#!/usr/bin/env python3
"""Exploratory WU-at-15:00 candidate P&L slices by month/bracket/price."""
import csv
import datetime as dt
import random
import statistics
from collections import defaultdict
from pathlib import Path

BASE=Path(__file__).resolve().parent
rows=list(csv.DictReader((BASE/'fixed_decision_weather_market_gate.csv').open(newline='')))
sample=[]
for r in rows:
    if not r['wu_price'] or r['wu_weather_winner'] not in ('True','False'):
        continue
    p=float(r['wu_price']); win=r['wu_weather_winner']=='True'
    gross=float(win)-p; fee=.05*p*(1-p)
    item={**r,'p':p,'win':win,'gross':gross,'net':gross-fee,
          'month':r['day'][:7],
          'age_sec':(dt.datetime.fromisoformat(r['decision_utc'])-
                     dt.datetime.fromisoformat(r['wu_price_utc'])).total_seconds(),
          'price_bin':'lt_0.50' if p<.5 else '0.50_0.80' if p<.8 else '0.80_0.95' if p<.95 else 'ge_0.95'}
    age=item['age_sec']
    item['age_bin']='le_120s' if age<=120 else '120_300s' if age<=300 else '300_600s' if age<=600 else 'gt_600s'
    sample.append(item)

groups=[]
for scope in ('all','lucknow','munich'):
    universe=[r for r in sample if scope=='all' or r['city']==scope]
    groups.append((scope,'all', 'all',universe))
    for kind,field in [('month','month'),('bracket','wu_bracket'),('price_bin','price_bin'),('quote_age','age_bin')]:
        keys=sorted({r[field] for r in universe})
        for key in keys:
            groups.append((scope,kind,key,[r for r in universe if r[field]==key]))

out=csv.writer(__import__('sys').stdout)
out.writerow(['city_scope','slice_type','slice_value','n','local_days','wins','losses','hit_rate',
              'mean_pricepoint','gross_per_trade','fee_scenario_net_per_trade',
              'fee_net_total_one_share','bootstrap95_net_mean_low','bootstrap95_net_mean_high',
              'maxdd_additive_one_share','quote_age_median_sec',
              'note'])
for scope,kind,key,group in groups:
    if not group: continue
    daily=defaultdict(list)
    for r in group: daily[r['day']].append(r['net'])
    days=list(daily)
    rng=random.Random(15112026+sum(ord(x) for x in (scope+kind+key)))
    boots=[]
    for _ in range(5000):
        draw=[rng.choice(days) for _ in days]
        values=[v for day in draw for v in daily[day]]
        boots.append(sum(values)/len(values))
    boots.sort()
    equity=peak=dd=0.0
    for day in sorted(days):
        equity+=sum(daily[day]); peak=max(peak,equity); dd=max(dd,peak-equity)
    out.writerow([scope,kind,key,len(group),len(days),sum(r['win'] for r in group),
        sum(not r['win'] for r in group),round(sum(r['win'] for r in group)/len(group),6),
        round(statistics.mean(r['p'] for r in group),6),round(statistics.mean(r['gross'] for r in group),6),
        round(statistics.mean(r['net'] for r in group),6),round(sum(r['net'] for r in group),6),
        round(boots[int(.025*len(boots))],6),round(boots[int(.975*len(boots))-1],6),
        round(dd,6),round(statistics.median(int((dt.datetime.fromisoformat(r['decision_utc'])-
              dt.datetime.fromisoformat(r['wu_price_utc'])).total_seconds()) for r in group),1),
        'price_points and Gamma-indicated winners; fee formula is a scenario; no asks/fills/official settlement'])
