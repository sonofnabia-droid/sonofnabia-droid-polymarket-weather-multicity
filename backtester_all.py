"""
backtester_all.py
=================
Backtest agregado em TODAS as cidades Celsius.
Apresenta resultados por cidade + resumo global com bets/dia, sazonalidade,
diagnose económica e veredicto.

Uso:
    python backtester_all.py --start 2021-01-01
    python backtester_all.py --start 2022-06-01 --end 2024-12-31
    python backtester_all.py --start 2023-01-01 --noise 0.0
    python backtester_all.py --start 2023-01-01 --ordertype percent --bet 2
    python backtester_all.py --start 2023-01-01 --cities munich,dallas
"""

import argparse
import json
import math
import warnings
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", category=UserWarning,
                        message=".*X does not have valid feature names.*")

from rich.console import Console
from rich.progress import Progress, BarColumn, TextColumn, TimeElapsedColumn, TimeRemainingColumn
from rich.table import Table
from rich import box as rich_box

from cities.config import get_city, CITIES
from predictor import set_city, load_models
from backtester import (
    SimulatedMarket, load_data, _compute_prev7_map, run_backtest,
    _compute_sharpe_sortino_from_day_records, SEASONS,
)

_console = Console(force_terminal=True)
OUTPUT_DIR = Path("backtest_results")
OUTPUT_DIR.mkdir(exist_ok=True)


# ══════════════════════════════════════════════════════
#  DATA STRUCTURES
# ══════════════════════════════════════════════════════
@dataclass
class CityResult:
    city_name: str
    total_days: int = 0
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    missed: int = 0
    win_pct: float = 0.0
    total_pnl: float = 0.0
    total_invested: float = 0.0
    pnl_pct: float = 0.0
    bets_per_day: float = 0.0
    avg_ask: float = 0.0
    sharpe: float = 0.0
    sortino: float = 0.0
    seasonal: dict = field(default_factory=dict)
    day_records: list = field(default_factory=list)
    error: Optional[str] = None


# ══════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════
def get_celsius_cities() -> list[str]:
    """Lista de cidades com market_unit == 'celsius'."""
    return [cfg.name for cfg in CITIES.values() if cfg.market_unit == "celsius"]


def _safe_ceil_slot(h: int, m: int) -> tuple[int, int]:
    """Delega para weather.ceil_slot sem import circular extra."""
    from weather import ceil_slot
    return ceil_slot(h, m)


# ══════════════════════════════════════════════════════
#  SINGLE CITY RUNNER
# ══════════════════════════════════════════════════════
def run_single_city(
    city_name: str,
    start_date: date,
    end_date: date,
    ordertype: str = "fixed",
    bet_value: float = 5.0,
    noise_std: float = 0.08,
) -> CityResult:
    """Executa backtest para uma cidade, devolve CityResult."""
    result = CityResult(city_name=city_name)

    try:
        city = get_city(city_name)
        set_city(city_name)

        models = load_models(city_name)

        df_all = load_data(Path(city.csv_path), city)
        df_all["date"] = pd.to_datetime(df_all["date"]).dt.date

        df = df_all[
            (df_all["date"] >= start_date) & (df_all["date"] <= end_date)
        ].copy()

        if df.empty:
            result.error = "sem dados no período"
            return result

        yearly, capital_history, day_records, _ = run_backtest(
            df, models, city,
            ordertype=ordertype,
            bet_value=bet_value,
            noise_std=noise_std,
            mode="single",
        )

        result.day_records = day_records
        if not day_records:
            result.error = "sem day_records"
            return result

        df_d = pd.DataFrame(day_records)

        result.total_days = len(df_d)
        result.total_trades = int((~df_d["single_missed"]).sum())
        result.wins = int(df_d["single_correct"].sum())
        result.losses = result.total_trades - result.wins
        result.missed = int(df_d["single_missed"].sum())
        result.win_pct = (
            (result.wins / result.total_trades * 100)
            if result.total_trades > 0 else 0.0
        )
        result.total_pnl = round(float(df_d["single_pnl"].sum()), 2)
        result.total_invested = round(float(df_d["single_invested"].sum()), 2)
        result.pnl_pct = (
            (result.total_pnl / result.total_invested * 100)
            if result.total_invested > 0 else 0.0
        )
        result.bets_per_day = (
            round(result.total_trades / result.total_days, 2)
            if result.total_days > 0 else 0.0
        )

        # Ask médio dos trades reais
        trades_df = df_d[df_d["single_ask"].notna()]
        result.avg_ask = (
            round(float(trades_df["single_ask"].mean()), 3)
            if len(trades_df) > 0 else 0.0
        )

        # Sharpe / Sortino
        sh, so = _compute_sharpe_sortino_from_day_records(day_records, "single")
        result.sharpe = sh
        result.sortino = so

        # Sazonalidade
        for season in ["winter", "spring", "summer", "autumn"]:
            sub = df_d[df_d["season"] == season]
            if sub.empty:
                continue
            trades_s = sub[~sub["single_missed"]]
            n_trades = len(trades_s)
            result.seasonal[season] = {
                "days": len(sub),
                "trades": n_trades,
                "win_pct": round(
                    int(trades_s["single_correct"].sum()) / n_trades * 100, 1
                ) if n_trades > 0 else 0.0,
                "pnl": round(float(sub["single_pnl"].sum()), 2),
            }

    except FileNotFoundError as e:
        result.error = f"ficheiro em falta: {e}"
    except Exception as e:
        result.error = str(e)[:120]

    return result


# ══════════════════════════════════════════════════════
#  AGGREGATE DASHBOARD
# ══════════════════════════════════════════════════════
def _color_win(pct: float) -> str:
    if pct > 80: return "green"
    if pct > 60: return "yellow"
    return "red"


def _color_pnl(val: float) -> str:
    return "green" if val > 0 else "red"


def print_aggregate_dashboard(
    results: list[CityResult],
    start_date: date,
    end_date: date,
    ordertype: str,
    bet_value: float,
    noise_std: float,
):
    """Dashboard agregado — todas as cidades Celsius."""

    ok = [r for r in results if r.error is None]
    bad = [r for r in results if r.error is not None]

    if not ok:
        _console.print("[red]Nenhuma cidade com resultados válidos.[/red]")
        for r in bad:
            _console.print(f"  [dim]{r.city_name}: {r.error}[/dim]")
        return

    # ─── Header ───
    _console.rule("[bold cyan]BACKTEST AGREGADO — TODAS AS CIDADES CELSIUS[/bold cyan]")
    noise_str = f"{noise_std*100:.1f}¢" if noise_std > 0 else "determinístico"
    order_str = f"${bet_value}" if ordertype == "fixed" else f"{bet_value}% do capital"
    _console.print(
        f"[dim]Período: {start_date} → {end_date}  |  "
        f"OrderType: {order_str}  |  Ruído: {noise_str}[/dim]\n"
    )

    # ─── Tabela por cidade (ordenada por PnL desc) ───
    tbl = Table(
        box=rich_box.ROUNDED, show_header=True,
        header_style="bold cyan", title="Resultados por Cidade",
    )
    cols = [
        ("Cidade",   14, "left"),
        ("Dias",      7, "right"),
        ("Trades",    7, "right"),
        ("Bets/dia",  9, "right"),
        ("Win%",      7, "right"),
        ("Invested", 10, "right"),
        ("PnL $",    11, "right"),
        ("PnL%",      8, "right"),
        ("Ask méd",   8, "right"),
        ("Sharpe",    7, "right"),
    ]
    for c, w, j in cols:
        tbl.add_column(c, justify=j, width=w)

    # Acumuladores globais
    G = dict(days=0, trades=0, wins=0, losses=0, missed=0,
             pnl=0.0, invested=0.0, sharpe_vals=[])

    for r in sorted(ok, key=lambda x: x.total_pnl, reverse=True):
        G["days"]    += r.total_days
        G["trades"]  += r.total_trades
        G["wins"]    += r.wins
        G["losses"]  += r.losses
        G["missed"]  += r.missed
        G["pnl"]     += r.total_pnl
        G["invested"]+= r.total_invested
        if r.sharpe != 0:
            G["sharpe_vals"].append(r.sharpe)

        cw = _color_win(r.win_pct)
        cp = _color_pnl(r.pnl_pct)
        tbl.add_row(
            r.city_name.title(),
            f"{r.total_days:,}",
            f"{r.total_trades:,}",
            f"{r.bets_per_day:.2f}",
            f"[{cw}]{r.win_pct:.1f}%[/{cw}]",
            f"${r.total_invested:,.0f}",
            f"[{cp}]${r.total_pnl:+,.0f}[/{cp}]",
            f"[{cp}]{r.pnl_pct:+.1f}%[/{cp}]",
            f"{r.avg_ask:.3f}",
            f"{r.sharpe:.2f}" if r.sharpe != 0 else "—",
        )

    # Linha separadora + total
    sep = "─"
    tbl.add_row(
        sep*14, sep*7, sep*7, sep*9, sep*7,
        sep*10, sep*11, sep*8, sep*8, sep*7,
    )
    g_win_pct = (G["wins"] / G["trades"] * 100) if G["trades"] > 0 else 0.0
    g_pnl_pct = (G["pnl"] / G["invested"] * 100) if G["invested"] > 0 else 0.0
    g_bpd = G["trades"] / G["days"] if G["days"] > 0 else 0.0
    g_sharpe = float(np.mean(G["sharpe_vals"])) if G["sharpe_vals"] else 0.0

    cw = _color_win(g_win_pct)
    cp = _color_pnl(g_pnl_pct)
    tbl.add_row(
        "[bold]TOTAL[/bold]",
        f"[bold]{G['days']:,}[/bold]",
        f"[bold]{G['trades']:,}[/bold]",
        f"[bold]{g_bpd:.2f}[/bold]",
        f"[bold][{cw}]{g_win_pct:.1f}%[/{cw}][/bold]",
        f"[bold]${G['invested']:,.0f}[/bold]",
        f"[bold][{cp}]${G['pnl']:+,.0f}[/{cp}][/bold]",
        f"[bold][{cp}]{g_pnl_pct:+.1f}%[/{cp}][/bold]",
        "—",
        f"[bold]{g_sharpe:.2f}[/bold]" if g_sharpe else "—",
    )
    _console.print(tbl)

    # ─── Resumo global detalhado ───
    _console.rule("[bold]RESUMO GLOBAL[/bold]")

    # Bets/dia mais granular
    unique_cal_dates = len({
        rec["date"] for r in ok for rec in r.day_records
    })
    unique_city_days = len({
        (r.city_name, rec["date"]) for r in ok for rec in r.day_records
    })
    bets_per_cal_day = G["trades"] / unique_cal_dates if unique_cal_dates else 0.0
    bets_per_city_day = G["trades"] / unique_city_days if unique_city_days else 0.0

    st = Table(box=rich_box.ROUNDED)
    st.add_column("Métrica", style="dim", min_width=40)
    st.add_column("Valor", justify="right", min_width=20)

    st.add_row("Cidades processadas (Celsius)", f"{len(ok)}")
    if bad:
        st.add_row("Cidades com erro", f"[red]{len(bad)}[/red]")
    st.add_row("", "")
    st.add_row("Dias totais (soma cidade-dia)", f"{G['days']:,}")
    st.add_row("Dias únicos no calendário", f"{unique_cal_dates:,}")
    st.add_row("Cidade-dias únicos", f"{unique_city_days:,}")
    st.add_row("", "")
    st.add_row("Total de Trades", f"{G['trades']:,}")
    st.add_row("Bets / dia calendário", f"{bets_per_cal_day:.2f}")
    st.add_row("Bets / cidade-dia", f"{bets_per_city_day:.2f}")
    st.add_row("", "")
    cw2 = _color_win(g_win_pct)
    st.add_row("Wins", f"[green]{G['wins']:,}[/green]")
    st.add_row("Losses", f"[red]{G['losses']:,}[/red]")
    st.add_row("Missed (sem entrada)", f"[yellow]{G['missed']:,}[/yellow]")
    st.add_row("Win%  (wins / trades)", f"[{cw2}]{g_win_pct:.1f}%[/{cw2}]")
    st.add_row("", "")
    st.add_row("Total Invested", f"${G['invested']:,.0f}")
    cp2 = _color_pnl(G["pnl"])
    st.add_row("PnL Total", f"[{cp2}]${G['pnl']:+,.0f}[/{cp2}]")
    cp3 = _color_pnl(g_pnl_pct)
    st.add_row("PnL% (sobre invested)", f"[{cp3}]{g_pnl_pct:+.1f}%[/{cp3}]")
    st.add_row(
        "PnL médio / trade",
        f"${G['pnl']/G['trades']:+.2f}" if G["trades"] else "—",
    )
    st.add_row("", "")

    # Break-even analysis agregado
    all_asks = [
        rec["single_ask"]
        for r in ok for rec in r.day_records
        if rec.get("single_ask") and not rec["single_missed"]
    ]
    if all_asks:
        avg_ask = float(np.mean(all_asks))
        # Proteger contra ask muito baixo (ruído pode ir < 0.01)
        avg_payoff = (1.0 / max(avg_ask, 0.001) - 1.0) if avg_ask > 0 else 0.0
        be_wr = (1.0 / (1.0 + avg_payoff) * 100) if avg_payoff > 0 else 100.0
        margin = g_win_pct - be_wr
        ev = (g_win_pct / 100 * avg_payoff) - ((1 - g_win_pct / 100) * 1.0)

        st.add_row("Ask médio (todos os trades)", f"{avg_ask:.3f}  ({avg_ask*100:.1f}¢)")
        st.add_row("Payoff por $ (quando ganha)", f"+${avg_payoff:.3f}")
        st.add_row("Win-rate break-even", f"{be_wr:.1f}%")
        mc = "green" if margin > 5 else "yellow" if margin > 0 else "red"
        st.add_row("Margem sobre break-even", f"[{mc}]{margin:+.1f}pp[/{mc}]")
        ec = "green" if ev > 0.05 else "yellow" if ev > 0 else "red"
        st.add_row("EV por $ apostado", f"[{ec}]${ev:+.4f}[/{ec}]")
        st.add_row("", "")

    st.add_row("Sharpe médio (por cidade)", f"{g_sharpe:.2f}" if g_sharpe else "—")
    _console.print(st)

    # ─── Ranking de cidades ───
    _console.rule("[bold]RANKING POR PnL[/bold]")
    rank = Table(box=rich_box.SIMPLE, show_header=True)
    for c, w, j in [("#", 4, "right"), ("Cidade", 14, "left"),
                     ("PnL $", 11, "right"), ("PnL%", 8, "right"),
                     ("Win%", 7, "right"), ("Bets/dia", 9, "right")]:
        rank.add_column(c, justify=j, width=w)
    for i, r in enumerate(sorted(ok, key=lambda x: x.total_pnl, reverse=True), 1):
        cp4 = _color_pnl(r.total_pnl)
        cw3 = _color_win(r.win_pct)
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
        rank.add_row(
            medal,
            r.city_name.title(),
            f"[{cp4}]${r.total_pnl:+,.0f}[/{cp4}]",
            f"[{cp4}]{r.pnl_pct:+.1f}%[/{cp4}]",
            f"[{cw3}]{r.win_pct:.1f}%[/{cw3}]",
            f"{r.bets_per_day:.2f}",
        )
    _console.print(rank)

    # ─── Sazonalidade agregada ───
    _console.rule("[bold]SAZONALIDADE AGREGADA[/bold]")
    icons = {"winter": "❄", "spring": "🌱", "summer": "☀", "autumn": "🍂"}
    season_agg = {}
    for season in ["winter", "spring", "summer", "autumn"]:
        sd, st2, sw, sp = 0, 0, 0, 0.0
        for r in ok:
            ss = r.seasonal.get(season)
            if ss:
                sd += ss["days"]
                st2 += ss["trades"]
                sp += ss["pnl"]
                sw += int(ss["win_pct"] / 100 * ss["trades"]) if ss["trades"] else 0
        if st2 > 0:
            season_agg[season] = {
                "days": sd, "trades": st2,
                "win_pct": round(sw / st2 * 100, 1),
                "pnl": round(sp, 2),
            }
    if season_agg:
        stbl = Table(box=rich_box.SIMPLE, show_header=True)
        for c in ["Estação", "Dias", "Trades", "Win%", "PnL", "Bets/dia"]:
            stbl.add_column(c, justify="right")
        for season in ["winter", "spring", "summer", "autumn"]:
            ss = season_agg.get(season)
            if not ss:
                continue
            cc = _color_win(ss["win_pct"])
            cp5 = _color_pnl(ss["pnl"])
            bpd = ss["trades"] / ss["days"] if ss["days"] else 0
            stbl.add_row(
                f"{icons.get(season,'')} {season}",
                f"{ss['days']:,}",
                f"{ss['trades']:,}",
                f"[{cc}]{ss['win_pct']}%[/{cc}]",
                f"[{cp5}]${ss['pnl']:+,.0f}[/{cp5}]",
                f"{bpd:.2f}",
            )
        _console.print(stbl)

    # ─── Veredicto ───
    _console.rule("[bold]VEREDICTO[/bold]")
    # Garantir que be_wr existe mesmo sem trades (evita NameError edge case)
    be_wr = be_wr if all_asks else 100.0  # 100% = nunca ganha = break-even trivial
    margin_val = g_win_pct - be_wr if all_asks else 0
    if g_pnl_pct > 5 and margin_val > 5:
        _console.print(
            f"[green bold]✓ EDGE POSITIVA ROBUSTA[/green bold] — "
            f"Margem +{margin_val:.1f}pp, PnL ${G['pnl']:+,.0f} "
            f"em {G['trades']:,} trades."
        )
    elif g_pnl_pct > 0 and margin_val > 0:
        _console.print(
            f"[yellow bold]⚠ EDGE MARGINAL[/yellow bold] — "
            f"Margem +{margin_val:.1f}pp. Slippage em produção pode eliminá-la."
        )
    else:
        _console.print(
            "[red bold]✗ EDGE NEGATIVA[/red bold] — "
            "O bot não tem vantagem sobre o mercado simulado."
        )

    if noise_std == 0:
        _console.print(
            "\n[dim red]Aviso: --noise 0.0 → backtest determinístico. "
            "Win-rate pode estar inflada por circularidade.[/dim red]"
        )

    # Erros
    if bad:
        _console.print(f"\n[dim]Cidades com erro ({len(bad)}):[/dim]")
        for r in bad:
            _console.print(f"  [dim red]{r.city_name}: {r.error}[/dim red]")

    # ─── Save JSON ───
    json_out = {
        "start_date": str(start_date),
        "end_date": str(end_date),
        "ordertype": ordertype,
        "bet_value": bet_value,
        "noise_std": noise_std,
        "global": {
            "n_cities_ok": len(ok),
            "n_cities_err": len(bad),
            "total_days": G["days"],
            "total_trades": G["trades"],
            "wins": G["wins"],
            "losses": G["losses"],
            "missed": G["missed"],
            "win_pct": round(g_win_pct, 1),
            "total_pnl": G["pnl"],
            "total_invested": G["invested"],
            "pnl_pct": round(g_pnl_pct, 1),
            "bets_per_cal_day": round(bets_per_cal_day, 2),
            "bets_per_city_day": round(bets_per_city_day, 2),
            "unique_cal_days": unique_cal_dates,
            "avg_sharpe": round(g_sharpe, 2) if g_sharpe else None,
            "avg_ask": round(avg_ask, 4) if all_asks else None,
            "be_win_rate": round(be_wr, 1) if all_asks else None,
            "margin_pp": round(margin_val, 1) if all_asks else None,
            "ev_per_dollar": round(ev, 4) if all_asks else None,
        },
        "seasonal": season_agg,
        "cities": {
            r.city_name: {
                "total_days": r.total_days,
                "total_trades": r.total_trades,
                "wins": r.wins,
                "losses": r.losses,
                "missed": r.missed,
                "win_pct": r.win_pct,
                "total_pnl": r.total_pnl,
                "total_invested": r.total_invested,
                "pnl_pct": r.pnl_pct,
                "bets_per_day": r.bets_per_day,
                "avg_ask": r.avg_ask,
                "sharpe": r.sharpe,
                "sortino": r.sortino,
                "seasonal": r.seasonal,
                "error": r.error,
            }
            for r in results
        },
    }
    json_path = OUTPUT_DIR / f"backtest_all_{start_date}_{end_date}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(json_out, f, indent=2, default=str, ensure_ascii=False)
    _console.print(f"\n[green]JSON guardado:[/green] {json_path}")


# ══════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════
def main():
    parser = argparse.ArgumentParser(
        description="Backtest agregado — todas as cidades Celsius",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Exemplos:
  python backtester_all.py --start 2021-01-01
  python backtester_all.py --start 2022-06-01 --end 2024-12-31
  python backtester_all.py --start 2023-01-01 --noise 0.0
  python backtester_all.py --start 2023-01-01 --ordertype percent --bet 2
  python backtester_all.py --start 2023-01-01 --cities munich,dallas
""",
    )
    parser.add_argument("--start", required=True, help="Data início (YYYY-MM-DD)")
    parser.add_argument("--end", default=None, help="Data fim (YYYY-MM-DD, default: ontem)")
    parser.add_argument("--ordertype", default="fixed", choices=["fixed", "percent"],
                        help="Tipo de ordem (default: fixed)")
    parser.add_argument("--bet", type=float, default=5.0,
                        help="Valor fixo $ ou %% do capital (default: 5.0)")
    parser.add_argument("--noise", type=float, default=0.08,
                        help="Ruído do mercado em ¢ (default: 0.08, use 0.0 para determinístico)")
    parser.add_argument("--cities", default=None,
                        help="Cidades específicas separadas por vírgula (default: todas Celsius)")

    args = parser.parse_args()

    start_date = date.fromisoformat(args.start)
    end_date = (
        date.fromisoformat(args.end)
        if args.end else date.today() - timedelta(days=1)
    )

    if args.cities:
        city_names = [c.strip().lower() for c in args.cities.split(",") if c.strip()]
        # Validar
        unknown = [c for c in city_names if c not in CITIES]
        if unknown:
            _console.print(f"[red]Cidades desconhecidas: {unknown}[/red]")
            _console.print(f"[dim]Disponíveis: {', '.join(CITIES.keys())}[/dim]")
            return
    else:
        city_names = get_celsius_cities()

    if not city_names:
        _console.print("[red]Nenhuma cidade Celsius encontrada em cities/config.py[/red]")
        return

    _console.print(
        f"[bold cyan]Backtest All — {len(city_names)} cidades Celsius[/bold cyan]\n"
        f"  Período : {start_date} → {end_date}\n"
        f"  Ordertype: {args.ordertype}  |  Bet: {args.bet}  |  Noise: {args.noise}\n"
    )

    results: list[CityResult] = []

    with Progress(
        TextColumn("[cyan]{task.description}"),
        BarColumn(),
        TextColumn("{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
        console=_console,
    ) as progress:
        task = progress.add_task("Cidades", total=len(city_names))

        for city_name in city_names:
            progress.update(task, description=f"[cyan]{city_name}[/cyan]")

            result = run_single_city(
                city_name, start_date, end_date,
                ordertype=args.ordertype,
                bet_value=args.bet,
                noise_std=args.noise,
            )
            results.append(result)

            if result.error is None:
                status = (
                    f"[green]✓ {result.total_trades} trades, "
                    f"${result.total_pnl:+,.0f} "
                    f"({result.win_pct:.0f}% win)[/green]"
                )
            else:
                status = f"[red]✗ {result.error}[/red]"

            progress.update(task, advance=1)
            _console.print(f"  {city_name:<14} {status}")

    _console.print("")
    print_aggregate_dashboard(
        results, start_date, end_date,
        args.ordertype, args.bet, args.noise,
    )


if __name__ == "__main__":
    main()
