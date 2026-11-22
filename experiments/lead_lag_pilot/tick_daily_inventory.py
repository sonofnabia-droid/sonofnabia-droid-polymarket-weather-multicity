#!/usr/bin/env python3
"""Read-only per-day inventory of A/B telemetry without importing logger."""
import csv,datetime as dt,json
from pathlib import Path
root=Path(__file__).resolve().parents[2]
w=csv.writer(__import__('sys').stdout); w.writerow(['bot','city','day','ticks','valid_timestamps','target_ticks','ladder_ticks','all_clob_ticks','target_book_ticks','target_ask_levels_ticks','actions_ticks','bought_ticks','first_utc','last_utc'])
for bot,folder in [('A','live_bot_logs'),('B','live_bot_logs_v6')]:
    for city in ('munich','lucknow'):
        for path in sorted((root/folder/'ticks').glob(f'ticks_{city}_2026-11-*.jsonl')):
            day=path.stem.rsplit('_',1)[-1]
            if not ('2026-11-01'<=day<='2026-11-14'): continue
            counts=[0]*9; times=[]
            with path.open() as f:
                for line in f:
                    try: r=json.loads(line)
                    except ValueError:continue
                    counts[0]+=1
                    try:
                        t=dt.datetime.fromisoformat(str(r.get('ts','')).replace('Z','+00:00'))
                        if t.tzinfo: times.append(t.astimezone(dt.timezone.utc)); counts[1]+=1
                    except (ValueError,TypeError):pass
                    target=r.get('target_bracket') or {}; ladder=r.get('market_full') or []; book=r.get('target_book') or {}
                    counts[2]+=bool(target.get('token_id')); counts[3]+=bool(ladder); counts[4]+=bool(ladder) and all(isinstance(x,dict) and x.get('src')=='clob' for x in ladder)
                    counts[5]+=bool(book); counts[6]+=bool(book.get('asks')); counts[7]+=bool(r.get('actions')); counts[8]+=bool(r.get('bought'))
            w.writerow([bot,city,day,*counts,min(times).isoformat() if times else '',max(times).isoformat() if times else ''])
