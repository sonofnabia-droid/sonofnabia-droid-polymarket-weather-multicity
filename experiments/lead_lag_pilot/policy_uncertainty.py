#!/usr/bin/env python3
"""Date-block bootstrap of post-hoc optimistic policy vs all entries."""
import collections,csv,random,statistics
from pathlib import Path
base=Path(__file__).resolve().parent
data={(r['city'],r['day']):r for r in csv.DictReader((base/'legacy_book_dataset.csv').open()) if r['status']=='provisional'}; pred=collections.defaultdict(dict)
for r in csv.DictReader((base/'book_ladder_walkforward.csv').open()):pred[(r['city'],r['day'])][r['method']]=r
w=csv.writer(__import__('sys').stdout); w.writerow(['policy','slippage','dates','base_city_days','delta_total','boot_low','boot_high'])
for slip in (0,.01,.03):
    for policy in ('M_current','H_current','H_upper'):
        byday=collections.defaultdict(float); n=0
        for key,models in pred.items():
            if key not in data or policy not in models:continue
            city,day=key; row=data[key]; p=float(row['best_ask'])+slip; byday[day]+=0; n+=1
            if p>=1:continue
            fee=.05*p*(1-p); value=int(row['outcome_gamma_yes'])-p-fee
            if float(models[policy]['p'])<=p+fee+.02:byday[day]-=value
        days=sorted(byday); rng=random.Random(20261115); vals=[byday[d] for d in days]; boots=sorted(sum(rng.choices(vals,k=len(vals))) for _ in range(5000))
        w.writerow([policy,slip,len(days),n,round(sum(vals),5),round(boots[124],5),round(boots[4874],5)])
