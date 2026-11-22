#!/usr/bin/env python3
"""Descriptive 15 Nov raw AWC reported times vs sampled books; no label access."""
import collections,csv,datetime as dt,json,math,re,sqlite3,sys
from pathlib import Path
from zoneinfo import ZoneInfo
root=Path(__file__).resolve().parents[2]; sys.path.insert(0,str(root))
from noaa_metar_eligibility_audit import parse_report
db=sqlite3.connect(f'file:{root / "data/polymarket_weather_2026.sqlite"}?mode=ro',uri=True); db.execute('PRAGMA query_only=ON')
reports=collections.defaultdict(list)
with (root/'forecast_benchmark'/'metar_raw.jsonl').open() as f:
    for line in f:
        try:
            r=json.loads(line); city=r.get('city')
            if city not in ('lucknow','munich'):continue
            zone=ZoneInfo('Asia/Kolkata' if city=='lucknow' else 'Europe/Berlin'); obs=dt.datetime.fromtimestamp(int(r['obs_time']),dt.timezone.utc)
            if obs.astimezone(zone).date().isoformat()!='2026-11-15':continue
            receipt=dt.datetime.fromisoformat(r['raw']['receiptTime'].replace('Z','+00:00')); start=dt.datetime.fromisoformat(r['collected_utc'].replace('Z','+00:00')); kind,corrected,temp,method=parse_report(r['raw'].get('rawOb'),r['icao'])
            if kind!='METAR' or temp is None:continue
            reports[city].append((obs,receipt,start,float(temp),method))
        except (KeyError,ValueError,TypeError):pass
w=csv.writer(sys.stdout); w.writerow(['city','day','observation_utc','awc_receipt_field_utc','collector_run_start_utc','prior_max','temp_c','bracket','at','yes_snapshot_utc','yes_bid','yes_bid_size','yes_ask','yes_ask_size','no_snapshot_utc','no_bid','no_bid_size','no_ask','no_ask_size','timing_note'])
for city in ('lucknow','munich'):
    seq=sorted(reports[city]); peak=None; n=0
    for obs,receipt,start,temp,method in seq:
        prior=peak; peak=temp if peak is None else max(peak,temp); n+=1
        if prior is None or n<4 or temp<=prior:continue
        old=int(math.floor(prior+.5)); new=int(math.floor(temp+.5)); markets=db.execute("SELECT m.bracket,t.outcome,t.token_id FROM markets m JOIN tokens t ON m.market_id=t.market_id WHERE m.city=? AND m.market_date=?",(city,'2026-11-15')).fetchall(); groups=collections.defaultdict(dict)
        for name,outcome,token in markets:
            m=re.fullmatch(r'(-?\d+)°C(?: or (below|higher))?',name or '')
            if m and m.group(2)!='higher' and old<=int(m.group(1))<new:groups[(int(m.group(1)),name)][outcome.upper()]=token
        if not groups:continue
        key=max(groups); tokens=groups[key]
        for tag,t in [('observation',obs),('awc_receipt_field',receipt)]:
            at=int(t.timestamp()); books=[]
            for outcome in ('YES','NO'):
                token=tokens.get(outcome); books.append(db.execute('SELECT sampled_at,best_bid,bid_size,best_ask,ask_size FROM book_snapshots WHERE token_id=? AND sampled_at BETWEEN ? AND ? ORDER BY sampled_at DESC LIMIT 1',(token,at-600,at)).fetchone() if token else None)
            yes,no=books; fmt=lambda row:dt.datetime.fromtimestamp(row[0],dt.timezone.utc).isoformat() if row else ''
            val=lambda row,i:row[i] if row and row[i] is not None else ''
            w.writerow([city,'2026-11-15',obs.isoformat(),receipt.isoformat(),start.isoformat(),prior,temp,key[1],tag,fmt(yes),val(yes,1),val(yes,2),val(yes,3),val(yes,4),fmt(no),val(no,1),val(no,2),val(no,3),val(no,4),'YES/NO timestamps independent; sides are sampled best levels, not fills; receiptTime semantics and public availability unverified; no outcome accessed'])
db.close()
