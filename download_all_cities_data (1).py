#!/usr/bin/env python3
"""
download_all_cities_data.py - Versão Unificada (Tuas + Script)
"""

import argparse
import time
from datetime import date, timedelta
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
import pandas as pd
from rich.progress import Progress, BarColumn, TextColumn, MofNCompleteColumn, TimeElapsedColumn, TimeRemainingColumn
from rich.console import Console

console = Console()

# Importar cidades do config.py (fonte única de verdade)
from cities.config import CITIES, CityConfig


def _get_wu_country(icao: str) -> str:
    """Mapeia ICAO para código de país da Weather Underground."""
    prefix = icao[:2].upper()
    mapping = {
        "EH": "NL", "LT": "TR", "LG": "GR", "ED": "DE", "EB": "BE",
        "LR": "RO", "LH": "HU", "EK": "DK", "EIDW": "IE", "EF": "FI",
        "VHHH": "HK", "WIII": "ID", "OP": "PK", "WM": "MY", "DN": "NG",
        "LP": "PT", "EG": "GB", "LE": "ES", "YM": "AU", "MM": "MX",
        "CY": "CA", "UU": "RU", "EN": "NO", "LFPG": "FR", "LK": "CZ",
        "LIRF": "IT", "SC": "CL", "SB": "BR", "RK": "KR", "WSSS": "SG",
        "ESSA": "SE", "YSSY": "AU", "RC": "TW", "LL": "IL", "LOWW": "AT",
        "EP": "PL", "LS": "CH", "ZB": "CN", "ZU": "CN", "ZG": "CN",
        "ZS": "CN", "ZH": "CN", "OE": "SA", "FA": "ZA", "NZ": "NZ",
        "MPTO": "PA", "VIDP": "IN", "OMDB": "AE", "HKJK": "KE",
    }
    # Tentar match completo primeiro, depois prefixo
    if icao in mapping:
        return mapping[icao]
    return mapping.get(prefix, "US")


def _city_to_tuple(city: CityConfig) -> tuple:
    """Converte CityConfig para tupla (station, country, timezone)."""
    country = _get_wu_country(city.icao)
    return (city.icao, country, city.timezone)


# Build dict dinamicamente a partir do config.py
POLYMARKET_CELSIUS_CITIES = {
    name: _city_to_tuple(cfg)
    for name, cfg in CITIES.items()
    if cfg.market_unit == "celsius"
}

OUTPUT_DIR = Path("historic_celsius")
API_KEY = "e1f10a1e78da46f5b10a1e78da96f525"

# (O resto do código é o mesmo da versão anterior - fetch_day, download_city, main)

def fetch_day(station, country, day, sleep_sec):
    date_str = day.strftime("%Y%m%d")
    url = f"https://api.weather.com/v1/location/{station}:9:{country}/observations/historical.json"
    params = {"apiKey": API_KEY, "units": "m", "startDate": date_str}

    for _ in range(3):
        try:
            r = requests.get(url, params=params, timeout=20)
            if r.status_code == 429:
                time.sleep(10)
                continue
            r.raise_for_status()
            obs = r.json().get("observations", [])
            return [{"date": day.strftime("%Y-%m-%d"), "temp_c": o.get("temp")} for o in obs]
        except:
            time.sleep(3)
    return []


def download_city(city, station, country, tz, start, end, threads, sleep_sec, skip_existing):
    csv_path = OUTPUT_DIR / f"{city}.csv"

    if skip_existing and csv_path.exists():
        try:
            df = pd.read_csv(csv_path)
            if len(df) > 100:
                console.print(f"[cyan]⏭  {city} (já existe)")
                return True, len(df)
        except:
            pass

    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    all_rows = []

    with ThreadPoolExecutor(max_workers=threads) as exe:
        futures = {exe.submit(fetch_day, station, country, d, sleep_sec): d for d in days}
        for future in as_completed(futures):
            all_rows.extend(future.result())

    if not all_rows:
        console.print(f"[red]✘  {city} - sem dados")
        return False, 0

    df = pd.DataFrame(all_rows)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(csv_path, index=False)

    console.print(f"[green]✔  {city} → {len(df):,} registos")
    return True, len(df)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--city", "-c", nargs="+")
    parser.add_argument("--skip-existing", "-s", action="store_true", default=True)
    parser.add_argument("--parallel", "-p", type=int, default=3)
    parser.add_argument("--threads", "-t", type=int, default=8)
    parser.add_argument("--sleep", type=float, default=0.35)
    parser.add_argument("--year", type=int, default=2020)
    args = parser.parse_args()

    cities = POLYMARKET_CELSIUS_CITIES
    if args.city:
        cities = {k: v for k, v in cities.items() if k in [c.lower() for c in args.city]}

    start = date(args.year, 1, 1)
    end = date.today() - timedelta(days=1)

    console.print(f"[bold cyan]Iniciando download para {len(cities)} cidades...")

    with Progress(
        TextColumn("[bold cyan]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
    ) as progress:
        task = progress.add_task("Progresso", total=len(cities))

        with ThreadPoolExecutor(max_workers=args.parallel) as executor:
            futures = []
            for city, (station, country, tz) in cities.items():
                fut = executor.submit(download_city, city, station, country, tz, start, end, 
                                     args.threads, args.sleep, args.skip_existing)
                futures.append(fut)

            for fut in as_completed(futures):
                progress.advance(task)

    console.print("[bold green]✅ Download concluído!")


if __name__ == "__main__":
    main()
