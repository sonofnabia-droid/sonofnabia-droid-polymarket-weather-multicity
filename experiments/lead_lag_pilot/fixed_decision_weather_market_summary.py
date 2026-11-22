#!/usr/bin/env python3
"""Daily-cluster summary for the fixed 15:00 exploratory W/M/H pilot."""
import csv
import random
import statistics
from collections import defaultdict
from pathlib import Path

BASE=Path(__file__).resolve().parent
rows=list(csv.DictReader((BASE/'fixed_decision_weather_market_gate.csv').open(newline='')))
out=csv.writer(__import__('sys').stdout)
out.writerow(['city_scope','valid_market_city_days','local_dates','all_labeled_city_days',
              'metar_wu_bracket_match_fraction_all','metar_accuracy_all','wu_accuracy_all',
              'metar_accuracy_selected','wu_accuracy_selected','market_accuracy',
              'hybrid_metar_trades','hybrid_metar_coverage',
              'hybrid_metar_accuracy','hybrid_metar_proxy_per_opportunity','hybrid_wu_trades',
              'wu_valid_intersection_city_days','hybrid_wu_coverage','hybrid_wu_accuracy','wu_proxy_per_opportunity',
              'hybrid_wu_proxy_per_opportunity','hybrid_wu_minus_market_per_opportunity',
              'bootstrap95_wu_minus_market_low','bootstrap95_wu_minus_market_high',
              'market_proxy_per_opportunity','market_proxy_on_wu_intersection',
              'hybrid_market_proxy_per_opportunity',
              'market_fee_scenario_net_on_wu_intersection','wu_fee_scenario_net_per_opportunity',
              'hybrid_wu_fee_scenario_net_per_opportunity','hybrid_wu_fee_net_minus_market',
              'bootstrap95_fee_net_diff_low','bootstrap95_fee_net_diff_high',
              'hybrid_metar_proxy_per_trade','hybrid_wu_proxy_per_trade',
              'market_median_price','hybrid_wu_median_price','maxdd_market_additive_daily',
              'maxdd_wu_additive_daily','maxdd_hybrid_wu_additive_daily',
              'note'])
for scope in ('all','lucknow','munich'):
    all_rows=[r for r in rows if scope=='all' or r['city']==scope]
    metar_all=[r for r in all_rows if r['weather_winner'] in ('True','False')]
    wu_all=[r for r in all_rows if r['wu_weather_winner'] in ('True','False')]
    sample=[r for r in all_rows if r['status']=='ok']
    wu_sample=[r for r in sample if r['wu_bracket'] and r['wu_weather_winner'] in ('True','False') and r['wu_price']]
    h=[r for r in sample if r['hybrid_agree']=='True']
    hwu=[r for r in wu_sample if r['hybrid_wu_agree']=='True']
    n=len(sample)
    wret=[float(r['w_gross_proxy']) for r in sample]
    mret=[float(r['m_gross_proxy']) for r in sample]
    hret=[float(r['h_gross_proxy']) for r in sample]
    wuret=[float(r['wu_weather_winner']=='True')-float(r['wu_price']) for r in wu_sample]
    hwuret=[(float(r['wu_weather_winner']=='True')-float(r['wu_price'])) if r['hybrid_wu_agree']=='True' else 0.0 for r in wu_sample]
    fee=lambda p:.05*p*(1-p)
    wu_net=[gross-fee(float(r['wu_price'])) for gross,r in zip(wuret,wu_sample)]
    market_net=[float(r['m_gross_proxy'])-fee(float(r['market_price'])) for r in wu_sample]
    hwu_net=[(float(r['market_winner']=='True')-float(r['market_price'])-
              fee(float(r['market_price']))) if r['hybrid_wu_agree']=='True' else 0.0 for r in wu_sample]
    daily=defaultdict(list); daily_net=defaultdict(list)
    for r in wu_sample:
        mv=float(r['m_gross_proxy'])
        hv=(float(r['market_winner']=='True')-float(r['market_price'])) if r['hybrid_wu_agree']=='True' else 0.0
        daily[r['day']].append((mv,hv,float(r['wu_weather_winner']=='True')-float(r['wu_price'])))
        mnet=mv-fee(float(r['market_price']))
        hnet=(float(r['market_winner']=='True')-float(r['market_price'])-fee(float(r['market_price']))) if r['hybrid_wu_agree']=='True' else 0.0
        daily_net[r['day']].append((mnet,hnet))
    daykeys=sorted(daily)
    rng=random.Random(15112026+(0 if scope=='all' else 1 if scope=='lucknow' else 2))
    boots=[]
    groups=[daily[d] for d in daykeys]
    for _ in range(5000):
        draw=[rng.choice(groups) for _ in groups]
        nd=sum(len(g) for g in draw)
        boots.append(sum(hv-mv for g in draw for mv,hv,_ in g)/nd)
    boots.sort()
    boots_net=[]
    for _ in range(5000):
        draw=[rng.choice([daily_net[d] for d in daykeys]) for _ in daykeys]
        nd=sum(len(g) for g in draw)
        boots_net.append(sum(hv-mv for g in draw for mv,hv in g)/nd)
    boots_net.sort()
    def maxdd(index):
        daily_ret=[sum(x[index] for x in daily[d]) for d in daykeys]
        equity=peak=dd=0.0
        for value in daily_ret:
            equity+=value; peak=max(peak,equity); dd=max(dd,peak-equity)
        return dd
    out.writerow([scope,n,len({r['day'] for r in sample}),
       len(metar_all),
       round(sum(r['metar_wu_bracket_agree']=='True' for r in all_rows if r['metar_wu_bracket_agree'] in ('True','False'))/
             sum(r['metar_wu_bracket_agree'] in ('True','False') for r in all_rows),6) if any(r['metar_wu_bracket_agree'] in ('True','False') for r in all_rows) else '',
       round(sum(r['weather_winner']=='True' for r in metar_all)/len(metar_all),6) if metar_all else '',
       round(sum(r['wu_weather_winner']=='True' for r in wu_all)/len(wu_all),6) if wu_all else '',
       round(sum(r['weather_winner']=='True' for r in sample)/n,6) if n else '',
       round(sum(r['wu_weather_winner']=='True' for r in wu_sample)/len(wu_sample),6) if wu_sample else '',
       round(sum(r['market_winner']=='True' for r in sample)/n,6) if n else '',len(h),
       round(len(h)/n,6) if n else '',round(sum(r['market_winner']=='True' for r in h)/len(h),6) if h else '',
       round(statistics.mean(hret),6) if n else '',len(hwu),round(len(hwu)/len(wu_sample),6) if wu_sample else '',
       len(wu_sample),round(len(hwu)/len(wu_sample),6) if wu_sample else '',
       round(sum(r['market_winner']=='True' for r in hwu)/len(hwu),6) if hwu else '',
       round(statistics.mean(wuret),6) if wuret else '',round(statistics.mean(hwuret),6) if hwuret else '',
       round(statistics.mean(hwuret)-statistics.mean([float(r['m_gross_proxy']) for r in wu_sample]),6) if wu_sample else '',
       round(boots[int(.025*len(boots))],6) if boots else '',
       round(boots[int(.975*len(boots))-1],6) if boots else '',
       round(statistics.mean(mret),6) if n else '',
       round(statistics.mean(float(r['m_gross_proxy']) for r in wu_sample),6) if wu_sample else '',
       round(statistics.mean(hret),6) if n else '',
       round(statistics.mean(market_net),6) if market_net else '',
       round(statistics.mean(wu_net),6) if wu_net else '',
       round(statistics.mean(hwu_net),6) if hwu_net else '',
       round(statistics.mean(hwu_net)-statistics.mean(market_net),6) if market_net else '',
       round(boots_net[int(.025*len(boots_net))],6) if boots_net else '',
       round(boots_net[int(.975*len(boots_net))-1],6) if boots_net else '',
       round(statistics.mean(float(r['market_winner']=='True')-float(r['market_price']) for r in h),6) if h else '',
       round(statistics.mean(float(r['market_winner']=='True')-float(r['market_price']) for r in hwu),6) if hwu else '',
       round(statistics.median(float(r['market_price']) for r in sample),6) if n else '',
       round(statistics.median(float(r['market_price']) for r in hwu),6) if hwu else '',
       round(maxdd(0),6) if daily else '',round(maxdd(2),6) if daily else '',round(maxdd(1),6) if daily else '',
       'one share per valid WU/market city-day; Gamma labels and historical price_points; no fees/fills; not official settlement'])
