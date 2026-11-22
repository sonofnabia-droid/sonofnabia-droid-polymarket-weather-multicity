#!/usr/bin/env python3
"""Research only: reconstruct logged PAPER entries and market filters."""
import collections,csv,datetime as dt,json,re,sqlite3
from pathlib import Path
root=Path(__file__).resolve().parents[2]; base=root/'experiments/lead_lag_pilot'; db=sqlite3.connect(f'file:{root / "data/polymarket_weather_2026.sqlite"}?mode=ro',uri=True); db.execute('PRAGMA query_only=ON')
ledgers={}
for bot,folder in [('A','live_bot_logs'),('B','live_bot_logs_v6'),('C','live_bot_logs_c')]:
    path=root/folder/'trade_ledger.jsonl'; rows=[]
    if path.exists():
        for line in path.open():
            try: rows.append(json.loads(line))
            except ValueError: pass
    ledgers[bot]=rows
w=csv.writer(__import__('sys').stdout); w.writerow(['bot','city','day','timestamp_utc','logged_status','ledger_status','ledger_source','gamma_target_yes','result_for_research','result_basis','paper_price','target_bracket','leader_bracket','target_is_leader','leader_price','above_target_price_sum','above_target_max','above_target_count','quotes_count','markets_count','p_rebound','context'])
for x in csv.DictReader((base/'paper_market_context.csv').open()):
    bot,city,day=x['bot'],x['city'],x['day']; folder={'A':'live_bot_logs','B':'live_bot_logs_v6','C':'live_bot_logs_c'}[bot]; path=root/folder/f'bets_{city}_{day}.json'
    try: data=json.loads(path.read_text()); recs=data if isinstance(data,list) else [data]
    except (OSError,ValueError):continue
    rec=None
    for candidate in recs:
        try:
            stamp=dt.datetime.fromisoformat(str(candidate.get('timestamp','')).replace('Z','+00:00'))
            if stamp.tzinfo and stamp.astimezone(dt.timezone.utc).isoformat()==x['decision_utc']: rec=candidate; break
        except (AttributeError,ValueError,TypeError): pass
    if rec is None:continue
    ledger=ledgers[bot]; order=rec.get('order_id'); opens=[z for z in ledger if z.get('event_type')=='BET_OPEN' and order and z.get('order_id')==order and z.get('token_id')==rec.get('token_id')]; closed=[]
    if len(opens)==1 and opens[0].get('position_id'):
        closed=[z for z in ledger if z.get('event_type')=='BET_CLOSE' and z.get('position_id')==opens[0]['position_id']]
    closed=closed if len(closed)==1 else []; ls=closed[0].get('result','') if closed else ''; lsource=closed[0].get('resolution_source','') if closed else ''
    gamma=x['gamma_closed_yes_price']; logged=x['status']; result=''; basis='unresolved_or_conflict'
    if ls in ('won','lost') and lsource=='official' and gamma in ('0.0','1.0') and ((ls=='won')==(float(gamma)==1)):
        result=ls; basis='ledger_official_matches_gamma'
    elif not closed and logged in ('won','lost') and gamma in ('0.0','1.0') and ((logged=='won')==(float(gamma)==1)):
        result=logged; basis='bets_matches_gamma_indicative'
    at=int(dt.datetime.fromisoformat(x['decision_utc']).timestamp()); markets=db.execute("SELECT m.bracket,t.token_id FROM markets m JOIN tokens t ON m.market_id=t.market_id WHERE m.city=? AND m.market_date=? AND t.outcome='YES'",(city,day)).fetchall(); quotes=[]
    for name,token in markets:
        q=db.execute('SELECT ts,price FROM price_points WHERE token_id=? AND fidelity_minutes=5 AND ts BETWEEN ? AND ? ORDER BY ts DESC LIMIT 1',(token,at-600,at)).fetchone()
        m=re.fullmatch(r'(-?\d+)°C(?: or (below|higher))?',name or '')
        if q and m: quotes.append((name,int(m.group(1)),m.group(2),float(q[1])))
    target=next((q for q in quotes if q[0]==x['target_bracket']),None); above=[]
    if target:
        # A lower-open target is followed by numerical brackets above its bound;
        # an upper-open target has no higher brackets in the partition.
        if target[2]!='higher': above=[q[3] for q in quotes if q[1]>target[1] and q[2]!='below']
    complete=bool(markets) and len(quotes)==len(markets) and target is not None and x['context_status']=='complete'
    w.writerow([bot,city,day,x['decision_utc'],logged,ls,lsource,gamma,result,basis,x['entry_ask'],x['target_bracket'],x['market_leader'],x['target_is_leader'],x['leader_price'],round(sum(above),6) if complete else '',max(above) if above else (0 if complete else ''),len(above) if complete else '',len(quotes),len(markets),x['p_rebound'],'complete' if complete else 'incomplete'])
db.close()
