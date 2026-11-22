#!/usr/bin/env python3
"""Replicate eliminated-bracket repricing on an existing crossing CSV.

Selection is from the prebuilt no-outcome METAR crossing file. Gamma closed
labels are never queried. All SQLite reads are token/time indexed, mode=ro.
Price history is indicative CLOB history, not executable book data.
"""
import csv,datetime as dt,json,re,sqlite3,sys
from collections import defaultdict
from pathlib import Path

BASE=Path(__file__).resolve().parent
ROOT=BASE.parents[1]
event_file=Path(sys.argv[1]) if len(sys.argv)>1 else BASE/'all_crossings_metar_through_july17.csv'
if not event_file.is_absolute(): event_file=ROOT/event_file
events=list(csv.DictReader(event_file.open(newline='')))
db=sqlite3.connect(f'file:{ROOT / "data/polymarket_weather_2026.sqlite"}?mode=ro',uri=True)
db.execute('PRAGMA query_only=ON')
pat=re.compile(r'(-?\d+)°C(?: or (below|higher))?')
def contains(label,value):
    m=pat.fullmatch(label or '')
    if not m:return False
    n=int(m.group(1));edge=m.group(2)
    return value<=n if edge=='below' else value>=n if edge=='higher' else value==n
def upper(label):
    m=pat.fullmatch(label or '')
    return int(m.group(1)) if m and m.group(2)!='higher' else None
market_cache={};source_cache={};qcache={}
offsets=(-15,-10,-5,0,5,10,15)
out=csv.writer(sys.stdout)
out.writerow(['event_id','city','day','obs_utc','previous_max_c','cross_temp_c','crossed_bracket','ceiling_c',
 'frontier_bracket','primary_resolution_source','offset_min','cross_yes','cross_no','frontier_yes','frontier_no',
 'cross_yes_utc','cross_no_utc','frontier_yes_utc','frontier_no_utc','crossed_minus_frontier_yes',
 'yes_delta_vs_m15','no_delta_vs_m15','localized_diff_in_diffs_vs_m15','actual_quote_min_after_obs',
 'max_four_token_skew_sec','status'])

def quote(token,cutoff):
    if not token:return None
    key=(token,cutoff)
    if key not in qcache:
        qcache[key]=db.execute('''SELECT ts,price FROM price_points WHERE token_id=?
          AND fidelity_minutes=5 AND ts BETWEEN ? AND ? ORDER BY ts DESC LIMIT 1''',
          (token,cutoff-360,cutoff)).fetchone()
    return qcache[key]

for ix,e in enumerate(events):
    city,day=e['city'],e['day'];event=(city,day)
    if event not in market_cache:
        rawrows=db.execute('''SELECT m.bracket,t.outcome,t.token_id,m.raw_json FROM markets m
          JOIN tokens t ON t.market_id=m.market_id WHERE m.city=? AND m.market_date=?''',event).fetchall()
        markets=defaultdict(dict);raw=None
        for bracket,outcome,token,raw_json in rawrows:
            markets[bracket][outcome]=token
            raw=raw_json
        market_cache[event]=markets
        try:source_cache[event]=json.loads(raw).get('resolutionSource','') if raw else ''
        except (ValueError,TypeError):source_cache[event]=''
    markets=market_cache[event]
    try:temp=int(float(e['temp']))
    except (ValueError,TypeError):continue
    frontier=next((label for label in markets if contains(label,temp)), '')
    crossed=e['bracket']; upper_c=upper(crossed)
    if not frontier or frontier==crossed:continue
    selected=[markets[crossed].get('YES'),markets[crossed].get('NO'),
              markets[frontier].get('YES'),markets[frontier].get('NO')]
    if any(not token for token in selected):continue
    obs=int(dt.datetime.fromisoformat(e['obs_utc']).timestamp())
    paths={}
    for offset in offsets:
        cutoff=obs+offset*60
        points=[quote(token,cutoff) for token in selected]
        if all(points):
            ts=[int(p[0]) for p in points]
            if max(ts)-min(ts)<=60:
                paths[offset]=(points,ts)
    base=paths.get(-15)
    for offset in offsets:
        item=paths.get(offset)
        if not item:
            out.writerow([ix,city,day,e['obs_utc'],e['previous_max'],e['temp'],crossed,upper_c,frontier,
                source_cache[event],offset,*(['']*14),'missing_or_unsynchronized'])
            continue
        points,times=item; prices=[float(p[1]) for p in points]
        age=(sum(times)/len(times)-obs)/60
        if base:
            bp=[float(p[1]) for p in base[0]]
            ydelta=prices[0]-bp[0];ndelta=prices[1]-bp[1]
            diff=(prices[0]-prices[2])-(bp[0]-bp[2])
        else:ydelta=ndelta=diff=''
        out.writerow([ix,city,day,e['obs_utc'],e['previous_max'],e['temp'],crossed,upper_c,frontier,
            source_cache[event],offset,*prices,
            *[dt.datetime.fromtimestamp(t,dt.timezone.utc).isoformat() for t in times],
            round(prices[0]-prices[2],6),round(ydelta,6) if ydelta!='' else '',
            round(ndelta,6) if ndelta!='' else '',round(diff,6) if diff!='' else '',
            round(age,3),max(times)-min(times),'paired' if base else 'paired_no_m15_base'])
db.close()
