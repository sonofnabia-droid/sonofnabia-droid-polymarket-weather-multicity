#!/usr/bin/env python3
"""Descriptive city and clustered-day bootstrap for market baseline."""
import collections,csv,random,statistics
from pathlib import Path
p=Path(__file__).resolve().parent
files=[('early',p/'market_baseline_2026-03-05_16.csv'),('later',p/'market_baseline_2026-03-17_04-30.csv')]
rows=[]
for period,path in files:
    for r in csv.DictReader(path.open()): r['period']=period; rows.append(r)
w=csv.writer(__import__('sys').stdout); w.writerow(['period','hour','city','eligible','incomplete','wins','mean_price','mean_win_minus_price'])
for period in ('early','later'):
    for hour in ('12','15'):
        for city in sorted({r['city'] for r in rows if r['period']==period}):
            subset=[r for r in rows if r['period']==period and r['hour_local']==hour and r['city']==city]
            good=[r for r in subset if r['status']=='exploratory']; missing=sum(r['status']=='incomplete_prices' for r in subset)
            if not subset: continue
            mean=lambda vals:round(statistics.mean(vals),4) if vals else ''
            w.writerow([period,hour,city,len(good),missing,sum(r['leader_won']=='True' for r in good),mean([float(r['leader_price']) for r in good]),mean([int(r['leader_won']=='True')-float(r['leader_price']) for r in good])])
for period in ('early','later'):
    for hour in ('12','15'):
        good=[r for r in rows if r['period']==period and r['hour_local']==hour and r['status']=='exploratory']
        byday=collections.defaultdict(list)
        for r in good: byday[r['day']].append(int(r['leader_won']=='True')-float(r['leader_price']))
        days=sorted(byday); rng=random.Random(20261115); boots=[]
        if not days: continue
        for _ in range(5000):
            sample=[rng.choice(days) for _ in days]; vals=[v for day in sample for v in byday[day]]; boots.append(statistics.mean(vals))
        boots.sort(); print(f'# {period} {hour} days={len(days)} n={len(good)} day_bootstrap_95=[{boots[124]:.4f},{boots[4874]:.4f}]')
