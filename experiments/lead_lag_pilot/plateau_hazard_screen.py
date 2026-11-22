#!/usr/bin/env python3
"""Source-separated historical screen of future temperature rises after a plateau.

Uses only archived METAR/WU observations and event-date identity. It does not
read market prices, Gamma winners, settlement outcomes, or the prospective
period. SQLite is opened read-only/query-only; summaries go to stdout.
"""
import csv
import datetime as dt
import statistics
import sqlite3
from collections import defaultdict
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[2]
START, END = "2026-03-05", "2026-07-17"
ZONES = {"munich": "Europe/Berlin", "lucknow": "Asia/Kolkata"}
HOURS = (9, 11, 13, 15, 17)
PLATEAU_TOLERANCE_C = 0.5
PLATEAU_MINUTES = 90
MAX_STREAK_GAP_MINUTES = 60


def load_event_days():
    db = sqlite3.connect(f"file:{ROOT / 'data/polymarket_weather_2026.sqlite'}?mode=ro", uri=True)
    db.execute("PRAGMA query_only=ON")
    rows = db.execute(
        "SELECT city,market_date FROM events WHERE city IN ('munich','lucknow') "
        "AND market_date BETWEEN ? AND ? AND status='found' ORDER BY market_date,city",
        (START, END),
    ).fetchall()
    db.close()
    return set(rows)


def load_source(source_dir, event_days):
    data = defaultdict(list)
    coverage = {}
    for city, zone_name in ZONES.items():
        zone = ZoneInfo(zone_name)
        path = ROOT / source_dir / f"{city}.csv"
        with path.open(newline="") as src:
            for row in csv.DictReader(src):
                try:
                    stamp = dt.datetime.fromisoformat(row["timestamp_utc"])
                    stamp = stamp.replace(tzinfo=dt.timezone.utc) if stamp.tzinfo is None else stamp.astimezone(dt.timezone.utc)
                    local_day = stamp.astimezone(zone).date().isoformat()
                    if (city, local_day) in event_days and row.get("temp_c"):
                        data[(city, local_day)].append((stamp, float(row["temp_c"])))
                except (ValueError, KeyError, TypeError):
                    continue
        for key, values in list(data.items()):
            if key[0] != city:
                continue
            values.sort()
            local = [t.astimezone(zone) for t, _ in values]
            day_start = dt.datetime.combine(dt.date.fromisoformat(key[1]), dt.time.min, zone)
            day_end = day_start + dt.timedelta(days=1)
            gaps = [(b - a).total_seconds() / 60 for a, b in zip(local, local[1:])]
            coverage[key] = {
                "first_min": (local[0] - day_start).total_seconds() / 60,
                "last_min": (day_end - local[-1]).total_seconds() / 60,
                "max_gap_min": max(gaps, default=float("inf")),
            }
    return data, coverage


def eligible_full_day(cov):
    # Require near-complete local-day coverage before calling the later maximum final.
    return cov["first_min"] <= 60 and cov["last_min"] <= 60 and cov["max_gap_min"] <= 90


def plateau_duration(past, running_max):
    if not past or past[-1][1] < running_max - PLATEAU_TOLERANCE_C:
        return 0.0
    streak = [past[-1]]
    for row in reversed(past[:-1]):
        gap_min = (streak[0][0] - row[0]).total_seconds() / 60
        if gap_min > MAX_STREAK_GAP_MINUTES or row[1] < running_max - PLATEAU_TOLERANCE_C:
            break
        streak.insert(0, row)
    return (streak[-1][0] - streak[0][0]).total_seconds() / 60


def age_bin(minutes):
    if minutes < 30:
        return "0-<30m"
    if minutes < 60:
        return "30-<60m"
    if minutes < 120:
        return "60-<120m"
    return "120m+"


def summarize(source_dir, event_days):
    data, coverage = load_source(source_dir, event_days)
    full_days = {key for key, cov in coverage.items() if eligible_full_day(cov)}
    print("SOURCE", source_dir, "event_days", len(event_days), "source_days", len(coverage), "full_day_eligible", len(full_days))
    for city, zone_name in ZONES.items():
        zone = ZoneInfo(zone_name)
        for hour in HOURS:
            all_rows, mature, other, ages = [], [], [], defaultdict(list)
            for key in sorted(k for k in full_days if k[0] == city):
                day = key[1]
                values = data[key]
                decision = dt.datetime.combine(dt.date.fromisoformat(day), dt.time(hour), zone).astimezone(dt.timezone.utc)
                cutoff = decision - dt.timedelta(minutes=15)
                past = [row for row in values if row[0] <= cutoff]
                future = [row for row in values if row[0] > cutoff]
                if len(past) < 4 or not future or (cutoff - past[-1][0]).total_seconds() > 90 * 60:
                    continue
                running_max = max(value for _, value in past)
                last_max_time = max(t for t, value in past if abs(value - running_max) < 0.01)
                age_since_max = (cutoff - last_max_time).total_seconds() / 60
                future_rise = max(0.0, max(value for _, value in future) - running_max)
                duration = plateau_duration(past, running_max)
                is_mature = duration >= PLATEAU_MINUTES
                row = (day, future_rise)
                all_rows.append(row)
                (mature if is_mature else other).append(row)
                ages[age_bin(age_since_max)].append(future_rise)

            def rates(rows):
                if not rows:
                    return "n=0"
                rises05 = sum(value >= 0.5 for _, value in rows)
                rises10 = sum(value >= 1.0 for _, value in rows)
                return f"n={len(rows)} rise>=0.5={rises05/len(rows):.3f} rise>=1={rises10/len(rows):.3f} median_rise={statistics.median(v for _,v in rows):.2f}"

            print("CITY_HOUR", city, hour, "all", rates(all_rows), "mature90", rates(mature), "other", rates(other))
            print("  AGE_BINS", " | ".join(f"{name}: {rates([(str(i),v) for i,v in enumerate(vals)])}" for name, vals in sorted(ages.items())))


def main():
    days = load_event_days()
    for source in ("historic_metar", "historic"):
        summarize(source, days)


if __name__ == "__main__":
    main()
