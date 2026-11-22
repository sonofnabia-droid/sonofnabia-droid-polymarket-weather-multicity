#!/usr/bin/env python3
"""Join each PAPER entry to the latest telemetry tick preceding its timestamp."""
import csv,datetime as dt,json
from pathlib import Path
root=Path(__file__).resolve().parents[2]; base=root/'experiments/lead_lag_pilot'
w=csv.writer(__import__('sys').stdout); w.writerow(['bot','city','day','entry_utc','result','history_leader','tick_status','tick_utc','tick_age_sec','same_token','ladder_size','ladder_clob_count','ladder_gamma_count','target_book_present','book_ask_price','book_ask_size','paper_price','tick_bought','tick_action_count'])
folders={'A':'live_bot_logs','B':'live_bot_logs_v6','C':'live_bot_logs_c'}
for r in csv.DictReader((base/'paper_filter_study.csv').open()):
    bot,city,day=r['bot'],r['city'],r['day']; folder=root/folders[bot]; entry=dt.datetime.fromisoformat(r['timestamp_utc']); bets=folder/f'bets_{city}_{day}.json'; tickfile=folder/'ticks'/f'ticks_{city}_{day}.jsonl'
    try: raw=json.loads(bets.read_text()); records=raw if isinstance(raw,list) else [raw]
    except (OSError,ValueError):continue
    token=None
    for rec in records:
        try:
            t=dt.datetime.fromisoformat(str(rec.get('timestamp','')).replace('Z','+00:00'))
            if t.tzinfo and t.astimezone(dt.timezone.utc)==entry: token=str(rec.get('token_id','')); break
        except (AttributeError,ValueError,TypeError):pass
    best=None; best_t=None
    if tickfile.exists():
        with tickfile.open() as f:
            for line in f:
                try:
                    tick=json.loads(line); t=dt.datetime.fromisoformat(str(tick.get('ts','')).replace('Z','+00:00'))
                    if t.tzinfo and 1<=(entry-t).total_seconds()<=900 and (best_t is None or t>best_t): best,best_t=tick,t
                except (ValueError,TypeError):pass
    if best is None:
        w.writerow([bot,city,day,r['timestamp_utc'],r['result_for_research'],r['target_is_leader'],'no_prior_tick']); continue
    tb=best.get('target_bracket') or {}; same=bool(token) and str(tb.get('token_id',''))==token; ladder=best.get('market_full') or []; book=best.get('target_book') if same else None
    asks=(book or {}).get('asks') or []; ask=asks[0] if asks else None
    try: ask_price=float(ask[0]); ask_size=float(ask[1])
    except (TypeError,IndexError,ValueError,KeyError):ask_price=ask_size=''
    age=(entry-best_t).total_seconds()
    # Tick timestamps are written at seconds precision; same-second ordering
    # cannot be established against the subsecond order timestamp.
    status='same_second_ambiguous' if age<1 else 'prior_tick'
    w.writerow([bot,city,day,r['timestamp_utc'],r['result_for_research'],r['target_is_leader'],status,best_t.astimezone(dt.timezone.utc).isoformat(),round(age,2),same,len(ladder),sum(x.get('src')=='clob' for x in ladder if isinstance(x,dict)),sum(x.get('src')=='gamma' for x in ladder if isinstance(x,dict)),bool(book),ask_price,ask_size,r['paper_price'],bool(best.get('bought')),len(best.get('actions') or [])])
