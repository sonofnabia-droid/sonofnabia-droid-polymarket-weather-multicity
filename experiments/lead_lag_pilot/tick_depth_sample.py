#!/usr/bin/env python3
"""One pre-cutoff tick at fixed local hours; calculate displayed 5-share depth."""
import csv,datetime as dt,json
from pathlib import Path
from zoneinfo import ZoneInfo
root=Path(__file__).resolve().parents[2]; w=csv.writer(__import__('sys').stdout)
w.writerow(['city','day','local_hour','status','tick_utc','age_sec','bought_before_tick','target_label','best_ask','best_ask_size','five_shares_displayed','five_share_vwap','levels_used','market_ladder_clob','market_ladder_gamma'])
for city,zone in [('lucknow','Asia/Kolkata'),('munich','Europe/Berlin')]:
    tz=ZoneInfo(zone)
    for path in sorted((root/'live_bot_logs'/'ticks').glob(f'ticks_{city}_2026-11-*.jsonl')):
        day=path.stem.rsplit('_',1)[-1]
        if not '2026-11-10'<=day<='2026-11-14':continue
        records=[]
        with path.open() as f:
            for line in f:
                try:
                    r=json.loads(line); t=dt.datetime.fromisoformat(str(r.get('ts','')).replace('Z','+00:00'))
                    if t.tzinfo:records.append((t.astimezone(dt.timezone.utc),r))
                except (ValueError,TypeError):pass
        for hour in (12,15,18):
            cutoff=dt.datetime.combine(dt.date.fromisoformat(day),dt.time(hour),tz).astimezone(dt.timezone.utc); prior=[(t,r) for t,r in records if 0<=(cutoff-t).total_seconds()<=600]
            if not prior:w.writerow([city,day,hour,'no_recent_tick']);continue
            t,r=max(prior,key=lambda x:x[0]); target=r.get('target_bracket') or {}; book=r.get('target_book') or {}; ladder=r.get('market_full') or []; asks=[]
            for level in book.get('asks') or []:
                try:
                    p,q=float(level[0]),float(level[1])
                    if 0<p<1 and q>0:asks.append((p,q))
                except (TypeError,ValueError,IndexError,KeyError):pass
            asks.sort(); remain=5.0; cost=0.0; used=0
            for p,q in asks:
                take=min(q,remain); cost+=take*p; remain-=take; used+=1
                if remain<=1e-9:break
            full=bool(asks) and remain<=1e-9
            w.writerow([city,day,hour,'book_ask' if asks else 'no_ask_levels',t.isoformat(),round((cutoff-t).total_seconds(),1),bool(r.get('bought')),target.get('label',''),asks[0][0] if asks else '',asks[0][1] if asks else '',full,round(cost/5,5) if full else '',used,sum(isinstance(x,dict) and x.get('src')=='clob' for x in ladder),sum(isinstance(x,dict) and x.get('src')=='gamma' for x in ladder)])
