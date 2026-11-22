#!/usr/bin/env python3
"""Avaliação exploratória WU/OM contra máximas METAR."""

import json
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from cities.config import CITIES
from metar import _to_obs

BASE = Path("forecast_benchmark")


def load(source):
    path = BASE / f"{source}_raw.jsonl"
    if not path.exists():
        return []

    rows = []
    for line in path.open():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def metar_maxima():
    observations = defaultdict(dict)

    for row in load("metar"):
        city = row["city"]
        tz = ZoneInfo(CITIES[city].timezone)

        obs = _to_obs(row["raw"])
        if not obs or obs.get("temp_c") is None:
            continue

        timestamp = obs["obs_time"]
        if isinstance(timestamp, (int, float)):
            timestamp = datetime.fromtimestamp(
                timestamp, timezone.utc
            )

        local = timestamp.astimezone(tz)
        day = local.date().isoformat()

        observations[(city, day)][timestamp] = {
            "local": local,
            "temp": obs["temp_c"],
        }

    result = {}

    for key, items in observations.items():
        values = list(items.values())
        peak = max(x["temp"] for x in values)

        peak_times = [
            x["local"]
            for x in values
            if x["temp"] == peak
        ]

        result[key] = {
            "max_c": peak,
            "n_obs": len(values),
            "first": min(x["local"] for x in values),
            "last": max(x["local"] for x in values),
            "peak_first": min(peak_times),
        }

    return result


def forecasts(source):
    result = []

    for row in load(source):
        city = row["city"]
        tz = ZoneInfo(CITIES[city].timezone)
        collected = datetime.fromisoformat(
            row["collected_utc"].replace("Z", "+00:00")
        )
        local_collected = collected.astimezone(tz)

        raw = row["raw"]

        if source == "wu":
            dates = [
                value[:10]
                for value in raw.get("validTimeLocal", [])
            ]
            values = [
                None if value is None else (float(value) - 32) * 5 / 9
                for value in raw.get("calendarDayTemperatureMax", [])
            ]
        else:
            daily = raw.get("daily", {})
            dates = daily.get("time", [])
            values = daily.get("temperature_2m_max", [])

        for day, value in zip(dates, values):
            if value is None:
                continue

            target = datetime.fromisoformat(day).date()
            lead_days = (
                target - local_collected.date()
            ).days

            result.append({
                "source": source,
                "city": city,
                "day": day,
                "forecast_c": float(value),
                "collected_utc": collected,
                "lead_days": lead_days,
            })

    return result


def main():
    actuals = metar_maxima()
    predictions = forecasts("wu") + forecasts("om")

    print("Máximas METAR disponíveis:", len(actuals))
    print("Previsões disponíveis:", len(predictions))
    print()

    counts = defaultdict(int)
    prospective = defaultdict(int)

    for pred in predictions:
        key = (pred["city"], pred["day"])
        actual = actuals.get(key)

        if not actual:
            continue

        counts[pred["source"]] += 1

        # A previsão tem de anteceder a primeira
        # observação da máxima conhecida.
        if pred["collected_utc"] < actual["peak_first"].astimezone(timezone.utc):
            prospective[pred["source"]] += 1

    print("========== COBERTURA ==========")

    for source in ("wu", "om"):
        print(
            f"{source.upper():<5} "
            f"com METAR={counts[source]:>4} "
            f"antes do pico={prospective[source]:>4}"
        )

    print()
    print("========== EXEMPLOS ==========")

    shown = 0

    for pred in predictions:
        key = (pred["city"], pred["day"])
        actual = actuals.get(key)

        if not actual:
            continue

        if shown >= 12:
            break

        before_peak = (
            pred["collected_utc"]
            < actual["peak_first"].astimezone(timezone.utc)
        )

        print(
            f"{pred['city']:<17} "
            f"{pred['day']} "
            f"{pred['source'].upper():<3} "
            f"prev={pred['forecast_c']:>5.1f} "
            f"metar={actual['max_c']:>5.1f} "
            f"lead={pred['lead_days']:>2} "
            f"antes_pico={'SIM' if before_peak else 'NÃO'} "
            f"obs={actual['n_obs']}"
        )

        shown += 1


if __name__ == "__main__":
    main()
