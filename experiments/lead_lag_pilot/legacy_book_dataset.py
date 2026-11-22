#!/usr/bin/env python3
"""Build small exploratory per-day sample from legacy collector and METAR CSV.

Collector requests token[0]; this script requires archived YES first, exact
event slug and a matching bracket. Weather delay is hypothetical, not measured.
"""
import collections,csv,datetime as dt,json,math,re,sqlite3
from pathlib import Path
from zoneinfo import ZoneInfo
root=Path(__file__).resolve().parents[2]; db=sqlite3.connect(f'file:{root / "data/polymarket_weather_2026.sqlite"}?mode=ro',uri=True); db.execute('PRAGMA query_only=ON')
zones={'lucknow':'Asia/Kolkata','munich':'Europe/Berlin'}; batches=collections.defaultdict(list); weather=collections.defaultdict(list)
for city,zone in zones.items():
    tz=ZoneInfo(zone)
    with (root/'historic_metar'/f'{city}.csv').open(newline='') as f:
        for r in csv.DictReader(f):
            try:
                t=dt.datetime.fromisoformat(r['timestamp_utc']); t=t.replace(tzinfo=dt.timezone.utc) if t.tzinfo is None else t.astimezone(dt.timezone.utc); day=t.astimezone(tz).date().isoformat()
                if '2026-08-27'<=day<='2026-11-14' and r['temp_c']:weather[(city,day)].append((t,float(r['temp_c'])))
            except (ValueError,KeyError,TypeError):pass
with (root/'ask_collector_data.csv').open(newline='') as f:
    for r in csv.DictReader(f):
        city=r.get('city'); zone=zones.get(city)
        if not zone:continue
        try:
            t=dt.datetime.fromisoformat(r['ts'].replace('Z','+00:00')); local=t.astimezone(ZoneInfo(zone)); day=local.date().isoformat()
            if '2026-08-27'<=day<='2026-11-14' and 14<=local.hour<15:batches[(city,day)].append((t,r))
        except (ValueError,KeyError,TypeError):pass
w=csv.writer(__import__('sys').stdout); w.writerow(['city','day','status','decision_utc','weather_obs_utc','running_max','target_bracket','best_bid','best_ask','spread','ask_depth_top5_usdc','outcome_gamma_yes','book_age_sec','source_hint'])
for (city,day),records in sorted(batches.items()):
    start=min(t for t,r in records); group=[(t,r) for t,r in records if (t-start).total_seconds()<=300]; decision=max(t for t,r in group); event=db.execute('SELECT status,slug FROM events WHERE city=? AND market_date=?',(city,day)).fetchone()
    if not event or event[0]!='found' or any(r.get('slug')!=event[1] for t,r in group): w.writerow([city,day,'event_slug_mismatch']);continue
    available=[(t,temp) for t,temp in weather[(city,day)] if t<=decision-dt.timedelta(minutes=15)]
    if not available or (decision-max(t for t,v in available)).total_seconds()>7200:w.writerow([city,day,'missing_recent_weather']);continue
    maximum=max(v for t,v in available); high=int(math.floor(maximum+.5)); markets=db.execute('SELECT bracket,closed,outcome_prices,raw_json FROM markets WHERE city=? AND market_date=?',(city,day)).fetchall(); candidates=[]
    for name,closed,prices,raw in markets:
        m=re.fullmatch(r'(-?\d+)°C(?: or (below|higher))?',name or '')
        if not m:continue
        n=int(m.group(1)); side=m.group(2)
        if (side is None and high==n) or (side=='below' and high<=n) or (side=='higher' and high>=n):candidates.append((name,closed,prices,raw))
    if len(candidates)!=1:w.writerow([city,day,'ambiguous_bracket']);continue
    name,closed,prices,raw=candidates[0]; target=[(t,r) for t,r in group if r.get('bracket')==name]
    if len(target)!=1:w.writerow([city,day,'missing_or_duplicate_target']);continue
    t,r=target[0]
    try:
        o=json.loads(raw); outs=o.get('outcomes',[]); outs=json.loads(outs) if isinstance(outs,str) else outs; tokens=o.get('clobTokenIds',[]); tokens=json.loads(tokens) if isinstance(tokens,str) else tokens
        if len(outs)<2 or len(tokens)<2 or str(outs[0]).upper()!='YES':w.writerow([city,day,'yes_token_not_verified']);continue
        vals=json.loads(prices); p=float(vals[0]); label=int(p) if closed and p in (0,1) else None
        bid=float(r['best_bid']); ask=float(r['best_ask']); depth=float(r['ask_depth_usdc'])
        if not (0<bid<=ask<1 and depth>0):raise ValueError('invalid quote')
    except (ValueError,TypeError,KeyError,IndexError):w.writerow([city,day,'missing_book_or_label']);continue
    if label is None:w.writerow([city,day,'gamma_label_unverified']);continue
    w.writerow([city,day,'provisional',decision.astimezone(dt.timezone.utc).isoformat(),max(t for t,v in available).isoformat(),maximum,name,bid,ask,round(ask-bid,6),depth,label,round((decision-t).total_seconds(),2),o.get('resolutionSource','')])
db.close()
