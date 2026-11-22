#!/usr/bin/env python3
"""Compare METAR running-high bracket with market leader; not a bot replay."""
import argparse,collections,csv,datetime as dt,json,re,sqlite3
from pathlib import Path
from zoneinfo import ZoneInfo
parser=argparse.ArgumentParser(); parser.add_argument('--weather-delay',type=int,default=0); parser.add_argument('--end',default='2026-06-21'); args=parser.parse_args()
if args.weather_delay<0: raise SystemExit('weather delay must be non-negative')
if args.end>'2026-07-17': raise SystemExit('End exceeds local WU comparison window')
root=Path(__file__).resolve().parents[2]; db=sqlite3.connect(f'file:{root / "data/polymarket_weather_2026.sqlite"}?mode=ro',uri=True); db.execute('PRAGMA query_only=ON')
out=csv.writer(__import__('sys').stdout); out.writerow(['city','day','hour','status','metar_obs_utc','rmax','candidate','candidate_price','leader','leader_price','winner','candidate_won','leader_won'])
for city,zone in [('lucknow','Asia/Kolkata'),('munich','Europe/Berlin')]:
    tz=ZoneInfo(zone); obs=collections.defaultdict(list)
    with (root/'historic_metar'/f'{city}.csv').open(newline='') as f:
        for r in csv.DictReader(f):
            try:
                t=dt.datetime.fromisoformat(r['timestamp_utc']).replace(tzinfo=dt.timezone.utc); day=t.astimezone(tz).date().isoformat()
                if '2026-03-05'<=day<=args.end and r['temp_c']: obs[day].append((t,float(r['temp_c'])))
            except (ValueError,KeyError): pass
    for day in sorted(obs):
        markets=db.execute("SELECT m.bracket,m.closed,m.outcome_prices,m.raw_json,t.token_id FROM markets m JOIN tokens t ON m.market_id=t.market_id WHERE m.city=? AND m.market_date=? AND t.outcome='YES'",(city,day)).fetchall()
        if not markets: continue
        winner=[]
        for name,closed,prices,raw,token in markets:
            try:
                obj=json.loads(raw); outcomes=obj.get('outcomes',[]); outcomes=json.loads(outcomes) if isinstance(outcomes,str) else outcomes; ix=next(i for i,x in enumerate(outcomes) if str(x).upper()=='YES')
                if closed and float(json.loads(prices)[ix])>=.999: winner.append(name)
            except (ValueError,TypeError,IndexError,StopIteration): pass
        for hour in (12,15):
            now=dt.datetime.combine(dt.date.fromisoformat(day),dt.time(hour),tz).astimezone(dt.timezone.utc); past=[x for x in obs[day] if x[0]<=now-dt.timedelta(minutes=args.weather_delay)]
            if not past: out.writerow([city,day,hour,'no_weather']); continue
            high=max(x[1] for x in past); newest=max(x[0] for x in past); matches=[]; quotes=[]
            for name,closed,prices,raw,token in markets:
                m=re.fullmatch(r'(-?\d+)°C(?: or (below|higher))?',name or '')
                if m and high.is_integer():
                    bound=int(m.group(1)); side=m.group(2)
                    if (side is None and high==bound) or (side=='below' and high<=bound) or (side=='higher' and high>=bound): matches.append(name)
                ts=int(now.timestamp()); q=db.execute('SELECT ts,price FROM price_points WHERE token_id=? AND fidelity_minutes=5 AND ts BETWEEN ? AND ? ORDER BY ts DESC LIMIT 1',(token,ts-600,ts)).fetchone()
                if q: quotes.append((float(q[1]),name))
            if len(matches)!=1 or len(quotes)!=len(markets) or len(winner)!=1 or sum(q[0]==max(x[0] for x in quotes) for q in quotes)>1:
                out.writerow([city,day,hour,'incomplete_or_ambiguous',newest.isoformat(),high]); continue
            leader=max(quotes); candidate=matches[0]; cp=next(x[0] for x in quotes if x[1]==candidate)
            out.writerow([city,day,hour,'descriptive',newest.isoformat(),high,candidate,cp,leader[1],leader[0],winner[0],candidate==winner[0],leader[1]==winner[0]])
db.close()
