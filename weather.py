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

# ══════════════════════════════════════════════════════
#  HELPERS DE CONVERSÃO
# ══════════════════════════════════════════════════════

def _maybe_convert_mph_to_kmh(value: float | None, threshold: float = 150.0) -> float | None:
    """
    Converte mph → km/h se o valor parece estar em mph.

    A WU API aceita units="m" (metric), mas algumas estações PWS
    ignoram o parâmetro e devolvem imperial. Um valor > threshold
    em km/h é meteorologicamente raro (só em furacões); se > 150,
    assume-se mph e converte-se (1 mph = 1.60934 km/h).

    Args:
        value: valor bruto da API
        threshold: limiar acima do qual assume mph (default 150 km/h)
    Returns:
        Valor em km/h, ou None se input é None
    """
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if v > threshold:
        return round(v * 1.60934, 1)
    return v


# URLs base
# ENDPOINTS VÁLIDOS (confirmados 2026-06):
#   /v3/wx/observations/current — observação actual (free key)
#   /v3/wx/forecast/daily/5day  — forecast 5 dias (free key)
#   /v2/pws/history/all         — histórico PWS por stationId (free key, units=m)
#   /v2/pws/observations/current — observação actual PWS (free key, units=m)
#
# ENDPOINTS DESCONTINUADOS (não usados — dão 401 Akamai):
#   /v1/location/.../observations/historical.json
WU_BASE_OBS_v3  = "https://api.weather.com/v3/wx/observations/current"
WU_BASE_FC_v3   = "https://api.weather.com/v3/wx/forecast/daily/5day"
WU_BASE_PWS_HIST = "https://api.weather.com/v2/pws/history/all"
WU_BASE_PWS_OBS  = "https://api.weather.com/v2/pws/observations/current"
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
    """Retorna URL WU para a cidade, ou None se não disponível.
    AGORA USA ENDPOINT V3 (o v1/location está descontinuado para free keys).
    """
    if not city.wu_history_path:
        return None
    # Não usamos mais URL construido — fetch_wu_day usa WU_BASE_PWS_HIST directamente
    return WU_BASE_PWS_HIST


def _wu_parse_obs(obs_list: list, city_tz: ZoneInfo) -> list[dict]:
    """Parser para o formato v1/location (descontinuado).
    Mantido por compatibilidade, mas o novo _v2_pws_parse é o que é usado.
    """
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


def _v3_current_parse(data: dict, city_tz: ZoneInfo) -> dict | None:
    """Parser para endpoint /v3/wx/observations/current.
    Retorna 1 observação (a actual) ou None.
    """
    if not data or not isinstance(data, dict):
        return None
    temp = data.get("temperature")
    if temp is None:
        return None
    try:
        temp_c = float(temp)
    except (TypeError, ValueError):
        return None

    # Timestamp: usar expirationTimeUtc ou obsTimeLocal
    ts = data.get("validTimeUtc") or data.get("expirationTimeUtc")
    if ts:
        try:
            dt = datetime.fromtimestamp(int(ts), tz=_tz.utc).astimezone(city_tz)
            hour = dt.hour
            minute = dt.minute
        except Exception:
            # FIX Bug #11: fallback usa minuto real (não 0) para colocar
            # observação no slot correcto. Antes colocava no início da hora
            # (slot errado), causando inconsistência com latest_obs/peak_temp.
            now = datetime.now(tz=city_tz)
            hour = now.hour
            minute = now.minute
    else:
        now = datetime.now(tz=city_tz)
        hour = now.hour
        minute = now.minute

    cloud_cover = int(data.get("cloudCover") or 50)

    # Helper para converter com segurança — alguns campos vêm como string noutro formato
    # (ex: uvDescription = "Low"/"Moderate"/"High" em vez de número)
    def _safe_float(value, default):
        if value is None:
            return default
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    # UV: preferir uvIndex (numérico), fallback uvDescription (texto)
    uv_index = _safe_float(data.get("uvIndex"), None)
    if uv_index is None:
        # Mapear uvDescription para valor aproximado
        uv_desc = str(data.get("uvDescription") or "").lower()
        uv_map = {
            "low":         2,
            "moderate":    4,
            "high":        7,
            "very high":  10,
            "extreme":    11,
        }
        uv_index = uv_map.get(uv_desc, 3)

    return {
        "hour":        hour,
        "minute":      minute,
        "temp_c":      temp_c,
        "humidity":    int(round(_safe_float(data.get("relativeHumidity"), 70))),
        "cloud_cover": cloud_cover,
        "wx":          str(data.get("cloudCoverPhrase", "") or ""),
        "source":      "WU-v3",
        "dewpoint_c":     _safe_float(data.get("temperatureDewPoint"), temp_c - 10),
        "pressure_hpa":   _safe_float(data.get("pressureMeanSeaLevel"),
                                       _safe_float(data.get("pressureAltimeter"), 1013)),
        "wind_dir_deg":   _safe_float(data.get("windDirection"), 0),
        "wind_speed_kmh": _safe_float(data.get("windSpeed"), 5.0),
        "wind_gust_kmh":  _safe_float(data.get("windGust"), 8.0),
        "uv_index":       uv_index,
    }


def _v2_pws_history_parse(observations: list, city_tz: ZoneInfo) -> list[dict]:
    """Parser para endpoint /v2/pws/history/all.
    Retorna lista de observações (uma por hora).
    """
    if not observations or not isinstance(observations, list):
        return []

    rows = []
    for obs in observations:
        # Timestamp: obsTimeUtc (formato real: "2026-06-17T22:04:52Z")
        ts = obs.get("obsTimeUtc")
        if ts:
            try:
                # Formato real do WU PWS: "2026-06-17T22:04:52Z"
                # Python 3.11+ fromisoformat suporta Z; para <3.11 substituir
                ts_clean = ts.replace("Z", "+00:00") if ts.endswith("Z") else ts
                dt = datetime.fromisoformat(ts_clean).astimezone(city_tz)
            except Exception:
                try:
                    # Fallback: formato com milisegundos e offset "-0000"
                    dt = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S.%f%z").astimezone(city_tz)
                except Exception:
                    continue
        else:
            continue

        # Temperatura: metric.tempAvg ou imperial.tempAvg
        metric = obs.get("metric", {}) or {}
        temp_c = metric.get("tempAvg") or metric.get("temp")
        if temp_c is None:
            # Fallback imperial → converter
            imperial = obs.get("imperial", {}) or {}
            temp_f = imperial.get("tempAvg") or imperial.get("temp")
            if temp_f is None:
                continue
            try:
                temp_c = (float(temp_f) - 32) * 5 / 9
            except (TypeError, ValueError):
                continue
        try:
            temp_c = float(temp_c)
        except (TypeError, ValueError):
            continue

        # Helpers para distinguir 0 de None (0 é valor válido para wind/uv/pressure)
        def _f(d, key, default):
            """Float — retorna default se key em falta ou None, mas respeita 0."""
            v = d.get(key) if d else None
            return float(v) if v is not None else default

        rows.append({
            "hour":        dt.hour,
            "minute":      dt.minute,
            "temp_c":      temp_c,
            "humidity":    int(round(_f(obs, "humidityAvg", _f(metric, "humidityAvg", 70)))),
            "cloud_cover": 50,  # PWS não costuma ter cloud_cover directo
            "wx":          "",
            "source":      "WU-PWS",
            "dewpoint_c":     _f(metric, "dewptAvg", temp_c - 10),
            "pressure_hpa":   _f(metric, "pressureMax", _f(metric, "pressureMin", 1013.0)),
            "wind_dir_deg":   _f(obs, "winddirAvg", 0.0),
            # FIX Bug 5.2: validar/converter wind speed que pode vir em mph
            "wind_speed_kmh": _maybe_convert_mph_to_kmh(_f(metric, "windspeedAvg", 0.0)),
            "wind_gust_kmh":  _maybe_convert_mph_to_kmh(_f(metric, "windgustAvg", _f(metric, "windgustHigh", 0.0))),
            "uv_index":       _f(obs, "uvHigh", 0.0),  # 0 = noite ou nublado (válido!)
        })
    return rows


def fetch_wu_day(city: CityConfig, day: date,
                api_key: str, session: requests.Session) -> list[dict]:
    """Busca observações WU para um dia específico usando /v2/pws/history/all.

    Usa o endpoint PWS (Personal Weather Station) — o endpoint v1/location está
    descontinuado para free keys (dá 401 Akamai).
    Precisa de city.pws_station_id configurado em cities/config.py.
    """
    if not city.wu_history_path:
        return []
    if not api_key:
        print(f"  [WU] {city.name}: WU_API_KEY vazia — não consigo buscar dados")
        return []

    # station_id: tenta city.pws_station_id, senão fallback para icao
    station_id = getattr(city, 'pws_station_id', None) or city.icao
    city_tz = _get_city_timezone(city)

    try:
        r = session.get(WU_BASE_PWS_HIST, params={
            "apiKey":     api_key,
            "stationId":  station_id,
            "format":     "json",
            "units":      "m",  # IMPORTANTE: "m" (metric), NÃO "metric"
            "date":       day.strftime("%Y%m%d"),
        }, timeout=20)
    except requests.exceptions.Timeout:
        print(f"  [WU] {city.name}: TIMEOUT (>20s) a pedir histórico PWS station={station_id}")
        return []
    except requests.exceptions.ConnectionError as e:
        print(f"  [WU] {city.name}: ERRO DE CONEXAO: {e}")
        return []
    except Exception as e:
        print(f"  [WU] {city.name}: EXCEPCAO no request: {type(e).__name__}: {e}")
        return []

    # Verificar HTTP status
    if r.status_code != 200:
        status_msgs = {
            401: "API key invalida ou expirada",
            403: "API key sem permissões / IP bloqueado",
            404: "Station PWS não encontrada — verifica pws_station_id",
            429: "RATE LIMIT excedido — espera antes de tentar",
            500: "Erro interno do servidor WU",
        }
        msg = status_msgs.get(r.status_code, "erro HTTP")
        body_preview = r.text[:300] if r.text else "(sem body)"
        print(f"  [WU] {city.name}: HTTP {r.status_code} — {msg}")
        print(f"  [WU] station={station_id} date={day.isoformat()}")
        print(f"  [WU] Body: {body_preview}")
        return []

    # Parse JSON
    try:
        data = r.json()
    except Exception as e:
        print(f"  [WU] {city.name}: JSON invalido: {e}")
        print(f"  [WU] Body (primeiros 500 chars): {r.text[:500]}")
        return []

    # Formato esperado: {"observations": [...], "metadata": {...}}
    observations = data.get("observations", []) if isinstance(data, dict) else []
    if not observations:
        # Pode ser erro reportado pelo WU
        if isinstance(data, dict) and data.get("errors"):
            print(f"  [WU] {city.name}: API errors: {data['errors']}")
        else:
            print(f"  [WU] {city.name}: 200 OK mas sem 'observations' no response")
            print(f"  [WU] Top keys: {list(data.keys())[:10] if isinstance(data, dict) else type(data)}")
            print(f"  [WU] Body (primeiros 500 chars): {r.text[:500]}")
        return []

    rows = _v2_pws_history_parse(observations, city_tz)
    if not rows:
        print(f"  [WU] {city.name}: 200 OK com {len(observations)} observations mas parser não extraiu nenhuma")
        return []

    # Sanity check de temperatura (margem justa para detetar Fahrenheit vs Celsius)
    # FIX Bug #4: check bidireccional — antes só bloqueava temperaturas ALTAS,
    # falhando em detectar conversões erradas que produzem temperaturas MUITO
    # BAIXAS (ex: Fahrenheit interpretado como Celsius em dias frios → pico
    # pode ficar 20°C abaixo do real).
    if city.climatology:
        clim_max = max(city.climatology.values())
        clim_min = min(city.climatology.values())
        sanity_high = clim_max + 15.0
        sanity_low  = clim_min - 25.0
        temps = [row.get("temp_c", 0.0) for row in rows]
        if any(t > sanity_high for t in temps):
            print(
                f"  [WU] {city.name}: invalid high temperature "
                f"max_temp={max(temps):.1f} "
                f"sanity_high={sanity_high:.1f}"
            )
            return []
        if any(t < sanity_low for t in temps):
            print(
                f"  [WU] {city.name}: invalid low temperature "
                f"min_temp={min(temps):.1f} "
                f"sanity_low={sanity_low:.1f}"
            )
            return []
    return rows


def fetch_wu_latest(city: CityConfig, api_key: str,
                   session: requests.Session) -> dict | None:
    """Observação mais recente via /v3/wx/observations/current.

    Usa geocode (lat,lon) — não precisa de stationId PWS.
    Este endpoint é confirmado funcionar com free keys (passa do Akamai).
    """
    if not city.wu_history_path:
        return None
    if not api_key:
        print(f"  [WU] {city.name}: WU_API_KEY vazia")
        return None

    city_tz = _get_city_timezone(city)
    geocode = f"{city.latitude},{city.longitude}"

    try:
        r = session.get(WU_BASE_OBS_v3, params={
            "apiKey":   api_key,
            "geocode":  geocode,
            "units":    "m",
            "language": "en-US",
            "format":   "json",
        }, timeout=15)
    except requests.exceptions.Timeout:
        print(f"  [WU] {city.name}: TIMEOUT (>15s) a pedir current obs")
        return None
    except requests.exceptions.ConnectionError as e:
        print(f"  [WU] {city.name}: ERRO DE CONEXAO: {e}")
        return None
    except Exception as e:
        print(f"  [WU] {city.name}: EXCEPCAO: {type(e).__name__}: {e}")
        return None

    if r.status_code != 200:
        status_msgs = {
            400: "parâmetros em falta (verificar language/geocode)",
            401: "API key invalida",
            403: "API key sem permissões",
            404: "geocode não encontrado",
            429: "RATE LIMIT excedido",
        }
        msg = status_msgs.get(r.status_code, "erro HTTP")
        body_preview = r.text[:300] if r.text else ""
        print(f"  [WU] {city.name}: HTTP {r.status_code} — {msg}")
        if body_preview:
            print(f"  [WU] Body: {body_preview}")
        return None

    try:
        data = r.json()
    except Exception as e:
        print(f"  [WU] {city.name}: JSON invalido: {e}")
        return None

    obs = _v3_current_parse(data, city_tz)
    if obs is None:
        print(f"  [WU] {city.name}: 200 OK mas parser não extraiu observação")
        print(f"  [WU] Top keys: {list(data.keys())[:10] if isinstance(data, dict) else type(data)}")
    return obs


def fetch_wu_forecast_max(city: CityConfig, api_key: str,
                          session: requests.Session) -> dict | None:
    """Previsão WU de temperatura máxima para hoje via /v3/wx/forecast/daily/5day.

    Endpoint confirmado funcionar com free keys.
    """
    if not city.wu_history_path:
        return None
    if not api_key:
        return None

    try:
        r = session.get(WU_BASE_FC_v3, params={
            "apiKey":   api_key,
            "geocode":  f"{city.latitude},{city.longitude}",
            "units":    "m",
            "language": "en-US",
            "format":   "json",
        }, timeout=15)
    except Exception as e:
        print(f"  [WU] {city.name}: forecast fetch failed: {type(e).__name__}: {e}")
        return None

    if r.status_code != 200:
        print(f"  [WU] {city.name}: forecast HTTP {r.status_code}")
        return None

    try:
        d = r.json()
    except Exception as e:
        print(f"  [WU] {city.name}: forecast JSON invalido: {e}")
        return None

    if not d or not isinstance(d, dict):
        return None

    # Formato v3: {calendarDayTemperatureMax: [...], calendarDayTemperatureMin: [...]}
    t_max_list = d.get("calendarDayTemperatureMax") or d.get("temperatureMax") or []
    t_min_list = d.get("calendarDayTemperatureMin") or d.get("temperatureMin") or []

    if not t_max_list:
        return None

    t_max = t_max_list[0] if t_max_list[0] is not None else None
    t_min = t_min_list[0] if t_min_list and t_min_list[0] is not None else None

    if t_max is None:
        return None

    return {
        "temp_max": int(round(float(t_max))),
        "temp_min": int(round(float(t_min))) if t_min is not None else None,
        "source":   "WU-v3",
    }


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


def fetch_om_forecast_current_hour(city: CityConfig, session: requests.Session) -> dict | None:
    """
    Previsão horária do Open-Meteo para a hora actual da cidade.

    NOTA: isto retorna a PREVISÃO (forecast) para a hora mais próxima,
    não uma observação real. Para dados observados, usar bootstrap_om_today
    ou o endpoint archive do Open-Meteo.
    """
    rows = fetch_om_hourly_today(city, session)
    if not rows:
        return None
    h_now = datetime.now(tz=_get_city_timezone(city)).hour
    return min(rows, key=lambda r: abs(r["hour"] - h_now))


# Alias para compatibilidade com código existente
fetch_om_latest = fetch_om_forecast_current_hour


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
    # FIX Bug #7: validar hour/minute para evitar keys invalidas como (24,30)
    # ou (12,60) que corrompiam dicionarios de slots e causavam crash.
    h = max(0, min(23, int(hour)))
    m = max(0, min(59, int(minute)))
    if m < 30:
        return (h, 30)
    nh = h + 1
    if nh == 24:
        return (23, 30)
    return (nh, 0)


def floor_slot(hour: int, minute: int) -> tuple[int, int]:
    """
    Converte (hour, minute) para o último slot 30min COMPLETO.
    Semântica: truncar para BAIXO (slot já terminado).
      minute=0-29  → slot 0 da mesma hora
      minute=30-59 → slot 30 da mesma hora
    """
    # FIX Bug #7: validar hour/minute (ver ceil_slot acima).
    h = max(0, min(23, int(hour)))
    m = max(0, min(59, int(minute)))
    if m < 30:
        return (h, 0)
    return (h, 30)


def bootstrap_today(city: CityConfig, api_key: str,
                   session: requests.Session, verbose: bool = True) -> tuple[dict, list[dict]]:
    """
    Carrega observações de hoje via WU.
    SEM FALLBACK PARA OPEN-METEO — se WU falha, retorna ({}, []) e o caller
    trata o erro. Os prints do fetch_wu_day já vão mostrar a causa real.

    Retorna (series_dict, slots_list).
    """
    global _bootstrap_rows_cache, _bootstrap_obs_min

    today = _city_date(city)
    city_name = city.name

    # Tenta WU (única fonte)
    if city.wu_history_path:
        if verbose:
            print(f"  WU {city.icao} histórico {today}...", end=" ", flush=True)
        rows = fetch_wu_day(city, today, api_key, session)
        if rows:
            t_vals = [r["temp_c"] for r in rows]
            if verbose:
                print(f"{len(rows)} obs  {min(t_vals)}°C – {max(t_vals)}°C")

            _bootstrap_rows_cache[city_name] = rows

            series:  dict[tuple, float] = {}
            obs_min: dict[tuple, tuple] = {}
            for r in rows:
                # FIX Bug #3: usar floor_slot (slot completo anterior) em vez de
                # ceil_slot — o caller filtra slots passados via floor_slot(limit),
                # por isso precisamos que o mapeamento seja consistente. Com
                # ceil_slot, observações do slot actual (em curso) eram colocadas
                # nesse slot e depois excluídas pelo caller, levando a perda de
                # dados e slots_so_far incompletos.
                key = floor_slot(r["hour"], r["minute"])
                if key not in series or r["temp_c"] >= series[key]:
                    series[key]  = r["temp_c"]
                    obs_min[key] = (r["hour"], r["minute"])

            _bootstrap_obs_min[city_name] = obs_min

            seen:  set[tuple]  = set()
            slots: list[dict]  = []
            for r in sorted(rows, key=lambda x: x["hour"] * 60 + x["minute"]):
                k = floor_slot(r["hour"], r["minute"])
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
        else:
            # WU falhou — fetch_wu_day já imprimiu a causa real
            if verbose:
                print(f"FALHOU (ver mensagens [WU] acima)")
            return {}, []

    # Cidade sem WU history path (Dallas, Ankara, etc.) — não suportada em modo WU-only
    if verbose:
        print(f"  {city_name}: sem WU history path configurado — sem dados")
    return {}, []


def bootstrap_om_today(city: CityConfig, session: requests.Session, verbose: bool = True) -> tuple[dict, list[dict]]:
    """Bootstrap com dados horários do Open-Meteo."""
    global _bootstrap_rows_cache, _bootstrap_obs_min

    today = _city_date(city)
    city_name = city.name

    if verbose:
        print(f"  Open-Meteo hourly {today}...", end=" ", flush=True)
    rows = fetch_om_hourly_today(city, session)
    if not rows:
        if verbose:
            print("sem dados OM")
        return {}, []

    t_vals = [r["temp_c"] for r in rows]
    if verbose:
        print(f"{len(rows)} obs  {min(t_vals)}°C – {max(t_vals)}°C")

    current_city_hour = datetime.now(tz=_get_city_timezone(city)).hour
    rows = [r for r in rows if int(r.get("hour", 0)) <= current_city_hour]
    if not rows:
        if verbose:
            print("sem dados OM passados")
        return {}, []

    _bootstrap_rows_cache[city_name] = rows

    series:  dict[tuple, float] = {}
    obs_min: dict[tuple, tuple] = {}
    for r in rows:
        # FIX Bug #3: usar floor_slot para consistência com o caller (ver acima).
        key = floor_slot(r["hour"], r["minute"])
        if key not in series or r["temp_c"] >= series[key]:
            series[key]  = r["temp_c"]
            obs_min[key] = (r["hour"], r["minute"])

    _bootstrap_obs_min[city_name] = obs_min

    seen:  set[tuple]  = set()
    slots: list[dict]  = []
    for r in sorted(rows, key=lambda x: x["hour"] * 60 + x["minute"]):
        k = floor_slot(r["hour"], r["minute"])
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
