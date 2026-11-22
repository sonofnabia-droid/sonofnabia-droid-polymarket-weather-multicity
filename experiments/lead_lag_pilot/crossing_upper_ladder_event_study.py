#!/usr/bin/env python3
"""Track the crossed bracket and two brackets above it around each report."""
import csv
import datetime as dt
import re
import sqlite3
import sys
from pathlib import Path

BASE=Path(__file__).resolve().parent
ROOT=BASE.parents[1]
DB=sqlite3.connect(f'file:{ROOT / "data/polymarket_weather_2026.sqlite"}?mode=ro',uri=True)
DB.execute('PRAGMA query_only=ON')
pattern=re.compile(r'(-?\d+)°C(?: or (below|higher))?')
crossings=list(csv.DictReader((BASE/'all_crossings.csv').open(newline='')))
market_cache={}; quote_cache={}; cuts=(-15,-10,-5,0,5,10,15,30)
out=csv.writer(sys.stdout)
out.writerow(['city','day','obs_utc','crossed_bracket','next_live_bracket','second_upper_bracket',
              'offset_min','crossed_yes','crossed_utc','next_yes','next_utc','second_yes','second_utc',
              'crossed_minus_next','next_minus_second','spread_change_from_m15_crossed_next',
              'spread_change_from_m15_next_second','actual_quote_min_after_obs','max_skew_sec','status'])

def q(token,cutoff):
    key=(token,cutoff)
    if key not in quote_cache:
        quote_cache[key]=DB.execute('''SELECT ts,price FROM price_points WHERE token_id=?
            AND fidelity_minutes=5 AND ts BETWEEN ? AND ? ORDER BY ts DESC LIMIT 1''',
            (token,cutoff-360,cutoff)).fetchone()
    return quote_cache[key]

def statistics_median(values):
    vals=sorted(values); n=len(vals)
    return vals[n//2] if n%2 else (vals[n//2-1]+vals[n//2])/2

for e in crossings:
    m=pattern.fullmatch(e['bracket'] or '')
    if not m: continue
    bound=int(m.group(1)); key=e['city'],e['day']
    if key not in market_cache:
        rows=DB.execute('''SELECT m.bracket,t.token_id FROM markets m JOIN tokens t ON t.market_id=m.market_id
            WHERE m.city=? AND m.market_date=? AND t.outcome='YES' ''',key).fetchall()
        market_cache[key]={label:token for label,token in rows}
    tokens=market_cache[key]
    labels=[]
    for label in tokens:
        match=pattern.fullmatch(label or '')
        if match and match.group(2)!='higher': labels.append((int(match.group(1)),label))
    ups=sorted((v,l) for v,l in labels if v>bound)
    if len(ups)<2: continue
    next_label,second_label=ups[0][1],ups[1][1]
    selected=[(e['bracket'],tokens.get(e['bracket'])),(next_label,tokens[next_label]),(second_label,tokens[second_label])]
    if any(not t for _,t in selected): continue
    obs=int(dt.datetime.fromisoformat(e['obs_utc']).timestamp()); path={}
    for off in cuts:
        cutoff=obs+off*60; quotes=[q(t,cutoff) for _,t in selected]
        if all(quotes) and max(x[0] for x in quotes)-min(x[0] for x in quotes)<=60:
            path[off]=(cutoff,quotes)
    base=path.get(-15)
    for off in cuts:
        item=path.get(off)
        if not item:
            out.writerow([e['city'],e['day'],e['obs_utc'],e['bracket'],next_label,second_label,off,*(['']*12),'missing_or_unsynchronized'])
            continue
        cutoff,quotes=item; prices=[x[1] for x in quotes]; times=[x[0] for x in quotes]
        bprices=[x[1] for x in base[1]] if base else None
        d1=prices[0]-prices[1]; d2=prices[1]-prices[2]
        change1=d1-(bprices[0]-bprices[1]) if bprices else ''
        change2=d2-(bprices[1]-bprices[2]) if bprices else ''
        out.writerow([e['city'],e['day'],e['obs_utc'],e['bracket'],next_label,second_label,off,
            prices[0],dt.datetime.fromtimestamp(times[0],dt.timezone.utc).isoformat(),
            prices[1],dt.datetime.fromtimestamp(times[1],dt.timezone.utc).isoformat(),
            prices[2],dt.datetime.fromtimestamp(times[2],dt.timezone.utc).isoformat(),
            round(d1,6),round(d2,6),round(change1,6) if change1!='' else '',
            round(change2,6) if change2!='' else '',
            round((statistics_median(times)-obs)/60,3),max(times)-min(times),'paired' if bprices else 'no_m15_base'])
DB.close()
