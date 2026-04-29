"""
ankara_download.py
==================
Descarrega histórico horário para Ankara via Open-Meteo Archive API.

Variáveis descarregadas (um único request):
  temperature_2m        — temperatura a 2m (°C)
  dew_point_2m          — ponto de orvalho (°C)
  relative_humidity_2m  — humidade relativa (%)
  pressure_msl          — pressão ao nível do mar (hPa)
  wind_speed_10m        — velocidade do vento a 10m (km/h)
  wind_direction_10m    — direção do vento a 10m (graus)
  cloud_cover           — cobertura de nuvens (%)
  precipitation         — precipitação (mm)

Output: historic/ankara.csv

Colunas no CSV (compatível com Dallas):
  date, time, timestamp_utc, temp_c, dewpt_c, humidity_pct,
  pressure_hpa, wind_dir_deg, wind_dir_card, wind_speed_kmh,
  precip_mm, cloud_cover, wx_phrase

Instalação:
    pip install requests pandas

Uso:
    python ankara_download.py
    python ankara_download.py --start 2010-01-01
    python ankara_download.py --start 2014-01-01 --end 2024-12-31
    python ankara_download.py --output historic/ankara.csv

    # Actualizar CSV existente (acrescenta dias novos)
    python ankara_download.py --update
"""

import argparse
import requests
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path

# ── Config ─────────────────────────────────────────────
ANKARA_LAT     = 40.125   # Esenboga Airport (LTAC)
ANKARA_LON     = 32.993
TIMEZONE       = "Europe/Istanbul"

DEFAULT_START  = "2010-01-01"  # Começa igual a Dallas
DEFAULT_END    = (datetime.today() - timedelta(days=2)).strftime("%Y-%m-%d")
DEFAULT_OUTPUT = "historic/ankara.csv"

# Variáveis a descarregar (todas num único request)
HOURLY_VARS = ("temperature_2m,dew_point_2m,relative_humidity_2m,"
               "pressure_msl,wind_speed_10m,wind_direction_10m,"
               "cloud_cover,precipitation")


# ── Wind direction to cardinal ─────────────────────────
def deg_to_cardinal(d):
    """Converte graus em direção cardinal (N, NE, etc.)"""
    if pd.isna(d):
        return ""
    directions = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
                  "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
    idx = int((d + 11.25) / 22.5) % 16
    return directions[idx]


# ── Cloud cover to wx_phrase ───────────────────────────
def cloud_to_wx_phrase(cover, precip):
    """
    Converte cloud_cover + precip em wx_phrase simples.
    Não é perfeito mas dá consistência com Dallas.
    """
    if pd.notna(precip) and precip > 0:
        if precip < 0.5:
            return "Light Rain"
        elif precip < 2.5:
            return "Rain"
        else:
            return "Heavy Rain"
    if pd.isna(cover):
        return "Fair"
    if cover < 20:
        return "Fair"
    elif cover < 50:
        return "Partly Cloudy"
    elif cover < 75:
        return "Mostly Cloudy"
    else:
        return "Cloudy"


# ── Download ───────────────────────────────────────────
def download(start: str, end: str, output: str):
    print(f"── Ankara Historical Download ───────────────")
    print(f"   Coordenadas : {ANKARA_LAT}°N, {ANKARA_LON}°E")
    print(f"   Período     : {start} → {end}")
    print(f"   Variáveis   : temp, dewpt, humidity, pressure, wind, cloud, precip")
    print(f"   Output      : {output}")
    print(f"   API         : Open-Meteo Archive (gratuito, sem key)")
    print()

    url    = "https://archive-api.open-meteo.com/v1/archive"
    params = {
        "latitude":   ANKARA_LAT,
        "longitude":  ANKARA_LON,
        "start_date": start,
        "end_date":   end,
        "hourly":     HOURLY_VARS,
        "timezone":   TIMEZONE,
    }

    print("A fazer request à API...", end=" ", flush=True)
    r = requests.get(url, params=params, timeout=120)
    r.raise_for_status()
    data = r.json()
    print("✓")

    h = data["hourly"]
    df = pd.DataFrame({
        "timestamp_utc": pd.to_datetime(h["time"]),
        "temp_c":       h["temperature_2m"],
        "dewpt_c":      h["dew_point_2m"],
        "humidity_pct": h["relative_humidity_2m"],
        "pressure_hpa": h["pressure_msl"],
        "wind_speed_kmh": h["wind_speed_10m"],
        "wind_dir_deg": h["wind_direction_10m"],
        "cloud_cover":  h["cloud_cover"],
        "precip_mm":    h["precipitation"],
    })

    # Adicionar colunas date e time (formato compatível com Dallas)
    df["date"] = df["timestamp_utc"].dt.strftime("%m/%d/%Y")
    df["time"] = df["timestamp_utc"].dt.strftime("%I:%M %p")

    # Converter wind_dir_deg para cardinal
    df["wind_dir_card"] = df["wind_dir_deg"].apply(deg_to_cardinal)

    # Gerar wx_phrase simples a partir de cloud_cover e precip
    df["wx_phrase"] = df.apply(lambda row: cloud_to_wx_phrase(row["cloud_cover"], row["precip_mm"]), axis=1)

    # Remover linhas sem temperatura
    n_raw = len(df)
    df    = df.dropna(subset=["temp_c"])
    n_drop= n_raw - len(df)

    # Reordenar colunas (ordem Dallas)
    cols = ["date", "time", "timestamp_utc", "temp_c", "dewpt_c", "humidity_pct",
            "pressure_hpa", "wind_dir_deg", "wind_dir_card", "wind_speed_kmh",
            "precip_mm", "cloud_cover", "wx_phrase"]
    df = df[cols]

    # Criar diretório se não existir
    Path(output).parent.mkdir(parents=True, exist_ok=True)

    df.to_csv(output, index=False)

    print()
    print(f"── Resumo ───────────────────────────────────")
    print(f"   Linhas         : {len(df):,} horas")
    print(f"   Dias           : {df['date'].nunique():,}")
    print(f"   Primeira data  : {df.iloc[0]['date']} {df.iloc[0]['time']}")
    print(f"   Última data    : {df.iloc[-1]['date']} {df.iloc[-1]['time']}")
    print(f"   NaN temp. rem. : {n_drop}")
    print(f"   Temp.          : {df['temp_c'].min():.1f}°C → {df['temp_c'].max():.1f}°C  (média {df['temp_c'].mean():.1f}°C)")
    print(f"   Humidade       : {df['humidity_pct'].min():.0f}% → {df['humidity_pct'].max():.0f}%  (média {df['humidity_pct'].mean():.0f}%)")
    print(f"   Pressão        : {df['pressure_hpa'].min():.0f} hPa → {df['pressure_hpa'].max():.0f} hPa")
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

    existing = pd.read_csv(output, parse_dates=["timestamp_utc"])
    last_date = existing["timestamp_utc"].max().date()
    new_start = (last_date + timedelta(days=1)).strftime("%Y-%m-%d")
    new_end   = (datetime.today() - timedelta(days=2)).strftime("%Y-%m-%d")

    if new_start > new_end:
        print(f"  CSV já actualizado até {last_date} — nada a fazer.")
        return

    print(f"  Última data no CSV: {last_date}")
    print(f"  A descarregar: {new_start} → {new_end}")

    new_df = download(new_start, new_end, output="_tmp_update.csv")

    # Concatenar e remover duplicados
    combined = pd.concat([existing, new_df], ignore_index=True)
    combined  = combined.drop_duplicates(subset=["timestamp_utc"]).sort_values("timestamp_utc")
    combined.to_csv(output, index=False)

    Path("_tmp_update.csv").unlink(missing_ok=True)
    print(f"\n  ✓ CSV actualizado: {len(combined):,} horas totais → {output}")


# ── Main ───────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Download histórico horário Ankara — Open-Meteo"
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
