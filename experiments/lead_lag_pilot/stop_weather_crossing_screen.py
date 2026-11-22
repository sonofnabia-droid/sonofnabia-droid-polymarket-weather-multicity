#!/usr/bin/env python3
"""Exploratory stop-mark vs official-bracket-bound crossing chronology.

Uses resolution_rules.py for bracket bounds, native METAR observation timestamps,
5m price_points marks, and already-exposed PAPER labels. It does not read official
Gamma settlement payloads or claim METAR availability/contract eligibility.
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "experiments" / "lead_lag_pilot"
sys.path.insert(0, str(ROOT))
from resolution_rules import bracket_bounds

BOT_DIRS = {"A": "live_bot_logs", "B": "live_bot_logs_v6", "C": "live_bot_logs_c"}
ZONES = {"munich": "Europe/Berlin", "lucknow": "Asia/Kolkata"}
STOP_MARK = 0.50


def as_utc(value: object) -> dt.datetime | None:
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def load_weather():
    weather = defaultdict(list)
    for city, zone_name in ZONES.items():
        zone = ZoneInfo(zone_name)
        with (ROOT / "historic_metar" / f"{city}.csv").open(newline="") as handle:
            for row in csv.DictReader(handle):
                stamp = as_utc(row.get("timestamp_utc"))
                try:
                    temp = float(row["temp_c"])
                except (KeyError, TypeError, ValueError):
                    continue
                if stamp:
                    day = stamp.astimezone(zone).date().isoformat()
                    weather[(city, day)].append((stamp, temp))
    for points in weather.values():
        points.sort()
    return weather


def find_bet(bot, city, day, decision):
    path = ROOT / BOT_DIRS[bot] / f"bets_{city}_{day}.json"
    try:
        raw = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    records = raw if isinstance(raw, list) else [raw]
    for record in records:
        if not isinstance(record, dict) or record.get("simulated") is not True:
            continue
        if as_utc(record.get("timestamp")) == decision:
            return record
    return None


def main():
    weather = load_weather()
    db = sqlite3.connect(f"file:{ROOT / 'data/polymarket_weather_2026.sqlite'}?mode=ro", uri=True)
    db.execute("PRAGMA query_only=ON")
    results = []
    with (BASE / "paper_filter_study.csv").open(newline="") as handle:
        for row in csv.DictReader(handle):
            label = row.get("result_for_research")
            if label not in ("won", "lost"):
                continue
            decision = as_utc(row.get("timestamp_utc"))
            if not decision:
                continue
            bot, city, day = row["bot"], row["city"], row["day"]
            bet = find_bet(bot, city, day, decision)
            if not bet or bet.get("temp_lo") in (None, "") or bet.get("temp_hi") in (None, ""):
                continue
            token = str(bet.get("token_id") or "")
            if not token:
                continue
            zone = ZoneInfo(ZONES[city])
            end = dt.datetime.combine(
                dt.date.fromisoformat(day) + dt.timedelta(days=1), dt.time.min, tzinfo=zone
            ).astimezone(dt.timezone.utc)
            marks = db.execute(
                "SELECT ts,price FROM price_points "
                "WHERE token_id=? AND fidelity_minutes=5 AND ts>? AND ts<=? ORDER BY ts",
                (token, int(decision.timestamp()), int(end.timestamp())),
            ).fetchall()
            stop_ts = next((dt.datetime.fromtimestamp(int(ts), dt.timezone.utc)
                            for ts, price in marks if float(price) <= STOP_MARK), None)
            if not stop_ts:
                continue

            low, high = bracket_bounds(float(bet["temp_lo"]), float(bet["temp_hi"]))
            obs = weather[(city, day)]
            cross_index = next((i for i, (stamp, temp) in enumerate(obs)
                                if stamp > decision and temp >= high), None)
            cross_ts = obs[cross_index][0] if cross_index is not None else None
            next_obs = obs[cross_index + 1] if cross_index is not None and cross_index + 1 < len(obs) else None
            relation = ("no_cross" if cross_ts is None else
                        "cross_before_stop" if cross_ts < stop_ts else "cross_after_stop")
            crossing_delta_min = ((stop_ts - cross_ts).total_seconds() / 60
                                  if cross_ts and cross_ts < stop_ts else
                                  (cross_ts - stop_ts).total_seconds() / 60
                                  if cross_ts else None)
            before = max((item for item in marks if cross_ts and int(item[0]) < int(cross_ts.timestamp())),
                         default=None, key=lambda item: item[0])
            after = min((item for item in marks if cross_ts and int(item[0]) >= int(cross_ts.timestamp())),
                        default=None, key=lambda item: item[0])
            after15 = min((item for item in marks if cross_ts and int(item[0]) >= int((cross_ts + dt.timedelta(minutes=15)).timestamp())),
                          default=None, key=lambda item: item[0])
            results.append({
                "label": label, "city": city, "day": day,
                "bracket_lower_inclusive": low, "bracket_upper_exclusive": high,
                "first_stop_mark_utc": stop_ts.isoformat(),
                "first_official_bound_cross_obs_utc": cross_ts.isoformat() if cross_ts else "",
                "cross_relation": relation, "minutes_between_cross_and_stop": crossing_delta_min,
                "next_obs_utc": next_obs[0].isoformat() if next_obs else "",
                "next_obs_temp_c": next_obs[1] if next_obs else "",
                "next_obs_confirms_cross": bool(next_obs and next_obs[1] >= high) if cross_ts else "",
                "mark_before_cross": float(before[1]) if before else "",
                "first_mark_at_after_cross": float(after[1]) if after else "",
                "mark_at_or_after_cross_plus_15m": float(after15[1]) if after15 else "",
            })
    db.close()

    print("EXPLORATORY ONLY: exposed labels; METAR obs time != availability; marks != bid/fill")
    print("stop_positions", len(results))
    for label in ("won", "lost"):
        group = [x for x in results if x["label"] == label]
        print(label, "n", len(group), "cross_before_stop", sum(x["cross_relation"] == "cross_before_stop" for x in group),
              "cross_after_stop", sum(x["cross_relation"] == "cross_after_stop" for x in group),
              "no_cross", sum(x["cross_relation"] == "no_cross" for x in group),
              "next_obs_confirms", sum(x["next_obs_confirms_cross"] is True for x in group))
    writer = csv.DictWriter(sys.stdout, fieldnames=list(results[0]) if results else [
        "label", "city", "day", "bracket_lower_inclusive", "bracket_upper_exclusive",
        "first_stop_mark_utc", "first_official_bound_cross_obs_utc", "cross_relation",
        "minutes_between_cross_and_stop", "next_obs_utc", "next_obs_temp_c",
        "next_obs_confirms_cross", "mark_before_cross", "first_mark_at_after_cross",
        "mark_at_or_after_cross_plus_15m",
    ])
    writer.writeheader()
    writer.writerows(results)


if __name__ == "__main__":
    main()
