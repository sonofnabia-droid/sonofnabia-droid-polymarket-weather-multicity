#!/usr/bin/env python3
"""Illustrative fixed ask band and model edge; not Cassiopeia replay."""
import collections,csv
from pathlib import Path
base=Path(__file__).resolve().parent; data={(r['city'],r['day']):r for r in csv.DictReader((base/'legacy_book_dataset.csv').open()) if r['status']=='provisional'}; pred=collections.defaultdict(dict)
for r in csv.DictReader((base/'book_ladder_walkforward.csv').open()):pred[(r['city'],r['day'])][r['method']]=r
events=[]
for key,models in sorted(pred.items(),key=lambda x:(x[0][1],x[0][0])):
    if key in data and all(m in models for m in ('M_current','H_current','H_upper')):events.append((key,data[key],models))
w=csv.writer(__import__('sys').stdout); w.writerow(['policy','sample_city_days','band_opportunities','hypothetical_entries','wins','losses','sum_scenario_one_share','mean_per_band_opportunity','maxdd_additive','note'])
band_events=[event for event in events if .75<=float(event[1]['best_ask'])<=.90]
for policy in ('band_only','band_M_edge_2pp','band_H_edge_2pp','band_H_upper_edge_2pp'):
    daily=collections.defaultdict(float); values=[]
    for (city,day),r,models in band_events:
        daily[day]+=0; ask=float(r['best_ask']); fee=.05*ask*(1-ask); method={'band_M_edge_2pp':'M_current','band_H_edge_2pp':'H_current','band_H_upper_edge_2pp':'H_upper'}.get(policy)
        if method and float(models[method]['p'])<=ask+fee+.02:continue
        value=int(r['outcome_gamma_yes'])-ask-fee; values.append(value); daily[day]+=value
    balance=peak=dd=0
    for day in sorted(daily):balance+=daily[day]; peak=max(peak,balance); dd=max(dd,peak-balance)
    w.writerow([policy,len(events),len(band_events),len(values),sum(x>0 for x in values),sum(x<0 for x in values),round(sum(values),5),round(sum(values)/len(band_events),5) if band_events else '',round(dd,5),'retrospective fixed band; assumes fill at sampled ask; fee scenario; not bot replay or actual P&L'])
