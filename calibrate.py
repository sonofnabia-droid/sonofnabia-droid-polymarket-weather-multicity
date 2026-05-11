"""
calibrate.py
============
Calibrador genérico multi-cidade. Usa predictor.py e cities/config.py.

Uso:
    python calibrate.py --city munich --mode standard --years 5
    python calibrate.py --city dallas --mode full --metric outcome
    python calibrate.py --city ankara --mode fast

Modos de grid:
  --mode fast      21 combinações   (~30s)
  --mode standard  69 combinações   (~1min)   [DEFAULT]
  --mode detailed  161 combinações  (~3min)
  --mode full      570 combinações  (~7min)

Métricas (--metric):
  roi      Optimiza ROI $ via SimulatedMarket (legacy)
  outcome  Optimiza win-rate × log(volume) — métrica HONESTA [RECOMENDADO]
"""

import argparse
from datetime import date, timedelta
from pathlib import Path
import warnings

import numpy as np
import pandas as pd
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, BarColumn, TextColumn, TimeElapsedColumn
from rich import box as rich_box

from cities.config import CityConfig, get_city, CITIES
from predictor import load_models, predict_ensemble, set_city, compute_prev7
from backtester import load_data, ceil_slot, SimulatedMarket

warnings.filterwarnings("ignore")
_console = Console()


# ══════════════════════════════════════════════════════
#  BRACKET CONTAINS PEAK
# ══════════════════════════════════════════════════════
def bracket_contains_peak(lo: float, hi: float, peak: float) -> bool:
    """Verifica se o bracket contém o pico real (paridade com backtester.py)."""
    peak_int = int(round(peak))
    if hi >= 99:
        return peak_int >= int(round(lo))
    if lo <= -99:
        return peak_int <= int(round(hi))
    return int(round(lo)) <= peak_int <= int(round(hi))

def pnl_per_dollar(ask: float, won: bool) -> float:
    """PnL por $ investido: (1/ask - 1) se ganha, -1.0 se perde."""
    if won:
        return (1.0 / ask) - 1.0
    return -1.0


# ══════════════════════════════════════════════════════
#  GERAR SINAL p_ensemble PARA TODOS OS SLOTS
# ══════════════════════════════════════════════════════
def generate_daily_signals(df: pd.DataFrame, models: dict, city: CityConfig) -> pd.DataFrame:
    """Para cada slot, calcula p_ensemble e running_max."""
    rows = []
    history_max = {}
    day_start = city.day_start
    day_end = city.day_end

    with Progress(
        TextColumn("[cyan]Gerando sinais..."), BarColumn(),
        TextColumn("{task.percentage:>3.0f}%"),
        TimeElapsedColumn(), console=_console,
    ) as progress:
        task = progress.add_task("", total=df["date"].nunique())

        for d, day_df in df.groupby("date"):
            progress.update(task, advance=1)

            day_df = day_df.sort_values(["hour", "slot30"]).reset_index(drop=True)

            peak_temp = day_df["temp_c"].max()
            peak_matches = day_df[day_df["temp_c"] == peak_temp]
            if len(peak_matches) == 0:
                continue
            peak_row = peak_matches.iloc[-1]  # última ocorrência (paridade com train.py)
            peak_h = int(peak_row["hour"])
            peak_s = int(peak_row["slot30"])

            month = int(day_df["month"].iloc[0])
            doy = int(day_df["doy"].iloc[0])

            slots_so_far = []

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

                prev7 = compute_prev7(history_max, d, city.name)

                current = {
                    **slot_entry,
                    "prev_7d_avg_max": prev7,
                }

                if h < day_start or len(slots_so_far) < 4:
                    p_ens = 0.0
                else:
                    ens = predict_ensemble(models, slots_so_far, current, month, doy)
                    p_ens = ens.get("p_ensemble", 0.0)

                running_max = max(sl["temp_c"] for sl in slots_so_far)

                rows.append({
                    "date": d, "hour": h, "slot30": s, "temp_c": t,
                    "p_ensemble": p_ens,
                    "running_max": running_max,
                    "peak_temp_day": peak_temp,
                    "peak_hour_day": peak_h,
                    "peak_slot30_day": peak_s,
                })

            history_max[d] = peak_temp

    return pd.DataFrame(rows)


# ══════════════════════════════════════════════════════
#  SIMULAR ESTRATÉGIA SIMPLES PARA UM (threshold, hour_min)
# ══════════════════════════════════════════════════════
def simulate_strategy(signals_df: pd.DataFrame, city: CityConfig,
                      threshold: float, hour_min: int, hour_max: int = 20,
                      realistic_market: bool = False,
                      market_sim: SimulatedMarket = None) -> dict:
    """
    Para cada dia, encontra o primeiro slot onde:
      - hora em [hour_min, hour_max)
      - p_ensemble >= threshold

    Aposta $5 no bracket do running_max nesse momento.
    """
    PARCEL = 5.0
    total_days = 0
    trades = 0
    wins = 0
    premature = 0
    at_peak = 0
    late = 0
    total_pnl = 0.0
    total_invested = 0.0
    lags_hours = []
    winning_asks = []
    losing_asks = []

    for d, day_df in signals_df.groupby("date"):
        total_days += 1
        day_df = day_df.sort_values(["hour", "slot30"]).reset_index(drop=True)

        window = day_df[(day_df["hour"] >= hour_min) & (day_df["hour"] < hour_max)]
        firing = window[window["p_ensemble"] >= threshold]
        if firing.empty:
            continue

        first = firing.iloc[0]
        entry_h = int(first["hour"])
        entry_s = int(first["slot30"])
        entry_rmax = float(first["running_max"])
        peak_temp = float(first["peak_temp_day"])
        peak_h = int(first["peak_hour_day"])
        peak_s = int(first["peak_slot30_day"])
        p_at_entry = float(first["p_ensemble"])

        # Bracket alvo: comprar o bracket que contém o running_max arredondado.
        # A calibração deve usar sempre um mercado simulado consistente com o backtest.
        market_sim = market_sim or SimulatedMarket(temp_range=city.temp_range, noise_std=0.08, seed=42)
        brackets = market_sim.get_brackets(p_at_entry, entry_rmax, entry_h)
        target_temp = int(round(entry_rmax))

        best = None
        for b in brackets:
            lo, hi = b["temp_lo"], b["temp_hi"]
            if hi >= 99 and target_temp >= lo:
                best = b
                break
            if lo <= -99 and target_temp <= hi:
                best = b
                break
            if lo <= target_temp <= hi:
                best = b
                break

        if best is None:
            best = min(
                brackets,
                key=lambda b: abs(((b["temp_lo"] + b["temp_hi"]) / 2) - target_temp)
            )

        bracket_lo = best["temp_lo"]
        bracket_hi = best["temp_hi"]
        ask = best["ask"]

        won = bracket_contains_peak(bracket_lo, bracket_hi, peak_temp)

        pnl = PARCEL * pnl_per_dollar(ask, won)

        total_invested += PARCEL
        total_pnl += pnl
        trades += 1
        if won:
            wins += 1
            winning_asks.append(ask)
        else:
            losing_asks.append(ask)

        entry_sidx = entry_h * 2 + entry_s // 30
        peak_sidx = peak_h * 2 + peak_s // 30
        lag_slots = peak_sidx - entry_sidx
        lag_h = lag_slots * 0.5
        lags_hours.append(lag_h)

        if lag_h > 0:
            premature += 1
        elif lag_h == 0:
            at_peak += 1
        else:
            late += 1

    return {
        "threshold": threshold,
        "hour_min": hour_min,
        "total_days": total_days,
        "trades": trades,
        "trade_rate_pct": trades / total_days * 100 if total_days else 0,
        "wins": wins,
        "win_pct": wins / trades * 100 if trades else 0,
        "premature_pct": premature / trades * 100 if trades else 0,
        "at_peak_pct": at_peak / trades * 100 if trades else 0,
        "late_pct": late / trades * 100 if trades else 0,
        "median_lag_h": float(np.median(lags_hours)) if lags_hours else 0,
        "mean_lag_h": float(np.mean(lags_hours)) if lags_hours else 0,
        "total_invested": total_invested,
        "total_pnl": total_pnl,
        "roi_pct": total_pnl / total_invested * 100 if total_invested else 0,
        "avg_winning_ask": float(np.mean(winning_asks)) if winning_asks else 0,
        "avg_losing_ask": float(np.mean(losing_asks)) if losing_asks else 0,
        # outcome_score — independente de preços simulados
        "outcome_score": (wins / trades * 100 *
                          np.log10(1 + (trades / total_days * 365 if total_days else 0))
                          if trades > 0 else 0),
    }


# ══════════════════════════════════════════════════════
#  GRID SEARCH
# ══════════════════════════════════════════════════════
def run_grid_search(signals_df: pd.DataFrame, city: CityConfig,
                    thresholds: list, hour_mins: list,
                    realistic_market: bool = False) -> list:
    results = []

    total_combos = len(thresholds) * len(hour_mins)
    with Progress(
        TextColumn("[cyan]Grid search..."), BarColumn(),
        TextColumn("{task.percentage:>3.0f}%"),
        TimeElapsedColumn(), console=_console,
    ) as progress:
        task = progress.add_task("", total=total_combos)

        for thr in thresholds:
            for hmin in hour_mins:
                market_sim = (
                    SimulatedMarket(temp_range=city.temp_range, noise_std=0.08, seed=42)
                    if realistic_market else None
                )
                r = simulate_strategy(signals_df, city, thr, hmin,
                                      realistic_market=realistic_market,
                                      market_sim=market_sim)
                results.append(r)
                progress.update(task, advance=1)

    return results


def _select_best_result(results: list[dict], metric: str) -> dict | None:
    viable = [r for r in results if r["trades"] >= 30]
    if not viable:
        viable = results
    if not viable:
        return None
    sort_key = "outcome_score" if metric == "outcome" else "roi_pct"
    return max(viable, key=lambda r: r.get(sort_key, 0))


def _validation_years(signals_df: pd.DataFrame, n_years: int = 1) -> list[int]:
    years = sorted(pd.to_datetime(signals_df["date"]).dt.year.unique())
    if len(years) <= n_years:
        return []
    return [int(y) for y in years[-n_years:]]


def _result_summary(result: dict, n_days: int) -> dict:
    return {
        "outcome_score":   round(result.get("outcome_score", 0), 4),
        "roi_pct":         round(result.get("roi_pct", 0), 2),
        "win_pct":         round(result.get("win_pct", 0), 2),
        "n_trades":        int(result.get("trades", 0)),
        "trades_per_year": round(result.get("trades", 0) / n_days * 365, 1) if n_days else 0,
        "median_lag_h":    round(result.get("median_lag_h", 0), 2),
        "n_days":          int(n_days),
    }


# ══════════════════════════════════════════════════════
#  TABELAS E ANÁLISES
# ══════════════════════════════════════════════════════
def print_p_distribution(signals_df: pd.DataFrame, min_hour: int) -> None:
    """Distribuição de p_ensemble no pico vs fora."""
    signals_df = signals_df.copy()
    signals_df["is_peak_slot"] = (
        (signals_df["hour"] == signals_df["peak_hour_day"]) &
        (signals_df["slot30"] == signals_df["peak_slot30_day"])
    )

    _console.rule("[bold]Distribuição de p_ensemble[/bold]")

    peak_slots = signals_df[signals_df["is_peak_slot"]]["p_ensemble"]
    non_peak = signals_df[(~signals_df["is_peak_slot"]) & (signals_df["hour"] >= min_hour)]["p_ensemble"]

    tbl = Table(box=rich_box.SIMPLE, show_header=True)
    for c in ["Percentil", "Slots do pico real", "Slots fora do pico", "Ratio"]:
        tbl.add_column(c, justify="right")

    for pct in [10, 25, 50, 75, 90, 95, 99]:
        p_peak = np.percentile(peak_slots, pct)
        p_nonpeak = np.percentile(non_peak, pct)
        ratio = p_peak / p_nonpeak if p_nonpeak > 0.001 else float('inf')
        ratio_str = f"{ratio:.1f}x" if ratio < 100 else "inf"
        tbl.add_row(f"p{pct}", f"{p_peak:.3f}", f"{p_nonpeak:.3f}", ratio_str)

    _console.print(tbl)
    _console.print(
        f"\n[dim]Slots do pico real: N={len(peak_slots)}, mean={peak_slots.mean():.3f}\n"
        f"Slots fora do pico: N={len(non_peak)}, mean={non_peak.mean():.3f}\n"
        f"Razão das médias: {peak_slots.mean() / non_peak.mean():.1f}x [/dim]"
    )


def print_top_results(results: list, n: int = 30, sort_by: str = "roi_pct",
                       metric: str = "roi") -> None:
    sorted_results = sorted(results, key=lambda r: -r[sort_by])[:n]

    title = (f"Top {n} — ordenado por win-rate × log(volume)"
             if metric == "outcome"
             else f"Top {n} — ordenado por {sort_by}")
    table = Table(box=rich_box.ROUNDED, show_header=True, header_style="bold cyan",
                  title=title)

    if metric == "outcome":
        table.add_column("#",       justify="right", width=3)
        table.add_column("Thr",     justify="right", width=5)
        table.add_column("HMin",    justify="right", width=4)
        table.add_column("Trd/y",   justify="right", width=5)
        table.add_column("Win%",    justify="right", width=6)
        table.add_column("Lag",     justify="right", width=6)
        table.add_column("Prem%",   justify="right", width=6)
        table.add_column("Peak%",   justify="right", width=6)
        table.add_column("Late%",   justify="right", width=6)
        table.add_column("Score",   justify="right", width=7)
    else:
        table.add_column("#",       justify="right", width=3)
        table.add_column("Thr",     justify="right", width=5)
        table.add_column("HMin",    justify="right", width=4)
        table.add_column("Trd/y",   justify="right", width=5)
        table.add_column("Win%",    justify="right", width=6)
        table.add_column("Lag",     justify="right", width=6)
        table.add_column("AskW",    justify="right", width=5)
        table.add_column("AskL",    justify="right", width=5)
        table.add_column("Prem%",   justify="right", width=6)
        table.add_column("Peak%",   justify="right", width=6)
        table.add_column("Inv$",    justify="right", width=7)
        table.add_column("PnL$",    justify="right", width=8)
        table.add_column("ROI%",    justify="right", width=8)

    for i, r in enumerate(sorted_results, 1):
        roi = r["roi_pct"]
        win = r["win_pct"]
        trades_per_year = r["trades"] / (r["total_days"] / 365) if r["total_days"] else 0
        score = r.get("outcome_score", 0)

        c_roi = "green" if roi > 20 else "yellow" if roi > 0 else "red"
        c_win = "green" if win > 75 else "yellow" if win > 55 else "red"
        c_lag = "green" if abs(r["median_lag_h"]) < 0.5 else "yellow" if abs(r["median_lag_h"]) < 1.5 else "red"
        c_score = "green" if score > 100 else "yellow" if score > 50 else "red"

        if metric == "outcome":
            table.add_row(
                str(i),
                f"{r['threshold']:.3f}",
                f"{r['hour_min']}h",
                f"{trades_per_year:.0f}",
                f"[{c_win}]{win:.1f}%[/{c_win}]",
                f"[{c_lag}]{r['median_lag_h']:+.1f}h[/{c_lag}]",
                f"{r['premature_pct']:.0f}%",
                f"{r['at_peak_pct']:.0f}%",
                f"{r['late_pct']:.0f}%",
                f"[{c_score}]{score:.1f}[/{c_score}]",
            )
        else:
            ask_win = r.get("avg_winning_ask", 0)
            ask_loss = r.get("avg_losing_ask", 0)
            c_aw = "red" if ask_win < 0.20 else "yellow" if ask_win < 0.40 else "white"
            table.add_row(
                str(i),
                f"{r['threshold']:.3f}",
                f"{r['hour_min']}h",
                f"{trades_per_year:.0f}",
                f"[{c_win}]{win:.1f}%[/{c_win}]",
                f"[{c_lag}]{r['median_lag_h']:+.1f}h[/{c_lag}]",
                f"[{c_aw}]{ask_win:.2f}[/{c_aw}]",
                f"{ask_loss:.2f}",
                f"{r['premature_pct']:.0f}%",
                f"{r['at_peak_pct']:.0f}%",
                f"${r['total_invested']:,.0f}",
                f"[{c_roi}]${r['total_pnl']:+,.0f}[/{c_roi}]",
                f"[{c_roi}]{roi:+.1f}%[/{c_roi}]",
            )

    _console.print(table)


def print_heatmap(results: list, metric: str = "roi") -> None:
    """Heatmap: métrica escolhida como função de (threshold, hour_min)."""
    if metric == "outcome":
        value_col = "outcome_score"
        title = "Heatmap OUTCOME SCORE (threshold x hour_min)"
        def _colorize(v):
            if v > 150: return f"[bold green]{v:>5.0f}[/bold green]"
            if v > 100: return f"[green]{v:>5.0f}[/green]"
            if v > 50:  return f"[yellow]{v:>5.0f}[/yellow]"
            if v > 0:   return f"[red]{v:>5.0f}[/red]"
            return f"[dim]{v:>5.0f}[/dim]"
        legend = ("[bold green]>150[/bold green]  [green]>100[/green]  "
                  "[yellow]>50[/yellow]  [red]>0[/red]  [dim]=0[/dim]")
    else:
        value_col = "roi_pct"
        title = "Heatmap ROI (threshold x hour_min)"
        def _colorize(roi):
            if roi > 30: return f"[bold green]{roi:+5.1f}[/bold green]"
            if roi > 15: return f"[green]{roi:+5.1f}[/green]"
            if roi > 0:  return f"[yellow]{roi:+5.1f}[/yellow]"
            if roi > -15: return f"[red]{roi:+5.1f}[/red]"
            return f"[dim red]{roi:+5.1f}[/dim red]"
        legend = ("[bold green]>30%[/bold green]  [green]>15%[/green]  "
                  "[yellow]>0%[/yellow]  [red]<0%[/red]  [dim red]<-15%[/dim red]")

    _console.rule(f"[bold]{title}[/bold]")

    df = pd.DataFrame(results)
    pivot = df.pivot_table(index="threshold", columns="hour_min", values=value_col)

    hour_mins = sorted(pivot.columns)
    thresholds = sorted(pivot.index, reverse=True)

    tbl = Table(box=rich_box.SIMPLE, show_header=True, header_style="bold")
    tbl.add_column("thr \\ hmin", justify="right", style="dim")
    for h in hour_mins:
        tbl.add_column(f"{h}h", justify="right")

    for thr in thresholds:
        row = [f"{thr:.3f}"]
        for h in hour_mins:
            val = pivot.loc[thr, h]
            if pd.isna(val):
                row.append("-")
            else:
                row.append(_colorize(val))
        tbl.add_row(*row)

    _console.print(tbl)
    _console.print(f"[dim]Legenda: {legend}[/dim]")


def print_stability_analysis(results: list, metric: str = "roi") -> None:
    """Mede estabilidade da métrica escolhida à volta da melhor config."""
    viable = [r for r in results if r["trades"] >= 30]
    if not viable:
        return

    sort_key = "outcome_score" if metric == "outcome" else "roi_pct"
    best = max(viable, key=lambda r: r[sort_key])
    best_thr = best["threshold"]
    best_hmin = best["hour_min"]

    _console.rule(f"[bold]Análise de estabilidade à volta da melhor config "
                  f"({'win-rate × volume' if metric == 'outcome' else 'ROI'})[/bold]")
    metric_col = "outcome_score" if metric == "outcome" else "roi_pct"
    metric_label = "Score" if metric == "outcome" else "ROI%"
    metric_fmt = (lambda v: f"{v:>5.1f}") if metric == "outcome" else (lambda v: f"{v:+.1f}%")

    _console.print(
        f"[dim]Melhor config: thr={best_thr:.3f}, hmin={best_hmin}h -> "
        f"{metric_label}={metric_fmt(best[metric_col])}[/dim]\n"
        "Se mudar os params ligeiramente, quanto perdes?\n"
    )

    neighbors = []
    for r in viable:
        dthr = abs(r["threshold"] - best_thr)
        dhmin = abs(r["hour_min"] - best_hmin)
        if dthr <= 0.05 and dhmin <= 1 and (dthr > 0 or dhmin > 0):
            neighbors.append((dthr, dhmin, r))

    if not neighbors:
        _console.print("[dim]Sem vizinhos suficientes no grid[/dim]")
        return

    tbl = Table(box=rich_box.SIMPLE)
    for c in ["Thr", "HMin", "Trades/ano", "Win%", metric_label, f"Delta {metric_label}"]:
        tbl.add_column(c, justify="right")

    for _, _, r in sorted(neighbors, key=lambda x: (x[0], x[1])):
        drr = r[metric_col] - best[metric_col]
        bad_thr = -5 if metric == "roi" else -10
        c = "red" if drr < bad_thr else "yellow" if drr < 0 else "green"
        trades_per_year = r["trades"] / (r["total_days"] / 365)
        tbl.add_row(
            f"{r['threshold']:.3f}",
            f"{r['hour_min']}h",
            f"{trades_per_year:.0f}",
            f"{r['win_pct']:.1f}%",
            metric_fmt(r[metric_col]),
            f"[{c}]{drr:+.1f}{'pp' if metric == 'roi' else ''}[/{c}]",
        )
    _console.print(tbl)

    max_drop = min(r[metric_col] - best[metric_col] for _, _, r in neighbors)
    bad_drop = -10 if metric == "roi" else -20
    moderate_drop = -5 if metric == "roi" else -10
    if max_drop < bad_drop:
        _console.print(f"\n[yellow]AVISO: queda máxima em vizinhos: {max_drop:.1f} — config pouco estável[/yellow]")
    elif max_drop < moderate_drop:
        _console.print(f"\n[yellow]Queda máxima em vizinhos: {max_drop:.1f} — moderadamente estável[/yellow]")
    else:
        _console.print(f"\n[green]Queda máxima em vizinhos: {max_drop:.1f}pp — config estável[/green]")


def recommend_thresholds(results: list, metric: str = "roi") -> None:
    """Recomendações focadas em SingleEntry."""
    _console.rule("[bold green]RECOMENDAÇÕES PARA SingleEntry[/bold green]")

    viable = [r for r in results if r["trades"] >= 30]
    if not viable:
        _console.print("[yellow]Nenhuma config com >=30 trades — dados insuficientes[/yellow]")
        return

    metric_col = "outcome_score" if metric == "outcome" else "roi_pct"

    conservative_pool = [r for r in viable if r["win_pct"] >= 85 and r["threshold"] >= 0.60]
    if not conservative_pool:
        conservative_pool = [r for r in viable if r["win_pct"] >= 80]
    conservative = max(conservative_pool, key=lambda r: r[metric_col]) if conservative_pool else None

    balanced_pool = [r for r in viable if r["trades"] >= 50 and abs(r["median_lag_h"]) <= 1.0]
    balanced = max(balanced_pool, key=lambda r: r[metric_col]) if balanced_pool else None

    aggressive = max(viable, key=lambda r: r[metric_col])

    if conservative is None: conservative = aggressive
    if balanced is None: balanced = aggressive

    tbl = Table(box=rich_box.ROUNDED, show_header=True, header_style="bold cyan",
                title="3 perfis de configuração SingleEntry")
    if metric == "outcome":
        cols = ["Perfil", "Thr", "HMin", "Trades/ano", "Win%", "Lag med", "Prem%", "Score"]
    else:
        cols = ["Perfil", "Thr", "HMin", "Trades/ano", "Win%", "Lag med", "ROI%", "Max Draw"]
    for c in cols:
        tbl.add_column(c, justify="right")

    for label, r, emoji, colour in [
        ("CONSERVADOR", conservative, "🛡", "blue"),
        ("BALANCEADO",  balanced,     "⚖", "cyan"),
        ("AGRESSIVO",   aggressive,   "🚀", "magenta"),
    ]:
        tpy = r["trades"] / (r["total_days"] / 365)
        if metric == "outcome":
            tbl.add_row(
                f"[{colour}]{emoji} {label}[/{colour}]",
                f"{r['threshold']:.3f}",
                f"{r['hour_min']}h",
                f"{tpy:.0f}",
                f"{r['win_pct']:.1f}%",
                f"{r['median_lag_h']:+.1f}h",
                f"{r['premature_pct']:.0f}%",
                f"{r['outcome_score']:.1f}",
            )
        else:
            max_single_loss = r["avg_losing_ask"]
            tbl.add_row(
                f"[{colour}]{emoji} {label}[/{colour}]",
                f"{r['threshold']:.3f}",
                f"{r['hour_min']}h",
                f"{tpy:.0f}",
                f"{r['win_pct']:.1f}%",
                f"{r['median_lag_h']:+.1f}h",
                f"{r['roi_pct']:+.1f}%",
                f"${max_single_loss * 5:.2f}/trade",
            )
    _console.print(tbl)

    _console.print("\n[bold]Código para cities/config.py (atualizar threshold e hour_min):[/bold]\n")
    for label, r, emoji in [
        ("CONSERVADOR", conservative, "🛡"),
        ("BALANCEADO",  balanced,     "⚖"),
        ("AGRESSIVO",   aggressive,   "🚀"),
    ]:
        tpy = r["trades"] / (r["total_days"] / 365)
        if metric == "outcome":
            stats_str = (f"{tpy:.0f} trades/ano, win={r['win_pct']:.1f}%, "
                         f"score={r['outcome_score']:.1f}, lag={r['median_lag_h']:+.1f}h, "
                         f"prem%={r['premature_pct']:.0f}")
        else:
            stats_str = (f"{tpy:.0f} trades/ano, win={r['win_pct']:.1f}%, "
                         f"ROI={r['roi_pct']:+.1f}%, lag={r['median_lag_h']:+.1f}h")
        _console.print(
            f"[bold cyan]# {emoji} {label}[/bold cyan] — "
            f"[dim]{stats_str}[/dim]\n"
            f'  threshold={r["threshold"]:.3f},\n'
            f'  hour_min={r["hour_min"]},\n'
        )


def get_grid(mode: str):
    """Retorna (thresholds, hour_mins) para o modo escolhido."""
    if mode == "fast":
        thresholds = [0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90]
        hour_mins = [9, 11, 13]
    elif mode == "standard":
        thresholds = [round(x, 3) for x in np.arange(0.35, 0.91, 0.025)]
        hour_mins = [10, 12, 14]
    elif mode == "detailed":
        thresholds = [round(x, 3) for x in np.arange(0.35, 0.91, 0.025)]
        hour_mins = list(range(9, 16))
    elif mode == "full":
        thresholds = [round(x, 3) for x in np.arange(0.35, 0.91, 0.01)]
        hour_mins = list(range(8, 18))
    else:
        raise ValueError(f"Modo desconhecido: {mode}")
    return thresholds, hour_mins


def parse_windows_arg(value: str) -> list[int]:
    windows = []
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            years = int(part)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(f"Janela inválida: {part}") from exc
        if years < 2:
            raise argparse.ArgumentTypeError("Cada janela precisa de pelo menos 2 anos")
        windows.append(years)
    if not windows:
        raise argparse.ArgumentTypeError("Lista de janelas vazia")
    return sorted(set(windows))


def print_window_comparison(rows: list[dict], metric: str) -> None:
    table = Table(
        box=rich_box.ROUNDED,
        show_header=True,
        header_style="bold cyan",
        title="Comparação de janelas — seleção vs validação",
    )
    for col in [
        "Years", "Thr", "HMin", "Sel Win%", "Sel Trd/y", "Sel Score",
        "Val Years", "Val Win%", "Val Trd/y", "Val Score", "Δ Win",
    ]:
        table.add_column(col, justify="right")

    for row in rows:
        if row is None:
            continue
        sel = row.get("selection") or {}
        val = row.get("validation") or {}
        val_years = ",".join(str(y) for y in row.get("validation_years", [])) or "-"
        sel_win = sel.get("win_pct", row.get("win_pct", 0.0))
        val_win = val.get("win_pct") if val else None
        delta_win = (val_win - sel_win) if val_win is not None else None

        delta_style = "green"
        if delta_win is not None and delta_win < -10:
            delta_style = "red"
        elif delta_win is not None and delta_win < -5:
            delta_style = "yellow"

        table.add_row(
            str(row["years"]),
            f"{row['threshold']:.3f}",
            f"{row['hour_min']}h",
            f"{sel_win:.1f}%",
            f"{sel.get('trades_per_year', row.get('trades_per_year', 0.0)):.0f}",
            f"{sel.get('outcome_score', row.get('outcome_score', 0.0)):.1f}",
            val_years,
            f"{val_win:.1f}%" if val_win is not None else "-",
            f"{val.get('trades_per_year', 0.0):.0f}" if val else "-",
            f"{val.get('outcome_score', 0.0):.1f}" if val else "-",
            f"[{delta_style}]{delta_win:+.1f}pp[/{delta_style}]" if delta_win is not None else "-",
        )

    _console.print(table)
    if metric == "roi":
        _console.print("[dim]Nota: a tabela compara outcome_score/win-rate mesmo em metric=roi; "
                       "ROI continua disponível no JSON retornado por run_calibration().[/dim]")


def run_window_sweep(
    city_name: str,
    windows: list[int],
    mode: str,
    metric: str,
    realistic: bool,
) -> list[dict]:
    rows = []
    for years in windows:
        _console.rule(f"[bold cyan]{city_name} — janela {years} anos[/bold cyan]")
        cal = run_calibration(
            city_name=city_name,
            years=years,
            mode=mode,
            metric=metric,
            realistic=realistic,
            quiet=False,
            validate=True,
            validation_years=1,
        )
        if cal is None:
            _console.print(f"[red]Sem resultado para janela {years} anos[/red]")
            continue
        rows.append(cal)
    print_window_comparison(rows, metric)
    return rows


# ══════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════
def run_calibration(
    city_name: str,
    years: int = 5,
    mode: str = "standard",
    metric: str = "outcome",
    realistic: bool = False,
    quiet: bool = False,
    validate: bool = True,
    validation_years: int = 1,
) -> dict | None:
    """
    Corre calibração para 1 cidade e devolve dict com melhor configuração.

    Função reutilizável para wrappers (ex: calibrate_all.py).
    Não imprime tabelas — só faz o trabalho e devolve resultados.

    Args:
        city_name: nome da cidade (munich, dallas, ankara)
        years: anos de histórico
        mode: fast | standard | detailed | full
        metric: outcome | roi
        realistic: usar SimulatedMarket com ruído
        quiet: se True, silencia prints intermédios
        validate: se True, escolhe params sem o(s) ano(s) mais recente(s)
                  e reporta validação separada
        validation_years: número de anos finais reservados para validação

    Returns:
        dict com:
            threshold, hour_min, outcome_score, win_pct, trades_per_year,
            n_trades, n_days, data_period, metric, mode, ...
        ou None em caso de erro.
    """
    try:
        city = get_city(city_name)
        set_city(city_name)

        if not quiet:
            _console.print(f"  [{city_name}] Loading model and data...")

        models = load_models(city_name)
        df_all = load_data(Path(city.csv_path), city)
        df_all["date"] = pd.to_datetime(df_all["date"]).dt.date
        end_date = date.today() - timedelta(days=1)
        start_date = date(end_date.year - years + 1, 1, 1)
        df = df_all[(df_all["date"] >= start_date) & (df_all["date"] <= end_date)].copy()

        if df.empty:
            return None

        if not quiet:
            _console.print(f"  [{city_name}] {len(df):,} slots, {df['date'].nunique()} days "
                           f"({start_date} → {end_date})")
            _console.print(f"  [{city_name}] Generating signals...")

        signals_df = generate_daily_signals(df, models, city)

        thresholds, hour_mins = get_grid(mode)
        if not quiet:
            _console.print(f"  [{city_name}] Grid: {len(thresholds)}×{len(hour_mins)} = "
                           f"{len(thresholds)*len(hour_mins)} combos")

        val_years = _validation_years(signals_df, validation_years) if validate else []
        if val_years:
            years_series = pd.to_datetime(signals_df["date"]).dt.year
            selection_signals = signals_df[~years_series.isin(val_years)].copy()
            validation_signals = signals_df[years_series.isin(val_years)].copy()
            if not quiet:
                _console.print(f"  [{city_name}] Selection years: "
                               f"{sorted(pd.to_datetime(selection_signals['date']).dt.year.unique())}")
                _console.print(f"  [{city_name}] Validation years: {val_years}")
        else:
            selection_signals = signals_df
            validation_signals = pd.DataFrame()

        results = run_grid_search(
            selection_signals, city, thresholds, hour_mins,
            realistic_market=realistic,
        )

        if not results:
            return None

        best = _select_best_result(results, metric)
        if best is None:
            return None

        n_days = signals_df["date"].nunique() if "date" in signals_df.columns else 1
        selection_days = selection_signals["date"].nunique() if "date" in selection_signals.columns else 1
        selection_summary = _result_summary(best, selection_days)

        validation_result = None
        validation_summary = None
        if not validation_signals.empty:
            market_sim = (
                SimulatedMarket(temp_range=city.temp_range, noise_std=0.05, seed=42)
                if realistic else None
            )
            validation_result = simulate_strategy(
                validation_signals,
                city,
                threshold=best["threshold"],
                hour_min=int(best["hour_min"]),
                realistic_market=realistic,
                market_sim=market_sim,
            )
            validation_days = validation_signals["date"].nunique()
            validation_summary = _result_summary(validation_result, validation_days)

        return {
            "city":             city_name,
            "threshold":        round(best["threshold"], 4),
            "hour_min":         int(best["hour_min"]),
            "outcome_score":    selection_summary["outcome_score"],
            "roi_pct":          selection_summary["roi_pct"],
            "win_pct":          selection_summary["win_pct"],
            "n_trades":         selection_summary["n_trades"],
            "trades_per_year":  selection_summary["trades_per_year"],
            "median_lag_h":     selection_summary["median_lag_h"],
            "data_period":      [str(start_date), str(end_date)],
            "selection_period":  [
                str(selection_signals["date"].min()) if not selection_signals.empty else None,
                str(selection_signals["date"].max()) if not selection_signals.empty else None,
            ],
            "validation_period": [
                str(validation_signals["date"].min()) if not validation_signals.empty else None,
                str(validation_signals["date"].max()) if not validation_signals.empty else None,
            ],
            "validation_years":  val_years,
            "selection":        selection_summary,
            "validation":       validation_summary,
            "n_days":           int(n_days),
            "metric":           metric,
            "mode":             mode,
            "years":            years,
        }

    except Exception as e:
        if not quiet:
            import traceback
            _console.print(f"  [red][{city_name}] Calibration failed: {e}[/red]")
            _console.print(f"  [dim red]{traceback.format_exc()}[/dim red]")
        return None


def main():
    parser = argparse.ArgumentParser(description="Calibração genérica multi-cidade")
    parser.add_argument("--city", type=str, default="munich", choices=list(CITIES.keys()),
                        help="Cidade para calibrar")
    parser.add_argument("--years", type=int, default=5,
                        help="Quantos anos de histórico (default 5)")
    parser.add_argument("--windows", type=parse_windows_arg, default=None,
                        help="Compara várias janelas, ex: --windows 3,5,7,10")
    parser.add_argument("--mode", choices=["fast", "standard", "detailed", "full"],
                        default="standard",
                        help="Densidade: fast=21, standard=69, detailed=161, full=560")
    parser.add_argument("--realistic", action="store_true",
                        help="Usa SimulatedMarket com ruído")
    parser.add_argument("--top", type=int, default=30,
                        help="Top-N resultados a mostrar (default 30)")
    parser.add_argument("--metric", choices=["roi", "outcome"], default="roi",
                        help="roi: optimiza ROI $ via SimulatedMarket (default). "
                             "outcome: optimiza win-rate × log(volume) — métrica honesta.")
    args = parser.parse_args()

    if args.metric == "outcome" and args.realistic:
        _console.print("[yellow]Nota: --realistic é ignorado em modo --metric outcome "
                       "(não precisamos de preços simulados para optimizar win-rate).[/yellow]")
        args.realistic = False

    if args.windows:
        _console.print("\n[bold cyan]" + args.city.title() + " Calibration — comparação de janelas[/bold cyan]\n")
        run_window_sweep(
            city_name=args.city,
            windows=args.windows,
            mode=args.mode,
            metric=args.metric,
            realistic=args.realistic,
        )
        return

    city = get_city(args.city)
    set_city(args.city)

    _console.print("\n[bold cyan]" + city.name.title() + f" Calibration — análise de thresholds[/bold cyan]\n")

    _console.print("[1/5] Carregando modelo...")
    models = load_models(args.city)

    _console.print("\n[2/5] Carregando dados...")
    df_all = load_data(Path(city.csv_path), city)
    df_all["date"] = pd.to_datetime(df_all["date"]).dt.date
    end_date = date.today() - timedelta(days=1)
    start_date = date(end_date.year - args.years + 1, 1, 1)
    df = df_all[(df_all["date"] >= start_date) & (df_all["date"] <= end_date)].copy()
    _console.print(f"  Dataset: {len(df):,} slots, {df['date'].nunique()} dias ({start_date} -> {end_date})")

    _console.print("\n[3/5] Gerando p_ensemble para todos os slots...")
    signals_df = generate_daily_signals(df, models, city)
    _console.print(f"  [green]✓[/green] {len(signals_df):,} sinais gerados")

    print_p_distribution(signals_df, city.day_start)

    thresholds, hour_mins = get_grid(args.mode)
    total_combos = len(thresholds) * len(hour_mins)
    realistic_str = "REALISTA (SimulatedMarket+ruído)" if args.realistic else "proxy (ask≈p_ens)"
    _console.print(
        f"\n[4/5] Grid search — modo '{args.mode}': "
        f"{len(thresholds)} thresholds × {len(hour_mins)} horas = {total_combos} combos "
        f"| Preço: {realistic_str}"
    )

    results = run_grid_search(signals_df, city, thresholds, hour_mins,
                              realistic_market=args.realistic)

    _console.print(f"\n[5/5] Análise de resultados...")

    sort_key = "outcome_score" if args.metric == "outcome" else "roi_pct"
    print_top_results(results, n=args.top, sort_by=sort_key, metric=args.metric)

    if args.mode in ("detailed", "full"):
        print_heatmap(results, metric=args.metric)

    print_stability_analysis(results, metric=args.metric)
    recommend_thresholds(results, metric=args.metric)

    if args.metric == "outcome":
        notes = (
            "\n[dim]Notas finais:\n"
            f"  • Métrica: <b>OUTCOME</b> (win-rate puro, sem inventar preços)\n"
            f"  • outcome_score = win_pct × log10(1 + trades/ano)\n"
            f"  • Recompensa qualidade do sinal SEM enviesar por SimulatedMarket\n"
            f"  • Bracket alvo = round(running_max)\n"
            f"  • Lag positivo = entrou antes do pico; zero = no pico; negativo = depois[/dim]"
        )
    else:
        notes = (
            "\n[dim]Notas finais:\n"
            f"  • Métrica: <b>ROI $</b> (depende de SimulatedMarket — preços inventados)\n"
            f"  • Bracket alvo = round(running_max)\n"
            f"  • Lag positivo = entrou antes do pico; zero = no pico; negativo = depois\n"
            f"  • {'Preços REALISTAS (SimulatedMarket climatológico com ruído 5¢)' if args.realistic else 'Preços por proxy (ask ≈ p_ensemble)'}\n"
            f"  • Para métrica honesta sem ROI inventado, usar: --metric outcome[/dim]"
        )
    _console.print(notes)


if __name__ == "__main__":
    main()
