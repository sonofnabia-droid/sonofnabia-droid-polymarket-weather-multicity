#!/usr/bin/env python3
"""All newly crossed integer upper bounds per event day; exploratory only."""
import argparse,collections,csv,datetime as dt,json,re,sqlite3
from pathlib import Path
from zoneinfo import ZoneInfo
parser=argparse.ArgumentParser(); parser.add_argument('--source',choices=('historic','historic_metar'),default='historic_metar'); parser.add_argument('--end',default='2026-06-21'); args=parser.parse_args()
if args.end>'2026-07-17': raise SystemExit('End exceeds local WU comparison window')
root=Path(__file__).resolve().parents[2]; db=sqlite3.connect(f'file:{root / "data/polymarket_weather_2026.sqlite"}?mode=ro',uri=True); db.execute('PRAGMA query_only=ON')
w=csv.writer(__import__('sys').stdout); w.writerow(['city','day','obs_utc','local_hour','previous_max','temp','bracket','yes0','no0','yes5','no5','yes10','no10','yes15','no15','yes0_utc','no0_utc','gamma_closed_yes_price','wu_same_time','yes_book_bid0','no_book_ask0','no_ask_size0','yes5_utc','no5_utc','yes10_utc','no10_utc','yes15_utc','no15_utc'])
for city,zone in [('lucknow','Asia/Kolkata'),('munich','Europe/Berlin')]:
    tz=ZoneInfo(zone); obs=collections.defaultdict(list); wu={}
    for source_index,source in enumerate((args.source,'historic')):
        with (root/source/f'{city}.csv').open(newline='') as f:
            for row in csv.DictReader(f):
                try:
                    stamp=dt.datetime.fromisoformat(row['timestamp_utc']); stamp=stamp.replace(tzinfo=dt.timezone.utc) if stamp.tzinfo is None else stamp.astimezone(dt.timezone.utc); day=stamp.astimezone(tz).date().isoformat(); temp=float(row['temp_c'])
                    if '2026-03-05'<=day<=args.end:
                        if source_index==0: obs[day].append((stamp,temp))
                        else: wu.setdefault(stamp,[]).append(temp)
                except (ValueError,KeyError,TypeError): pass
    for day,observations in sorted(obs.items()):
        rows=db.execute('SELECT m.bracket,m.closed,m.outcome_prices,m.raw_json,t.outcome,t.token_id FROM markets m JOIN tokens t ON m.market_id=t.market_id WHERE m.city=? AND m.market_date=?',(city,day)).fetchall(); groups={}
        for name,closed,prices,raw,outcome,token in rows:
            match=re.fullmatch(r'(-?\d+)°C(?: or (below|higher))?',name or '')
            if not match or match.group(2)=='higher': continue
            item=groups.setdefault(name,{'upper':int(match.group(1)),'tokens':{},'settlement':'unknown'}); item['tokens'][outcome.upper()]=token
            try:
                meta=json.loads(raw); outcomes=meta.get('outcomes',[]); outcomes=json.loads(outcomes) if isinstance(outcomes,str) else outcomes
                ix=next(i for i,x in enumerate(outcomes) if str(x).upper()=='YES'); vals=json.loads(prices or '[]')
                if closed: item['settlement']=vals[ix]
            except (ValueError,TypeError,IndexError,StopIteration): pass
        peak=None
        for stamp,temp in sorted(observations):
            if peak is None: peak=temp; continue
            prev=peak; peak=max(peak,temp)
            if not temp.is_integer() or temp<=prev: continue
            for name,item in groups.items():
                if not (prev<=item['upper']<temp): continue
                values=[]; stamps=[]; at0=int(stamp.timestamp())
                for delay in (0,5,10,15):
                    for outcome in ('YES','NO'):
                        token=item['tokens'].get(outcome); at=at0+delay*60
                        q=db.execute('SELECT ts,price FROM price_points WHERE token_id=? AND fidelity_minutes=5 AND ts BETWEEN ? AND ? ORDER BY ts DESC LIMIT 1',(token,at-600,at)).fetchone() if token else None
                        values.append(q[1] if q else ''); stamps.append(dt.datetime.fromtimestamp(q[0],dt.timezone.utc).isoformat() if q else '')
                books=[]
                for outcome in ('YES','NO'):
                    token=item['tokens'].get(outcome); books.append(db.execute('SELECT best_bid,best_ask,ask_size FROM book_snapshots WHERE token_id=? AND sampled_at BETWEEN ? AND ? ORDER BY sampled_at DESC LIMIT 1',(token,at0-600,at0)).fetchone() if token else None)
                same=wu.get(stamp,[]); yes,no=books
                w.writerow([city,day,stamp.isoformat(),stamp.astimezone(tz).hour,prev,temp,name,*values,stamps[0],stamps[1],item['settlement'],same[0] if len(same)==1 else '',yes[0] if yes and yes[0] is not None else '',no[1] if no and no[1] is not None else '',no[2] if no and no[2] is not None else '',*stamps[2:]])
db.close()
