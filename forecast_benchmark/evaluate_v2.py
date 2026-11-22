#!/usr/bin/env python3
"""Benchmark V2: WU vs OM, com validação METAR e controlo temporal."""

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from statistics import mean
from zoneinfo import ZoneInfo

from cities.config import CITIES
from forecast_benchmark.evaluate import load, forecasts
from metar import _to_obs


MAX_GAP_MIN = 90
MIN_OBS = 18
MAX_PAIR_GAP_MIN = 30
MIN_SAMPLE = 20


def observations_by_day():
    groups = defaultdict(dict)

    for row in load("metar"):
        city = row["city"]
        if city not in CITIES:
            continue

        obs = _to_obs(row["raw"])
        if not obs or obs.get("temp_c") is None:
            continue

        stamp = obs["obs_time"]
        if isinstance(stamp, (int, float)):
            stamp = datetime.fromtimestamp(stamp, timezone.utc)

        local = stamp.astimezone(ZoneInfo(CITIES[city].timezone))
        key = (city, local.date().isoformat())

        groups[key][stamp] = (local, float(obs["temp_c"]))

    result = {}

    for key, values in groups.items():
        points = sorted(values.values(), key=lambda x: x[0])
        times = [p[0] for p in points]
        temps = [p[1] for p in points]

        gaps = [
            (b - a).total_seconds() / 60
            for a, b in zip(times, times[1:])
        ]

        complete = (
            len(points) >= MIN_OBS
            and times[0].hour < 2
            and times[-1].hour >= 22
            and max(gaps, default=0) <= MAX_GAP_MIN
        )

        maximum = max(temps)
        first_peak = next(
            t for t, temp in points if temp == maximum
        )

        result[key] = {
            "complete": complete,
            "maximum": maximum,
            "first_peak": first_peak.astimezone(timezone.utc),
            "n_obs": len(points),
            "max_gap_min": max(gaps, default=0),
        }

    return result


def eligible_forecasts(actuals):
    result = defaultdict(list)
    counters = defaultdict(int)

    for source in ("wu", "om"):
        for p in forecasts(source):
            if p["lead_days"] not in (0, 1, 2):
                continue

            key = (p["city"], p["day"])
            actual = actuals.get(key)

            if not actual:
                counters["without_metar"] += 1
                continue

            if not actual["complete"]:
                counters["incomplete_day"] += 1
                continue

            if p["collected_utc"] >= actual["first_peak"]:
                counters["after_peak"] += 1
                continue

            result[(key, source)].append(p)
            counters["eligible"] += 1

    for predictions in result.values():
        predictions.sort(key=lambda p: p["collected_utc"])

    return result, counters


def paired_samples(actuals, eligible):
    samples = defaultdict(list)

    for key, actual in actuals.items():
        if not actual["complete"]:
            continue

        wu = eligible.get((key, "wu"), [])
        om = eligible.get((key, "om"), [])

        # Um par por cidade/dia/horizonte.
        # Escolher o par mais próximo temporalmente.
        for lead in (0, 1, 2):
            candidates = []

            for w in wu:
                if w["lead_days"] != lead:
                    continue

                for o in om:
                    if o["lead_days"] != lead:
                        continue

                    gap = abs(
                        (w["collected_utc"] - o["collected_utc"])
                        .total_seconds()
                    ) / 60

                    if gap <= MAX_PAIR_GAP_MIN:
                        candidates.append((gap, w, o))

            if not candidates:
                continue

            # Menor distância temporal; desempate por recolha mais antiga.
            _, w, o = min(
                candidates,
                key=lambda x: (
                    x[0],
                    min(
                        x[1]["collected_utc"],
                        x[2]["collected_utc"]
                    )
                )
            )

            samples[lead].append({
                "city": key[0],
                "day": key[1],
                "actual": actual["maximum"],
                "wu": w["forecast_c"],
                "om": o["forecast_c"],
            })

    return samples


def metrics(rows, source):
    errors = [
        row[source] - row["actual"]
        for row in rows
    ]

    return {
        "mae": mean(abs(e) for e in errors),
        "bias": mean(errors),
        "within_1c": 100 * mean(abs(e) <= 1 for e in errors),
    }


def main():
    actuals = observations_by_day()
    eligible, counters = eligible_forecasts(actuals)
    samples = paired_samples(actuals, eligible)

    complete = sum(v["complete"] for v in actuals.values())

    print("========== COBERTURA METAR ==========")
    print("Dias/cidade disponíveis:", len(actuals))
    print("Dias/cidade completos:", complete)

    print("\n========== FILTROS ==========")
    for name, value in sorted(counters.items()):
        print(f"{name:<20} {value}")

    print("\n========== COMPARAÇÃO EMPARELHADA ==========")

    for lead in (0, 1, 2):
        rows = samples[lead]
        print(f"\nD+{lead}: {len(rows)} pares")

        if len(rows) < MIN_SAMPLE:
            print(
                f"Amostra insuficiente para ranking "
                f"(mínimo {MIN_SAMPLE})."
            )
            continue

        for source in ("wu", "om"):
            m = metrics(rows, source)

            print(
                f"{source.upper():<4} "
                f"MAE={m['mae']:.2f} °C  "
                f"viés={m['bias']:+.2f} °C  "
                f"±1°C={m['within_1c']:.1f}%"
            )

    print("\nNota: METAR é referência observacional provisória,")
    print("não necessariamente a fonte oficial do Polymarket.")


if __name__ == "__main__":
    main()
