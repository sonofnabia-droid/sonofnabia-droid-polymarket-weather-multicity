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

init(autoreset=True)

# ── Configuration ──────────────────────────────────────────────────────────────
STATION   = "EDDM"
CITY      = "munich"
TZ        = "Europe/Berlin"
UNITS     = "m"          # metric

MAX_THREADS = 4
SLEEP_SEC   = 0.4        # polite delay between requests

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
    "Accept":          "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer":         "https://www.wunderground.com/",
    "Origin":          "https://www.wunderground.com",
})

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s")
log = logging.getLogger(__name__)


# ── Fetch one day ──────────────────────────────────────────────────────────────
def fetch_day(station: str, tz: str, day: date) -> list[dict]:
    """
    Calls the Weather Underground 'history/daily' API for *station* on *day*.
    Returns a list of observation dicts (one per hourly reading).
    """
    date_str = day.strftime("%Y%m%d")

    # WU internal API used by the history page
    url = (
        f"https://api.weather.com/v1/location/{station}:9:DE"
        f"/observations/historical.json"
    )

    params = {
        "apiKey":    "e1f10a1e78da46f5b10a1e78da96f525",   # public key embedded in WU pages
        "units":     UNITS,
        "startDate": date_str,
    }

    try:
        r = session.get(url, params=params, timeout=25)
        r.raise_for_status()
        data = r.json()
        obs  = data.get("observations", [])

        rows = []
        for o in obs:
            gmt = o.get("valid_time_gmt")

            if gmt:
                dt_local   = datetime.fromtimestamp(gmt, tz=ZoneInfo(tz))
                dt_utc     = datetime.utcfromtimestamp(gmt)
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
                "sky_cover":      o.get("sky_cover"),          # CLR / FEW / SCT / BKN / OVC
                "heat_index_c":   o.get("heat_index"),
                "windchill_c":    o.get("windchill"),
            })

        time.sleep(SLEEP_SEC)
        return rows

    except requests.exceptions.HTTPError as e:
        log.warning(f"{Fore.YELLOW}{station} {day} HTTP {e.response.status_code} – skipping")
    except Exception as e:
        log.warning(f"{Fore.RED}{station} {day} error: {e}")

    return []


# ── Download full date range ───────────────────────────────────────────────────
def download_station(
    station: str,
    city:    str,
    tz:      str,
    start:   date,
    end:     date,
    progress,
    task,
) -> None:

    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]

    all_rows: list[dict] = []

    with ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
        futures = {executor.submit(fetch_day, station, tz, d): d for d in days}

        for future in as_completed(futures):
            rows = future.result()
            all_rows.extend(rows)
            progress.advance(task)

    if not all_rows:
        log.warning(f"{Fore.YELLOW}No data returned for {station}.")
        return

    df = pd.DataFrame(all_rows)

    # sort chronologically
    df["_sort"] = pd.to_datetime(df["timestamp_utc"], utc=True, errors="coerce")
    df = df.sort_values("_sort").drop(columns=["_sort"])

    csv_path = OUTPUT_DIR / f"{city}.csv"
    df.to_csv(csv_path, index=False)

    log.info(f"{Fore.GREEN}✔  Saved {csv_path}  ({len(df)} observations)")
    print(f"\n{Fore.CYAN}Columns: {list(df.columns)}")
    print(df.head(3).to_string(index=False))


# ── Entry point ────────────────────────────────────────────────────────────────
def main() -> None:
    print(f"{Fore.CYAN}╔══════════════════════════════════════╗")
    print(f"{Fore.CYAN}║  Wunderground  –  EDDM Munich        ║")
    print(f"{Fore.CYAN}║  https://www.wunderground.com/history ║")
    print(f"{Fore.CYAN}║  /daily/de/munich/EDDM               ║")
    print(f"{Fore.CYAN}╚══════════════════════════════════════╝\n")

    year_input  = input("Start year  [2001]: ").strip()
    month_input = input("Start month [1]:    ").strip()

    YEAR  = int(year_input)  if year_input  else 2001
    MONTH = int(month_input) if month_input else 1

    start = date(YEAR, MONTH, 1)
    end   = date.today() - timedelta(days=1)

    total_days = (end - start).days + 1

    print(f"\n{Fore.WHITE}Downloading {total_days} days  "
          f"({start}  →  {end})  for station {STATION}\n")

    with Progress(
        TextColumn("[bold cyan]{task.description}"),
        BarColumn(),
        TextColumn("{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
    ) as progress:

        task = progress.add_task(f"[EDDM] Munich", total=total_days)

        download_station(
            STATION, CITY, TZ,
            start, end,
            progress, task,
        )


if __name__ == "__main__":
    main()
