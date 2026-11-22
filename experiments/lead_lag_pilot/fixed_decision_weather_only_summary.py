#!/usr/bin/env python3
"""Coverage sensitivity of WU/METAR-only 15:00 price-point policies."""
import csv
import datetime as dt
import random
import statistics
from collections import defaultdict
from pathlib import Path

BASE=Path(__file__).resolve().parent
rows=list(csv.DictReader((BASE/'fixed_decision_weather_market_gate.csv').open(newline='')))
out=csv.writer(__import__('sys').stdout)
out.writerow(['city_scope','all_city_days','source','quoted_labeled_days','coverage_all_days',
              'quoted_days_full_ladder','coverage_of_full_ladder','median_quote_age_sec',
              'hit_rate','mean_pricepoint','gross_proxy_per_trade','fee_scenario_net_per_trade',
              'gross_proxy_per_all_days_missing_zero','fee_net_per_all_days_missing_zero',
              'local_dates','bootstrap95_fee_net_low','bootstrap95_fee_net_high',
              'maxdd_fee_net_additive_daily',
              'note'])
for scope in ('all','lucknow','munich'):
    universe=[r for r in rows if scope=='all' or r['city']==scope]
    for source,price_col,time_col,win_col in [
        ('METAR','weather_price','weather_price_utc','weather_winner'),
        ('WU','wu_price','wu_price_utc','wu_weather_winner')]:
        sample=[r for r in universe if r[price_col] and r[win_col] in ('True','False') and r[time_col]]
        gross=[float(r[win_col]=='True')-float(r[price_col]) for r in sample]
        fee=[.05*float(r[price_col])*(1-float(r[price_col])) for r in sample]
        daily=defaultdict(list)
        for g,f,r in zip(gross,fee,sample): daily[r['day']].append(g-f)
        daykeys=sorted(daily)
        rng=random.Random(15112026+(0 if scope=='all' else 1 if scope=='lucknow' else 2)+(0 if source=='WU' else 11))
        boots=[]
        for _ in range(5000):
            draw=[rng.choice(daykeys) for _ in daykeys]
            vals=[value for day in draw for value in daily[day]]
            boots.append(sum(vals)/len(vals))
        boots.sort()
        equity=peak=drawdown=0.0
        for day in daykeys:
            equity+=sum(daily[day]); peak=max(peak,equity); drawdown=max(drawdown,peak-equity)
        ages=[int((dt.datetime.fromisoformat(r['decision_utc'])-
                   dt.datetime.fromisoformat(r[time_col])).total_seconds()) for r in sample]
        full=[r for r in sample if r['status']=='ok']
        out.writerow([scope,len(universe),source,len(sample),round(len(sample)/len(universe),6) if universe else '',
            len(full),round(len(full)/sum(r['status']=='ok' for r in universe),6) if any(r['status']=='ok' for r in universe) else '',
            round(statistics.median(ages),1) if ages else '',
            round(sum(r[win_col]=='True' for r in sample)/len(sample),6) if sample else '',
            round(statistics.mean(float(r[price_col]) for r in sample),6) if sample else '',
            round(statistics.mean(gross),6) if sample else '',
            round(statistics.mean(g-f for g,f in zip(gross,fee)),6) if sample else '',
            round(sum(gross)/len(universe),6) if universe else '',
            round(sum(g-f for g,f in zip(gross,fee))/len(universe),6) if universe else '',
            len(daykeys),round(boots[int(.025*len(boots))],6) if boots else '',
            round(boots[int(.975*len(boots))-1],6) if boots else '',round(drawdown,6),
            'historical price_points, Gamma-indicated winner; quote age to 15:00; not asks/fills; missing quotes set to zero only in all-days policy yield'])
