#!/usr/bin/env python3
"""Post-hoc PAPER entry filtering, identical reconciled base; no policy approval."""
import collections,csv,statistics
from pathlib import Path
base=Path(__file__).resolve().parent
rows=[r for r in csv.DictReader((base/'paper_filter_study.csv').open()) if r['bot']=='A' and r['context']=='complete' and r['result_for_research'] in ('won','lost') and r['paper_price']]
rules=[('all_entries',lambda r:True),('target_market_leader',lambda r:r['target_is_leader']=='True'),('higher_brackets_sum_below_0.50',lambda r:float(r['above_target_price_sum'])<.5)]
w=csv.writer(__import__('sys').stdout); w.writerow(['city','rule','base_entries','kept','wins','losses','excluded_wins','excluded_losses','mean_indicative_per_share','mean_fee_scenario_per_share','maxdd_additive_per_share','days_no_trade_in_base'])
for city in ('lucknow','munich','both'):
    base_rows=sorted([r for r in rows if city=='both' or r['city']==city],key=lambda x:(x['day'],x['timestamp_utc'],x['city']))
    for name,rule in rules:
        kept=[r for r in base_rows if rule(r)]; removed=[r for r in base_rows if not rule(r)]
        gross=[(1 if r['result_for_research']=='won' else 0)-float(r['paper_price']) for r in kept]
        # Scenario used by project backtester; actual fees/fills are not established.
        net=[g-.05*float(r['paper_price'])*(1-float(r['paper_price'])) for g,r in zip(gross,kept)]
        # Additive one share per entry, aggregated by local calendar date; not account equity.
        daily=collections.defaultdict(float)
        for r,n in zip(kept,net):daily[r['day']]+=n
        equity=peak=drawdown=0
        for day in sorted(daily):
            equity+=daily[day]; peak=max(peak,equity); drawdown=max(drawdown,peak-equity)
        w.writerow([city,name,len(base_rows),len(kept),sum(r['result_for_research']=='won' for r in kept),sum(r['result_for_research']=='lost' for r in kept),sum(r['result_for_research']=='won' for r in removed),sum(r['result_for_research']=='lost' for r in removed),round(statistics.mean(gross),4) if gross else '',round(statistics.mean(net),4) if net else '',round(drawdown,4),len({r['day'] for r in base_rows}-{r['day'] for r in kept})])
