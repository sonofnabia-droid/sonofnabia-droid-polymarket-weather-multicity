#!/usr/bin/env python3
"""Polymarket daily HIGH temperature markets -> SQLite.

Read-only. Uses Gamma event metadata, CLOB batch price history (YES and NO),
and optional current order-book snapshots. Does not place orders.

Quick pilot (in the POLY-MULTI-CITY-V2 project):
  ./venv/bin/python polymarket_weather_archive.py --cities munich --since 2026-11-12 --until 2026-11-14

Full resumable backfill (available 2026 dates, all project cities):
  ./venv/bin/python polymarket_weather_archive.py --since 2026-01-01 --fidelity 5

Historical price series is NOT a historical executable ask/bid.
"""
from __future__ import annotations

import argparse
import calendar
import datetime as dt
import json
import os
import re
import shutil
import sqlite3
import sys
import time
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
UTC = dt.timezone.utc


def iso_now():
    return dt.datetime.now(UTC).isoformat(timespec="seconds")


def parse_date(s):
    return dt.date.fromisoformat(s)


def parse_array(value):
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except (ValueError, TypeError):
            return []
    return []


def get_project_cities():
    try:
        from cities.config import CITIES
    except ImportError as exc:
        raise SystemExit(
            "Nao consegui importar cities.config.CITIES. Executa a partir da pasta do "
            "projeto ou especifica --cities munich,madrid,..."
        ) from exc
    if isinstance(CITIES, dict):
        names = list(CITIES.keys())
    else:
        names = list(CITIES)
    return sorted(str(x) for x in names)


def city_timezone(city):
    try:
        from cities.config import get_city
        return str(get_city(city).timezone)
    except Exception:
        # Do NOT pretend to know a city's local time. An explicit UTC fallback is recorded.
        return "UTC"


def slug_for(city, day):
    # Seoul (Incheon) is published in Gamma under the 'seoul' city slug.
    name = {"seoul_incheon": "seoul", "seoul-incheon": "seoul"}.get(city, city)
    name = name.strip().lower().replace("_", "-").replace(" ", "-")
    return f"highest-temperature-in-{name}-on-{calendar.month_name[day.month].lower()}-{day.day}-{day.year}"


def connect_db(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(path), timeout=30)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript("""
    CREATE TABLE IF NOT EXISTS events (
        city TEXT NOT NULL, market_date TEXT NOT NULL, slug TEXT NOT NULL,
        event_id TEXT, title TEXT, timezone TEXT NOT NULL,
        status TEXT NOT NULL, checked_at TEXT NOT NULL,
        raw_json TEXT, error TEXT,
        PRIMARY KEY(city, market_date)
    );
    CREATE TABLE IF NOT EXISTS markets (
        market_id TEXT PRIMARY KEY, city TEXT NOT NULL,
        market_date TEXT NOT NULL, event_slug TEXT NOT NULL,
        question TEXT, bracket TEXT, closed INTEGER,
        start_date TEXT, end_date TEXT, outcome_prices TEXT,
        raw_json TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_markets_city_day ON markets(city, market_date);
    CREATE TABLE IF NOT EXISTS tokens (
        token_id TEXT PRIMARY KEY, market_id TEXT NOT NULL,
        outcome TEXT NOT NULL,
        FOREIGN KEY(market_id) REFERENCES markets(market_id)
    );
    CREATE INDEX IF NOT EXISTS idx_tokens_market ON tokens(market_id);
    CREATE TABLE IF NOT EXISTS price_points (
        token_id TEXT NOT NULL, ts INTEGER NOT NULL, fidelity_minutes INTEGER NOT NULL,
        price REAL NOT NULL, source TEXT NOT NULL DEFAULT 'clob_price_history',
        PRIMARY KEY(token_id, ts, fidelity_minutes),
        FOREIGN KEY(token_id) REFERENCES tokens(token_id)
    );
    CREATE INDEX IF NOT EXISTS idx_price_ts ON price_points(ts);
    CREATE TABLE IF NOT EXISTS history_chunks (
        token_id TEXT NOT NULL, start_ts INTEGER NOT NULL, end_ts INTEGER NOT NULL,
        fidelity_minutes INTEGER NOT NULL, status TEXT NOT NULL,
        points INTEGER NOT NULL DEFAULT 0, checked_at TEXT NOT NULL, error TEXT,
        PRIMARY KEY(token_id,start_ts,end_ts,fidelity_minutes),
        FOREIGN KEY(token_id) REFERENCES tokens(token_id)
    );
    CREATE TABLE IF NOT EXISTS book_snapshots (
        token_id TEXT NOT NULL, sampled_at INTEGER NOT NULL,
        best_bid REAL, bid_size REAL, best_ask REAL, ask_size REAL,
        bids_json TEXT, asks_json TEXT,
        PRIMARY KEY(token_id,sampled_at),
        FOREIGN KEY(token_id) REFERENCES tokens(token_id)
    );
    CREATE VIEW IF NOT EXISTS price_by_city AS
        SELECT m.city, m.market_date, m.bracket, m.question, t.outcome,
               p.ts, datetime(p.ts,'unixepoch') AS timestamp_utc,
               p.price, p.fidelity_minutes, p.source, t.token_id
        FROM price_points p JOIN tokens t ON t.token_id=p.token_id
        JOIN markets m ON m.market_id=t.market_id;
    """)
    db.commit()
    return db


def enforce_storage_budget(db_path, max_gib, min_free_gib):
    path = Path(db_path)
    db_files = (path, Path(str(path) + "-wal"), Path(str(path) + "-shm"))
    used = sum(f.stat().st_size for f in db_files if f.exists())
    free = shutil.disk_usage(path.parent).free
    gib = 1024 ** 3
    if used >= max_gib * gib:
        raise SystemExit(f"LIMITE SQLITE: {used/gib:.2f} GiB >= {max_gib:g} GiB. Paragem segura.")
    if free <= min_free_gib * gib:
        raise SystemExit(f"DISCO LIVRE: {free/gib:.2f} GiB <= reserva de {min_free_gib:g} GiB. Paragem segura.")


class APIError(Exception):
    pass


class Client:
    def __init__(self, delay):
        self.delay = delay
        self.next_request = 0.0
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "CassiopeiaWeatherResearch/1.0 (read-only)",
                                     "Accept": "application/json"})

    def request(self, method, url, *, params=None, payload=None, allow_404=False):
        for attempt in range(5):
            wait = self.next_request - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self.next_request = time.monotonic() + self.delay
            try:
                r = self.session.request(method, url, params=params, json=payload,
                                         timeout=(10, 40))
            except requests.RequestException as exc:
                if attempt == 4:
                    raise APIError(str(exc)) from exc
                time.sleep(min(30, 2 ** attempt))
                continue
            if r.status_code == 404 and allow_404:
                return None
            if r.status_code in (429, 500, 502, 503, 504):
                if attempt == 4:
                    raise APIError(f"HTTP {r.status_code} {url}: {r.text[:180]}")
                retry = r.headers.get("Retry-After", "")
                try:
                    pause = float(retry)
                except ValueError:
                    pause = min(45, 2 ** (attempt + 1))
                time.sleep(min(90, max(1, pause)))
                continue
            if r.status_code >= 400:
                raise APIError(f"HTTP {r.status_code} {url}: {r.text[:180]}")
            try:
                return r.json()
            except ValueError as exc:
                raise APIError(f"JSON invalido {url}: {r.text[:120]}") from exc
        raise APIError("Tentativas esgotadas")

    def event(self, slug):
        return self.request("GET", f"{GAMMA}/events/slug/{slug}", allow_404=True)

    def history(self, tokens, start, end, fidelity):
        payload = {"markets": tokens, "start_ts": start, "end_ts": end,
                   "fidelity": fidelity}
        try:
            result = self.request("POST", f"{CLOB}/batch-prices-history", payload=payload)
            if not isinstance(result, dict) or not isinstance(result.get("history"), dict):
                raise APIError(f"Formato batch inesperado: {str(result)[:120]}")
            values = result["history"]
            # Some APIs omit tokens with no data; we preserve this as EMPTY, never synthesize prices.
            return {tok: values.get(tok, []) for tok in tokens}
        except APIError as exc:
            # On endpoint incompatibility, use the documented single-token API.
            if not ("HTTP 400 " in str(exc) or "HTTP 404 " in str(exc)
                    or "HTTP 422 " in str(exc)):
                raise
            print(f"  [AVISO] Batch indisponivel; fallback GET por token: {str(exc)[:90]}")
            output = {}
            for tok in tokens:
                res = self.request("GET", f"{CLOB}/prices-history", params={
                    "market": tok, "startTs": start, "endTs": end, "fidelity": fidelity})
                if not isinstance(res, dict) or not isinstance(res.get("history"), list):
                    raise APIError(f"Formato GET inesperado token {tok[:12]}")
                output[tok] = res["history"]
            return output

    def books(self, tokens):
        res = self.request("POST", f"{CLOB}/books",
                           payload=[{"token_id": tok} for tok in tokens])
        if not isinstance(res, list):
            raise APIError(f"Formato books inesperado: {str(res)[:160]}")
        return res


def infer_bracket(m):
    bracket = m.get("groupItemTitle") or m.get("shortTitle")
    if bracket:
        return str(bracket)
    question = str(m.get("question", ""))
    hit = re.search(r"\bbe\s+(.+?)\s+on\s+\w+\s+\d{1,2}\b", question, re.I)
    return hit.group(1).strip() if hit else None


def save_event(db, city, day, tzname, slug, data):
    if not isinstance(data, dict) or not isinstance(data.get("markets"), list):
        raise APIError("Gamma devolveu evento sem lista markets; nao guardar como encontrado")
    if not data["markets"]:
        raise APIError("Evento Gamma sem brackets/markets")
    with db:
        db.execute("""INSERT INTO events(city,market_date,slug,event_id,title,timezone,status,checked_at,raw_json,error)
          VALUES(?,?,?,?,?,?,?,?,?,NULL)
          ON CONFLICT(city,market_date) DO UPDATE SET
          slug=excluded.slug,event_id=excluded.event_id,title=excluded.title,
          timezone=excluded.timezone,status=excluded.status,checked_at=excluded.checked_at,
          raw_json=excluded.raw_json,error=NULL""",
          (city,day.isoformat(),slug,str(data.get("id","")),data.get("title"),
           tzname,"found",iso_now(),json.dumps(data,ensure_ascii=False)))
        for m in data["markets"]:
            if not isinstance(m, dict) or not m.get("id"):
                continue
            market_id = str(m["id"])
            db.execute("""INSERT INTO markets(market_id,city,market_date,event_slug,question,
                bracket,closed,start_date,end_date,outcome_prices,raw_json)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(market_id) DO UPDATE SET
                question=excluded.question,bracket=excluded.bracket,closed=excluded.closed,
                start_date=excluded.start_date,end_date=excluded.end_date,
                outcome_prices=excluded.outcome_prices,raw_json=excluded.raw_json""",
                (market_id,city,day.isoformat(),slug,m.get("question"),infer_bracket(m),
                 int(bool(m.get("closed"))),m.get("startDate"),m.get("endDate"),
                 json.dumps(parse_array(m.get("outcomePrices"))),
                 json.dumps(m,ensure_ascii=False)))
            outcomes = [str(v).lower() for v in parse_array(m.get("outcomes"))]
            token_ids = parse_array(m.get("clobTokenIds"))
            for i, token_id in enumerate(token_ids):
                if not token_id:
                    continue
                label = outcomes[i].upper() if i < len(outcomes) else f"OUTCOME_{i}"
                db.execute("""INSERT INTO tokens(token_id,market_id,outcome) VALUES(?,?,?)
                    ON CONFLICT(token_id) DO UPDATE SET market_id=excluded.market_id,
                    outcome=excluded.outcome""", (str(token_id),market_id,label))


def upsert_discovery_failure(db, city, day, tzname, slug, status, error=None):
    with db:
        db.execute("""INSERT INTO events(city,market_date,slug,timezone,status,checked_at,error)
            VALUES(?,?,?,?,?,?,?) ON CONFLICT(city,market_date) DO UPDATE SET
            status=excluded.status,checked_at=excluded.checked_at,error=excluded.error""",
            (city,day.isoformat(),slug,tzname,status,iso_now(),error))


def chunk_bounds(day, tzname, pre_days, post_hours, chunk_hours):
    tz = ZoneInfo(tzname)
    local_midnight = dt.datetime.combine(day, dt.time.min, tzinfo=tz)
    start = int((local_midnight - dt.timedelta(days=pre_days)).timestamp())
    end = int((local_midnight + dt.timedelta(days=1, hours=post_hours)).timestamp())
    end = min(end, int(dt.datetime.now(UTC).timestamp()))
    step = chunk_hours * 3600
    while start < end:
        next_end = min(start + step, end)
        yield start, next_end
        start = next_end


def should_refresh(row, day, args):
    if row is None:
        return True
    recent = (dt.datetime.now(UTC).date() - day).days <= args.refresh_recent_days
    if recent:
        return True
    if row["status"] == "not_found":
        return args.retry_missing
    if row["status"] == "error":
        return True
    return False


def process_one(db, api, city, day, args):
    slug = slug_for(city, day)
    tzname = city_timezone(city)
    try:
        ZoneInfo(tzname)
    except Exception:
        tzname = "UTC"
    old = db.execute("SELECT status FROM events WHERE city=? AND market_date=?",
                     (city,day.isoformat())).fetchone()
    if should_refresh(old, day, args):
        try:
            event = api.event(slug)
            if event is None:
                upsert_discovery_failure(db,city,day,tzname,slug,"not_found")
                return "not_found", 0
            if str(event.get("slug", "")) != slug:
                raise APIError("Slug Gamma nao coincide com o solicitado")
            save_event(db,city,day,tzname,slug,event)
        except APIError as exc:
            upsert_discovery_failure(db,city,day,tzname,slug,"error",str(exc))
            return "error",0
    elif old["status"] != "found":
        return old["status"],0

    token_ids = [r[0] for r in db.execute("""SELECT t.token_id FROM tokens t
        JOIN markets m ON m.market_id=t.market_id
        WHERE m.city=? AND m.market_date=? ORDER BY t.token_id""",
        (city, day.isoformat()))]
    if not token_ids:
        upsert_discovery_failure(db,city,day,tzname,slug,"error","Evento sem token IDs")
        return "error",0

    npoints=0
    for start,end in chunk_bounds(day,tzname,args.pre_days,args.post_hours,args.chunk_hours):
        recent = (dt.datetime.now(UTC).date() - day).days <= args.refresh_recent_days
        for j in range(0,len(token_ids),20):
            group=token_ids[j:j+20]
            pending=[]
            for tok in group:
                row=db.execute("""SELECT status FROM history_chunks WHERE token_id=? AND
                      start_ts=? AND end_ts=? AND fidelity_minutes=?""",
                      (tok,start,end,args.fidelity)).fetchone()
                if row and not recent and (row[0]=="ok" or
                   (row[0]=="empty" and not args.retry_empty)):
                    continue
                pending.append(tok)
            if not pending:
                continue
            enforce_storage_budget(args.db, args.max_db_gib, args.min_free_gib)
            try:
                history=api.history(pending,start,end,args.fidelity)
                entries=[]
                states=[]
                for tok in pending:
                    points=history[tok]
                    if not isinstance(points,list):
                        raise APIError(f"Dados invalidos token {tok[:12]}")
                    valid=0
                    for obj in points:
                        if not isinstance(obj,dict):
                            continue
                        try:
                            timestamp=int(obj["t"])
                            price=float(obj["p"])
                        except (KeyError,ValueError,TypeError,OverflowError):
                            continue
                        if start<=timestamp<=end and 0<=price<=1:
                            entries.append((tok,timestamp,args.fidelity,price))
                            valid+=1
                    states.append((tok,start,end,args.fidelity,"ok" if valid else "empty",valid,iso_now(),None))
                with db:
                    db.executemany("""INSERT INTO price_points(token_id,ts,fidelity_minutes,price)
                      VALUES(?,?,?,?) ON CONFLICT(token_id,ts,fidelity_minutes)
                      DO UPDATE SET price=excluded.price""",entries)
                    db.executemany("""INSERT INTO history_chunks(token_id,start_ts,end_ts,
                      fidelity_minutes,status,points,checked_at,error)
                      VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(token_id,start_ts,end_ts,fidelity_minutes)
                      DO UPDATE SET status=excluded.status,points=excluded.points,
                      checked_at=excluded.checked_at,error=excluded.error""",states)
                npoints+=len(entries)
            except (APIError,KeyError) as exc:
                with db:
                    db.executemany("""INSERT INTO history_chunks(token_id,start_ts,end_ts,
                      fidelity_minutes,status,points,checked_at,error)
                      VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(token_id,start_ts,end_ts,fidelity_minutes)
                      DO UPDATE SET status=excluded.status,checked_at=excluded.checked_at,
                      error=excluded.error""",
                      [(tok,start,end,args.fidelity,"error",0,iso_now(),str(exc)[:300])
                       for tok in pending])
                print(f"  [ERRO HIST] {city} {day} {str(exc)[:160]}",file=sys.stderr)
    return "found",npoints


def snapshot_books(db, api, cities, day, args):
    # Read-only live snapshot; historical /books does NOT exist.
    now=int(time.time())
    total=0
    for city in cities:
        cached=db.execute(
            "SELECT 1 FROM events WHERE city=? AND market_date=? AND status='found'",
            (city,day.isoformat())).fetchone()
        if not cached:
            slug=slug_for(city,day)
            try:
                event=api.event(slug)
                if not event:
                    print(f"[BOOK] {city}: ainda nao existe evento para {day}")
                    continue
                if event.get("slug") != slug:
                    raise APIError("Slug nao coincide com o solicitado")
                save_event(db,city,day,city_timezone(city),slug,event)
            except APIError as exc:
                print(f"[BOOK ERRO] {city}: {exc}",file=sys.stderr)
                continue
        tokens=[r[0] for r in db.execute("""SELECT t.token_id FROM tokens t
            JOIN markets m ON m.market_id=t.market_id
            WHERE m.city=? AND m.market_date=? AND COALESCE(m.closed,0)=0""",
            (city,day.isoformat()))]
        for i in range(0,len(tokens),20):
            group=tokens[i:i+20]
            try:
                books=api.books(group)
                records=[]
                for b in books:
                    token=str(b.get("asset_id", ""))
                    if token not in group:
                        continue
                    bids=b.get("bids") or []
                    asks=b.get("asks") or []
                    def top(levels, maxside):
                        valid=[]
                        for q in levels:
                            try:
                                valid.append((float(q["price"]),float(q["size"])))
                            except (TypeError,ValueError,KeyError):
                                pass
                        return (max(valid,key=lambda x:x[0]) if maxside else
                                min(valid,key=lambda x:x[0])) if valid else (None,None)
                    bid,bid_size=top(bids,True)
                    ask,ask_size=top(asks,False)
                    records.append((token,now,bid,bid_size,ask,ask_size,
                                    json.dumps(bids),json.dumps(asks)))
                with db:
                    db.executemany("""INSERT OR REPLACE INTO book_snapshots
                        (token_id,sampled_at,best_bid,bid_size,best_ask,ask_size,bids_json,asks_json)
                        VALUES(?,?,?,?,?,?,?,?)""",records)
                total+=len(records)
            except APIError as exc:
                print(f"[BOOK ERRO] {city}: {exc}",file=sys.stderr)
    print(f"Order books arquivados: {total} tokens; instante UTC {dt.datetime.fromtimestamp(now,UTC)}")


def stats(db):
    for table in ("events","markets","tokens","price_points","history_chunks","book_snapshots"):
        n=db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"{table:18s} {n:>14,d}")
    print("Estado dos eventos:")
    for status,count in db.execute("SELECT status,COUNT(*) FROM events GROUP BY status ORDER BY status"):
        print(f"  {status:12s}: {count:,}")
    print("Estado dos chunks:")
    for status,count in db.execute("SELECT status,COUNT(*) FROM history_chunks GROUP BY status ORDER BY status"):
        print(f"  {status:12s}: {count:,}")
    print("Cobertura por cidade:")
    for row in db.execute("""SELECT city,COUNT(*) n,SUM(status='found') found,
        SUM(status='not_found') missing FROM events GROUP BY city ORDER BY city"""):
        print(f"  {row[0]:22s} dias={row[1]:4d} mercados={row[2] or 0:4d} sem_evento={row[3] or 0:4d}")


def main():
    p=argparse.ArgumentParser(description="Arquivo meteorologico Polymarket 2026 -> SQLite, SEM trades")
    p.add_argument("--mode",choices=["backfill","status","snapshot"],default="backfill")
    p.add_argument("--db",default="data/polymarket_weather_2026.sqlite")
    p.add_argument("--cities",help="Lista separada por virgulas; default cities.config.CITIES")
    p.add_argument("--since",default="2026-01-01")
    p.add_argument("--until",default=dt.datetime.now(UTC).date().isoformat())
    p.add_argument("--fidelity",type=int,default=5,help="Minutos da serie de precos: 5 recomendado, 1 alta resolucao")
    p.add_argument("--delay",type=float,default=0.20,help="Pausa minima global entre pedidos HTTP")
    p.add_argument("--pre-days",type=int,default=3,help="Dias antes do dia do contrato para capturar abertura")
    p.add_argument("--post-hours",type=int,default=6,help="Horas depois do dia local")
    p.add_argument("--chunk-hours",type=int,default=24)
    p.add_argument("--max-days",type=int,default=0,help="Limitar a N dias por cidade, para piloto")
    p.add_argument("--max-db-gib",type=float,default=25.0)
    p.add_argument("--min-free-gib",type=float,default=8.0)
    p.add_argument("--retry-missing",action="store_true",help="Rever datas antigas sem evento")
    p.add_argument("--retry-empty",action="store_true",help="Rever chunks historicos sem precos")
    p.add_argument("--refresh-recent-days",type=int,default=3)
    args=p.parse_args()
    if args.fidelity<1 or args.delay<0 or args.pre_days<0 or args.post_hours<0 or args.chunk_hours<1 or args.max_db_gib<=0 or args.min_free_gib<0:
        p.error("fidelity >=1, delay/pre-days/post-hours>=0, chunk-hours>=1")
    db=connect_db(args.db)
    db.row_factory=sqlite3.Row
    if args.mode=="status":
        stats(db); return
    cities=([s.strip() for s in args.cities.split(",") if s.strip()]
            if args.cities else get_project_cities())
    if not cities:
        p.error("Nenhuma cidade")
    print(f"Cidades ({len(cities)}): {', '.join(cities)}",flush=True)
    api=Client(args.delay)
    if args.mode=="snapshot":
        day=parse_date(args.until)
        today_utc=dt.datetime.now(UTC).date()
        if not today_utc-dt.timedelta(days=1)<=day<=today_utc+dt.timedelta(days=2):
            p.error("Snapshot live apenas para datas proximas da data atual UTC")
        snapshot_books(db,api,cities,day,args)
        stats(db); return
    since,until=parse_date(args.since),parse_date(args.until)
    if since > until or since.year < 2020:
        p.error("Datas invalidas: usa um intervalo crescente desde 2020")
    today=dt.datetime.now(UTC).date()
    if until>today:
        print(f"AVISO: dias futuros nao existem ainda; --until ajustado para {today}")
        until=today
    failed=0
    for city in cities:
        d=since
        n=0
        while d<=until and (not args.max_days or n<args.max_days):
            try:
                status,pts=process_one(db,api,city,d,args)
                print(f"{city:22s} {d} {status:10s} novos_pontos={pts}",flush=True)
                if status=="error": failed+=1
            except Exception as exc:
                failed+=1
                print(f"ERRO inesperado {city}/{d}: {type(exc).__name__}: {exc}",file=sys.stderr)
            d+=dt.timedelta(days=1);n+=1
    print("\n========== RESUMO ==========")
    stats(db)
    print(f"Falhas de descoberta/processamento: {failed}; chunks com erro na tabela history_chunks")
    if failed:
        sys.exit(2)


if __name__=="__main__":
    main()
