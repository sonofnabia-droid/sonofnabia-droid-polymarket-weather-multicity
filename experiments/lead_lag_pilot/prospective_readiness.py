#!/usr/bin/env python3
"""Read-only input readiness; deliberately does not read settlement labels."""
import argparse,csv,datetime as dt,json,re,sqlite3
from pathlib import Path
from zoneinfo import ZoneInfo
parser=argparse.ArgumentParser(); parser.add_argument('--day',required=True); args=parser.parse_args(); date=dt.date.fromisoformat(args.day)
root=Path(__file__).resolve().parents[2]; db=sqlite3.connect(f'file:{root / "data/polymarket_weather_2026.sqlite"}?mode=ro',uri=True); db.execute('PRAGMA query_only=ON')
w=csv.writer(__import__('sys').stdout); w.writerow(['city','day','cutoff_utc','status','tick_utc','tick_age_sec','running_max','target_bracket','yes_tokens','n_above','sqlite_target_book_recent','sqlite_target_ask_present','sqlite_above_asks_present','tick_book_bid_levels','tick_book_ask_levels','tick_book_matches_target','tick_clob_above_asks','tick_book_sample_time_proven','p_rebound_recorded','label_examined'])
for city,zone in [('lucknow','Asia/Kolkata'),('munich','Europe/Berlin')]:
    cutoff=dt.datetime.combine(date,dt.time(15),ZoneInfo(zone)).astimezone(dt.timezone.utc); path=root/'live_bot_logs'/'ticks'/f'ticks_{city}_{args.day}.jsonl'; best=None; best_time=None
    if path.exists():
        with path.open() as f:
            for line in f:
                try:
                    r=json.loads(line); t=dt.datetime.fromisoformat(str(r.get('ts','')).replace('Z','+00:00'))
                    if t.tzinfo and 1<=(cutoff-t).total_seconds()<=600 and (best_time is None or t>best_time):best,best_time=r,t
                except (ValueError,TypeError):pass
    if best is None:w.writerow([city,args.day,cutoff.isoformat(),'no_recent_prior_tick']);continue
    target=best.get('target_bracket') or {}; token=str(target.get('token_id') or '')
    markets=db.execute("SELECT m.bracket,t.token_id FROM markets m JOIN tokens t ON m.market_id=t.market_id WHERE m.city=? AND m.market_date=? AND t.outcome='YES'",(city,args.day)).fetchall(); parsed=[]
    for name,tid in markets:
        match=re.fullmatch(r'(-?\d+)°C(?: or (below|higher))?',name or '')
        if match:parsed.append((int(match.group(1)),name,tid))
    parsed.sort(); idx=next((i for i,x in enumerate(parsed) if str(x[2])==token),None)
    if idx is None or len(parsed)!=len(markets):w.writerow([city,args.day,cutoff.isoformat(),'target_or_bracket_mapping_missing',best_time.astimezone(dt.timezone.utc).isoformat(),(cutoff-best_time).total_seconds(),best.get('running_max','')]);continue
    above=parsed[idx+1:]; at=int(cutoff.timestamp()); quoted=[]
    for _,name,tid in [parsed[idx]]+above:
        q=db.execute('SELECT sampled_at,best_ask FROM book_snapshots WHERE token_id=? AND sampled_at BETWEEN ? AND ? ORDER BY sampled_at DESC LIMIT 1',(tid,at-600,at)).fetchone(); quoted.append(q)
    n_asks=sum(q is not None and q[1] is not None and 0<float(q[1])<1 for q in quoted[1:]); targetq=quoted[0]; target_ask=bool(targetq and targetq[1] is not None and 0<float(targetq[1])<1)
    # TickLogger stores a cached CLOB-enriched market and target_book but no
    # book sampled_at. Keep that evidence separate from timestamped SQLite.
    tick_target=best.get('target_bracket') or {}; tick_book=best.get('target_book') or {}
    bid_levels=tick_book.get('bids') or []; ask_levels=tick_book.get('asks') or []
    tick_lo=float(tick_target.get('temp_lo',float('nan'))); tick_hi=float(tick_target.get('temp_hi',float('nan')))
    target_label=str(parsed[idx][1]); target_bound=parsed[idx][0]
    if 'below' in target_label: bounds_match=tick_lo<=-99 and tick_hi==target_bound
    elif 'higher' in target_label: bounds_match=tick_lo==target_bound and tick_hi>=99
    else: bounds_match=tick_lo==target_bound and tick_hi==target_bound
    tick_matches=(str(tick_target.get('token_id') or '')==str(token) and bounds_match)
    full=best.get('market_full') or []
    clob_above=sum(1 for x in full if isinstance(x,dict)
                   and x.get('src')=='clob'
                   and isinstance(x.get('lo'),(int,float))
                   and x['lo']>float(tick_target.get('temp_hi',float('inf')))
                   and x.get('ask') is not None and 0<float(x['ask'])<1)
    sqlite_ready=target_ask and n_asks==len(above)
    if sqlite_ready: status='sqlite_book_ready_provisional'
    elif tick_matches and bid_levels and ask_levels: status='tick_book_present_unstamped'
    else: status='book_incomplete'
    w.writerow([city,args.day,cutoff.isoformat(),status,best_time.astimezone(dt.timezone.utc).isoformat(),round((cutoff-best_time).total_seconds(),2),best.get('running_max',''),parsed[idx][1],len(markets),len(above),bool(targetq),target_ask,n_asks,len(bid_levels),len(ask_levels),tick_matches,clob_above,False,False,False])
db.close()
