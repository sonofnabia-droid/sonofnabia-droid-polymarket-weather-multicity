#!/usr/bin/env python3
"""Daily retrospective WU/METAR maxima versus archived Gamma metadata."""
import argparse,collections,csv,datetime as dt,json,re,sqlite3
from decimal import Decimal,ROUND_FLOOR
from pathlib import Path
from zoneinfo import ZoneInfo
parser=argparse.ArgumentParser(); parser.add_argument('--end',default='2026-07-17'); args=parser.parse_args()
if args.end>'2026-11-14': raise SystemExit('Use only completed days through 2026-11-14')
root=Path(__file__).resolve().parents[2]; db=sqlite3.connect(f'file:{root / "data/polymarket_weather_2026.sqlite"}?mode=ro',uri=True); db.execute('PRAGMA query_only=ON')
w=csv.writer(__import__('sys').stdout); w.writerow(['city','day','status','source_hint','winner_gamma','wu_n','wu_max','wu_first_local','wu_last_local','wu_max_gap_min','wu_rounded','wu_bracket','wu_match','metar_n','metar_max','metar_first_local','metar_last_local','metar_max_gap_min','metar_rounded','metar_bracket','metar_match','winner_status'])
def bracket(value,names):
    if value is None:return None,None
    # Nearest integer with exact halves toward the higher integer, including negatives.
    rounded=int((Decimal(str(value))+Decimal('0.5')).to_integral_value(rounding=ROUND_FLOOR)); matches=[]
    for name in names:
        m=re.fullmatch(r'(-?\d+)°C(?: or (below|higher))?',name or '')
        if not m:continue
        n=int(m.group(1)); side=m.group(2)
        if (side is None and rounded==n) or (side=='below' and rounded<=n) or (side=='higher' and rounded>=n): matches.append(name)
    return rounded,matches[0] if len(matches)==1 else None
def stats(values):
    if not values:return [0,'','','','','','','']
    values=sorted(values,key=lambda x:x[0].astimezone(dt.timezone.utc)); times=sorted({t.astimezone(dt.timezone.utc) for t,v in values}); mx=max(v for t,v in values); gaps=[(b-a).total_seconds()/60 for a,b in zip(times,times[1:])]
    return [len(values),mx,values[0][0].isoformat(),values[-1][0].isoformat(),max(gaps) if gaps else '',None,None,None]
for city,zone in [('lucknow','Asia/Kolkata'),('munich','Europe/Berlin')]:
    tz=ZoneInfo(zone); weather={}
    for src in ('historic','historic_metar'):
        byday=collections.defaultdict(list)
        with (root/src/f'{city}.csv').open(newline='') as f:
            for row in csv.DictReader(f):
                try:
                    t=dt.datetime.fromisoformat(row['timestamp_utc']); t=t.replace(tzinfo=dt.timezone.utc) if t.tzinfo is None else t.astimezone(dt.timezone.utc); loc=t.astimezone(tz); day=loc.date().isoformat(); v=float(row['temp_c'])
                    if '2026-03-05'<=day<=args.end: byday[day].append((loc,v))
                except (ValueError,KeyError,TypeError): pass
        weather[src]=byday
    day=dt.date(2026,3,5)
    while day<=dt.date.fromisoformat(args.end):
        ds=day.isoformat(); event=db.execute('SELECT status FROM events WHERE city=? AND market_date=?',(city,ds)).fetchone(); markets=db.execute('SELECT bracket,closed,outcome_prices,raw_json FROM markets WHERE city=? AND market_date=?',(city,ds)).fetchall(); winners=[]; sources=set()
        for name,closed,prices,raw in markets:
            try:
                obj=json.loads(raw); source=(obj.get('resolutionSource') or '').lower(); desc=(obj.get('description') or '').lower()
                if 'wunderground' in source:sources.add('WU')
                elif 'aviationweather' in source:sources.add('AWC')
                elif 'weather.gov' in source:sources.add('NOAA')
                else:sources.add('other_or_missing')
                outcomes=obj.get('outcomes',[]); outcomes=json.loads(outcomes) if isinstance(outcomes,str) else outcomes; ix=next(i for i,x in enumerate(outcomes) if str(x).upper()=='YES'); p=float(json.loads(prices)[ix])
                if closed and p>=.999:winners.append(name)
            except (ValueError,TypeError,IndexError,StopIteration):pass
        win=winners[0] if len(winners)==1 else None; names=[x[0] for x in markets]; output=[]
        for src in ('historic','historic_metar'):
            s=stats(weather[src][ds]); rounded,name=bracket(s[1] if s[0] else None,names); s[5:8]=[rounded if rounded is not None else '',name or '',name==win if name and win else '']; output.extend(s)
        w.writerow([city,ds,event[0] if event else 'absent',','.join(sorted(sources)),win or '',*output,'gamma_indicated' if win else 'unverified']); day+=dt.timedelta(days=1)
db.close()
