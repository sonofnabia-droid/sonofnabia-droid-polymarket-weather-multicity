import sys
from pathlib import Path
from collections import defaultdict

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from cities.config import get_city
from cassiopeia_backtester import resolve_params, round_half_up
from experiments.exp05.compare_hit import prepare_data
from experiments.exp04_c180_noprior import train as c


CITIES = ["munich", "shenzhen", "sao_paulo"]


def evaluate(city_name):
    city = get_city(city_name)
    params = resolve_params(city_name)
    df = prepare_data(city_name, city)

    daily_max = df.groupby("_day")["temp_c"].max().to_dict()
    ceil_slot = c._get_ceil_slot()

    results = []

    for day, group in df.groupby("_day", sort=True):
        if day.year != 2025:
            continue

        previous = {
            d: maximum
            for d, maximum in daily_max.items()
            if d < day
        }

        prev7 = c.compute_prev7(previous, day, city.name)

        if prev7 is None or not np.isfinite(prev7):
            continue

        group = group.sort_values("_utc")
        slots_by_key = {}
        day_max = float(group["temp_c"].max())

        for _, row in group.iterrows():
            h, m = ceil_slot(
                int(row["_hour"]),
                int(row["_minute"]),
            )

            if not (city.day_start <= h <= city.day_end):
                continue

            temp = float(row["temp_c"])

            slots_by_key[(h, m)] = {
                "hour": h,
                "slot30": m,
                "temp_c": temp,
            }

            slots = [
                slots_by_key[k]
                for k in sorted(slots_by_key)
            ]

            if not (
                int(params["start_hour"])
                <= h
                <= int(params["end_hour"])
            ):
                continue

            if h < 12 or len(slots) < 4:
                continue

            rmax = max(s["temp_c"] for s in slots)
            rmin = min(s["temp_c"] for s in slots)

            if rmax - rmin < float(params["min_spread"]):
                continue

            if rmax > prev7 + float(params["outlier_cap"]):
                continue

            target = float(round_half_up(rmax))

            hit = (
                target - 0.5
                <= day_max
                < target + 0.5
            )

            results.append({
                "date": day,
                "hour": h,
                "target": target,
                "day_max": day_max,
                "hit": bool(hit),
            })

            break

    return results


def summarize(rows):
    n = len(rows)
    hits = sum(r["hit"] for r in rows)
    rate = 100 * hits / n if n else float("nan")
    return n, hits, rate


def main():
    print("=" * 70)
    print("EXP05 — BASELINE SEM ML — 2025")
    print("=" * 70)

    for city in CITIES:
        rows = evaluate(city)
        n, hits, rate = summarize(rows)

        print(f"\n{city.upper()}")
        print(f"Trades: {n}")
        print(f"Hits: {hits}")
        print(f"%Hit: {rate:.2f}%")

        monthly = defaultdict(list)
        for row in rows:
            monthly[row["date"].strftime("%Y-%m")].append(row)

        print("MENSAL:")
        for month in sorted(monthly):
            mn, mh, mr = summarize(monthly[month])
            print(
                f"  {month}: "
                f"trades={mn:3d} "
                f"hits={mh:3d} "
                f"%Hit={mr:6.2f}"
            )


if __name__ == "__main__":
    main()
