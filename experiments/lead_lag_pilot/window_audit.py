#!/usr/bin/env python3
"""Audit observed price coverage for candidate and neighbouring brackets."""
import csv, datetime as dt, re, sqlite3
from pathlib import Path

root=Path(__file__).resolve().parents[2]
db=sqlite3.connect(f'file:{root / "data/polymarket_weather_2026.sqlite"}?mode=ro',uri=True)
db.execute('PRAGMA query_only=ON')
writer=csv.writer(__import__('sys').stdout)
writer.writerow(['city','date','bracket','role','points_60m','max_gap_seconds','asof_before','asof_after','coverage_pass'])
for row in csv.DictReader((root/'experiments/lead_lag_pilot/development.csv').open()):
    if row['status'] not in ('descriptive','window_missing'): continue
    markets=db.execute("SELECT m.bracket,t.token_id FROM markets m JOIN tokens t ON t.market_id=m.market_id WHERE m.city=? AND m.market_date=? AND t.outcome='YES'",(row['city'],row['date'])).fetchall()
    parsed=[]
    for name,token in markets:
        match=re.fullmatch(r'(-?\d+)°C(?: or (below|higher))?',name or '')
        if match: parsed.append((int(match.group(1)),name,token))
    parsed.sort()
    indices=[i for i,x in enumerate(parsed) if x[1]==row['candidate']]
    if len(indices)!=1: continue
    index=indices[0]; target=int(dt.datetime.fromisoformat(row['observation_utc']).timestamp())
    for i in range(max(0,index-1),min(len(parsed),index+2)):
        _,name,token=parsed[i]; start=target-1800; end=target+1800
        points=db.execute('SELECT ts FROM price_points WHERE token_id=? AND fidelity_minutes=5 AND ts BETWEEN ? AND ? ORDER BY ts',(token,start-600,end)).fetchall()
        times=[p[0] for p in points]; in_window=[t for t in times if start<=t<=end]
        before=any(start-600<=t<=start for t in times); after=any(end-600<=t<=end for t in times)
        gaps=[b-a for a,b in zip(in_window,in_window[1:])]
        maxgap=max(gaps) if gaps else None
        passed=before and after and len(in_window)>=10 and maxgap is not None and maxgap<=600
        writer.writerow([row['city'],row['date'],name,'candidate' if i==index else 'adjacent',len(in_window),maxgap,before,after,passed])
db.close()
