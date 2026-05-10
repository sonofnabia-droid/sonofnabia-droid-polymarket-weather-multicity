"""
backtester.py
=============
Backtester multi-cidade (refactor do munich_backtester.py para multi-city).

Inclui:
  • PnL realista Polymarket: (1/ask - 1) por $, não 0.95 fixo
  • Outcome real: "correct" = bracket cobre peak_temp
  • RESUMO TOTAL acumulado
  • Sharpe/Sortino reais a partir de retornos diários
  • Estatísticas sazonais (winter/spring/summer/autumn)
  • Lag por parcela em horas (diagnóstico de timing)
  • prev_7d_avg_max real por dia
  • SimulatedMarket com ruído de mercado
  • Save de resumo JSON em backtest_results/

Uso:
    python backtester.py --city munich --mode single --years 5
    python backtester.py --city dallas --mode single --years 3 --ordertype percent --bet 2
    python backtester.py --city ankara --mode single --years 5 --noise 0.0   # determinístico
"""

import argparse
import json
import warnings
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

# Suprimir warnings do sklearn sobre feature names ausentes em arrays
# (model treinado com DataFrame, inference com array — funciona, é só ruído visual)
warnings.filterwarnings("ignore", category=UserWarning,
                        message=".*X does not have valid feature names.*")

from rich.console import Console
from rich.progress import Progress, BarColumn, TextColumn, TimeElapsedColumn, TimeRemainingColumn
from rich.table import Table
from rich import box as rich_box

from cities.config import CityConfig, get_city, CITIES
from predictor import set_city, load_models, predict_ensemble
from modules.single_entry import SingleEntry

_console = Console(force_terminal=True)
OUTPUT_DIR = Path("backtest_results")
OUTPUT_DIR.mkdir(exist_ok=True)


# ── Constantes genéricas (independentes de cidade) ──
SEASONS = {
    "winter": [12, 1, 2], "spring": [3, 4, 5],
    "summer": [6, 7, 8],  "autumn": [9, 10, 11],
}


def ceil_slot(hour: int, minute: int) -> tuple[int, int]:
    """Converte (hour, minute) para slot 30min (truncar para CIMA)."""
    if minute < 30:
        return (hour, 30)
    else:
        return (hour + 1, 0)


# ══════════════════════════════════════════════════════
#  SIMULATED MARKET — baseado em climatologia + ruído
# ══════════════════════════════════════════════════════
class SimulatedMarket:
    """
    Simula asks dos brackets Polymarket de forma climatologicamente realista.

    Princípio base (v2 — 2026-04):
    --------------------------------
    Um trader racional no mercado precifica principalmente com base em:
      1. **A hora do dia** (quanto mais tarde, mais certeza sobre o rmax)
      2. **A distância entre temperatura candidata e running_max**

    A opinião do modelo (p_ensemble) tem impacto secundário, porque o
    mercado tem acesso à mesma informação climatológica. Logo o nosso
    modelo só "bate" o mercado quando antecipa um pico antes de ser
    óbvio climatologicamente.

    Isto corrige o bug da v1, onde o ask era quase linear em p_ensemble
    e thresholds baixos davam asks artificialmente baratos (permitindo
    ROI absurdo de +300% a thr=0.35).

    Parâmetros
    ----------
    noise_std : float
        Desvio-padrão do ruído gaussiano no ask (default 0.05 = 5¢).
        Simula informação que o mercado tem e o modelo não (forecasts,
        sentiment, liquidez). Passa 0.0 para backtest determinístico.
    seed : int
        Seed para reprodutibilidade do ruído.
    """
    # Janela do dia em que assumimos que o pico pode ocorrer
    DAY_HOUR_START = 6    # antes das 6h praticamente não há informação
    DAY_HOUR_END   = 20   # depois das 20h o dia está basicamente fechado

    # Range de brackets expandido (-5°C a 44°C) para cobrir clima real de Munich.
    # Antes era 5..39 que falhava em dias frios de inverno (rmax < 5°C) e em
    # dias muito quentes de verão (rmax > 39°C), causando matches inválidos.
    def __init__(self, temp_range=None, noise_std: float = 0.05, seed: int = 42):
        # temp_range deve vir da cidade — fallback genérico amplo
        if temp_range is None:
            temp_range = range(-15, 50)
        self.temp_range = temp_range
        self.noise_std = noise_std
        self._rng = np.random.default_rng(seed)

    def _climatological_ask(self, dist: int, hour: int, temp_below_rmax: bool) -> float:
        """
        Preço "climatologicamente justo" do bracket, função de:
          - `dist`: distância em °C entre este bracket e o running_max
          - `hour`: hora do dia
          - `temp_below_rmax`: True se este bracket < running_max
                               (muito improvável — a temperatura baixou?)

        Lógica:
          - Às 6h, o running_max ainda é muito informativo pouco,
            todos os brackets plausíveis têm asks parecidos (20-30¢).
          - Às 20h, o running_max é quase definitivo. Bracket central
            tem 85-90¢, bracket ±1 tem 5-10¢.

        Factor de confiança do mercado em [0, 1]:
          0.0 às 6h → 1.0 às 20h.
        """
        # Clamp a hora ao intervalo do dia
        h = max(self.DAY_HOUR_START, min(self.DAY_HOUR_END, hour))
        confidence = (h - self.DAY_HOUR_START) / (self.DAY_HOUR_END - self.DAY_HOUR_START)

        # Se o bracket está ABAIXO do running_max, é "quase impossível" vencer
        # (seria preciso a temp descer abaixo do máximo já atingido — Polymarket
        # é sobre o MÁXIMO do dia, não fecho). Polymarket precifica-os quase zero.
        if temp_below_rmax:
            # Começa a 10¢ (manhã, com alguma incerteza em brackets perto do rmax),
            # cai para ~2¢ à tarde
            base = 0.10 * (1 - confidence) + 0.02 * confidence
            # Mas se for MUITO abaixo (dist > 2), é sempre zero-ish
            if dist > 2:
                base = 0.02
            return base

        # Bracket ACIMA ou IGUAL ao running_max — pode vencer se temp subir
        if dist == 0:
            # Bracket central:
            # - manhã cedo: muita competição com brackets vizinhos → 30-45¢
            # - tarde: consolidado → 80-92¢
            ask = 0.35 + 0.55 * confidence
        elif dist == 1:
            # Precisa de subir 1°C. Plausível de manhã, improvável à tarde.
            ask = 0.30 * (1 - confidence) + 0.07 * confidence
        elif dist == 2:
            # Precisa de subir 2°C.
            ask = 0.18 * (1 - confidence) + 0.03 * confidence
        elif dist == 3:
            ask = 0.08 * (1 - confidence) + 0.02 * confidence
        else:
            # Brackets muito afastados — quase zero liquidez/probabilidade
            ask = max(0.02, 0.05 - 0.01 * dist)

        return ask

    def get_brackets(self, p_ensemble: float, running_max: float, hour: int) -> list[dict]:
        if np.isnan(running_max) or np.isinf(running_max):
            running_max = 15.0
        brackets = []
        rmax_int = int(round(running_max))

        for temp in self.temp_range:
            signed_dist = temp - rmax_int    # positivo se bracket acima do rmax
            dist = abs(signed_dist)
            temp_below_rmax = signed_dist < 0

            # 1. Baseline climatológica (DOMINA o preço)
            climatological = self._climatological_ask(dist, hour, temp_below_rmax)

            # 2. Nudge pelo modelo (pequeno — máx ±5¢ de efeito)
            # O modelo só influencia o bracket central e vizinhos próximos.
            # Nudge: quando p_ensemble é alta, o trader "concorda" e puxa o preço
            # para cima; quando é baixa, puxa para baixo. Mas nunca muito.
            if dist <= 1 and not temp_below_rmax:
                # Centrado em 0.5; desvio de p_ensemble vs 0.5 multiplicado por 0.10
                model_nudge = (p_ensemble - 0.5) * 0.10
            else:
                model_nudge = 0.0

            ask = climatological + model_nudge

            # 3. Ruído gaussiano independente do modelo
            if self.noise_std > 0:
                # Ruído maior em brackets afastados (menos liquidez)
                noise_scale = self.noise_std * (1.0 + 0.05 * dist)
                ask += self._rng.normal(0, noise_scale)

            # Liquidez zero em brackets muito afastados
            if dist > 5:
                ask = 0.01
                bid = 0.0
            else:
                ask = float(np.clip(ask, 0.02, 0.97))
                # Spread: mais apertado no bracket central, mais largo nas pontas
                spread_factor = 0.05 + dist * 0.015
                bid = ask * (1 - spread_factor)

            is_last  = (temp == self.temp_range[-1])
            is_first = (temp == self.temp_range[0])
            if is_last:
                label, lo, hi = f"{temp}°C or higher", float(temp), 99.0
            elif is_first:
                label, lo, hi = f"{temp}°C or lower", -99.0, float(temp)
            else:
                label, lo, hi = f"{temp}°C", float(temp), float(temp)

            brackets.append({
                "label": label,
                "ask": round(ask, 4),
                "price": round(ask, 4),
                "bid": round(bid, 4),
                "temp_lo": lo,
                "temp_hi": hi,
            })
        return brackets


# ══════════════════════════════════════════════════════
#  STATS DATACLASS
# ══════════════════════════════════════════════════════
@dataclass
class BacktestStats:
    total_days:    int   = 0
    total_trades:  int   = 0
    wins:          int   = 0
    losses:        int   = 0

    correct_pct:   float = 0.0
    premature_pct: float = 0.0
    missed_pct:    float = 0.0

    lag_mean_h:    Optional[float] = None
    lag_median_h:  Optional[float] = None
    lag_le1h_pct:  float = 0.0
    lag_le2h_pct:  float = 0.0

    parcel1_pct:   float = 0.0
    parcel2_pct:   float = 0.0
    parcel3_pct:   float = 0.0
    avg_n_parcels: float = 0.0
    avg_invested:  float = 0.0
    total_pnl:     float = 0.0
    total_return_pct: float = 0.0
    sharpe:        float = 0.0
    sortino:       float = 0.0

    seasonal_stats: dict = field(default_factory=dict)


# ══════════════════════════════════════════════════════
#  DATA LOADING
# ══════════════════════════════════════════════════════
def load_data(csv_path: Path, city: CityConfig) -> pd.DataFrame:
    """Carrega e normaliza o CSV histórico de uma cidade."""
    if not csv_path.exists():
        raise FileNotFoundError(f"{csv_path} não encontrado")

    with open(csv_path, "r", encoding="utf-8") as f:
        first = f.readline()
    sep = "\t" if "\t" in first else ","
    raw = pd.read_csv(csv_path, sep=sep, low_memory=False)

    if "timestamp_utc" not in raw.columns:
        raise ValueError("CSV sem coluna 'timestamp_utc'")

    from zoneinfo import ZoneInfo
    CITY_TZ = ZoneInfo(city.timezone)

    raw["timestamp_utc"] = pd.to_datetime(raw["timestamp_utc"], errors="coerce")
    if raw["timestamp_utc"].dt.tz is not None:
        raw["timestamp_utc"] = raw["timestamp_utc"].dt.tz_convert(None)
    raw["timestamp_utc"] = raw["timestamp_utc"].dt.tz_localize("UTC")

    dt_locals, dates, hours, slots30 = [], [], [], []
    for ts in raw["timestamp_utc"]:
        dt_local = ts.astimezone(CITY_TZ)
        h, m = dt_local.hour, dt_local.minute
        h2, s2 = ceil_slot(h, m)
        if h2 == 24:
            # Manter no mesmo dia como slot 23:30 (último slot do dia)
            h2 = 23
            s2 = 30
        dt_locals.append(dt_local)
        dates.append(dt_local.date())
        hours.append(h2)
        slots30.append(s2)

    raw["datetime_local"] = dt_locals
    raw["date"] = dates
    raw["hour"] = hours
    raw["slot30"] = slots30
    raw["month"] = [d.month for d in dt_locals]
    raw["doy"] = [d.timetuple().tm_yday for d in dt_locals]
    raw["temp_c"] = pd.to_numeric(raw["temp_c"], errors="coerce")

    # Helper: aceita várias possíveis colunas (WU vs Open-Meteo) e tem default
    def _coalesce_col(possible_names: list[str], default: float) -> pd.Series:
        for name in possible_names:
            if name in raw.columns:
                return pd.to_numeric(raw[name], errors="coerce").fillna(default)
        # Nenhuma encontrada: criar Series com default
        return pd.Series([default] * len(raw), index=raw.index, dtype="float64")

    # Colunas meteorológicas (mapeamentos compatíveis WU + Open-Meteo)
    raw["humidity"]       = _coalesce_col(["humidity_pct", "humidity", "relative_humidity_2m"], 70.0)
    raw["cloud_cover"]    = _coalesce_col(["sky_cover", "cloud_cover", "cloudcover"], 50.0)
    raw["dewpoint_c"]     = _coalesce_col(["dewpt_c", "dewpoint_c", "dew_point_2m"],
                                          float((raw["temp_c"] - 10).mean() if "temp_c" in raw.columns else 5.0))
    raw["pressure_hpa"]   = _coalesce_col(["pressure_hpa", "pressure_msl", "surface_pressure"], 1013.0)
    raw["wind_dir_deg"]   = _coalesce_col(["wind_dir_deg", "wind_direction_10m", "winddirection_10m"], 0.0)
    raw["wind_speed_kmh"] = _coalesce_col(["wind_speed_kmh", "wind_speed_10m", "windspeed_10m"], 5.0)
    raw["wind_gust_kmh"]  = _coalesce_col(["wind_gust_kmh", "wind_gusts_10m", "windgusts_10m"], 8.0)
    raw["uv_index"]       = _coalesce_col(["uv_index"], 3.0)

    df = raw[
        (raw["hour"] >= city.day_start) & (raw["hour"] <= city.day_end)
    ].dropna(subset=["temp_c"]).sort_values(
        ["date", "hour", "slot30"]
    ).reset_index(drop=True)

    _console.print(f"    [green]✓[/green] {len(df):,} slots  {df['date'].nunique()} dias")
    return df


def _compute_prev7_map(df: pd.DataFrame) -> dict:
    """{date: prev_7d_avg_max} — evita hardcoding a 15.0."""
    daily_max = df.groupby("date")["temp_c"].max().sort_index()
    dates_list = list(daily_max.index)
    prev7 = {}
    for i, d in enumerate(dates_list):
        if i == 0:
            prev7[d] = 15.0
        else:
            window = daily_max[dates_list[max(0, i - 7):i]]
            prev7[d] = float(window.mean()) if len(window) else 15.0
    return prev7


# ══════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════
def _slot_idx(h: int, s: int) -> int:
    return h * 2 + s // 30


def _bracket_contains_peak(temp_lo: float, temp_hi: float, peak_temp: float) -> bool:
    peak_int = int(round(peak_temp))
    if temp_hi >= 99:
        return peak_int >= int(round(temp_lo))
    if temp_lo <= -99:
        return peak_int <= int(round(temp_hi))
    return int(round(temp_lo)) <= peak_int <= int(round(temp_hi))


def _pnl_per_dollar(ask: float, won: bool) -> float:
    if not ask or ask <= 0 or ask >= 1:
        return -1.0 if not won else 0.0
    return (1.0 / ask) - 1.0 if won else -1.0


def _compute_sharpe_sortino(capital_history: list) -> tuple:
    if not capital_history or len(capital_history) < 2:
        return 0.0, 0.0
    caps = np.array([c for _, c in capital_history], dtype=float)
    rets = np.diff(caps) / caps[:-1]
    if len(rets) == 0 or rets.std() < 1e-8:
        return 0.0, 0.0
    ann = np.sqrt(252)
    sharpe = float(rets.mean() / rets.std() * ann)
    downside = rets[rets < 0]
    if len(downside) > 1 and downside.std() > 1e-8:
        sortino = float(rets.mean() / downside.std() * ann)
    else:
        sortino = 0.0
    return round(sharpe, 2), round(sortino, 2)


def _season_of(month: int) -> str:
    for s, months in SEASONS.items():
        if month in months:
            return s
    return "spring"


# ══════════════════════════════════════════════════════
#  RUN BACKTEST
# ══════════════════════════════════════════════════════
def run_backtest(
    df: pd.DataFrame,
    models: dict,
    city: CityConfig,
    ordertype: str = "fixed",
    bet_value: float = 5.0,
    noise_std: float = 0.08,
    mode: str = "single",
) -> tuple:
    """
    Retorna (yearly_dict, capital_history, day_records).

    mode: "single" — determina qual PnL é somado ao capital simulado.
    """
    sim_mkt = SimulatedMarket(temp_range=city.temp_range, noise_std=noise_std)
    prev7_map = _compute_prev7_map(df)

    yearly = {}
    capital = 1000.0
    capital_history = []
    day_records = []
    capital_flow_debug = []  # debug CSV: cada trade single em modo percent

    with Progress(
        TextColumn("[cyan]Processando..."), BarColumn(),
        TextColumn("{task.percentage:>3.0f}%"),
        TimeElapsedColumn(), TimeRemainingColumn(),
        console=_console,
    ) as progress:
        task = progress.add_task("", total=df["date"].nunique())

        for d, day_df in df.groupby("date"):
            progress.update(task, advance=1)
            year = d.year if hasattr(d, "year") else pd.Timestamp(d).year
            if year not in yearly:
                yearly[year] = {
                    "single": {"correct":0,"premature":0,"missed":0,"total":0,"trades":0,"invested":0.0,"pnl":0.0}
                }

            month = int(day_df["month"].iloc[0])
            doy = int(day_df["doy"].iloc[0])
            season = _season_of(month)

            peak_temp = day_df["temp_c"].max()
            peak_idx = day_df[day_df["temp_c"] == peak_temp].index[-1]
            peak_h = int(day_df.loc[peak_idx, "hour"])
            peak_s = int(day_df.loc[peak_idx, "slot30"])
            peak_sidx = _slot_idx(peak_h, peak_s)

            if ordertype == "percent":
                bet_size = max(5.0, min(500.0, capital * (bet_value / 100.0)))
            else:
                bet_size = bet_value

            # Decisão 2026-04: LightGBM puro (sem ensemble). O zscore deixa
            # de ser criado/atualizado por dia — era puro overhead.
            slots_so_far = []

            # SingleEntry usa defaults calibrados (thr/hour_min de cities/{city}/strategy_config_{city}.json
            # ou de city_config como fallback)
            entry_single = SingleEntry(city, parcel_size=bet_size)

            fc_agreement = {"valid": True}  # assumimos forecasts concordam

            for _, row in day_df.iterrows():
                h = int(row["hour"])
                s = int(row["slot30"])
                t = float(row["temp_c"])

                slot_entry = {
                    "hour": h, "slot30": s, "temp_c": t,
                    "humidity": float(row["humidity"]),
                    "cloud_cover": float(row["cloud_cover"]),
                    "dewpoint_c": float(row["dewpoint_c"]),
                    "pressure_hpa": float(row["pressure_hpa"]),
                    "wind_dir_deg": float(row["wind_dir_deg"]),
                    "wind_speed_kmh": float(row["wind_speed_kmh"]),
                    "wind_gust_kmh": float(row["wind_gust_kmh"]),
                    "uv_index": float(row["uv_index"]),
                }
                slots_so_far.append(slot_entry)

                if h < city.day_start or len(slots_so_far) < 4:
                    continue

                running_max = max(sl["temp_c"] for sl in slots_so_far)
                if np.isnan(running_max) or np.isinf(running_max):
                    running_max = 15.0

                current_extra = {**slot_entry, "prev_7d_avg_max": prev7_map.get(d, 15.0)}

                # zscore_detector=None → predict_ensemble só usa LightGBM
                ens = predict_ensemble(models, slots_so_far, current_extra, month, doy, None)
                p_ens = ens.get("p_ensemble", 0.0)

                brackets = sim_mkt.get_brackets(p_ens, running_max, h)
                market_sim = {"brackets": brackets}

                # SINGLE — 1 compra por sessão
                for act in entry_single.evaluate(p_ens, h, market_sim, running_max, fc_agreement):
                    if act.get("size_usdc", 0) > 0:
                        # Estratégia real: apostar no bracket que contém round(running_max)
                        target_temp = int(round(running_max))
                        best = None
                        for b in brackets:
                            if b["temp_lo"] <= target_temp <= b["temp_hi"]:
                                best = b
                                break
                        # Fallback: bracket mais próximo se nenhum contém exactamente
                        if best is None:
                            best = min(
                                brackets,
                                key=lambda b: abs(((b["temp_lo"] + b["temp_hi"]) / 2) - target_temp),
                            )
                        entry_single.mark_bought(0, {
                            "hour": h, "slot30": s,
                            "ask": best["ask"],
                            "bracket_label": best["label"],
                            "temp_lo": best["temp_lo"],
                            "temp_hi": best["temp_hi"],
                            "size_usdc": act["size_usdc"],
                        })
                        break

                # STOP-LOSS — verificar em todos os slots após a compra (SINGLE only)
                stop_signal = entry_single.check_stop_loss(t)
                if stop_signal:
                    # Encontrar bid do bracket da posição
                    pos = stop_signal["position"]
                    matching = [b for b in brackets
                                if b["temp_lo"] == pos["temp_lo"]
                                and b["temp_hi"] == pos["temp_hi"]]
                    if matching:
                        sell_bid = matching[0]["bid"]
                    else:
                        sell_bid = 0.02  # liquidez zero

                    # PnL realizado: vendemos ao bid, depois de ter comprado ao ask
                    entry_ask = pos["ask"]
                    shares = pos["size_usdc"] / entry_ask if entry_ask > 0 else 0
                    sell_value = shares * sell_bid
                    realized_pnl = sell_value - pos["size_usdc"]

                    entry_single.mark_sold_by_stop(sell_bid, realized_pnl)

            # ── Avaliação fim-de-dia ──
            # SINGLE
            single_won, single_pnl, single_lag_h = False, 0.0, None
            if entry_single.bought and entry_single.record:
                rec = entry_single.record
                single_won = _bracket_contains_peak(rec["temp_lo"], rec["temp_hi"], peak_temp)

                # Se foi vendida por stop-loss, usar o PnL realizado nesse momento
                # (ignorando o resultado final — vendemos cedo para recuperar capital)
                if entry_single.sold_by_stop and "realized_pnl" in rec:
                    single_pnl = rec["realized_pnl"]
                else:
                    single_pnl = rec["size_usdc"] * _pnl_per_dollar(rec["ask"], single_won)

                lag_slots = peak_sidx - _slot_idx(rec["hour"], rec["slot30"])
                single_lag_h = lag_slots * 0.5
                premature_s = rec["hour"] < peak_h and not single_won
            else:
                premature_s = False
            correct_s = single_won
            missed_s = not entry_single.bought

            # Acumular anual
            yearly[year]["single"]["correct"]   += int(correct_s)
            yearly[year]["single"]["premature"] += int(premature_s)
            yearly[year]["single"]["missed"]    += int(missed_s)
            yearly[year]["single"]["total"]     += 1                # total de DIAS (todos)
            # Trades reais = dias com entrada efectiva (correct OR premature, NOT missed)
            yearly[year]["single"]["trades"]    += int(not missed_s)
            yearly[year]["single"]["invested"]  += entry_single.total_invested
            yearly[year]["single"]["pnl"]       += single_pnl

            # Record para sazonal / lag
            day_records.append({
                "date": d, "month": month, "season": season,
                "peak_temp": peak_temp, "peak_hour": peak_h,
                "single_correct": correct_s, "single_premature": premature_s,
                "single_missed": missed_s, "single_lag_h": single_lag_h,
                "single_pnl": single_pnl,
                "single_invested": entry_single.total_invested,
                "single_stop_loss": entry_single.sold_by_stop,
                # Diagnose económica — para análise post-backtest
                "single_ask": entry_single.record["ask"] if entry_single.bought and entry_single.record else None,
                "single_size_usdc": entry_single.record["size_usdc"] if entry_single.bought and entry_single.record else None,
                "single_hour": entry_single.record["hour"] if entry_single.bought and entry_single.record else None,
            })

            if ordertype == "percent":
                # Só somar ao capital o PnL relevante para o modo escolhido.
                cap_before = capital
                if mode == "single":
                    capital += single_pnl
                else:  # "both"
                    capital += single_pnl
                capital_after_pnl = capital  # antes do clip
                capital = max(capital, 100.0)

                # DEBUG: gravar trade-a-trade para CSV se mode=single
                if mode == "single" and entry_single.bought:
                    capital_flow_debug.append({
                        "date": d,
                        "cap_before": round(cap_before, 2),
                        "bet_size": round(bet_size, 2),
                        "ask": round(entry_single.record["ask"], 4) if entry_single.record else None,
                        "won": single_won,
                        "sold_by_stop": entry_single.sold_by_stop,
                        "single_pnl": round(single_pnl, 2),
                        "cap_after_pnl": round(capital_after_pnl, 2),
                        "cap_clipped": round(capital, 2),
                        "clip_loss": round(capital - capital_after_pnl, 2),
                    })

            capital_history.append((d, capital))

    return yearly, capital_history, day_records, capital_flow_debug


# ══════════════════════════════════════════════════════
#  MÉTRICAS POR MODO
# ══════════════════════════════════════════════════════
def compute_stats(day_records: list, mode: str, capital_history: list) -> BacktestStats:
    df = pd.DataFrame(day_records)
    n = len(df)
    if n == 0:
        return BacktestStats()

    prefix = mode
    correct_mask = df[f"{prefix}_correct"]
    lag_col = f"{prefix}_lag_h" if mode == "single" else "parcel1_lag_h"
    correct_lags = df[correct_mask & df[lag_col].notna()][lag_col].values
    total_pnl = df[f"{prefix}_pnl"].sum()

    stats = BacktestStats(
        total_days    = n,
        total_trades  = int(df[f"{prefix}_correct"].sum() + df[f"{prefix}_premature"].sum()),
        wins          = int(correct_mask.sum()),
        losses        = int((~correct_mask & ~df[f"{prefix}_missed"]).sum()),
        correct_pct   = round(correct_mask.mean() * 100, 1),
        premature_pct = round(df[f"{prefix}_premature"].mean() * 100, 1),
        missed_pct    = round(df[f"{prefix}_missed"].mean() * 100, 1),
        lag_mean_h    = round(float(np.mean(correct_lags)), 2) if len(correct_lags) else None,
        lag_median_h  = round(float(np.median(correct_lags)), 2) if len(correct_lags) else None,
        lag_le1h_pct  = round((correct_lags <= 1.0).mean() * 100, 1) if len(correct_lags) else 0.0,
        lag_le2h_pct  = round((correct_lags <= 2.0).mean() * 100, 1) if len(correct_lags) else 0.0,
        total_pnl     = round(float(total_pnl), 2),
    )

    # Sharpe/Sortino do capital global
    sh, so = _compute_sharpe_sortino(capital_history)
    stats.sharpe = sh
    stats.sortino = so
    if capital_history:
        final_cap = capital_history[-1][1]
        stats.total_return_pct = round((final_cap / 1000.0 - 1) * 100, 1)

    # Sazonalidade
    for season, months in SEASONS.items():
        sub = df[df["season"] == season]
        if sub.empty:
            continue
        # Trades = dias com entrada (NOT missed)
        trades_in_season = sub[~sub[f"{prefix}_missed"]]
        n_trades = len(trades_in_season)
        n_correct = int(trades_in_season[f"{prefix}_correct"].sum())
        n_premature = int(trades_in_season[f"{prefix}_premature"].sum())

        stats.seasonal_stats[season] = {
            "n_days": len(sub),
            "n_trades": n_trades,
            # Win% = wins / trades (% dos que entraram que ganharam)
            "win_pct": round(n_correct / n_trades * 100, 1) if n_trades > 0 else 0.0,
            # Prem% = premature / trades (% dos trades que entraram cedo)
            "premature_pct": round(n_premature / n_trades * 100, 1) if n_trades > 0 else 0.0,
            # NoEntry% = missed / total_days
            "noentry_pct": round((len(sub) - n_trades) / len(sub) * 100, 1),
            "pnl": round(sub[f"{prefix}_pnl"].sum(), 2),
        }

    return stats


# ══════════════════════════════════════════════════════
#  DASHBOARD
# ══════════════════════════════════════════════════════
def print_dashboard(
    yearly: dict,
    day_records: list,
    capital_history: list,
    models: dict,
    initial_capital: float = 1000.0,
    ordertype: str = "fixed",
    bet_value: float = 5.0,
    noise_std: float = 0.08,
    model_dir: Path = Path("cities/munich/munich_peak_model"),  # caller deve passar city.model_dir
) -> tuple:
    """Dashboard principal. Retorna stats_single."""

    auc_str = "?"
    prior_str = "não"
    try:
        cfg = json.loads((model_dir / "peak_model_config.json").read_text())
        auc = cfg.get("mean_auc_wf") or cfg.get("global_auc")
        if auc:
            auc_str = f"{auc:.4f}"
        prior_str = "sim" if cfg.get("seasonal_peak_prior") else "não"
    except Exception:
        pass

    order_str = f"${bet_value}" if ordertype == "fixed" else f"{bet_value}% do capital (inicial ${initial_capital:,.0f})"
    noise_str = f"{noise_std*100:.1f}¢" if noise_std > 0 else "determinístico (circular!)"

    _console.rule(f"[bold cyan]BACKTEST FINAL — SINGLE[/bold cyan]")
    _console.print(f"[dim]AUC modelo: {auc_str} | Seasonal Prior: {prior_str} | Modelo: {model_dir}[/dim]")
    _console.print(f"[bold]Capital inicial: ${initial_capital:,.0f} | OrderType: {order_str} | Ruído mercado: {noise_str}[/bold]\n")

    # ─── Tabela anual ───
    table = Table(box=rich_box.ROUNDED, show_header=True, header_style="bold cyan", title="Resultados por Ano")
    # Colunas explicadas:
    #   Trades   = nº de trades (dias com entrada, exclui Miss)
    #   Win%     = wins / trades  (entre os que ENTRARAM, % que ganhou)
    #   Wins     = trades vencedores
    #   Prem%    = % dos trades em que entrou ANTES do pico real
    #   NoEntry% = % dos dias sem trade (modelo nunca disparou)
    for col, w, just in [("Ano",6,"left"),("Trades",7,"right"),("Win%",7,"right"),("Wins",6,"right"),
                          ("Prem%",7,"right"),("NoEntry%",9,"right"),
                          ("Invested",10,"right"),("PnL $",11,"right"),("PnL%",8,"right")]:
        table.add_column(col, justify=just, width=w)

    total_single = {"correct":0, "premature":0, "missed":0, "total":0, "trades":0, "invested":0.0, "pnl":0.0}

    for year in sorted(yearly):
        mode = "single"
        s = yearly[year][mode]
        t_days = s["total"]
        t_trades = s["trades"]
        if t_days == 0: continue
        wins = s["correct"]
        # Win% agora correctamente sobre trades efectuados
        win_pct = (wins / t_trades * 100) if t_trades > 0 else 0.0
        prem_pct = (s["premature"] / t_trades * 100) if t_trades > 0 else 0.0
        noentry_pct = s["missed"] / t_days * 100
        pnl_pct = (s["pnl"] / s["invested"] * 100) if s["invested"] > 0 else 0.0
        c_win = "green" if win_pct > 80 else "yellow" if win_pct > 60 else "red"
        c_pnl = "green" if pnl_pct > 0 else "red"
        table.add_row(
            str(year),
            f"{t_trades}",
            f"[{c_win}]{win_pct:.1f}%[/{c_win}]",
            f"[{c_win}]{wins}[/{c_win}]",
            f"{prem_pct:.1f}%",
            f"{noentry_pct:.1f}%",
            f"${s['invested']:,.0f}",
            f"[{c_pnl}]${s['pnl']:+,.0f}[/{c_pnl}]",
            f"[{c_pnl}]{pnl_pct:+.1f}%[/{c_pnl}]",
        )
        for k in ("correct","premature","missed","total","trades","invested","pnl"):
            total_single[k] += s[k]
    table.add_row("─"*6,"─"*7,"─"*7,"─"*6,"─"*7,"─"*9,"─"*10,"─"*11,"─"*8)

    _console.print(table)

    # ─── Resumo total ───
    _console.rule("[bold]RESUMO TOTAL DO PERÍODO[/bold]")
    total_table = Table(box=rich_box.ROUNDED)
    for c in ["Dias","Trades","Win%","Wins","Prem%","NoEntry%","Invested","PnL $","PnL%"]:
        total_table.add_column(c, justify="right")
    mode_name, data = ("SINGLE", total_single)
    t_days = data["total"]
    t_trades = data["trades"]
    if t_days > 0:
        wins = data["correct"]
        # Win% correctamente sobre trades realmente efectuados
        win_pct = (wins / t_trades * 100) if t_trades > 0 else 0.0
        prem_pct = (data["premature"] / t_trades * 100) if t_trades > 0 else 0.0
        noentry_pct = data["missed"] / t_days * 100
        pnl_pct = (data["pnl"] / data["invested"] * 100) if data["invested"] > 0 else 0.0
    c_win = "green" if win_pct > 80 else "yellow" if win_pct > 60 else "red"
    c_pnl = "green" if pnl_pct > 0 else "red"
    total_table.add_row(
        f"{t_days}",
        f"{t_trades}",
        f"[{c_win}]{win_pct:.1f}%[/{c_win}]",
        f"[{c_win}]{wins}[/{c_win}]",
        f"{prem_pct:.1f}%",
        f"{noentry_pct:.1f}%",
        f"${data['invested']:,.0f}",
        f"[{c_pnl}]${data['pnl']:+,.0f}[/{c_pnl}]",
        f"[{c_pnl}]{pnl_pct:+.1f}%[/{c_pnl}]",
    )
    _console.print(total_table)

    # Pequena legenda explicativa para evitar confusão
    _console.print(
        "\n[dim]Legenda:\n"
        "  • Trades = dias com entrada (NoEntry excluídos)\n"
        "  • Win%  = wins / trades (qualidade do sinal quando entra)\n"
        "  • Prem% = trades em que entrou ANTES do pico real\n"
        "  • NoEntry% = dias sem trade (modelo nunca disparou)\n"
        "  • PnL% = retorno sobre o invested[/dim]"
    )

    # Stop-loss stats (SINGLE only)
    df_days = pd.DataFrame(day_records)
    if "single_stop_loss" in df_days.columns:
        n_sl = int(df_days["single_stop_loss"].sum())
        if n_sl > 0:
            sl_days = df_days[df_days["single_stop_loss"]]
            avg_sl_pnl = sl_days["single_pnl"].mean()
            total_sl_pnl = sl_days["single_pnl"].sum()
            _console.print(
                f"\n[bold]Stop-losses (SINGLE):[/bold] {n_sl} triggered  "
                f"|  PnL médio por trigger: ${avg_sl_pnl:+.2f}  "
                f"|  PnL total de stops: ${total_sl_pnl:+.0f}"
            )

    # ─── DIAGNOSE ECONÓMICA (SINGLE) ───
    # Investiga onde vem (ou não vem) o lucro: distribuição de asks pagos,
    # payoff por trade, sensibilidade do EV ao win-rate.
    if "single_ask" in df_days.columns:
        trades_df = df_days[df_days["single_ask"].notna()].copy()
        if len(trades_df) > 0:
            _console.rule("[bold cyan]DIAGNOSE ECONÓMICA — SINGLE[/bold cyan]")

            wins_df = trades_df[trades_df["single_correct"]]
            losses_df = trades_df[~trades_df["single_correct"]]

            # Distribuição de asks pagos
            tbl_asks = Table(box=rich_box.SIMPLE, show_header=True,
                             title="Distribuição dos asks pagos")
            for c in ["Categoria", "N", "Ask médio", "Ask p25", "Ask p50", "Ask p75", "Ask p95"]:
                tbl_asks.add_column(c, justify="right")

            for label, sub, colour in [
                ("Wins",       wins_df,    "green"),
                ("Losses",     losses_df,  "red"),
                ("Stop-losses", trades_df[trades_df["single_stop_loss"]], "yellow"),
                ("Todos",      trades_df,  "white"),
            ]:
                if len(sub) == 0:
                    continue
                asks = sub["single_ask"]
                tbl_asks.add_row(
                    f"[{colour}]{label}[/{colour}]",
                    str(len(sub)),
                    f"{asks.mean():.3f}",
                    f"{asks.quantile(0.25):.3f}",
                    f"{asks.quantile(0.50):.3f}",
                    f"{asks.quantile(0.75):.3f}",
                    f"{asks.quantile(0.95):.3f}",
                )
            _console.print(tbl_asks)

            # Análise económica: payoff vs perda, EV por trade
            avg_ask_win = wins_df["single_ask"].mean() if len(wins_df) else 0
            avg_payoff_per_dollar = (1 / avg_ask_win - 1) if avg_ask_win > 0 else 0
            win_pct = len(wins_df) / len(trades_df) * 100

            ev_per_dollar = (
                (len(wins_df) * avg_payoff_per_dollar - len(losses_df) * 1.0)
                / len(trades_df) if len(trades_df) > 0 else 0
            )

            # Win-rate de break-even matemático
            be_win_rate = 1 / (1 + avg_payoff_per_dollar) * 100 if avg_payoff_per_dollar > 0 else 100
            margin = win_pct - be_win_rate

            tbl_econ = Table(box=rich_box.SIMPLE, show_header=False,
                             title="Análise económica do trade típico")
            tbl_econ.add_column("Métrica", style="dim")
            tbl_econ.add_column("Valor", justify="right")

            tbl_econ.add_row("Ask médio quando ganha",
                             f"{avg_ask_win:.3f} ({avg_ask_win*100:.1f}¢)")
            tbl_econ.add_row("Payoff por $ apostado (win)",
                             f"+${avg_payoff_per_dollar:.3f}")
            tbl_econ.add_row("Win-rate observado",
                             f"{win_pct:.1f}%")
            tbl_econ.add_row("Win-rate break-even",
                             f"{be_win_rate:.1f}%")
            color = "green" if margin > 5 else "yellow" if margin > 0 else "red"
            tbl_econ.add_row("Margem (observado − break-even)",
                             f"[{color}]{margin:+.1f}pp[/{color}]")
            color = "green" if ev_per_dollar > 0.05 else "yellow" if ev_per_dollar > 0 else "red"
            tbl_econ.add_row("EV por $ apostado (esperado)",
                             f"[{color}]${ev_per_dollar:+.3f}[/{color}]")
            _console.print(tbl_econ)

            # Distribuição por hora de entrada — para detectar se asks dependem da hora
            if "single_hour" in trades_df.columns:
                hourly = trades_df.groupby("single_hour").agg(
                    n=("single_ask", "size"),
                    ask_mean=("single_ask", "mean"),
                    win_rate=("single_correct", lambda s: s.sum() / len(s) * 100),
                ).reset_index()

                tbl_hours = Table(box=rich_box.SIMPLE, show_header=True,
                                  title="Por hora de entrada")
                for c in ["Hora", "Trades", "Ask médio", "Win%", "Payoff $/win", "EV $/trade"]:
                    tbl_hours.add_column(c, justify="right")

                for _, row in hourly.iterrows():
                    n = int(row["n"])
                    ask_h = row["ask_mean"]
                    wr = row["win_rate"]
                    payoff = (1 / ask_h - 1) if ask_h > 0 else 0
                    ev = (wr / 100 * payoff) - ((1 - wr/100) * 1.0)
                    color = "green" if ev > 0.05 else "yellow" if ev > 0 else "red"
                    tbl_hours.add_row(
                        f"{int(row['single_hour'])}h",
                        str(n),
                        f"{ask_h:.3f}",
                        f"{wr:.1f}%",
                        f"+${payoff:.3f}",
                        f"[{color}]${ev:+.3f}[/{color}]",
                    )
                _console.print(tbl_hours)

            # Veredicto
            if margin < 0:
                _console.print(
                    "\n[red bold]⚠  EDGE NEGATIVO[/red bold] — em média o backtest perde "
                    "valor esperado por trade. Causas possíveis:\n"
                    "  • Asks demasiado altos no SimulatedMarket (revisitar fórmula climatológica)\n"
                    "  • Configuração demasiado tardia (hour_min alto → asks já consolidados)\n"
                    "  • Modelo entra em situações onde mercado é eficiente"
                )
            elif margin < 5:
                _console.print(
                    "\n[yellow bold]⚠  EDGE MARGINAL[/yellow bold] — margem positiva mas pequena.\n"
                    "  Em produção, slippage, fees ou variância podem facilmente destruir esta edge.\n"
                    "  Considerar: hour_min mais cedo (ask mais baixo) ou threshold mais alto (win-rate mais alto)."
                )
            else:
                _console.print(
                    f"\n[green bold]✓ EDGE POSITIVA[/green bold] — margem confortável de {margin:.1f}pp "
                    "sobre o break-even.\n"
                    "  Configuração financeiramente sã (assumindo SimulatedMarket realista)."
                )

    # ─── Sharpe/Sortino globais ───
    if capital_history and len(capital_history) >= 2:
        sharpe, sortino = _compute_sharpe_sortino(capital_history)
        final_cap = capital_history[-1][1]
        total_return_pct = (final_cap / initial_capital - 1) * 100
        caps = [c for _, c in capital_history]
        max_cap = max(caps)
        min_cap = min(caps)
        # Encontrar quando atingiu o mínimo
        min_date = next(d for d, c in capital_history if c == min_cap)

        # Reconciliar PnL absoluto (soma dos PnLs trade-a-trade) com retorno do capital
        # Os dois podem divergir bastante quando capital é clipped a $100 (drawdown).
        # Mostrar AMBOS para evitar confusão.
        _console.print(
            f"\n[bold]Capital simulado (--ordertype percent):[/bold]\n"
            f"  Inicial: ${initial_capital:,.2f}  →  Final: ${final_cap:,.2f}  "
            f"({total_return_pct:+.1f}%)\n"
            f"  Mínimo durante: ${min_cap:,.2f} (em {min_date})  "
            f"|  Máximo: ${max_cap:,.2f}\n"
            f"  Sharpe anualizado: {sharpe}   Sortino anualizado: {sortino}"
        )

        # Avisar se houve clipping (capital tocou em $100)
        if min_cap <= 100.0:
            _console.print(
                "\n[yellow]⚠  AVISO: O capital simulado tocou no piso de $100 (clipping).[/yellow]\n"
                "[dim]Isto significa que num momento o capital ficou tão baixo que o\n"
                "  backtester clamped a $100 para evitar bankroll negativo. A partir\n"
                "  daí, qualquer recuperação fica artificialmente limitada.\n"
                "  O ROI honesto é o PnL%/Invested mostrado acima na tabela RESUMO\n"
                "  TOTAL, NÃO o 'return total' do capital.[/dim]"
            )

        if max_cap == min_cap:
            _console.print(
                "[dim yellow]Nota: capital constante — Sharpe/Sortino só informativos com --ordertype percent.[/dim yellow]"
            )
        if noise_std == 0:
            _console.print(
                "[dim red]Aviso: backtest determinístico (--noise 0). Win-rate pode estar inflado por circularidade.[/dim red]"
            )

    # ─── Sazonalidade por modo ───
    stats_single = compute_stats(day_records, "single", capital_history)

    _console.rule("[dim]SINGLE — Lag & Sazonalidade[/dim]", style="dim")

    if stats_single.lag_mean_h is not None:
        _console.print(
            f"  Lag: médio +{stats_single.lag_mean_h}h, mediano +{stats_single.lag_median_h}h, "
            f"≤1h: {stats_single.lag_le1h_pct}%, ≤2h: {stats_single.lag_le2h_pct}%"
        )

    if stats_single.seasonal_stats:
        season_tbl = Table(box=rich_box.SIMPLE, show_header=True)
        for c in ["Estação","Dias","Trades","Win%","Prem%","NoEntry%","PnL"]:
            season_tbl.add_column(c, justify="right")
        icons = {"winter":"❄","spring":"🌱","summer":"☀","autumn":"🍂"}
        for season in ["winter", "spring", "summer", "autumn"]:
            ss = stats_single.seasonal_stats.get(season)
            if not ss: continue
            cc = "green" if ss["win_pct"] >= 80 else "yellow" if ss["win_pct"] >= 60 else "red"
            cp = "green" if ss["pnl"] > 0 else "red"
            season_tbl.add_row(
                f"{icons.get(season,'')} {season}",
                str(ss["n_days"]),
                str(ss["n_trades"]),
                f"[{cc}]{ss['win_pct']}%[/{cc}]",
                f"{ss['premature_pct']}%",
                f"{ss['noentry_pct']}%",
                f"[{cp}]${ss['pnl']:+.0f}[/{cp}]",
            )
        _console.print(season_tbl)

    # ─── Gráfico do capital ───
    if capital_history and ordertype == "percent":
        dates_c, capitals = zip(*capital_history)
        plt.figure(figsize=(12, 6))
        plt.plot(dates_c, capitals, color="#00ff9f", linewidth=2.5, label="Capital")
        plt.title("Evolução do Capital", fontsize=16, fontweight="bold", color="white")
        plt.xlabel("Data"); plt.ylabel("Capital ($)")
        plt.grid(True, alpha=0.3)
        plt.fill_between(dates_c, capitals, alpha=0.2, color="#00ff9f")
        plt.legend(); plt.tight_layout()
        chart_path = OUTPUT_DIR / "capital_evolution.png"
        plt.savefig(chart_path, dpi=300, facecolor="#1e1e1e")
        plt.close()
        _console.print(f"\n[green]Gráfico guardado em:[/green] {chart_path}")

    _console.print("\n[green]Dashboard finalizada.[/green]\n")
    return stats_single


# ══════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════
def main():
    parser = argparse.ArgumentParser(description="Backtester multi-cidade")
    parser.add_argument("--city", type=str, default="munich", choices=list(CITIES.keys()),
                        help="Cidade para backtest (default: munich)")
    parser.add_argument("--mode", choices=["single"], default="single")
    parser.add_argument("--years", type=int, default=3)
    parser.add_argument("--start", type=str, help="Data início (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, help="Data fim (YYYY-MM-DD)")
    parser.add_argument("--ordertype", choices=["fixed","percent"], default="fixed")
    parser.add_argument("--bet", type=float, default=5.0,
                        help="$ absoluto se fixed, % do capital se percent")
    parser.add_argument("--noise", type=float, default=0.05,
                        help="Ruído gaussiano no ask do mercado simulado (default 0.05 = 5¢). "
                             "0.0 = determinístico.")
    args = parser.parse_args()

    city = get_city(args.city)
    set_city(args.city)

    _console.print(f"\n[bold cyan]{city.name.title()} Backtester[/bold cyan]")
    _console.print("[1/4] Modelos...")
    model_dir = Path(city.model_dir)
    models = load_models(args.city)

    _console.print("\n[2/4] Dados...")
    df_all = load_data(Path(city.csv_path), city)
    df_all["date"] = pd.to_datetime(df_all["date"]).dt.date

    if args.end:
        end_date = date.fromisoformat(args.end)
    else:
        end_date = date.today() - timedelta(days=1)
    if args.start:
        start_date = date.fromisoformat(args.start)
    else:
        start_date = date(end_date.year - args.years + 1, 1, 1)

    df = df_all[(df_all["date"] >= start_date) & (df_all["date"] <= end_date)].copy()
    _console.print(f"  {len(df):,} slots | {start_date} → {end_date}")

    _console.print(f"\n[3/4] Backtest (mode={args.mode}, {args.ordertype}={args.bet}, ruído={args.noise})...")
    yearly, capital_history, day_records, capital_flow_debug = run_backtest(
        df, models, city,
        ordertype=args.ordertype,
        bet_value=args.bet,
        noise_std=args.noise,
        mode=args.mode,
    )

    _console.print("\n[4/4] Dashboard & métricas...")
    stats_single = print_dashboard(
        yearly, day_records, capital_history, models,
        initial_capital=1000.0,
        ordertype=args.ordertype,
        bet_value=args.bet,
        noise_std=args.noise,
        model_dir=model_dir,
    )

    # Guardar resumo JSON (caminho por cidade)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_json = OUTPUT_DIR / f"{city.name}_backtest_{args.mode}_{start_date.isoformat()}_{end_date.isoformat()}.json"
    out_json.write_text(json.dumps({
        "city": city.name,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "mode": args.mode,
        "ordertype": args.ordertype,
        "bet": args.bet,
        "noise_std": args.noise,
        "model_dir": str(model_dir),
        "single": {
            "total_days": stats_single.total_days,
            "correct_pct": stats_single.correct_pct,
            "premature_pct": stats_single.premature_pct,
            "missed_pct": stats_single.missed_pct,
            "lag_mean_h": stats_single.lag_mean_h,
            "lag_le1h_pct": stats_single.lag_le1h_pct,
            "total_pnl": stats_single.total_pnl,
            "sharpe": stats_single.sharpe,
            "sortino": stats_single.sortino,
            "seasonal_stats": stats_single.seasonal_stats,
        },
    }, indent=2))
    _console.print(f"  [green]✓[/green] Resumo JSON: {out_json}")

    # ─── Debug CSV: capital flow trade-a-trade (modo percent + single) ───
    if capital_flow_debug:
        debug_csv = OUTPUT_DIR / f"{city.name}_capital_flow_debug_{args.mode}.csv"
        df_debug = pd.DataFrame(capital_flow_debug)
        df_debug.to_csv(debug_csv, index=False)
        _console.print(f"  [green]✓[/green] Debug CSV: {debug_csv}  ({len(df_debug)} trades)")

        # Análise inline
        _console.rule("[bold magenta]DIAGNÓSTICO — CAPITAL FLOW[/bold magenta]")

        # Estatísticas globais
        sum_single = df_debug["single_pnl"].sum()
        sum_total_clip = df_debug["clip_loss"].sum()  # quanto perdeu por clipping

        _console.print(
            f"  Trades em modo percent: [bold]{len(df_debug)}[/bold]\n"
            f"  Soma de single_pnl: [bold]${sum_single:+,.2f}[/bold]\n"
            f"  Capital perdido por clipping ($100 piso): [bold]${sum_total_clip:+,.2f}[/bold]\n"
        )

        # Top 5 piores trades (mais negativos)
        worst = df_debug.nsmallest(5, "single_pnl")
        _console.print("[yellow]Top 5 piores trades:[/yellow]")
        for _, row in worst.iterrows():
            _console.print(
                f"  {row['date']}  bet=${row['bet_size']:.2f}  ask={row['ask']:.3f}  "
                f"won={row['won']}  SL={row['sold_by_stop']}  "
                f"pnl=${row['single_pnl']:+.2f}  "
                f"cap: ${row['cap_before']:.2f} → ${row['cap_clipped']:.2f}"
            )

        # Quando capital atinge piso pela primeira vez
        clipped = df_debug[df_debug["clip_loss"] > 0]
        if len(clipped) > 0:
            first_clip = clipped.iloc[0]
            _console.print(
                f"\n[yellow]Primeiro clip a $100:[/yellow] {first_clip['date']}"
            )
            # Mostrar 5 trades antes desse evento
            idx_first = clipped.index[0]
            window = df_debug.iloc[max(0, idx_first-5):idx_first+1]
            _console.print(f"\n[dim]Trades antes do primeiro clip:[/dim]")
            for _, row in window.iterrows():
                _console.print(
                    f"  {row['date']}  bet=${row['bet_size']:.2f}  ask={row['ask']:.3f}  "
                    f"won={row['won']}  pnl=${row['single_pnl']:+.2f}  "
                    f"cap: ${row['cap_before']:.2f} → ${row['cap_clipped']:.2f}"
                )

        # Análise do progresso temporal
        df_debug["date"] = pd.to_datetime(df_debug["date"])
        df_debug = df_debug.sort_values("date").reset_index(drop=True)

        # Resumo por trimestre para detectar padrões
        df_debug["quarter"] = df_debug["date"].dt.to_period("Q")
        by_q = df_debug.groupby("quarter").agg(
            n_trades=("single_pnl", "size"),
            pnl_total=("single_pnl", "sum"),
            cap_min=("cap_clipped", "min"),
            cap_max=("cap_clipped", "max"),
            wins=("won", "sum"),
        ).reset_index()
        by_q["win_pct"] = by_q["wins"] / by_q["n_trades"] * 100

        tbl_q = Table(box=rich_box.SIMPLE, show_header=True, title="Capital por trimestre")
        for c in ["Trimestre", "N", "Win%", "PnL trimestre", "Cap min", "Cap max"]:
            tbl_q.add_column(c, justify="right")
        for _, row in by_q.iterrows():
            tbl_q.add_row(
                str(row["quarter"]),
                str(int(row["n_trades"])),
                f"{row['win_pct']:.1f}%",
                f"${row['pnl_total']:+.0f}",
                f"${row['cap_min']:.0f}",
                f"${row['cap_max']:.0f}",
            )
        _console.print(tbl_q)


if __name__ == "__main__":
    main()
