"""
munich_config.py
================
Constantes globais, helpers de timezone, ANSI e janelas de sinal WU.
Importado por todos os outros módulos — sem dependências externas
além da stdlib e numpy.

NÃO importar munich_weather/model/display aqui a nível de módulo, para
evitar ciclos (o smart_sleep faz import local da fetch_wu_latest).

Histórico:
- Sprint 1: smart_sleep separado
- Sprint 2.3.8: POLY_MAX_DAILY_LOSS com try/except
- Iteração 5 (2026): smart_sleep integrada aqui com polling activo
  nas janelas EDDM (quando a estação de facto reporta nova observação).
"""

import os
import time
import warnings
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

warnings.filterwarnings("ignore")


# ══════════════════════════════════════════════════════
#  TIMEZONES
# ══════════════════════════════════════════════════════

_BERLIN = ZoneInfo("Europe/Berlin")
_LOCAL  = ZoneInfo("Europe/Lisbon")   # fuso local do bot — ajustar se necessário


def berlin_now() -> datetime:
    """Datetime atual em hora de Berlim/Munich."""
    return datetime.now(tz=_BERLIN)


def berlin_date() -> date:
    """Data atual segundo o relógio de Munich — determina o slug do mercado."""
    return berlin_now().date()


def local_now() -> datetime:
    """Datetime atual no fuso local do bot (Lisboa)."""
    return datetime.now(tz=_LOCAL)


# ══════════════════════════════════════════════════════
#  HORARIO ACTIVO DO BOT (hora local)
# ══════════════════════════════════════════════════════

BOT_ACTIVE_START = 8   # 08:00 hora local (Lisboa)
BOT_ACTIVE_END   = 20  # 20:00 hora local (Lisboa)


# ══════════════════════════════════════════════════════
#  JANELAS DE SINAL EDDM
# ══════════════════════════════════════════════════════

# A estação reporta tipicamente ~:20 e ~:50 de cada hora.
_SIGNAL_CHECK_WINDOWS = [(18, 32), (45, 55)]  # (min_início, min_fim) hora Berlim

# Intervalo de polling rápido dentro das janelas de sinal (segundos)
_FAST_POLL_INTERVAL = 2


def _in_signal_window() -> bool:
    """True se o minuto atual de Berlim está dentro de uma janela de sinal EDDM."""
    m = berlin_now().minute
    return any(lo <= m <= hi for lo, hi in _SIGNAL_CHECK_WINDOWS)


def smart_sleep(interval: int, wu_key: str, wu_sess, last_temp, on_new_obs=None):
    """
    Substitui time.sleep(interval) no loop principal.

    Fora das janelas de sinal: dorme `interval` segundos normalmente.
    Dentro das janelas de sinal (EDDM tipicamente reporta ~:20 e ~:50):
    faz polling ativo à WU a cada _FAST_POLL_INTERVAL segundos até
    detectar uma nova temperatura OU sair da janela.

    Devolve a nova observação WU se foi detectada durante o fast-poll,
    ou None caso contrário.

    Parâmetros
    ----------
    interval : int
        Segundos a dormir fora das janelas.
    wu_key : str
        API key Weather Underground.
    wu_sess : requests.Session
        Sessão HTTP para a WU.
    last_temp : float | None
        Temperatura da última observação, para detectar mudança.
    on_new_obs : callable | None
        Callback opcional(obs) chamado assim que nova temperatura
        é detectada durante o polling.
    """
    # Importação local para evitar ciclo munich_config → munich_weather → munich_config
    from munich_weather import fetch_wu_latest

    if not _in_signal_window():
        time.sleep(interval)
        return None

    # Estamos numa janela — polling rápido até encontrar nova obs ou sair da janela
    deadline = time.time() + interval
    while time.time() < deadline and _in_signal_window():
        time.sleep(_FAST_POLL_INTERVAL)
        try:
            obs = fetch_wu_latest(wu_key, wu_sess)
        except Exception:
            obs = None
        if obs and obs.get("temp_c") != last_temp:
            if on_new_obs:
                on_new_obs(obs)
            return obs

    # Janela passou ou deadline atingido — dormir o restante do intervalo
    remaining = deadline - time.time()
    if remaining > 0:
        time.sleep(remaining)
    return None


# ══════════════════════════════════════════════════════
#  SLOT 30MIN
# ══════════════════════════════════════════════════════

def ceil_slot(hour: int, minute: int) -> tuple[int, int]:
    """
    Converte (hour, minute) de uma observação WU para o slot 30min correto.

    Semântica: truncar para CIMA.
      minute=0-29  → slot 30 da mesma hora    (ex: 14:20 → (14, 30))
      minute=30-59 → slot  0 da hora seguinte (ex: 14:50 → (15,  0))
    """
    if minute < 30:
        return (hour, 30)
    else:
        return (hour + 1, 0)


# ══════════════════════════════════════════════════════
#  PATHS
# ══════════════════════════════════════════════════════

MODEL_LGB    = Path("munich_peak_model/lgbm_peak.pkl")
MODEL_XGB    = Path("munich_peak_model/xgb_peak.pkl")
MODEL_CONFIG = Path("munich_peak_model/peak_model_config.json")
DATA_CSV     = Path("historic/munich.csv")
LOG_DIR      = Path("live_bot_logs")
BACKTEST_RESULTS_DIR = Path("backtest_results")


# ══════════════════════════════════════════════════════
#  URLs
# ══════════════════════════════════════════════════════

WU_BASE     = "https://api.weather.com/v1/location"
GAMMA_API   = "https://gamma-api.polymarket.com"
OM_FORECAST = "https://api.open-meteo.com/v1/forecast"
OM_ARCHIVE  = "https://archive-api.open-meteo.com/v1/archive"


# ══════════════════════════════════════════════════════
#  CHAVES DE AMBIENTE (Sprint 2.3.8)
# ══════════════════════════════════════════════════════

WU_API_KEY          = os.environ.get("WU_API_KEY", "")
POLY_PRIVATE_KEY    = os.environ.get("POLY_PRIVATE_KEY", "")

try:
    POLY_MAX_DAILY_LOSS = float(os.environ.get("POLY_MAX_DAILY_LOSS", "50"))
except ValueError:
    POLY_MAX_DAILY_LOSS = 50.0


# ══════════════════════════════════════════════════════
#  GEO
# ══════════════════════════════════════════════════════

MUNICH_LAT    = 48.35
MUNICH_LON    = 11.79
MUNICH_LAT_OM = 48.14
MUNICH_LON_OM = 11.58


# ══════════════════════════════════════════════════════
#  HORARIO DE DADOS
# ══════════════════════════════════════════════════════

DAY_START = 6
DAY_END   = 21
MIN_HOUR  = 6


# ══════════════════════════════════════════════════════
#  NOMES DE MESES / ESTAÇÕES
# ══════════════════════════════════════════════════════

MONTH_NAMES = {
    1: "january",  2: "february", 3: "march",    4: "april",
    5: "may",      6: "june",     7: "july",      8: "august",
    9: "september",10: "october", 11: "november", 12: "december",
}
SEASONS = {
    "winter": [12, 1, 2], "spring": [3, 4, 5],
    "summer": [6, 7, 8],  "autumn": [9, 10, 11],
}


# ══════════════════════════════════════════════════════
#  FEATURES CANONICAS — 25 total
# ══════════════════════════════════════════════════════

FEATURE_COLS = [
    "slot_frac", "doy_sin", "doy_cos",
    "temp_c", "running_max", "temp_vs_climatology",
    "delta_30m", "delta_1h", "accel", "recent_slope",
    "temp_lag_3", "roll3_std", "plateau_indicator",
    "morning_max", "radiation_proxy", "humidity_drop_1h",
    "prev_7d_avg_max", "seasonal_peak_prior",
    "dewpoint_c", "temp_to_dewpoint_gap", "pressure_trend_3h",
    "wind_south_proxy", "wind_speed_kmh", "uv_index", "foehn_indicator",
]


# ══════════════════════════════════════════════════════
#  MODELO — LightGBM puro
# ══════════════════════════════════════════════════════
#
# Decisão (2026-04): removido o ensemble LGBM+XGB+z-score.
# Razão: o LightGBM sozinho tem AUC walk-forward ~0.954 e gap in-sample
# de apenas 0.011 — um modelo já forte. XGBoost era redundância
# (mesmo algoritmo, gradient boosting em árvores). O z-score do
# StreamingPeakDetector é mais fraco que o LGBM e estava a diluir as
# predições do modelo principal — o `slope_signal` do z-score ativa
# quando a temperatura já está a descer (depois do pico), o que é o
# oposto do que queremos para entrar antes do pico.
#
# ENSEMBLE_WEIGHTS é mantido como dicionário "de legado" para não quebrar
# código antigo que o importe; valores forçam LightGBM puro.

ENSEMBLE_WEIGHTS = {
    "lgbm":   1.00,
    "xgb":    0.00,
    "zscore": 0.00,
}

FORECAST_AGREEMENT_TOLERANCE = 2


# ══════════════════════════════════════════════════════
#  ANSI
# ══════════════════════════════════════════════════════

R   = "\033[0m"
B   = "\033[1m"
DIM = "\033[2m"
C = {
    "cyan":   "\033[96m", "green":  "\033[92m", "yellow": "\033[93m",
    "orange": "\033[33m", "red":    "\033[91m", "blue":   "\033[94m",
    "purple": "\033[95m", "gray":   "\033[90m", "white":  "\033[97m",
    "reset":  "\033[0m",
}