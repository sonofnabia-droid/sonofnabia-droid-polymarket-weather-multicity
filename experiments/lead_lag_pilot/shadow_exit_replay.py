#!/usr/bin/env python3
"""Read-only shadow screen for PAPER exits using same-token CLOB book snapshots.

This deliberately does not read bet outcomes, resolution fields, or settlement labels.
It reports quote triggers and top-bid depth only; it does not claim fills or net P&L.
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
BOT_DIRS = {
    "A": "live_bot_logs",
    "B": "live_bot_logs_v6",
    "C": "live_bot_logs_c",
}
TAKE_PROFIT = 0.95
STOP_BID = 0.50


def parse_utc(value: object) -> dt.datetime | None:
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(dt.timezone.utc)


def first_cross(rows: list[tuple[int, float | None, str | None]], threshold: float,
                *, at_or_above: bool) -> tuple[int, float, str | None] | None:
    for sampled_at, bid, bid_size in rows:
        if bid is None:
            continue
        crossed = bid >= threshold if at_or_above else bid <= threshold
        if crossed:
            return sampled_at, bid, bid_size
    return None


def parsed_bids(raw: str | None) -> list[tuple[float, float]]:
    try:
        levels = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return []
    parsed = []
    for level in levels if isinstance(levels, list) else []:
        try:
            price, size = float(level[0]), float(level[1])
        except (TypeError, ValueError, IndexError):
            continue
        if 0 <= price <= 1 and size > 0:
            parsed.append((price, size))
    return sorted(parsed, reverse=True)


def sweep(levels: list[tuple[float, float]], shares: float | None,
          minimum_price: float | None = None) -> tuple[float, float, float | None]:
    """Return eligible depth, simulated filled shares, and VWAP for that fill."""
    eligible = [(price, size) for price, size in levels
                if minimum_price is None or price >= minimum_price]
    depth = sum(size for _, size in eligible)
    if shares is None or shares <= 0:
        return depth, 0.0, None
    remaining = shares
    proceeds = filled = 0.0
    for price, size in eligible:
        quantity = min(size, remaining)
        proceeds += price * quantity
        filled += quantity
        remaining -= quantity
        if remaining <= 1e-9:
            break
    return depth, filled, proceeds / filled if filled else None


def event_end(day: dt.date, city: str) -> dt.datetime:
    local_next_midnight = dt.datetime.combine(
        day + dt.timedelta(days=1), dt.time.min,
        tzinfo=ZoneInfo(CITY_ZONES[city]),
    )
    return local_next_midnight.astimezone(dt.timezone.utc)


def main() -> int:
    now = dt.datetime.now(dt.timezone.utc)
    db = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    db.execute("PRAGMA query_only=ON")
    writer = csv.writer(sys.stdout)
    writer.writerow([
        "bot", "city", "day", "entry_utc", "paper_entry_ask", "position_shares",
        "book_snapshots", "first_snapshot_utc", "last_snapshot_utc",
        "tp_first_utc", "tp_bid", "tp_depth_ge_095", "tp_fillable_shares_ge_095",
        "tp_vwap_on_fillable_shares_ge_095", "tp_full_depth_covers_position",
        "stop_first_utc", "stop_bid", "stop_total_visible_bid_depth",
        "stop_fillable_shares", "stop_vwap_on_fillable_shares", "stop_full_depth_covers_position",
        "first_trigger", "data_complete_through_local_day_end",
    ])

    for bot, dirname in BOT_DIRS.items():
        for city in CITY_ZONES:
            for path in sorted((ROOT / dirname).glob(f"bets_{city}_*.json")):
                try:
                    day = dt.date.fromisoformat(path.stem.rsplit("_", 1)[-1])
                    raw = json.loads(path.read_text())
                except (OSError, ValueError, json.JSONDecodeError):
                    continue
                records = raw if isinstance(raw, list) else [raw]
                for record in records:
                    if not isinstance(record, dict) or record.get("simulated") is not True:
                        continue
                    entry = parse_utc(record.get("timestamp"))
                    token = str(record.get("token_id") or "")
                    if entry is None or not token:
                        continue
                    try:
                        shares = float(record.get("shares"))
                    except (TypeError, ValueError):
                        shares = None
                    ask = record.get("ask")
                    try:
                        ask = float(ask) if ask is not None else None
                    except (TypeError, ValueError):
                        ask = None

                    end = min(event_end(day, city), now)
                    if end <= entry:
                        continue
                    # Composite primary key (token_id, sampled_at) makes this bounded query indexed.
                    snapshots = db.execute(
                        "SELECT sampled_at,best_bid,bids_json FROM book_snapshots "
                        "WHERE token_id=? AND sampled_at>? AND sampled_at<=? "
                        "ORDER BY sampled_at",
                        (token, int(entry.timestamp()), int(end.timestamp())),
                    ).fetchall()
                    rows = [
                        (int(ts), float(bid) if bid is not None else None, levels)
                        for ts, bid, levels in snapshots
                    ]
                    tp = first_cross(rows, TAKE_PROFIT, at_or_above=True)
                    stop = first_cross(rows, STOP_BID, at_or_above=False)
                    if tp and stop:
                        first = "take_profit" if tp[0] < stop[0] else (
                            "stop" if stop[0] < tp[0] else "same_snapshot"
                        )
                    elif tp:
                        first = "take_profit"
                    elif stop:
                        first = "stop"
                    else:
                        first = "no_trigger"

                    def fmt(snapshot: tuple[int, float, str | None] | None, index: int):
                        if snapshot is None:
                            return ""
                        if index == 0:
                            return dt.datetime.fromtimestamp(snapshot[0], dt.timezone.utc).isoformat()
                        return snapshot[index]

                    tp_depth, tp_fill, tp_vwap = sweep(
                        parsed_bids(tp[2]) if tp else [], shares, minimum_price=TAKE_PROFIT
                    )
                    stop_depth, stop_fill, stop_vwap = sweep(
                        parsed_bids(stop[2]) if stop else [], shares
                    )

                    complete = end >= event_end(day, city)
                    writer.writerow([
                        bot, city, day.isoformat(), entry.isoformat(),
                        ask if ask is not None else "", shares if shares is not None else "",
                        len(rows),
                        dt.datetime.fromtimestamp(rows[0][0], dt.timezone.utc).isoformat() if rows else "",
                        dt.datetime.fromtimestamp(rows[-1][0], dt.timezone.utc).isoformat() if rows else "",
                        fmt(tp, 0), fmt(tp, 1), tp_depth if tp else "", tp_fill if tp else "",
                        tp_vwap if tp else "", bool(tp and shares is not None and tp_fill >= shares),
                        fmt(stop, 0), fmt(stop, 1), stop_depth if stop else "",
                        stop_fill if stop else "", stop_vwap if stop else "",
                        bool(stop and shares is not None and stop_fill >= shares), first, complete,
                    ])
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
