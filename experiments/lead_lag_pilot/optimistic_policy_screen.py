#!/usr/bin/env python3
"""Post-hoc screen assuming observed best ask fills; NOT executable P&L."""
import collections,csv,statistics
from pathlib import Path
base=Path(__file__).resolve().parent
data={(r['city'],r['day']):r for r in csv.DictReader((base/'legacy_book_dataset.csv').open()) if r['status']=='provisional'}
predictions=collections.defaultdict(dict)
for r in csv.DictReader((base/'book_ladder_walkforward.csv').open()): predictions[(r['city'],r['day'])][r['method']]=r
events=[]
for key,models in sorted(predictions.items(),key=lambda x:(x[0][1],x[0][0])):
    if key not in data or not all(m in models for m in ('M_current','H_current','H_upper')):continue
    row=data[key]; ask=float(row['best_ask']); fee=.05*ask*(1-ask); y=int(row['outcome_gamma_yes']); events.append((key,ask,fee,y,models))
policies=[('no_trade',lambda a,f,m:False),('all',lambda a,f,m:True),('M_edge_2pp',lambda a,f,m:float(m['M_current']['p'])>a+f+.02),('H_edge_2pp',lambda a,f,m:float(m['H_current']['p'])>a+f+.02),('H_upper_edge_2pp',lambda a,f,m:float(m['H_upper']['p'])>a+f+.02)]
w=csv.writer(__import__('sys').stdout); w.writerow(['policy','eligible_city_days','calendar_dates_in_sample','hypothetical_entries','wins','losses','no_trade_city_days','mean_per_base_share','sum_scenario_one_share','maxdd_additive_one_share','assumptions'])
for name,rule in policies:
    daily=collections.defaultdict(float); entries=[]
    for (city,day),ask,fee,y,models in events:
        daily[day]+=0
        if rule(ask,fee,models):
            value=y-ask-fee; entries.append(value); daily[day]+=value
    equity=peak=drawdown=0
    for day in sorted(daily):
        equity+=daily[day]; peak=max(peak,equity); drawdown=max(drawdown,peak-equity)
    w.writerow([name,len(events),len(daily),len(entries),sum(x>0 for x in entries),sum(x<0 for x in entries),len(events)-len(entries),round(sum(entries)/len(events),5) if events else '',round(sum(entries),5),round(drawdown,5),'hypothetical fills at sampled best ask; no size or slippage; labels and availability unverified; not actual P&L'])
