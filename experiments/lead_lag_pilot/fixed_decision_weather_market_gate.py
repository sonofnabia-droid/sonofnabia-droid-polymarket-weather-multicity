#!/usr/bin/env python3
"""Unselected 15:00 local W/M/H comparison for Munich and Lucknow.

Reads historical METAR CSVs and Gamma labels already exposed in prior work.
SQLite is mode=ro/query_only. Observation time is not publication time; all
economic columns use price_points, never executable asks.
"""
import csv
import datetime as dt
import json
import math
import re
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path
from zoneinfo import ZoneInfo

BASE=Path(__file__).resolve().parent
ROOT=BASE.parents[1]
DB=sqlite3.connect(f'file:{ROOT / "data/polymarket_weather_2026.sqlite"}?mode=ro',uri=True)
DB.execute('PRAGMA query_only=ON')
pattern=re.compile(r'(-?\d+)°C(?: or (below|higher))?')
start,end='2026-03-05','2026-06-21'
weather=defaultdict(list)
for source_dir in ('historic_metar','historic'):
 for city in ('lucknow','munich'):
    with (ROOT/source_dir/f'{city}.csv').open(newline='') as f:
        for row in csv.DictReader(f):
            try:
                stamp=dt.datetime.fromisoformat(row['timestamp_utc'])
                if stamp.tzinfo is None: stamp=stamp.replace(tzinfo=dt.timezone.utc)
                else: stamp=stamp.astimezone(dt.timezone.utc)
                if '2026-03-04'<=stamp.date().isoformat()<='2026-06-22':
                    weather[(source_dir,city,stamp.astimezone(ZoneInfo('Asia/Kolkata' if city=='lucknow' else 'Europe/Berlin')).date().isoformat())].append((stamp,float(row['temp_c'])))
            except (ValueError,KeyError,TypeError):
                continue

events=DB.execute('''SELECT city,market_date,timezone FROM events
                     WHERE city IN ('lucknow','munich') AND market_date BETWEEN ? AND ?
                     AND status='found' ORDER BY market_date,city''',(start,end)).fetchall()
out=csv.writer(sys.stdout)
out.writerow(['city','day','decision_utc','status','observations_up_to_decision','last_obs_utc',
              'running_max_c','weather_bracket','wu_observations_up_to_decision','wu_last_obs_utc',
              'wu_running_max_c','wu_bracket','metar_wu_bracket_agree','market_brackets','priced_brackets',
              'price_time_span_sec','quote_age_max_sec','weather_price','weather_price_utc','weather_winner',
              'wu_price','wu_price_utc','wu_weather_winner','hybrid_wu_agree','hybrid_wu_gross_proxy',
              'market_leader','market_price','market_winner','hybrid_agree','gamma_winner',
              'w_gross_proxy','m_gross_proxy','h_gross_proxy','label_basis'])
for city,day,zone in events:
    tz=ZoneInfo(zone or ('Asia/Kolkata' if city=='lucknow' else 'Europe/Berlin'))
    decision=dt.datetime.combine(dt.date.fromisoformat(day),dt.time(15,0),tz).astimezone(dt.timezone.utc)
    obs=[x for x in weather.get(('historic_metar',city,day),[]) if x[0]<=decision]
    wu_obs=[x for x in weather.get(('historic',city,day),[]) if x[0]<=decision]
    if not obs:
        out.writerow([city,day,decision.isoformat(),'no_metar',0]); continue
    peak=max(x[1] for x in obs)
    rounded=math.floor(peak+.5)
    wu_peak=max((x[1] for x in wu_obs),default=None)
    wu_rounded=math.floor(wu_peak+.5) if wu_peak is not None else None
    markets=DB.execute('''SELECT m.bracket,m.closed,m.outcome_prices,m.raw_json,t.token_id
                          FROM markets m JOIN tokens t ON t.market_id=m.market_id
                          WHERE m.city=? AND m.market_date=? AND t.outcome='YES' ''',(city,day)).fetchall()
    if not markets:
        out.writerow([city,day,decision.isoformat(),'no_markets',len(obs),obs[-1][0].isoformat(),peak]); continue
    winners=[]; quotes=[]
    def contains(label,value):
        match=pattern.fullmatch(label or '')
        if not match or value is None:return False
        bound=int(match.group(1));side=match.group(2)
        return value<=bound if side=='below' else value>=bound if side=='higher' else value==bound
    weather_candidates=[label for label,_,_,_,_ in markets if contains(label,rounded)]
    wu_candidates=[label for label,_,_,_,_ in markets if contains(label,wu_rounded)] if wu_rounded is not None else []
    weather_label=weather_candidates[0] if len(weather_candidates)==1 else ''
    wu_label=wu_candidates[0] if len(wu_candidates)==1 else ''
    for label,closed,prices,raw,token in markets:
        try:
            meta=json.loads(raw); outcomes=meta.get('outcomes',[])
            outcomes=json.loads(outcomes) if isinstance(outcomes,str) else outcomes
            vals=json.loads(prices or '[]'); yi=next(i for i,v in enumerate(outcomes) if str(v).upper()=='YES')
            if closed and float(vals[yi])>=.999: winners.append(('__WINNER__',label))
        except (ValueError,TypeError,KeyError,IndexError,StopIteration): pass
        q=DB.execute('''SELECT ts,price FROM price_points WHERE token_id=? AND fidelity_minutes=5
                        AND ts BETWEEN ? AND ? ORDER BY ts DESC LIMIT 1''',
                     (token,int(decision.timestamp())-600,int(decision.timestamp()))).fetchone()
        if q: quotes.append((label,token,q[0],float(q[1]),label==weather_label))
    complete=len(quotes)==len(markets)
    synced=complete and max(x[2] for x in quotes)-min(x[2] for x in quotes)<=60
    leaders=[]
    if synced:
        high=max(x[3] for x in quotes); leaders=[x for x in quotes if x[3]==high]
    leader=leaders[0] if len(leaders)==1 else None
    final=[b for k,b in winners if k=='__WINNER__']
    final_label=final[0] if len(final)==1 else ''
    wquote=next((q for q in quotes if q[0]==weather_label),None)
    wu_quote=next((q for q in quotes if q[0]==wu_label),None)
    wwin=weather_label==final_label if weather_label and final_label else None
    wu_win=wu_label==final_label if wu_label and final_label else None
    mwin=leader[0]==final_label if leader and final_label else None
    agree=bool(leader and weather_label and leader[0]==weather_label)
    wu_agree=bool(leader and wu_label and leader[0]==wu_label)
    status=('ok' if synced and leader and weather_label and len(final)==1 else
            'incomplete_or_unresolved')
    out.writerow([city,day,decision.isoformat(),status,len(obs),obs[-1][0].isoformat(),peak,weather_label,
        len(wu_obs),wu_obs[-1][0].isoformat() if wu_obs else '',wu_peak if wu_peak is not None else '',wu_label,
        wu_label==weather_label if wu_label and weather_label else '',
        len(markets),len(quotes),max((x[2] for x in quotes),default=0)-min((x[2] for x in quotes),default=0),
        max((int(decision.timestamp())-x[2] for x in quotes),default=''),
        wquote[3] if wquote else '',dt.datetime.fromtimestamp(wquote[2],dt.timezone.utc).isoformat() if wquote else '',wwin,
        wu_quote[3] if wu_quote else '',dt.datetime.fromtimestamp(wu_quote[2],dt.timezone.utc).isoformat() if wu_quote else '',wu_win,wu_agree,
        (int(wu_win)-wu_quote[3]) if wu_agree and wu_win is not None and wu_quote else 0 if not wu_agree else '',
        leader[0] if leader else '',leader[3] if leader else '',mwin,agree,final_label,
        (int(wwin)-wquote[3]) if wwin is not None and wquote else '',
        (int(mwin)-leader[3]) if mwin is not None and leader else '',
        (int(mwin)-leader[3]) if agree and mwin is not None and leader else 0 if not agree else '',
        'archived Gamma closed YES; not independently settled'])
DB.close()
