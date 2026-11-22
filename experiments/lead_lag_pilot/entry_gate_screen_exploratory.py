#!/usr/bin/env python3
"""Exploratory screen of proposed age/rebound/market entry gates.

Uses already-exposed PAPER outcomes and price marks, plus native METAR observation
times (not publication times). No bot settings are read or changed; no labels are
used for tuning. All market quotes are price_points, not executable asks.
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import sqlite3
from collections import defaultdict
from pathlib import Path

from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "experiments" / "lead_lag_pilot"
BOT_DIRS = {"A": "live_bot_logs", "B": "live_bot_logs_v6", "C": "live_bot_logs_c"}
ZONES = {"munich": "Europe/Berlin", "lucknow": "Asia/Kolkata"}
WEATHER_BUFFER_MINUTES = 15
MAX_MARK_AGE_SECONDS = 600


def utc(value: object) -> dt.datetime | None:
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def load_weather():
    records = defaultdict(list)
    for city, zone_name in ZONES.items():
        zone = ZoneInfo(zone_name)
        path = ROOT / "historic_metar" / f"{city}.csv"
        with path.open(newline="") as handle:
            for row in csv.DictReader(handle):
                stamp = utc(row.get("timestamp_utc"))
                try:
                    temp = float(row["temp_c"])
                except (KeyError, TypeError, ValueError):
                    continue
                if stamp:
                    day = stamp.astimezone(zone).date().isoformat()
                    records[(city, day)].append((stamp, temp))
    for values in records.values():
        values.sort()
    return records


def entry_record(bot: str, city: str, day: str, timestamp: dt.datetime):
    folder = BOT_DIRS[bot]
    path = ROOT / folder / f"bets_{city}_{day}.json"
    try:
        raw = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    records = raw if isinstance(raw, list) else [raw]
    for record in records:
        if not isinstance(record, dict) or record.get("simulated") is not True:
            continue
        if utc(record.get("timestamp")) == timestamp:
            return record
    return None


def summarize(name, group):
    if not group:
        return {"gate": name, "n": 0}
    wins = sum(row["won"] for row in group)
    pnl = sum((1.0 if row["won"] else 0.0) - row["entry_price"] for row in group)
    return {
        "gate": name,
        "n": len(group),
        "wins": wins,
        "hit_rate": round(wins / len(group), 4),
        "gross_pnl_per_share_proxy": round(pnl, 4),
        "mean_gross_per_share_proxy": round(pnl / len(group), 4),
    }


def main():
    weather = load_weather()
    db = sqlite3.connect(f"file:{ROOT / 'data/polymarket_weather_2026.sqlite'}?mode=ro", uri=True)
    db.execute("PRAGMA query_only=ON")
    enriched = []
    with (BASE / "paper_filter_study.csv").open(newline="") as handle:
        for source in csv.DictReader(handle):
            decision = utc(source.get("timestamp_utc"))
            if decision is None:
                continue
            bot, city, day = source["bot"], source["city"], source["day"]
            record = entry_record(bot, city, day, decision)
            try:
                p_rebound = float(source["p_rebound"])
                entry_price = float(source["paper_price"])
            except (KeyError, TypeError, ValueError):
                p_rebound = entry_price = None
            label = source.get("result_for_research")
            if label not in ("won", "lost"):
                continue

            cutoff = decision - dt.timedelta(minutes=WEATHER_BUFFER_MINUTES)
            past = [(ts, temp) for ts, temp in weather.get((city, day), []) if ts <= cutoff]
            age = None
            if past:
                running_max = max(temp for _, temp in past)
                last_max = max(ts for ts, temp in past if temp == running_max)
                age = (cutoff - last_max).total_seconds() / 60

            mark = None
            mark_age = None
            token = str((record or {}).get("token_id") or "")
            if token:
                quote = db.execute(
                    "SELECT ts,price FROM price_points "
                    "WHERE token_id=? AND fidelity_minutes=5 AND ts BETWEEN ? AND ? "
                    "ORDER BY ts DESC LIMIT 1",
                    (token, int(decision.timestamp()) - MAX_MARK_AGE_SECONDS,
                     int(decision.timestamp())),
                ).fetchone()
                if quote:
                    mark, mark_age = float(quote[1]), int(decision.timestamp()) - int(quote[0])

            enriched.append({
                "city": city,
                "day": day,
                "bot": bot,
                "won": label == "won",
                "p_rebound": p_rebound,
                "age_since_max_min": age,
                "target_mark": mark,
                "mark_age_sec": mark_age,
                "entry_price": entry_price,
            })
    db.close()

    gates = {
        "all_binary_labeled": lambda r: True,
        "p_rebound_lt_0.20": lambda r: r["p_rebound"] is not None and r["p_rebound"] < 0.20,
        "max_age_gt_60m": lambda r: r["age_since_max_min"] is not None and r["age_since_max_min"] > 60,
        "rebound_and_age": lambda r: r["p_rebound"] is not None and r["p_rebound"] < 0.20 and r["age_since_max_min"] is not None and r["age_since_max_min"] > 60,
        "rebound_and_target_mark_gt_0.60": lambda r: r["p_rebound"] is not None and r["p_rebound"] < 0.20 and r["target_mark"] is not None and r["mark_age_sec"] <= MAX_MARK_AGE_SECONDS and r["target_mark"] > 0.60,
        "all_three": lambda r: r["p_rebound"] is not None and r["p_rebound"] < 0.20 and r["age_since_max_min"] is not None and r["age_since_max_min"] > 60 and r["target_mark"] is not None and r["mark_age_sec"] <= MAX_MARK_AGE_SECONDS and r["target_mark"] > 0.60,
    }
    print("EXPLORATORY ONLY: exposed labels; METAR observation time != availability; marks != executable asks")
    print("entry_rows", len(enriched),
          "with_p_rebound", sum(r["p_rebound"] is not None for r in enriched),
          "with_age_feature", sum(r["age_since_max_min"] is not None for r in enriched),
          "with_fresh_target_mark", sum(r["target_mark"] is not None and r["mark_age_sec"] <= MAX_MARK_AGE_SECONDS for r in enriched))
    for name, predicate in gates.items():
        selected = [row for row in enriched if predicate(row)]
        print(summarize(name, selected))
    print("by_city")
    for city in ZONES:
        city_rows = [row for row in enriched if row["city"] == city]
        for name in ("all_binary_labeled", "p_rebound_lt_0.20", "rebound_and_age",
                     "rebound_and_target_mark_gt_0.60"):
            selected = [row for row in city_rows if gates[name](row)]
            print(city, summarize(name, selected))


if __name__ == "__main__":
    main()
