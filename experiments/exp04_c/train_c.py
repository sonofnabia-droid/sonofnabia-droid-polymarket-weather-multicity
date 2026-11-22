#!/usr/bin/env python3
"""EXP04-C: original Cassiopeia features and six-observation target on METAR.

Experimental only. No production model or bot modifications.
"""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from zoneinfo import ZoneInfo

from cities.config import get_city
from cassiopeia_train import (
    FEATURE_COLS,
    REBOUND_FUTURE_SLOTS,
    REBOUND_DELTA_THRESHOLD,
    _get_ceil_slot,
    _train_lgbm,
    load_csv,
)
from cassiopeia_predictor import build_features, compute_prev7


def num(row, key, default):
    v = row.get(key, np.nan)
    try:
        return float(v) if pd.notna(v) else float(default)
    except (ValueError, TypeError):
        return float(default)


def build_dataset(df, city):
    df = df.copy()
    df["utc"] = pd.to_datetime(df["timestamp_utc"], utc=True, errors="coerce")
    df["temp_c"] = pd.to_numeric(df["temp_c"], errors="coerce")
    df = df.dropna(subset=["utc", "temp_c"])
    df = df.sort_values("utc").drop_duplicates("utc", keep="last")

    local = df["utc"].dt.tz_convert(ZoneInfo(city.timezone))
    df["day"] = local.dt.date
    df["local_hour"] = local.dt.hour
    df["local_minute"] = local.dt.minute

    ceil_slot = _get_ceil_slot()
    min_hour = int(getattr(city, "cassiopeia_min_hour_target", 12))

    rows = []
    history_max = {}
    prior_map = {}

    for day, group in df.groupby("day", sort=True):
        group = group.sort_values("utc").reset_index(drop=True)
        temps = group["temp_c"].to_numpy(dtype=float)

        prev7 = compute_prev7(history_max, day, city.name)
        slots = []
        day_prior_updates = []

        for i, row in group.iterrows():
            h, m = ceil_slot(int(row["local_hour"]), int(row["local_minute"]))

            if not (city.day_start <= h <= city.day_end):
                continue

            temp = float(row["temp_c"])
            slot = {
                "hour": h,
                "slot30": m,
                "temp_c": temp,
                "humidity": num(row, "humidity", num(row, "humidity_pct", 70)),
                "cloud_cover": num(row, "cloud_cover", num(row, "sky_cover", 50)),
                "dewpoint_c": num(row, "dewpoint_c", num(row, "dewpt_c", temp - 10)),
                "pressure_hpa": num(row, "pressure_hpa", 1013),
                "wind_dir_deg": num(row, "wind_dir_deg", 0),
                "wind_speed_kmh": num(row, "wind_speed_kmh", 5),
                "wind_gust_kmh": num(row, "wind_gust_kmh", 8),
                "uv_index": num(row, "uv_index", 3),
                "cloud_real": num(row, "cloud_real", 50),
                "precip_last_3h": num(row, "precip_last_3h", 0),
            }
            slots.append(slot)

            if h < min_hour or i + REBOUND_FUTURE_SLOTS >= len(group):
                continue

            running_max = max(s["temp_c"] for s in slots)
            future_max = float(np.max(
                temps[i + 1:i + 1 + REBOUND_FUTURE_SLOTS]
            ))
            label = int(
                future_max > running_max + REBOUND_DELTA_THRESHOLD
            )

            key = (day.month, h, m)
            features = build_features(
                slots,
                {**slot, "prev_7d_avg_max": prev7},
                day.month,
                day.timetuple().tm_yday,
            )
            features["seasonal_peak_prior"] = prior_map.get(key, 0.5)

            rows.append({
                **features,
                "date": day,
                "label": label,
                "hour": h,
                "slot30": m,
            })
            day_prior_updates.append((key, label))

        # Prior causal: updates only after the local day.
        # Freeze at end of 2024; never learn from 2025 OOS labels.
        if day.year <= 2024:
            for key, label in day_prior_updates:
                if key in prior_map:
                    prior_map[key] = 0.9 * prior_map[key] + 0.1 * label
                else:
                    prior_map[key] = float(label)

        history_max[day] = float(np.max(temps))

    return pd.DataFrame(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--city", default="munich")
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()

    source = Path("historic_metar") / f"{args.city}.csv"
    output = Path("experiments/exp04_c") / args.city

    print("EXP04-C | city:", args.city)
    print("Source:", source)
    print("Output:", output)
    print("Target: next 6 observations, delta > 0.3C")
    print("Train <= 2022; validation 2023-2024; OOS 2025")

    if not args.run:
        print("PREFLIGHT: no training or writing.")
        return

    if output.exists():
        raise SystemExit(f"REFUSING existing output: {output}")

    city = get_city(args.city)
    df = load_csv(source, city_name=args.city)

    # Preserve 2026 as a later untouched holdout.
    utc = pd.to_datetime(df["timestamp_utc"], utc=True, errors="coerce")
    local = utc.dt.tz_convert(city.timezone)
    df = df.loc[local.dt.year <= 2025].copy()

    dataset = build_dataset(df, city)
    dataset["date"] = pd.to_datetime(dataset["date"])

    features = [
        c for c in FEATURE_COLS
        if c in dataset.columns and dataset[c].nunique(dropna=True) > 1
    ]

    dataset = dataset.replace([np.inf, -np.inf], np.nan)
    dataset = dataset.dropna(subset=features + ["label"])

    train = dataset[dataset.date <= "2022-12-31"]
    val = dataset[
        (dataset.date >= "2023-01-01")
        & (dataset.date <= "2024-12-31")
    ]
    test = dataset[
        (dataset.date >= "2025-01-01")
        & (dataset.date <= "2025-12-31")
    ]

    for name, part in [("train", train), ("val", val), ("test", test)]:
        print(name, len(part), "positive_rate", part.label.mean())
        if len(part) < 200 or part.label.nunique() < 2:
            raise SystemExit(f"Insufficient {name} data")

    Xtr = train[features].astype(np.float32).values
    Xva = val[features].astype(np.float32).values
    Xte = test[features].astype(np.float32).values

    model = _train_lgbm(
        Xtr, train.label.astype(int).values,
        Xva, val.label.astype(int).values,
    )

    from sklearn.metrics import roc_auc_score, brier_score_loss, log_loss

    p = np.clip(
        model.predict(Xte, num_iteration=model.best_iteration),
        1e-7, 1 - 1e-7,
    )
    y = test.label.astype(int).values

    metrics = {
        "samples": len(y),
        "positive_rate": float(y.mean()),
        "auc": float(roc_auc_score(y, p)),
        "brier": float(brier_score_loss(y, p)),
        "logloss": float(log_loss(y, p)),
    }

    output.mkdir(parents=True, exist_ok=False)
    import joblib
    joblib.dump(model, output / "experimental_lgbm.pkl")

    report = {
        "experiment": "EXP04-C",
        "city": args.city,
        "target": "next_six_observations_delta_gt_0.3C",
        "features": features,
        "train_samples": len(train),
        "validation_samples": len(val),
        "test_2025": metrics,
        "experimental_only": True,
    }

    (output / "report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
