#!/usr/bin/env python3
"""Read existing PAPER bets and indexed market context; never place orders."""
import csv,datetime as dt,json,sqlite3
from pathlib import Path
root=Path(__file__).resolve().parents[2]; db=sqlite3.connect(f'file:{root / "data/polymarket_weather_2026.sqlite"}?mode=ro',uri=True); db.execute('PRAGMA query_only=ON')
w=csv.writer(__import__('sys').stdout); w.writerow(['bot','city','day','decision_utc','status','simulated','entry_ask','raw_ask','p_rebound','target_bracket','target_history_price','market_leader','leader_price','target_is_leader','market_tokens','priced_tokens','target_book_bid','target_book_ask','book_sample_utc','context_status','gamma_closed_yes_price','status_matches_gamma','target_price_timestamp_utc'])
for bot,folder in [('A','live_bot_logs'),('B','live_bot_logs_v6'),('C','live_bot_logs_c')]:
    for city in ('lucknow','munich'):
        for path in sorted((root/folder).glob(f'bets_{city}_*.json')):
            day=path.stem.rsplit('_',1)[-1]
            try: data=json.loads(path.read_text()); records=data if isinstance(data,list) else [data]
            except (OSError,ValueError): continue
            for rec in records:
                if not isinstance(rec,dict) or rec.get('simulated') is not True: continue
                try:
                    instant=dt.datetime.fromisoformat(str(rec.get('timestamp','')).replace('Z','+00:00'))
                    if instant.tzinfo is None: continue
                    at=int(instant.timestamp())
                except (ValueError,TypeError): continue
                markets=db.execute("SELECT m.bracket,t.token_id FROM markets m JOIN tokens t ON m.market_id=t.market_id WHERE m.city=? AND m.market_date=? AND t.outcome='YES'",(city,day)).fetchall(); target=next((name for name,token in markets if str(token)==str(rec.get('token_id',''))),None)
                quotes=[]; target_price_ts=None
                for name,token in markets:
                    q=db.execute('SELECT ts,price FROM price_points WHERE token_id=? AND fidelity_minutes=5 AND ts BETWEEN ? AND ? ORDER BY ts DESC LIMIT 1',(token,at-600,at)).fetchone()
                    if q:
                        quotes.append((float(q[1]),name))
                        if name==target: target_price_ts=q[0]
                book=db.execute('SELECT sampled_at,best_bid,best_ask FROM book_snapshots WHERE token_id=? AND sampled_at BETWEEN ? AND ? ORDER BY sampled_at DESC LIMIT 1',(str(rec.get('token_id','')),at-600,at)).fetchone()
                target_quote=next((p for p,name in quotes if name==target),None)
                complete=bool(markets) and len(markets)==len(quotes) and target is not None
                leader=max(quotes) if complete else None
                tie=bool(leader) and sum(p==leader[0] for p,n in quotes)>1
                archived=db.execute('SELECT m.closed,m.outcome_prices,m.raw_json FROM markets m JOIN tokens t ON t.market_id=m.market_id WHERE t.token_id=?',(str(rec.get('token_id','')),)).fetchone(); final=''; consistent=''
                if archived:
                    try:
                        obj=json.loads(archived[2]); outcomes=obj.get('outcomes',[]); outcomes=json.loads(outcomes) if isinstance(outcomes,str) else outcomes; ix=next(i for i,x in enumerate(outcomes) if str(x).upper()=='YES'); value=float(json.loads(archived[1])[ix])
                        if archived[0] and value in (0,1):
                            final=value
                            if rec.get('status') in ('won','lost'): consistent=(rec['status']=='won')==(value==1)
                    except (ValueError,TypeError,IndexError,StopIteration): pass
                w.writerow([bot,city,day,instant.astimezone(dt.timezone.utc).isoformat(),rec.get('status',''),rec.get('simulated'),rec.get('ask',''),rec.get('raw_ask',''),rec.get('p_rebound',''),target or '',target_quote if target_quote is not None else '',leader[1] if leader and not tie else '',leader[0] if leader and not tie else '',target==leader[1] if leader and not tie else '',len(markets),len(quotes),book[1] if book and book[1] is not None else '',book[2] if book and book[2] is not None else '',dt.datetime.fromtimestamp(book[0],dt.timezone.utc).isoformat() if book else '', 'complete' if complete and not tie else 'incomplete_or_tied',final,consistent,dt.datetime.fromtimestamp(target_price_ts,dt.timezone.utc).isoformat() if target_price_ts is not None else ''])
db.close()
