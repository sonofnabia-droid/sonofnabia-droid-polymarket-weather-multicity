#!/usr/bin/env python3
"""Target-vs-next-live-bracket event study around METAR crossings.

Uses price_points only, not outcomes. Quotes must be <=6 minutes old at the
nominal cut and target/control timestamps must differ by <=60 seconds.
"""
import csv
import datetime as dt
import re
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[1]
DB = sqlite3.connect(f'file:{ROOT / "data/polymarket_weather_2026.sqlite"}?mode=ro', uri=True)
DB.execute('PRAGMA query_only=ON')
label_re = re.compile(r'(-?\d+)°C(?: or (below|higher))?')
events = list(csv.DictReader((BASE / 'all_crossings.csv').open(newline='')))
token_cache = {}
quote_cache = {}
cuts = (-15,-10,-5,0,5,10,15,30)
output = csv.writer(sys.stdout)
output.writerow(['city','day','obs_utc','target_bracket','next_live_bracket','offset_min',
                 'target_price','target_price_utc','control_price','control_price_utc',
                 'target_minus_control','target_delta_from_m15','control_delta_from_m15',
                 'delta_difference_from_m15','target_age_sec','control_age_sec',
                 'pair_skew_sec','status'])

def get_quote(token, cutoff):
    key=(token,cutoff)
    if key not in quote_cache:
        quote_cache[key]=DB.execute('''SELECT ts,price FROM price_points
            WHERE token_id=? AND fidelity_minutes=5 AND ts BETWEEN ? AND ?
            ORDER BY ts DESC LIMIT 1''',(token,cutoff-360,cutoff)).fetchone()
    return quote_cache[key]

for event in events:
    city,day=event['city'],event['day']; target=event['bracket']
    m=label_re.fullmatch(target or '')
    if not m: continue
    upper=int(m.group(1)); next_label=''
    if (city,day) not in token_cache:
        rows=DB.execute('''SELECT m.bracket,t.token_id FROM markets m JOIN tokens t
                           ON t.market_id=m.market_id WHERE m.city=? AND m.market_date=?
                           AND t.outcome='YES' ''',(city,day)).fetchall()
        token_cache[(city,day)]={name:token for name,token in rows}
    tokens=token_cache[(city,day)]
    candidates=[]
    for label in tokens:
        b=label_re.fullmatch(label or '')
        if b and b.group(2)!='higher' and int(b.group(1))>upper:
            candidates.append((int(b.group(1)),label))
    if not candidates: continue
    next_label=min(candidates)[1]
    tt,ct=tokens.get(target),tokens.get(next_label)
    if not tt or not ct: continue
    obs=int(dt.datetime.fromisoformat(event['obs_utc']).timestamp())
    points={}
    for offset in cuts:
        cutoff=obs+offset*60; tq=get_quote(tt,cutoff); cq=get_quote(ct,cutoff)
        if tq and cq and abs(tq[0]-cq[0])<=60:
            points[offset]=(cutoff,tq,cq)
    base=points.get(-15)
    for offset in cuts:
        item=points.get(offset)
        if not item:
            output.writerow([city,day,event['obs_utc'],target,next_label,offset,*(['']*11),'missing_or_unsynchronized'])
            continue
        cutoff,tq,cq=item
        target_base=base[1][1] if base else None
        control_base=base[2][1] if base else None
        tdelta=tq[1]-target_base if target_base is not None else None
        cdelta=cq[1]-control_base if control_base is not None else None
        paired=tdelta-cdelta if tdelta is not None and cdelta is not None else None
        output.writerow([city,day,event['obs_utc'],target,next_label,offset,
                         tq[1],dt.datetime.fromtimestamp(tq[0],dt.timezone.utc).isoformat(),
                         cq[1],dt.datetime.fromtimestamp(cq[0],dt.timezone.utc).isoformat(),
                         round(tq[1]-cq[1],6),round(tdelta,6) if tdelta is not None else '',
                         round(cdelta,6) if cdelta is not None else '',round(paired,6) if paired is not None else '',
                         cutoff-tq[0],cutoff-cq[0],abs(tq[0]-cq[0]),'paired' if paired is not None else 'no_m15_base'])
DB.close()
