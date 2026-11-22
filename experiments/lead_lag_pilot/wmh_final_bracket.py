#!/usr/bin/env python3
"""Exploratory grouped-softmax W/M/H for the final Gamma-indicated bracket.

Read-only SQLite queries and local METAR history. Prints temporal walk-forward
metrics only; does not persist predictions or fit production models.
"""
import bisect
import csv
import datetime as dt
import json
import math
import re
import sqlite3
from collections import defaultdict
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
from scipy.optimize import minimize
from scipy.special import logsumexp

ROOT = Path(__file__).resolve().parents[2]
DB = sqlite3.connect(f"file:{ROOT / 'data/polymarket_weather_2026.sqlite'}?mode=ro", uri=True)
DB.execute("PRAGMA query_only=ON")
ZONES = {"munich": "Europe/Berlin", "lucknow": "Asia/Kolkata"}
START, END = "2026-03-05", "2026-07-17"
TRAIN_END, EVAL_START, EVAL_END = "2026-06-21", "2026-06-22", "2026-07-17"
# Primary pre-registered decision time. Other hours remain secondary work.
HOURS = (15,)
BRACKET_RE = re.compile(r"(-?\d+)°C(?: or (below|higher))?")
L2 = 1.0  # fixed before this run; no tuning on the evaluation block
SERIES_CACHE = {}


def winner_from_rows(rows):
    winners = []
    for row in rows:
        try:
            meta = json.loads(row["raw_json"] or "{}")
            outcomes = meta.get("outcomes", [])
            outcomes = json.loads(outcomes) if isinstance(outcomes, str) else outcomes
            prices = json.loads(row["outcome_prices"] or "[]")
            yes_i = next(i for i, x in enumerate(outcomes) if str(x).upper() == "YES")
            if row["closed"] and float(prices[yes_i]) >= .999:
                winners.append(row["bracket"])
        except (ValueError, TypeError, KeyError, IndexError, StopIteration):
            pass
    return winners[0] if len(winners) == 1 else None


def bracket_sort_key(name):
    m = BRACKET_RE.fullmatch(name or "")
    if not m:
        return (1, 0)
    bound, side = int(m.group(1)), m.group(2)
    return (0, bound - .5 if side == "below" else bound + .5 if side == "higher" else bound)


def bracket_for_temp(temp, names):
    rounded = math.floor(temp + .5)
    for name in names:
        m = BRACKET_RE.fullmatch(name or "")
        if not m:
            continue
        bound, side = int(m.group(1)), m.group(2)
        if (side is None and rounded == bound) or (side == "below" and rounded <= bound) or (side == "higher" and rounded >= bound):
            return name
    return None


def read_metar():
    result = defaultdict(list)
    for city, zone_name in ZONES.items():
        with (ROOT / "historic_metar" / f"{city}.csv").open(newline="") as f:
            for row in csv.DictReader(f):
                try:
                    stamp = dt.datetime.fromisoformat(row["timestamp_utc"])
                    stamp = stamp.replace(tzinfo=dt.timezone.utc) if stamp.tzinfo is None else stamp.astimezone(dt.timezone.utc)
                    if START <= stamp.astimezone(ZoneInfo(zone_name)).date().isoformat() <= END:
                        result[(city, stamp.astimezone(ZoneInfo(zone_name)).date().isoformat())].append((stamp, float(row["temp_c"])))
                except (ValueError, TypeError, KeyError):
                    continue
    for values in result.values():
        values.sort()
    return result


def market_rows(city, day):
    rows = DB.execute(
        "SELECT m.market_id,m.bracket,m.closed,m.outcome_prices,m.raw_json,t.token_id "
        "FROM markets m JOIN tokens t ON t.market_id=m.market_id "
        "WHERE m.city=? AND m.market_date=? AND t.outcome='YES'",
        (city, day),
    ).fetchall()
    return [dict(zip(("market_id", "bracket", "closed", "outcome_prices", "raw_json", "token_id"), x)) for x in rows]


def quote_series(token, start_epoch, end_epoch):
    key = (token, start_epoch, end_epoch)
    if key not in SERIES_CACHE:
        SERIES_CACHE[key] = DB.execute(
        "SELECT ts,price FROM price_points WHERE token_id=? AND fidelity_minutes=5 "
        "AND ts>=? AND ts<? ORDER BY ts", (token, start_epoch, end_epoch)
        ).fetchall()
    return SERIES_CACHE[key]


def price_before(values, target, max_age=600):
    ts = [int(x[0]) for x in values]
    i = bisect.bisect_right(ts, int(target)) - 1
    if i < 0 or target - ts[i] > max_age:
        return None
    return float(values[i][1]), int(target - ts[i])


def build_events():
    metar = read_metar()
    events = DB.execute(
        "SELECT city,market_date,timezone FROM events WHERE city IN ('munich','lucknow') "
        "AND market_date BETWEEN ? AND ? AND status='found' ORDER BY market_date,city",
        (START, END),
    ).fetchall()
    groups, counts = [], defaultdict(int)
    for city, day, db_zone in events:
        zone = ZoneInfo(db_zone or ZONES[city])
        date = dt.date.fromisoformat(day)
        markets = market_rows(city, day)
        winner = winner_from_rows(markets)
        if not winner:
            counts["no_unique_gamma_winner"] += 1
            continue
        markets.sort(key=lambda r: bracket_sort_key(r["bracket"]))
        if len(markets) < 3 or any(bracket_sort_key(r["bracket"])[0] for r in markets):
            counts["invalid_ladder"] += 1
            continue
        names = [r["bracket"] for r in markets]
        if winner not in names:
            counts["winner_not_in_ladder"] += 1
            continue
        date0 = dt.datetime.combine(date, dt.time.min, zone)
        day_start = int(date0.timestamp())
        day_end = int((date0 + dt.timedelta(days=1)).timestamp())
        series = metar[(city, day)]
        for hour in HOURS:
            decision = dt.datetime.combine(date, dt.time(hour), zone)
            cut_utc = decision.astimezone(dt.timezone.utc)
            weather_cut = cut_utc - dt.timedelta(minutes=15)
            past = [x for x in series if x[0] <= weather_cut]
            if len(past) < 4 or (weather_cut - past[-1][0]).total_seconds() > 90 * 60:
                counts["weather_missing"] += 1
                counts[f"{city}_weather_missing"] += 1
                counts[f"{city}_{day[:7]}_weather_missing"] += 1
                continue
            running_max = max(x[1] for x in past)
            weather_bracket = bracket_for_temp(running_max, names)
            if not weather_bracket:
                counts["weather_outside_ladder"] += 1
                continue
            counts[f"{city}_weather_available"] += 1
            latest_t, latest_temp = past[-1]
            last_max_t = max(t for t, value in past if abs(value - running_max) < .01)
            age_since_max_min = (weather_cut - last_max_t).total_seconds() / 60
            below_max = running_max - latest_temp
            lag_target = latest_t - dt.timedelta(minutes=60)
            lag_obs = [x for x in past if x[0] <= lag_target]
            warming_60 = (latest_temp - lag_obs[-1][1]) if lag_obs and (lag_target-lag_obs[-1][0]).total_seconds() <= 30*60 else 0.0
            plateau_start = latest_t if latest_temp >= running_max - .5 else None
            if plateau_start:
                for obs_t, obs_temp in reversed(past[:-1]):
                    if (plateau_start - obs_t).total_seconds() > 60*60 or obs_temp < running_max - .5:
                        break
                    plateau_start = obs_t
                plateau_min = (latest_t - plateau_start).total_seconds() / 60
            else:
                plateau_min = 0.0
            epoch = int(cut_utc.timestamp())
            quotes = []
            missing_current = missing_lag = False
            for rank_i, row in enumerate(markets):
                vals = quote_series(row["token_id"], day_start, day_end)
                q = price_before(vals, epoch)
                q15 = price_before(vals, epoch - 900)
                if q is None:
                    missing_current = True
                    counts[f"missing_current_rank_{rank_i}"] += 1
                    counts[f"{city}_missing_current_rank_{rank_i}"] += 1
                if q15 is None:
                    missing_lag = True
                    counts[f"missing_lag_rank_{rank_i}"] += 1
                if q is not None and q15 is not None:
                    quotes.append((q[0], q15[0], q[1]))
            if len(quotes) != len(markets):
                counts["quote_or_momentum_missing"] += 1
                counts[f"{city}_quote_or_momentum_missing"] += 1
                if missing_current:
                    counts["current_quote_missing"] += 1
                    counts[f"{city}_current_quote_missing"] += 1
                    counts[f"{city}_{day[:7]}_current_quote_missing"] += 1
                elif missing_lag:
                    counts["momentum_lag_missing"] += 1
                    counts[f"{city}_momentum_lag_missing"] += 1
                    counts[f"{city}_{day[:7]}_momentum_lag_missing"] += 1
                continue
            if winner not in names:
                continue
            prices = np.array([x[0] for x in quotes], dtype=float)
            total = float(prices.sum())
            if total <= 0:
                counts["invalid_price_sum"] += 1
                continue
            normalized = prices / total
            order = np.argsort(np.argsort(-prices, kind="stable"), kind="stable")
            market_X, weather_X, weather_dyn_X = [], [], []
            wi = names.index(weather_bracket)
            n = len(names)
            for i, (p, old, age) in enumerate(quotes):
                relative = i - wi
                logit = math.log(min(.999, max(.001, p)) / (1 - min(.999, max(.001, p))))
                momentum = p - old
                is_munich = float(city == "munich")
                market_X.append([logit, normalized[i], float(order[i]) / max(1, n - 1), momentum, abs(momentum), age / 600])
                weather_X.append([relative, abs(relative), relative * relative, float(relative == 0), float(relative > 0), float(relative < 0), is_munich * relative, is_munich * float(relative == 0)])
                weather_dyn_X.append(weather_X[-1] + [
                    relative * age_since_max_min / 180,
                    relative * below_max,
                    relative * warming_60,
                    relative * plateau_min / 180,
                    relative * (weather_cut-latest_t).total_seconds() / 3600,
                ])
            groups.append({"city": city, "day": day, "hour": hour, "names": names,
                           "y": names.index(winner), "price_p": normalized,
                           "weather_i": wi, "market_i": int(np.argmax(normalized)),
                           "quote_age_max_sec": max(x[2] for x in quotes),
                           "market_rank_winner": int(order[names.index(winner)]) + 1,
                           "W": np.asarray(weather_X, dtype=float), "WD": np.asarray(weather_dyn_X, dtype=float),
                           "M": np.asarray(market_X, dtype=float)})
            counts["eligible_groups"] += 1
            counts[f"{city}_eligible_groups"] += 1
            counts[f"{city}_{day[:7]}_eligible"] += 1
    return groups, counts


def fit_grouped_softmax(train_groups, feature_key):
    matrices = [g[feature_key] for g in train_groups]
    all_x = np.vstack(matrices)
    mean = all_x.mean(axis=0)
    scale = all_x.std(axis=0)
    scale[scale < 1e-8] = 1.0
    xs = [(x - mean) / scale for x in matrices]
    sizes = np.asarray([len(x) for x in xs], dtype=int)
    starts = np.concatenate(([0], np.cumsum(sizes)[:-1]))
    all_x = np.vstack(xs)
    target_rows = starts + np.asarray([g["y"] for g in train_groups], dtype=int)
    dim = all_x.shape[1]

    def objective(beta):
        b = beta.reshape(dim)
        scores = all_x @ b
        max_scores = np.maximum.reduceat(scores, starts)
        exp_scores = np.exp(scores - np.repeat(max_scores, sizes))
        sums = np.add.reduceat(exp_scores, starts)
        log_z = max_scores + np.log(sums)
        probs = exp_scores / np.repeat(sums, sizes)
        n = len(sizes)
        loss = np.sum(log_z - scores[target_rows]) / n
        grad = (all_x.T @ probs - np.sum(all_x[target_rows], axis=0)) / n
        return loss + .5 * L2 * float(b @ b), grad + L2 * b

    res = minimize(lambda b: objective(b), np.zeros(dim), jac=True, method="L-BFGS-B", options={"maxiter":250,"ftol":1e-9})
    if not res.success and not np.isfinite(res.fun):
        raise RuntimeError(f"Grouped softmax optimization failed: {res.message}")
    return res.x, mean, scale


def predict(group, fitted, feature_key):
    beta, mean, scale = fitted
    x = (group[feature_key] - mean) / scale
    scores = x @ beta
    return np.exp(scores - logsumexp(scores))


def metrics(rows, pred_key):
    loss, brier, hits = [], [], []
    for g in rows:
        p = g[pred_key]
        y = g["y"]
        loss.append(-math.log(max(1e-12, float(p[y]))))
        onehot = np.zeros(len(p)); onehot[y] = 1
        brier.append(float(np.sum((p - onehot) ** 2)))
        hits.append(int(int(np.argmax(p)) == y))
    return float(np.mean(brier)), float(np.mean(loss)), float(np.mean(hits))


def main():
    groups, counts = build_events()
    print("eligibility", dict(counts), "groups", len(groups), "hours", HOURS)
    for rank_i in range(11):
        total_missing = counts.get(f"missing_current_rank_{rank_i}", 0)
        denom = sum(counts.get(f"{city}_weather_available", 0) for city in ZONES)
        print("missing_current_by_ladder_rank", rank_i, "tokens_missing", total_missing,
              "events_with_weather", denom, "rate", round(total_missing / denom, 4) if denom else None)
        print("  by_city", {city: {
            "missing": counts.get(f"{city}_missing_current_rank_{rank_i}", 0),
            "weather_available": counts.get(f"{city}_weather_available", 0),
        } for city in ZONES})
    for city in ZONES:
        months = sorted({g["day"][:7] for g in groups if g["city"] == city})
        for month in months:
            print("coverage_month", city, month, "eligible", counts.get(f"{city}_{month}_eligible",0),
                  "missing_current", counts.get(f"{city}_{month}_current_quote_missing",0),
                  "missing_lag", counts.get(f"{city}_{month}_momentum_lag_missing",0),
                  "weather_missing", counts.get(f"{city}_{month}_weather_missing",0))
    predictions = {k: [] for k in ("market_ladder", "W", "WD", "M", "H", "HD")}
    for test_day in sorted({g["day"] for g in groups if EVAL_START <= g["day"] <= EVAL_END}):
        cutoff = (dt.date.fromisoformat(test_day) - dt.timedelta(days=7)).isoformat()
        train = [g for g in groups if g["day"] <= cutoff]
        test = [g for g in groups if g["day"] == test_day]
        if len(train) < 20 or not test:
            continue
        try:
            fitted = {k: fit_grouped_softmax(train, k) for k in ("W", "WD", "M")}
        except RuntimeError as exc:
            print("fit_skip", test_day, str(exc)); continue
        for g in test:
            g0 = dict(g); g0["market_ladder"] = g["price_p"]
            g0["W"] = predict(g, fitted["W"], "W")
            g0["WD"] = predict(g, fitted["WD"], "WD")
            g0["M"] = predict(g, fitted["M"], "M")
            h_features = np.concatenate((g["W"], g["M"]), axis=1)
            g0["H_features"] = h_features
            g0["HD_features"] = np.concatenate((g["WD"], g["M"]), axis=1)
            g0["H"] = None
            g0["HD"] = None
            # H is fit per fold on the exact same training events.
            predictions["market_ladder"].append(g0)
        if test:
            # Refit H once per day, using the same frozen regularization.
            h_train, hd_train = [], []
            for g in train:
                h = dict(g); h["H"] = np.concatenate((g["W"], g["M"]), axis=1); h_train.append(h)
                hd = dict(g); hd["HD"] = np.concatenate((g["WD"], g["M"]), axis=1); hd_train.append(hd)
            h_fit = fit_grouped_softmax(h_train, "H")
            hd_fit = fit_grouped_softmax(hd_train, "HD")
            for g in predictions["market_ladder"]:
                if g["day"] == test_day:
                    g["H"] = predict({"H": g["H_features"]}, h_fit, "H")
                    g["HD"] = predict({"HD": g["HD_features"]}, hd_fit, "HD")
    eval_rows = [g for g in predictions["market_ladder"]]
    print("evaluation", "groups", len(eval_rows), "dates", len({g['day'] for g in eval_rows}),
          "cities", {c: sum(g['city']==c for g in eval_rows) for c in ZONES},
          "hours", {h: sum(g['hour']==h for g in eval_rows) for h in HOURS}, "brackets_median", int(np.median([len(g['names']) for g in eval_rows])) if eval_rows else 0)
    both = sum(g["weather_i"] == g["y"] and g["market_i"] == g["y"] for g in eval_rows)
    weather_only = sum(g["weather_i"] == g["y"] and g["market_i"] != g["y"] for g in eval_rows)
    market_only = sum(g["weather_i"] != g["y"] and g["market_i"] == g["y"] for g in eval_rows)
    neither = len(eval_rows) - both - weather_only - market_only
    agreement = sum(g["weather_i"] == g["market_i"] for g in eval_rows)
    print("raw_candidate_overlap", "agreement", agreement, "both_correct", both,
          "weather_only_correct", weather_only, "market_only_correct", market_only, "neither", neither)
    def diagnostic(label, subset):
        if not subset:
            return
        n = len(subset)
        y_true = np.asarray([g["y"] for g in subset], dtype=int)
        brier_market = np.mean([np.sum((g["price_p"] - np.eye(len(g["price_p"]))[g["y"]]) ** 2) for g in subset])
        brier_h = np.mean([np.sum((g["HD"] - np.eye(len(g["HD"]))[g["y"]]) ** 2) for g in subset])
        mean_true = {k: float(np.mean([g[k][g["y"]] for g in subset])) for k in ("price_p", "W", "WD", "M", "H", "HD")}
        hit_market = np.mean([int(g["market_i"] == g["y"]) for g in subset])
        hit_weather = np.mean([int(g["weather_i"] == g["y"]) for g in subset])
        print("diagnostic", label, "n", n, "market_hit", round(float(hit_market),4),
              "weather_hit", round(float(hit_weather),4), "mean_p_true",
              {k: round(v,4) for k,v in mean_true.items()},
              "brier_market", round(float(brier_market),5), "brier_H_dyn", round(float(brier_h),5))
    for city in ZONES:
        diagnostic(f"city={city}", [g for g in eval_rows if g["city"] == city])
    for label, predicate in (
        ("winner_same_as_weather_bracket", lambda g: g["y"] == g["weather_i"]),
        ("winner_one_bracket_from_weather", lambda g: abs(g["y"] - g["weather_i"]) == 1),
        ("winner_2plus_from_weather", lambda g: abs(g["y"] - g["weather_i"]) >= 2),
        ("winner_market_rank_1", lambda g: g["market_rank_winner"] == 1),
        ("winner_market_rank_2", lambda g: g["market_rank_winner"] == 2),
        ("winner_market_rank_3plus", lambda g: g["market_rank_winner"] >= 3),
        ("max_quote_age_le_300s", lambda g: g["quote_age_max_sec"] <= 300),
        ("max_quote_age_301_600s", lambda g: 300 < g["quote_age_max_sec"] <= 600),
    ):
        diagnostic(label, [g for g in eval_rows if predicate(g)])
    for method in ("market_ladder", "W", "WD", "M", "H", "HD"):
        if method == "market_ladder":
            vals = [(g, g["price_p"]) for g in eval_rows]
        else:
            vals = [(g, g[method]) for g in eval_rows]
        temp = []
        for g, p in vals:
            x = dict(g); x[method] = p; temp.append(x)
        brier, ll, acc = metrics(temp, method)
        print("overall", method, "n", len(temp), "brier", round(brier, 6), "logloss", round(ll, 6), "accuracy", round(acc, 4))
        for hour in HOURS:
            sub = [x for x in temp if x["hour"] == hour]
            if sub:
                mb, ml, ma = metrics(sub, method)
                print("  hour", hour, "n", len(sub), "brier", round(mb, 6), "logloss", round(ml, 6), "accuracy", round(ma, 4))
        for city in ZONES:
            sub = [x for x in temp if x["city"] == city]
            if sub:
                mb, ml, ma = metrics(sub, method)
                print("  city", city, "n", len(sub), "brier", round(mb, 6), "logloss", round(ml, 6), "accuracy", round(ma, 4))
    # Day-clustered paired Brier deltas against normalized market ladder.
    for method in ("W", "WD", "M", "H", "HD"):
        by_day = defaultdict(list)
        for g in eval_rows:
            yh = np.zeros(len(g["price_p"])); yh[g["y"]] = 1
            p = g[method]
            by_day[g["day"]].append(float(np.sum((p-yh)**2) - np.sum((g["price_p"]-yh)**2)))
        daily = np.array([np.mean(v) for v in by_day.values()])
        if len(daily):
            rng = np.random.default_rng(20261116 + len(method))
            boot = np.array([daily[rng.integers(0, len(daily), len(daily))].mean() for _ in range(5000)])
            print("delta_vs_market_brier", method, "delta", round(float(daily.mean()),6),
                  "bootstrap95", np.round(np.quantile(boot,[.025,.975]),6).tolist(), "dates", len(daily))
    for richer, simpler in (("WD", "W"), ("HD", "H")):
        by_day = defaultdict(list)
        for g in eval_rows:
            yh = np.zeros(len(g["price_p"])); yh[g["y"]] = 1
            by_day[g["day"]].append(float(np.sum((g[richer]-yh)**2) - np.sum((g[simpler]-yh)**2)))
        daily = np.array([np.mean(v) for v in by_day.values()])
        rng = np.random.default_rng(20261116 + len(richer) + len(simpler))
        boot = np.array([daily[rng.integers(0, len(daily), len(daily))].mean() for _ in range(5000)])
        print("delta_dynamics_vs_simple_brier", richer, "minus", simpler,
              "delta", round(float(daily.mean()),6), "bootstrap95",
              np.round(np.quantile(boot,[.025,.975]),6).tolist(), "dates", len(daily))


if __name__ == "__main__":
    main()
