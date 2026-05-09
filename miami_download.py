"""
miami_download.py
==================
Descarrega histórico horário para Miami (KMIA) via Wunderground API
Tal e qual o munich_downloader.py + argparse flexível (--start 01-01-2026)
"""

import time
import logging
from datetime import date, timedelta, datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from zoneinfo import ZoneInfo
import requests
import pandas as pd
from rich.progress import Progress, BarColumn, TextColumn, TimeElapsedColumn, TimeRemainingColumn
from colorama import init, Fore
import argparse

init(autoreset=True)

# ── Configuration ──────────────────────────────────────────────────────────────
STATION = "KMIA"
CITY = "miami"
TZ = "America/New_York"
UNITS = "m"
MAX_THREADS = 4
SLEEP_SEC = 0.4
OUTPUT_DIR = Path("historic")
OUTPUT_DIR.mkdir(exist_ok=True)

# ── HTTP session ───────────────────────────────────────────────────────────────
session = requests.Session()
session.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.wunderground.com/",
    "Origin": "https://www.wunderground.com",
})

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)

# ── Fetch one day ──────────────────────────────────────────────────────────────
def fetch_day(station: str, tz: str, day: date) -> list[dict]:
    date_str = day.strftime("%Y%m%d")
    url = f"https://api.weather.com/v1/location/{station}:9:US/observations/historical.json"
    params = {
        "apiKey": "e1f10a1e78da46f5b10a1e78da96f525",
        "units": UNITS,
        "startDate": date_str,
    }
    try:
        r = session.get(url, params=params, timeout=25)
        r.raise_for_status()
        data = r.json()
        obs = data.get("observations", [])
        rows = []
        for o in obs:
            gmt = o.get("valid_time_gmt")
            if gmt:
                dt_local = datetime.fromtimestamp(gmt, tz=ZoneInfo(tz))
                dt_utc = datetime.utcfromtimestamp(gmt)
                date_local = dt_local.strftime("%d/%m/%Y")
                time_local = dt_local.strftime("%H:%M")
            else:
                date_local = time_local = ""
                dt_utc = None
            rows.append({
                "date": date_local,
                "time_local": time_local,
                "timestamp_utc": dt_utc,
                "temp_c": o.get("temp"),
                "dewpt_c": o.get("dewpt"),
                "humidity_pct": o.get("rh"),
                "pressure_hpa": o.get("pressure"),
                "wind_dir_deg": o.get("wdir"),
                "wind_dir_card": o.get("wdir_cardinal"),
                "wind_speed_kmh": o.get("wspd"),
                "wind_gust_kmh": o.get("gust"),
                "precip_mm": o.get("precip_hrly"),
                "condition": o.get("wx_phrase"),
                "uv_index": o.get("uv_index"),
                "visibility_km": o.get("vis"),
                "sky_cover": o.get("sky_cover"),
                "heat_index_c": o.get("heat_index"),
                "windchill_c": o.get("windchill"),
            })
        time.sleep(SLEEP_SEC)
        return rows
    except Exception as e:
        log.warning(f"{Fore.YELLOW}{station} {day} error: {e}")
    return []

# ── Download range ─────────────────────────────────────────────────────────────
def download_station(station: str, city: str, tz: str, start: date, end: date, progress=None, task=None):
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    all_rows: list[dict] = []
    with ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
        futures = {executor.submit(fetch_day, station, tz, d): d for d in days}
        for future in as_completed(futures):
            rows = future.result()
            all_rows.extend(rows)
            if progress and task is not None:
                progress.advance(task)
    if not all_rows:
        log.warning(f"{Fore.YELLOW}No data returned for {station}.")
        return None
    df = pd.DataFrame(all_rows)
    df["_sort"] = pd.to_datetime(df["timestamp_utc"], utc=True, errors="coerce")
    df = df.sort_values("_sort").drop(columns=["_sort"])
    csv_path = OUTPUT_DIR / f"{city}.csv"
    df.to_csv(csv_path, index=False)
    log.info(f"{Fore.GREEN}✔ Saved {csv_path} ({len(df)} observations)")
    return df

# ── Update mode ────────────────────────────────────────────────────────────────
def update_mode():
    csv_path = OUTPUT_DIR / "miami.csv"
    if not csv_path.exists():
        print(f"{Fore.YELLOW}Ficheiro não existe → download completo...")
        main_download(date(2010, 1, 1), date.today() - timedelta(days=1))
        return

    df = pd.read_csv(csv_path, parse_dates=["timestamp_utc"])
    last_date = df["timestamp_utc"].max().date()
    new_start = last_date + timedelta(days=1)
    today = date.today() - timedelta(days=1)

    if new_start > today:
        print(f"{Fore.GREEN}CSV já actualizado até {last_date} — nada a fazer.")
        return

    print(f"{Fore.CYAN}Última data: {last_date} → descarregar {new_start} até {today}")
    new_df = download_station(STATION, CITY, TZ, new_start, today)
    if new_df is not None:
        combined = pd.concat([df, new_df], ignore_index=True)
        combined = combined.drop_duplicates(subset=["timestamp_utc"]).sort_values("timestamp_utc")
        combined.to_csv(csv_path, index=False)
        print(f"{Fore.GREEN}✓ Actualizado: {len(combined)} linhas")

# ── Main download ──────────────────────────────────────────────────────────────
def main_download(start_date: date, end_date: date):
    print(f"{Fore.CYAN}╔══════════════════════════════════════╗")
    print(f"{Fore.CYAN}║ Wunderground – KMIA Miami (MIA) ║")
    print(f"{Fore.CYAN}╚══════════════════════════════════════╝\n")
    total_days = (end_date - start_date).days + 1
    print(f"{Fore.WHITE}A descarregar {total_days} dias ({start_date} → {end_date})\n")

    with Progress(
        TextColumn("[bold cyan]{task.description}"),
        BarColumn(),
        TextColumn("{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
    ) as progress:
        task = progress.add_task(f"[KMIA] Miami", total=total_days)
        download_station(STATION, CITY, TZ, start_date, end_date, progress, task)

# ── CLI ────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download histórico Wunderground Miami")
    parser.add_argument("--start", default="2010-01-01",
                        help="Data de início. Aceita: 2026-01-01 ou 01-01-2026")
    parser.add_argument("--end", default=None,
                        help="Data de fim (opcional)")
    parser.add_argument("--update", action="store_true",
                        help="Acrescentar apenas dias novos")
    args = parser.parse_args()

    try:
        if len(args.start.split("-")[0]) == 2:
            start_date = datetime.strptime(args.start, "%d-%m-%Y").date()
        else:
            start_date = datetime.strptime(args.start, "%Y-%m-%d").date()
    except ValueError:
        print(f"{Fore.RED}Erro: Formato inválido! Usa --start 01-01-2026 ou --start 2026-01-01")
        exit(1)

    if args.update:
        update_mode()
    else:
        end_date = datetime.strptime(args.end, "%Y-%m-%d").date() if args.end else (date.today() - timedelta(days=1))
        main_download(start_date, end_date)