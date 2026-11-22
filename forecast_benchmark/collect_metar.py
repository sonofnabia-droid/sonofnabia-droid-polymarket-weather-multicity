#!/usr/bin/env python3
"""Recolha independente de observações METAR para benchmark WU/OM."""

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

from cities.config import CITIES

OUTPUT = Path("forecast_benchmark/metar_raw.jsonl")
URL = "https://aviationweather.gov/api/data/metar"

def main():
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    existing = set()

    if OUTPUT.exists():
        for line in OUTPUT.read_text().splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                existing.add((row["icao"], row["obs_time"]))
            except (ValueError, KeyError):
                continue

    session = requests.Session()
    collected_at = datetime.now(timezone.utc).isoformat()

    added = 0
    duplicates = 0
    errors = 0

    with OUTPUT.open("a") as out:
        for name, city in sorted(CITIES.items()):
            try:
                response = session.get(
                    URL,
                    params={
                        "ids": city.icao,
                        "format": "json",
                        "hours": 26,
                    },
                    timeout=20,
                )
                response.raise_for_status()
                reports = response.json()

                if not isinstance(reports, list):
                    raise ValueError("Resposta não é uma lista")

                city_added = 0

                for report in reports:
                    obs_time = report.get("obsTime")
                    if obs_time is None:
                        continue

                    obs_time = int(obs_time)
                    key = (city.icao, obs_time)

                    if key in existing:
                        duplicates += 1
                        continue

                    row = {
                        "collected_utc": collected_at,
                        "city": name,
                        "icao": city.icao,
                        "obs_time": obs_time,
                        "raw": report,
                    }

                    out.write(json.dumps(row, ensure_ascii=False) + "\n")
                    existing.add(key)
                    added += 1
                    city_added += 1

                print(
                    f"{name:<20} {city.icao:<6} "
                    f"recebidos={len(reports):>3} "
                    f"novos={city_added:>3}"
                )

            except Exception as exc:
                errors += 1
                print(f"{name:<20} ERRO: {exc}")

            time.sleep(0.25)

    print("\n========== RESUMO ==========")
    print("Cidades configuradas:", len(CITIES))
    print("Novas observações:", added)
    print("Duplicados ignorados:", duplicates)
    print("Cidades com erro:", errors)
    print("Ficheiro:", OUTPUT)

if __name__ == "__main__":
    main()
