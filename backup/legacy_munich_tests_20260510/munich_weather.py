"""
munich_weather.py
=================
Acesso a dados meteorologicos via WU EDDM + Open-Meteo.

Exporta:
  make_wu_session()
  make_om_session()
  fetch_wu_day_eddm(day, api_key, session)
  fetch_wu_latest(api_key, session)
  fetch_wu_forecast_max(api_key, session)
  fetch_om_forecast_max(session)
  fetch_om_hourly_today(session)
  fetch_om_latest(session)
  bootstrap_today(api_key, session)       -> (series_dict, slots_list)
  bootstrap_om_today(session)             -> (series_dict, slots_list)
  cloud_from_series(series_today, rows_cache)
  forecasts_agree(wu_forecast, om_forecast)

Alteracoes vs INTEGRATION original:
  Fix 1: fetch_wu_forecast_max — parentese errado em t_min causava TypeError
          quando a API retornava None ou lista vazia (ex: pedido fora de horas)
  Fix 2: bootstrap_om_today — slots agora incluem campos V2 com defaults
          (dewpoint_c, pressure_hpa, wind_dir_deg, wind_speed_kmh, wind_gust_kmh,
          uv_index) para que predict_ensemble nao fique com NaN nas features V2
  Fix 3: bootstrap_today/_rows_cache/_obs_min — substituido por variaveis de
          modulo em vez de atributos de funcao; mais robusto a reloads e testes
"""

import requests
from datetime import date, datetime, timezone as _tz

from munich_config import (
    WU_BASE, OM_FORECAST, OM_ARCHIVE,
    MUNICH_LAT_OM, MUNICH_LON_OM,
    _BERLIN, DIM, C, R,
    DAY_START, DAY_END,
    FORECAST_AGREEMENT_TOLERANCE,
    berlin_date, ceil_slot,
)

WU_EDDM_URL = f"{WU_BASE}/EDDM:9:DE/observations/historical.json"

# Fix 3: estado do bootstrap como variaveis de modulo em vez de atributos
# de funcao — mais robusto a reimports e testes unitarios
_bootstrap_rows_cache: list[dict] = []
_bootstrap_obs_min:    dict       = {}


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
    """Open-Meteo nao requer API key."""
    s = requests.Session()
    s.headers.update({
        "User-Agent": "MunichPeakBot/2.0",
        "Accept":     "application/json",
    })
    return s


# ══════════════════════════════════════════════════════
#  WUNDERGROUND — EDDM
# ══════════════════════════════════════════════════════

def _wu_parse_obs(obs_list: list) -> list[dict]:
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
            dt = datetime.fromtimestamp(int(vt), tz=_tz.utc).astimezone(_BERLIN)
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
            # V2 features — presentes na resposta WU quando disponiveis
            "dewpoint_c":     float(obs.get("dewpt") or (temp_c - 10)),
            "pressure_hpa":   float(obs.get("pressure")) if obs.get("pressure") is not None else 1013.0,
            "wind_dir_deg":   float(obs.get("wdir")) if obs.get("wdir") is not None else -1.0,  # -1 = sem direcao
            "wind_speed_kmh": float(obs.get("wspd")) if obs.get("wspd") is not None else 5.0,
            "wind_gust_kmh":  float(obs.get("gust")) if obs.get("gust") is not None else 8.0,
            "uv_index":       float(obs.get("uv_index") or 3),
        })
    return rows


def fetch_wu_day_eddm(day: date, api_key: str,
                      session: requests.Session) -> list[dict]:
    try:
        r = session.get(WU_EDDM_URL, params={
            "apiKey":    api_key,
            "units":     "m",
            "startDate": day.strftime("%Y%m%d"),
        }, timeout=20)
        r.raise_for_status()
        obs = r.json().get("observations", [])
        return _wu_parse_obs(obs) if obs else []
    except Exception:
        return []


def fetch_wu_latest(api_key: str,
                    session: requests.Session) -> dict | None:
    """Observacao mais recente do dia de hoje."""
    rows = fetch_wu_day_eddm(berlin_date(), api_key, session)
    if not rows:
        return None
    return max(rows, key=lambda r: r["hour"] * 60 + r["minute"])


def fetch_wu_forecast_max(api_key: str,
                          session: requests.Session) -> dict | None:
    """
    Temperatura maxima prevista para hoje via WU forecast 5-day.

    Fix: parentese errado em t_min causava TypeError quando a API retornava
    None ou lista vazia. O round() fechava antes do operador ternario,
    tornando None o argumento de int() em vez de ser o resultado final.
    """
    url = "https://api.weather.com/v3/wx/forecast/daily/5day"
    try:
        r = session.get(url, params={
            "apiKey":   api_key,
            "geocode":  "48.354,11.792",
            "units":    "m",
            "language": "en-US",
            "format":   "json",
        }, timeout=15)
        r.raise_for_status()
        d = r.json()

        if not d:
            print(f"  {C['yellow']}WU forecast: resposta vazia{R}")
            return None

        t_max = None
        t_min = None

        # Caminho 1: formato directo (mais comum)
        if "temperatureMax" in d and "temperatureMin" in d:
            t_max_list = d.get("temperatureMax", [None])
            t_min_list = d.get("temperatureMin", [None])
            t_max = (int(round(float(t_max_list[0])))
                     if t_max_list and t_max_list[0] is not None else None)
            # Fix: parentese correcto — int(round(...)) avalia primeiro,
            # depois o operador ternario decide se usa o resultado ou None
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
            print(f"  {C['yellow']}WU forecast: sem temp_max na resposta{R}")
            return None

        return {"temp_max": t_max, "temp_min": t_min, "source": "WU"}

    except requests.exceptions.HTTPError as e:
        print(f"  {C['yellow']}WU forecast HTTP {e.response.status_code}{R}")
        return None
    except Exception as e:
        print(f"  {C['yellow']}WU forecast error: {e}{R}")
        return None


def bootstrap_today(api_key: str,
                    session: requests.Session) -> tuple[dict, list[dict]]:
    """
    Carrega todas as observacoes WU de hoje e organiza em:
      series: dict (hour, slot30) -> temp_c  (para o grafico)
      slots:  list de dicts com todas as features (para predict_ensemble)

    Fix 3: estado guardado em _bootstrap_rows_cache / _bootstrap_obs_min
    (variaveis de modulo) em vez de atributos da funcao.
    """
    global _bootstrap_rows_cache, _bootstrap_obs_min

    today = berlin_date()
    print(f"  {DIM}WU EDDM historico {today}...{R}", end=" ", flush=True)
    rows = fetch_wu_day_eddm(today, api_key, session)
    if not rows:
        print(f"{C['red']}sem dados WU EDDM{R}")
        _bootstrap_rows_cache = []
        _bootstrap_obs_min    = {}
        return {}, []

    t_vals = [r["temp_c"] for r in rows]
    print(f"{C['green']}{len(rows)} obs  {min(t_vals)}°C – {max(t_vals)}°C{R}")

    _bootstrap_rows_cache = rows

    series:  dict[tuple, float] = {}
    obs_min: dict[tuple, tuple] = {}
    for r in rows:
        key = ceil_slot(r["hour"], r["minute"])
        if key not in series or r["temp_c"] >= series[key]:
            series[key]  = r["temp_c"]
            obs_min[key] = (r["hour"], r["minute"])

    _bootstrap_obs_min = obs_min

    seen:  set[tuple]  = set()
    slots: list[dict]  = []
    for r in sorted(rows, key=lambda x: x["hour"] * 60 + x["minute"]):
        k = ceil_slot(r["hour"], r["minute"])
        if k not in seen:
            seen.add(k)
            slots.append({
                "hour":           k[0],
                "slot30":         k[1],
                "temp_c":         r["temp_c"],
                "cloud_cover":    r.get("cloud_cover", 50),
                "humidity":       r.get("humidity", 70),
                "source":         "WU",
                # V2 features
                "dewpoint_c":     r.get("dewpoint_c",     r["temp_c"] - 10),
                "pressure_hpa":   r.get("pressure_hpa",   1013),
                "wind_dir_deg":   r.get("wind_dir_deg",   0),
                "wind_speed_kmh": r.get("wind_speed_kmh", 5),
                "wind_gust_kmh":  r.get("wind_gust_kmh",  8),
                "uv_index":       r.get("uv_index",       3),
            })
    return series, slots


def cloud_from_series(series_today: dict, rows_cache: list) -> dict[int, int]:
    """Indice hora -> cobertura de nuvens, a partir do cache de rows WU."""
    cloud = {}
    for r in rows_cache:
        cloud[r["hour"]] = r.get("cloud_cover", 50)
    return cloud


# ══════════════════════════════════════════════════════
#  OPEN-METEO
# ══════════════════════════════════════════════════════

def fetch_om_forecast_max(session: requests.Session) -> dict | None:
    """
    Previsao de temperatura maxima para hoje via Open-Meteo.
    Gratuito, sem API key.
    """
    try:
        r = session.get(OM_FORECAST, params={
            "latitude":      MUNICH_LAT_OM,
            "longitude":     MUNICH_LON_OM,
            "daily":         "temperature_2m_max,temperature_2m_min,cloud_cover_mean",
            "timezone":      "Europe/Berlin",
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
    except Exception as e:
        print(f"  {C['yellow']}OM forecast falhou: {e}{R}")
        return None


def fetch_om_hourly_today(session: requests.Session) -> list[dict]:
    """
    Previsao horaria de hoje via Open-Meteo.
    Util para comparar com observacoes WU e para bootstrap quando WU falha.
    """
    try:
        r = session.get(OM_FORECAST, params={
            "latitude":      MUNICH_LAT_OM,
            "longitude":     MUNICH_LON_OM,
            "hourly":        ("temperature_2m,cloud_cover,relative_humidity_2m,"
                              "dew_point_2m,surface_pressure,wind_direction_10m,"
                              "wind_speed_10m,wind_gusts_10m,uv_index"),
            "timezone":      "Europe/Berlin",
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

        rows = []
        for i, t_str in enumerate(times):
            dt = datetime.fromisoformat(t_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=_BERLIN)

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
                # V2 features — OM fornece todos estes campos
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


def fetch_om_latest(session: requests.Session) -> dict | None:
    """Previsao horaria do Open-Meteo para a hora actual de Munich."""
    rows = fetch_om_hourly_today(session)
    if not rows:
        return None
    h_now = datetime.now(tz=_BERLIN).hour
    return min(rows, key=lambda r: abs(r["hour"] - h_now))


def bootstrap_om_today(session: requests.Session) -> tuple[dict, list[dict]]:
    """
    Bootstrap com dados horarios do Open-Meteo.
    Usado como fallback quando WU nao responde.
    Devolve formato identico ao bootstrap_today().

    Fix 2: slots agora incluem todos os campos V2 (dewpoint_c, pressure_hpa,
    wind_dir_deg, wind_speed_kmh, wind_gust_kmh, uv_index) para que
    predict_ensemble nao receba NaN nas features V2.
    """
    today = berlin_date()
    print(f"  {DIM}Open-Meteo hourly {today}...{R}", end=" ", flush=True)
    rows = fetch_om_hourly_today(session)
    if not rows:
        print(f"{C['red']}sem dados OM{R}")
        return {}, []

    t_vals = [r["temp_c"] for r in rows]
    print(f"{C['green']}{len(rows)} obs  {min(t_vals)}°C – {max(t_vals)}°C{R}")

    series:  dict[tuple, float] = {}
    obs_min: dict[tuple, tuple] = {}
    for r in rows:
        key = ceil_slot(r["hour"], r["minute"])
        if key not in series or r["temp_c"] >= series[key]:
            series[key]  = r["temp_c"]
            obs_min[key] = (r["hour"], r["minute"])

    seen:  set[tuple] = set()
    slots: list[dict] = []
    for r in sorted(rows, key=lambda x: x["hour"] * 60 + x["minute"]):
        k = ceil_slot(r["hour"], r["minute"])
        if k not in seen:
            seen.add(k)
            slots.append({
                "hour":           k[0],
                "slot30":         k[1],
                "temp_c":         r["temp_c"],
                "cloud_cover":    r.get("cloud_cover",    50),
                "humidity":       r.get("humidity",       70),
                "source":         "Open-Meteo",
                # V2 features — agora sempre presentes (fix 2)
                "dewpoint_c":     r.get("dewpoint_c",     r["temp_c"] - 10),
                "pressure_hpa":   r.get("pressure_hpa",   1013.0),
                "wind_dir_deg":   r.get("wind_dir_deg",   0.0),
                "wind_speed_kmh": r.get("wind_speed_kmh", 5.0),
                "wind_gust_kmh":  r.get("wind_gust_kmh",  8.0),
                "uv_index":       r.get("uv_index",       3.0),
            })
    return series, slots


# ══════════════════════════════════════════════════════
#  ACORDO DUAL WU + OM
# ══════════════════════════════════════════════════════

def forecasts_agree(wu_forecast:  dict | None,
                    om_forecast:  dict | None,
                    tolerance: int = FORECAST_AGREEMENT_TOLERANCE) -> dict:
    """
    Verifica se WU e OM concordam na temperatura maxima prevista.

    Retorna dict com:
      valid:         bool — ambas concordam dentro da tolerancia
      wu_max:        int | None
      om_max:        int | None
      diff:          int | None — diferenca absoluta em graus C
      consensus_max: int | None — media das duas se concordam
      reason:        str — "agree" | "disagree_Nc" | "wu_missing" |
                           "om_missing" | "both_missing"
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

    # CONSENSO ESTRITO (2026-04): forecasts só "concordam" se forem iguais.
    # Antes era diff <= tolerance (ex: 1°C), o que arredondava 22+21 para 22
    # mesmo quando havia divergência genuina. Agora e binário: igual ou nao.
    is_equal = (wu_max == om_max)

    return {
        "valid":         is_equal,
        "wu_max":        wu_max,
        "om_max":        om_max,
        "diff":          diff,
        "consensus_max": wu_max if is_equal else None,
        "reason":        "agree" if is_equal else f"disagree_{diff}c",
    }