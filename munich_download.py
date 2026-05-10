import time
import logging
import argparse
from datetime import date, timedelta, datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from zoneinfo import ZoneInfo

import requests
import pandas as pd
from rich.progress import Progress, BarColumn, TextColumn, TimeElapsedColumn, TimeRemainingColumn
from colorama import init, Fore

init(autoreset=True)

# ── Configuration ──────────────────────────────────────────────────────────────
STATION = "EDDM"
CITY = "munich"
TZ = "Europe/Berlin"
COUNTRY = "DE"
UNITS = "m"

MAX_THREADS = 4
SLEEP_SEC = 0.4

OUTPUT_DIR = Path("historic")
OUTPUT_DIR.mkdir(exist_ok=True)

CSV_PATH = OUTPUT_DIR / f"{CITY}.csv"

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

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s")
log = logging.getLogger(__name__)


# ── Date parser ────────────────────────────────────────────────────────────────
def parse_date(value: str) -> date:
    """
    Aceita:
      2008-01-01
      01-01-2008
    """
    try:
        if len(value.split("-")[0]) == 2:
            return datetime.strptime(value, "%d-%m-%Y").date()
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise SystemExit(
            f"{Fore.RED}Erro: formato inválido '{value}'. Usa 2008-01-01 ou 01-01-2008."
        )


# ── Fetch one day ──────────────────────────────────────────────────────────────
def fetch_day(station: str, tz: str, day: date) -> list[dict]:
    date_str = day.strftime("%Y%m%d")

    url = (
        f"https://api.weather.com/v1/location/{station}:9:{COUNTRY}"
        f"/observations/historical.json"
    )

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
                date_local = ""
                time_local = ""
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

    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response is not None else "?"
        log.warning(f"{Fore.YELLOW}{station} {day} HTTP {status} – skipping")
    except Exception as e:
        log.warning(f"{Fore.RED}{station} {day} error: {e}")

    return []


# ── Download date range ────────────────────────────────────────────────────────
def download_station(
    station: str,
    city: str,
    tz: str,
    start: date,
    end: date,
    progress=None,
    task=None,
) -> pd.DataFrame | None:

    if end < start:
        print(f"{Fore.YELLOW}Nada a descarregar: end < start.")
        return None

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


# ── Full download ──────────────────────────────────────────────────────────────
def main_download(start_date: date, end_date: date) -> None:
    print(f"{Fore.CYAN}╔══════════════════════════════════════╗")
    print(f"{Fore.CYAN}║ Wunderground – EDDM Munich           ║")
    print(f"{Fore.CYAN}║ /daily/de/munich/EDDM                ║")
    print(f"{Fore.CYAN}╚══════════════════════════════════════╝\n")

    total_days = (end_date - start_date).days + 1

    print(
        f"{Fore.WHITE}A descarregar {total_days} dias "
        f"({start_date} → {end_date}) para {STATION}\n"
    )

    with Progress(
        TextColumn("[bold cyan]{task.description}"),
        BarColumn(),
        TextColumn("{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
    ) as progress:

        task = progress.add_task(f"[{STATION}] Munich", total=total_days)

        df = download_station(
            STATION,
            CITY,
            TZ,
            start_date,
            end_date,
            progress,
            task,
        )

    if df is not None:
        print(f"\n{Fore.CYAN}── Resumo ───────────────────────────────────")
        print(f"{Fore.WHITE}Linhas       : {len(df):,}")
        print(f"{Fore.WHITE}Ficheiro     : {CSV_PATH.resolve()}")
        print(f"{Fore.GREEN}✅ Concluído.")


# ── Update mode ────────────────────────────────────────────────────────────────
def update_mode() -> None:
    if not CSV_PATH.exists():
        print(f"{Fore.YELLOW}Ficheiro não existe → download completo...")
        main_download(date(2008, 1, 1), date.today() - timedelta(days=1))
        return

    df = pd.read_csv(CSV_PATH, parse_dates=["timestamp_utc"])

    if df.empty or "timestamp_utc" not in df.columns:
        print(f"{Fore.YELLOW}CSV vazio ou inválido → download completo...")
        main_download(date(2008, 1, 1), date.today() - timedelta(days=1))
        return

    last_date = pd.to_datetime(df["timestamp_utc"], errors="coerce").max().date()
    new_start = last_date + timedelta(days=1)
    today = date.today() - timedelta(days=1)

    if new_start > today:
        print(f"{Fore.GREEN}CSV já actualizado até {last_date} — nada a fazer.")
        return

    print(f"{Fore.CYAN}Última data: {last_date} → descarregar {new_start} até {today}")

    total_days = (today - new_start).days + 1

    with Progress(
        TextColumn("[bold cyan]{task.description}"),
        BarColumn(),
        TextColumn("{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
    ) as progress:

        task = progress.add_task(f"[{STATION}] Munich update", total=total_days)

        new_df = download_station(
            STATION,
            CITY,
            TZ,
            new_start,
            today,
            progress,
            task,
        )

    if new_df is not None:
        combined = pd.concat([df, new_df], ignore_index=True)
        combined["timestamp_utc"] = pd.to_datetime(
            combined["timestamp_utc"],
            utc=True,
            errors="coerce",
        )
        combined = combined.drop_duplicates(subset=["timestamp_utc"])
        combined = combined.sort_values("timestamp_utc")
        combined.to_csv(CSV_PATH, index=False)

        print(f"{Fore.GREEN}✓ Actualizado: {len(combined):,} linhas em {CSV_PATH}")


# ── CLI ────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download histórico Wunderground Munich")

    parser.add_argument(
        "--start",
        default="2008-01-01",
        help="Data de início. Aceita: 2008-01-01 ou 01-01-2008",
    )

    parser.add_argument(
        "--end",
        default=None,
        help="Data de fim. Aceita: 2026-05-08 ou 08-05-2026. Opcional.",
    )

    parser.add_argument(
        "--update",
        action="store_true",
        help="Acrescentar apenas dias novos ao CSV existente.",
    )

    args = parser.parse_args()

    if args.update:
        update_mode()
    else:
        start_date = parse_date(args.start)
        end_date = parse_date(args.end) if args.end else date.today() - timedelta(days=1)
        main_download(start_date, end_date)