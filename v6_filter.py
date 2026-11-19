#!/usr/bin/env python3
"""v6_filter.py — filtro p_win do Bot B (v6 CONSISTENCY).
Carrega o F1 (quantiles + atom classifier) por cidade; calcula
P(bracket ganha) = F(X+0.5 - rmax) para bracket numérico X.
FAIL-CLOSED: sem modelos F1 -> None -> o bot B NÃO entra.
Config: V6_FILTER=1 ativa; V6_MIN_PWIN=0.82 (nominal 0.80 + margem p/ overconfidence
documentado no Gate A: mean p|subiu 0.548 vs 0.31)."""
import os
from pathlib import Path
import numpy as np
import joblib

TAUS = [0.05, 0.15, 0.25, 0.35, 0.45, 0.55, 0.65, 0.75, 0.85, 0.95]
FEATS = ["hour", "hour_sin", "hour_cos", "month", "doy_sin", "doy_cos",
         "slot_frac", "rmax", "rmax_vs_prev7", "rmax_vs_clim",
         "delta_1h", "delta_2h", "slope_2h", "plateau_hours", "spread",
         "humidity", "wind_speed_kmh", "uv_index",
         "om_cloud", "om_precip", "om_radiation"]

_cache = {}


def _load(city):
    if city in _cache:
        return _cache[city]
    d = Path(f"cities/{city}/v5_quantile_model")
    try:
        # V6-GATE: só carrega cidades com F1 promovido (gate_pass no relatório)
        import json as _json
        rpt = _json.load(open(d / "f1_report.json"))
        if not rpt.get("gate_pass"):
            _cache[city] = None
            return None
        models = joblib.load(d / "quantiles.pkl")
        clf = joblib.load(d / "atom_classifier.pkl")
        _cache[city] = (models, clf)
    except Exception:
        _cache[city] = None
    return _cache[city]


def _features(city, hour, month, doy, rmax, slots, prev7):
    from cities.config import get_city
    cfg = get_city(city)
    temps = {}
    hum = wind = uv = None
    for s in slots or []:
        t = s.get("temp_c")
        if t is None:
            continue
        h = int(s.get("hour", hour))
        temps[h] = max(temps.get(h, -99.0), float(t))
        if s.get("humidity") is not None:
            hum = float(s["humidity"])
        if s.get("wind_speed_kmh") is not None:
            wind = float(s["wind_speed_kmh"])
        if s.get("uv_index") is not None:
            uv = float(s["uv_index"])
    if not temps:
        return None
    rmin = min(temps.values())
    rmax_hour = hour
    for h in sorted(temps):
        if temps[h] >= rmax - 1e-9:
            rmax_hour = h
    prev1 = temps.get(hour - 1, rmax)
    prev2 = temps.get(hour - 2, prev1)
    clim = getattr(cfg, "climatology", None) or {}
    return {
        "hour": hour, "hour_sin": np.sin(2*np.pi*hour/24),
        "hour_cos": np.cos(2*np.pi*hour/24), "month": month,
        "doy_sin": np.sin(2*np.pi*doy/365), "doy_cos": np.cos(2*np.pi*doy/365),
        "slot_frac": hour/24.0, "rmax": rmax,
        "rmax_vs_prev7": rmax - float(prev7) if prev7 else 0.0,
        "rmax_vs_clim": rmax - clim.get(month, rmax),
        "delta_1h": rmax - prev1, "delta_2h": rmax - prev2,
        "slope_2h": prev1 - prev2, "plateau_hours": hour - rmax_hour,
        "spread": rmax - rmin,
        "humidity": hum if hum is not None else 70.0,
        "wind_speed_kmh": wind if wind is not None else 5.0,
        "uv_index": uv if uv is not None else 3.0,
        "om_cloud": 50.0, "om_precip": 0.0, "om_radiation": 128.0,
    }


def compute_p_win(city, hour, month, doy, rmax, bracket_hi, slots, prev7):
    """P(bracket oficial [., X+0.5) ganha) ou None (fail-closed).

    bracket_hi é o temp_hi do mercado (X); o limite oficial superior é X+0.5.
    """
    bracket_hi = float(bracket_hi) if bracket_hi is not None else 0.0
    if bracket_hi >= 99:
        return None  # "or above": precisa do limite inferior; fail-closed
    bracket_upper = bracket_hi + 0.5
    loaded = _load(city)
    if loaded is None:
        return None
    models, clf = loaded
    fx = _features(city, hour, month, doy, rmax, slots, prev7)
    if fx is None:
        return None
    try:
        X = np.array([[fx[k] for k in FEATS]], dtype=np.float32)
        p_pos = float(clf.predict_proba(X)[0, 1])
        qs = np.sort(np.array([float(models[str(t)].predict(X)[0]) for t in TAUS]))
        qs = np.maximum(qs, 0.0)

        def F(x):
            """P(push <= x); push>=0 por definição (day_max>=rmax)."""
            if x < 0:
                return 0.0
            f2 = float(np.interp(x, qs, TAUS))
            return (1.0 - p_pos) + p_pos * f2

        return F(float(bracket_upper) - float(rmax))
    except Exception as e:
        print(f"[v6_filter] ERRO {city}: {e}")
        return None


def gate(city, hour, month, doy, rmax, bracket_hi, slots, prev7, min_pwin=None):
    """True = pode entrar. Sem modelo/gate reprovado -> False (fail-closed duplo)."""
    if not os.environ.get("V6_FILTER"):
        return True                          # bot A: filtro inativo
    min_pwin = float(min_pwin or os.environ.get("V6_MIN_PWIN", 0.82))
    p = compute_p_win(city, hour, month, doy, rmax, bracket_hi, slots, prev7)
    if p is None:
        print(f"[v6] {city}: sem F1/gate reprovado -> BLOQUEIO (fail-closed)")
        return False
    ok = p >= min_pwin
    # contador persistido (o monitor lê daqui mesmo sem linhas visíveis):
    try:
        from pathlib import Path as _P
        import json as _json, time as _time
        # §88: stats seguem o log_dir do processo (D também gateia o braço
        # colecionador — sem isto os julgamentos do D poluíam o ficheiro do B)
        sp = _P(os.environ.get("CASS_LOG_DIR", "live_bot_logs_v6")) / "v6_gate_stats.json"
        st = _json.load(open(sp)) if sp.exists() else {"judged": 0, "passed": 0,
                                                       "p_win_sum": 0.0, "by_city": {}}
        st["judged"] += 1
        st["passed"] += int(ok)
        st["p_win_sum"] += p
        st.setdefault("by_city", {}).setdefault(city, 0)
        st["by_city"][city] += 1
        st["last"] = {"city": city, "hour": hour, "rmax": rmax, "hi": bracket_hi,
                      "p_win": round(p, 4), "pass": ok, "ts": _time.time()}
        sp.parent.mkdir(parents=True, exist_ok=True)
        tmp = sp.with_suffix(".tmp")
        tmp.write_text(_json.dumps(st, indent=1))
        tmp.replace(sp)
    except Exception as _e:
        print(f"[v6] stats falhou (inofensivo): {_e}")
    print(f"[v6] {city} {hour}h rmax={rmax:.1f} hi={bracket_hi:.1f}: "
          f"p_win={p*100:.1f}% {'✅ PASS' if ok else '⛔ corte'} (min {min_pwin})")
    return ok


# ════════════════════════════════════════════════════════
# D-v5 (§87): segmentação de braços por faixa de ask
# ════════════════════════════════════════════════════════
def arm_decision(ask: float, v5_max: float = 0.0, f1_min: float = 0.0) -> str:
    """Decide qual braço aplica a uma entrada candidata.

    'v5'  → ask <= v5_max: regra v5 pura (bandas/horas/threshold já validados
            a montante pelo SingleEntry) — SEM gate F1.
    'dead'→ zona morta v5_max < ask < f1_min — nunca compra.
    'f1'  → ask >= f1_min (ou sem segmentação configurada): gate F1 normal.

    Sem v5_max/f1_min configurados → 'f1' sempre (back-compat total: o
    comportamento de A/B/D antes do §87 fica byte-a-byte igual).
    """
    if v5_max and ask <= v5_max:
        return "v5"
    if f1_min and ask < f1_min:
        return "dead"
    return "f1"
