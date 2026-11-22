#!/usr/bin/env python3
"""Contaminated historical scenario comparison using non-executable 5m marks.

Reads already-exposed labels from paper_filter_study.csv only to compare scenarios
exploratorily. Price_points are not bids/asks/fills; outputs are gross mark proxies,
not strategy performance or independent validation.
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import sqlite3
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "experiments" / "lead_lag_pilot"
DB_PATH = ROOT / "data" / "polymarket_weather_2026.sqlite"
BOT_DIRS = {"A": "live_bot_logs", "B": "live_bot_logs_v6", "C": "live_bot_logs_c"}
ZONES = {"munich": "Europe/Berlin", "lucknow": "Asia/Kolkata"}
TP = 0.95
STOP = 0.50


def utc(value: object) -> dt.datetime | None:
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed.astimezone(dt.timezone.utc) if parsed.tzinfo else None


def max_drawdown(values: list[float]) -> float:
    equity = peak = drawdown = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return drawdown


def summarize(name: str, values: list[float], shares: list[float]) -> dict:
    return {
        "scenario": name,
        "n": len(values),
        "gross_pnl_proxy": sum(values),
        "gross_per_share_proxy": sum(values) / sum(shares) if sum(shares) else None,
        "positive_positions": sum(v > 0 for v in values),
        "max_drawdown_proxy": max_drawdown(values),
    }


def main() -> int:
    # Labels are intentionally limited to the already-exposed exploratory sample.
    labels = {}
    with (BASE / "paper_filter_study.csv").open(newline="") as handle:
        for row in csv.DictReader(handle):
            result = row.get("result_for_research")
            timestamp = utc(row.get("timestamp_utc"))
            if result in ("won", "lost") and timestamp:
                labels[(row["bot"], row["city"], row["day"], timestamp)] = result

    db = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    db.execute("PRAGMA query_only=ON")
    positions = []
    for bot, dirname in BOT_DIRS.items():
        for city, zone in ZONES.items():
            for path in sorted((ROOT / dirname).glob(f"bets_{city}_*.json")):
                try:
                    day = dt.date.fromisoformat(path.stem.rsplit("_", 1)[-1])
                    raw = json.loads(path.read_text())
                except (OSError, ValueError, json.JSONDecodeError):
                    continue
                end = dt.datetime.combine(
                    day + dt.timedelta(days=1), dt.time.min, tzinfo=ZoneInfo(zone)
                ).astimezone(dt.timezone.utc)
                records = raw if isinstance(raw, list) else [raw]
                for record in records:
                    if not isinstance(record, dict) or record.get("simulated") is not True:
                        continue
                    entry = utc(record.get("timestamp"))
                    token = str(record.get("token_id") or "")
                    label = labels.get((bot, city, day.isoformat(), entry)) if entry else None
                    if entry is None or not token or not label or end <= entry:
                        continue
                    try:
                        ask = float(record["ask"])
                        shares = float(record["shares"])
                    except (KeyError, TypeError, ValueError):
                        continue
                    quotes = db.execute(
                        "SELECT ts,price FROM price_points "
                        "WHERE token_id=? AND fidelity_minutes=5 AND ts>? AND ts<=? "
                        "ORDER BY ts",
                        (token, int(entry.timestamp()), int(end.timestamp())),
                    ).fetchall()
                    quotes = [(int(ts), float(price)) for ts, price in quotes]
                    tp = next((x for x in quotes if x[1] >= TP), None)
                    stop = next((x for x in quotes if x[1] <= STOP), None)
                    outcome = 1.0 if label == "won" else 0.0
                    hold_exit = outcome
                    tp_exit = tp[1] if tp else outcome
                    stop_exit = stop[1] if stop else outcome
                    if tp and stop:
                        combo_exit = tp[1] if tp[0] < stop[0] else stop[1]
                    elif tp:
                        combo_exit = tp[1]
                    elif stop:
                        combo_exit = stop[1]
                    else:
                        combo_exit = outcome
                    positions.append({
                        "entry": entry,
                        "day": day.isoformat(),
                        "city": city,
                        "shares": shares,
                        "hold": shares * (hold_exit - ask),
                        "tp": shares * (tp_exit - ask),
                        "stop": shares * (stop_exit - ask),
                        "combo": shares * (combo_exit - ask),
                        "tp_hit": tp is not None,
                        "stop_hit": stop is not None,
                        "both": tp is not None and stop is not None,
                        "first": ("tp" if tp[0] < stop[0] else "stop") if tp and stop else "tp" if tp else "stop" if stop else "none",
                        "label": label,
                    })
    db.close()

    positions.sort(key=lambda row: row["entry"])
    print("EXPLORATORY ONLY: labels already exposed; price marks are not executable; fees omitted")
    print("positions", len(positions), "tp_marks", sum(p["tp_hit"] for p in positions),
          "stop_marks", sum(p["stop_hit"] for p in positions),
          "both", sum(p["both"] for p in positions),
          "both_first_stop", sum(p["both"] and p["first"] == "stop" for p in positions))
    for label in ("won", "lost"):
        group = [p for p in positions if p["label"] == label]
        print("exposed_label_group", label, "n", len(group),
              "tp_marks", sum(p["tp_hit"] for p in group),
              "stop_marks", sum(p["stop_hit"] for p in group),
              "both", sum(p["both"] for p in group))
    for key in ("hold", "tp", "stop", "combo"):
        print(summarize(key, [p[key] for p in positions], [p["shares"] for p in positions]))
    print("paired_gross_deltas_vs_hold", {
        key: round(sum(p[key] - p["hold"] for p in positions), 6)
        for key in ("tp", "stop", "combo")
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
