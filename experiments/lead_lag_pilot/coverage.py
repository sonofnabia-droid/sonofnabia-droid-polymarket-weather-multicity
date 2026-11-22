#!/usr/bin/env python3
"""Inventory weekly candidate events and original weather observations."""
import csv
import datetime as dt
import sqlite3
from pathlib import Path
from zoneinfo import ZoneInfo

root = Path(__file__).resolve().parents[2]
db = sqlite3.connect(f'file:{root / "data/polymarket_weather_2026.sqlite"}?mode=ro', uri=True)
db.execute('PRAGMA query_only=ON')
out = csv.writer(__import__('sys').stdout)
out.writerow(['city', 'day', 'event_status', 'markets', 'yes_tokens_with_price', 'weather_observations'])
for city, tzname in [('lucknow','Asia/Kolkata'), ('munich','Europe/Berlin')]:
    tz = ZoneInfo(tzname)
    days = {}
    with (root / 'historic_metar' / f'{city}.csv').open(newline='') as f:
        for row in csv.DictReader(f):
            try:
                stamp = dt.datetime.fromisoformat(row['timestamp_utc']).replace(tzinfo=dt.timezone.utc)
                day = stamp.astimezone(tz).date()
                if dt.date(2026,3,5) <= day <= dt.date(2026,7,17) and row['temp_c']:
                    days[day] = days.get(day, 0) + 1
            except (ValueError, KeyError):
                continue
    day = dt.date(2026,3,5)
    while day <= dt.date(2026,7,17):
        event = db.execute('SELECT status FROM events WHERE city=? AND market_date=?',(city,day.isoformat())).fetchone()
        markets = db.execute('SELECT market_id FROM markets WHERE city=? AND market_date=?',(city,day.isoformat())).fetchall()
        tokens = db.execute("SELECT t.token_id FROM markets m JOIN tokens t ON t.market_id=m.market_id WHERE m.city=? AND m.market_date=? AND t.outcome='YES'",(city,day.isoformat())).fetchall()
        start = int(dt.datetime.combine(day, dt.time.min, tz).timestamp())
        end = int(dt.datetime.combine(day+dt.timedelta(days=1), dt.time.min, tz).timestamp())
        priced = sum(bool(db.execute('SELECT 1 FROM price_points WHERE token_id=? AND ts>=? AND ts<? AND fidelity_minutes=5 LIMIT 1',(token[0],start,end)).fetchone()) for token in tokens)
        out.writerow([city,day.isoformat(),event[0] if event else 'absent',len(markets),priced,days.get(day,0)])
        day += dt.timedelta(days=1)
db.close()
