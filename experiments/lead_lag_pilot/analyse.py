#!/usr/bin/env python3
"""Weekly development inventory and descriptive as-of movements; holdout masked."""
import csv, datetime as dt, json, sqlite3, re
from pathlib import Path
from zoneinfo import ZoneInfo

root = Path(__file__).resolve().parents[2]
db = sqlite3.connect(f'file:{root / "data/polymarket_weather_2026.sqlite"}?mode=ro', uri=True)
db.execute('PRAGMA query_only=ON')
coverage = list(csv.DictReader((root/'experiments/lead_lag_pilot/coverage.csv').open()))
writer = csv.writer(__import__('sys').stdout)
writer.writerow(['city','date','status','observation_utc','temp_c','candidate','price_before','price_after','change_pp','details'])
for city, zone in [('lucknow','Asia/Kolkata'),('munich','Europe/Berlin')]:
    tz = ZoneInfo(zone)
    rows = [r for r in coverage if r['city']==city]
    weeks = sorted({dt.date.fromisoformat(r['day']).isocalendar()[:2] for r in rows})
    holdout = set(weeks[-4:])
    observations = {}
    with (root/'historic_metar'/f'{city}.csv').open(newline='') as f:
        for r in csv.DictReader(f):
            try:
                t = dt.datetime.fromisoformat(r['timestamp_utc']).replace(tzinfo=dt.timezone.utc)
                local = t.astimezone(tz)
                if local.date().isocalendar()[:2] in holdout: continue
                if dt.date(2026,3,5) <= local.date() <= dt.date(2026,7,17) and r['temp_c']:
                    observations.setdefault(local.date().isoformat(), []).append((t,float(r['temp_c'])))
            except (ValueError,KeyError): pass
    for week in weeks:
        if week in holdout:
            writer.writerow([city, f'{week[0]}-W{week[1]:02}', 'holdout_masked','','','','','','',''])
            continue
        candidates = [r for r in rows if dt.date.fromisoformat(r['day']).isocalendar()[:2]==week]
        # Preliminary selection uses coverage only; settlement and window eligibility remain unverified.
        r = next((x for x in candidates if x['event_status']=='found' and int(x['weather_observations'])>0 and int(x['markets'])>0 and x['markets']==x['yes_tokens_with_price']), None)
        if not r:
            writer.writerow([city,f'{week[0]}-W{week[1]:02}','no_preliminary_candidate','','','','','','',''])
            continue
        day=r['day']; obs=sorted(observations.get(day,[])); peak=None; event=None
        for t,temp in obs:
            new = peak is not None and temp > peak
            peak = temp if peak is None else max(peak,temp)
            if new and t.astimezone(tz).hour>=12:
                event=(t,temp); break
        if not event:
            writer.writerow([city,day,'no_afternoon_new_max','','','','','','','']); continue
        t,temp=event
        # Integer values only: open endpoints are inclusive; no rounding assumption.
        bracket=f'{temp:g}°C'
        markets=db.execute("SELECT m.bracket,t.token_id FROM markets m JOIN tokens t ON t.market_id=m.market_id WHERE m.city=? AND m.market_date=? AND t.outcome='YES'",(city,day)).fetchall()
        matches=[]
        if temp.is_integer():
            for name, token_id in markets:
                match=re.fullmatch(r'(-?\d+)°C(?: or (below|higher))?',name or '')
                if match:
                    bound=int(match.group(1)); side=match.group(2)
                    if (side is None and temp==bound) or (side=='below' and temp<=bound) or (side=='higher' and temp>=bound):
                        matches.append((name,token_id))
        token=(matches[0][1],) if len(matches)==1 else None
        if token: bracket=matches[0][0]
        if not token:
            writer.writerow([city,day,'bracket_unmatched',t.isoformat(),temp,bracket,'','','','official mapping unverified']); continue
        prices=[]
        for shift in (-30,30):
            ts=int(t.timestamp())+shift*60
            p=db.execute('SELECT ts,price FROM price_points WHERE token_id=? AND ts BETWEEN ? AND ? AND fidelity_minutes=5 ORDER BY ts DESC LIMIT 1',(token[0],ts-600,ts)).fetchone()
            prices.append(p)
        if not all(prices):
            writer.writerow([city,day,'window_missing',t.isoformat(),temp,bracket,'','','','10m as-of tolerance']); continue
        writer.writerow([city,day,'descriptive',t.isoformat(),temp,bracket,prices[0][1],prices[1][1],round(100*(prices[1][1]-prices[0][1]),2),f'price timestamps UTC {dt.datetime.fromtimestamp(prices[0][0],dt.timezone.utc).isoformat()} / {dt.datetime.fromtimestamp(prices[1][0],dt.timezone.utc).isoformat()}'])
db.close()
