#!/usr/bin/env python3
"""Descriptive Lucknow pilot; observation times do not establish availability."""
import csv
import datetime as dt
import sqlite3
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
UTC = dt.timezone.utc
IST = ZoneInfo('Asia/Kolkata')
DAY = dt.date(2026, 4, 25)
with (ROOT / 'historic_metar/lucknow.csv').open(newline='') as f:
    observations = [(dt.datetime.fromisoformat(r['timestamp_utc']).replace(tzinfo=UTC), r['temp_c'])
                    for r in csv.DictReader(f) if r['date'] == '25/04/2026' and r['temp_c']]
db = sqlite3.connect(f'file:{ROOT / "data/polymarket_weather_2026.sqlite"}?mode=ro', uri=True)
db.execute('PRAGMA query_only=ON')
tokens = db.execute("""SELECT m.bracket,t.token_id FROM markets m JOIN tokens t ON t.market_id=m.market_id
 WHERE m.city=? AND m.market_date=? AND t.outcome='YES' AND m.bracket IN ('42°C','43°C','44°C')
 ORDER BY m.bracket""", ('lucknow', DAY.isoformat())).fetchall()
print('Lucknow 2026-04-25 | UTC and IST | YES historical prices, not asks')
print('METAR observation time is not verified publication time; settlement is unvalidated.')
print('METAR original CSV, 13:00–15:30 IST:')
for stamp, temp in observations:
    local = stamp.astimezone(IST)
    if dt.time(13) <= local.time() <= dt.time(15, 30):
        print(f'{stamp:%H:%M UTC} / {local:%H:%M IST}: {temp} °C')
print('\nDecision time IST | bracket: price (original UTC timestamp, age minutes); max age 10m')
for minute in range(13 * 60 + 30, 15 * 60 + 31, 5):
    instant = dt.datetime.combine(DAY, dt.time(minute // 60, minute % 60), IST)
    epoch = int(instant.timestamp())
    quotes = []
    for bracket, token in tokens:
        row = db.execute('SELECT ts,price FROM price_points WHERE token_id=? AND ts BETWEEN ? AND ? AND fidelity_minutes=5 ORDER BY ts DESC LIMIT 1', (token, epoch-600, epoch)).fetchone()
        if row:
            observed = dt.datetime.fromtimestamp(row[0], UTC)
            quotes.append(f'{bracket}: {row[1]:.3f} ({observed:%H:%M:%S} UTC, {(epoch-row[0])/60:.1f}m)')
        else:
            quotes.append(f'{bracket}: missing')
    print(f'{instant:%H:%M} | ' + ' | '.join(quotes))
db.close()
