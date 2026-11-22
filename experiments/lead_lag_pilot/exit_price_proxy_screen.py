#!/usr/bin/env python3
"""Exploratory, non-executable exit-threshold screen on 5m price_points.

No bet outcomes or settlement labels are read. Historical price_points are marks,
not bids/asks/fills; this script reports trigger paths only, never P&L.
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import sqlite3
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "data" / "polymarket_weather_2026.sqlite"
CITY_ZONES = {"munich": "Europe/Berlin", "lucknow": "Asia/Kolkata"}
BOT_DIRS = {"A": "live_bot_logs", "B": "live_bot_logs_v6", "C": "live_bot_logs_c"}
TAKE_PROFIT = 0.95
STOP_MARK = 0.50


def as_utc(value: object) -> dt.datetime | None:
    try:
        value = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return value.astimezone(dt.timezone.utc) if value.tzinfo else None


def first_cross(quotes: list[tuple[int, float]], threshold: float, is_tp: bool):
    for timestamp, price in quotes:
        crossed = price >= threshold if is_tp else price <= threshold
        if crossed:
            return timestamp, price
    return None


def fmt(value):
    return "" if value is None else dt.datetime.fromtimestamp(value, dt.timezone.utc).isoformat()


def main() -> int:
    db = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    db.execute("PRAGMA query_only=ON")
    out = csv.writer(sys.stdout)
    out.writerow([
        "bot", "city", "day", "entry_utc", "paper_entry_ask", "position_shares",
        "fidelity_minutes", "post_entry_marks", "first_mark_utc", "last_mark_utc",
        "tp_first_mark_utc", "tp_mark", "stop_first_mark_utc", "stop_mark",
        "first_threshold", "both_thresholds_seen", "not_executable",
    ])
    for bot, dirname in BOT_DIRS.items():
        for city, zone in CITY_ZONES.items():
            for path in sorted((ROOT / dirname).glob(f"bets_{city}_*.json")):
                try:
                    day = dt.date.fromisoformat(path.stem.rsplit("_", 1)[-1])
                    raw = json.loads(path.read_text())
                except (OSError, ValueError, json.JSONDecodeError):
                    continue
                local_end = dt.datetime.combine(
                    day + dt.timedelta(days=1), dt.time.min, tzinfo=ZoneInfo(zone)
                ).astimezone(dt.timezone.utc)
                records = raw if isinstance(raw, list) else [raw]
                for record in records:
                    if not isinstance(record, dict) or record.get("simulated") is not True:
                        continue
                    entry = as_utc(record.get("timestamp"))
                    token = str(record.get("token_id") or "")
                    if entry is None or not token or local_end <= entry:
                        continue
                    marks = db.execute(
                        "SELECT ts,price FROM price_points "
                        "WHERE token_id=? AND fidelity_minutes=5 AND ts>? AND ts<=? "
                        "ORDER BY ts",
                        (token, int(entry.timestamp()), int(local_end.timestamp())),
                    ).fetchall()
                    quotes = [(int(ts), float(price)) for ts, price in marks]
                    tp = first_cross(quotes, TAKE_PROFIT, True)
                    stop = first_cross(quotes, STOP_MARK, False)
                    if tp and stop:
                        first = "take_profit" if tp[0] < stop[0] else "stop" if stop[0] < tp[0] else "same_mark"
                    elif tp:
                        first = "take_profit"
                    elif stop:
                        first = "stop"
                    else:
                        first = "none"
                    out.writerow([
                        bot, city, day.isoformat(), entry.isoformat(), record.get("ask", ""),
                        record.get("shares", ""), 5, len(quotes), fmt(quotes[0][0]) if quotes else "",
                        fmt(quotes[-1][0]) if quotes else "", fmt(tp[0]) if tp else "",
                        tp[1] if tp else "", fmt(stop[0]) if stop else "", stop[1] if stop else "",
                        first, bool(tp and stop), True,
                    ])
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
