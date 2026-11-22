#!/usr/bin/env python3
"""Bounded day/token book inventory for feasibility of W/M/H training."""
import csv,datetime as dt,json,sqlite3
from pathlib import Path
from zoneinfo import ZoneInfo
root=Path(__file__).resolve().parents[2]; db=sqlite3.connect(f'file:{root / "data/polymarket_weather_2026.sqlite"}?mode=ro',uri=True); db.execute('PRAGMA query_only=ON')
w=csv.writer(__import__('sys').stdout); w.writerow(['city','day','event_status','yes_tokens','yes_tokens_with_local_day_books','snapshots_local_day','winner_gamma_indicated','hour_local','tokens_with_recent_books','tokens_with_ask','tokens_with_two_sided','oldest_recent_age_sec'])
for city,zone in [('lucknow','Asia/Kolkata'),('munich','Europe/Berlin')]:
    tz=ZoneInfo(zone); day=dt.date(2026,11,1)
    while day<=dt.date(2026,11,15):
        ds=day.isoformat(); event=db.execute('SELECT status FROM events WHERE city=? AND market_date=?',(city,ds)).fetchone(); markets=db.execute("SELECT m.bracket,m.closed,m.outcome_prices,m.raw_json,t.token_id FROM markets m JOIN tokens t ON t.market_id=m.market_id WHERE m.city=? AND m.market_date=? AND t.outcome='YES'",(city,ds)).fetchall(); winners=[]
        start=int(dt.datetime.combine(day,dt.time.min,tz).timestamp()); end=int(dt.datetime.combine(day+dt.timedelta(days=1),dt.time.min,tz).timestamp()); covered=0; total=0
        for name,closed,prices,raw,token in markets:
            count=db.execute('SELECT COUNT(*) FROM book_snapshots WHERE token_id=? AND sampled_at>=? AND sampled_at<?',(token,start,end)).fetchone()[0]; covered+=count>0; total+=count
            try:
                o=json.loads(raw); outcomes=o.get('outcomes',[]); outcomes=json.loads(outcomes) if isinstance(outcomes,str) else outcomes; i=next(j for j,x in enumerate(outcomes) if str(x).upper()=='YES'); p=float(json.loads(prices)[i])
                if closed and p>=.999:winners.append(name)
            except (ValueError,TypeError,IndexError,StopIteration):pass
        for hour in (12,15,18):
            at=int(dt.datetime.combine(day,dt.time(hour),tz).timestamp()); quotes=[]
            for _,_,_,_,token in markets:
                q=db.execute('SELECT sampled_at,best_bid,best_ask FROM book_snapshots WHERE token_id=? AND sampled_at BETWEEN ? AND ? ORDER BY sampled_at DESC LIMIT 1',(token,at-600,at)).fetchone()
                if q:quotes.append(q)
            w.writerow([city,ds,event[0] if event else 'absent',len(markets),covered,total,winners[0] if len(winners)==1 else '',hour,len(quotes),sum(q[2] is not None for q in quotes),sum(q[1] is not None and q[2] is not None for q in quotes),max((at-q[0] for q in quotes),default='')])
        day+=dt.timedelta(days=1)
db.close()
