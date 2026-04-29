"""
backtester.py
=============
Backtester multi-cidade genérico. Usa predictor.py e cities/config.py.

Inclui:
  • PnL realista Polymarket: (1/ask - 1) por $
  • Outcome real: "correct" = bracket cobre peak_temp
  • 1 parcela por slot em phased
  • RESUMO TOTAL acumulado
  • Sharpe/Sortino reais a partir de retornos diários
  • Estatísticas sazonais (winter/spring/summer/autumn)
  • Lag por parcela em horas
  • prev_7d_avg_max real por dia (climatologia da cidade)
  • SimulatedMarket com ruído de mercado

Uso:
    python backtester.py --city munich --mode both --years 3 --ordertype percent --bet 2
    python backtester.py --city dallas --mode single --years 5 --ordertype fixed --bet 5
    python backtester.py --city ankara --mode both --years 3 --noise 0.0
"""

import argparse
import json
from dataclasses import dataclass, field
from datetime import date, timedelta, datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from rich.console import Console
from rich.progress import Progress, BarColumn, TextColumn, TimeElapsedColumn, TimeRemainingColumn
from rich.table import Table
from rich import box as rich_box

from cities.config import CityConfig, get_city, CITIES
from predictor import load_models, predict_ensemble, set_city, compute_prev7, init_history_max, update_history_max


_console = Console(force_terminal=True)
OUTPUT_DIR = Path("backtest_results")
OUTPUT_DIR.mkdir(exist_ok=True)


# ══════════════════════════════════════════════════════
#  SLOT HELPER
# ══════════════════════════════════════════════════════
def ceil_slot(hour: int, minute: int) -> tuple[int, int]:
    """Converte (hour, minute) para o slot 30min correto (truncar para CIMA)."""
    if minute < 30:
        return (hour, 30)
    else:
        return (hour + 1, 0)


# ══════════════════════════════════════════════════════
#  SIMULATED MARKET — baseado em climatologia + ruído
# ══════════════════════════════════════════════════════
class SimulatedMarket:
    """Simula asks dos brackets Polymarket de forma climatologicamente realista."""
    DAY_HOUR_START = 6
    DAY_HOUR_END = 20

    def __init__(self, temp_range: range, noise_std: float = 0.05, seed: int = 42):
        self.temp_range = temp_range
        self.noise_std = noise_std
        self._rng = np.random.default_rng(seed)

    def _climatological_ask(self, dist: int, hour: int, temp_below_rmax: bool) -> float:
        """Preço climatológico do bracket."""
        h = max(self.DAY_HOUR_START, min(self.DAY_HOUR_END, hour))
        confidence = (h - self.DAY_HOUR_START) / (self.DAY_HOUR_END - self.DAY_HOUR_START)

        if temp_below_rmax:
            base = 0.10 * (1 - confidence) + 0.02 * confidence
            if dist > 2:
                base = 0.02
            return base

        if dist == 0:
            ask = 0.35 + 0.55 * confidence
        elif dist == 1:
            ask = 0.30 * (1 - confidence) + 0.07 * confidence
        elif dist == 2:
            ask = 0.18 * (1 - confidence) + 0.03 * confidence
        elif dist == 3:
            ask = 0.08 * (1 - confidence) + 0.02 * confidence
        else:
            ask = max(0.02, 0.05 - 0.01 * dist)

        return ask

    def get_brackets(self, p_ensemble: float, running_max: float, hour: int) -> list[dict]:
        if np.isnan(running_max) or np.isinf(running_max):
            running_max = 15.0
        brackets = []
        rmax_int = int(round(running_max))

        for temp in self.temp_range:
            signed_dist = temp - rmax_int
            dist = abs(signed_dist)
            temp_below_rmax = signed_dist < 0

            climatological = self._climatological_ask(dist, hour, temp_below_rmax)

            if dist <= 1 and not temp_below_rmax:
                model_nudge = (p_ensemble - 0.5) * 0.10
            else:
                model_nudge = 0.0

            ask = climatological + model_nudge

            if self.noise_std > 0:
                noise_scale = self.noise_std * (1.0 + 0.05 * dist)
                ask += self._rng.normal(0, noise_scale)

            if dist > 5:
                ask = 0.01
                bid = 0.0
            else:
                ask = float(np.clip(ask, 0.02, 0.97))
                spread_factor = 0.05 + dist * 0.015
                bid = ask * (1 - spread_factor)

            is_last = (temp == self.temp_range[-1])
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
#  STRATEGIES
# ══════════════════════════════════════════════════════
@dataclass
class Trade:
    day: date
    bracket_lo: float
    bracket_hi: float
    enter_hour: float
    ask: float
    bet_size: float
    is_correct: bool
    is_premature: bool
    peak_temp: float
    lag_h: Optional[float] = None


@dataclass
class DailyResult:
    day: date
    peak_temp: float
    peak_hour: float
    trades: list[Trade] = field(default_factory=list)

    @property
    def n_correct(self) -> int:
        return sum(1 for t in self.trades if t.is_correct)

    @property
    def n_premature(self) -> int:
        return sum(1 for t in self.trades if t.is_premature)

    @property
    def n_missed(self) -> int:
        return sum(1 for t in self.trades if not t.is_correct and not t.is_premature)


class SingleEntryStrategy:
    """Estratégia SingleEntry: 1 trade por dia se P >= threshold."""
    def __init__(self, threshold: float = 0.55, hour_min: int = 15):
        self.threshold = threshold
        self.hour_min = hour_min

    def should_enter(self, p_ensemble: float, hour: int) -> bool:
        return p_ensemble >= self.threshold and hour >= self.hour_min

    def get_bracket(self, brackets: list[dict], running_max: float) -> Optional[dict]:
        for b in brackets:
            if b["temp_lo"] <= running_max <= b["temp_hi"]:
                return b
        return None


class PhasedEntryStrategy:
    """Estratégia PhasedEntry: múltiplas entradas ao longo do dia."""
    def __init__(self, thresholds: list[tuple[int, float]]):
        # thresholds = [(hour, threshold), ...]
        self.thresholds = thresholds

    def get_threshold(self, hour: int) -> float:
        for h, thr in sorted(self.thresholds, reverse=True):
            if hour >= h:
                return thr
        return 0.5

    def should_enter(self, p_ensemble: float, hour: int, last_entered_hour: float) -> bool:
        if hour <= last_entered_hour:
            return False
        thr = self.get_threshold(hour)
        return p_ensemble >= thr

    def get_bracket(self, brackets: list[dict], running_max: float) -> Optional[dict]:
        for b in brackets:
            if b["temp_lo"] <= running_max <= b["temp_hi"]:
                return b
        return None


# ══════════════════════════════════════════════════════
#  STATS DATACLASS
# ══════════════════════════════════════════════════════
@dataclass
class BacktestStats:
    total_days:    int = 0
    total_trades:  int = 0
    wins:          int = 0
    losses:        int = 0

    correct_pct:   float = 0.0
    premature_pct: float = 0.0
    missed_pct:    float = 0.0

    lag_mean_h:    Optional[float] = None
    lag_median_h:  Optional[float] = None
    lag_le1h_pct:  float = 0.0
    lag_le2h_pct:  float = 0.0

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
    """Carrega e normaliza o CSV histórico para a cidade."""
    if not csv_path.exists():
        raise FileNotFoundError(f"{csv_path} não encontrado")

    with open(csv_path, "r", encoding="utf-8") as f:
        first = f.readline()
    sep = "\t" if "\t" in first else ","
    raw = pd.read_csv(csv_path, sep=sep, low_memory=False)

    if "timestamp_utc" not in raw.columns:
        raise ValueError("CSV sem coluna 'timestamp_utc'")

    from zoneinfo import ZoneInfo
    city_tz = ZoneInfo(city.timezone)

    raw["timestamp_utc"] = pd.to_datetime(raw["timestamp_utc"], errors="coerce")
    if raw["timestamp_utc"].dt.tz is not None:
        raw["timestamp_utc"] = raw["timestamp_utc"].dt.tz_convert(None)
    raw["timestamp_utc"] = raw["timestamp_utc"].dt.tz_localize("UTC")

    dt_locals, dates, hours, slots30 = [], [], [], []
    for ts in raw["timestamp_utc"]:
        dt_local = ts.astimezone(city_tz)
        h, m = dt_local.hour, dt_local.minute
        h2, s2 = ceil_slot(h, m)
        if h2 == 24:
            dt_local = (dt_local + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            h2 = 0
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

    # Colunas meteorológicas
    raw["humidity"] = pd.to_numeric(raw["humidity_pct"], errors="coerce").fillna(70.0) if "humidity_pct" in raw.columns else 70.0
    raw["cloud_cover"] = pd.to_numeric(raw["sky_cover"], errors="coerce").fillna(50.0) if "sky_cover" in raw.columns else 50.0
    raw["dewpoint_c"] = pd.to_numeric(raw["dewpt_c"], errors="coerce").fillna(raw["temp_c"] - 10) if "dewpt_c" in raw.columns else (raw["temp_c"] - 10)
    raw["pressure_hpa"] = pd.to_numeric(raw["pressure_hpa"], errors="coerce").fillna(1013.0) if "pressure_hpa" in raw.columns else 1013.0
    raw["wind_dir_deg"] = pd.to_numeric(raw["wind_dir_deg"], errors="coerce").fillna(0.0) if "wind_dir_deg" in raw.columns else 0.0
    raw["wind_speed_kmh"] = pd.to_numeric(raw["wind_speed_kmh"], errors="coerce").fillna(5.0) if "wind_speed_kmh" in raw.columns else 5.0
    raw["wind_gust_kmh"] = pd.to_numeric(raw["wind_gust_kmh"], errors="coerce").fillna(8.0) if "wind_gust_kmh" in raw.columns else 8.0
    raw["uv_index"] = pd.to_numeric(raw["uv_index"], errors="coerce").fillna(3.0) if "uv_index" in raw.columns else 3.0

    df = raw[
        (raw["hour"] >= city.day_start) & (raw["hour"] <= city.day_end)
    ].dropna(subset=["temp_c"]).sort_values(
        ["date", "hour", "slot30"]
    ).reset_index(drop=True)

    return df


# ══════════════════════════════════════════════════════
#  BACKTEST ENGINE
# ══════════════════════════════════════════════════════
def run_backtest(
    df: pd.DataFrame,
    models: dict,
    city: CityConfig,
    strategy: SingleEntryStrategy | PhasedEntryStrategy,
    sim_market: SimulatedMarket,
    start_year: int = 2021,
    end_year: int = 2025,
) -> list[DailyResult]:
    """Executa o backtest num intervalo de anos."""
    df_years = df[df["year"].between(start_year, end_year)].copy()
    years = sorted(df_years["year"].unique())
    results = []
    history_max = init_history_max()

    _console.print(f"\n[bold blue]Backtesting {len(years)} years ({start_year}-{end_year})...[/bold blue]")

    for year in years:
        df_year = df_years[df_years["year"] == year]
        days = sorted(df_year["date"].unique())

        with Progress(
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
            console=_console,
        ) as progress:
            task = progress.add_task(f"[cyan]Year {year}[/cyan]", total=len(days))

            for day in days:
                df_day = df_year[df_year["date"] == day].sort_values(["hour", "slot30"])
                if df_day.empty:
                    continue

                peak_temp = df_day["temp_c"].max()
                peak_row = df_day.loc[df_day["temp_c"].idxmax()]
                peak_hour = float(peak_row["hour"] + peak_row["slot30"] / 60.0)

                trades = []
                bought = False
                last_entered_hour = 0.0

                for _, row in df_day.iterrows():
                    current_slots = df_day[df_day.index <= row.name].to_dict("records")

                    if len(current_slots) < 4:
                        continue

                    current = {
                        "temp_c": row["temp_c"],
                        "hour": row["hour"],
                        "slot30": row["slot30"],
                        "cloud_cover": row["cloud_cover"],
                        "dewpoint_c": row["dewpoint_c"],
                        "wind_dir_deg": row["wind_dir_deg"],
                        "wind_speed_kmh": row["wind_speed_kmh"],
                        "wind_gust_kmh": row["wind_gust_kmh"],
                        "uv_index": row["uv_index"],
                        "pressure_hpa": row["pressure_hpa"],
                        "humidity": row["humidity"],
                    }

                    prev7 = compute_prev7(history_max, day, city.name)
                    current["prev_7d_avg_max"] = prev7

                    running_max = max(s["temp_c"] for s in current_slots)

                    pred = predict_ensemble(
                        models, current_slots, current,
                        row["month"], row["doy"]
                    )

                    p_ensemble = pred["p_ensemble"]
                    hour = row["hour"]

                    brackets = sim_market.get_brackets(p_ensemble, running_max, hour)

                    if isinstance(strategy, SingleEntryStrategy):
                        if not bought and strategy.should_enter(p_ensemble, hour):
                            bracket = strategy.get_bracket(brackets, running_max)
                            if bracket:
                                ask = bracket["ask"]
                                bet_size = 5.0

                                is_correct = (bracket["temp_lo"] <= peak_temp <= bracket["temp_hi"])
                                is_premature = (hour < peak_hour)

                                lag_h = peak_hour - (hour + row["slot30"] / 60.0)

                                trades.append(Trade(
                                    day=day,
                                    bracket_lo=bracket["temp_lo"],
                                    bracket_hi=bracket["temp_hi"],
                                    enter_hour=hour + row["slot30"] / 60.0,
                                    ask=ask,
                                    bet_size=bet_size,
                                    is_correct=is_correct,
                                    is_premature=is_premature,
                                    peak_temp=peak_temp,
                                    lag_h=lag_h if is_premature else None,
                                ))
                                bought = True

                    elif isinstance(strategy, PhasedEntryStrategy):
                        if strategy.should_enter(p_ensemble, hour, last_entered_hour):
                            bracket = strategy.get_bracket(brackets, running_max)
                            if bracket:
                                ask = bracket["ask"]
                                bet_size = 2.0

                                is_correct = (bracket["temp_lo"] <= peak_temp <= bracket["temp_hi"])
                                is_premature = (hour < peak_hour)

                                lag_h = peak_hour - (hour + row["slot30"] / 60.0)

                                trades.append(Trade(
                                    day=day,
                                    bracket_lo=bracket["temp_lo"],
                                    bracket_hi=bracket["temp_hi"],
                                    enter_hour=hour + row["slot30"] / 60.0,
                                    ask=ask,
                                    bet_size=bet_size,
                                    is_correct=is_correct,
                                    is_premature=is_premature,
                                    peak_temp=peak_temp,
                                    lag_h=lag_h if is_premature else None,
                                ))
                                last_entered_hour = hour + row["slot30"] / 60.0

                    update_history_max(history_max, current_slots, city.name)

                results.append(DailyResult(
                    day=day,
                    peak_temp=peak_temp,
                    peak_hour=peak_hour,
                    trades=trades,
                ))

                progress.update(task, advance=1)

    return results


# ══════════════════════════════════════════════════════
#  STATS COMPUTATION
# ══════════════════════════════════════════════════════
def compute_stats(results: list[DailyResult]) -> BacktestStats:
    stats = BacktestStats()

    stats.total_days = len(results)
    all_trades = [t for r in results for t in r.trades]
    stats.total_trades = len(all_trades)

    if stats.total_trades == 0:
        return stats

    stats.wins = sum(1 for t in all_trades if t.is_correct)
    stats.losses = stats.total_trades - stats.wins

    stats.correct_pct = 100.0 * stats.wins / stats.total_trades
    stats.premature_pct = 100.0 * sum(1 for t in all_trades if t.is_premature) / stats.total_trades
    stats.missed_pct = 100.0 - stats.correct_pct - stats.premature_pct

    lags = [t.lag_h for t in all_trades if t.lag_h is not None]
    if lags:
        stats.lag_mean_h = np.mean(lags)
        stats.lag_median_h = np.median(lags)
        stats.lag_le1h_pct = 100.0 * sum(1 for l in lags if l <= 1.0) / len(lags)
        stats.lag_le2h_pct = 100.0 * sum(1 for l in lags if l <= 2.0) / len(lags)

    stats.avg_invested = np.mean([t.ask * t.bet_size for t in all_trades])

    total_invested = sum(t.ask * t.bet_size for t in all_trades)
    total_returned = sum((1.0 / t.ask - 1) * t.bet_size if t.is_correct else -t.ask * t.bet_size for t in all_trades)
    stats.total_pnl = total_returned
    stats.total_return_pct = 100.0 * total_returned / total_invested if total_invested > 0 else 0.0

    # Sharpe/Sortino (requer retornos diários)
    daily_returns = []
    for r in results:
        if r.trades:
            day_pnl = sum((1.0 / t.ask - 1) * t.bet_size if t.is_correct else -t.ask * t.bet_size for t in r.trades)
            day_invested = sum(t.ask * t.bet_size for t in r.trades)
            if day_invested > 0:
                daily_returns.append(day_pnl / day_invested)

    if daily_returns:
        returns = np.array(daily_returns)
        stats.sharpe = np.mean(returns) / np.std(returns) * np.sqrt(365) if np.std(returns) > 0 else 0.0
        downside = returns[returns < 0]
        stats.sortino = np.mean(returns) / np.std(downside) * np.sqrt(365) if len(downside) > 0 and np.std(downside) > 0 else 0.0

    return stats


def print_stats(stats: BacktestStats, city_name: str) -> None:
    table = Table(title=f"[bold cyan]Backtest Results — {city_name}[/bold cyan]", box=rich_box.ROUNDED)

    table.add_column("[bold]Metric[/bold]", style="cyan")
    table.add_column("[bold]Value[/bold]", justify="right")

    table.add_row("Total Days", f"{stats.total_days:,}")
    table.add_row("Total Trades", f"{stats.total_trades:,}")
    table.add_row("Wins / Losses", f"{stats.wins:,} / {stats.losses:,}")
    table.add_row("", "")
    table.add_row("Correct %", f"{stats.correct_pct:.1f}%")
    table.add_row("Premature %", f"{stats.premature_pct:.1f}%")
    table.add_row("Missed %", f"{stats.missed_pct:.1f}%")
    table.add_row("", "")
    if stats.lag_median_h is not None:
        table.add_row("Lag Mean", f"{stats.lag_mean_h:.2f}h")
        table.add_row("Lag Median", f"{stats.lag_median_h:.2f}h")
        table.add_row("Lag ≤1h", f"{stats.lag_le1h_pct:.1f}%")
        table.add_row("Lag ≤2h", f"{stats.lag_le2h_pct:.1f}%")
    table.add_row("", "")
    table.add_row("Avg Invested per Trade", f"${stats.avg_invested:.2f}")
    table.add_row("Total PnL", f"${stats.total_pnl:.2f}")
    table.add_row("Total Return %", f"{stats.total_return_pct:.1f}%")
    table.add_row("", "")
    table.add_row("Sharpe", f"{stats.sharpe:.2f}")
    table.add_row("Sortino", f"{stats.sortino:.2f}")

    _console.print(table)


# ══════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════
def parse_args():
    parser = argparse.ArgumentParser(description="Backtester multi-cidade")
    parser.add_argument("--city", type=str, default="munich", choices=list(CITIES.keys()),
                        help="Cidade para backtest")
    parser.add_argument("--mode", type=str, default="single", choices=["single", "phased", "both"],
                        help="Modo de estratégia")
    parser.add_argument("--years", type=int, default=5,
                        help="Número de anos para backtest")
    parser.add_argument("--start-year", type=int, default=None,
                        help="Ano inicial (default: 2021)")
    parser.add_argument("--ordertype", type=str, default="percent", choices=["fixed", "percent"],
                        help="Tipo de aposta")
    parser.add_argument("--bet", type=float, default=2.0,
                        help="Tamanho da aposta")
    parser.add_argument("--threshold", type=float, default=None,
                        help="Threshold (usa config da cidade se omitido)")
    parser.add_argument("--noise", type=float, default=0.05,
                        help="Noise do SimulatedMarket")
    parser.add_argument("--seed", type=int, default=42,
                        help="Seed para reprodutibilidade")

    return parser.parse_args()


def main():
    args = parse_args()

    city = get_city(args.city)
    set_city(args.city)

    _console.print(f"[bold green]City:[/bold green] {city.name}")
    _console.print(f"[bold green]Timezone:[/bold green] {city.timezone}")
    _console.print(f"[bold green]Model:[/bold green] {city.model_dir}")
    _console.print(f"[bold green]CSV:[/bold green] {city.csv_path}")

    # Load models
    models = load_models(args.city)

    # Load data
    df = load_data(Path(city.csv_path), city)

    # Add year column
    df["year"] = df["date"].apply(lambda d: d.year)

    # Strategy
    threshold = args.threshold or city.threshold or 0.55
    hour_min = city.hour_min or 15

    strategies = []
    if args.mode in ["single", "both"]:
        strategies.append(("single", SingleEntryStrategy(threshold=threshold, hour_min=hour_min)))
    if args.mode in ["phased", "both"]:
        thresholds = [(12, 0.35), (14, 0.45), (16, 0.55), (18, 0.65)]
        strategies.append(("phased", PhasedEntryStrategy(thresholds=thresholds)))

    # SimulatedMarket
    sim_market = SimulatedMarket(temp_range=city.temp_range, noise_std=args.noise, seed=args.seed)

    # Run backtests
    end_year = df["year"].max()
    start_year = args.start_year or (end_year - args.years + 1)

    all_results = {}

    for mode_name, strategy in strategies:
        _console.print(f"\n[bold yellow]Running backtest with {mode_name} strategy...[/bold yellow]")

        results = run_backtest(
            df=df,
            models=models,
            city=city,
            strategy=strategy,
            sim_market=sim_market,
            start_year=start_year,
            end_year=end_year,
        )

        stats = compute_stats(results)
        all_results[mode_name] = {"results": results, "stats": stats}

        print_stats(stats, f"{city.name} ({mode_name})")

        # Save results
        out_file = OUTPUT_DIR / f"{city.name}_{mode_name}_backtest_{start_year}-{end_year}.json"
        with open(out_file, "w") as f:
            json.dump({
                "city": city.name,
                "mode": mode_name,
                "years": f"{start_year}-{end_year}",
                "threshold": threshold,
                "stats": {
                    "total_days": stats.total_days,
                    "total_trades": stats.total_trades,
                    "correct_pct": stats.correct_pct,
                    "premature_pct": stats.premature_pct,
                    "lag_median_h": stats.lag_median_h,
                    "total_pnl": stats.total_pnl,
                    "total_return_pct": stats.total_return_pct,
                    "sharpe": stats.sharpe,
                    "sortino": stats.sortino,
                },
            }, f, indent=2)

        _console.print(f"[dim]Results saved to {out_file}[/dim]")


if __name__ == "__main__":
    main()
