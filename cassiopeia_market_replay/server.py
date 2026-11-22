#!/usr/bin/env python3
"""CASSIOPEIA Market Replay — local, read-only SQL/CSV service.

Requires only the Python standard library. Does not touch trading processes.
"""
from __future__ import annotations
import argparse
import csv
import json
import math
import os
import re
import sqlite3
import sys
import threading
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

ROOT = Path(__file__).resolve().parent.parent
STATIC = Path(__file__).resolve().parent
UTC = timezone.utc
CITY_RE = re.compile(r'^[a-z][a-z_]{0,50}$')


def connect_ro(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise FileNotFoundError(f'Não encontrei a SQLite: {path}')
    db = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA query_only=ON')
    db.execute('PRAGMA busy_timeout=5000')
    return db


def sql_table(db, table):
    return bool(db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone())


def parse_iso(s):
    try:
        d = datetime.fromisoformat(str(s).strip().replace('Z', '+00:00'))
        if d.tzinfo is None:
            d = d.replace(tzinfo=UTC)
        return int(d.timestamp())
    except (ValueError, TypeError, OverflowError):
        return None


def read_weather_csv(path: Path, start: int, end: int, zone: ZoneInfo):
    rows = []
    with path.open('r', encoding='utf-8-sig', errors='replace', newline='') as f:
        sample = f.read(4096)
        f.seek(0)
        dialect = csv.excel_tab if '\t' in sample.split('\n')[0] else csv.excel
        reader = csv.DictReader(f, dialect=dialect)
        if not reader.fieldnames:
            return []
        fields = {name.lower().strip(): name for name in reader.fieldnames if name}
        tempcol = next((fields[x] for x in ('temp_c','temperature_c','temperature','tmpc','temp') if x in fields), None)
        tscol = next((fields[x] for x in ('timestamp_utc','datetime_utc','time_utc') if x in fields), None)
        fallback = next((fields[x] for x in ('timestamp','datetime') if x in fields), None)
        if not tempcol or not (tscol or fallback or ('date' in fields and 'hour' in fields)):
            return []
        for r in reader:
            try:
                value = float((r.get(tempcol) or '').replace(',', '.'))
            except (ValueError, AttributeError):
                continue
            if not math.isfinite(value):
                continue
            ts = parse_iso(r.get(tscol or fallback)) if (tscol or fallback) else None
            if ts is None and 'date' in fields and 'hour' in fields:
                try:
                    day = str(r[fields['date']]).strip()
                    hr = int(float(r[fields['hour']]))
                    mm = int(float(r.get(fields.get('slot30', ''), 0) or 0))
                    naive = datetime.fromisoformat(day).replace(hour=hr, minute=mm)
                    ts = int(naive.replace(tzinfo=zone).timestamp())
                except (ValueError, TypeError, OverflowError):
                    pass
            if ts is not None and start <= ts < end:
                rows.append([ts, round(value, 3)])
    # On duplicate timestamps choose final observed row, never average conflicting samples.
    return [[ts, value] for ts, value in sorted(dict(rows).items())]


def read_wu_sqlite(path: Path, city: str, start: int, end: int):
    if not path.is_file():
        return []
    d = connect_ro(path)
    try:
        if not sql_table(d, 'wu_observations'):
            return []
        startstr = datetime.fromtimestamp(start, UTC).strftime('%Y-%m-%d %H:%M:%S')
        endstr = datetime.fromtimestamp(end, UTC).strftime('%Y-%m-%d %H:%M:%S')
        rows = d.execute('''SELECT timestamp_utc,temp_c FROM wu_observations
            WHERE city=? AND timestamp_utc>=? AND timestamp_utc<? AND temp_c IS NOT NULL
            ORDER BY timestamp_utc''', (city, startstr, endstr)).fetchall()
        values = {}
        for r in rows:
            ts = parse_iso(r['timestamp_utc'])
            if ts is not None:
                values[ts] = float(r['temp_c'])
        return [[ts, x] for ts, x in sorted(values.items())]
    finally:
        d.close()


def read_noaa_sqlite(path: Path, city: str, start: int, end: int):
    """Optional NOAA GHCNh archive: metar-derived and unadjusted station values."""
    if not path.is_file():
        return []
    out = []
    with closing(connect_ro(path)) as db:
        if not sql_table(db, 'observations'):
            return []
        columns = {r[1] for r in db.execute('PRAGMA table_info(observations)')}
        required = {'city', 'observed_at', 'temperature_metar', 'temperature_noaa', 'report_kind'}
        if not required <= columns:
            return []
        lo = datetime.fromtimestamp(start, UTC).strftime('%Y-%m-%d')
        hi = (datetime.fromtimestamp(end, UTC) + timedelta(days=1)).strftime('%Y-%m-%d')
        rows = db.execute('''SELECT observed_at, temperature_metar, temperature_noaa, report_kind
            FROM observations WHERE city=? AND observed_at>=? AND observed_at<?
            ORDER BY observed_at''', (city, lo, hi)).fetchall()
        metar, noaa = {}, {}
        for r in rows:
            ts = parse_iso(r['observed_at'])
            if ts is None or not start <= ts < end:
                continue
            if r['temperature_metar'] is not None and r['report_kind'] == 'METAR':
                metar[ts] = float(r['temperature_metar'])
            if r['temperature_noaa'] is not None:
                noaa[ts] = float(r['temperature_noaa'])
        if metar:
            out.append({'name': 'METAR (GHCNh)', 'source': str(path.relative_to(ROOT)),
                        'points': [[a, b] for a, b in sorted(metar.items())]})
        if noaa:
            out.append({'name': 'NOAA GHCNh', 'source': str(path.relative_to(ROOT)),
                        'points': [[a, b] for a, b in sorted(noaa.items())]})
    return out


def read_source_monitor(path: Path, city: str, start: int, end: int):
    """Optional current-time WU/AWC monitor data; no network request."""
    if not path.is_file():
        return []
    results = {}
    with closing(connect_ro(path)) as db:
        if not sql_table(db, 'observations'):
            return []
        columns = {r[1] for r in db.execute('PRAGMA table_info(observations)')}
        if not {'city', 'observed_at', 'temperature_c', 'source'} <= columns:
            return []
        lo = datetime.fromtimestamp(start, UTC).strftime('%Y-%m-%d')
        hi = (datetime.fromtimestamp(end, UTC) + timedelta(days=1)).strftime('%Y-%m-%d')
        rows = db.execute('''SELECT observed_at,temperature_c,source FROM observations
            WHERE city=? AND observed_at>=? AND observed_at<? AND temperature_c IS NOT NULL
            ORDER BY observed_at''', (city, lo, hi)).fetchall()
        for r in rows:
            ts = parse_iso(r['observed_at'])
            src = str(r['source'] or '').upper()
            if ts is not None and start <= ts < end and src in ('AWC', 'WU'):
                results.setdefault(src, {})[ts] = float(r['temperature_c'])
    return [{'name': src + ' monitor', 'source': str(path.relative_to(ROOT)),
             'points': [[ts, v] for ts, v in sorted(values.items())]}
            for src, values in sorted(results.items()) if values]


def load_weather(root: Path, city: str, start: int, end: int, zone, metar_dir: str | None):
    series=[]
    # Prefer directly archived WU observations when available.
    wu_db = root / 'historic_noaa' / 'ghcnh_history.sqlite'
    try:
        data = read_wu_sqlite(wu_db, city, start, end)
    except (sqlite3.Error, OSError, ValueError):
        data = []
    if data:
        series.append({'name':'WU', 'source':str(wu_db.relative_to(root)), 'points':data})
    elif (root / 'historic' / f'{city}.csv').exists():
        path=root / 'historic' / f'{city}.csv'
        series.append({'name':'Histórico meteorológico', 'source':str(path.relative_to(root)),
                       'points':read_weather_csv(path, start, end, zone)})
    try:
        series.extend(read_noaa_sqlite(wu_db, city, start, end))
    except (sqlite3.Error, OSError, ValueError):
        pass
    try:
        series.extend(read_source_monitor(root / 'weather_source_monitor.sqlite', city, start, end))
    except (sqlite3.Error, OSError, ValueError):
        pass
    if metar_dir:
        path = (root / metar_dir / f'{city}.csv').resolve()
        if path.is_file() and (root in path.parents):
            series.append({'name':'METAR CSV', 'source':str(path.relative_to(root)),
                           'points':read_weather_csv(path, start, end, zone)})
    return series


def market_sort_key(row):
    label = row.get('bracket') or ''
    match = re.search(r'-?\d+(?:[.,]\d+)?', label)
    val = float(match.group().replace(',', '.')) if match else 1e9
    return (val, label)


def catalog(path: Path):
    with closing(connect_ro(path)) as db:
        rows = db.execute('''SELECT e.city, COUNT(DISTINCT e.market_date) n,
                     MIN(e.market_date) first_day, MAX(e.market_date) last_day
            FROM events e WHERE e.status='found'
            AND EXISTS (SELECT 1 FROM markets m WHERE m.city=e.city AND m.market_date=e.market_date)
            GROUP BY e.city ORDER BY e.city''').fetchall()
        return {'cities':[dict(r) for r in rows]}


def dates(path: Path, city: str):
    with closing(connect_ro(path)) as db:
        return {'city':city,'dates':[r[0] for r in db.execute('''
            SELECT DISTINCT market_date FROM markets WHERE city=? ORDER BY market_date DESC''', (city,))]}


def load_replay(path: Path, root: Path, city: str, day_string: str, metar_dir: str | None):
    day = date.fromisoformat(day_string)
    with closing(connect_ro(path)) as db:
        evt = db.execute('SELECT timezone,title,status FROM events WHERE city=? AND market_date=?',
                         (city,day_string)).fetchone()
        tzname = evt['timezone'] if evt and evt['timezone'] else 'UTC'
        try:
            zone=ZoneInfo(tzname)
        except ZoneInfoNotFoundError:
            tzname='UTC'; zone=ZoneInfo('UTC')
        start_dt=datetime.combine(day,time.min,zone)
        end_dt=datetime.combine(day+timedelta(days=1),time.min,zone)
        start,end=int(start_dt.timestamp()),int(end_dt.timestamp())
        raw=db.execute('''SELECT m.market_id,m.question,m.bracket,m.closed,m.outcome_prices,
                t.token_id,t.outcome
            FROM markets m JOIN tokens t ON t.market_id=m.market_id
            WHERE m.city=? AND m.market_date=?
            ORDER BY m.market_id,t.outcome''',(city,day_string)).fetchall()
        if not raw:
            raise LookupError(f'Sem brackets para {city} em {day_string}')
        markets={}
        for r in raw:
            k=r['market_id']
            if k not in markets:
                markets[k]={'market_id':k,'bracket':r['bracket'] or r['question'] or k,
                            'question':r['question'],'closed':bool(r['closed']), 'tokens':{}}
            outcome=r['outcome'].upper()
            # only plot YES/NO in the first phase
            if outcome in ('YES','NO'):
                markets[k]['tokens'][outcome]={'id':r['token_id'],'prices':[],'books':[]}
        # Each statement uses token-first primary key index and a single day range.
        # Include a small pre-midnight baseline only; JavaScript enforces staleness limits.
        total_prices=0;total_books=0
        for m in markets.values():
            for outcome,t in m['tokens'].items():
                token=t['id']
                baseline=db.execute('''SELECT ts,price,fidelity_minutes FROM price_points
                    WHERE token_id=? AND ts<? AND ts>=? ORDER BY ts DESC,fidelity_minutes ASC LIMIT 1''',
                    (token,start,start-12*3600)).fetchone()
                vals={}
                if baseline: vals[int(baseline['ts'])]=[int(baseline['ts']),round(float(baseline['price']),5),int(baseline['fidelity_minutes'])]
                for r in db.execute('''SELECT ts,price,fidelity_minutes FROM price_points
                    WHERE token_id=? AND ts>=? AND ts<? ORDER BY ts ASC,fidelity_minutes DESC''',
                    (token,start,end)):
                    vals[int(r['ts'])]=[int(r['ts']),round(float(r['price']),5),int(r['fidelity_minutes'])]
                t['prices']=list(vals.values())
                total_prices+=len(vals)
                bs=[]
                if sql_table(db,'book_snapshots'):
                    for r in db.execute('''SELECT sampled_at,best_bid,bid_size,best_ask,ask_size
                        FROM book_snapshots WHERE token_id=? AND sampled_at>=? AND sampled_at<?
                        ORDER BY sampled_at''', (token,start-20*60,end)):
                        bs.append([int(r[0]),r[1],r[2],r[3],r[4]])
                t['books']=bs;total_books+=len(bs)
        weather=load_weather(root,city,start,end,zone,metar_dir)
        return {'city':city,'date':day_string,'title':evt['title'] if evt else None,
                'timezone':tzname,'start':start,'end':end,
                'markets':sorted(markets.values(),key=market_sort_key),
                'weather':weather,
                'statistics':{'brackets':len(markets),'price_points':total_prices,
                              'book_snapshots':total_books,
                              'temperature_points':sum(len(x['points']) for x in weather)}}


class Handler(BaseHTTPRequestHandler):
    server_version='CassiopeiaReplay/1.0'
    def log_message(self,fmt,*args):
        print('%s %s' % (self.log_date_time_string(),fmt%args),file=sys.stderr)

    def _send(self,status,ctype,data):
        self.send_response(status)
        self.send_header('Content-Type',ctype)
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Content-Security-Policy',"default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; img-src 'self' data:")
        self.send_header('Content-Length',str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url=urlparse(self.path)
        try:
            if url.path in ('/','/index.html'):
                blob=(STATIC/'index.html').read_bytes()
                return self._send(200,'text/html; charset=utf-8',blob)
            if url.path in ('/app.js','/styles.css'):
                kind = 'application/javascript; charset=utf-8' if url.path.endswith('.js') else 'text/css; charset=utf-8'
                return self._send(200,kind,(STATIC/url.path.lstrip('/')).read_bytes())
            if url.path=='/api/catalog':
                data=catalog(self.server.db_path)
            elif url.path=='/api/dates':
                q=parse_qs(url.query)
                city=q.get('city',[''])[0]
                if not CITY_RE.fullmatch(city): raise ValueError('Cidade inválida')
                data=dates(self.server.db_path,city)
            elif url.path=='/api/replay':
                q=parse_qs(url.query)
                city=q.get('city',[''])[0]; day=q.get('date',[''])[0]
                if not CITY_RE.fullmatch(city): raise ValueError('Cidade inválida')
                if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',day): raise ValueError('Data inválida')
                data=load_replay(self.server.db_path,self.server.root,city,day,self.server.metar_dir)
            else:
                return self._send(404,'application/json; charset=utf-8',json.dumps({'error':'Não encontrado'},ensure_ascii=False).encode('utf-8'))
            blob=json.dumps(data,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode('utf-8')
            return self._send(200,'application/json; charset=utf-8',blob)
        except (ValueError,LookupError) as exc:
            return self._send(400,'application/json; charset=utf-8',json.dumps({'error':str(exc)},ensure_ascii=False).encode())
        except (OSError,sqlite3.Error) as exc:
            print(type(exc).__name__,str(exc),file=sys.stderr)
            return self._send(503,'application/json; charset=utf-8',json.dumps({'error':'Ficheiro ou SQLite indisponível: '+str(exc)},ensure_ascii=False).encode())
        except Exception as exc:
            print(type(exc).__name__,str(exc),file=sys.stderr)
            return self._send(500,'application/json; charset=utf-8',b'{"error":"Erro inesperado; consultar log do servidor"}')


def main():
    p=argparse.ArgumentParser(description='Cassiopeia — Replay de mercados, 100% read-only')
    p.add_argument('--db',default='data/polymarket_weather_2026.sqlite')
    p.add_argument('--port',type=int,default=8788)
    p.add_argument('--host',default='127.0.0.1',help='Local por segurança; não expor à rede por omissão')
    p.add_argument('--metar-csv-dir',default=None,help='Pasta opcional de ficheiros <city>.csv com timestamp_utc,temp_c')
    args=p.parse_args()
    db=(ROOT/args.db).resolve()
    if not db.exists():
        p.error('SQLite não encontrada: '+str(db))
    with closing(connect_ro(db)) as check:
        for table in ('events','markets','tokens','price_points','book_snapshots'):
            if not sql_table(check,table):p.error('Tabela em falta: '+table)
    s=ThreadingHTTPServer((args.host,args.port),Handler)
    s.db_path=db;s.root=ROOT;s.metar_dir=args.metar_csv_dir
    print(f'CASSIOPEIA Market Replay | http://{args.host}:{args.port}/',flush=True)
    print(f'SQLite (READ ONLY): {db}',flush=True)
    print('Sem trades. Sem alterações na BD, bots ou dashboard existente.',flush=True)
    try:s.serve_forever()
    except KeyboardInterrupt:pass
    finally:s.server_close()

if __name__=='__main__':main()
