#!/usr/bin/env python3
"""
download_all_cities_data.py
===========================
Downloader multi-cidade inspirado no munich_downloader.py.

Baixa dados horários completos da Weather Underground com ~25 features
para todas as cidades definidas em cities/config.py.

Uso:
    python download_all_cities_data.py --year 2010
    python download_all_cities_data.py --city amsterdam london --year 2015
    python download_all_cities_data.py --parallel 3 --threads 4 --sleep 0.4 --year 2020
"""

import argparse
import time
import logging
from datetime import date, timedelta, datetime, timezone
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from zoneinfo import ZoneInfo

import requests
import pandas as pd
from rich.progress import Progress, BarColumn, TextColumn, MofNCompleteColumn, TimeElapsedColumn, TimeRemainingColumn
from rich.console import Console

# Importar cidades do config.py
from cities.config import CITIES, CityConfig


console = Console()
log = logging.getLogger(__name__)

OUTPUT_DIR = Path("historic_celsius")
OUTPUT_DIR.mkdir(exist_ok=True)

# ── HTTP session ───────────────────────────────────────────────────────────────
session = requests.Session()
session.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept":          "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer":         "https://www.wunderground.com/",
    "Origin":          "https://www.wunderground.com",
})


# ── Country code mapping (wu_history_path prefix → ISO country code) ───────────
PATH_PREFIX_TO_ISO = {
    "nl": "NL",
    "fi": "FI",
    "tr": "TR",
    "gb": "GB",
    "es": "ES",
    "it": "IT",
    "ru": "RU",
    "de": "DE",
    "fr": "FR",
    "pl": "PL",
    "cn": "CN",
    "kr": "KR",
    "pk": "PK",
    "my": "MY",
    "in": "IN",
    "ph": "PH",
    "tw": "TW",
    "il": "IL",
    "jp": "JP",
    "sa": "SA",
    "za": "ZA",
    "ar": "AR",
    "mx": "MX",
    "pa": "PA",
    "br": "BR",
    "ca": "CA",
    "nz": "NZ",
    "sg": "SG",
}


# ── Alternative station codes (ICAO → fallback ICAOs) ─────────────────────────
# Algumas cidades mudaram de aeroporto, ou a WU usa código diferente
ALT_STATIONS = {
    "LTFM": ["LTBA"],   # Istanbul: novo (LTFM) → antigo (LTBA - Atatürk)
}


def _get_wu_country(icao: str) -> str:
    """Mapeia ICAO para código de país da Weather Underground (fallback)."""
    prefix = icao[:2].upper()
    mapping = {
        "EH": "NL", "LT": "TR", "LG": "GR", "ED": "DE", "EB": "BE",
        "LR": "RO", "LH": "HU", "EK": "DK", "EF": "FI",
        "OP": "PK", "WM": "MY", "LP": "PT", "EG": "GB", "LE": "ES",
        "MM": "MX", "CY": "CA", "UU": "RU", "EN": "NO",
        "RK": "KR", "RC": "TW", "LL": "IL", "EP": "PL", "LS": "CH",
        "ZB": "CN", "ZU": "CN", "ZG": "CN", "ZS": "CN", "ZH": "CN",
        "OE": "SA", "FA": "ZA", "NZ": "NZ", "SB": "BR",
        "RP": "PH",
        "MP": "PA",
        "RJ": "JP",
    }
    icao_specific = {
        "EIDW": "IE", "VHHH": "HK", "WIII": "ID", "DN": "NG",
        "LFPG": "FR", "LIRF": "IT", "WSSS": "SG", "ESSA": "SE",
        "YSSY": "AU", "LOWW": "AT", "YM": "AU", "MPTO": "PA",
        "VIDP": "IN", "OMDB": "AE", "HKJK": "KE",
    }
    if icao in icao_specific:
        return icao_specific[icao]
    return mapping.get(prefix, "US")


def _city_to_tuple(city: CityConfig) -> tuple:
    """
    Converte CityConfig para tupla (station, country, timezone).
    
    Prioridade para extrair country code do wu_history_path,
    pois contém o país correto configurado manualmente.
    """
    # Tentar extrair do wu_history_path (mais confiável)
    if city.wu_history_path:
        path_prefix = city.wu_history_path.split("/")[0].lower()
        country = PATH_PREFIX_TO_ISO.get(path_prefix)
        if country:
            return (city.icao, country, city.timezone)

    # Fallback para mapeamento por ICAO
    country = _get_wu_country(city.icao)
    return (city.icao, country, city.timezone)


# Build dict dinamicamente a partir do config.py
POLYMARKET_CELSIUS_CITIES = {
    name: _city_to_tuple(cfg)
    for name, cfg in CITIES.items()
    if cfg.market_unit == "celsius"
}


# ── Alternative country codes to try on 400 errors ────────────────────────────
def _get_alt_countries(station: str, primary_country: str) -> list[str]:
    """Retorna lista de country codes alternativos para tentar."""
    prefix = station[:2].upper()
    
    alt_by_prefix = {
        "LF": ["FR"], "EG": ["GB"], "ED": ["DE"], "LE": ["ES"],
        "LI": ["IT"], "EB": ["BE"], "EH": ["NL"], "LK": ["CZ"],
        "EP": ["PL"], "LS": ["CH"], "EF": ["FI"], "EN": ["NO"],
        "EK": ["DK"], "LP": ["PT"], "LR": ["RO"], "LH": ["HU"],
        "LT": ["TR"], "LG": ["GR"], "ZB": ["CN"], "ZU": ["CN"],
        "ZG": ["CN"], "ZS": ["CN"], "ZH": ["CN"], "WM": ["MY"],
        "RK": ["KR"], "RC": ["TW"], "LL": ["IL"], "RJ": ["JP"],
        "OP": ["PK"], "SA": ["AR"], "SB": ["BR"], "MM": ["MX"],
        "CY": ["CA"], "NZ": ["NZ"], "FA": ["ZA"], "OE": ["SA"],
        "RP": ["PH"],
        "MP": ["PA"],
    }
    
    alt_by_icao = {
        "EIDW": ["IE"], "VHHH": ["HK"], "WIII": ["ID"], "WSSS": ["SG"],
        "ESSA": ["SE"], "YSSY": ["AU"], "LOWW": ["AT"], "MPTO": ["PA"],
        "VIDP": ["IN"], "OMDB": ["AE"], "HKJK": ["KE"],
    }
    
    alts = []
    
    if prefix in alt_by_prefix:
        for c in alt_by_prefix[prefix]:
            if c != primary_country:
                alts.append(c)
    
    if station in alt_by_icao:
        for c in alt_by_icao[station]:
            if c != primary_country and c not in alts:
                alts.append(c)
    
    return alts


# ── Fetch one day ──────────────────────────────────────────────────────────────
def fetch_day(station: str, country: str, tz: str, day: date, sleep_sec: float) -> list[dict]:
    """
    Calls the Weather Underground API for *station* on *day*.
    Returns a list of observation dicts (one per hourly reading) with ~25 features.

    Tenta country codes alternativos e estações alternativas em caso de erro.
    """
    date_str = day.strftime("%Y%m%d")

    # Estações alternativas para tentar (ex: LTFM → LTBA)
    stations_to_try = [station] + ALT_STATIONS.get(station, [])

    # Country codes para tentar
    country_attempts = [country] + _get_alt_countries(station, country)

    for try_station in stations_to_try:
        for attempt_country in country_attempts:
            url = (
                f"https://api.weather.com/v1/location/{try_station}:9:{attempt_country}"
                f"/observations/historical.json"
            )

            params = {
                "apiKey": "e1f10a1e78da46f5b10a1e78da96f525",
                "units": "m",
                "startDate": date_str,
            }

            try:
                r = session.get(url, params=params, timeout=25)

                if r.status_code == 400:
                    continue

                if r.status_code == 403:
                    time.sleep(sleep_sec * 5)
                    continue

                r.raise_for_status()
                data = r.json()
                obs = data.get("observations", [])

                if obs:
                    return _parse_observations(obs, tz, sleep_sec)

            except requests.exceptions.HTTPError:
                continue
            except requests.exceptions.Timeout:
                continue
            except Exception:
                continue

    return []


def _parse_observations(obs: list, tz: str, sleep_sec: float) -> list[dict]:
    """Parse observations da WU para o formato do CSV."""
    rows = []
    for o in obs:
        gmt = o.get("valid_time_gmt")

        if gmt:
            dt_local = datetime.fromtimestamp(gmt, tz=ZoneInfo(tz))
            dt_utc = datetime.fromtimestamp(gmt, tz=timezone.utc)  # ← FIX: sem deprecation
            date_local = dt_local.strftime("%d/%m/%Y")
            time_local = dt_local.strftime("%H:%M")
        else:
            date_local = time_local = ""
            dt_utc = None

        rows.append({
            "date":           date_local,
            "time_local":     time_local,
            "timestamp_utc":  dt_utc,
            "temp_c":         o.get("temp"),
            "dewpt_c":        o.get("dewpt"),
            "humidity_pct":   o.get("rh"),
            "pressure_hpa":   o.get("pressure"),
            "wind_dir_deg":   o.get("wdir"),
            "wind_dir_card":  o.get("wdir_cardinal"),
            "wind_speed_kmh": o.get("wspd"),
            "wind_gust_kmh":  o.get("gust"),
            "precip_mm":      o.get("precip_hrly"),
            "condition":      o.get("wx_phrase"),
            "uv_index":       o.get("uv_index"),
            "visibility_km":  o.get("vis"),
            "sky_cover":      o.get("sky_cover"),
            "heat_index_c":   o.get("heat_index"),
            "windchill_c":    o.get("windchill"),
        })

    time.sleep(sleep_sec)
    return rows


# ── Download one city ──────────────────────────────────────────────────────────
def download_city(
    city: str,
    station: str,
    country: str,
    tz: str,
    start: date,
    end: date,
    threads: int,
    sleep_sec: float,
    skip_existing: bool,
    city_progress=None,
) -> tuple[bool, int]:
    """Download completo para uma cidade com barra de progresso individual."""

    csv_path = OUTPUT_DIR / f"{city}.csv"

    if skip_existing and csv_path.exists():
        try:
            df = pd.read_csv(csv_path)
            if len(df) > 100:
                console.print(f"[cyan]⏭  {city} (já existe — {len(df):,} registos)[/cyan]")
                return True, len(df)
        except Exception:
            pass

    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    total_days = len(days)
    all_rows: list[dict] = []

    if city_progress:
        city_task = city_progress.add_task(
            f"[yellow]⏳ {city}",
            total=total_days,
            completed=0,
        )

    with ThreadPoolExecutor(max_workers=threads) as executor:
        futures = {executor.submit(fetch_day, station, country, tz, d, sleep_sec): d for d in days}

        for future in as_completed(futures):
            rows = future.result()
            all_rows.extend(rows)
            if city_progress:
                city_progress.advance(city_task)

    if city_progress:
        city_progress.remove_task(city_task)

    if not all_rows:
        # Mostrar estações alternativas que foram tentadas
        alts = ALT_STATIONS.get(station, [])
        if alts:
            console.print(f"[red]✘  {city} — sem dados (tentou: {station}, {', '.join(alts)})[/red]")
        else:
            console.print(f"[red]✘  {city} — sem dados[/red]")
        return False, 0

    df = pd.DataFrame(all_rows)

    # Sort cronológico
    df["_sort"] = pd.to_datetime(df["timestamp_utc"], utc=True, errors="coerce")
    df = df.sort_values("_sort").drop(columns=["_sort"])

    # Salvar
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(csv_path, index=False)

    # Mostrar qual estação foi usada (se houve fallback)
    alts = ALT_STATIONS.get(station, [])
    station_info = f"{station}" if not alts else f"{station}/{'/'.join(alts)}"

    console.print(
        f"[green]✔  {city} → {len(df):,} registos "
        f"({total_days:,} dias, {len(df.columns)} colunas) [{station_info}] → {csv_path}[/green]"
    )
    return True, len(df)


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Downloader multi-cidade Weather Underground",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Exemplos:
  python download_all_cities_data.py --year 2010
  python download_all_cities_data.py --city amsterdam london --year 2015
  python download_all_cities_data.py --parallel 3 --threads 4 --sleep 0.4 --year 2020
  python download_all_cities_data.py --city istanbul manila panama_city --year 2020
""",
    )
    parser.add_argument("--city", "-c", nargs="+", help="Cidades específicas")
    parser.add_argument("--skip-existing", "-s", action="store_true", default=True,
                        help="Pula cidades com CSV existente")
    parser.add_argument("--no-skip", dest="skip_existing", action="store_false",
                        help="Força re-download mesmo se CSV existir")
    parser.add_argument("--parallel", "-p", type=int, default=3,
                        help="Cidades em paralelo (default: 3)")
    parser.add_argument("--threads", "-t", type=int, default=4,
                        help="Threads por cidade (default: 4)")
    parser.add_argument("--sleep", type=float, default=0.4,
                        help="Sleep entre requests em segundos (default: 0.4)")
    parser.add_argument("--year", type=int, default=2020,
                        help="Ano de início (default: 2020)")
    args = parser.parse_args()

    cities = POLYMARKET_CELSIUS_CITIES
    if args.city:
        cities = {k: v for k, v in cities.items() if k in [c.lower() for c in args.city]}

    start = date(args.year, 1, 1)
    end = date.today() - timedelta(days=1)

    console.print()
    console.print(f"[dim]Output dir: {OUTPUT_DIR.absolute()}[/dim]")
    console.print()

    # Mostrar mapeamento das cidades selecionadas
    console.print("[dim]Mapeamento station→country:[/dim]")
    for city_name, (station, country, tz) in cities.items():
        alts = ALT_STATIONS.get(station, [])
        alt_info = f" (fallback: {', '.join(alts)})" if alts else ""
        console.print(f"[dim]  {city_name}: {station} → {country}{alt_info}[/dim]")
    console.print()

    console.print("=" * 70, style="cyan")
    console.print(" [bold cyan]DOWNLOAD ALL — Weather Underground[/bold cyan]", justify="center")
    console.print("=" * 70, style="cyan")
    console.print(f"  Cidades:    {len(cities)}")
    console.print(f"  Período:    {start} → {end}")
    console.print(f"  Paralelo:   {args.parallel} cidades")
    console.print(f"  Threads:    {args.threads} por cidade")
    console.print(f"  Sleep:      {args.sleep}s")
    console.print()

    with Progress(
        TextColumn("[bold cyan]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
        console=console,
    ) as global_progress:
        global_task = global_progress.add_task("[bold cyan]Progresso Global", total=len(cities))

        with Progress(
            TextColumn("  {task.description}"),
            BarColumn(bar_width=30),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TextColumn("({task.completed}/{task.total})"),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
            console=console,
        ) as city_progress:

            with ThreadPoolExecutor(max_workers=args.parallel) as executor:
                futures = []
                for city, (station, country, tz) in cities.items():
                    fut = executor.submit(
                        download_city,
                        city, station, country, tz, start, end,
                        args.threads, args.sleep, args.skip_existing, city_progress
                    )
                    futures.append((fut, city))

                for fut, city_name in futures:
                    try:
                        fut.result()
                    except Exception as e:
                        console.print(f"[red]✘  {city_name} — erro: {e}[/red]")
                    global_progress.advance(global_task)

    console.print()
    console.print(f"[dim]Output dir: {OUTPUT_DIR.absolute()}[/dim]")
    console.print()
    console.print("=" * 70, style="cyan")
    console.print(" [bold green]✅ Download concluído![/bold green]", justify="center")
    console.print("=" * 70, style="cyan")
    console.print()


if __name__ == "__main__":
    main()
