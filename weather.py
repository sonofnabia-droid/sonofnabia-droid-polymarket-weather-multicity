"""
weather.py
==========
Acesso a dados meteorológicos via WU (se disponível) + Open-Meteo.

Versão genérica multi-cidade — aceita CityConfig.
Para cidades sem WU (Dallas, Ankara), usa apenas Open-Meteo.

Exporta:
  make_wu_session()
  make_om_session()
  fetch_wu_day(city, day, api_key, session)
  fetch_wu_latest(city, api_key, session)
  fetch_wu_forecast_max(city, api_key, session)      # informativo/dashboard
  fetch_om_forecast_max(city, session)               # informativo/dashboard
  fetch_om_hourly_today(city, session)
  fetch_om_latest(city, session)
  bootstrap_today(city, api_key, session)       -> (series_dict, slots_list)
  bootstrap_om_today(city, session)             -> (series_dict, slots_list)
  cloud_from_series(series_today, rows_cache)
  forecasts_agree(wu_forecast, om_forecast)     # informativo/dashboard
"""

import requests
from datetime import date, datetime, timezone as _tz
from zoneinfo import ZoneInfo

from cities.config import CityConfig
from cities.config import CITIES

# URLs base
WU_BASE     = "https://api.weather.com/v1/location"
OM_FORECAST = "https://api.open-meteo.com/v1/forecast"
OM_ARCHIVE  = "https://archive-api.open-meteo.com/v1/archive"

# Estado do bootstrap (por cidade)
_bootstrap_rows_cache: dict[str, list[dict]] = {}
_bootstrap_obs_min:    dict[str, dict]       = {}


def is_plausible_temp(temp_c: float | None, city: CityConfig) -> bool:
    """Filtro conservador para glitches absurdos de temperatura."""
    if temp_c is None:
        return False
    try:
        temp = float(temp_c)
    except Exception:
        return False
    if temp != temp or temp in (float("inf"), float("-inf")):
        return False

    if city.climatology:
        historic_max = max(city.climatology.values()) + 25.0
        historic_min = min(city.climatology.values()) - 25.0
        return historic_min <= temp <= historic_max

    return -40.0 <= temp <= 60.0


def _get_city_timezone(city: CityConfig) -> ZoneInfo:
    """Retorna ZoneInfo da cidade."""
    return ZoneInfo(city.timezone)


def _get_bot_timezone(city: CityConfig) -> ZoneInfo:
    """Retorna ZoneInfo onde o bot corre (pode ser diferente da cidade)."""
    return ZoneInfo(city.bot_timezone)


def _city_date(city: CityConfig) -> date:
    """Data atual segundo o relógio da cidade."""
    return datetime.now(tz=_get_city_timezone(city)).date()


# ══════════════════════════════════════════════════════
#  SESSIONS
# ══════════════════════════════════════════════════════

def make_wu_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent":      ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"),
        "Accept":          "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer":         "https://www.wunderground.com/",
        "Origin":          "https://www.wunderground.com",
    })
    return s


def make_om_session() -> requests.Session:
    """Open-Meteo não requer API key."""
    s = requests.Session()
    s.headers.update({
        "User-Agent": "PeakBot/3.0",
        "Accept":     "application/json",
    })
    return s


# ══════════════════════════════════════════════════════
#  WUNDERGROUND (se disponível para a cidade)
# ══════════════════════════════════════════════════════

def _get_wu_url(city: CityConfig) -> str | None:
    """Retorna URL WU para a cidade, ou None se não disponível."""
    if not city.wu_history_path:
        return None
    return f"{WU_BASE}/{city.wu_history_path}/observations/historical.json"


def _wu_parse_obs(obs_list: list, city_tz: ZoneInfo) -> list[dict]:
    clds_map = {
        "CLR": 0, "SKC": 0, "FEW": 12, "SCT": 37,
        "BKN": 75, "OVC": 100, "OBS": 100, "VV": 100, "X": 100,
    }
    rows = []
    for obs in obs_list:
        temp = obs.get("temp")
        if temp is None:
            continue
        vt = obs.get("valid_time_gmt")
        if vt is None:
            continue
        try:
            dt = datetime.fromtimestamp(int(vt), tz=_tz.utc).astimezone(city_tz)
        except Exception:
            continue

        clds_raw    = str(obs.get("clds", "") or "").upper().strip()
        cloud_cover = clds_map.get(clds_raw, 50)
        temp_c      = float(temp)

        rows.append({
            "hour":        dt.hour,
            "minute":      dt.minute,
            "temp_c":      temp_c,
            "humidity":    int(round(float(obs.get("rh") or 70))),
            "cloud_cover": cloud_cover,
            "wx":          str(obs.get("wx_phrase", "") or ""),
            "source":      "WU",
            # V2 features
            "dewpoint_c":     float(obs.get("dewpt") or (temp_c - 10)),
            "pressure_hpa":   float(obs.get("pressure") or 1013),
            "wind_dir_deg":   float(obs.get("wdir") or 0),
            "wind_speed_kmh": float(obs.get("wspd")) if obs.get("wspd") is not None else 5.0,
            "wind_gust_kmh":  float(obs.get("gust")) if obs.get("gust") is not None else 8.0,
            "uv_index":       float(obs.get("uv_index") or 3),
        })
    return rows


def fetch_wu_day(city: CityConfig, day: date,
                api_key: str, session: requests.Session) -> list[dict]:
    """Busca observações WU para um dia específico da cidade."""
    wu_url = _get_wu_url(city)
    if not wu_url:
        return []

    try:
        r = session.get(wu_url, params={
            "apiKey":    api_key,
            "units":     "m",
            "startDate": day.strftime("%Y%m%d"),
        }, timeout=20)
        r.raise_for_status()
        obs = r.json().get("observations", [])
        city_tz = _get_city_timezone(city)
        rows = _wu_parse_obs(obs, city_tz) if obs else []
        if rows and city.climatology:
            clim_max = max(city.climatology.values())
            sanity_limit = clim_max + 50.0
            if any(row.get("temp_c", 0.0) > sanity_limit for row in rows):
                print(
                    f"  [WU] invalid temperature scale for {city.name}: "
                    f"max_temp={max(row.get('temp_c', 0.0) for row in rows):.1f} "
                    f"sanity_limit={sanity_limit:.1f}"
                )
                return []
        return rows
    except Exception:
        return []


def fetch_wu_latest(city: CityConfig, api_key: str,
                   session: requests.Session) -> dict | None:
    """Observação mais recente do dia de hoje via WU."""
    rows = fetch_wu_day(city, _city_date(city), api_key, session)
    if not rows:
        return None
    return max(rows, key=lambda r: r["hour"] * 60 + r["minute"])


def fetch_wu_forecast_max(city: CityConfig, api_key: str,
                          session: requests.Session) -> dict | None:
    """Previsão WU de temperatura máxima para hoje."""
    if not city.wu_history_path:
        return None

    url = "https://api.weather.com/v3/wx/forecast/daily/5day"
    try:
        r = session.get(url, params={
            "apiKey":   api_key,
            "geocode":  f"{city.latitude},{city.longitude}",
            "units":    "m",
            "language": "en-US",
            "format":   "json",
        }, timeout=15)
        r.raise_for_status()
        d = r.json()

        if not d:
            return None

        t_max = None
        t_min = None

        # Caminho 1: formato directo
        if "temperatureMax" in d and "temperatureMin" in d:
            t_max_list = d.get("temperatureMax", [None])
            t_min_list = d.get("temperatureMin", [None])
            t_max = (int(round(float(t_max_list[0])))
                     if t_max_list and t_max_list[0] is not None else None)
            t_min = (int(round(float(t_min_list[0])))
                     if t_min_list and t_min_list[0] is not None else None)

        # Caminho 2: formato nested daily
        elif "daily" in d:
            daily      = d["daily"]
            t_max_list = daily.get("temperatureMax", [None])
            t_min_list = daily.get("temperatureMin", [None])
            t_max = (int(round(float(t_max_list[0])))
                     if t_max_list and t_max_list[0] is not None else None)
            t_min = (int(round(float(t_min_list[0])))
                     if t_min_list and t_min_list[0] is not None else None)

        if t_max is None:
            return None

        return {"temp_max": t_max, "temp_min": t_min, "source": "WU"}

    except Exception:
        return None


# ══════════════════════════════════════════════════════
#  OPEN-METEO (todas as cidades)
# ══════════════════════════════════════════════════════

def fetch_om_forecast_max(city: CityConfig, session: requests.Session) -> dict | None:
    """Previsão Open-Meteo de temperatura máxima para hoje."""
    try:
        r = session.get(OM_FORECAST, params={
            "latitude":      city.latitude,
            "longitude":     city.longitude,
            "daily":         "temperature_2m_max,temperature_2m_min,cloud_cover_mean",
            "timezone":      city.timezone,
            "forecast_days": 1,
        }, timeout=15)
        r.raise_for_status()
        d     = r.json()
        daily = d.get("daily", {})

        t_max_list = daily.get("temperature_2m_max", [None])
        t_min_list = daily.get("temperature_2m_min", [None])
        cloud_list = daily.get("cloud_cover_mean",   [None])

        t_max = t_max_list[0] if t_max_list and t_max_list[0] is not None else None
        t_min = t_min_list[0] if t_min_list and t_min_list[0] is not None else None
        cloud = cloud_list[0] if cloud_list and cloud_list[0] is not None else None

        if t_max is None:
            return None

        return {
            "temp_max":    int(round(float(t_max))),
            "temp_min":    int(round(float(t_min))) if t_min is not None else None,
            "cloud_cover": int(round(float(cloud))) if cloud is not None else None,
            "source":      "Open-Meteo",
        }
    except Exception:
        return None


def fetch_om_hourly_today(city: CityConfig, session: requests.Session) -> list[dict]:
    """Previsão horária de hoje via Open-Meteo."""
    try:
        r = session.get(OM_FORECAST, params={
            "latitude":      city.latitude,
            "longitude":     city.longitude,
            "hourly":        ("temperature_2m,cloud_cover,relative_humidity_2m,"
                              "dew_point_2m,surface_pressure,wind_direction_10m,"
                              "wind_speed_10m,wind_gusts_10m,uv_index"),
            "timezone":      city.timezone,
            "forecast_days": 1,
        }, timeout=15)
        r.raise_for_status()
        d      = r.json()
        hourly = d.get("hourly", {})

        times  = hourly.get("time", [])
        temps  = hourly.get("temperature_2m", [])
        clouds = hourly.get("cloud_cover", [])
        hums   = hourly.get("relative_humidity_2m", [])
        dewpts = hourly.get("dew_point_2m", [])
        press  = hourly.get("surface_pressure", [])
        wdirs  = hourly.get("wind_direction_10m", [])
        wspds  = hourly.get("wind_speed_10m", [])
        wgsts  = hourly.get("wind_gusts_10m", [])
        uvs    = hourly.get("uv_index", [])

        city_tz = _get_city_timezone(city)
        rows = []
        for i, t_str in enumerate(times):
            dt = datetime.fromisoformat(t_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=city_tz)

            temp = temps[i] if i < len(temps) else None
            if temp is None:
                continue

            temp_c = float(temp)
            rows.append({
                "hour":           dt.hour,
                "minute":         0,
                "temp_c":         temp_c,
                "humidity":       int(round(float(hums[i])))   if i < len(hums)   and hums[i]   is not None else 70,
                "cloud_cover":    int(round(float(clouds[i]))) if i < len(clouds) and clouds[i] is not None else 50,
                "wx":             "",
                "source":         "Open-Meteo",
                "dewpoint_c":     float(dewpts[i]) if i < len(dewpts) and dewpts[i] is not None else temp_c - 10,
                "pressure_hpa":   float(press[i])  if i < len(press)  and press[i]  is not None else 1013.0,
                "wind_dir_deg":   float(wdirs[i])  if i < len(wdirs)  and wdirs[i]  is not None else 0.0,
                "wind_speed_kmh": float(wspds[i])  if i < len(wspds)  and wspds[i]  is not None else 5.0,
                "wind_gust_kmh":  float(wgsts[i])  if i < len(wgsts)  and wgsts[i]  is not None else 8.0,
                "uv_index":       float(uvs[i])    if i < len(uvs)    and uvs[i]    is not None else 3.0,
            })
        return rows
    except Exception:
        return []


def fetch_om_latest(city: CityConfig, session: requests.Session) -> dict | None:
    """Previsão horária do Open-Meteo para a hora atual da cidade."""
    rows = fetch_om_hourly_today(city, session)
    if not rows:
        return None
    h_now = datetime.now(tz=_get_city_timezone(city)).hour
    return min(rows, key=lambda r: abs(r["hour"] - h_now))


# ══════════════════════════════════════════════════════
#  BOOTSTRAP (WU ou Open-Meteo)
# ══════════════════════════════════════════════════════

def ceil_slot(hour: int, minute: int) -> tuple[int, int]:
    """
    Converte (hour, minute) para o slot 30min correto.
    Semântica: truncar para CIMA.
      minute=0-29  → slot 30 da mesma hora
      minute=30-59 → slot  0 da hora seguinte
    """
    if minute < 30:
        return (hour, 30)
    h = hour + 1
    if h == 24:
        return (23, 30)
    return (h, 0)


def bootstrap_today(city: CityConfig, api_key: str,
                   session: requests.Session) -> tuple[dict, list[dict]]:
    """
    Carrega observações de hoje (WU se disponível, senão Open-Meteo).
    Retorna (series_dict, slots_list).
    """
    global _bootstrap_rows_cache, _bootstrap_obs_min

    today = _city_date(city)
    city_name = city.name

    # Tenta WU primeiro se disponível
    if city.wu_history_path:
        print(f"  WU {city.icao} histórico {today}...", end=" ", flush=True)
        rows = fetch_wu_day(city, today, api_key, session)
        if rows:
            t_vals = [r["temp_c"] for r in rows]
            print(f"{len(rows)} obs  {min(t_vals)}°C – {max(t_vals)}°C")

            _bootstrap_rows_cache[city_name] = rows

            series:  dict[tuple, float] = {}
            obs_min: dict[tuple, tuple] = {}
            for r in rows:
                key = ceil_slot(r["hour"], r["minute"])
                if key not in series or r["temp_c"] >= series[key]:
                    series[key]  = r["temp_c"]
                    obs_min[key] = (r["hour"], r["minute"])

            _bootstrap_obs_min[city_name] = obs_min

            seen:  set[tuple]  = set()
            slots: list[dict]  = []
            for r in sorted(rows, key=lambda x: x["hour"] * 60 + x["minute"]):
                k = ceil_slot(r["hour"], r["minute"])
                if k not in seen:
                    seen.add(k)
                    slots.append({
                        "date":           today,
                        "hour":           k[0],
                        "slot30":         k[1],
                        "temp_c":         r["temp_c"],
                        "cloud_cover":    r.get("cloud_cover", 50),
                        "humidity":       r.get("humidity", 70),
                        "source":         "WU",
                        "dewpoint_c":     r.get("dewpoint_c",     r["temp_c"] - 10),
                        "pressure_hpa":   r.get("pressure_hpa",   1013),
                        "wind_dir_deg":   r.get("wind_dir_deg",   0),
                        "wind_speed_kmh": r.get("wind_speed_kmh", 5),
                        "wind_gust_kmh":  r.get("wind_gust_kmh",  8),
                        "uv_index":       r.get("uv_index",       3),
                    })
            return series, slots

    # Fallback para Open-Meteo
    return bootstrap_om_today(city, session)


def bootstrap_om_today(city: CityConfig, session: requests.Session) -> tuple[dict, list[dict]]:
    """Bootstrap com dados horários do Open-Meteo."""
    global _bootstrap_rows_cache, _bootstrap_obs_min

    today = _city_date(city)
    city_name = city.name

    print(f"  Open-Meteo hourly {today}...", end=" ", flush=True)
    rows = fetch_om_hourly_today(city, session)
    if not rows:
        print("sem dados OM")
        return {}, []

    t_vals = [r["temp_c"] for r in rows]
    print(f"{len(rows)} obs  {min(t_vals)}°C – {max(t_vals)}°C")

    current_city_hour = datetime.now(tz=_get_city_timezone(city)).hour
    rows = [r for r in rows if int(r.get("hour", 0)) <= current_city_hour]
    if not rows:
        print("sem dados OM passados")
        return {}, []

    _bootstrap_rows_cache[city_name] = rows

    series:  dict[tuple, float] = {}
    obs_min: dict[tuple, tuple] = {}
    for r in rows:
        key = ceil_slot(r["hour"], r["minute"])
        if key not in series or r["temp_c"] >= series[key]:
            series[key]  = r["temp_c"]
            obs_min[key] = (r["hour"], r["minute"])

    _bootstrap_obs_min[city_name] = obs_min

    seen:  set[tuple]  = set()
    slots: list[dict]  = []
    for r in sorted(rows, key=lambda x: x["hour"] * 60 + x["minute"]):
        k = ceil_slot(r["hour"], r["minute"])
        if k not in seen:
            seen.add(k)
            slots.append({
                "date":           today,
                "hour":           k[0],
                "slot30":         k[1],
                "temp_c":         r["temp_c"],
                "cloud_cover":    r.get("cloud_cover",    50),
                "humidity":       r.get("humidity",       70),
                "source":         "Open-Meteo",
                "dewpoint_c":     r.get("dewpoint_c",     r["temp_c"] - 10),
                "pressure_hpa":   r.get("pressure_hpa",   1013.0),
                "wind_dir_deg":   r.get("wind_dir_deg",   0.0),
                "wind_speed_kmh": r.get("wind_speed_kmh", 5.0),
                "wind_gust_kmh":  r.get("wind_gust_kmh",  8.0),
                "uv_index":       r.get("uv_index",       3.0),
            })
    return series, slots


def cloud_from_series(rows_cache: list) -> dict[int, int]:
    """Índice hora -> cobertura de nuvens, a partir do cache de rows."""
    cloud = {}
    for r in rows_cache:
        cloud[r["hour"]] = r.get("cloud_cover", 50)
    return cloud


# ══════════════════════════════════════════════════════
#  ACORDO DUAL WU + OM
# ══════════════════════════════════════════════════════

def forecasts_agree(wu_forecast: dict | None,
                   om_forecast: dict | None,
                   tolerance: int = 2) -> dict:
    """
    Verifica se WU e OM concordam na temperatura máxima prevista.
    Retorna dict com valid, wu_max, om_max, diff, consensus_max, reason.
    """
    if wu_forecast is None and om_forecast is None:
        return {
            "valid": False, "wu_max": None, "om_max": None,
            "diff": None, "consensus_max": None, "reason": "both_missing",
        }
    if wu_forecast is None:
        return {
            "valid": False, "wu_max": None,
            "om_max": om_forecast.get("temp_max"),
            "diff": None,
            "consensus_max": om_forecast.get("temp_max"),
            "reason": "wu_missing",
        }
    if om_forecast is None:
        return {
            "valid": False,
            "wu_max": wu_forecast.get("temp_max"),
            "om_max": None, "diff": None,
            "consensus_max": wu_forecast.get("temp_max"),
            "reason": "om_missing",
        }

    wu_max = wu_forecast["temp_max"]
    om_max = om_forecast["temp_max"]
    diff   = abs(wu_max - om_max)

    # Consenso estrito: só concordam se forem iguais
    is_equal = (wu_max == om_max)

    return {
        "valid":         is_equal,
        "wu_max":        wu_max,
        "om_max":        om_max,
        "diff":          diff,
        "consensus_max": wu_max if is_equal else None,
        "reason":        "agree" if is_equal else f"disagree_{diff}c",
    }
