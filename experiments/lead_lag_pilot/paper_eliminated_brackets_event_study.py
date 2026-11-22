#!/usr/bin/env python3
"""Exploratory price response after native METAR max crosses bracket ceilings.

Selected PAPER city-days only; not a representative sample. Uses native
METAR observation timestamps, Gamma metadata/labels, and historical 5m prices.
Observation time is not publication time. No orderbooks or fills are inferred.
"""
import csv, datetime as dt, json, math, re, sqlite3
from collections import defaultdict
from pathlib import Path
from zoneinfo import ZoneInfo

BASE=Path(__file__).resolve().parent
ROOT=BASE.parents[1]
paper=list(csv.DictReader((BASE/'paper_native_metar_complement.csv').open(newline='')))
events=sorted({(r['city'],r['day']) for r in paper})
weather=defaultdict(list)
for city in ('lucknow','munich'):
    with (ROOT/'historic_metar'/f'{city}.csv').open(newline='') as f:
        for row in csv.DictReader(f):
            try:
                stamp=dt.datetime.fromisoformat(row['timestamp_utc'].replace('Z','+00:00'))
                if stamp.tzinfo is None: stamp=stamp.replace(tzinfo=dt.timezone.utc)
                weather[city].append((stamp.astimezone(dt.timezone.utc),float(row['temp_c'])))
            except (ValueError,TypeError): pass

db=sqlite3.connect(f'file:{ROOT / "data/polymarket_weather_2026.sqlite"}?mode=ro',uri=True)
db.execute('PRAGMA query_only=ON')
pat=re.compile(r'(-?\d+)°C(?: or (below|higher))?')
def upper_bound(bracket):
    m=pat.fullmatch(bracket or '')
    if not m or m.group(2)=='higher': return None
    return int(m.group(1))
def contains(bracket,value):
    m=pat.fullmatch(bracket or '')
    if not m:return False
    n=int(m.group(1)); edge=m.group(2)
    return value<=n if edge=='below' else value>=n if edge=='higher' else value==n
def pick(points,target,max_age=600):
    chosen=None
    for ts,p in points:
        if ts<=target: chosen=(ts,p)
        else: break
    if chosen is None or target-chosen[0]>max_age:return (None,None,None)
    return chosen[1],target-chosen[0],chosen[0]

out=csv.writer(__import__('sys').stdout)
out.writerow(['city','day','gamma_resolution_source','gamma_description_rule','bracket','ceiling_c',
 'first_native_metar_cross_utc','observed_temp_c','running_max_rounded_c','prior_rows_same_day',
 'crossing_observable_within_day',
 'gamma_yes_winner','quote_points_yes','quote_points_no',
 'yes_pre30','yes_pre30_age_sec','yes_pre15','yes_pre15_age_sec',
 'yes_pre_minus10','yes_pre_age_sec','yes_plus5','yes_plus5_age_sec','yes_plus10','yes_plus10_age_sec',
 'yes_plus15','yes_plus15_age_sec','no_pre30','no_pre30_age_sec','no_pre15','no_pre15_age_sec',
 'no_pre_minus10','no_pre_age_sec','no_plus5','no_plus5_age_sec',
 'no_plus10','no_plus10_age_sec','no_plus15','no_plus15_age_sec',
 'yes_delta_pre_to_5','no_delta_pre_to_5','yes_delta_pre_to_10','no_delta_pre_to_10',
 'yes_delta_pre_to_15','no_delta_pre_to_15',
 'frontier_bracket','frontier_yes_pre','frontier_yes_plus5','frontier_yes_plus10','frontier_yes_plus15',
 'frontier_no_pre','frontier_no_plus5','frontier_no_plus10','frontier_no_plus15',
 'frontier_yes_pre30','frontier_yes_pre15','frontier_no_pre30','frontier_no_pre15',
 'localized_yes_diff_in_diffs_plus5','localized_yes_diff_in_diffs_plus10','localized_yes_diff_in_diffs_plus15',
 'localized_yes_pretrend_diff_in_diffs',
 'cross_frontier_quote_skew_pre_sec','cross_frontier_quote_skew_plus5_sec',
 'cross_frontier_quote_skew_plus10_sec','cross_frontier_quote_skew_plus15_sec',
 'four_token_quote_skew_pre_sec','four_token_quote_skew_plus5_sec',
 'four_token_quote_skew_plus10_sec','four_token_quote_skew_plus15_sec',
 'four_token_quote_skew_pre30_sec','four_token_quote_skew_pre15_sec',
 'limitations'])

for city,day in events:
    ev=db.execute('SELECT timezone FROM events WHERE city=? AND market_date=? AND status="found" LIMIT 1',(city,day)).fetchone()
    tz=ZoneInfo(ev[0]) if ev and ev[0] else ZoneInfo('Asia/Kolkata' if city=='lucknow' else 'Europe/Berlin')
    local=dt.date.fromisoformat(day)
    obs=[(ts,t) for ts,t in weather[city] if ts.astimezone(tz).date()==local]
    obs.sort()
    if not obs:continue
    markets=db.execute('''SELECT m.bracket,m.closed,m.outcome_prices,m.raw_json,t.token_id,t.outcome
       FROM markets m JOIN tokens t ON t.market_id=m.market_id
       WHERE m.city=? AND m.market_date=? ORDER BY m.bracket,t.outcome''',(city,day)).fetchall()
    groups=defaultdict(dict); metas={}
    for bracket,closed,prices,raw,token,outcome in markets:
        groups[bracket][outcome]=(token,closed,prices)
        metas[bracket]=json.loads(raw)
    running=-math.inf; crossing={}
    for obs_i,(ts,temp) in enumerate(obs):
        running=max(running,math.floor(temp+0.5))
        for bracket in groups:
            ceiling=upper_bound(bracket)
            if ceiling is not None and running>ceiling and bracket not in crossing:
                crossing[bracket]=(ts,temp,running,obs_i,obs_i>0)
    for bracket,(cross,temp,rounded,prior_rows,observable) in crossing.items():
        meta=metas[bracket]; res=meta.get('resolutionSource','')
        desc=' '.join((meta.get('description') or '').split())
        yes=groups[bracket].get('YES'); no=groups[bracket].get('NO')
        if not yes or not no:continue
        def is_winner(item):
            try:
                _,closed,prices=item; vals=json.loads(prices or '[]')
                outcomes=meta.get('outcomes',[]); outcomes=json.loads(outcomes) if isinstance(outcomes,str) else outcomes
                i=next(i for i,x in enumerate(outcomes) if str(x).upper()=='YES')
                return bool(closed and float(vals[i])>=.999)
            except (ValueError,TypeError,KeyError,IndexError,StopIteration):return False
        token_yes=yes[0];token_no=no[0]
        # Token-indexed, date-bounded reads only; the -40m/+20m window is sparse.
        lo=int(cross.timestamp())-2400; hi=int(cross.timestamp())+1200
        ypts=db.execute('SELECT ts,price FROM price_points WHERE token_id=? AND fidelity_minutes=5 AND ts BETWEEN ? AND ? ORDER BY ts',(token_yes,lo,hi)).fetchall()
        npts=db.execute('SELECT ts,price FROM price_points WHERE token_id=? AND fidelity_minutes=5 AND ts BETWEEN ? AND ? ORDER BY ts',(token_no,lo,hi)).fetchall()
        ypts=[(int(t),float(p)) for t,p in ypts]; npts=[(int(t),float(p)) for t,p in npts]
        cuts={name:int((cross+dt.timedelta(minutes=offset)).timestamp()) for name,offset in [('pre30',-30),('pre15',-15),('pre',-10),('p5',5),('p10',10),('p15',15)]}
        yp={k:pick(ypts,t) for k,t in cuts.items()};np={k:pick(npts,t) for k,t in cuts.items()}
        yd5=(yp['p5'][0]-yp['pre'][0]) if yp['p5'][0] is not None and yp['pre'][0] is not None else ''
        nd5=(np['p5'][0]-np['pre'][0]) if np['p5'][0] is not None and np['pre'][0] is not None else ''
        yd10=(yp['p10'][0]-yp['pre'][0]) if yp['p10'][0] is not None and yp['pre'][0] is not None else ''
        nd10=(np['p10'][0]-np['pre'][0]) if np['p10'][0] is not None and np['pre'][0] is not None else ''
        yd15=(yp['p15'][0]-yp['pre'][0]) if yp['p15'][0] is not None and yp['pre'][0] is not None else ''
        nd15=(np['p15'][0]-np['pre'][0]) if np['p15'][0] is not None and np['pre'][0] is not None else ''
        frontier=next((b for b in groups if contains(b,rounded)), '')
        fy={};fn={}
        if frontier and frontier!=bracket and 'YES' in groups[frontier] and 'NO' in groups[frontier]:
            fyt=groups[frontier]['YES'][0]; fnt=groups[frontier]['NO'][0]
            fyp=db.execute('SELECT ts,price FROM price_points WHERE token_id=? AND fidelity_minutes=5 AND ts BETWEEN ? AND ? ORDER BY ts',(fyt,lo,hi)).fetchall()
            fnp=db.execute('SELECT ts,price FROM price_points WHERE token_id=? AND fidelity_minutes=5 AND ts BETWEEN ? AND ? ORDER BY ts',(fnt,lo,hi)).fetchall()
            fyp=[(int(t),float(p)) for t,p in fyp];fnp=[(int(t),float(p)) for t,p in fnp]
            fy={k:pick(fyp,t) for k,t in cuts.items()};fn={k:pick(fnp,t) for k,t in cuts.items()}
        diff5=(yd5-(fy['p5'][0]-fy['pre'][0])) if yd5!='' and fy.get('p5',(None,None))[0] is not None and fy.get('pre',(None,None))[0] is not None else ''
        diff10=(yd10-(fy['p10'][0]-fy['pre'][0])) if yd10!='' and fy.get('p10',(None,None))[0] is not None and fy.get('pre',(None,None))[0] is not None else ''
        diff15=(yd15-(fy['p15'][0]-fy['pre'][0])) if yd15!='' and fy.get('p15',(None,None))[0] is not None and fy.get('pre',(None,None))[0] is not None else ''
        pretrend=((yp['pre15'][0]-yp['pre30'][0])-(fy['pre15'][0]-fy['pre30'][0])) if all(yp[k][0] is not None and fy.get(k,(None,None,None))[0] is not None for k in ('pre30','pre15')) else ''
        skews={k:abs(yp[k][2]-fy[k][2]) if yp[k][2] is not None and fy.get(k,(None,None,None))[2] is not None else '' for k in ('pre','p5','p10','p15','pre30','pre15')}
        all_skews={k:(max(vals)-min(vals) if all(x is not None for x in vals) else '')
                   for k,vals in {'pre':[yp['pre'][2],np['pre'][2],fy.get('pre',(None,None,None))[2],fn.get('pre',(None,None,None))[2]],
                                  'p5':[yp['p5'][2],np['p5'][2],fy.get('p5',(None,None,None))[2],fn.get('p5',(None,None,None))[2]],
                                  'p10':[yp['p10'][2],np['p10'][2],fy.get('p10',(None,None,None))[2],fn.get('p10',(None,None,None))[2]],
                                  'p15':[yp['p15'][2],np['p15'][2],fy.get('p15',(None,None,None))[2],fn.get('p15',(None,None,None))[2]],
                                  'pre30':[yp['pre30'][2],np['pre30'][2],fy.get('pre30',(None,None,None))[2],fn.get('pre30',(None,None,None))[2]],
                                  'pre15':[yp['pre15'][2],np['pre15'][2],fy.get('pre15',(None,None,None))[2],fn.get('pre15',(None,None,None))[2]]}.items()}
        out.writerow([city,day,res,desc[:600],bracket,upper_bound(bracket),cross.isoformat(),temp,rounded,
          prior_rows,observable,is_winner(yes),len(ypts),len(npts),
          yp['pre30'][0],yp['pre30'][1],yp['pre15'][0],yp['pre15'][1],
          yp['pre'][0],yp['pre'][1],yp['p5'][0],yp['p5'][1],yp['p10'][0],yp['p10'][1],yp['p15'][0],yp['p15'][1],
          np['pre30'][0],np['pre30'][1],np['pre15'][0],np['pre15'][1],
          np['pre'][0],np['pre'][1],np['p5'][0],np['p5'][1],np['p10'][0],np['p10'][1],np['p15'][0],np['p15'][1],
          yd5,nd5,yd10,nd10,yd15,nd15,
          frontier,fy.get('pre',(None,None))[0],fy.get('p5',(None,None))[0],fy.get('p10',(None,None))[0],fy.get('p15',(None,None))[0],
          fn.get('pre',(None,None))[0],fn.get('p5',(None,None))[0],fn.get('p10',(None,None))[0],fn.get('p15',(None,None))[0],
          fy.get('pre30',(None,None))[0],fy.get('pre15',(None,None))[0],fn.get('pre30',(None,None))[0],fn.get('pre15',(None,None))[0],
          diff5,diff10,diff15,pretrend,
          skews['pre'],skews['p5'],skews['p10'],skews['p15'],
          all_skews['pre'],all_skews['p5'],all_skews['p10'],all_skews['p15'],
          all_skews['pre30'],all_skews['pre15'],
          'native METAR obs timestamp != confirmed publication; Gamma archived rule/source; 5m price_points != executable CLOB ask/fill; event-selected PAPER dates'])
db.close()
