#!/usr/bin/env python3
"""Deployment-only pm_books loop driven by fleet.json; never trades."""
from __future__ import annotations

import fcntl
import json
import sqlite3
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
CONFIG = Path(__file__).with_name("fleet.json")


def settings() -> tuple[dict, list[str], Path]:
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    section = cfg["collectors"]["pm_books"]
    if not section.get("enabled"):
        raise ValueError("pm_books está disabled; edita deployment/paper/fleet.json explicitamente")
    cities = cfg["city_sets"].get(section.get("city_set"))
    if not cities or len(set(cities)) != len(cities):
        raise ValueError("city_set de pm_books vazio ou duplicado")
    db = (ROOT / section["database"]).resolve()
    if ROOT not in db.parents:
        raise ValueError("database deve ficar dentro do diretório do bundle")
    return section, cities, db


def preflight() -> tuple[dict, list[str], Path]:
    section, cities, db = settings()
    if db.is_file() and db.stat().st_size > float(section["max_db_gib"]) * 1024**3:
        raise RuntimeError("SQLite já excede max_db_gib; collector recusado")
    import shutil
    free = shutil.disk_usage(db.parent if db.parent.exists() else ROOT).free
    if free < float(section["min_free_gib"]) * 1024**3:
        raise RuntimeError("Espaço livre abaixo de min_free_gib; collector recusado")
    if db.is_file() and db.stat().st_size > 0:
        uri = f"file:{db.as_posix()}?mode=ro"
        with sqlite3.connect(uri, uri=True, timeout=5) as conn:
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not {"events", "markets", "tokens", "book_snapshots"}.issubset(tables):
                raise RuntimeError("SQLite existente sem tabelas do archive; collector recusado")
    return section, cities, db


def main() -> int:
    if "--check" in sys.argv:
        section, cities, db = preflight()
        db_bytes = db.stat().st_size if db.exists() else 0
        print(f"pm_books preflight OK · cidades={len(cities)} · intervalo={section['interval_seconds']}s · db={db_bytes} bytes · sem backfill")
        return 0

    section, cities, db = preflight()
    sys.path.insert(0, str(ROOT))
    import polymarket_weather_archive as arc

    db.parent.mkdir(parents=True, exist_ok=True)
    lock_path = db.parent / "orderbooks_live.lock"
    missing_attempt: dict[tuple[str, str], float] = {}
    with lock_path.open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("Já existe um pm_books collector com esta DB") from exc
        conn = arc.connect_db(db)
        conn.row_factory = sqlite3.Row
        api = arc.Client(0.4)
        try:
            while True:
                started = time.monotonic()
                try:
                    arc.enforce_storage_budget(db, float(section["max_db_gib"]),
                                               float(section["min_free_gib"]))
                    before = conn.execute("SELECT COUNT(*) FROM book_snapshots").fetchone()[0]
                    now = datetime.now(timezone.utc)
                    for city in cities:
                        tz = ZoneInfo(arc.city_timezone(city))
                        today = now.astimezone(tz).date()
                        for day in (today, today + timedelta(days=1)):
                            found = conn.execute(
                                "SELECT 1 FROM events WHERE city=? AND market_date=? AND status='found' LIMIT 1",
                                (city, day.isoformat()),
                            ).fetchone()
                            key = (city, day.isoformat())
                            if not found and time.monotonic() - missing_attempt.get(key, -1e12) < 1800:
                                continue
                            if not found:
                                missing_attempt[key] = time.monotonic()
                            arc.snapshot_books(conn, api, [city], day, None)
                    after = conn.execute("SELECT COUNT(*) FROM book_snapshots").fetchone()[0]
                    print(f"[{datetime.now(timezone.utc).isoformat()}] novos_snapshots={after-before} total={after}", flush=True)
                except SystemExit as exc:
                    print(f"PARAGEM DE SEGURANÇA: {exc}", flush=True)
                    break
                except Exception:
                    traceback.print_exc()
                time.sleep(max(2, int(section["interval_seconds"]) - (time.monotonic() - started)))
        except KeyboardInterrupt:
            print("pm_books deployment collector interrompido.", flush=True)
        finally:
            conn.close()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        raise SystemExit(2)
