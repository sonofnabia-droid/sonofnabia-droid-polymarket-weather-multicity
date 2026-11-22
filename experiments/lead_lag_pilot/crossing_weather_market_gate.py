#!/usr/bin/env python3
"""Exploratory W/M/H decision comparison at historical new-max crossings.

W predicts the bracket containing the newly observed maximum. M predicts the
historical-price leader. H abstains unless W and M agree. Archived Gamma labels
were previously inspected; results are not independent validation or P&L.
"""
import csv
import random
import re
import sqlite3
import statistics
from collections import defaultdict
from pathlib import Path

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[1]
DB = sqlite3.connect(f'file:{ROOT / "data/polymarket_weather_2026.sqlite"}?mode=ro', uri=True)
DB.execute('PRAGMA query_only=ON')
markets_cache = {}
bracket_re = re.compile(r'(-?\d+)°C(?: or (below|higher))?')

crossings = {}
for row in csv.DictReader((BASE / 'all_crossings.csv').open(newline='')):
    key = row['city'], row['day'], row['obs_utc']
    crossings.setdefault(key, row)
market_rows = list(csv.DictReader((BASE / 'anticipation.csv').open(newline='')))
out = csv.writer(__import__('sys').stdout)
out.writerow(['city_scope','offset_min','valid_events','local_days','weather_accuracy',
              'market_accuracy','hybrid_agreement_events','hybrid_coverage',
              'hybrid_accuracy','market_accuracy_on_agreement','median_market_leader_price_on_agreement',
              'market_mean_price','market_gross_proxy_per_trade','hybrid_gross_proxy_per_trade',
              'hybrid_gross_proxy_per_opportunity','hybrid_minus_market_per_opportunity',
              'bootstrap95_diff_low','bootstrap95_diff_high','note'])

for offset in (0, 10, 30):
    merged = []
    for market in market_rows:
        if int(market['offset_min']) != offset or market['status'] != 'ok':
            continue
        key = market['city'], market['day'], market['obs_utc']
        event = crossings.get(key)
        if not event:
            continue
        try:
            temp = int(float(event['temp']))
            if float(event['temp']) != temp:
                continue
        except (ValueError, TypeError):
            continue
        if key not in markets_cache:
            rows = DB.execute('''SELECT m.bracket,t.outcome,t.token_id
                                 FROM markets m JOIN tokens t ON t.market_id=m.market_id
                                 WHERE m.city=? AND m.market_date=? AND t.outcome='YES' ''',
                              (key[0], key[1])).fetchall()
            markets_cache[key] = rows
        candidates = []
        for label, _, _ in markets_cache[key]:
            match = bracket_re.fullmatch(label or '')
            if not match:
                continue
            bound, suffix = int(match.group(1)), match.group(2)
            if suffix == 'below' and temp <= bound:
                candidates.append(label)
            elif suffix == 'higher' and temp >= bound:
                candidates.append(label)
            elif suffix is None and temp == bound:
                candidates.append(label)
        if len(candidates) != 1:
            continue
        weather = candidates[0]
        merged.append({'city':key[0], 'day':key[1], 'weather':weather,
                       'market':market['leader'], 'winner':market['winner'],
                       'price':float(market['leader_price'])})

    for scope in ('all','lucknow','munich'):
        sample = [r for r in merged if scope == 'all' or r['city'] == scope]
        agreements = [r for r in sample if r['weather'] == r['market']]
        n = len(sample)
        market_returns = [float(r['market'] == r['winner'])-r['price'] for r in sample]
        hybrid_returns = [float(r['weather'] == r['market'] and r['market'] == r['winner'])-r['price']
                          if r['weather'] == r['market'] else 0.0 for r in sample]
        hybrid_trade_returns = [float(r['market'] == r['winner'])-r['price'] for r in agreements]
        by_day = defaultdict(list)
        for row, mr, hr in zip(sample, market_returns, hybrid_returns):
            by_day[row['day']].append((mr,hr))
        rng = random.Random(15112026+offset+(0 if scope=='all' else (1 if scope=='lucknow' else 2)))
        days = list(by_day.values())
        boots = []
        for _ in range(5000):
            draw = [rng.choice(days) for _ in days]
            n_draw = sum(len(day) for day in draw)
            boots.append(sum(h-m for day in draw for m,h in day)/n_draw)
        boots.sort()
        diff = sum(h-m for day in days for m,h in day)/n if n else 0
        out.writerow([scope,offset,n,len({r['day'] for r in sample}),
                      round(sum(r['weather']==r['winner'] for r in sample)/n,6) if n else '',
                      round(sum(r['market']==r['winner'] for r in sample)/n,6) if n else '',
                      len(agreements),round(len(agreements)/n,6) if n else '',
                      round(sum(r['weather']==r['winner'] for r in agreements)/len(agreements),6) if agreements else '',
                      round(sum(r['market']==r['winner'] for r in agreements)/len(agreements),6) if agreements else '',
                      round(sorted(r['price'] for r in agreements)[len(agreements)//2],6) if agreements else '',
                      round(statistics.mean(r['price'] for r in sample),6) if sample else '',
                      round(statistics.mean(market_returns),6) if sample else '',
                      round(statistics.mean(hybrid_trade_returns),6) if hybrid_trade_returns else '',
                      round(statistics.mean(hybrid_returns),6) if sample else '',round(diff,6) if sample else '',
                      round(boots[int(.025*len(boots))],6) if boots else '',
                      round(boots[int(.975*len(boots))-1],6) if boots else '',
                      'gross proxy uses historical price_points and archived Gamma winner; no asks, fees, fills, or official label audit'])
DB.close()
