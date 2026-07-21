"""
weather_v3.py
=============
Funções para aceder à Weather Underground API V3 com ICAO code.

Esta API suporta estações oficiais (ICAO) ao contrário da V2 PWS.
Endpoints usados:
- v3/wx/observations/current        → Observações atuais
- v3/wx/forecast/daily/3day         → Forecast diário (3 dias)
- v3/wx/forecast/hourly/1day        → Forecast horário (1 dia)
- v3/wx/conditions/historical/hourly/1day → Histórico horário (1 dia)
"""

import requests
import json
from datetime import datetime, date
from typing import Optional, Dict, Any, List

V3_BASE = "https://api.weather.com/v3"


def _v3_get(endpoint: str, icao: str, api_key: str, units: str = "e", 
             language: str = "en-US", format: str = "json") -> Optional[Dict]:
    """Chamada genérica ao endpoint V3 com ICAO."""
    url = f"{V3_BASE}/{endpoint}"
    params = {
        "icaoCode": icao,
        "units": units,
        "language": language,
        "format": format,
        "apiKey": api_key,
    }
    try:
        resp = requests.get(url, params=params, timeout=15)
        if resp.status_code == 200:
            return resp.json()
        else:
            print(f"  [V3] {icao}: HTTP {resp.status_code} — {endpoint}")
            return None
    except Exception as e:
        print(f"  [V3] {icao}: Erro em {endpoint}: {e}")
        return None


def v3_fetch_current(icao: str, api_key: str) -> Optional[Dict[str, Any]]:
    """
    Observações atuais via V3 ICAO.
    Retorna dict com: temp_c, temp_f, humidity, pressure_hpa, wind_speed_kmh,
                      wind_dir_deg, wind_gust_kmh, dewpoint_c, uv_index,
                      cloud_cover, hour, minute
    """
    data = _v3_get("wx/observations/current", icao, api_key)
    if not data:
        return None

    obs = data.get("observation", {})
    if not obs:
        return None

    # Converter unidades
    temp_f = obs.get("temp")
    if temp_f is None:
        return None

    temp_c = round((temp_f - 32) * 5 / 9, 1)
    dewpt_f = obs.get("dewPt", temp_f - 20)
    dewpt_c = round((dewpt_f - 32) * 5 / 9, 1)

    # Pressão: inches → hPa
    pressure_in = obs.get("pressure", 29.92)
    pressure_hpa = round(pressure_in * 33.8639, 1)

    # Vento: mph → km/h
    wind_mph = obs.get("wspd", 0)
    wind_kmh = round(wind_mph * 1.60934, 1)
    gust_mph = obs.get("gust") or wind_mph
    gust_kmh = round(gust_mph * 1.60934, 1)

    # Direção
    wind_dir = obs.get("wdir", 0)

    # Humidade
    humidity = obs.get("rh", 50)

    # UV
    uv_index = obs.get("uv_index", 0)

    # Cloud cover (v3 usa clds como string, estimar)
    clds = obs.get("clds", "")
    cloud_cover = _clds_to_percent(clds)

    # Hora da observação
    valid_time = obs.get("valid_time_gmt")
    if valid_time:
        dt = datetime.utcfromtimestamp(valid_time)
        hour = dt.hour
        minute = dt.minute
    else:
        dt = datetime.utcnow()
        hour = dt.hour
        minute = dt.minute

    return {
        "temp_c": temp_c,
        "temp_f": temp_f,
        "humidity": humidity,
        "pressure_hpa": pressure_hpa,
        "wind_speed_kmh": wind_kmh,
        "wind_dir_deg": wind_dir,
        "wind_gust_kmh": gust_kmh,
        "dewpoint_c": dewpt_c,
        "uv_index": uv_index,
        "cloud_cover": cloud_cover,
        "hour": hour,
        "minute": minute,
    }


def v3_fetch_forecast_daily(icao: str, api_key: str) -> Optional[Dict[str, Any]]:
    """
    Forecast diário (3 dias) via V3 ICAO.
    Retorna dict com: temp_max (°C), temp_min (°C)
    """
    data = _v3_get("wx/forecast/daily/3day", icao, api_key)
    if not data:
        return None

    forecasts = data.get("calendarDayTemperatureMax", [])
    if not forecasts:
        return None

    temp_max_f = forecasts[0]  # Hoje
    temp_min_f = data.get("calendarDayTemperatureMin", [0])[0]

    return {
        "temp_max": round((temp_max_f - 32) * 5 / 9, 1),
        "temp_min": round((temp_min_f - 32) * 5 / 9, 1),
    }


def v3_fetch_forecast_hourly(icao: str, api_key: str) -> Optional[Dict[str, Any]]:
    """
    Forecast horário (1 dia) via V3 ICAO.
    Retorna dict com: temp_max (°C) — máxima prevista nas próximas 24h
    """
    data = _v3_get("wx/forecast/hourly/1day", icao, api_key)
    if not data:
        return None

    temps = data.get("temperature", [])
    if not temps:
        return None

    # Encontrar máxima nas próximas horas
    max_f = max(t for t in temps if t is not None)

    return {
        "temp_max": round((max_f - 32) * 5 / 9, 1),
    }


def v3_fetch_historical_hourly(icao: str, api_key: str) -> Optional[List[Dict[str, Any]]]:
    """
    Histórico horário do dia atual via V3 ICAO.
    Retorna lista de slots com: hour, slot30, temp_c, cloud_cover, humidity, etc.

    Endpoint: v3/wx/conditions/historical/hourly/1day

    NOTA: A resposta V3 vem com as chaves directamente (temperature, relativeHumidity, etc.)
    NÃO tem uma chave intermédia "v3-wx-conditions-historical-hourly-1day".
    """
    data = _v3_get("wx/conditions/historical/hourly/1day", icao, api_key)
    if not data:
        return None

    # A resposta V3 vem com as chaves directamente
    # Exemplo: {'temperature': [86, 85, ...], 'relativeHumidity': [51, 52, ...], ...}

    # Extrair arrays directamente
    temps_f = data.get("temperature", [])
    if not temps_f:
        print(f"  [V3] {icao}: Sem dados de temperatura no histórico")
        return None

    dews_f = data.get("temperatureDewPoint", [])
    rh = data.get("relativeHumidity", [])
    wind_spd = data.get("windSpeed", [])
    wind_dir = data.get("windDirection", [])
    wind_gust = data.get("windGust", [])
    pressure = data.get("pressureAltimeter", [])
    uv = data.get("uvIndex", [])
    valid_times = data.get("validTimeLocal", [])

    n = len(temps_f)
    slots = []

    for i in range(n):
        if temps_f[i] is None:
            continue

        # Converter temperatura F → C
        temp_c = round((temps_f[i] - 32) * 5 / 9, 1)

        # Dewpoint
        dew_f = dews_f[i] if i < len(dews_f) and dews_f[i] is not None else temps_f[i] - 20
        dew_c = round((dew_f - 32) * 5 / 9, 1)

        # Humidade
        humidity = rh[i] if i < len(rh) and rh[i] is not None else 70

        # Vento: mph → km/h
        wspd = wind_spd[i] if i < len(wind_spd) and wind_spd[i] is not None else 0
        wkmh = round(wspd * 1.60934, 1)

        wgust = wind_gust[i] if i < len(wind_gust) and wind_gust[i] is not None else wspd
        gkmh = round(wgust * 1.60934, 1)

        # Direção
        wdir = wind_dir[i] if i < len(wind_dir) and wind_dir[i] is not None else 0

        # Pressão: inches → hPa
        press_in = pressure[i] if i < len(pressure) and pressure[i] is not None else 29.92
        press_hpa = round(press_in * 33.8639, 1)

        # UV
        uv_idx = uv[i] if i < len(uv) and uv[i] is not None else 0

        # Hora
        if i < len(valid_times) and valid_times[i]:
            try:
                # Formato: "2016-09-17T12:45:00-0400"
                dt_str = valid_times[i][:19]  # Remove timezone
                dt = datetime.strptime(dt_str, "%Y-%m-%dT%H:%M:%S")
                hour = dt.hour
                minute = dt.minute
            except Exception:
                hour = i
                minute = 0
        else:
            hour = i
            minute = 0

        # slot30: 0 para :00, 30 para :30
        slot30 = 30 if minute >= 30 else 0

        # Cloud cover (não disponível no V3 historical, estimar)
        cloud_cover = 50

        slot = {
            "hour": hour,
            "slot30": slot30,
            "temp_c": temp_c,
            "cloud_cover": cloud_cover,
            "humidity": humidity,
            "dewpoint_c": dew_c,
            "pressure_hpa": press_hpa,
            "wind_dir_deg": wdir,
            "wind_speed_kmh": wkmh,
            "wind_gust_kmh": gkmh,
            "uv_index": uv_idx,
        }
        slots.append(slot)

    return slots


def _clds_to_percent(clds: str) -> int:
    """Converte código de cloud cover para percentagem."""
    mapping = {
        "CLR": 0,    # Clear
        "FEW": 15,   # Few
        "SCT": 30,   # Scattered
        "BKN": 60,   # Broken
        "OVC": 90,   # Overcast
    }
    return mapping.get(clds, 50)


def v3_bootstrap_today(icao: str, api_key: str) -> tuple:
    """
    Bootstrap do dia atual usando V3 ICAO.
    Retorna (series_dict, slots_list) como o bootstrap_today original.
    """
    slots = v3_fetch_historical_hourly(icao, api_key)

    if not slots or len(slots) < 4:
        return {}, []

    # Filtrar só slots do dia atual
    today = date.today()
    filtered = [s for s in slots if s.get("date", today) == today]

    # Se não há slots de hoje, usar todos (o endpoint pode retornar últimas 24h)
    if not filtered:
        filtered = slots

    # Ordenar por hora
    filtered.sort(key=lambda s: s["hour"] * 60 + s["slot30"])

    # Construir series dict
    series = {}
    for idx, s in enumerate(filtered):
        series[(s["hour"], s["slot30"], idx)] = s["temp_c"]

    return series, filtered
