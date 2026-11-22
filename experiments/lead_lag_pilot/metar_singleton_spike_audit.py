#!/usr/bin/env python3
"""Read-only screen for isolated native-METAR temperature spikes in 2026.

An anomaly is descriptive only: same-local-day triplet, both gaps <=60m, endpoints
within 2C, and middle point >=4C away from each endpoint. It is not auto-corrected.
Gamma archived winners are included only as exposed exploratory comparisons.
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import sqlite3
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "data" / "polymarket_weather_2026.sqlite"
ZONES = {"lucknow": "Asia/Kolkata", "munich": "Europe/Berlin"}


def round_half_up(value: float) -> int:
    import math
    return math.floor(value + 0.5)


def load_city(city: str):
    zone = ZoneInfo(ZONES[city])
    by_day = {}
    with (ROOT / "historic_metar" / f"{city}.csv").open(newline="") as handle:
        for row in csv.DictReader(handle):
            try:
                stamp = dt.datetime.fromisoformat(row["timestamp_utc"])
                stamp = stamp.replace(tzinfo=dt.timezone.utc) if stamp.tzinfo is None else stamp.astimezone(dt.timezone.utc)
                if stamp.year != 2026:
                    continue
                temp = float(row["temp_c"])
                dew = float(row["dewpt_c"]) if row.get("dewpt_c") not in (None, "") else None
            except (KeyError, TypeError, ValueError):
                continue
            local = stamp.astimezone(zone)
            by_day.setdefault(local.date().isoformat(), []).append((stamp, temp, dew, row))
    for rows in by_day.values():
        rows.sort()
    return zone, by_day


def gamma_info(db, city: str, day: str):
    markets = db.execute(
        "SELECT m.bracket,m.closed,m.outcome_prices,m.raw_json "
        "FROM markets m WHERE m.city=? AND m.market_date=?",
        (city, day),
    ).fetchall()
    winners, sources = [], set()
    for bracket, closed, prices_raw, raw in markets:
        try:
            meta = json.loads(raw)
            if meta.get("resolutionSource"):
                sources.add(meta["resolutionSource"])
            if not closed:
                continue
            outcomes = meta.get("outcomes", [])
            outcomes = json.loads(outcomes) if isinstance(outcomes, str) else outcomes
            prices = json.loads(prices_raw or "[]")
            yes_index = next(i for i, outcome in enumerate(outcomes) if str(outcome).upper() == "YES")
            if float(prices[yes_index]) >= 0.999:
                winners.append(bracket)
        except (ValueError, TypeError, KeyError, IndexError, StopIteration):
            continue
    return winners, sorted(sources), len(markets)


def backup_value(city: str, stamp_text: str):
    path = ROOT / "historic_metar" / f"{city}.csv.bak_20261115_073927"
    if city == "munich":
        path = ROOT / "historic_metar" / "munich.csv.bak_20261115_073902"
    if not path.exists():
        return ""
    with path.open(newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("timestamp_utc") == stamp_text:
                return row.get("temp_c", "")
    return ""


def main():
    db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    db.execute("PRAGMA query_only=ON")
    cases = []
    for city in ZONES:
        zone, by_day = load_city(city)
        for day, rows in by_day.items():
            for i in range(1, len(rows) - 1):
                prev, middle, nxt = rows[i - 1:i + 2]
                local = [point[0].astimezone(zone) for point in (prev, middle, nxt)]
                gaps = [(local[1] - local[0]).total_seconds() / 60,
                        (local[2] - local[1]).total_seconds() / 60]
                if len({point.date() for point in local}) != 1 or max(gaps) > 60:
                    continue
                if abs(prev[1] - nxt[1]) > 2 or abs(middle[1] - prev[1]) < 4 or abs(middle[1] - nxt[1]) < 4:
                    continue
                day_rows = by_day[day]
                day_max = max(point[1] for point in day_rows)
                max_without = max(point[1] for point in day_rows if point is not middle)
                winners, sources, market_count = gamma_info(db, city, day)
                cases.append({
                    "city": city, "day": day,
                    "prev_local": local[0].strftime("%H:%M"), "prev_temp_c": prev[1],
                    "spike_local": local[1].strftime("%H:%M"), "spike_temp_c": middle[1],
                    "spike_utc": middle[3].get("timestamp_utc", ""),
                    "dewpoint_c": middle[2] if middle[2] is not None else "",
                    "dewpoint_exceeds_temp": middle[2] is not None and middle[2] > middle[1],
                    "next_local": local[2].strftime("%H:%M"), "next_temp_c": nxt[1],
                    "prev_to_spike_gap_min": round(gaps[0], 2), "spike_to_next_gap_min": round(gaps[1], 2),
                    "day_max_c": day_max, "rounded_day_max": round_half_up(day_max),
                    "max_without_spike_c": max_without,
                    "rounded_max_without_spike": round_half_up(max_without),
                    "gamma_winner": ";".join(winners), "resolution_sources": ";".join(sources),
                    "markets": market_count,
                    "backup_temp_c": backup_value(city, middle[3].get("timestamp_utc", "")),
                })
    db.close()

    print("EXPLORATORY ONLY: singleton-spike rule is a QC flag, not a correction; Gamma labels are exposed")
    print("isolated_spikes", len(cases), "affected_days", len({(x['city'], x['day']) for x in cases}),
          "days_where_removal_changes_rounded_daily_max",
          sum(x["rounded_day_max"] != x["rounded_max_without_spike"] for x in cases))
    writer = csv.DictWriter(__import__("sys").stdout, fieldnames=list(cases[0]) if cases else ["city", "day"])
    writer.writeheader()
    writer.writerows(cases)


if __name__ == "__main__":
    main()
