"""
cassiopeia_predictor.py v3 (UNIFICADO)
Fusao do antigo predictor.py + cassiopeia_predictor.py.
Reconstruido apos corrupcao (ficheiro truncado a 0 bytes).
"""
from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import json
import os
import bisect
import warnings
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import joblib
import numpy as np

from cities.config import CityConfig, get_city

LOG_DIR = Path(os.environ.get("CASS_LOG_DIR", "live_bot_logs"))
LOG_DIR.mkdir(exist_ok=True)

warnings.filterwarnings(
    "ignore",
    message="X does not have valid feature names, but LGBMClassifier was fitted with feature names",
    category=UserWarning,
)

MODEL_SUBDIR = "cassiopeia_rebound_model"
WARNED = set()


def _warn_once(key: str, msg: str) -> None:
    if key not in WARNED:
        sys.stderr.write(f"[AVISO] {msg}\n")
        WARNED.add(key)


def _model_predict_proba(model, X_array) -> float:
    """Dispatch: sklearn API (predict_proba) OU LightGBM Booster nativo (predict)."""
    if hasattr(model, "predict_proba"):
        return float(model.predict_proba(X_array)[0, 1])
    if hasattr(model, "predict"):
        num_iter = getattr(model, "best_iteration", None)
        out = model.predict(X_array, num_iteration=num_iter) if num_iter else model.predict(X_array)
        return float(np.asarray(out).ravel()[0])
    raise TypeError(f"Modelo de tipo nao suportado: {type(model).__name__}")


_last_save_times: dict[str, float] = {}


def set_city(name: str) -> CityConfig:
    return get_city(name)


def _get_city() -> CityConfig:
    raise ValueError("_get_city sem city_name — passar a cidade explicitamente "
                     "(o fallback munich silencioso já custou análises erradas)")


def _city_now(city_name: str | None = None) -> datetime:
    cfg = get_city(city_name) if city_name else _get_city()
    return datetime.now(tz=ZoneInfo(cfg.timezone))


def _city_date(city_name: str | None = None) -> date:
    return _city_now(city_name).date()


def _bot_now(city_name: str | None = None) -> datetime:
    cfg = get_city(city_name) if city_name else _get_city()
    return datetime.now(tz=ZoneInfo(cfg.bot_timezone))


_SEASONAL_PRIOR: dict[tuple, float] = {}


def set_seasonal_prior(prior_map: dict) -> None:
    global _SEASONAL_PRIOR
    _SEASONAL_PRIOR = prior_map or {}


def get_seasonal_prior(month: int, hour: int, slot30: int) -> float:
    if _SEASONAL_PRIOR:
        return _SEASONAL_PRIOR.get((month, hour, slot30), 0.5)
    return 0.5


def _lookup_seasonal_prior(month: int, hour: int, slot30: int,
                           prior_map: dict | None = None) -> float:
    if prior_map:
        return prior_map.get((month, hour, slot30), 0.5)
    return get_seasonal_prior(month, hour, slot30)


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


def load_models(city: str = "munich", model_dir: Path | None = None) -> dict:
    """Carrega o modelo PEAK para a cidade especificada."""
    config = get_city(city)
    if model_dir is None:
        model_dir = Path(config.model_dir)

    lgb_path = model_dir / "lgbm_peak.pkl"
    config_path = model_dir / "peak_model_config.json"

    if not lgb_path.exists():
        raise FileNotFoundError(
            f"\nModelo nao encontrado: {lgb_path}\n"
            f"Corre primeiro: python train.py --city {city}"
        )

    model_lgb = joblib.load(lgb_path)

    cfg_dict = {}
    if config_path.exists():
        try:
            cfg_dict = json.loads(config_path.read_text())
        except Exception as e:
            _warn_once(f"peakcfg_{city}", f"peak_model_config.json ilegivel: {e}")

    feat_cols = cfg_dict.get("feature_cols", FEATURE_COLS)

    raw_prior = cfg_dict.get("seasonal_peak_prior", {})
    prior_map: dict[tuple, float] = {}
    for k, v in raw_prior.items():
        parts = k.split("_")
        if len(parts) == 3:
            try:
                prior_map[(int(parts[0]), int(parts[1]), int(parts[2]))] = float(v)
            except ValueError:
                pass

    raw_thresh = cfg_dict.get("monthly_threshold", {})
    monthly_threshold: dict[int, float] = {}
    for k, v in raw_thresh.items():
        try:
            monthly_threshold[int(k)] = float(v)
        except ValueError:
            pass

    doy_poly_raw = cfg_dict.get("doy_poly_coeffs")
    doy_poly = np.array(doy_poly_raw, dtype=float) if doy_poly_raw else None

    auc = cfg_dict.get("global_auc", "?")
    auc_str = f"{auc:.4f}" if isinstance(auc, float) else str(auc)

    print(f" ✓ [{config.name}] Peak modelo={type(model_lgb).__name__} "
          f"AUC={auc_str} features={len(feat_cols)} prior={'sim' if prior_map else 'nao'}")

    return {
        "model_lgb": model_lgb,
        "model_xgb": None,
        "feat_cols": feat_cols,
        "prior_map": prior_map,
        "monthly_threshold": monthly_threshold,
        "doy_poly": doy_poly,
        "ensemble_weights": {"lgbm": 1.0, "xgb": 0.0, "zscore": 0.0},
        "_city": config,
    }


def load_models_rebound(city: str = "munich", model_dir: Path | None = None) -> dict:
    """Carrega o modelo REBOUND (Cassiopeia) para a cidade especificada."""
    config = get_city(city)
    if model_dir is None:
        model_dir = Path(config.model_dir).parent / MODEL_SUBDIR

    lgb_path = model_dir / "lgbm_rebound.pkl"
    config_path = model_dir / "rebound_model_config.json"

    if not lgb_path.exists():
        raise FileNotFoundError(
            f"\nModelo rebound nao encontrado: {lgb_path}\n"
            f"Corre primeiro: python cassiopeia_train.py --city {city}"
        )

    model_lgb = joblib.load(lgb_path)

    cfg_dict = {}
    if config_path.exists():
        try:
            cfg_dict = json.loads(config_path.read_text())
        except Exception as e:
            _warn_once(f"rbcfg_{city}", f"rebound_model_config.json ilegivel: {e}")

    feat_cols = cfg_dict.get("feature_cols", FEATURE_COLS)

    raw_prior = cfg_dict.get("seasonal_peak_prior", {})
    prior_map: dict[tuple, float] = {}
    for k, v in raw_prior.items():
        parts = k.split("_")
        if len(parts) == 3:
            try:
                prior_map[(int(parts[0]), int(parts[1]), int(parts[2]))] = float(v)
            except ValueError:
                pass

    auc = cfg_dict.get("global_auc", "?")
    auc_str = f"{auc:.4f}" if isinstance(auc, float) else str(auc)

    print(
        f" ✓ [{config.name}] Rebound modelo={type(model_lgb).__name__} "
        f"(treinado: {cfg_dict.get('best_model', '?')}) AUC={auc_str} "
        f"features={len(feat_cols)} prior={'sim' if prior_map else 'nao'}"
    )

    return {
        "model_lgb": model_lgb,
        "feat_cols": feat_cols,
        "prior_map": prior_map,
        "rebound_threshold": cfg_dict.get("rebound_threshold", 0.15),
        "future_slots": cfg_dict.get("future_slots", 6),
        "delta_threshold": cfg_dict.get("delta_threshold", 0.3),
        "_city": config,
    }


# Alias publico — live_bot importa "save_history_max"
def save_history_max(history_max: dict, city_name: str | None = None) -> None:
    _save_history_max_file(history_max, city_name)


def build_features(slots_so_far: list[dict], current: dict,
                   month: int, doy: int,
                   seasonal_prior_map: dict | None = None) -> dict:
    """Constrói features canónicas. CONVENÇÃO: slots_so_far INCLUI o slot atual.
    Todas as features olham apenas para o passado — sem lookahead."""
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

    if "prev_7d_avg_max" in current:
        prev7 = current["prev_7d_avg_max"]
    else:
        _warn_once("prev7_fallback",
                   "build_features sem prev_7d_avg_max -> fallback rmax. "
                   "Passa prev7 explicito!")
        prev7 = rmax

    slot_frac = (hour + slot30 / 60.0) / 24.0

    slope_w = vals[-4:] if n >= 4 else vals
    slope = float(np.polyfit(np.arange(len(slope_w)), slope_w, 1)[0]) if len(slope_w) >= 2 else 0.0

    plateau = 1.0 if (n >= 6 and np.std(vals[-6:]) < 0.4) else 0.0
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
        "om_cloud": float(current.get("om_cloud", current.get("cloud_cover", 50)) or 50),
        "om_precip": float(current.get("om_precip", 0.0) or 0.0),
        "om_radiation": float(current.get("om_radiation", 128.0) or 128.0),
        "om_radiation_dev": float(current.get("om_radiation_dev", 0.0) or 0.0),
        "cloud_real": float(current.get("cloud_real", current.get("cloud_cover", 50)) or 50),
        "cloud_change_3h": float(current.get("cloud_change_3h", 0.0) or 0.0),
        "precip_last_3h": float(current.get("precip_last_3h", 0.0) or 0.0),
        "hours_since_last_rain": float(current.get("hours_since_last_rain", 99) or 99),
        "heat_index": float(current.get("heat_index", cur) or cur),
        "condition_windy": float(current.get("condition_windy", 0.0) or 0.0),
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
        "temp_lag_3": lag(4),
        "roll3_std": float(np.std(vals[-3:])) if n >= 3 else 0.0,
        "plateau_indicator": plateau,
        "morning_max": mmax,
        "radiation_proxy": radiation,
        "humidity_drop_1h": hum_drop_1h,
        "prev_7d_avg_max": prev7,
        "seasonal_peak_prior": _lookup_seasonal_prior(month, hour, slot30, seasonal_prior_map),
        "dewpoint_c": dewpt,
        "temp_to_dewpoint_gap": temp_to_dewpoint_gap,
        "pressure_trend_3h": pressure_trend_3h,
        "wind_south_proxy": wind_south_proxy,
        "wind_speed_kmh": wspd,
        "uv_index": uv,
        "foehn_indicator": foehn_indicator,
    }


def predict_ensemble(models: dict, slots_so_far: list[dict], current: dict,
                     month: int, doy: int, zscore_detector=None) -> dict:
    """Predição ensemble peak (LightGBM puro). Mantém assinatura legada."""
    city = models.get("_city") or get_city("munich")
    hour_min = city.hour_min if city.hour_min is not None else 6

    hour = current["hour"]
    if len(slots_so_far) < 4 or hour < hour_min:
        return {
            "p_ensemble": 0.0, "p_lgbm": 0.0, "p_xgb": None, "p_zscore": None,
            "weights": {"lgbm": 1.0, "xgb": 0.0, "zscore": 0.0},
            "components": {},
        }

    feat_cols = models["feat_cols"]
    row = build_features(slots_so_far, current, month, doy, models.get("prior_map", {}))

    X_array = np.array([[row.get(f, 0.0) for f in feat_cols]], dtype=np.float32)

    p_lgbm = _model_predict_proba(models["model_lgb"], X_array)
    p_lgbm = float(np.clip(p_lgbm, 0.0, 1.0))

    return {
        "p_ensemble": p_lgbm, "p_lgbm": p_lgbm,
        "p_xgb": None, "p_zscore": None,
        "weights": {"lgbm": 1.0, "xgb": 0.0, "zscore": 0.0},
        "components": {"lgbm": round(p_lgbm, 4)},
    }


def predict_rebound_prob(models: dict, slots_so_far: list[dict], current: dict,
                         month: int, doy: int) -> dict:
    """Prediz a probabilidade de rebound (>delta_threshold acima do running_max
    nos proximos future_slots). Gate fail-closed: slots<4 ou hora cedo -> 1.0."""
    city = models.get("_city") or get_city("munich")
    hour_min = getattr(city, "cassiopeia_hour_min",
                       city.hour_min if city.hour_min is not None else 14)

    hour = current.get("hour", 12)
    # V4.1: horas cedo/slots poucos → None (sem opinião), não 1.0 falso.
    # O caller (entry) trata None como bloqueio — semântica correta.
    if len(slots_so_far) < 4 or hour < hour_min - 1:
        return {"p_rebound": None, "p_lgbm": None}

    feat_cols = models["feat_cols"]
    row = build_features(slots_so_far, current, month, doy, models.get("prior_map", {}))

    X_array = np.array([[row.get(f, 0.0) for f in feat_cols]], dtype=np.float32)

    p_rebound = _model_predict_proba(models["model_lgb"], X_array)
    p_rebound = float(np.clip(p_rebound, 0.0, 1.0))

    return {"p_rebound": p_rebound, "p_lgbm": p_rebound}


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


def compute_prev7(history: dict, d: date, city_name: str | None = None) -> float:
    """Media dos maximos dos ultimos 7 dias. Fallback: climatologia da cidade.
    bisect exclui o proprio dia d — sem lookahead."""
    cfg = get_city(city_name) if city_name else _get_city()
    climatology = cfg.climatology if cfg.climatology else {i: 15.0 for i in range(1, 13)}

    if not history:
        return climatology.get(d.month, 15.0)
    days = sorted(history.keys())
    idx = bisect.bisect_left(days, d)
    start = max(0, idx - 32)
    recent = [dd for dd in days[start:idx] if (d - dd).days <= 7]
    if not recent:
        return climatology.get(d.month, 15.0)
    vals = [history[x] for x in recent]
    return float(np.mean(vals)) if vals else climatology.get(d.month, 15.0)


def _history_path(city_name: str | None) -> Path:
    return LOG_DIR / f"{city_name or 'munich'}_history_max.json"


def init_history_max(city_name: str | None = None) -> dict:
    """Carrega o historico de maximas diarias do disco."""
    if city_name is None:
        _warn_once("init_no_city",
                   "init_history_max sem city_name -> a usar munich. Passa sempre a cidade!")
    path = _history_path(city_name)
    if path.exists():
        try:
            return {
                date.fromisoformat(k): float(v)
                for k, v in json.loads(path.read_text()).items()
            }
        except Exception as e:
            _warn_once(f"hist_{city_name}", f"history_max ilegivel: {e}")
    return {}


def _save_history_max_file(history_max: dict, city_name: str | None = None) -> None:
    """Escrita ATÓMICA (temp+rename) — o predictor já foi truncado a 0 bytes
    uma vez (kill durante write); nunca mais."""
    path = _history_path(city_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {d.isoformat(): v for d, v in history_max.items()}
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(path)


def update_history_max(history: dict, slots_so_far: list[dict],
                       city_name: str | None = None) -> None:
    """Atualiza (in-place) a entrada do dia com o max das temperaturas.
    FIX: aceita date object OU ISO string no campo date dos slots."""
    global _last_save_times
    if not slots_so_far:
        return

    first_slot = slots_so_far[0]
    today = first_slot.get("date") if "date" in first_slot else None
    if isinstance(today, str):
        try:
            today = date.fromisoformat(str(today)[:10])
        except Exception:
            today = None
    if today is None:
        if city_name:
            today = _city_date(city_name)
        else:
            today = _city_date()

    try:
        cur_max = max(s["temp_c"] for s in slots_so_far if "temp_c" in s)
    except ValueError:
        return

    if np.isnan(cur_max) or np.isinf(cur_max):
        return
    old_max = history.get(today)
    history[today] = max(history.get(today, -999.0), float(cur_max))

    cutoff = today - timedelta(days=60)
    for d in [d for d in history.keys() if d < cutoff]:
        history.pop(d, None)

    import time
    now = time.time()
    key = city_name or "munich"
    last = _last_save_times.get(key, 0.0)
    if now - last >= 300 or old_max is None or cur_max > old_max:
        _save_history_max_file(history, city_name)
        _last_save_times[key] = now


def load_model():
    """Legado: carrega modelo PEAK para Munich."""
    result = load_models("munich")
    return result["model_lgb"], result["feat_cols"], result["prior_map"], result["monthly_threshold"]


def predict_p(model, feat_cols, slots_so_far: list[dict], current: dict,
              month: int, doy: int) -> float:
    """Legado: predicao simples (com dispatch Booster)."""
    row = build_features(slots_so_far, current, month, doy)
    X = np.array([[row.get(f, 0.0) for f in feat_cols]], dtype=np.float32)
    return _model_predict_proba(model, X)
