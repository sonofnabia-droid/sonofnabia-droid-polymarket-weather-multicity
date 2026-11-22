#!/usr/bin/env python3
"""Summarize retrospective price-leader accuracy around METAR crossings."""
import csv
import statistics
from pathlib import Path

BASE = Path(__file__).resolve().parent
rows = list(csv.DictReader((BASE / 'anticipation.csv').open(newline='')))
out = csv.writer(__import__('sys').stdout)
out.writerow(['city_scope','offset_min','ok_events','local_days','leader_winner_fraction',
              'median_final_winner_price','median_market_leader_price',
              'mean_final_winner_price','n_crossing_events_total'])
for offset in (-10,0,10,30):
    for city in ('all','lucknow','munich'):
        sample = [r for r in rows if int(r['offset_min']) == offset and r['status'] == 'ok'
                  and (city == 'all' or r['city'] == city)]
        total = [r for r in rows if int(r['offset_min']) == offset
                 and (city == 'all' or r['city'] == city)]
        out.writerow([city,offset,len(sample),
                      len({r['day'] for r in sample}),
                      round(sum(r['winner_is_leader'] == 'True' for r in sample)/len(sample),6) if sample else '',
                      round(statistics.median(float(r['winner_price']) for r in sample),6) if sample else '',
                      round(statistics.median(float(r['leader_price']) for r in sample),6) if sample else '',
                      round(statistics.mean(float(r['winner_price']) for r in sample),6) if sample else '',
                      len(total)])
