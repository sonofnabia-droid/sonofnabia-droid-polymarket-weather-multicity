#!/usr/bin/env python3
"""EXP04 C-180: A features on B's exact METAR samples and labels."""
import argparse
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score, brier_score_loss, log_loss

from cities.config import get_city
from cassiopeia_train import FEATURE_COLS, load_csv, _train_lgbm
from experiments.exp04_c180_noprior.b_with_timestamps import build as build_b
from cassiopeia_predictor import build_features, compute_prev7
from cassiopeia_train import _get_ceil_slot


def number(row, key, default):
    value = row.get(key, np.nan)
    try:
        return float(value) if pd.notna(value) else float(default)
    except (ValueError, TypeError):
        return float(default)


def build_c180(df, city):
    df = df.copy()
    df["_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True, errors="coerce")
    df["temp_c"] = pd.to_numeric(df["temp_c"], errors="coerce")
    df = df.dropna(subset=["_utc", "temp_c"]).sort_values("_utc")
    df = df.drop_duplicates("_utc", keep="last")

    local = df["_utc"].dt.tz_convert(city.timezone)
    df["_day"] = local.dt.date
    df["_hour"] = local.dt.hour
    df["_minute"] = local.dt.minute

    ceil_slot = _get_ceil_slot()
    min_hour = int(getattr(city, "cassiopeia_min_hour_target", 12))

    rows = []
    history_max = {}
    prior_map = {}

    for day, group in df.groupby("_day", sort=True):
        group = group.sort_values("_utc").reset_index(drop=True)
        ns = pd.DatetimeIndex(group["_utc"]).as_unit("ns").asi8
        temps = group["temp_c"].to_numpy(dtype=float)

        prev7 = compute_prev7(history_max, day, city.name)
        slots_by_key = {}
        history = []
        updates = []

        for i, row in group.iterrows():
            h, m = ceil_slot(int(row["_hour"]), int(row["_minute"]))
            if not (city.day_start <= h <= city.day_end):
                continue

            temp = float(row["temp_c"])
            slot = {
                "hour": h, "slot30": m, "temp_c": temp,
                "cloud_cover": number(row, "cloud_cover",
                                      number(row, "sky_cover", 50)),
                "humidity": number(row, "humidity",
                                   number(row, "humidity_pct", 70)),
                "dewpoint_c": number(row, "dewpoint_c",
                                     number(row, "dewpt_c", temp - 10)),
                "pressure_hpa": number(row, "pressure_hpa", 1013),
                "wind_dir_deg": number(row, "wind_dir_deg", 0),
                "wind_speed_kmh": number(row, "wind_speed_kmh", 5),
                "wind_gust_kmh": number(row, "wind_gust_kmh", 8),
                "uv_index": number(row, "uv_index", 3),
            }

            slots_by_key[(h, m)] = slot
            slots = [slots_by_key[k] for k in sorted(slots_by_key)]

            if h < min_hour or len(slots) < 4:
                continue

            dt = (ns[i + 1:] - ns[i]) / 60_000_000_000
            ix = np.where((dt > 0) & (dt <= 180))[0] + i + 1
            if len(ix) < 2:
                continue
            if (ns[ix[-1]] - ns[i]) < 150 * 60_000_000_000:
                continue

            running_max = max(s["temp_c"] for s in slots)
            label = int(float(np.max(temps[ix])) > running_max + 0.3)

            features = build_features(
                slots,
                {**slot, "prev_7d_avg_max": prev7},
                day.month,
                day.timetuple().tm_yday,
            )

            key = (day.month, h, m)
            features["seasonal_peak_prior"] = prior_map.get(key, 0.5)

            rows.append({
                **features,
                "date": day,
                "timestamp_utc": row["_utc"],
                "label": label,
            })
            updates.append((key, label))

        if day.year <= 2024:
            for key, label in updates:
                prior_map[key] = (
                    0.9 * prior_map[key] + 0.1 * label
                    if key in prior_map else float(label)
                )

        history_max[day] = float(np.max(temps))

    return pd.DataFrame(rows)


def metrics(y, p):
    y = np.asarray(y, dtype=int)
    p = np.clip(np.asarray(p, dtype=float), 1e-7, 1 - 1e-7)
    return {
        "samples": len(y),
        "positive_rate": float(y.mean()),
        "auc": float(roc_auc_score(y, p)),
        "brier": float(brier_score_loss(y, p)),
        "logloss": float(log_loss(y, p, labels=[0, 1])),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--city", default="munich")
    ap.add_argument("--run", action="store_true")
    args = ap.parse_args()

    source = Path("historic_metar") / f"{args.city}.csv"
    output = Path("experiments/exp04_c180_noprior") / args.city

    print("EXP04 C-180:", args.city)
    print("Output:", output)

    if not args.run:
        print("PREFLIGHT ONLY")
        return

    if output.exists():
        raise SystemExit("REFUSING existing output")

    city = get_city(args.city)
    df = load_csv(source, city_name=args.city)

    utc = pd.to_datetime(df["timestamp_utc"], utc=True, errors="coerce")
    local = utc.dt.tz_convert(city.timezone)
    df = df.loc[local.dt.year <= 2025].copy()

    # B is the reference for eligibility and labels.
    b, _ = build_b(df, city)
    c = build_c180(df, city)

    b["date"] = pd.to_datetime(b["date"])
    c["date"] = pd.to_datetime(c["date"])

    # Exact row order and target parity are required.
    if len(b) != len(c):
        raise SystemExit(
            f"PARITY FAILED: B={len(b)} C={len(c)} samples"
        )
    if not np.array_equal(b["label"].to_numpy(), c["label"].to_numpy()):
        raise SystemExit("PARITY FAILED: target labels differ")
    if not np.array_equal(b["date"].to_numpy(), c["date"].to_numpy()):
        raise SystemExit("PARITY FAILED: dates differ")

    if "timestamp_utc" not in b.columns:
        raise SystemExit(
            "PARITY NOT VERIFIED: B has no timestamp_utc column"
        )

    b_ts = pd.to_datetime(b["timestamp_utc"], utc=True, errors="coerce")
    c_ts = pd.to_datetime(c["timestamp_utc"], utc=True, errors="coerce")

    if b_ts.isna().any() or c_ts.isna().any():
        raise SystemExit("PARITY FAILED: invalid timestamps")

    if not np.array_equal(b_ts.to_numpy(), c_ts.to_numpy()):
        raise SystemExit("PARITY FAILED: timestamps differ")

    print("PARITY OK:", len(c), "samples, timestamps and labels")

    c = c.replace([np.inf, -np.inf], np.nan)
    features = [
        f for f in FEATURE_COLS
        if f != "seasonal_peak_prior"
        and f in c.columns and c[f].nunique(dropna=True) > 1
    ]
    c = c.dropna(subset=features + ["label"])

    train = c[c.date <= "2022-12-31"]
    val = c[(c.date >= "2023-01-01") & (c.date <= "2024-12-31")]
    test = c[(c.date >= "2025-01-01") & (c.date <= "2025-12-31")]

    for name, part in [("train", train), ("val", val), ("test", test)]:
        print(name, len(part), "positive_rate", part.label.mean())
        if len(part) < 200 or part.label.nunique() < 2:
            raise SystemExit(f"Insufficient {name} samples")

    Xtr = train[features].astype(np.float32).values
    Xva = val[features].astype(np.float32).values
    Xte = test[features].astype(np.float32).values

    model = _train_lgbm(
        Xtr, train.label.astype(int).values,
        Xva, val.label.astype(int).values,
    )

    p = model.predict(Xte, num_iteration=model.best_iteration)
    result = metrics(test.label, p)

    output.mkdir(parents=True, exist_ok=False)
    joblib.dump(model, output / "experimental_lgbm.pkl")

    report = {
        "experiment": "EXP04-C180-NOPRIOR",
        "city": args.city,
        "target": "B_180min_identical_labels",
        "features": features,
        "best_iteration": int(model.best_iteration),
        "test_2025": result,
        "experimental_only": True,
    }
    (output / "report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
