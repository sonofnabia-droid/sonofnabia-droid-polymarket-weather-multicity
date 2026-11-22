#!/usr/bin/env python3
"""Exploratory candidate-risk screen: weather plateau x 5m price dynamics.

Reads only Munich/Lucknow event, METAR history, and 5m YES price points from
the archive. SQLite is opened read-only/query-only. Prints metrics; writes no
model or data. The historical period is exposed and Gamma updatedAt is not a
proof of label availability.
"""
import bisect
import csv
import datetime as dt
import json
import math
import re
import sqlite3
import statistics
from collections import defaultdict
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler


ROOT = Path(__file__).resolve().parents[2]
DB = sqlite3.connect(f"file:{ROOT / 'data/polymarket_weather_2026.sqlite'}?mode=ro", uri=True)
DB.execute("PRAGMA query_only=ON")
ZONES = {"lucknow": "Asia/Kolkata", "munich": "Europe/Berlin"}
HOURS = (9, 11, 13, 15, 17)
START, END = "2026-03-05", "2026-07-17"
EVAL_START, EVAL_END = "2026-06-22", "2026-07-17"
WEATHER_DELAY_MIN = 15
PRICE_MAX_AGE_SEC = 600
LABEL_EMBARGO_DAYS = 7  # timing proxy only; not verified label availability
BRACKET_RE = re.compile(r"(-?\d+)°C(?: or (below|higher))?")


def parse_bracket_for_temp(temp, names):
    for name in names:
        match = BRACKET_RE.fullmatch(name or "")
        if not match:
            continue
        bound, side = int(match.group(1)), match.group(2)
        if (side is None and float(temp) == bound) or (side == "below" and temp <= bound) or (side == "higher" and temp >= bound):
            return name
    return None


def gamma_winner(markets):
    winners = []
    for name, closed, prices_json, raw_json, _token in markets:
        try:
            meta = json.loads(raw_json)
            outcomes = meta.get("outcomes", [])
            outcomes = json.loads(outcomes) if isinstance(outcomes, str) else outcomes
            yes_ix = next(i for i, value in enumerate(outcomes) if str(value).upper() == "YES")
            prices = json.loads(prices_json or "[]")
            if closed and float(prices[yes_ix]) >= 0.999:
                winners.append(name)
        except (ValueError, TypeError, KeyError, IndexError, StopIteration):
            continue
    return winners[0] if len(winners) == 1 else None


def nearest_before(series, target, tolerance_min):
    times = [x[0] for x in series]
    ix = bisect.bisect_right(times, target) - 1
    if ix < 0 or (target - series[ix][0]).total_seconds() > tolerance_min * 60:
        return None
    return series[ix]


def weather_features(series, decision):
    cutoff = decision - dt.timedelta(minutes=WEATHER_DELAY_MIN)
    eligible = [x for x in series if x[0] <= cutoff]
    if len(eligible) < 4 or (cutoff - eligible[-1][0]).total_seconds() > 90 * 60:
        return None

    latest_t, latest_temp = eligible[-1]
    running_max = max(value for _, value in eligible)
    latest_max_t = max(t for t, value in eligible if abs(value - running_max) < 0.01)
    age_max_min = (cutoff - latest_max_t).total_seconds() / 60
    below_max = running_max - latest_temp

    lag60 = nearest_before(eligible, latest_t - dt.timedelta(minutes=60), 30)
    lag30 = nearest_before(eligible, latest_t - dt.timedelta(minutes=30), 20)
    lag60b = nearest_before(eligible, latest_t - dt.timedelta(minutes=60), 20)
    lag90 = nearest_before(eligible, latest_t - dt.timedelta(minutes=90), 25)
    if lag60 is None or lag30 is None or lag60b is None or lag90 is None:
        return None
    warming_1h = latest_temp - lag60[1]
    acceleration_30m = (latest_temp - lag30[1]) - (lag30[1] - lag60b[1])

    streak = [eligible[-1]] if latest_temp >= running_max - 0.5 else []
    if streak:
        for row in reversed(eligible[:-1]):
            if (streak[0][0] - row[0]).total_seconds() > 60 * 60 or row[1] < running_max - 0.5:
                break
            streak.insert(0, row)
    plateau_min = (latest_t - streak[0][0]).total_seconds() / 60 if streak else 0.0
    return {
        "running_max": running_max,
        "below_max": below_max,
        "age_max_h": age_max_min / 60,
        "plateau_h": plateau_min / 60,
        "warming_1h": warming_1h,
        "acceleration_30m": acceleration_30m,
        "last_obs_age_min": (cutoff - latest_t).total_seconds() / 60,
    }


def price_at(points, target_ts):
    ts, prices = points
    ix = bisect.bisect_right(ts, target_ts) - 1
    if ix < 0 or target_ts - ts[ix] > PRICE_MAX_AGE_SEC:
        return None
    return prices[ix]


def make_rows():
    observations = defaultdict(list)
    for city, zone in ZONES.items():
        path = ROOT / "historic_metar" / f"{city}.csv"
        with path.open(newline="") as src:
            for row in csv.DictReader(src):
                try:
                    stamp = dt.datetime.fromisoformat(row["timestamp_utc"])
                    stamp = stamp.replace(tzinfo=dt.timezone.utc) if stamp.tzinfo is None else stamp.astimezone(dt.timezone.utc)
                    if row.get("temp_c"):
                        local_day = stamp.astimezone(ZoneInfo(zone)).date().isoformat()
                        observations[(city, local_day)].append((stamp, float(row["temp_c"])))
                except (ValueError, KeyError, TypeError):
                    continue
    for values in observations.values():
        values.sort()

    events = DB.execute(
        "SELECT city,market_date,timezone FROM events "
        "WHERE city IN ('lucknow','munich') AND market_date BETWEEN ? AND ? "
        "AND status='found' ORDER BY market_date,city",
        (START, END),
    ).fetchall()
    rows = []
    for city, day, market_tz in events:
        zone = ZoneInfo(market_tz or ZONES[city])
        date = dt.date.fromisoformat(day)
        markets = DB.execute(
            "SELECT m.bracket,m.closed,m.outcome_prices,m.raw_json,t.token_id "
            "FROM markets m JOIN tokens t ON t.market_id=m.market_id "
            "WHERE m.city=? AND m.market_date=? AND t.outcome='YES'",
            (city, day),
        ).fetchall()
        markets = sorted(
            markets,
            key=lambda row: int(BRACKET_RE.fullmatch(row[0] or "").group(1))
            if BRACKET_RE.fullmatch(row[0] or "") else 0,
        )
        winner = gamma_winner(markets)
        if not winner:
            continue

        names = [row[0] for row in markets]
        start_ts = int(dt.datetime.combine(date, dt.time.min, zone).timestamp())
        end_ts = int(dt.datetime.combine(date + dt.timedelta(days=1), dt.time.min, zone).timestamp())
        points = {}
        for name, _closed, _prices, _raw, token in markets:
            values = DB.execute(
                "SELECT ts,price FROM price_points WHERE token_id=? AND fidelity_minutes=5 "
                "AND ts>=? AND ts<? ORDER BY ts",
                (token, start_ts, end_ts),
            ).fetchall()
            if values:
                points[name] = ([x[0] for x in values], [float(x[1]) for x in values])

        for hour in HOURS:
            decision = dt.datetime.combine(date, dt.time(hour), zone).astimezone(dt.timezone.utc)
            weather = weather_features(observations[(city, day)], decision)
            if weather is None:
                continue
            candidate = parse_bracket_for_temp(weather["running_max"], names)
            if candidate is None:
                continue

            epoch = int(decision.timestamp())
            quotes = {}
            quote_ages = []
            momentum = {}
            for name in names:
                token_points = points.get(name)
                if not token_points:
                    continue
                current = price_at(token_points, epoch)
                if current is None:
                    continue
                quotes[name] = current
                ix = bisect.bisect_right(token_points[0], epoch) - 1
                quote_ages.append(epoch - token_points[0][ix])
                lag_prices = [price_at(token_points, epoch - offset * 60) for offset in (5, 10, 15, 30)]
                if any(value is None for value in lag_prices):
                    momentum[name] = None
                else:
                    p5, p10, p15, p30 = lag_prices
                    momentum[name] = (current - p5, current - p15, current - p30, (current - p5) - (p5 - p10))

            if len(quotes) != len(names) or len(momentum) != len(names) or any(v is None for v in momentum.values()):
                continue
            leader_price = max(quotes.values())
            leaders = [name for name, price in quotes.items() if price == leader_price]
            if len(leaders) != 1:
                continue

            total_price = sum(quotes.values())
            candidate_price = quotes[candidate]
            upper_sum = sum(price for name, price in quotes.items() if names.index(name) > names.index(candidate))
            candidate_rank = 1 + sum(price > candidate_price for price in quotes.values())
            d5, d15, d30, acceleration = momentum[candidate]
            local_hour = hour
            harmonic = 2 * math.pi * local_hour / 24
            base = [
                float(city == "munich"), math.sin(harmonic), math.cos(harmonic),
                weather["running_max"], weather["below_max"], weather["age_max_h"],
                weather["plateau_h"], weather["warming_1h"], weather["acceleration_30m"],
            ]
            market = [
                float(candidate_price / total_price) if total_price > 0 else candidate_price,
                float(candidate_price), float(leader_price - candidate_price),
                float(candidate == leaders[0]), float(candidate_rank), float(upper_sum),
                float(d5), float(d15), float(d30), float(acceleration),
            ]
            rows.append({
                "city": city, "day": day, "hour": hour,
                "y": int(candidate == winner),
                "market_p": float(candidate_price / total_price) if total_price > 0 else float(candidate_price),
                "weather": base, "market": [float(city == "munich"), math.sin(harmonic), math.cos(harmonic)] + market,
                "hybrid": base + market,
                "quote_age_sec": statistics.median(quote_ages),
                "plateau_h": weather["plateau_h"], "age_max_h": weather["age_max_h"],
                "warming_1h": weather["warming_1h"], "acceleration_30m": weather["acceleration_30m"],
            })
    return rows


def score(pairs):
    y = np.asarray([r[1] for r in pairs], dtype=int)
    p = np.clip(np.asarray([r[2] for r in pairs], dtype=float), 1e-6, 1 - 1e-6)
    return brier_score_loss(y, p), log_loss(y, p, labels=[0, 1])


def main():
    rows = make_rows()
    by_day = defaultdict(list)
    for row in rows:
        by_day[row["day"]].append(row)

    methods = {"market_price": "market_p", "W": "weather", "M": "market", "H": "hybrid"}
    predictions = {name: [] for name in methods}
    prediction_rows = []
    for test_day in sorted(d for d in by_day if EVAL_START <= d <= EVAL_END):
        cutoff = (dt.date.fromisoformat(test_day) - dt.timedelta(days=LABEL_EMBARGO_DAYS)).isoformat()
        train = [row for day, day_rows in by_day.items() if day <= cutoff for row in day_rows]
        test = by_day[test_day]
        y_train = np.asarray([row["y"] for row in train], dtype=int)
        if len(y_train) == 0 or min(int(y_train.sum()), int(len(y_train) - y_train.sum())) < 10:
            continue
        day_predictions = {"market_price": [(r, r["market_p"]) for r in test]}
        for method in ("W", "M", "H"):
            model = make_pipeline(StandardScaler(), LogisticRegression(C=1.0, max_iter=1000, random_state=20261116))
            x_train = np.asarray([row[methods[method]] for row in train])
            x_test = np.asarray([row[methods[method]] for row in test])
            model.fit(x_train, y_train)
            p = model.predict_proba(x_test)[:, 1]
            day_predictions[method] = list(zip(test, p))
        for method, pairs in day_predictions.items():
            predictions[method].extend((r["day"], r["city"], r["hour"], r["y"], float(p)) for r, p in pairs)
            for r, p in pairs:
                prediction_rows.append((method, r, float(p)))

    print("scope", START, END, "rows", len(rows), "eligible_eval_rows", len(predictions["H"]),
          "eval_dates", len({x[0] for x in predictions["H"]}), "embargo_days", LABEL_EMBARGO_DAYS)
    for method, vals in predictions.items():
        brier, logloss = score([(x[0], x[3], x[4]) for x in vals])
        print("overall", method, "n", len(vals), "brier", round(brier, 6), "logloss", round(logloss, 6))

    # The historical evaluation block is contaminated. These slices are only
    # diagnostics of heterogeneity, not hour/threshold selection.
    for city in ("munich", "lucknow"):
        for hour in HOURS:
            print("slice", city, hour, end=" ")
            for method, vals in predictions.items():
                subset = [x for x in vals if x[1] == city and x[2] == hour]
                if subset:
                    brier, _ = score([(x[0], x[3], x[4]) for x in subset])
                    print(f"{method}={len(subset)}:{brier:.4f}", end=" ")
            print()

    # Paired bootstrap of H-M Brier difference, resampling whole local dates.
    method_maps = {m: {(x[0], x[1], x[2]): x for x in vals} for m, vals in predictions.items()}
    shared = sorted(set(method_maps["H"]) & set(method_maps["M"]))
    day_deltas = defaultdict(list)
    for key in shared:
        hrow, mrow = method_maps["H"][key], method_maps["M"][key]
        day_deltas[key[0]].append((hrow[3] - hrow[4]) ** 2 - (mrow[3] - mrow[4]) ** 2)
    days = sorted(day_deltas)
    if days:
        values = np.asarray([np.mean(day_deltas[d]) for d in days])
        rng = np.random.default_rng(20261116)
        boot = np.asarray([values[rng.integers(0, len(values), len(values))].mean() for _ in range(5000)])
        print("H_minus_M_brier_by_day", "paired_dates", len(days), "delta", round(float(values.mean()), 6),
              "bootstrap95", np.round(np.quantile(boot, [0.025, 0.975]), 6).tolist())


if __name__ == "__main__":
    main()
