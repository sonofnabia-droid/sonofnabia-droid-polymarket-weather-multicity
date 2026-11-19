#!/usr/bin/env python3
"""metar.py — observações METAR via aviationweather.gov (§98).

A resolução oficial dos mercados Polymarket é o METAR do ICAO da cidade.
O WU diverge em ~20% dos dias (basis risk). Este módulo passa a ser a
fonte preferida de temperatura ao vivo; WU fica como fallback.

API: https://aviationweather.gov/api/data/metar?ids=EGLC&format=json&hours=N
Sem chave, grátis. Cadência típica 20-60 min consoante a estação.
"""
import math
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests

METAR_URL = "https://aviationweather.gov/api/data/metar"
STALE_MIN = 90  # obs mais velha que isto -> considerar indisponível

_COVER_PCT = {"CLR": 0, "SKC": 0, "NSC": 0, "FEW": 20, "SCT": 40,
              "BKN": 75, "OVC": 100, "VV": 100}


def _cloud_pct(clouds) -> int:
    pct = 0
    if isinstance(clouds, list):
        for layer in clouds:
            if isinstance(layer, dict):
                pct = max(pct, _COVER_PCT.get(str(layer.get("cover", "")).upper(), 0))
    return pct


def _rh_from_dewpoint(temp_c: float, dewp_c: float) -> int:
    """Humidade relativa via fórmula de Magnus."""
    try:
        es_t = math.exp(17.625 * temp_c / (243.04 + temp_c))
        es_td = math.exp(17.625 * dewp_c / (243.04 + dewp_c))
        return max(0, min(100, round(100 * es_td / es_t)))
    except Exception:
        return 50


def _parse_time(m: dict) -> Optional[datetime]:
    rt = m.get("reportTime")
    if rt:
        try:
            return datetime.fromisoformat(str(rt).replace("Z", "+00:00"))
        except Exception:
            pass
    icao_t = m.get("obsTime")
    try:
        return datetime.fromtimestamp(int(icao_t), tz=timezone.utc)
    except Exception:
        return None


def _fetch(icao: str, hours: int) -> List[dict]:
    r = requests.get(METAR_URL,
                     params={"ids": icao, "format": "json", "hours": hours},
                     timeout=15)
    if r.status_code != 200:
        return []
    data = r.json()
    return data if isinstance(data, list) else []


_T_RE = re.compile(r"\bT([01])(\d{3})[01]\d{3}\b")


def _tremark_temp(raw: str):
    """T-remark (décimas) — a grandeza oficial de resolução (regras do mercado).
    T0156xxxx = +15.6°C · T1017xxxx = −1.7°C. None se ausente."""
    if not raw:
        return None
    m = _T_RE.search(raw)
    if not m:
        return None
    v = int(m.group(2)) / 10.0
    return -v if m.group(1) == "1" else v


def _to_obs(m: dict) -> Optional[Dict[str, Any]]:
    temp = m.get("temp")
    # §98: preferir o T-remark do raw (décimas, idêntico à resolução oficial);
    # o campo temp da API é o grupo do corpo (graus inteiros)
    t_tenths = _tremark_temp(str(m.get("rawOb") or ""))
    if temp is None and t_tenths is None:
        return None
    temp_c = round(t_tenths if t_tenths is not None else float(temp), 1)
    dewp = m.get("dewp")
    dewp_c = round(float(dewp), 1) if dewp is not None else temp_c - 10.0
    wspd_kt = m.get("wspd") or 0
    gust_kt = m.get("wgust") or wspd_kt
    altim_raw = m.get("altim")
    pressure_hpa = 1013.0
    if altim_raw:
        # a API devolve hPa (ex.: 1018.0); se algum dia vier inHg (<200), converte
        pressure_hpa = round(float(altim_raw) if float(altim_raw) > 200
                             else float(altim_raw) * 33.8639, 1)
    wdir_raw = m.get("wdir")
    try:
        wind_dir = int(float(wdir_raw))
    except (TypeError, ValueError):
        wind_dir = 0  # VRB (variável) e afins
    obs_time = _parse_time(m)
    return {
        "temp_c": temp_c,
        "temp_f": round(temp_c * 9 / 5 + 32, 1),
        "humidity": _rh_from_dewpoint(temp_c, dewp_c),
        "pressure_hpa": pressure_hpa,
        "wind_speed_kmh": round(float(wspd_kt) * 1.852, 1),
        "wind_gust_kmh": round(float(gust_kt) * 1.852, 1),
        "wind_dir_deg": wind_dir,
        "dewpoint_c": dewp_c,
        "uv_index": 0,
        "cloud_cover": _cloud_pct(m.get("clouds")),
        "obs_time": obs_time,
        "source": "metar",
    }


def fetch_metar_current(icao: str) -> Optional[Dict[str, Any]]:
    """Observação mais recente; None se inexistente ou mais velha que STALE_MIN."""
    try:
        reports = _fetch(icao, hours=3)
    except Exception:
        return None
    best, best_t = None, None
    for m in reports:
        t = _parse_time(m)
        if t and (best_t is None or t > best_t):
            obs = _to_obs(m)
            if obs:
                best, best_t = obs, t
    if best is None or best_t is None:
        return None
    age_min = (datetime.now(timezone.utc) - best_t).total_seconds() / 60
    if age_min > STALE_MIN:
        return None
    return best


def fetch_metar_today_slots(icao: str, city_tz, day: "object") -> List[dict]:
    """Slots de 30 min do dia local `day` (date) a partir dos METARs de hoje.
    Cada slot: {hour, slot30, temp_c, cloud_cover, humidity, ...}."""
    try:
        reports = _fetch(icao, hours=26)
    except Exception:
        return []
    slots: Dict[tuple, dict] = {}
    for m in reports:
        obs = _to_obs(m)
        t = obs.pop("obs_time", None) if obs else None
        if obs is None or t is None:
            continue
        local = t.astimezone(city_tz)
        if local.date() != day:
            continue
        slot30 = 0 if local.minute < 30 else 30
        key = (local.hour, slot30)
        # se dois METARs caem no mesmo slot, fica o mais recente
        slots[key] = {"hour": local.hour, "slot30": slot30, **obs}
    return [slots[k] for k in sorted(slots)]
