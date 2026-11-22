#!/usr/bin/env python3
"""W/M/H rank comparison with complete, timestamp-synchronized price ladders.

Exploratory retrospective sample only. Gamma winner labels were previously
inspected; market prices are not executable asks or proven available to a bot.
"""
import csv
import datetime as dt
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
bracket_re = re.compile(r'(-?\d+)°C(?: or (below|higher))?')
crossings = {}
for row in csv.DictReader((BASE / 'all_crossings.csv').open(newline='')):
    crossings.setdefault((row['city'],row['day'],row['obs_utc']),row)
events = {}
for row in csv.DictReader((BASE / 'anticipation.csv').open(newline='')):
    events[(row['city'],row['day'],row['obs_utc'],int(row['offset_min']))] = row
market_cache = {}
quotes_cache = {}
merged = []

def bracket_contains(label, value):
    m = bracket_re.fullmatch(label or '')
    if not m: return False
    bound, side = int(m.group(1)), m.group(2)
    return value <= bound if side == 'below' else value >= bound if side == 'higher' else value == bound

for (city,day,obs,offset), archived in events.items():
    if archived['status'] != 'ok' or (city,day,obs) not in crossings:
        continue
    key=(city,day)
    if key not in market_cache:
        market_cache[key]=DB.execute('''SELECT m.bracket,t.token_id
                                        FROM markets m JOIN tokens t ON t.market_id=m.market_id
                                        WHERE m.city=? AND m.market_date=? AND t.outcome='YES' ''',key).fetchall()
    try:
        temperature=float(crossings[(city,day,obs)]['temp'])
        if not temperature.is_integer(): continue
    except (ValueError,TypeError):
        continue
    w_brackets=[label for label,token in market_cache[key] if bracket_contains(label,int(temperature))]
    if len(w_brackets)!=1: continue
    cutoff=int(dt.datetime.fromisoformat(obs).timestamp())+offset*60
    priced=[]
    for label,token in market_cache[key]:
        if (token,cutoff) not in quotes_cache:
            quotes_cache[(token,cutoff)]=DB.execute('''SELECT ts,price FROM price_points
                WHERE token_id=? AND fidelity_minutes=5 AND ts BETWEEN ? AND ?
                ORDER BY ts DESC LIMIT 1''',(token,cutoff-600,cutoff)).fetchone()
        quote=quotes_cache[(token,cutoff)]
        if quote: priced.append((label,token,quote[0],float(quote[1])))
    if len(priced)!=len(market_cache[key]) or not priced: continue
    times=[r[2] for r in priced]
    if max(times)-min(times)>60: continue
    high=max(r[3] for r in priced); leaders=[r[0] for r in priced if r[3]==high]
    if len(leaders)!=1: continue
    merged.append({'city':city,'day':day,'offset':offset,'weather':w_brackets[0],
                   'market':leaders[0],'winner':archived['winner'],'price':high,
                   'actual_min':(statistics.median(times)-dt.datetime.fromisoformat(obs).timestamp())/60,
                   'n_market':len(priced),'skew_sec':max(times)-min(times)})

out=csv.writer(__import__('sys').stdout)
out.writerow(['city_scope','offset_min','valid_sync_events','local_days','median_actual_quote_min_after_obs',
              'max_ladder_skew_sec','weather_accuracy','market_accuracy','hybrid_events','hybrid_coverage',
              'hybrid_accuracy','market_mean_price','market_gross_proxy_per_trade',
              'hybrid_gross_proxy_per_trade','hybrid_gross_proxy_per_opportunity',
              'hybrid_minus_market_per_opportunity','bootstrap95_diff_low','bootstrap95_diff_high',
              'note'])
for offset in (0,10,30):
    for scope in ('all','lucknow','munich'):
        sample=[r for r in merged if r['offset']==offset and (scope=='all' or r['city']==scope)]
        agree=[r for r in sample if r['weather']==r['market']]
        n=len(sample); mret=[float(r['market']==r['winner'])-r['price'] for r in sample]
        hret=[(float(r['market']==r['winner'])-r['price']) if r['weather']==r['market'] else 0.0 for r in sample]
        by_day=defaultdict(list)
        for r,m,h in zip(sample,mret,hret): by_day[r['day']].append((m,h))
        groups=list(by_day.values()); rng=random.Random(15112026+offset+(0 if scope=='all' else 1 if scope=='lucknow' else 2)); boots=[]
        for _ in range(5000):
            draw=[rng.choice(groups) for _ in groups]; nd=sum(len(g) for g in draw)
            boots.append(sum(h-m for g in draw for m,h in g)/nd)
        boots.sort(); htrade=[float(r['market']==r['winner'])-r['price'] for r in agree]
        diff=sum(h-m for g in groups for m,h in g)/n if n else ''
        out.writerow([scope,offset,n,len(by_day),
                      round(statistics.median(r['actual_min'] for r in sample),3) if sample else '',
                      max(r['skew_sec'] for r in sample) if sample else '',
                      round(sum(r['weather']==r['winner'] for r in sample)/n,6) if n else '',
                      round(sum(r['market']==r['winner'] for r in sample)/n,6) if n else '',
                      len(agree),round(len(agree)/n,6) if n else '',
                      round(sum(r['market']==r['winner'] for r in agree)/len(agree),6) if agree else '',
                      round(statistics.mean(r['price'] for r in sample),6) if sample else '',
                      round(statistics.mean(mret),6) if sample else '',
                      round(statistics.mean(htrade),6) if htrade else '',
                      round(statistics.mean(hret),6) if sample else '',round(diff,6) if n else '',
                      round(boots[int(.025*len(boots))],6) if boots else '',
                      round(boots[int(.975*len(boots))-1],6) if boots else '',
                      'complete YES ladder, timestamps span <=60s; historical prices/Gamma outcomes, no asks or fills'])
DB.close()
