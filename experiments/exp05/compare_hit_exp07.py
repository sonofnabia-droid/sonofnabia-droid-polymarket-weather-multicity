import json
import joblib
import numpy as np
import pandas as pd
from pathlib import Path
from collections import defaultdict

from cities.config import get_city
from cassiopeia_backtester import resolve_params, round_half_up
from experiments.exp04_c180_noprior import train as c
from cassiopeia_train_metar_exp03 import (
    BASE_FEATURES,
    build_time_features,
)

CITIES = ['amsterdam', 'beijing', 'buenos_aires', 'busan', 'cape_town', 'chengdu', 'chongqing', 'guangzhou', 'istanbul', 'jeddah', 'karachi', 'kuala_lumpur', 'london', 'lucknow', 'madrid', 'manila', 'milan', 'moscow', 'munich', 'panama_city', 'paris', 'qingdao', 'sao_paulo', 'seoul', 'shanghai', 'shenzhen', 'singapore', 'taipei', 'tel_aviv', 'tokyo', 'toronto', 'warsaw', 'wellington', 'wuhan']
B_ROOT = Path("experiments/exp03_calibration_full_20261113_v2")
C_ROOT = Path("experiments/exp04_c180_noprior")


def load_models(city):
    bf = B_ROOT / city
    cf = C_ROOT / city

    b_report = json.loads((bf / "selection_report.json").read_text())
    c_report = json.loads((cf / "report.json").read_text())

    b_model = joblib.load(bf / "experimental_lgbm.pkl")
    c_model = joblib.load(cf / "experimental_lgbm.pkl")

    b_features = b_report["features"]
    c_features = c_report["features"]

    assert len(b_features) == b_model.num_feature()
    assert len(c_features) == c_model.num_feature()
    assert b_features == BASE_FEATURES + [
        "temp_delta_30m",
        "temp_delta_60m",
        "temp_delta_180m",
        "observation_age_minutes",
        "observations_last_3h",
    ]

    method = b_report["selected_method"].lower()
    assert method in ("original", "isotonic", "platt"), method

    isotonic = None
    if method == "isotonic":
        isotonic = joblib.load(bf / "experimental_isotonic.pkl")

    return {
        "B": (b_model, b_features),
        "C": (c_model, c_features),
        "isotonic": isotonic,
        "platt": b_report["platt"] if method == "platt" else None,
    }


def probability(model, features, values):
    x = np.array(
        [[values.get(f, np.nan) for f in features]],
        dtype=np.float32,
    )
    return float(
        np.asarray(
            model.predict(
                x,
                num_iteration=model.best_iteration,
            )
        ).ravel()[0]
    )


def prepare_data(city_name, city):
    df = c.load_csv(
        Path(f"historic_metar/{city_name}.csv"),
        city_name=city_name,
    )

    df["_utc"] = pd.to_datetime(
        df["timestamp_utc"], utc=True, errors="coerce"
    )
    df["temp_c"] = pd.to_numeric(
        df["temp_c"], errors="coerce"
    )

    df = (
        df.dropna(subset=["_utc", "temp_c"])
        .sort_values("_utc")
        .drop_duplicates("_utc", keep="last")
        .copy()
    )

    local = df["_utc"].dt.tz_convert(city.timezone)
    df["_day"] = local.dt.date
    df["_hour"] = local.dt.hour
    df["_minute"] = local.dt.minute

    return df


def compare_city(city_name):
    city = get_city(city_name)
    params = resolve_params(city_name)
    models = load_models(city_name)
    df = prepare_data(city_name, city)

    threshold = float(params["threshold"])
    min_spread = float(params["min_spread"])
    outlier_cap = float(params["outlier_cap"])
    start_hour = int(params["start_hour"])
    end_hour = int(params["end_hour"])

    ceil_slot = c._get_ceil_slot()

    # Máximas históricas calculadas por dia local.
    # Para cada previsão, compute_prev7 recebe apenas dias anteriores.
    daily_max = df.groupby("_day")["temp_c"].max().to_dict()

    results = {"B": [], "C": []}
    candidate_counts = defaultdict(int)

    for day, group in df.groupby("_day", sort=True):
        if day.year != 2025:
            continue

        group = group.sort_values("_utc")

        previous = {
            d: maximum
            for d, maximum in daily_max.items()
            if d < day
        }
        prev7 = c.compute_prev7(previous, day, city.name)

        if prev7 is None or not np.isfinite(prev7):
            continue

        slots_by_key = {}
        history = []
        entered = {"B": False, "C": False}

        day_max = float(group["temp_c"].max())
        month = day.month
        doy = day.timetuple().tm_yday

        for _, row in group.iterrows():
            h, m = ceil_slot(
                int(row["_hour"]),
                int(row["_minute"]),
            )

            if not (city.day_start <= h <= city.day_end):
                continue

            temp = float(row["temp_c"])

            slot = {
                "hour": h,
                "slot30": m,
                "temp_c": temp,
                "cloud_cover": c.number(
                    row, "cloud_cover",
                    c.number(row, "sky_cover", 50),
                ),
                "humidity": c.number(
                    row, "humidity",
                    c.number(row, "humidity_pct", 70),
                ),
                "dewpoint_c": c.number(
                    row, "dewpoint_c",
                    c.number(row, "dewpt_c", temp - 10),
                ),
                "pressure_hpa": c.number(
                    row, "pressure_hpa", 1013
                ),
                "wind_dir_deg": c.number(
                    row, "wind_dir_deg", 0
                ),
                "wind_speed_kmh": c.number(
                    row, "wind_speed_kmh", 5
                ),
                "wind_gust_kmh": c.number(
                    row, "wind_gust_kmh", 8
                ),
                "uv_index": c.number(
                    row, "uv_index", 3
                ),
            }

            slots_by_key[(h, m)] = slot
            slots = [
                slots_by_key[k]
                for k in sorted(slots_by_key)
            ]

            history.append({
                "timestamp_utc": row["_utc"],
                "temp_c": temp,
                "humidity": slot["humidity"],
            })

            if all(entered.values()):
                break

            if not (start_hour <= h <= end_hour):
                continue

            if len(slots) < 4:
                continue

            # O treino de B e C exige hora >= 12.
            if h < 12:
                continue

            rmax = max(s["temp_c"] for s in slots)
            rmin = min(s["temp_c"] for s in slots)

            if rmax - rmin < min_spread:
                continue

            if rmax > prev7 + outlier_cap:
                continue

            baseline = c.build_features(
                slots,
                {**slot, "prev_7d_avg_max": prev7},
                month,
                doy,
            )

            timed = build_time_features(
                history, row["_utc"]
            )

            b_values = {
                **{
                    f: baseline.get(f, np.nan)
                    for f in BASE_FEATURES
                },
                **timed,
            }
            c_values = baseline

            candidate_counts[city_name] += 1

            for name, values in [
                ("B", b_values),
                ("C", c_values),
            ]:
                if entered[name]:
                    continue

                model, features = models[name]
                p = probability(model, features, values)

                if name == "B" and models["platt"] is not None:
                    from scipy.special import expit, logit

                    a = float(models["platt"]["a"])
                    b = float(models["platt"]["b"])

                    p = float(
                        expit(a * logit(np.clip(p, 1e-12, 1 - 1e-12)) + b)
                    )

                if name == "B" and models["isotonic"] is not None:
                    p = float(
                        np.asarray(
                            models["isotonic"].predict([p])
                        ).ravel()[0]
                    )

                if not np.isfinite(p):
                    continue

                if p >= threshold:
                    continue

                target = float(round_half_up(rmax))
                low = target - 0.5
                high = target + 0.5

                hit = bool(low <= day_max < high)

                results[name].append({
                    "date": day,
                    "hour": h,
                    "minute": m,
                    "p": p,
                    "rmax": rmax,
                    "day_max": day_max,
                    "target": target,
                    "hit": hit,
                })

                entered[name] = True

    return results, params, candidate_counts[city_name]


def summary(rows):
    n = len(rows)
    hits = sum(r["hit"] for r in rows)
    return n, hits, (100 * hits / n if n else float("nan"))


def print_monthly(name, rows):
    months = defaultdict(list)
    for row in rows:
        months[row["date"].strftime("%Y-%m")].append(row)

    print(f"\n  {name} — MENSAL")
    for month in sorted(months):
        n, hits, rate = summary(months[month])
        print(
            f"    {month}: "
            f"trades={n:3d} "
            f"hits={hits:3d} "
            f"hit_rate={rate:6.2f}%"
        )


def main():
    print("=" * 72)
    print("EXP05 — B VS C — HIT RATE 2025")
    print("=" * 72)

    for city in CITIES:
        results, params, candidates = compare_city(city)

        b = results["B"]
        c_rows = results["C"]

        nb, hb, rb = summary(b)
        nc, hc, rc = summary(c_rows)

        print(f"\n{'=' * 72}")
        print(city.upper())
        print("=" * 72)
        print(
            "Parâmetros:",
            {
                k: params[k]
                for k in [
                    "threshold",
                    "min_spread",
                    "start_hour",
                    "end_hour",
                    "outlier_cap",
                ]
            },
        )
        print("Candidatos avaliados:", candidates)

        print(f"B: trades={nb}, hits={hb}, %Hit={rb:.2f}")
        print(f"C: trades={nc}, hits={hc}, %Hit={rc:.2f}")
        print(f"Diferença C-B: {rc-rb:+.2f} pontos percentuais")

        by_b = {r["date"]: r for r in b}
        by_c = {r["date"]: r for r in c_rows}
        common = sorted(set(by_b) & set(by_c))

        both_hit = sum(
            by_b[d]["hit"] and by_c[d]["hit"]
            for d in common
        )
        only_b_hit = sum(
            by_b[d]["hit"] and not by_c[d]["hit"]
            for d in common
        )
        only_c_hit = sum(
            by_c[d]["hit"] and not by_b[d]["hit"]
            for d in common
        )
        neither_hit = sum(
            not by_b[d]["hit"] and not by_c[d]["hit"]
            for d in common
        )

        print("\nDIAS COMUNS:")
        print("  Dias:", len(common))
        print("  Ambos acertaram:", both_hit)
        print("  Só B acertou:", only_b_hit)
        print("  Só C acertou:", only_c_hit)
        print("  Ambos falharam:", neither_hit)
        print("  Dias exclusivos B:", len(by_b) - len(common))
        print("  Dias exclusivos C:", len(by_c) - len(common))

        print_monthly("B", b)
        print_monthly("C", c_rows)


if __name__ == "__main__":
    main()
