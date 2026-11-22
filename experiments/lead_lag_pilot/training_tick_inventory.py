#!/usr/bin/env python3
"""Feasibility inventory at 15 local using recorded A telemetry, not training."""
import csv,datetime as dt,json,sqlite3
from pathlib import Path
from zoneinfo import ZoneInfo
root=Path(__file__).resolve().parents[2]; db=sqlite3.connect(f'file:{root / "data/polymarket_weather_2026.sqlite"}?mode=ro',uri=True); db.execute('PRAGMA query_only=ON')
w=csv.writer(__import__('sys').stdout); w.writerow(['city','day','cutoff_utc','tick_utc','tick_age_sec','status','book_bid','book_ask','bid_size','ask_size','target_gamma_closed_yes_price','bought_at_tick','ladder_all_clob','p_rebound_recorded'])
for city,zone in [('lucknow','Asia/Kolkata'),('munich','Europe/Berlin')]:
    tz=ZoneInfo(zone)
    for path in sorted((root/'live_bot_logs'/'ticks').glob(f'ticks_{city}_*.jsonl')):
        day=path.stem.rsplit('_',1)[-1]
        try:
            date=dt.date.fromisoformat(day)
            if date>dt.date(2026,11,14):continue
        except ValueError:continue
        cutoff=dt.datetime.combine(date,dt.time(15),tz).astimezone(dt.timezone.utc); best=None; best_time=None
        with path.open() as f:
            for line in f:
                try:
                    r=json.loads(line); t=dt.datetime.fromisoformat(str(r.get('ts','')).replace('Z','+00:00'))
                    if t.tzinfo and 1<=(cutoff-t).total_seconds()<=600 and (best_time is None or t>best_time):best,best_time=r,t
                except (ValueError,TypeError):pass
        if best is None:w.writerow([city,day,cutoff.isoformat(),'','','no_recent_tick']);continue
        target=best.get('target_bracket') or {}; token=target.get('token_id'); book=best.get('target_book') or {}; bids=[]; asks=[]
        for source,dest in ((book.get('bids') or [],bids),(book.get('asks') or [],asks)):
            for level in source:
                try:
                    p,q=float(level[0]),float(level[1])
                    if 0<p<1 and q>0:dest.append((p,q))
                except (ValueError,TypeError,IndexError,KeyError):pass
        bid=max(bids) if bids else None; ask=min(asks) if asks else None
        market=db.execute('SELECT m.closed,m.outcome_prices,m.raw_json FROM markets m JOIN tokens t ON t.market_id=m.market_id WHERE t.token_id=? AND m.city=? AND m.market_date=? AND t.outcome=\'YES\'',(str(token or ''),city,day)).fetchone(); label=''
        if market:
            try:
                o=json.loads(market[2]); outs=o.get('outcomes',[]); outs=json.loads(outs) if isinstance(outs,str) else outs; i=next(i for i,x in enumerate(outs) if str(x).upper()=='YES'); v=float(json.loads(market[1])[i])
                if market[0] and v in (0,1):label=int(v)
            except (ValueError,TypeError,IndexError,StopIteration):pass
        ladder=best.get('market_full') or []; all_clob=bool(ladder) and all(isinstance(x,dict) and x.get('src')=='clob' for x in ladder)
        status='no_token' if not token else 'no_target_book' if not book else 'one_sided_book' if bid is None or ask is None else 'no_gamma_label' if label=='' else 'eligible_provisional'
        w.writerow([city,day,cutoff.isoformat(),best_time.astimezone(dt.timezone.utc).isoformat(),round((cutoff-best_time).total_seconds(),2),status,bid[0] if bid else '',ask[0] if ask else '',bid[1] if bid else '',ask[1] if ask else '',label,bool(best.get('bought')),all_clob,False])
db.close()
