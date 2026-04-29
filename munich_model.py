"""
munich_model.py
===============
Carregamento de modelos (LightGBM + XGBoost), construção de features
V1 canonicas + V2 preditivas, predicao ensemble com predict_proba(),
z-score streaming, gestao do historico diario de maximas.

ASSINATURA de predict_ensemble (NÃO alterar):
  predict_ensemble(models, slots_so_far, current, month, doy, zscore_detector=None)
  -> dict: {p_ensemble, p_lgbm, p_xgb, p_zscore, weights, components}
"""

import json
from datetime import date
from pathlib import Path
import warnings

import joblib
import numpy as np
import pandas as pd

from munich_config import (
    MODEL_LGB, MODEL_XGB, MODEL_CONFIG, FEATURE_COLS,
    ENSEMBLE_WEIGHTS, LOG_DIR,
    MIN_HOUR,
)

# ══════════════════════════════════════════════════════
# SEASONAL PRIOR
# ══════════════════════════════════════════════════════
_SEASONAL_PRIOR: dict[tuple, float] = {}

def set_seasonal_prior(prior_map: dict) -> None:
    global _SEASONAL_PRIOR
    _SEASONAL_PRIOR = prior_map or {}

def get_seasonal_prior(month: int, hour: int, slot30: int) -> float:
    if _SEASONAL_PRIOR:
        return _SEASONAL_PRIOR.get((month, hour, slot30), 0.5)
    return 0.5

# ══════════════════════════════════════════════════════
# LOAD MODELS — LightGBM puro
# ══════════════════════════════════════════════════════
# Decisão 2026-04: removido ensemble LGBM+XGB+z-score. Ver comentário
# em munich_config.ENSEMBLE_WEIGHTS para racional.
# Mantemos `model_xgb` e `ensemble_weights` nas chaves do dict retornado
# apenas para não quebrar código chamador legado — têm sempre valores neutros.
def load_models(model_dir: Path = None) -> dict:
    if model_dir is None:
        model_dir = Path("munich_peak_model")

    lgb_path = model_dir / "lgbm_peak.pkl"
    config_path = model_dir / "peak_model_config.json"

    if not lgb_path.exists():
        raise FileNotFoundError(
            f"\nModelo não encontrado: {lgb_path}\n"
            "Corre primeiro: python munich_train.py"
        )

    model_lgb = joblib.load(lgb_path)

    config = {}
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text())
        except Exception:
            pass

    feat_cols = config.get("feature_cols", FEATURE_COLS)

    # Prior sazonal
    raw_prior = config.get("seasonal_peak_prior", {})
    prior_map: dict[tuple, float] = {}
    for k, v in raw_prior.items():
        parts = k.split("_")
        if len(parts) == 3:
            try:
                prior_map[(int(parts[0]), int(parts[1]), int(parts[2]))] = float(v)
            except ValueError:
                pass

    # Threshold (opcional, legado)
    raw_thresh = config.get("monthly_threshold", {})
    monthly_threshold: dict[int, float] = {}
    for k, v in raw_thresh.items():
        try:
            monthly_threshold[int(k)] = float(v)
        except ValueError:
            pass

    doy_poly_raw = config.get("doy_poly_coeffs")
    doy_poly = np.array(doy_poly_raw, dtype=float) if doy_poly_raw else None

    # Weights: sempre LightGBM=1.0 (legacy: aceitamos o que vier no config mas
    # forçamos LGBM puro se o config ainda tiver weights de ensemble antigo)
    saved_weights = config.get("ensemble_weights", {})
    if saved_weights.get("lgbm", 1.0) < 1.0:
        # Config antigo com ensemble — avisar e forçar LGBM puro
        print(
            f" ⚠  Config tem weights de ensemble antigo {saved_weights} — "
            "forçando LightGBM puro (ver comentário em munich_config)"
        )
    weights = {"lgbm": 1.0, "xgb": 0.0, "zscore": 0.0}

    auc = config.get("global_auc", "?")
    if isinstance(auc, float):
        auc_str = f"{auc:.4f}"
    else:
        auc_str = str(auc)

    if doy_poly is not None:
        thr_str = f"curva DOY grau {len(doy_poly)-1}"
    elif monthly_threshold:
        thr_str = f"{len(monthly_threshold)} meses"
    else:
        thr_str = "não disponível"

    print(f" ✓ LightGBM AUC={auc_str} features={len(feat_cols)} "
          f"threshold={thr_str} "
          f"prior={'sim' if prior_map else 'não'} "
          f"[LightGBM puro]")

    return {
        "model_lgb": model_lgb,
        "model_xgb": None,              # legado — sempre None
        "feat_cols": feat_cols,
        "prior_map": prior_map,
        "monthly_threshold": monthly_threshold,
        "doy_poly": doy_poly,
        "ensemble_weights": weights,    # legado — sempre {lgbm:1, xgb:0, z:0}
    }

# ══════════════════════════════════════════════════════
# FEATURE BUILDER
# ══════════════════════════════════════════════════════
def build_features(slots_so_far: list[dict], current: dict,
                   month: int, doy: int) -> dict:
    vals = [s["temp_c"] for s in slots_so_far]
    hums = [s.get("humidity", 70) for s in slots_so_far]
    n = len(vals)
    cur = vals[-1]
    rmax = max(vals)
    hour = current["hour"]
    slot30 = current.get("slot30", 0)
    cloud = float(current.get("cloud_cover", 50))

    def lag(k): return vals[-k] if n >= k else vals[0]
    def lagh(k): return hums[-k] if n >= k else hums[0]

    morn_vals = [s["temp_c"] for s in slots_so_far[:-1] if s.get("hour", 0) <= 12]
    mmax = max(morn_vals) if morn_vals else cur

    prev7 = current.get("prev_7d_avg_max", rmax)
    slot_frac = (hour + slot30 / 60.0) / 24.0

    slope_w = vals[-4:] if n >= 4 else vals
    slope = float(np.polyfit(np.arange(len(slope_w)), slope_w, 1)[0]) if len(slope_w) >= 2 else 0.0

    plateau = 1.0 if (np.std(vals[-6:]) < 0.4 and n >= 4) else 0.0
    radiation = float(np.cos((slot_frac - 0.5) * 2 * np.pi)) * (1 - cloud / 100)
    hum_drop_1h = lagh(3) - hums[-1] if n >= 3 else 0.0

    dewpt = float(current.get("dewpoint_c", cur - 10))
    wdir = float(current.get("wind_dir_deg", 0.0))
    wspd = float(current.get("wind_speed_kmh", 5.0))
    wgst = float(current.get("wind_gust_kmh", 8.0))
    uv = float(current.get("uv_index", 3.0))
    hu = hums[-1] if hums else 70.0

    temp_to_dewpoint_gap = max(0.0, cur - dewpt)
    press_vals = [s.get("pressure_hpa", 1013.0) for s in slots_so_far[-6:]]
    pressure_trend_3h = (press_vals[-1] - press_vals[0]) if len(press_vals) >= 2 else 0.0

    wind_south_proxy = (1.0 - abs(wdir - 180) / 45.0) if 135 <= wdir <= 225 else 0.0
    foehn_south = 1.0 if 135 <= wdir <= 225 else 0.0
    foehn_gusty = min(1.0, wgst / 30.0)
    foehn_dry = max(0.0, (80 - hu) / 20.0) if hu < 80 else 0.0
    foehn_indicator = foehn_south * (0.4 + 0.3 * foehn_gusty + 0.3 * foehn_dry)

    return {
        "slot_frac": slot_frac,
        "doy_sin": float(np.sin(2 * np.pi * doy / 365)),
        "doy_cos": float(np.cos(2 * np.pi * doy / 365)),
        "temp_c": cur,
        "running_max": rmax,
        "temp_vs_climatology": cur - prev7,
        "delta_30m": cur - lag(2),
        "delta_1h": cur - lag(3),
        "accel": (cur - lag(2)) - (lag(2) - lag(3)),
        "recent_slope": slope,
        # FIX #4: temp_lag_3 estava em FEATURE_COLS mas NÃO era retornada aqui
        # → o predict_ensemble usava sempre 0.0 em produção (model mismatch).
        # IMPORTANTE: no munich_train.py usa-se `day_df["temp_c"].shift(3).iloc[i]`,
        # ou seja, 3 slots atrás (= 1h30 para slots de 30min), NÃO 3 horas.
        # Espelhamos a mesma semântica aqui: lag(k) é vals[-k] com lag(1) = atual,
        # portanto 3 slots atrás = lag(4).
        "temp_lag_3": lag(4),
        "roll3_std": float(np.std(vals[-3:])) if n >= 3 else 0.0,
        "plateau_indicator": plateau,
        "morning_max": mmax,
        "radiation_proxy": radiation,
        "humidity_drop_1h": hum_drop_1h,
        "prev_7d_avg_max": prev7,
        "seasonal_peak_prior": get_seasonal_prior(month, hour, slot30),
        "dewpoint_c": dewpt,
        "temp_to_dewpoint_gap": temp_to_dewpoint_gap,
        "pressure_trend_3h": pressure_trend_3h,
        "wind_south_proxy": wind_south_proxy,
        "wind_speed_kmh": wspd,
        "uv_index": uv,
        "foehn_indicator": foehn_indicator,
    }


# ══════════════════════════════════════════════════════
# PREDICT — LightGBM puro
# ══════════════════════════════════════════════════════
# Nome mantido como `predict_ensemble` e assinatura inalterada (incluindo
# o `zscore_detector` opcional) para retro-compatibilidade com backtester
# e live_bot. Internamente usa apenas LightGBM.
def predict_ensemble(
    models: dict,
    slots_so_far: list[dict],
    current: dict,
    month: int,
    doy: int,
    zscore_detector=None,     # mantido para compatibilidade; ignorado
) -> dict:
    hour = current["hour"]
    if len(slots_so_far) < 4 or hour < MIN_HOUR:
        return {
            "p_ensemble": 0.0,
            "p_lgbm": 0.0,
            "p_xgb": None,
            "p_zscore": None,
            "weights": {"lgbm": 1.0, "xgb": 0.0, "zscore": 0.0},
            "components": {},
        }

    feat_cols = models["feat_cols"]
    row = build_features(slots_so_far, current, month, doy)

    # numpy array direto (rápido)
    X_array = np.array([[row.get(f, 0.0) for f in feat_cols]], dtype=np.float32)

    p_lgbm = float(models["model_lgb"].predict_proba(X_array)[0, 1])
    p_lgbm = float(np.clip(p_lgbm, 0.0, 1.0))

    return {
        "p_ensemble": p_lgbm,          # com LightGBM puro, p_ensemble == p_lgbm
        "p_lgbm": p_lgbm,
        "p_xgb": None,
        "p_zscore": None,
        "weights": {"lgbm": 1.0, "xgb": 0.0, "zscore": 0.0},
        "components": {"lgbm": round(p_lgbm, 4)},
    }


# ══════════════════════════════════════════════════════
# STREAMING Z-SCORE PEAK DETECTOR
# ══════════════════════════════════════════════════════
class StreamingPeakDetector:
    def __init__(self, lookback: int = 24, threshold_z: float = 1.5):
        self.lookback = lookback
        self.threshold_z = threshold_z
        self.buffer: list[float] = []
        self.running_max: float = -999.0

    def update(self, temp: float) -> float:
        self.buffer.append(temp)
        self.running_max = max(self.running_max, temp)
        if len(self.buffer) > self.lookback * 2:
            self.buffer = self.buffer[-self.lookback * 2:]

        if len(self.buffer) < 8:
            return 0.0

        arr = np.array(self.buffer[-self.lookback:])
        n = len(arr)
        mean, std = np.mean(arr), np.std(arr)
        z = (temp - mean) / std if std > 0.1 else 0.0
        z_signal = float(1.0 / (1.0 + np.exp(-1.5 * (z - self.threshold_z))))

        slope = float(np.polyfit(np.arange(n, dtype=float), arr, 1)[0]) if n >= 4 else 0.0
        slope_signal = float(1.0 / (1.0 + np.exp(5.0 * slope)))

        pct_of_max = temp / self.running_max if self.running_max > 0 else 1.0
        max_signal = min(1.0, pct_of_max ** 2)

        p = 0.40 * z_signal + 0.35 * slope_signal + 0.25 * max_signal
        return float(np.clip(p, 0.0, 1.0))

    def reset(self) -> None:
        self.buffer = []
        self.running_max = -999.0


# ══════════════════════════════════════════════════════
# PREV_7D_AVG_MAX
# ══════════════════════════════════════════════════════
_CLIMATOLOGY_BY_MONTH = {
    1: 3.0, 2: 5.0, 3: 10.0, 4: 15.0, 5: 20.0, 6: 23.0,
    7: 25.0, 8: 25.0, 9: 20.0, 10: 14.0, 11: 7.0, 12: 4.0
}

def compute_prev7(history: dict, d: date) -> float:
    if not history:
        return _CLIMATOLOGY_BY_MONTH.get(d.month, 15.0)
    days = sorted(history.keys())
    if d not in days:
        recent = days[-7:]
        if recent:
            return float(np.mean([history[x] for x in recent]))
        return _CLIMATOLOGY_BY_MONTH.get(d.month, 15.0)
    idx = days.index(d)
    if idx == 0:
        return float(history[d])
    window = days[max(0, idx - 7):idx]
    vals = [history[x] for x in window]
    return float(np.mean(vals)) if vals else float(history[d])


# ══════════════════════════════════════════════════════
# HISTORY MAX — dicionário {date: max_temp}
# FIX #1: funções em falta que o live_bot importa (linhas 38-39).
#         Sem elas, `from munich_model import ...` crasha logo no arranque.
# ══════════════════════════════════════════════════════
_last_save_time = 0.0

def init_history_max() -> dict:
    """
    Carrega o histórico de máximas diárias do disco.
    Usar LOG_DIR em vez de path hardcoded.
    """
    import time
    path = LOG_DIR / "live_history_max.json"
    if path.exists():
        try:
            return {
                date.fromisoformat(k): float(v)
                for k, v in json.loads(path.read_text()).items()
            }
        except Exception:
            pass
    return {}


def _save_history_max_file(history_max: dict) -> None:
    """Helper interno para salvar em disco."""
    path = LOG_DIR / "live_history_max.json"
    LOG_DIR.mkdir(exist_ok=True)
    data = {d.isoformat(): v for d, v in history_max.items()}
    path.write_text(json.dumps(data, indent=2))


def update_history_max(history: dict, slots_so_far: list[dict]) -> None:
    """
    Atualiza (in-place) a entrada do dia de hoje com o max das temperaturas
    observadas até agora. Idempotente — pode ser chamada em cada tick.

    `slots_so_far` é a lista cumulativa de slots do dia corrente.

    FIX: só guardar em disco a cada 5 minutos ou se a máxima subiu
         para reduzir I/O excessivo.
    """
    global _last_save_time
    if not slots_so_far:
        return
    # import local para evitar ciclo com munich_config em import-time
    from munich_config import berlin_date
    today = berlin_date()
    try:
        cur_max = max(s["temp_c"] for s in slots_so_far if "temp_c" in s)
    except ValueError:
        return  # lista vazia após filtro
    if np.isnan(cur_max) or np.isinf(cur_max):
        return
    old_max = history.get(today)
    history[today] = max(history.get(today, -999.0), float(cur_max))

    # Só guardar em disco a cada 5 minutos ou se a máxima subiu
    import time
    now = time.time()
    if now - _last_save_time >= 300 or old_max is None or cur_max > old_max:
        _save_history_max_file(history)
        _last_save_time = now


# Retrocompatibilidade
def load_model():
    result = load_models()
    return result["model_lgb"], result["feat_cols"], result["prior_map"], result["monthly_threshold"]


def predict_p(model, feat_cols, slots_so_far: list[dict], current: dict, month: int, doy: int) -> float:
    """Retrocompatibilidade"""
    row = build_features(slots_so_far, current, month, doy)
    X = pd.DataFrame([row])[feat_cols].fillna(0)
    return float(model.predict_proba(X)[0, 1])