"""
cassiopeia_backtester.py v3.3
=============================
Backtester Cassiopeia com:
  - P&L assimétrico estilo Polymarket (não binário +1/-1)
  - breakeven_hit_rate inclui fees; edge_vs_price = hit_rate - breakeven
  - TZ-aware por cidade (--assume-tz utc|local)
  - warm-up de 7 dias (prev7 incompleto -> sem filtro outlier -> não entra)
  - FAIL-CLOSED: sem modelo ML ou sem histórico prev7 -> zero entradas
  - [ML ERROR] suprimido após a 1ª ocorrência por processo
  - Guards de NaN/valores inválidos; loop por groupby (rápido p/ grids)
  - §95 (8/11, auditoria): fee default = Polymarket real 0.05·p·(1-p);
    §107: geometria oficial = round_half_up(rmax), [X-0.5, X+0.5);
    entrada sem gate temp==rmax (alinha com o live); bracket_half deixa
    de influenciar resultados no modo cassiopeia (era parâmetro morto).
"""
from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import argparse
import math
import numpy as np
from resolution_rules import round_half_up
import pandas as pd
from datetime import timedelta
from zoneinfo import ZoneInfo

try:
    from cassiopeia_params import resolve_params
except ImportError:
    resolve_params = None

try:
    from cassiopeia_predictor import load_models_rebound, predict_rebound_prob
    HAS_PREDICTOR = True
except ImportError as _e:
    HAS_PREDICTOR = False
    PREDICTOR_ERROR = str(_e)

try:
    from predictor import compute_prev7
except ImportError:
    compute_prev7 = None

# ── Constantes ──
REBOUND_PROB_THRESHOLD = 0.35
MIN_SPREAD_C = 0.5
MAX_OUTLIER_DELTA = 3.0
MIN_HOUR_ENTRY = 13
MAX_HOUR_ENTRY = 19
BRACKET_HALF_WIDTH = 0.5
ENTRY_PRICE_DEFAULT = 0.60   # preço assumido do YES — ajustar ao teu regime!
# §95 (8/11): fee default passa a ser o modelo REAL Polymarket Weather
# (0.05 × p × (1-p) por share, cobrada na compra). fee_rate explícito
# (ex.: --fee-rate 0.009) mantém o modelo linear legado como override.
FEE_RATE_DEFAULT = None
WARMUP_DAYS = 7


def _taker_fee(price: float, fee_rate) -> float:
    """Fee por share na compra taker. None -> fórmula real Weather."""
    if fee_rate is None:
        return 0.05 * price * (1.0 - price)
    return float(fee_rate) * price


# ── Helpers de valor seguro ──
def _safe_float(v, default=None):
    """float() tolerante: NaN/None/string inválida -> default."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    return default if np.isnan(f) else f


# (nome_canonico, default_se_ausente, nomes_alternativos_no_csv)
_SLOT_SPEC = [
    ("humidity",      70.0,  ("humidity", "humidity_pct")),
    ("cloud_cover",   50.0,  ("cloud_cover", "sky_cover")),
    ("dewpoint_c",    None,  ("dewpoint_c", "dewpt_c")),          # None -> temp-10
    ("pressure_hpa",  1013.0,("pressure_hpa", "pressure")),
    ("wind_dir_deg",  0.0,   ("wind_dir_deg", "wind_dir")),
    ("wind_speed_kmh",5.0,   ("wind_speed_kmh", "wind_speed")),
    ("wind_gust_kmh", 8.0,   ("wind_gust_kmh", "wind_gust")),
    ("uv_index",      3.0,   ("uv_index", "uv")),
]


def _pick_slot_value(tup, names, default, temp):
    for n in names:
        f = _safe_float(getattr(tup, n, None), None)
        if f is not None:
            return f
    return (temp - 10.0) if default is None else default


# ── Localização de CSV ──
def _find_csv(city: str, csv_path: str | None = None) -> Path:
    if csv_path:
        p = Path(csv_path)
        if p.exists():
            return p
    for c in [Path(f"historic/{city}.csv"),
              Path(f"cities/{city}/weather_{city}.csv"),
              Path(f"data/{city}_2024.csv"),
              Path(f"data/{city}.csv")]:
        if c.exists():
            return c
    return Path(f"historic/{city}.csv")


def _city_timezone(city: str) -> str | None:
    try:
        from cities.config import get_city
        cfg = get_city(city)
        return getattr(cfg, "timezone", None)
    except Exception:
        return None


def load_csv(city: str, csv_path: str | None = None, assume_tz: str = "utc") -> pd.DataFrame:
    """
    assume_tz: 'utc'   -> timestamps naive sao UTC (canonical: coluna timestamp_utc
                          do pipeline train/weather_v3); converte p/ hora local da cidade.
               'local' -> timestamps naive ja sao hora local da cidade.
    Em ambos os casos, o relógio final fica na hora LOCAL da cidade.
    """
    path = _find_csv(city, csv_path)
    if not path.exists():
        raise FileNotFoundError(f"CSV nao encontrado: {path}")
    df = pd.read_csv(path, low_memory=False)

    ts_col = next((c for c in ["timestamp", "timestamp_utc", "datetime", "date"]
                   if c in df.columns), None)
    if ts_col is None:
        raise ValueError(
            f"{path}: nenhuma coluna temporal encontrada "
            f"(procurei: timestamp, timestamp_utc, datetime, date)")

    raw = df[ts_col]
    if pd.api.types.is_numeric_dtype(raw):
        unit = "ms" if float(pd.Series(raw).dropna().median()) > 1e11 else "s"
        df["timestamp"] = pd.to_datetime(raw, unit=unit, errors="coerce")
    else:
        df["timestamp"] = pd.to_datetime(raw, errors="coerce")

    if df["timestamp"].notna().sum() == 0:
        raise ValueError(f"{path}: todas as datas invalidas")

    # ── Normalização de fuso ──
    try:
        tz_city = _city_timezone(city)
        if df["timestamp"].dt.tz is None:
            if assume_tz == "local":
                target = ZoneInfo(tz_city or "UTC")
                # DST: 2h ambiguas/ano -> NaT e descartadas (janela 13-19h nao afetada)
                df["timestamp"] = df["timestamp"].dt.tz_localize(
                    target, ambiguous="NaT", nonexistent="shift_forward")
            else:  # utc
                df["timestamp"] = df["timestamp"].dt.tz_localize("UTC")
        if tz_city:
            df["timestamp"] = (df["timestamp"]
                               .dt.tz_convert(ZoneInfo(tz_city))
                               .dt.tz_localize(None))
    except Exception as e:
        sys.stderr.write(f"[AVISO TZ] {e} -> a usar timestamps como vieram\n")

    df = df[df["timestamp"].notna()]
    return df.sort_values("timestamp").reset_index(drop=True)


def _get_temp_col(df):
    for c in ["temp_c", "temp", "temperature", "temperature_c"]:
        if c in df.columns:
            return c
    raise KeyError("Coluna de temperatura nao encontrada")


def _compute_prev7(history: dict, d, city_name: str):
    if compute_prev7:
        v = compute_prev7(history, d, city_name)
        return float(v) if v is not None else None
    vals = [history.get(d - timedelta(days=i)) for i in range(1, 8)]
    vals = [v for v in vals if v is not None]
    return float(np.mean(vals)) if vals else None


# ── ML com fail-closed + erro suprimido apos 1a vez ──
_ML_ERROR_SHOWN = False


def _predict_rebound_ml(models, slots_so_far, current, month, doy):
    """Retorna None se modelo indisponivel/erro (fail-closed)."""
    global _ML_ERROR_SHOWN
    if not HAS_PREDICTOR or models is None:
        return None
    try:
        result = predict_rebound_prob(models, slots_so_far, current, month, doy)
        p = result.get("p_rebound")
        # V4.1: predictor devolve None ("sem opinião") em horas cedo / poucos
        # slots — é um bloqueio legítimo (== live), não um erro.
        return None if p is None else float(p)
    except Exception as e:
        if not _ML_ERROR_SHOWN:
            sys.stderr.write(f"[ML ERROR] {e} (seguintes suprimidos neste processo)\n")
            _ML_ERROR_SHOWN = True
        return None


# ── Simulação de um dia ──
def backtest_day(df_day, params, models=None, city_name="unknown",
                 verbose=False, history_max=None, use_ml=True):
    threshold    = float(params.get("threshold") or REBOUND_PROB_THRESHOLD)
    min_spread   = float(params.get("min_spread") or MIN_SPREAD_C)
    bracket_half = float(params.get("bracket_half") or BRACKET_HALF_WIDTH)
    start_hour   = int(params.get("start_hour") or MIN_HOUR_ENTRY)
    end_hour     = int(params.get("end_hour") or MAX_HOUR_ENTRY)
    outlier_cap  = float(params.get("outlier_cap") or MAX_OUTLIER_DELTA)
    entry_price  = float(params.get("entry_price", ENTRY_PRICE_DEFAULT))
    fee_rate     = params.get("fee_rate", FEE_RATE_DEFAULT)   # None = weather real
    # ── MODO STAIRS (One More Push) — aditivo; cassiopeia intocado ──
    mode                = str(params.get("mode", "cassiopeia")).lower()
    stairs_threshold    = float(params.get("stairs_threshold", 0.60))
    stairs_entry_price  = float(params.get("stairs_entry_price", 0.30))
    stairs_gap_max      = float(params.get("stairs_gap_max", 0.30))

    if not (0.01 <= entry_price <= 0.99):
        raise ValueError(f"entry_price invalido: {entry_price}")

    if "timestamp" not in df_day.columns:
        return []
    temp_col = _get_temp_col(df_day)
    df_day = df_day.sort_values("timestamp")

    if "hour" not in df_day.columns:
        df_day = df_day.assign(hour=df_day["timestamp"].dt.hour)

    first_val = df_day["timestamp"].iloc[0]
    if pd.isna(first_val):
        return []
    day_date = first_val.date()
    month, doy = int(first_val.month), int(first_val.dayofyear)

    trades = []
    entered = False
    if history_max is None:
        history_max = {}

    prev7 = _compute_prev7(history_max, day_date, city_name)

    rmax, rmin = -999.0, 999.0
    slots_so_far = []

    for tup in df_day.itertuples(index=False):
        temp = _safe_float(getattr(tup, temp_col), None)
        if temp is None:
            continue
        hour = int(_safe_float(getattr(tup, "hour", 12), 12))
        slot30 = int(_safe_float(getattr(tup, "slot30", 0), 0))

        rmax = max(rmax, temp)
        rmin = min(rmin, temp)

        slot = {"hour": hour, "slot30": slot30, "temp_c": temp}
        for canon, dv, names in _SLOT_SPEC:
            slot[canon] = _pick_slot_value(tup, names, dv, temp)
        slots_so_far.append(slot)

        if entered:
            continue
        if not (start_hour <= hour <= end_hour):
            continue

        if mode == "stairs":
            # ONE MORE PUSH: aposta no degrau seguinte (round_half_up(rmax)+1)
            # de um plateau. Gap pequeno = o push >=delta_threshold do modelo
            # chega para ativar o degrau. Sem gates "no rmax"/spread — o sinal
            # e o push previsto, nao o topo.
            strike = float(round_half_up(rmax)) + 1.0
            gap_to_strike = strike - rmax
            if gap_to_strike > stairs_gap_max:
                continue
        else:
            # §95-5: gate "temp == rmax" REMOVIDO — o live entra em qualquer
            # tick da janela com p < threshold (também após dips). O gate
            # antigo fazia o backtest medir uma estratégia que não corre live.
            if (rmax - rmin) < min_spread:
                continue
        if prev7 is None:
            continue                       # fail-closed: sem historico nao entra
        if rmax > prev7 + outlier_cap:
            continue

        if use_ml:
            p = _predict_rebound_ml(models, slots_so_far,
                                    {**slots_so_far[-1], "prev_7d_avg_max": prev7},
                                    month, doy)
            if p is None:                  # fail-closed: modelo ausente bloqueia
                continue
            if mode == "stairs":
                if p < stairs_threshold:   # OMP: so entra com push previsto FORTE
                    continue
            elif p >= threshold:
                continue
        elif mode == "stairs":
            continue                       # stairs sem ML = sem sinal (fail-closed)

        if mode == "stairs":
            trades.append({
                "timestamp": pd.Timestamp(day_date),
                "hour": hour, "entry_temp": temp, "rmax": rmax,
                "strike": strike,
                "bracket_low": strike,
                "bracket_high": strike,        # bracket inteira [strike, strike+1)
                "entry_price": stairs_entry_price,
            })
        else:
            # Regra oficial: bracket = round_half_up(rmax), com
            # [X-0.5, X+0.5). Ex.: rmax 14.7 -> bracket 15 -> [14.5, 15.5).
            target = float(round_half_up(rmax))
            trades.append({
                "timestamp": pd.Timestamp(day_date),
                "hour": hour, "entry_temp": temp, "rmax": rmax,
                "bracket_low": target - 0.5,
                "bracket_high": target + 0.5,
                "entry_price": entry_price,
            })
        entered = True

    # Resultado APENAS no fim do dia — sem lookahead
    day_max = float(df_day[temp_col].dropna().max())
    for tr in trades:
        tr["day_max"] = day_max
        if "strike" in tr:
            tr["hit"] = day_max >= tr["strike"]    # degrau ativado
        else:
            # bracket half-open [lo, hi): 15.0 resolve na bracket dos 15
            tr["hit"] = tr["bracket_low"] <= day_max < tr["bracket_high"]
        p = tr["entry_price"]
        fee = _taker_fee(p, fee_rate)
        tr["pnl"] = ((1.0 - p) - fee) if tr["hit"] else (-p - fee)
        tr["return_pct"] = tr["pnl"] / p

    history_max[day_date] = day_max
    return trades


# ── Backtest multi-dia ──
def run_backtest(city: str, csv_path: str | None = None, verbose=False,
                 _df: pd.DataFrame | None = None, _models=None,
                 use_ml: bool = True, assume_tz: str = "utc", **kwargs) -> dict:
    def _get(k1, k2, default):
        v = kwargs.get(k1, kwargs.get(k2))
        return default if v is None else v

    params = {
        "threshold":    _get("threshold",    "rebound_threshold", REBOUND_PROB_THRESHOLD),
        "min_spread":   _get("min_spread",   "spread",            MIN_SPREAD_C),
        "bracket_half": _get("bracket_half", "bracket",           BRACKET_HALF_WIDTH),
        "start_hour":   _get("start_hour",   "min_hour",          MIN_HOUR_ENTRY),
        "end_hour":     _get("end_hour",     "max_hour",          MAX_HOUR_ENTRY),
        "outlier_cap":  _get("outlier_cap",  "max_outlier",       MAX_OUTLIER_DELTA),
        "entry_price":  _get("entry_price",  "price",             ENTRY_PRICE_DEFAULT),
        "fee_rate":     _get("fee_rate",     "fees",              FEE_RATE_DEFAULT),
    }
    # ── modo stairs (aditivo) ──
    params["mode"] = str(kwargs.get("mode", "cassiopeia")).lower()
    params["stairs_threshold"]   = _get("stairs_threshold",   "stairs_threshold",   0.60)
    params["stairs_entry_price"] = _get("stairs_entry_price", "stairs_entry_price", 0.30)
    params["stairs_gap_max"]     = _get("stairs_gap_max",     "stairs_gap_max",     0.30)
    if params["mode"] == "stairs":
        if kwargs.get("start_hour") is None and kwargs.get("min_hour") is None:
            params["start_hour"] = 11          # janela convectiva por defeito
        if kwargs.get("end_hour") is None and kwargs.get("max_hour") is None:
            params["end_hour"] = 16

    models = _models
    model_dir = kwargs.get("model_dir")
    if models is None and HAS_PREDICTOR and use_ml:
        try:
            models = load_models_rebound(city, model_dir=Path(model_dir) if model_dir else None)
        except FileNotFoundError:
            sys.stderr.write(
                f"[AVISO] Modelo rebound ausente p/ {city} -> FAIL-CLOSED "
                f"(zero entradas). Use --no-ml p/ heuristica pura.\n")
            # models permanece None e use_ml True -> backtest_day bloqueia tudo

    if _df is not None:
        df = _df
    else:
        df = load_csv(city, csv_path, assume_tz=assume_tz)

    if "timestamp" not in df.columns:
        raise ValueError("df sem coluna 'timestamp' — impossivel agrupar por dia")

    # Janela temporal opcional: end_date corta o fim; start_date só conta
    # trades a partir dessa data, mas mantém ~10 dias de contexto antes
    # (prev7/history_max ficam corretos no início da janela).
    sd_raw = kwargs.get("start_date")
    sd = pd.to_datetime(sd_raw).date() if sd_raw else None
    ed_raw = kwargs.get("end_date")
    if ed_raw:
        df = df[df["timestamp"].dt.date <= pd.to_datetime(ed_raw).date()]
    if sd:
        df = df[df["timestamp"].dt.date >= sd - timedelta(days=10)]
    # Override incondicional: coluna 'date' do CSV e string DD/MM/YYYY e a sua
    # ordenacao lexicografica embaralhava a ordem temporal dos dias (prev7 caotico,
    # warm-up errado, holdout OOS sem sentido). Reconstruir do timestamp convertido.
    df = df.assign(date=pd.to_datetime(df["timestamp"]).dt.date)
    if "hour" not in df.columns:
        df = df.assign(hour=pd.to_datetime(df["timestamp"]).dt.hour)

    all_trades, days_entered, window_days = [], 0, 0
    history_max = {}
    grouped = df.groupby("date", sort=True)
    days_tested = grouped.ngroups

    for idx, (date, day_df) in enumerate(grouped):
        trades = backtest_day(day_df, params, models=models, city_name=city,
                              verbose=verbose, history_max=history_max,
                              use_ml=use_ml)   # fail-closed se models None
        if idx < WARMUP_DAYS:
            continue
        if sd is not None and date < sd:
            continue
        window_days += 1
        if trades:
            days_entered += 1
        all_trades.extend(trades)

    eff_days = window_days if sd is not None else max(0, days_tested - WARMUP_DAYS)
    base = {"entries": 0, "hits": 0, "hit_rate": 0.0, "pnl": 0.0,
            "pnl_per_trade": 0.0, "sharpe": 0.0, "avg_entry_hour": 0.0,
            "days_tested": eff_days, "days_entered": 0}
    if not all_trades:
        return {**base, "total_staked": 0.0, "roi": 0.0, "max_drawdown": 0.0,
                "edge_vs_price": 0.0, "breakeven_hit_rate": 0.0}

    tdf = pd.DataFrame(all_trades)
    n = len(tdf)
    hits = int(tdf["hit"].sum())
    staked = float(tdf["entry_price"].sum())
    total_pnl = float(tdf["pnl"].sum())
    rets = tdf["return_pct"]

    dd_cum = tdf["pnl"].cumsum()
    max_dd = float((dd_cum - dd_cum.cummax()).min())

    fee_rate = params["fee_rate"]
    # breakeven com fee modelada (fee em ambos os desfechos):
    # h*(1-p-f) = (1-h)*(p+f)  =>  h = p + f
    fees = tdf["entry_price"].apply(lambda p: _taker_fee(p, fee_rate))
    breakeven = float((tdf["entry_price"] + fees).mean())

    return {
        "entries": n, "hits": hits, "hit_rate": hits / n,
        "pnl": total_pnl, "pnl_per_trade": total_pnl / n,
        "sharpe": float(rets.mean() / (rets.std() + 1e-9)),
        "avg_entry_hour": float(tdf["hour"].mean()),
        "days_tested": eff_days,
        "days_entered": days_entered,
        "total_staked": staked,
        "roi": total_pnl / staked if staked else 0.0,
        "max_drawdown": max_dd,
        "breakeven_hit_rate": breakeven,
        "edge_vs_price": (hits / n) - breakeven,
    }


# ── CLI ──
def main():
    parser = argparse.ArgumentParser(description="Cassiopeia Backtester v3.2")
    parser.add_argument("--city", required=True)
    parser.add_argument("--csv")
    parser.add_argument("--assume-tz", default="utc", choices=["utc", "local"],
                        help="Interpretacao dos timestamps naive do CSV "
                             "(default utc = pipeline timestamp_utc; "
                             "'local' se o CSV foi gravado em hora local)")
    parser.add_argument("--threshold", type=float)
    parser.add_argument("--spread", type=float, dest="min_spread")
    parser.add_argument("--bracket-half", type=float)
    parser.add_argument("--start-hour", type=int)
    parser.add_argument("--end-hour", type=int)
    parser.add_argument("--outlier-cap", type=float)
    parser.add_argument("--entry-price", type=float)
    parser.add_argument("--fee-rate", type=float, dest="fee_rate")
    parser.add_argument("--auto-params", action="store_true")
    parser.add_argument("--mode", default="cassiopeia", choices=["cassiopeia", "stairs"])
    parser.add_argument("--stairs-threshold", type=float)
    parser.add_argument("--stairs-entry-price", type=float)
    parser.add_argument("--stairs-gap-max", type=float)
    parser.add_argument("--no-ml", action="store_true")
    parser.add_argument("--model-dir", default=None,
                        help="Dir alternativa do modelo rebound "
                             "(default: cities/<city>/cassiopeia_rebound_model)")
    parser.add_argument("--start-date", default=None,
                        help="Só conta trades a partir desta data (YYYY-MM-DD)")
    parser.add_argument("--end-date", default=None,
                        help="Ignora dados depois desta data (YYYY-MM-DD)")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    city = args.city.lower().strip()
    overrides = {k: v for k, v in {
        "threshold": args.threshold, "min_spread": args.min_spread,
        "bracket_half": args.bracket_half, "start_hour": args.start_hour,
        "end_hour": args.end_hour, "outlier_cap": args.outlier_cap,
        "entry_price": args.entry_price, "fee_rate": args.fee_rate,
        "mode": args.mode, "stairs_threshold": args.stairs_threshold,
        "stairs_entry_price": args.stairs_entry_price,
        "stairs_gap_max": args.stairs_gap_max,
    }.items() if v is not None}

    if args.auto_params and resolve_params is not None:
        params = resolve_params(city, **overrides)
        print("📡 Parametros do active config.")
    else:
        params = overrides
        print("⚙️  Parametros manuais / defaults.")

    results = run_backtest(city, verbose=args.verbose,
                           use_ml=not args.no_ml,
                           assume_tz=args.assume_tz,
                           model_dir=args.model_dir,
                           start_date=args.start_date,
                           end_date=args.end_date, **params)

    print(f"\n{'='*60}\nBACKTEST CASSIOPEIA — {city.upper()}\n{'='*60}")
    print(f"Dias testados      : {results['days_tested']}")
    print(f"Dias com entrada   : {results['days_entered']}")
    print(f"Trades / Hits      : {results['entries']} / {results['hits']}")
    print(f"Hit rate           : {results['hit_rate']:.2%}")
    print(f"Breakeven hit rate : {results['breakeven_hit_rate']:.3f}  (inclui fee)")
    edge = results["edge_vs_price"]
    verdict = "LUCRATIVO (EV>0)" if edge > 0 else "PERDEDOR (EV<0)"
    print(f"EDGE vs breakeven  : {edge:+.2%}   <- {verdict}")
    print(f"Total P&L (USDC)   : {results['pnl']:+.3f}")
    print(f"ROI s/ capital     : {results['roi']:+.2%}")
    print(f"Max drawdown       : {results['max_drawdown']:+.3f}")
    print(f"Hora media entrada : {results['avg_entry_hour']:.1f}h")
    print("=" * 60)


if __name__ == "__main__":
    main()