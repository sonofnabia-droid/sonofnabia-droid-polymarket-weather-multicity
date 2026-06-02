"""
display.py
==========
Dashboard multi-cidade — substitui munich_display.py.
Usa rich (Panel, Table, Columns, Text) para terminal profissional.

Integração com live_bot.py (no fim do loop principal):

    from display import extract_display_data, render_dashboard

    cities_display = []
    for cn in city_names:
        state = states[cn]
        cd = extract_display_data(state, daily_stats.get(cn), city_bankrolls.get(cn, 500.0))
        cd.p_ensemble = last_p_ensemble.get(cn, 0.0)  # guardar após predict_ensemble
        cd.p_lgbm     = last_p_lgbm.get(cn, 0.0)
        cd.target_bracket = last_target_bracket.get(cn)
        cities_display.append(cd)

    render_dashboard(cities_display, trading_mode_str=args.run.upper(), session_stats=session_stats)
"""

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, date
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.columns import Columns
from rich import box as rich_box

from cities.config import CityConfig

try:
    from polymarket_clob import TradingMode, PositionStatus
    _HAS_CLOB = True
except ImportError:
    _HAS_CLOB = False

# Forçar modo terminal/interativo para ambientes onde Rich não deteta TTY corretamente.
_con = Console(force_terminal=True, force_interactive=True)
LOG_DIR = Path("live_bot_logs")
SNAPSHOT_PATH = LOG_DIR / "live_snapshot.json"

# ══════════════════════════════════════════════════════════════════════
#  FLAGS E LABELS
# ══════════════════════════════════════════════════════════════════════

_FLAGS = {
    "munich":       "🇩🇪", "dallas":        "🇺🇸", "ankara":       "🇹🇷",
    "singapore":    "🇸🇬", "jakarta":       "🇮🇩", "kuala_lumpur": "🇲🇾",
    "lagos":        "🇳🇬", "taipei":        "🇹🇼", "miami":        "🇺🇸",
    "karachi":      "🇵🇰", "moscow":        "🇷🇺", "warsaw":       "🇵🇱",
    "beijing":      "🇨🇳", "chicago":       "🇺🇸", "madrid":       "🇪🇸",
    "tel_aviv":     "🇮🇱", "phoenix":       "🇺🇸", "las_vegas":    "🇺🇸",
    "buenos_aires": "🇦🇷", "hong_kong":     "🇭🇰",
}

_PRETTY = {
    "las_vegas":    "Las Vegas",
    "kuala_lumpur": "Kuala Lumpur",
    "buenos_aires": "Buenos Aires",
    "tel_aviv":     "Tel Aviv",
    "hong_kong":    "Hong Kong",
}

def _flag(name: str)  -> str: return _FLAGS.get(name, "🌍")
def _label(name: str) -> str: return _PRETTY.get(name, name.replace("_", " ").title())


def _json_default(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


# ══════════════════════════════════════════════════════════════════════
#  DATACLASS — snapshot de dados por cidade para o dashboard
# ══════════════════════════════════════════════════════════════════════

@dataclass
class CityDisplayData:
    city:            CityConfig
    temp:            Optional[float]  = None   # temperatura actual
    running_max:     Optional[float]  = None   # máximo do dia até agora
    p_ensemble:      float            = 0.0    # probabilidade do ensemble
    p_lgbm:          Optional[float]  = None   # componente LGBM
    slots_so_far:    list             = field(default_factory=list)
    wu_forecast:     Optional[int]    = None   # previsão WU (°C inteiro)
    om_forecast:     Optional[int]    = None   # previsão Open-Meteo
    forecast_agree:  Optional[bool]   = None   # True se WU e OM concordam
    market:          Optional[dict]   = None   # dict do Polymarket
    target_bracket:  Optional[dict]   = None   # bracket alvo (com ask, bid, label)
    bought:          bool             = False
    position:        Optional[dict]   = None   # {ask, bracket, size, strategy}
    daily_pnl:       float            = 0.0
    n_trades:        int              = 0
    stop_loss_hit:   bool             = False
    positions_all:   list             = field(default_factory=list)  # objs CLOB
    daily_loss:      float            = 0.0
    max_daily_loss:  float            = 20.0
    bankroll:        float            = 500.0
    humidity:        Optional[float]  = None
    cloud_cover:     Optional[int]    = None


# ══════════════════════════════════════════════════════════════════════
#  EXTRACTOR — CityState → CityDisplayData
# ══════════════════════════════════════════════════════════════════════

def extract_display_data(state, daily_stats=None, bankroll: float = 500.0) -> "CityDisplayData":
    """
    Converte um CityState (live_bot.py) em CityDisplayData.
    Chama depois de cada tick, antes de render_dashboard().

    Nota: p_ensemble, p_lgbm e target_bracket devem ser definidos
    pelo caller após predict_ensemble(), pois não estão no CityState.
    """
    city = state.city

    temp = hum = cloud = None
    if state.latest_obs:
        temp  = state.latest_obs.get("temp_c")
        hum   = state.latest_obs.get("humidity")
        cloud = state.latest_obs.get("cloud_cover")

    rmax = None
    if state.slots_so_far:
        valid = [s["temp_c"] for s in state.slots_so_far if s.get("temp_c") is not None]
        if valid:
            rmax = max(valid)

    bought = False
    position = None
    if state.entry:
        bought = getattr(state.entry, "bought", False)
        rec    = getattr(state.entry, "record", None)
        if rec and bought:
            position = {
                "ask":      rec.get("ask", 0),
                "bracket":  rec.get("bracket_label") or rec.get("bracket") or str(rec.get("temp_hi", "?")),
                "size":     rec.get("size_usdc", 5.0),
                "strategy": rec.get("strategy", "single"),
            }

    daily_pnl  = 0.0
    n_trades   = 0
    daily_loss = 0.0
    if daily_stats:
        daily_pnl  = getattr(daily_stats, "daily_pnl", 0.0)
        n_trades   = len(getattr(daily_stats, "trades", []))
        trades_list = getattr(daily_stats, "trades", [])
        if trades_list:
            daily_loss = sum(
                float(t.get("realized_pnl", 0.0))
                for t in trades_list
                if float(t.get("realized_pnl", 0.0)) < 0
            )
            daily_loss = abs(daily_loss)
        if daily_loss == 0 and daily_pnl < 0:
            daily_loss = abs(daily_pnl)

    positions_all = []
    if _HAS_CLOB and state.clob and hasattr(state.clob, "positions"):
        try:
            positions_all = state.clob.positions.all_positions()
        except Exception:
            pass

    # Forecast agreement
    wu  = state.last_wu_forecast_max
    om  = state.last_om_forecast_max
    # Fix 13: usar "is not None" para não tratar 0°C como ausente
    agree = (abs(wu - om) <= 1) if (wu is not None and om is not None) else None

    return CityDisplayData(
        city           = city,
        temp           = temp,
        running_max    = rmax,
        slots_so_far   = list(state.slots_so_far),
        wu_forecast    = wu,
        om_forecast    = om,
        forecast_agree = agree,
        market         = state.market,
        bought         = bought,
        position       = position,
        daily_pnl      = daily_pnl,
        n_trades       = n_trades,
        stop_loss_hit  = daily_loss >= city.max_daily_loss,
        positions_all  = positions_all,
        daily_loss     = daily_loss,
        max_daily_loss = city.max_daily_loss,
        bankroll       = bankroll,
        humidity       = hum,
        cloud_cover    = cloud,
    )


# ══════════════════════════════════════════════════════════════════════
#  HELPERS VISUAIS
# ══════════════════════════════════════════════════════════════════════

def _p_bar(p: float, width: int = 18) -> Text:
    """Barra de probabilidade colorida."""
    filled = round(p * width)
    t = Text()
    style = ("bold green"       if p >= 0.75 else
             "bold yellow"      if p >= 0.55 else
             "bold dark_orange" if p >= 0.40 else
             "dim white")
    t.append("█" * filled,          style=style)
    t.append("░" * (width - filled), style="dim")
    return t


def _sparkline(slots: list, width: int = 30) -> Text:
    """Sparkline de temperatura com block characters Unicode."""
    chars = "▁▂▃▄▅▆▇█"
    temps = [s["temp_c"] for s in slots if s.get("temp_c") is not None]
    if not temps:
        return Text("  —", style="dim")

    t_min, t_max = min(temps), max(temps)
    t_rng = max(t_max - t_min, 0.5)

    n = len(temps)
    if n > width:
        sampled = [temps[int(i * n / width)] for i in range(width)]
    else:
        sampled = temps

    peak_idx = sampled.index(max(sampled))
    result = Text()
    for i, t in enumerate(sampled):
        frac = (t - t_min) / t_rng
        idx  = min(int(frac * len(chars)), len(chars) - 1)
        if i == peak_idx:
            result.append(chars[idx], style="bold red")
        elif frac > 0.75:
            result.append(chars[idx], style="bold yellow")
        elif frac > 0.40:
            result.append(chars[idx], style="bold cyan")
        else:
            result.append(chars[idx], style="dim cyan")
    return result


def _risk_bar(used: float, width: int = 14) -> Text:
    """Barra de risco: verde → amarelo → vermelho."""
    filled = round(min(used, 1.0) * width)
    t = Text()
    style = ("bold red" if used > 0.75 else "bold yellow" if used > 0.45 else "green")
    t.append("█" * filled,          style=style)
    t.append("░" * (width - filled), style="dim")
    return t


def _ask_color(ask: float) -> str:
    if ask < 0.25: return "bold green"
    if ask < 0.50: return "bold yellow"
    if ask < 0.70: return "bold dark_orange"
    return "bold red"


def _visible_market_brackets(cd: "CityDisplayData", limit: int = 6) -> list[dict]:
    """Mostra sempre target + vizinhos, em vez dos primeiros brackets baixos."""
    if not cd.market:
        return []

    brackets = list(cd.market.get("brackets", []))
    if not brackets:
        return []
    if len(brackets) <= limit:
        return brackets

    target = cd.target_bracket
    if not target:
        return brackets[:limit]

    target_idx = None
    target_token = target.get("token_id")
    target_label = target.get("label")
    for i, b in enumerate(brackets):
        if target_token and b.get("token_id") == target_token:
            target_idx = i
            break
        if target_label and b.get("label") == target_label:
            target_idx = i
            break

    if target_idx is None:
        return brackets[:limit]

    half = limit // 2
    start = max(0, target_idx - half)
    end = start + limit
    if end > len(brackets):
        end = len(brackets)
        start = max(0, end - limit)
    return brackets[start:end]


def _city_status(cd: "CityDisplayData") -> tuple[str, str]:
    """(label, rich_style) de acordo com o estado da cidade."""
    city    = cd.city
    city_dt = datetime.now(tz=ZoneInfo(city.timezone))
    p       = cd.p_ensemble
    # Fix 10b: usar "is not None" para não tratar 0 ou 0.0 como ausente
    thr     = city.threshold if city.threshold is not None else 0.65
    hmin    = city.hour_min  if city.hour_min  is not None else 14

    if cd.stop_loss_hit:
        return "⛔ STOP-LOSS",      "bold red"
    if cd.bought:
        return "🟢 COMPRADO",       "bold green"
    if city_dt.hour > city.day_end or city_dt.hour < city.day_start:
        return "💤 FORA DE HORA",   "dim"
    if city_dt.hour < hmin:
        return f"⏳ AGUARDA {hmin:02d}h", "yellow"
    if p >= thr:
        return "🎯 SIGNAL!",        "bold yellow"
    return "🔍 A MONITORIZAR",      "cyan"


def _city_group(cd: "CityDisplayData") -> str:
    label, _ = _city_status(cd)
    if cd.stop_loss_hit:
        return "stopped"
    if cd.bought:
        return "bought"
    if "FORA" in label or "AGUARDA" in label or "💤" in label:
        return "idle"
    return "monitoring"


def _border_color(cd: "CityDisplayData") -> str:
    group = _city_group(cd)
    if group == "stopped": return "red"
    if group == "bought": return "green"
    if group == "monitoring": return "gold1"
    return "dim"


# ══════════════════════════════════════════════════════════════════════
#  PAINEL INDIVIDUAL POR CIDADE
# ══════════════════════════════════════════════════════════════════════

def _city_panel(cd: "CityDisplayData") -> Panel:
    city    = cd.city
    city_dt = datetime.now(tz=ZoneInfo(city.timezone))
    tz_off  = city_dt.strftime("%z")
    tz_lbl  = f"UTC{tz_off[:3]}"
    p       = cd.p_ensemble
    # Fix 10b: usar "is not None" para não tratar 0 ou 0.0 como ausente
    thr     = city.threshold if city.threshold is not None else 0.65
    hmin    = city.hour_min  if city.hour_min  is not None else 14

    status_lbl, status_sty = _city_status(cd)
    t = Text()

    # ── Linha 1: hora local + timezone + status
    t.append(f" {city_dt.strftime('%H:%M')} ", style="bold white")
    t.append(f"{tz_lbl}   ",                   style="dim")
    t.append(status_lbl + "\n",                style=status_sty)

    # ── Linha 2: temperatura + humidade
    if cd.temp is not None:
        temp_col = ("bold red"    if cd.temp > 38 else
                    "bold yellow" if cd.temp > 28 else
                    "bold cyan")
        t.append(f" 🌡 {cd.temp:>5.1f}°C", style=temp_col)
        if cd.humidity is not None:
            t.append(f"  💧{cd.humidity:.0f}%", style="dim")
        if cd.cloud_cover is not None:
            t.append(f"  ☁{cd.cloud_cover}%", style="dim")
        t.append("\n")
    else:
        t.append(" 🌡  sem dados\n", style="dim")

    # ── Linha 3: running max + sparkline
    if cd.slots_so_far:
        t.append(" ")
        t.append_text(_sparkline(cd.slots_so_far, width=28))
        if cd.running_max is not None:
            t.append(f"  {cd.running_max:.0f}°↑", style="bold red")
        t.append("\n")
    elif cd.running_max is not None:
        t.append(f"  RMax: {cd.running_max:.1f}°C\n", style="dim")

    # ── P(pico)
    t.append("\n")
    p_col = ("bold green"  if p >= thr else
             "bold yellow" if p >= thr * 0.85 else "dim white")
    t.append(f" P(pico)  ", style="dim")
    t.append(f"{p:.3f}", style=p_col)
    if p >= thr:
        t.append("  ✅ SIGNAL!\n", style="bold green")
    elif p >= thr * 0.85:
        short = (thr - p) * 100
        t.append(f"  ⚠ faltam {short:.1f}%\n", style="yellow")
    else:
        t.append("\n")
    t.append(" ")
    t.append_text(_p_bar(p, width=22))
    t.append(f"  thr={thr:.2f}\n", style="dim")

    # ── Forecasts WU + OM
    wu, om = cd.wu_forecast, cd.om_forecast
    if wu is not None or om is not None:
        t.append("\n FC  ", style="dim")
        if wu is not None:
            t.append(f"WU:{wu}°", style="bold blue")
        if wu is not None and om is not None:
            t.append("   ")
        if om is not None:
            t.append(f"OM:{om}°", style="bold cyan")
        # Fix 13: usar "is not None" para não tratar 0°C como ausente
        if wu is not None and om is not None:
            if cd.forecast_agree:
                t.append("  ✅ concordam", style="dim green")
            else:
                t.append(f"  ⚠ diff={abs(wu - om)}°", style="yellow")
        t.append("\n")

    # ── Mercado Polymarket
    t.append("\n")
    if cd.market:
        vol  = cd.market.get("volume", 0)
        n_br = cd.market.get("n_outcomes", 0)
        t.append(f" 📊 Vol ${vol:>8,.0f}   {n_br} brackets\n", style="dim")

        # Target + vizinhos, para cidades quentes não esconderem o bracket alvo.
        brackets = _visible_market_brackets(cd, limit=6)
        tgt_lbl  = cd.target_bracket.get("label", "") if cd.target_bracket else ""

        for b in brackets:
            is_tgt = (b.get("label") == tgt_lbl) and tgt_lbl
            ask = b.get("ask") or b.get("price") or 0
            bid = b.get("bid") or ask
            lbl = b.get("label", "?")[:14]
            bar_w = 10
            filled = round(ask * bar_w)
            bar_col = _ask_color(ask)

            if is_tgt:
                t.append(" 🎯 ", style="bold green")
                t.append(f"{lbl:<14}", style="bold white")
            else:
                t.append("    ")
                t.append(f"{lbl:<14}", style="dim")

            t.append(f"  {bid*100:>3.0f}¢/", style="dim green")
            t.append(f"{ask*100:>3.0f}¢  ", style=bar_col)
            t.append("█" * filled + "░" * (bar_w - filled), style=bar_col if is_tgt else "dim")
            t.append("\n")
    else:
        t.append(" 📊 Mercado não disponível\n", style="dim red")

    # ── Posição actual
    if cd.bought and cd.position:
        pos = cd.position
        ask = pos.get("ask", 0)
        bkt = str(pos.get("bracket", "?"))[:20]
        sz  = pos.get("size", 5.0)
        stg = pos.get("strategy", "")
        t.append(f"\n 💼 {bkt:<20}", style="bold green")
        t.append(f" @ {ask*100:.0f}¢  ${sz:.0f}", style="green")
        if stg:
            t.append(f"  [{stg}]", style="dim green")
        t.append("\n")

    # ── Resumo diário + risco
    t.append("\n")
    pnl_col = "green" if cd.daily_pnl >= 0 else "red"
    t.append(f" Hoje: {cd.n_trades} trade{'s' if cd.n_trades != 1 else ''}   ", style="dim")
    t.append(f"PnL: ", style="dim")
    t.append(f"{cd.daily_pnl:+.2f}$\n", style=f"bold {pnl_col}")

    if cd.max_daily_loss > 0:
        used = min(1.0, cd.daily_loss / cd.max_daily_loss)
        t.append(f" Risk  ", style="dim")
        t.append_text(_risk_bar(used, width=14))
        t.append(f"  ${cd.daily_loss:.1f}/${cd.max_daily_loss:.0f}", style="dim")
        if used > 0.75:
            t.append("  ⚠", style="bold red")
        t.append("\n")

    # ── Título do painel
    title = Text(f" {_flag(city.name)} {_label(city.name).upper()} ")

    group = _city_group(cd)
    panel_style = (
        "on dark_green" if group == "bought" else
        "on grey11" if group == "monitoring" else
        "on grey7"
    )

    return Panel(
        t,
        title=title,
        border_style=_border_color(cd),
        padding=(0, 1),
        style=panel_style,
    )


def _city_group_columns(city_data: list["CityDisplayData"]) -> Columns:
    groups = {
        "idle": [],
        "monitoring": [],
        "bought": [],
    }
    stopped = []
    for cd in city_data:
        group = _city_group(cd)
        if group == "stopped":
            stopped.append(cd)
        elif group in groups:
            groups[group].append(cd)
        else:
            groups["idle"].append(cd)

    groups["monitoring"].sort(
        key=lambda cd: cd.p_ensemble - (cd.city.threshold if cd.city.threshold is not None else 0.65),
        reverse=True,
    )
    groups["bought"].sort(key=lambda cd: cd.daily_pnl, reverse=True)
    groups["idle"].sort(key=lambda cd: cd.city.name)
    if stopped:
        groups["bought"] = stopped + groups["bought"]

    specs = [
        ("Fora de horas / aguarda", groups["idle"], "dim", "on grey7"),
        ("Monitorização / sinais", groups["monitoring"], "gold1", "on grey11"),
        ("Com posição", groups["bought"], "green", "on dark_green"),
    ]
    panels = []
    for title, rows, border, style in specs:
        body = Columns([_city_panel(cd) for cd in rows], equal=True, expand=True) if rows else Text(" sem cidades", style="dim")
        panels.append(Panel(
            body,
            title=f"[bold {border}] {title} ({len(rows)}) [/bold {border}]",
            border_style=border,
            padding=(0, 1),
            style=style,
        ))
    return Columns(panels, equal=True, expand=True)


# ══════════════════════════════════════════════════════════════════════
#  TABELA RESUMO COLECTIVA (linha por cidade)
# ══════════════════════════════════════════════════════════════════════

def _summary_table(city_data: list["CityDisplayData"]) -> Table:
    tbl = Table(
        box=rich_box.SIMPLE_HEAVY,
        border_style="dim",
        header_style="bold dim cyan",
        show_header=True,
        padding=(0, 1),
        expand=True,
    )
    tbl.add_column("Cidade",      style="bold white",    width=17)
    tbl.add_column("Local",       justify="center",      width=6)
    tbl.add_column("Temp",        justify="right",       width=7)
    tbl.add_column("RMax",        justify="right",       width=7)
    tbl.add_column("P(pico)",     justify="left",        width=24)
    tbl.add_column("FC WU/OM",    justify="center",      width=14)
    tbl.add_column("Target",      justify="left",        width=20)
    tbl.add_column("Status",      justify="center",      width=18)
    tbl.add_column("Tds",         justify="center",      width=4)
    tbl.add_column("PnL hoje",    justify="right",       width=11)

    for cd in city_data:
        city    = cd.city
        city_dt = datetime.now(tz=ZoneInfo(city.timezone))
        p       = cd.p_ensemble
        # Fix 10b: usar "is not None" para não tratar 0 ou 0.0 como ausente
        thr     = city.threshold if city.threshold is not None else 0.65

        # Hora local
        ts = city_dt.strftime("%H:%M")

        # Temp / RMax
        temp_s = (f"{cd.temp:.1f}°"       if cd.temp        is not None else "—")
        rmax_s = (f"{cd.running_max:.1f}°" if cd.running_max is not None else "—")

        # P bar compacto
        p_txt  = Text()
        bar_w  = 10
        filled = round(p * bar_w)
        p_sty  = ("bold green" if p >= thr else
                  "bold yellow" if p >= thr * 0.85 else "dim")
        p_txt.append("█" * filled,          style=p_sty)
        p_txt.append("░" * (bar_w - filled), style="dim")
        p_txt.append(f" {p:.3f}", style=p_sty)
        if p >= thr:
            p_txt.append(" ✅", style="bold green")

        # Forecast
        wu, om = cd.wu_forecast, cd.om_forecast
        fc_t   = Text()
        # Fix 13: usar "is not None" para não tratar 0°C como ausente
        if wu is not None:
            fc_t.append(f"W:{wu}°", style="blue")
        if wu is not None and om is not None:
            fc_t.append(" ")
        if om is not None:
            fc_t.append(f"O:{om}°", style="cyan")
        if wu is not None and om is not None:
            fc_t.append(" ✅" if cd.forecast_agree else " ⚠",
                        style="green" if cd.forecast_agree else "yellow")

        # Target bracket
        tgt_t = Text()
        if cd.target_bracket:
            ask = cd.target_bracket.get("ask") or cd.target_bracket.get("price") or 0
            lbl = cd.target_bracket.get("label", "?")[:13]
            tgt_t.append(lbl, style="white")
            tgt_t.append(f"  {ask*100:.0f}¢", style=_ask_color(ask))

        # Status
        st_lbl, st_sty = _city_status(cd)
        if (not cd.bought) and p >= 0.70 and p < thr:
            st_lbl = "🔥 QUASE SIGNAL"
            st_sty = "bold yellow"
        st_t = Text(st_lbl, style=st_sty, justify="center")

        # PnL
        pnl_t = Text()
        pc = ("bold green" if cd.daily_pnl > 0 else
              "bold red"   if cd.daily_pnl < 0 else "dim")
        pnl_t.append(f"{cd.daily_pnl:+.2f}$", style=pc)

        tbl.add_row(
            f"{_flag(city.name)} {_label(city.name)}",
            ts, temp_s, rmax_s, p_txt, fc_t, tgt_t, st_t,
            str(cd.n_trades), pnl_t,
        )

    return tbl


# ══════════════════════════════════════════════════════════════════════
#  TABELA GLOBAL DE POSIÇÕES (todas as cidades)
# ══════════════════════════════════════════════════════════════════════

def _positions_tables(city_data: list["CityDisplayData"], trading_mode_str: str) -> tuple[Optional[Table], Optional[Table]]:
    """Tabelas colectivas: posições abertas e posições resolvidas."""

    # Recolher linhas: (city_name, pos_obj_or_None)
    rows: list[tuple[str, object]] = []
    for cd in city_data:
        if cd.positions_all:
            for pos in cd.positions_all:
                rows.append((cd.city.name, pos))
        elif cd.bought and cd.position:
            rows.append((cd.city.name, None))  # posição paper sem CLOB

    if not rows:
        return None, None

    def _make_tbl(title: str) -> Table:
        t = Table(
            title=title,
            title_style="bold cyan",
            box=rich_box.SIMPLE_HEAVY,
            border_style="dim cyan",
            header_style="bold dim",
            padding=(0, 1),
            expand=True,
        )
        t.add_column("Cidade",   style="bold", width=16)
        t.add_column("Abertura",               width=19)
        t.add_column("Bracket",                width=20)
        t.add_column("Entrada",  justify="right", width=8)
        t.add_column("Actual",   justify="right", width=8)
        t.add_column("P&L $",    justify="right", width=9)
        t.add_column("P&L %",    justify="right", width=8)
        t.add_column("Shares",   justify="right", width=7)
        t.add_column("Status",   justify="center", width=12)
        return t

    tbl_open = _make_tbl("  Posições Abertas — todas as cidades")
    tbl_resolved = _make_tbl("  Posições Resolvidas — todas as cidades")
    n_open = 0
    n_resolved = 0
    total_pnl_resolved = 0.0

    def _status_for_row(pos_obj, city_name: str) -> tuple[str, str]:
        s_val = getattr(pos_obj, "status", None)
        if _HAS_CLOB:
            _status_map = {
                PositionStatus.OPEN:    ("🔵 ABERTA",   "cyan"),
                PositionStatus.WON:     ("✅ GANHOU",   "bold green"),
                PositionStatus.LOST:    ("❌ PERDEU",   "bold red"),
                PositionStatus.EXPIRED: ("⏱ EXPIROU",  "dim"),
                PositionStatus.UNKNOWN: ("❓",           "dim"),
            }
            s_lbl, s_sty = _status_map.get(s_val, ("❓", "dim"))
            if str(getattr(pos_obj, "mode", "")).lower() == "paper":
                city_obj = next((c for c in city_data if c.city.name == city_name), None)
                resolved_from_price = False
                won_from_price = False
                if city_obj and city_obj.market:
                    token_id = getattr(pos_obj, "token_id", None)
                    for b in (city_obj.market.get("brackets") or []):
                        if token_id and b.get("token_id") == token_id:
                            ask = b.get("ask")
                            if ask is None:
                                ask = b.get("price")
                            try:
                                ask_f = float(ask) if ask is not None else None
                            except Exception:
                                ask_f = None
                            if ask_f is not None:
                                if ask_f >= 0.99:
                                    resolved_from_price = True
                                    won_from_price = True
                                elif ask_f <= 0.01:
                                    resolved_from_price = True
                                    won_from_price = False
                            break
                if resolved_from_price:
                    s_lbl, s_sty = (
                        ("✅ GANHOU", "bold green") if won_from_price else ("❌ PERDEU", "bold red")
                    )
                elif s_val == PositionStatus.OPEN:
                    s_lbl, s_sty = ("🔵 ABERTA", "cyan")
            return s_lbl, s_sty
        return "ABERTA", "cyan"

    def _is_resolved_status(lbl: str) -> bool:
        return ("GANHOU" in lbl) or ("PERDEU" in lbl) or ("EXPIROU" in lbl)

    def _add_row_to(tbl: Table, clbl: str, d_op: str, b_lbl: str, entry: float, mid, pnl_u, pnl_p, shr, s_lbl: str, s_sty: str):
        pnl_col = ("bold green" if (pnl_u or 0) > 0 else
                   "bold red"   if (pnl_u or 0) < 0 else "dim")
        tbl.add_row(
            clbl, str(d_op), b_lbl,
            f"{entry*100:.1f}¢",
            f"{mid*100:.1f}¢" if mid is not None else "—",
            Text(f"{pnl_u:+.2f}$" if pnl_u is not None else "—", style=pnl_col),
            Text(f"{pnl_p:+.1f}%" if pnl_p is not None else "—", style=pnl_col),
            f"{shr:.2f}" if shr else "—",
            Text(s_lbl, style=s_sty),
        )

    for city_name, pos in rows:
        flag = _flag(city_name)
        clbl = f"{flag} {_label(city_name)}"

        if pos is None:
            cd = next((c for c in city_data if c.city.name == city_name), None)
            if not cd or not cd.position:
                continue
            ask = cd.position.get("ask", 0)
            bkt = str(cd.position.get("bracket", "?"))[:18]
            tbl_open.add_row(
                clbl, date.today().isoformat(), bkt,
                f"{ask*100:.1f}¢", "—", "—", "—", "—",
                Text("📄 PAPER", style="yellow"),
            )
            n_open += 1
            continue

        mid   = getattr(pos, "current_mid",   None)
        pnl_u = getattr(pos, "pnl_usd",       None)
        pnl_p = getattr(pos, "pnl_pct",       None)
        entry = getattr(pos, "entry_ask",      0)
        shr   = getattr(pos, "shares",         0)
        d_op  = getattr(pos, "opened_at", None) or getattr(pos, "date_opened", "?")
        b_lbl = str(getattr(pos, "bracket_label", "?"))[:18]

        s_lbl, s_sty = _status_for_row(pos, city_name)
        resolved = _is_resolved_status(s_lbl)
        if resolved:
            _add_row_to(tbl_resolved, clbl, str(d_op), b_lbl, entry, mid, pnl_u, pnl_p, shr, s_lbl, s_sty)
            n_resolved += 1
            if pnl_u is not None:
                total_pnl_resolved += float(pnl_u)
        else:
            _add_row_to(tbl_open, clbl, str(d_op), b_lbl, entry, mid, pnl_u, pnl_p, shr, s_lbl, s_sty)
            n_open += 1

    if n_resolved > 0 and total_pnl_resolved != 0.0:
        pc = "bold green" if total_pnl_resolved >= 0 else "bold red"
        tbl_resolved.add_section()
        tbl_resolved.add_row("", "", "", "", "TOTAL P&L", "",
                             Text(f"{total_pnl_resolved:+.2f}$", style=pc), "", "")

    return (tbl_open if n_open else None), (tbl_resolved if n_resolved else None)


def _position_to_snapshot(pos) -> dict:
    if pos is None:
        return {}
    if isinstance(pos, dict):
        return dict(pos)
    data = {}
    for key in (
        "date_opened", "bracket_label", "token_id", "entry_ask", "shares",
        "size_usdc", "mode", "order_id", "market_slug", "temp_lo", "temp_hi",
        "current_mid", "pnl_usd", "pnl_pct", "last_updated",
    ):
        data[key] = getattr(pos, key, None)
    status = getattr(pos, "status", None)
    data["status"] = getattr(status, "value", status)
    return data


def _city_to_snapshot(cd: "CityDisplayData") -> dict:
    city_dt = datetime.now(tz=ZoneInfo(cd.city.timezone))
    threshold = cd.city.threshold if cd.city.threshold is not None else 0.65
    hour_min = cd.city.hour_min if cd.city.hour_min is not None else 14
    status_label, _ = _city_status(cd)
    brackets = []
    if cd.market:
        visible = _visible_market_brackets(cd, limit=12)
        for b in visible:
            brackets.append({
                "label": b.get("label"),
                "ask": b.get("ask") or b.get("price"),
                "bid": b.get("bid"),
                "volume": b.get("volume"),
                "temp_lo": b.get("temp_lo"),
                "temp_hi": b.get("temp_hi"),
                "token_id": b.get("token_id"),
            })

    return {
        "name": cd.city.name,
        "label": _label(cd.city.name),
        "flag": _flag(cd.city.name),
        "timezone": cd.city.timezone,
        "local_time": city_dt.isoformat(),
        "local_hm": city_dt.strftime("%H:%M"),
        "day_start": cd.city.day_start,
        "day_end": cd.city.day_end,
        "has_wu": bool(cd.city.wu_history_path),
        "threshold": threshold,
        "hour_min": hour_min,
        "status": status_label,
        "temp": cd.temp,
        "running_max": cd.running_max,
        "p_ensemble": cd.p_ensemble,
        "p_lgbm": cd.p_lgbm,
        "slots": cd.slots_so_far[-96:],
        "wu_forecast": cd.wu_forecast,
        "om_forecast": cd.om_forecast,
        "forecast_agree": cd.forecast_agree,
        "market": {
            "title": cd.market.get("title") if cd.market else None,
            "volume": cd.market.get("volume") if cd.market else None,
            "n_outcomes": cd.market.get("n_outcomes") if cd.market else None,
            "brackets": brackets,
        },
        "target_bracket": cd.target_bracket,
        "bought": cd.bought,
        "position": cd.position,
        "positions_all": [_position_to_snapshot(p) for p in cd.positions_all],
        "daily_pnl": cd.daily_pnl,
        "n_trades": cd.n_trades,
        "daily_loss": cd.daily_loss,
        "max_daily_loss": cd.max_daily_loss,
        "bankroll": cd.bankroll,
        "humidity": cd.humidity,
        "cloud_cover": cd.cloud_cover,
        "stop_loss_hit": cd.stop_loss_hit,
    }


def write_live_snapshot(
    city_data: list["CityDisplayData"],
    trading_mode_str: str = "PAPER",
    session_stats: dict | None = None,
) -> None:
    """Grava snapshot read-only para dashboard web, sem depender do Flask."""
    session_stats = session_stats or {}
    LOG_DIR.mkdir(exist_ok=True)
    now = datetime.now(tz=ZoneInfo("Europe/Lisbon"))
    cities = [_city_to_snapshot(cd) for cd in city_data]
    bankroll = sum(c.get("bankroll") or 0 for c in cities)
    daily_pnl = sum(c.get("daily_pnl") or 0 for c in cities)
    initial_capital = (
        1000.0
        if str(trading_mode_str).upper() == "PAPER"
        else bankroll
    )
    payload = {
        "generated_at": now.isoformat(),
        "trading_mode": trading_mode_str,
        "session": {
            "total_trades": session_stats.get("total_trades", 0),
            "total_pnl": session_stats.get("total_pnl", 0.0),
            "start_time": session_stats.get("start_time"),
        },
        "summary": {
            "n_cities": len(cities),
            "n_bought": sum(1 for c in cities if c.get("bought")),
            "n_signal": sum(
                1 for c in cities
                if not c.get("bought")
                and (c.get("p_ensemble") or 0) >= (c.get("threshold") or 0.65)
            ),
            "n_stop": sum(1 for c in cities if c.get("stop_loss_hit")),
            "daily_pnl": daily_pnl,
            "daily_trades": sum(c.get("n_trades") or 0 for c in cities),
            "bankroll": bankroll,
            "initial_capital": initial_capital,
            "current_capital": initial_capital + daily_pnl,
        },
        "cities": cities,
    }
    tmp_path = SNAPSHOT_PATH.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, default=_json_default))
    tmp_path.replace(SNAPSHOT_PATH)


# ══════════════════════════════════════════════════════════════════════
#  RENDER PRINCIPAL
# ══════════════════════════════════════════════════════════════════════

def render_dashboard(
    city_data:        list["CityDisplayData"],
    trading_mode_str: str  = "PAPER",
    session_stats:    dict | None = None,
) -> None:
    """
    Renderiza o dashboard multi-cidade completo no terminal.
    Limpa o ecrã e redraw a cada chamada (ciclo do bot).

    Args:
        city_data:        lista de CityDisplayData (uma por cidade activa)
        trading_mode_str: "PAPER" ou "REAL"
        session_stats:    {"total_trades": int, "total_pnl": float, "start_time": datetime}
    """
    if session_stats is None:
        session_stats = {}

    write_live_snapshot(city_data, trading_mode_str, session_stats)

    _con.clear()

    lisbon_now  = datetime.now(tz=ZoneInfo("Europe/Lisbon"))
    lisbon_str  = lisbon_now.strftime("%H:%M:%S")
    n_cities    = len(city_data)
    n_bought    = sum(1 for cd in city_data if cd.bought)
    n_signal    = sum(1 for cd in city_data
                      if not cd.bought and cd.p_ensemble >= (cd.city.threshold if cd.city.threshold is not None else 0.65))
    n_stop      = sum(1 for cd in city_data if cd.stop_loss_hit)
    total_pnl   = session_stats.get("total_pnl",    0.0)
    total_trades= session_stats.get("total_trades",  0)
    total_bkr   = sum(cd.bankroll for cd in city_data)
    open_out_of_day = 0
    for cd in city_data:
        city_today = datetime.now(tz=ZoneInfo(cd.city.timezone)).date().isoformat()
        for pos in cd.positions_all or []:
            status = getattr(getattr(pos, "status", None), "value", getattr(pos, "status", None))
            if str(status).lower() != "open":
                continue
            d_open = str(getattr(pos, "date_opened", "") or "")
            if d_open and d_open != city_today:
                open_out_of_day += 1

    # ── HEADER ─────────────────────────────────────────────────────
    is_paper = trading_mode_str == "PAPER"
    mode_icon = "📄" if is_paper else "💰"
    mode_col  = "yellow" if is_paper else "bold red"

    hdr = Text(justify="center")
    hdr.append("  ⚡ POLYMARKET TEMP BOT  ", style="bold white")
    hdr.append("│ ", style="dim")
    hdr.append(f"{mode_icon} {trading_mode_str}  ", style=mode_col)
    hdr.append("│ ", style="dim")
    hdr.append(f"🕐 Lisboa {lisbon_str}  ", style="bold cyan")
    hdr.append("│ ", style="dim")
    hdr.append(f"{n_cities} cidades  ", style="white")

    if n_stop:
        hdr.append("│ ", style="dim")
        hdr.append(f"⛔ {n_stop} stop-loss  ", style="bold red")
    if n_bought:
        hdr.append("│ ", style="dim")
        hdr.append(f"🟢 {n_bought} posição{'ões' if n_bought > 1 else ''} aberta{'s' if n_bought > 1 else ''}  ", style="bold green")
    if n_signal:
        hdr.append("│ ", style="dim")
        hdr.append(f"🎯 {n_signal} signal{'s' if n_signal > 1 else ''}  ", style="bold yellow")
    if total_trades > 0:
        hdr.append("│ ", style="dim")
        pnl_c = "green" if total_pnl >= 0 else "red"
        hdr.append(f"Sessão: {total_trades} trades  ", style="dim")
        hdr.append(f"PnL {total_pnl:+.2f}$  ", style=f"bold {pnl_c}")
    hdr.append("│ ", style="dim")
    sanity_style = "bold green" if open_out_of_day == 0 else "bold red"
    hdr.append(f"Sanity abertas fora do dia: {open_out_of_day}  ", style=sanity_style)

    hdr.append("│ ", style="dim")
    hdr.append(f"Bankroll ${total_bkr:,.0f}  ", style="dim")

    _con.print(Panel(hdr, border_style="cyan", padding=(0, 1)))

    # ── ESTADOS POR COLUNA ─────────────────────────────────────────
    _con.print(_city_group_columns(city_data))

    # ── TABELA RESUMO COLECTIVA ────────────────────────────────────
    _con.print()
    _con.print(Panel(
        _summary_table(city_data),
        title="[bold cyan] Resumo — todas as cidades [/bold cyan]",
        border_style="cyan",
        padding=(0, 1),
    ))

    # ── POSIÇÕES GLOBAIS ───────────────────────────────────────────
    pos_open_tbl, pos_resolved_tbl = _positions_tables(city_data, trading_mode_str)
    if pos_open_tbl:
        _con.print()
        _con.print(Panel(pos_open_tbl, border_style="dim cyan", padding=(0, 1)))
    if pos_resolved_tbl:
        _con.print()
        _con.print(Panel(pos_resolved_tbl, border_style="dim cyan", padding=(0, 1)))

    # ── FOOTER ─────────────────────────────────────────────────────
    pnl_dia   = sum(cd.daily_pnl  for cd in city_data)
    trd_dia   = sum(cd.n_trades   for cd in city_data)
    wins_dia  = sum(1 for cd in city_data if cd.daily_pnl > 0 and cd.n_trades > 0)
    pnl_c     = "bold green" if pnl_dia >= 0 else "bold red"

    footer = Text()
    footer.append(f"  DIA: {trd_dia} trades  ", style="dim")
    footer.append(f"cidades em profit: {wins_dia}/{n_cities}  ", style="dim")
    footer.append("PnL dia: ", style="dim")
    footer.append(f"{pnl_dia:+.2f}$   ", style=pnl_c)
    if session_stats.get("start_time"):
        elapsed = lisbon_now - session_stats["start_time"]
        h, rem  = divmod(int(elapsed.total_seconds()), 3600)
        m, _    = divmod(rem, 60)
        footer.append(f"uptime {h}h{m:02d}m   ", style="dim")
    footer.append(f"actualizado {lisbon_str}   Ctrl+C para parar", style="dim")

    _con.print()
    _con.print(footer)
    _con.print()
