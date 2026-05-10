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

import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime, date
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

_con = Console()

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
        daily_loss = getattr(daily_stats, "total_invested", 0.0)

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


def _border_color(cd: "CityDisplayData") -> str:
    label, _ = _city_status(cd)
    if "STOP"   in label: return "red"
    if "COMPRA" in label: return "green"
    if "SIGNAL" in label: return "yellow"
    if "FORA"   in label or "AGUARDA" in label or "💤" in label: return "dim"
    return "blue"


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

        # Top 3 brackets + highlight do target
        brackets = cd.market.get("brackets", [])[:6]
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

    return Panel(t, title=title, border_style=_border_color(cd), padding=(0, 1))


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
    tbl.add_column("Status",      justify="center",      width=14)
    tbl.add_column("Tds",         justify="center",      width=4)
    tbl.add_column("PnL hoje",    justify="right",       width=9)

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

def _positions_table(city_data: list["CityDisplayData"], trading_mode_str: str) -> Optional[Table]:
    """Tabela colectiva de posições abertas e fechadas de todas as cidades."""

    # Recolher linhas: (city_name, pos_obj_or_None)
    rows: list[tuple[str, object]] = []
    for cd in city_data:
        if cd.positions_all:
            for pos in cd.positions_all:
                rows.append((cd.city.name, pos))
        elif cd.bought and cd.position:
            rows.append((cd.city.name, None))  # posição paper sem CLOB

    if not rows:
        return None

    tbl = Table(
        title="  Posições — todas as cidades",
        title_style="bold cyan",
        box=rich_box.SIMPLE_HEAVY,
        border_style="dim cyan",
        header_style="bold dim",
        padding=(0, 1),
        expand=True,
    )
    tbl.add_column("Cidade",   style="bold", width=16)
    tbl.add_column("Data",                   width=11)
    tbl.add_column("Bracket",                width=20)
    tbl.add_column("Entrada",  justify="right", width=8)
    tbl.add_column("Actual",   justify="right", width=8)
    tbl.add_column("P&L $",    justify="right", width=9)
    tbl.add_column("P&L %",    justify="right", width=8)
    tbl.add_column("Shares",   justify="right", width=7)
    tbl.add_column("Status",   justify="center", width=12)

    total_pnl = 0.0

    for city_name, pos in rows:
        flag = _flag(city_name)
        clbl = f"{flag} {_label(city_name)}"

        if pos is None:
            # Posição paper sem CLOB — dados básicos
            cd = next((c for c in city_data if c.city.name == city_name), None)
            if not cd or not cd.position:
                continue
            ask = cd.position.get("ask", 0)
            bkt = str(cd.position.get("bracket", "?"))[:18]
            mode_lbl = Text("📄 PAPER", style="yellow")
            tbl.add_row(clbl, date.today().isoformat(), bkt,
                        f"{ask*100:.1f}¢", "—", "—", "—", "—", mode_lbl)
            continue

        # Posição CLOB
        mid   = getattr(pos, "current_mid",   None)
        pnl_u = getattr(pos, "pnl_usd",       None)
        pnl_p = getattr(pos, "pnl_pct",       None)
        entry = getattr(pos, "entry_ask",      0)
        shr   = getattr(pos, "shares",         0)
        s_val = getattr(pos, "status",         None)
        d_op  = getattr(pos, "date_opened",    "?")
        b_lbl = str(getattr(pos, "bracket_label", "?"))[:18]

        if pnl_u is not None:
            total_pnl += pnl_u

        pnl_col = ("bold green" if (pnl_u or 0) > 0 else
                   "bold red"   if (pnl_u or 0) < 0 else "dim")

        if _HAS_CLOB:
            _status_map = {
                PositionStatus.OPEN:    ("🔵 ABERTA",   "cyan"),
                PositionStatus.WON:     ("✅ GANHOU",   "bold green"),
                PositionStatus.LOST:    ("❌ PERDEU",   "bold red"),
                PositionStatus.EXPIRED: ("⏱ EXPIROU",  "dim"),
                PositionStatus.UNKNOWN: ("❓",           "dim"),
            }
            s_lbl, s_sty = _status_map.get(s_val, ("❓", "dim"))
        else:
            s_lbl, s_sty = ("ABERTA", "cyan")

        tbl.add_row(
            clbl, str(d_op), b_lbl,
            f"{entry*100:.1f}¢",
            f"{mid*100:.1f}¢" if mid is not None else "—",
            Text(f"{pnl_u:+.2f}$" if pnl_u is not None else "—", style=pnl_col),
            Text(f"{pnl_p:+.1f}%" if pnl_p is not None else "—", style=pnl_col),
            f"{shr:.2f}" if shr else "—",
            Text(s_lbl, style=s_sty),
        )

    if total_pnl != 0.0:
        pc = "bold green" if total_pnl >= 0 else "bold red"
        tbl.add_section()
        tbl.add_row("", "", "", "", "TOTAL P&L", "",
                    Text(f"{total_pnl:+.2f}$", style=pc), "", "")

    return tbl


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

    os.system("clear" if os.name != "nt" else "cls")

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
    hdr.append(f"Bankroll ${total_bkr:,.0f}  ", style="dim")

    _con.print(Panel(hdr, border_style="cyan", padding=(0, 1)))

    # ── GRID DE PAINÉIS ────────────────────────────────────────────
    try:
        term_w = shutil.get_terminal_size().columns
    except Exception:
        term_w = 160

    n_cols = (3 if term_w >= 200 else
              2 if term_w >= 120 else 1)

    panels = [_city_panel(cd) for cd in city_data]

    for i in range(0, len(panels), n_cols):
        _con.print(Columns(panels[i:i + n_cols], equal=True, expand=True))

    # ── TABELA RESUMO COLECTIVA ────────────────────────────────────
    _con.print()
    _con.print(Panel(
        _summary_table(city_data),
        title="[bold cyan] Resumo — todas as cidades [/bold cyan]",
        border_style="cyan",
        padding=(0, 1),
    ))

    # ── POSIÇÕES GLOBAIS ───────────────────────────────────────────
    pos_tbl = _positions_table(city_data, trading_mode_str)
    if pos_tbl:
        _con.print()
        _con.print(Panel(pos_tbl, border_style="dim cyan", padding=(0, 1)))

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