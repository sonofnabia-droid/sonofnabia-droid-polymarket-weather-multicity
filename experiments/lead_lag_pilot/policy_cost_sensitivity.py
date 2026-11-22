#!/usr/bin/env python3
"""Illustrative ask/slippage scenarios; quotes do not guarantee fills."""
import collections,csv
from pathlib import Path
base=Path(__file__).resolve().parent
data={(r['city'],r['day']):r for r in csv.DictReader((base/'legacy_book_dataset.csv').open()) if r['status']=='provisional'}; predictions=collections.defaultdict(dict)
for r in csv.DictReader((base/'book_ladder_walkforward.csv').open()):predictions[(r['city'],r['day'])][r['method']]=r
events=[]
for key,models in sorted(predictions.items(),key=lambda x:(x[0][1],x[0][0])):
    if key in data and all(k in models for k in ('M_current','H_current','H_upper')):events.append((key,data[key],models))
w=csv.writer(__import__('sys').stdout); w.writerow(['policy','assumed_slippage','base_events','hypothetical_fills','wins','losses','sum_scenario_one_share','mean_per_base_share','maxdd_additive_one_share'])
for slip in (0,.01,.03):
    for policy in ('all','M_current','H_current','H_upper'):
        daily=collections.defaultdict(float); results=[]
        for (city,day),row,models in events:
            daily[day]+=0; ask=float(row['best_ask']); hypothetical=ask+slip
            if hypothetical>=1:continue
            fee=.05*hypothetical*(1-hypothetical)
            if policy!='all' and float(models[policy]['p'])<=hypothetical+fee+.02:continue
            value=int(row['outcome_gamma_yes'])-hypothetical-fee; results.append(value); daily[day]+=value
        balance=peak=dd=0
        for day in sorted(daily):balance+=daily[day]; peak=max(peak,balance); dd=max(dd,peak-balance)
        w.writerow([policy,slip,len(events),len(results),sum(x>0 for x in results),sum(x<0 for x in results),round(sum(results),5),round(sum(results)/len(events),5) if events else '',round(dd,5)])
