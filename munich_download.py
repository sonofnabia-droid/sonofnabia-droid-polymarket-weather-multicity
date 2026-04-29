"""
munich_download.py
==================
Descarrega histórico horário para Munich via Open-Meteo Archive API.

Variáveis descarregadas (um único request):
  temperature_2m   — temperatura a 2m (°C)
  cloud_cover      — cobertura de nuvens (%)        ← novo
  relative_humidity_2m — humidade relativa (%)      ← novo

Output: munich_historical.csv

Colunas no CSV:
  datetime, temp_c, cloud_cover, humidity,
  date, hour, month, doy, year

Instalação:
    pip install requests pandas

Uso:
    python munich_download.py
    python munich_download.py --start 2010-01-01
    python munich_download.py --start 2014-01-01 --end 2024-12-31
    python munich_download.py --output meu_ficheiro.csv

    # Actualizar CSV existente (acrescenta dias novos)
    python munich_download.py --update
"""

import argparse
import requests
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path

# ── Config ─────────────────────────────────────────────
MUNICH_LAT     = 48.1374
MUNICH_LON     = 11.5755
TIMEZONE       = "Europe/Berlin"

DEFAULT_START  = "2014-01-01"
DEFAULT_END    = (datetime.today() - timedelta(days=2)).strftime("%Y-%m-%d")
DEFAULT_OUTPUT = "munich_historical.csv"

# Variáveis a descarregar (todas num único request)
HOURLY_VARS = "temperature_2m,cloud_cover,relative_humidity_2m"


# ── Download ───────────────────────────────────────────
def download(start: str, end: str, output: str):
    print(f"── Munich Historical Download ───────────────")
    print(f"   Período  : {start} → {end}")
    print(f"   Variáveis: temperatura, cloud cover, humidade")
    print(f"   Output   : {output}")
    print(f"   API      : Open-Meteo Archive (gratuito, sem key)")
    print()

    url    = "https://archive-api.open-meteo.com/v1/archive"
    params = {
        "latitude":   MUNICH_LAT,
        "longitude":  MUNICH_LON,
        "start_date": start,
        "end_date":   end,
        "hourly":     HOURLY_VARS,
        "timezone":   TIMEZONE,
    }

    print("A fazer request...", end=" ", flush=True)
    r = requests.get(url, params=params, timeout=60)
    r.raise_for_status()
    data = r.json()
    print("✓")

    h = data["hourly"]
    df = pd.DataFrame({
        "datetime":    pd.to_datetime(h["time"]),
        "temp_c":      h["temperature_2m"],
        "cloud_cover": h.get("cloud_cover"),
        "humidity":    h.get("relative_humidity_2m"),
    })

    # Colunas auxiliares
    df["date"]  = df["datetime"].dt.date
    df["hour"]  = df["datetime"].dt.hour
    df["month"] = df["datetime"].dt.month
    df["doy"]   = df["datetime"].dt.dayofyear
    df["year"]  = df["datetime"].dt.year

    # Remover linhas sem temperatura
    n_raw = len(df)
    df    = df.dropna(subset=["temp_c"])
    n_drop= n_raw - len(df)

    # Preencher NaN em cloud_cover e humidity com interpolação linear
    df["cloud_cover"] = df["cloud_cover"].interpolate(limit=3).fillna(50.0)
    df["humidity"]    = df["humidity"].interpolate(limit=3).fillna(70.0)

    df.to_csv(output, index=False)

    print()
    print(f"── Resumo ───────────────────────────────────")
    print(f"   Linhas         : {len(df):,} horas")
    print(f"   Dias           : {df['date'].nunique():,}")
    print(f"   Anos           : {df['year'].min()} → {df['year'].max()}")
    print(f"   NaN temp. rem. : {n_drop}")
    print(f"   Temp.          : {df['temp_c'].min():.1f}°C → {df['temp_c'].max():.1f}°C  (média {df['temp_c'].mean():.1f}°C)")
    print(f"   Cloud cover    : {df['cloud_cover'].min():.0f}% → {df['cloud_cover'].max():.0f}%  (média {df['cloud_cover'].mean():.0f}%)")
    print(f"   Humidade       : {df['humidity'].min():.0f}% → {df['humidity'].max():.0f}%  (média {df['humidity'].mean():.0f}%)")
    print(f"   Ficheiro       : {Path(output).resolve()}")
    print(f"────────────────────────────────────────────")
    print(f"✅ Concluído.")
    return df


# ── Update (acrescenta só dias novos) ──────────────────
def update(output: str):
    """
    Lê o CSV existente, verifica a última data,
    e descarrega apenas os dias em falta até hoje.
    """
    path = Path(output)
    if not path.exists():
        print(f"  {output} não existe — a fazer download completo...")
        download(DEFAULT_START, DEFAULT_END, output)
        return

    existing = pd.read_csv(output, parse_dates=["datetime"])
    last_date = existing["datetime"].max().date()
    new_start = (last_date + timedelta(days=1)).strftime("%Y-%m-%d")
    new_end   = (datetime.today() - timedelta(days=2)).strftime("%Y-%m-%d")

    if new_start > new_end:
        print(f"  CSV já actualizado até {last_date} — nada a fazer.")
        return

    print(f"  Última data no CSV: {last_date}")
    print(f"  A descarregar: {new_start} → {new_end}")

    new_df = download(new_start, new_end, output="_tmp_update.csv")

    # Verificar se CSV existente tem as novas colunas
    for col, fill in [("cloud_cover", 50.0), ("humidity", 70.0)]:
        if col not in existing.columns:
            existing[col] = fill

    combined = pd.concat([existing, new_df], ignore_index=True)
    combined  = combined.drop_duplicates(subset=["datetime"]).sort_values("datetime")
    combined.to_csv(output, index=False)

    Path("_tmp_update.csv").unlink(missing_ok=True)
    print(f"\n  ✓ CSV actualizado: {len(combined):,} horas totais → {output}")


# ── Main ───────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Download histórico horário Munich — Open-Meteo"
    )
    parser.add_argument("--start",  default=DEFAULT_START,
                        help=f"Data início (default: {DEFAULT_START})")
    parser.add_argument("--end",    default=DEFAULT_END,
                        help=f"Data fim (default: hoje-2d)")
    parser.add_argument("--output", default=DEFAULT_OUTPUT,
                        help=f"Ficheiro CSV (default: {DEFAULT_OUTPUT})")
    parser.add_argument("--update", action="store_true",
                        help="Acrescentar só dias novos ao CSV existente")
    args = parser.parse_args()

    if args.update:
        update(args.output)
    else:
        download(start=args.start, end=args.end, output=args.output)
