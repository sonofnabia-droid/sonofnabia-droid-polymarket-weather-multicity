"""
calibrate_dual.py
=================
Calibrador de Dual Strategy para multi-cidade.

Optimiza parâmetros:
  - fc_hour_min, fc_hour_max (janela forecast early)
  - fc_p_min (threshold P(forecast correct))
  - fc_ev_margin (margem EV positiva)
  - pk_threshold (threshold P(peak))
  - pk_hour_min (hora mínima peak detection)
  - stop_loss_delta

Uso:
    python calibrate_dual.py --city munich --mode standard --years 3
    python calibrate_dual.py --city munich --mode fast
"""

import argparse
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Optional
import warnings

import numpy as np
import pandas as pd
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, BarColumn, TextColumn, TimeElapsedColumn
from rich import box as rich_box

from cities.config import CityConfig, get_city, CITIES
from predictor import load_models, predict_ensemble, set_city, compute_prev7, init_history_max, update_history_max
from modules.dual_strategy import DualStrategy
from backtester import load_data, SimulatedMarket, ceil_slot

warnings.filterwarnings("ignore")
_console = Console()


@dataclass
class DualCalibResult:
    """Resultado de calibração Dual Strategy."""
    fc_hour_min: int
    fc_hour_max: int
    fc_p_min: float
    fc_ev_margin: float
    pk_threshold: float
    pk_hour_min: int
    stop_loss_delta: float

    total_days: int = 0
    trades: int = 0
    wins: int = 0
    fc_trades: int = 0
    pk_trades: int = 0
    stop_losses: int = 0

    total_invested: float = 0.0
    total_pnl: float = 0.0
    win_pct: float = 0.0
    roi_pct: float = 0.0
    outcome_score: float = 0.0

    lag_mean_h: float = 0.0
    lag_median_h: float = 0.0


def fetch_wu_forecast_max(df_day: pd.DataFrame) -> Optional[int]:
    """Busca forecast máximo WU do dia (simulado: usa peak real como proxy)."""
    if df_day.empty:
        return None
    return int(round(df_day["temp_c"].max()))


def fetch_om_forecast_max(df_day: pd.DataFrame) -> Optional[int]:
    """Busca forecast máximo OM do dia (simulado: usa peak real como proxy)."""
    if df_day.empty:
        return None
    # OM é geralmente menos preciso, adiciona pequeno erro
    peak = df_day["temp_c"].max()
    error = np.random.normal(0, 1.0)
    return int(round(peak + error))


def run_single_backtest(
    df: pd.DataFrame,
    models: dict,
    city: CityConfig,
    sim_market: SimulatedMarket,
    params: dict,
) -> DualCalibResult:
    """Executa backtest para uma combinação de parâmetros."""
    # Criar DualStrategy com os parâmetros
    strategy = DualStrategy(city, **params)

    total_days = 0
    trades = 0
    wins = 0
    fc_trades = 0
    pk_trades = 0
    stop_losses = 0
    total_invested = 0.0
    total_pnl = 0.0
    lags = []
    history_max = init_history_max()

    for day, day_df in df.groupby("date"):
        total_days += 1
        day_df = day_df.sort_values(["hour", "slot30"]).reset_index(drop=True)

        peak_temp = day_df["temp_c"].max()
        peak_row = day_df.loc[day_df["temp_c"].idxmax()]
        peak_h = int(peak_row["hour"])
        peak_s = int(peak_row["slot30"])
        peak_hour_float = peak_h + peak_s / 60.0

        # Buscar forecasts (simulado)
        wu_forecast_max = fetch_wu_forecast_max(day_df)
        om_forecast_max = fetch_om_forecast_max(day_df)

        strategy.reset()
        bought = False
        bracket_record = None
        stop_triggered = False

        current_slots = []

        for _, row in day_df.iterrows():
            h = int(row["hour"])
            s = int(row["slot30"])
            t = float(row["temp_c"])

            current_slots.append({
                "temp_c": t,
                "hour": h,
                "slot30": s,
                "cloud_cover": float(row["cloud_cover"]),
                "humidity": float(row["humidity"]),
                "dewpoint_c": float(row["dewpoint_c"]),
                "pressure_hpa": float(row["pressure_hpa"]),
                "wind_dir_deg": float(row["wind_dir_deg"]),
                "wind_speed_kmh": float(row["wind_speed_kmh"]),
                "wind_gust_kmh": float(row["wind_gust_kmh"]),
                "uv_index": float(row["uv_index"]),
            })

            if len(current_slots) < 4:
                continue

            running_max = max(sl["temp_c"] for sl in current_slots)

            # Forecast para o modelo ML
            current = {
                "temp_c": t,
                "hour": h,
                "slot30": s,
                "cloud_cover": row["cloud_cover"],
                "humidity": row["humidity"],
                "dewpoint_c": row["dewpoint_c"],
                "wind_dir_deg": row["wind_dir_deg"],
                "wind_speed_kmh": row["wind_speed_kmh"],
                "wind_gust_kmh": row["wind_gust_kmh"],
                "uv_index": row["uv_index"],
                "pressure_hpa": row["pressure_hpa"],
            }

            prev7 = compute_prev7(history_max, day, city.name)
            current["prev_7d_avg_max"] = prev7

            month = int(row["month"])
            doy = int(row["doy"])

            pred = predict_ensemble(models, current_slots, current, month, doy)
            p_peak = pred.get("p_ensemble", 0.0)

            # Market simulado
            brackets = sim_market.get_brackets(p_peak, running_max, h)
            market_data = {"brackets": brackets}

            # Avaliar DualStrategy
            if not bought and not stop_triggered:
                actions = strategy.evaluate(
                    p_peak=p_peak,
                    hour=h,
                    market=market_data,
                    running_max=running_max,
                    wu_forecast_max=wu_forecast_max,
                    om_forecast_max=om_forecast_max,
                    cloud_cover=row["cloud_cover"],
                    humidity=row["humidity"],
                    month=month,
                    uv_index=row["uv_index"],
                )

                for action in actions:
                    if action.get("size_usdc", 0) > 0:
                        bracket = action.get("bracket")
                        if bracket:
                            bought = True
                            bracket_record = {
                                **bracket,
                                "strategy": action.get("strategy"),
                                "enter_hour": h + s / 60.0,
                                "ask": bracket.get("ask", 0.5),
                            }

                            if action.get("strategy") == "forecast_early":
                                fc_trades += 1
                            else:
                                pk_trades += 1

            # Verificar stop-loss
            if bought and not stop_triggered and bracket_record:
                stop_check = strategy.check_stop_loss(t)
                if stop_check:
                    stop_triggered = True
                    stop_losses += 1
                    # Assume perda total no stop-loss
                    pnl = -bracket_record["ask"] * strategy.parcel_size
                    total_pnl += pnl
                    trades += 1
                    break

            # Check se ganhou (no fim do dia)
            if bought and not stop_triggered and h >= city.day_end - 1:
                bracket_lo = bracket_record["temp_lo"]
                bracket_hi = bracket_record["temp_hi"]
                won = bracket_lo <= peak_temp <= bracket_hi

                ask = bracket_record["ask"]
                if won:
                    pnl = (1.0 / ask - 1.0) * strategy.parcel_size
                    wins += 1
                else:
                    pnl = -ask * strategy.parcel_size

                total_pnl += pnl
                total_invested += ask * strategy.parcel_size
                trades += 1

                lag = peak_hour_float - bracket_record["enter_hour"]
                if lag > 0:
                    lags.append(lag)

                break

        update_history_max(history_max, current_slots, city.name)

    return DualCalibResult(
        fc_hour_min=params["fc_hour_min"],
        fc_hour_max=params["fc_hour_max"],
        fc_p_min=params["fc_p_min"],
        fc_ev_margin=params["fc_ev_margin"],
        pk_threshold=params["pk_threshold"],
        pk_hour_min=params["pk_hour_min"],
        stop_loss_delta=params["stop_loss_delta"],
        total_days=total_days,
        trades=trades,
        wins=wins,
        fc_trades=fc_trades,
        pk_trades=pk_trades,
        stop_losses=stop_losses,
        total_invested=total_invested,
        total_pnl=total_pnl,
        win_pct=wins / trades * 100 if trades > 0 else 0,
        roi_pct=total_pnl / total_invested * 100 if total_invested > 0 else 0,
        outcome_score=(wins / trades * 100 *
                      np.log10(1 + trades / total_days * 365)
                      if trades > 0 else 0),
        lag_mean_h=float(np.mean(lags)) if lags else 0,
        lag_median_h=float(np.median(lags)) if lags else 0,
    )


def run_grid_search(
    df: pd.DataFrame,
    models: dict,
    city: CityConfig,
    sim_market: SimulatedMarket,
    param_grid: dict,
) -> list[DualCalibResult]:
    """Executa grid search de parâmetros."""
    keys = list(param_grid.keys())
    results = []

    # Gerar todas as combinações
    import itertools
    combinations = list(itertools.product(*param_grid.values()))

    total = len(combinations)

    with Progress(
        TextColumn("[cyan]Grid search..."),
        BarColumn(),
        TextColumn("{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        console=_console,
    ) as progress:
        task = progress.add_task("", total=total)

        for combo in combinations:
            params = dict(zip(keys, combo))
            result = run_single_backtest(df, models, city, sim_market, params)
            results.append(result)
            progress.update(task, advance=1)

    return results


def get_grid(mode: str) -> dict:
    """Retorna grid de parâmetros para o modo."""
    if mode == "fast":
        return {
            "fc_hour_min": [10],
            "fc_hour_max": [14],
            "fc_p_min": [0.70, 0.75, 0.80],
            "fc_ev_margin": [0.05],
            "pk_threshold": [0.60, 0.65, 0.70],
            "pk_hour_min": [11],
            "stop_loss_delta": [1.0],
        }
    elif mode == "standard":
        return {
            "fc_hour_min": [10],
            "fc_hour_max": [14],
            "fc_p_min": [0.65, 0.70, 0.75, 0.80],
            "fc_ev_margin": [0.03, 0.05, 0.07],
            "pk_threshold": [0.55, 0.60, 0.65, 0.70],
            "pk_hour_min": [10, 11, 12],
            "stop_loss_delta": [0.5, 1.0, 1.5],
        }
    elif mode == "detailed":
        return {
            "fc_hour_min": [9, 10, 11],
            "fc_hour_max": [13, 14, 15],
            "fc_p_min": [0.60, 0.65, 0.70, 0.75, 0.80],
            "fc_ev_margin": [0.02, 0.03, 0.05, 0.07, 0.10],
            "pk_threshold": [0.50, 0.55, 0.60, 0.65, 0.70, 0.75],
            "pk_hour_min": [9, 10, 11, 12],
            "stop_loss_delta": [0.5, 1.0, 1.5, 2.0],
        }
    else:
        raise ValueError(f"Modo desconhecido: {mode}")


def print_results(results: list[DualCalibResult], n: int = 20) -> None:
    """Imprime top resultados."""
    sorted_results = sorted(results, key=lambda r: -r.outcome_score)[:n]

    table = Table(
        box=rich_box.ROUNDED,
        show_header=True,
        header_style="bold cyan",
        title=f"Top {n} Dual Strategy Configs",
    )

    table.add_column("#", justify="right", width=3)
    table.add_column("FC", justify="right", width=4)
    table.add_column("Pmin", justify="right", width=5)
    table.add_column("EV", justify="right", width=4)
    table.add_column("Pk", justify="right", width=4)
    table.add_column("PkH", justify="right", width=4)
    table.add_column("Trd/y", justify="right", width=6)
    table.add_column("Win%", justify="right", width=6)
    table.add_column("FC%", justify="right", width=5)
    table.add_column("SL%", justify="right", width=5)
    table.add_column("Score", justify="right", width=7)

    for i, r in enumerate(sorted_results, 1):
        trades_per_year = r.trades / (r.total_days / 365) if r.total_days else 0
        fc_pct = r.fc_trades / r.trades * 100 if r.trades else 0
        sl_pct = r.stop_losses / r.trades * 100 if r.trades else 0

        c_score = "green" if r.outcome_score > 100 else "yellow" if r.outcome_score > 50 else "red"
        c_win = "green" if r.win_pct > 75 else "yellow" if r.win_pct > 55 else "red"

        table.add_row(
            str(i),
            f"{r.fc_hour_min}-{r.fc_hour_max}",
            f"{r.fc_p_min:.2f}",
            f"{r.fc_ev_margin:.2f}",
            f"{r.pk_threshold:.2f}",
            f"{r.pk_hour_min}",
            f"{trades_per_year:.0f}",
            f"[{c_win}]{r.win_pct:.1f}%[/{c_win}]",
            f"{fc_pct:.0f}%",
            f"{sl_pct:.0f}%",
            f"[{c_score}]{r.outcome_score:.1f}[/{c_score}]",
        )

    _console.print(table)


def print_best_config(result: DualCalibResult, city_name: str) -> None:
    """Imprime a melhor configuração em formato de código."""
    _console.print("\n[bold cyan]Melhor configuração Dual Strategy:[/bold cyan]\n")
    _console.print(
        f"[dim]  # {city_name.title()} — Dual Strategy[/dim]\n"
        f'  fc_hour_min={result.fc_hour_min},\n'
        f'  fc_hour_max={result.fc_hour_max},\n'
        f'  fc_p_min={result.fc_p_min:.2f},\n'
        f'  fc_ev_margin={result.fc_ev_margin:.2f},\n'
        f'  pk_threshold={result.pk_threshold:.2f},\n'
        f'  pk_hour_min={result.pk_hour_min},\n'
        f'  stop_loss_delta={result.stop_loss_delta:.1f},\n'
    )
    trades_per_year = result.trades / (result.total_days / 365) if result.total_days else 0
    _console.print(
        f"[dim]  # Estatísticas: {trades_per_year:.0f} trades/ano, win={result.win_pct:.1f}%, "
        f"score={result.outcome_score:.1f}[/dim]"
    )


def main():
    parser = argparse.ArgumentParser(description="Calibração Dual Strategy")
    parser.add_argument("--city", type=str, default="munich", choices=list(CITIES.keys()),
                        help="Cidade para calibrar")
    parser.add_argument("--years", type=int, default=3,
                        help="Anos de histórico")
    parser.add_argument("--mode", choices=["fast", "standard", "detailed"],
                        default="standard",
                        help="Densidade do grid")
    parser.add_argument("--top", type=int, default=20,
                        help="Top resultados a mostrar")

    args = parser.parse_args()

    city = get_city(args.city)

    # Verificar se cidade tem WU
    if not city.wu_history_path:
        _console.print(f"[yellow]Aviso: {args.city.title()} não tem WU history path. "
                       f"Dual Strategy Forecast Early não funcionará corretamente.[/yellow]")

    set_city(args.city)

    _console.print(f"\n[bold cyan]{city.name.title()} Dual Strategy Calibration[/bold cyan]\n")

    _console.print("[1/4] Carregando modelo...")
    models = load_models(args.city)

    _console.print("[2/4] Carregando dados...")
    df_all = load_data(Path(city.csv_path), city)
    df_all["date"] = pd.to_datetime(df_all["date"]).dt.date
    df_all["year"] = [d.year for d in df_all["date"]]

    end_date = date.today() - timedelta(days=1)
    start_date = date(end_date.year - args.years + 1, 1, 1)
    df = df_all[(df_all["date"] >= start_date) & (df_all["date"] <= end_date)].copy()
    _console.print(f"  Dataset: {len(df):,} slots, {df['date'].nunique()} dias")

    _console.print("[3/4] Configurando SimulatedMarket...")
    sim_market = SimulatedMarket(temp_range=city.temp_range, noise_std=0.05, seed=42)

    param_grid = get_grid(args.mode)
    total_combos = 1
    for values in param_grid.values():
        total_combos *= len(values)

    _console.print(f"  Grid search: {total_combos} combinações")

    _console.print("[4/4] Executando grid search...")
    results = run_grid_search(df, models, city, sim_market, param_grid)

    _console.print("\n[bold green]Resultados:[/bold green]\n")
    print_results(results, n=args.top)

    best = max(results, key=lambda r: r.outcome_score)
    print_best_config(best, args.city)


if __name__ == "__main__":
    main()
