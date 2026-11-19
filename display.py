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
import math
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
# FIX SNAPSHOT-1: respeitar CASS_LOG_DIR (igual ao live_bot) — sem isto, bots B/D
# escreviam o snapshot no diretório do A e o dashboard lia o estado errado/trocado.
import os as _os
LOG_DIR = Path(_os.environ.get("CASS_LOG_DIR", "live_bot_logs"))
SNAPSHOT_PATH = LOG_DIR / "live_snapshot.json"

# FIX P2-4: cache global para leituras de bets JSON (TTL 1 hora)
_bets_cache: dict[str, tuple[datetime, list]] = {}


def _load_bets_cached(city_name: str, d: date) -> list:
    """Carrega bets do disco com cache de 1 hora."""
    key = f"{city_name}_{d}"
    now = datetime.now()
    if key in _bets_cache:
        cached_at, data = _bets_cache[key]
        if (now - cached_at).total_seconds() < 3600:
            return data
    bets_path = LOG_DIR / f"bets_{city_name}_{d}.json"
    if not bets_path.exists():
        _bets_cache[key] = (now, [])
        return []
    try:
        data = json.loads(bets_path.read_text())
    except Exception:
        data = []
    _bets_cache[key] = (now, data)
    return data

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
    # om_forecast removido — Open-Meteo descontinuado
    forecast_agree:  Optional[bool]   = None   # N/A — Open-Meteo removido
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
    # D5: dados da estrategia activa (cassiopeia mostra o motor certo)
    strategy_name:   str              = "single"
    signal_threshold: Optional[float] = None
    p_rebound:       Optional[float]  = None
    signal_window:   Optional[tuple]  = None


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
    # Fallback: usar último slot se latest_obs falhar
    if temp is None and state.slots_so_far:
        last_slot = state.slots_so_far[-1]
        temp = last_slot.get("temp_c")
        hum = last_slot.get("humidity")
        cloud = last_slot.get("cloud_cover")

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
                # entry_ask é a chave dos registos restaurados de
                # paper_positions.json; ask é a dos registos em memória
                "ask":      rec.get("ask") or rec.get("entry_ask") or 0,
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
            raw_positions = state.clob.positions.all_positions()
            c_name = city.name.lower()
            c_slug_pfx = getattr(city, "polymarket_slug_pfx", "").lower()
            for p in raw_positions:
                slug = getattr(p, "market_slug", "") or ""
                prefix = slug.split("-on-")[0] if slug else ""
                p_city = prefix.split("-in-")[1] if "-in-" in prefix else prefix
                p_city = p_city.lower()

                match = False
                if slug and c_slug_pfx and slug.startswith(c_slug_pfx):
                    match = True
                elif p_city and (p_city == c_name or p_city in c_name or c_name in p_city):
                    match = True
                elif state.market and "brackets" in state.market:
                    tok_id = getattr(p, "token_id", None)
                    if tok_id and any(b.get("token_id") == tok_id for b in state.market.get("brackets", [])):
                        match = True
                if match:
                    positions_all.append(p)
        except Exception:
            pass

    # ── LER posições resolvidas do bets_*.json (últimos 3 dias) ──
    try:
        from datetime import timedelta
        for days_ago in range(3):
            d = date.today() - timedelta(days=days_ago)
            # FIX P2-4: usar cache em vez de ler do disco diretamente
            bets_data = _load_bets_cached(city.name, d)
            if not bets_data:
                continue
            for b in bets_data:
                if not (b.get("resolved") or b.get("sold_by_stop") or b.get("status") in ("won", "lost")):
                    continue
                # Converter para formato compatível com _position_to_snapshot
                resolved_pos = dict(b)
                resolved_pos["entry_ask"] = b.get("ask", 0)
                resolved_pos["pnl_usd"] = b.get("realized_pnl", 0)
                resolved_pos["pnl_pct"] = (
                    (b.get("realized_pnl", 0) / b.get("size_usdc", 1) * 100)
                    if b.get("size_usdc") else 0
                )
                resolved_pos["opened_at"] = b.get("time") or b.get("timestamp")
                resolved_pos["date_opened"] = b.get("date_opened") or str(d)
                resolved_pos["current_mid"] = b.get("exit_ask", b.get("ask", 0))
                resolved_pos["shares"] = b.get("shares", 0)
                resolved_pos["size_usdc"] = b.get("size_usdc", 0)
                # Evitar duplicados (se já está no CLOB)
                tok = b.get("token_id")
                lbl = b.get("bracket_label") or b.get("bracket")
                dup = False
                for existing in positions_all:
                    if (tok and getattr(existing, "token_id", None) == tok) or \
                       (lbl and getattr(existing, "bracket_label", None) == lbl):
                        dup = True
                        break
                if not dup:
                    positions_all.append(resolved_pos)
    except Exception:
        pass

    # FIX S1-14: p_ensemble default seguro
    p_ens = float(getattr(state, 'last_p_ensemble', 0.0) or 0.0)

    # Forecast — apenas WU (Open-Meteo removido)
    wu  = getattr(state, 'last_wu_forecast_max', None)
    agree = None  # Open-Meteo removido — agreement não aplicável

    # D5: dados da estratégia activa (cassiopeia)
    strategy_name = getattr(state, "strategy_mode", "single")
    signal_threshold = None
    p_rebound = None
    signal_window = None
    entry_obj = getattr(state, "entry", None)
    if strategy_name == "cassiopeia" and entry_obj is not None:
        le = getattr(entry_obj, "last_eval", None)
        if le:
            signal_threshold = le.get("threshold")
            p_rebound = le.get("p_rebound")
            signal_window = (le.get("start_hour"), le.get("end_hour"))

    # FIX S1-14: p_ensemble NUNCA None (o render compara >= e rebenta)
    if p_ens is None:
        p_ens = 0.0
    return CityDisplayData(
        city           = city,
        temp           = temp,
        running_max    = rmax,
        slots_so_far   = list(state.slots_so_far),
        wu_forecast    = wu,
        # om_forecast removido — Open-Meteo descontinuado
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
        strategy_name  = strategy_name,
        signal_threshold = signal_threshold,
        p_rebound      = p_rebound,
        signal_window  = signal_window,
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


def _is_market_resolved(cd: "CityDisplayData") -> tuple[bool, Optional[dict]]:
    """Verifica se o mercado já está resolvido (algum bracket a >=99% ou <=1%).

    Returns:
        (is_resolved, winning_bracket) — winning_bracket é o bracket a >=99%
    """
    if not cd.market or not cd.market.get("brackets"):
        return False, None

    for b in cd.market["brackets"]:
        ask = b.get("ask") or b.get("price") or 0
        try:
            ask_f = float(ask)
        except Exception:
            continue
        if ask_f >= 0.99:
            return True, b
        if ask_f <= 0.01:
            # Verificar se é o único bracket a 0.01 (outros também podem estar)
            pass
    return False, None


def _signals_low(cd: "CityDisplayData") -> bool:
    """Direção do sinal por estratégia: Cassiopeia COMPRA quando
    p_rebound < threshold (rebound improvável = bracket atual segura);
    o mundo peak/single sinaliza quando p >= threshold.
    Antes deste fix o display mostrava "SIGNAL!" exatamente quando a
    Cassiopeia NÃO comprava (inversão cosmética que confundia o dono)."""
    return (getattr(cd, "strategy_name", None) == "cassiopeia"
            and getattr(cd, "p_rebound", None) is not None)


def _active_params(cd: "CityDisplayData") -> tuple[float, int]:
    """(threshold, hour_min) da estratégia ATIVA. Cassiopeia: last_eval do
    entry → resolve_params (config calibrada METAR) → fallback legacy.
    O strategy_config do mundo SingleEntry (0.35/0.50/0.65, hour_min trocado)
    NÃO reflete a config ativa (bug §92 — o relatório TG já lia do entry,
    o snapshot não; corrigido aqui de vez, §106)."""
    thr = None
    hmin = None
    if getattr(cd, "strategy_name", None) == "cassiopeia":
        if getattr(cd, "signal_threshold", None) is not None:
            thr = cd.signal_threshold
        sw = getattr(cd, "signal_window", None)
        if sw and sw[0] is not None:
            try:
                hmin = int(sw[0])
            except Exception:
                pass
        if thr is None or hmin is None:
            try:
                from cassiopeia_params import resolve_params
                p = resolve_params(cd.city.name)
                if thr is None:
                    thr = float(p["threshold"])
                if hmin is None:
                    hmin = int(p["start_hour"])
            except Exception:
                pass
    if thr is None:
        thr = cd.city.threshold if cd.city.threshold is not None else 0.65
    if hmin is None:
        hmin = cd.city.hour_min if cd.city.hour_min is not None else 14
    return thr, hmin


def _city_status(cd: "CityDisplayData") -> tuple[str, str]:
    """(label, rich_style) de acordo com o estado da cidade."""
    city    = cd.city
    city_dt = datetime.now(tz=ZoneInfo(city.timezone))
    p       = (cd.p_rebound if getattr(cd, "strategy_name", None) == "cassiopeia"
               and getattr(cd, "p_rebound", None) is not None else cd.p_ensemble)
    # Fix 10b: usar "is not None" para não tratar 0 ou 0.0 como ausente
    thr, hmin = _active_params(cd)

    if cd.stop_loss_hit:
        return "⛔ STOP-LOSS",      "bold red"
    if cd.bought:
        return "🟢 COMPRADO",       "bold green"
    if city_dt.hour > city.day_end or city_dt.hour < city.day_start:
        return "💤 FORA DE HORA",   "dim"
    if city_dt.hour < hmin:
        return f"⏳ AGUARDA {hmin:02d}h", "yellow"

    # FIX: verificar se mercado já está resolvido (algum bracket a >=99%)
    resolved, winner = _is_market_resolved(cd)
    if resolved and winner and not cd.bought:
        lbl = winner.get("label", "?")
        return f"🏁 RESOLVIDO: {lbl}", "dim"

    # ── Mercado caro: bloqueia signal mesmo que P >= threshold ──
    target = cd.target_bracket
    if target and not cd.bought:
        ask = target.get("ask") or target.get("price")
        try:
            ask_f = float(ask) if ask is not None else 0.0
        except Exception:
            ask_f = 0.0
        if ask_f >= 0.90:
            return "🏁 MERCADO > 0.9¢", "dim"

    if (_signals_low(cd) and p < thr) or (not _signals_low(cd) and p >= thr):
        return "🎯 SIGNAL!",        "bold yellow"
    return "🔍 A MONITORIZAR",      "cyan"


def _city_group(cd: "CityDisplayData") -> str:
    """Determina o grupo da cidade para organização do dashboard.

    FIX BAIXO-16: usa a mesma lógica de estado que _city_status em vez de
    fazer parsing frágil de strings do label.
    """
    city    = cd.city
    city_dt = datetime.now(tz=ZoneInfo(city.timezone))
    p       = (cd.p_rebound if getattr(cd, "strategy_name", None) == "cassiopeia"
               and getattr(cd, "p_rebound", None) is not None else cd.p_ensemble)
    thr, hmin = _active_params(cd)

    if cd.stop_loss_hit:
        return "stopped"
    if cd.bought:
        return "bought"
    # FIX: verificar se mercado já está resolvido
    resolved, _ = _is_market_resolved(cd)
    if resolved and not cd.bought:
        return "resolved"

    # Mesma lógica de "mercado caro" de _city_status
    if cd.target_bracket and not cd.bought:
        ask = cd.target_bracket.get("ask") or cd.target_bracket.get("price")
        try:
            ask_f = float(ask) if ask is not None else 0.0
        except Exception:
            ask_f = 0.0
        if ask_f >= 0.90:
            return "resolved"
    # Fora de horas / aguarda
    if city_dt.hour > city.day_end or city_dt.hour < city.day_start or city_dt.hour < hmin:
        return "idle"
    return "monitoring"


def _border_color(cd: "CityDisplayData") -> str:
    group = _city_group(cd)
    if group == "stopped": return "red"
    if group == "bought": return "green"
    if group == "monitoring": return "gold1"
    if group == "resolved": return "#808080"
    return "dim"


# ══════════════════════════════════════════════════════════════════════
#  PAINEL INDIVIDUAL POR CIDADE
# ══════════════════════════════════════════════════════════════════════

def _city_panel(cd: "CityDisplayData") -> Panel:
    city    = cd.city
    city_dt = datetime.now(tz=ZoneInfo(city.timezone))
    tz_off  = city_dt.strftime("%z")
    tz_lbl  = f"UTC{tz_off[:3]}"
    p       = (cd.p_rebound if getattr(cd, "strategy_name", None) == "cassiopeia"
               and getattr(cd, "p_rebound", None) is not None else cd.p_ensemble)
    # Fix 10b: usar "is not None" para não tratar 0 ou 0.0 como ausente
    thr     = (getattr(cd, "signal_threshold", None)
               if getattr(cd, "strategy_name", None) == "cassiopeia"
               and getattr(cd, "signal_threshold", None) is not None
               else (city.threshold if city.threshold is not None else 0.65))
    hmin    = city.hour_min  if city.hour_min  is not None else 14
    if getattr(cd, "strategy_name", None) == "cassiopeia" and getattr(cd, "signal_window", None):
        try: hmin = int(cd.signal_window[0])
        except Exception: pass

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
    _low = _signals_low(cd)
    if _low:
        p_col = ("bold green"  if p < thr else
                 "bold yellow" if p < thr * 1.15 else "dim white")
    else:
        p_col = ("bold green"  if p >= thr else
                 "bold yellow" if p >= thr * 0.85 else "dim white")
    t.append(f" {'P(reb)' if getattr(cd, 'strategy_name', None) == 'cassiopeia' else 'P(pico)'}  ", style="dim")
    t.append(f"{p:.3f}", style=p_col)
    _sig = (p < thr) if _low else (p >= thr)
    if _sig:
        t.append("  ✅ SIGNAL!\n", style="bold green")
    elif _low and p < thr * 1.15:
        over = (p - thr) * 100
        t.append(f"  ⚠ acima {over:.1f}%\n", style="yellow")
    elif not _low and p >= thr * 0.85:
        short = (thr - p) * 100
        t.append(f"  ⚠ faltam {short:.1f}%\n", style="yellow")
    else:
        t.append("\n")
    t.append(" ")
    t.append_text(_p_bar(p, width=22))
    t.append(f"  thr={thr:.2f}\n", style="dim")

    # ── Forecast WU (Open-Meteo removido) ──
    wu = cd.wu_forecast
    if wu is not None:
        t.append("\n FC  ", style="dim")
        if wu is not None:
            t.append(f"WU:{wu}°", style="bold blue")
            t.append("   ")

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
        ask = pos.get("ask") or 0
        bkt = str(pos.get("bracket", "?"))[:20]
        sz  = pos.get("size") or 5.0
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
        "on dark_green"      if group == "bought" else
        "on #3d3d1f"        if group == "monitoring" else   # amarelo-dourado escuro
        "on #2a2a2a"        if group == "resolved" else    # cinzento escuro
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
        "resolved": [],
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
    groups["resolved"].sort(key=lambda cd: cd.city.name)
    groups["idle"].sort(key=lambda cd: cd.city.name)
    if stopped:
        groups["bought"] = stopped + groups["bought"]

    specs = [
        ("Fora de horas / aguarda", groups["idle"], "dim", "on grey7"),
        ("Monitorização / sinais", groups["monitoring"], "gold1", "on #3d3d1f"),
        ("Mercado > 0.9¢", groups["resolved"], "#808080", "on #2a2a2a"),
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
    tbl.add_column("FC WU",       justify="center",      width=10)
    tbl.add_column("Target",      justify="left",        width=20)
    tbl.add_column("Status",      justify="center",      width=18)
    tbl.add_column("Tds",         justify="center",      width=4)
    tbl.add_column("PnL hoje",    justify="right",       width=11)

    for cd in city_data:
        city    = cd.city
        city_dt = datetime.now(tz=ZoneInfo(city.timezone))
        p       = (cd.p_rebound if getattr(cd, "strategy_name", None) == "cassiopeia"
               and getattr(cd, "p_rebound", None) is not None else cd.p_ensemble)
        # Fix 10b: usar "is not None" para não tratar 0 ou 0.0 como ausente
        thr     = (getattr(cd, "signal_threshold", None)
               if getattr(cd, "strategy_name", None) == "cassiopeia"
               and getattr(cd, "signal_threshold", None) is not None
               else (city.threshold if city.threshold is not None else 0.65))

        # Hora local
        ts = city_dt.strftime("%H:%M")

        # Temp / RMax
        temp_s = (f"{cd.temp:.1f}°"       if cd.temp        is not None else "—")
        rmax_s = (f"{cd.running_max:.1f}°" if cd.running_max is not None else "—")

        # P bar compacto
        p_txt  = Text()
        bar_w  = 10
        filled = round(p * bar_w)
        _low   = _signals_low(cd)
        _sig_on = (p < thr) if _low else (p >= thr)
        _near  = (p < thr * 1.15) if _low else (p >= thr * 0.85)
        p_sty  = ("bold green" if _sig_on else
                  "bold yellow" if _near else "dim")
        p_txt.append("█" * filled,          style=p_sty)
        p_txt.append("░" * (bar_w - filled), style="dim")
        p_txt.append(f" {p:.3f}", style=p_sty)
        if _sig_on:
            p_txt.append(" ✅", style="bold green")

        # Forecast
        wu = cd.wu_forecast
        fc_t   = Text()
        if wu is not None:
            fc_t.append(f"W:{wu}°", style="blue")
            fc_t.append(" ")
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
        if not cd.bought:
            if _low and (thr <= p < thr * 1.15):
                st_lbl = "🔥 QUASE SIGNAL"
                st_sty = "bold yellow"
            elif not _low and p >= 0.70 and p < thr:
                st_lbl = "🔥 QUASE SIGNAL"
                st_sty = "bold yellow"
        st_t = Text(st_lbl, style=st_sty, justify="center")

        # PnL
        pnl_t = Text()
        pc = ("bold green" if cd.daily_pnl > 0 else
              "bold red"   if cd.daily_pnl < 0 else "dim")
        pnl_t.append(f"{cd.daily_pnl:+.2f}$", style=pc)

        # Background da linha baseado no status
        row_style = ""
        st_lbl_clean = st_lbl.replace("🏁 ", "").replace("🔍 ", "").replace("🎯 ", "").replace("💤 ", "").replace("⏳ ", "").replace("🟢 ", "").replace("⛔ ", "")
        if "MERCADO > 0.9¢" in st_lbl_clean:
            row_style = "on #2a2a2a"
        elif st_lbl_clean == "A MONITORIZAR":
            row_style = "on #3d3d1f"
        elif st_lbl_clean == "SIGNAL!":
            row_style = "on #3d3d00"
        elif st_lbl_clean == "COMPRADO":
            row_style = "on #1a331a"
        elif "FORA DE HORA" in st_lbl_clean or "AGUARDA" in st_lbl_clean:
            row_style = "on #1a1a1a"
        elif "STOP-LOSS" in st_lbl_clean:
            row_style = "on #331a1a"

        tbl.add_row(
            f"{_flag(city.name)} {_label(city.name)}",
            ts, temp_s, rmax_s, p_txt, fc_t, tgt_t, st_t,
            str(cd.n_trades), pnl_t,
            style=row_style,
        )

    return tbl


# ══════════════════════════════════════════════════════════════════════
#  TABELA GLOBAL DE POSIÇÕES (todas as cidades)
# ══════════════════════════════════════════════════════════════════════

def _parse_to_date(val) -> Optional[date]:
    if not val:
        return None
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    if isinstance(val, str):
        try:
            clean_str = val.split('T')[0].strip()
            return date.fromisoformat(clean_str)
        except Exception:
            return None
    return None


def _positions_tables(city_data: list["CityDisplayData"], trading_mode_str: str) -> tuple[Table, Table]:
    """Tabelas colectivas: posições abertas e posições resolvidas.

    SEMPRE retorna as duas tabelas, mesmo que vazias.
    """

    from datetime import timedelta
    rows: list[tuple[str, object]] = []
    cutoff_date = date.today() - timedelta(days=3)

    for cd in city_data:
        c_name = cd.city.name
        c_slug_pfx = getattr(cd.city, "polymarket_slug_pfx", "").lower()

        if cd.positions_all:
            for pos in cd.positions_all:
                slug = getattr(pos, "market_slug", "") or ""
                prefix = slug.split("-on-")[0] if slug else ""
                p_city = prefix.split("-in-")[1] if "-in-" in prefix else prefix
                p_city = p_city.lower()

                match = False
                if slug and c_slug_pfx and slug.startswith(c_slug_pfx):
                    match = True
                elif p_city and (p_city == c_name.lower() or p_city in c_name.lower() or c_name.lower() in p_city):
                    match = True
                elif cd.market and "brackets" in cd.market:
                    tok_id = getattr(pos, "token_id", None)
                    if tok_id and any(b.get("token_id") == tok_id for b in cd.market.get("brackets", [])):
                        match = True

                if not match:
                    continue

                d_open_raw = getattr(pos, "opened_at", None) or getattr(pos, "date_opened", None)
                pos_date = _parse_to_date(d_open_raw)
                if pos_date is None or pos_date >= cutoff_date:
                    rows.append((c_name, pos))

        elif cd.bought and cd.position:
            entry_time = cd.position.get("timestamp") or cd.position.get("time") or cd.position.get("date_opened")
            pos_date = _parse_to_date(entry_time)
            if pos_date is None or pos_date >= cutoff_date:
                rows.append((c_name, None))

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
        t.add_column("Abertura",               width=24)
        t.add_column("Bracket",                width=20)
        t.add_column("Entrada",  justify="right", width=8)
        t.add_column("Actual",   justify="right", width=8)
        t.add_column("P&L $",    justify="right", width=9)
        t.add_column("P&L %",    justify="right", width=8)
        t.add_column("Shares",   justify="right", width=7)
        t.add_column("Status",   justify="center", width=14)
        return t

    tbl_open = _make_tbl("  Posições Abertas")
    tbl_resolved = _make_tbl("  Posições Resolvidas — últimos 3 dias")
    n_open = 0
    n_resolved = 0
    total_pnl_resolved = 0.0

    def _is_race(pos_obj) -> bool:
        """Detecta se a posição foi comprada em modo race."""
        if isinstance(pos_obj, dict):
            return bool(pos_obj.get("is_race") or pos_obj.get("trigger") == "race")
        return bool(getattr(pos_obj, "is_race", False) or getattr(pos_obj, "trigger", "") == "race")

    def _status_for_row(pos_obj, city_name: str, cd: "CityDisplayData" = None) -> tuple[str, str]:
        """Retorna (label, style) limpo — sem 'PAPER', etc."""
        s_val = getattr(pos_obj, "status", None)
        is_race_flag = _is_race(pos_obj)
        race_suffix = " (RACE)" if is_race_flag else ""

        # Se temos o CityDisplayData e o mercado actual, verificar preço para PAPER auto-close
        if cd and cd.market and hasattr(pos_obj, "__dict__"):
            token_id = getattr(pos_obj, "token_id", None)
            if token_id:
                for b in cd.market.get("brackets", []):
                    if b.get("token_id") == token_id:
                        ask = b.get("ask") or b.get("price")
                        try:
                            ask_f = float(ask) if ask is not None else None
                        except Exception:
                            ask_f = None
                        if ask_f is not None:
                            if ask_f >= 0.99:
                                return (f"✅ GANHOU{race_suffix}", "bold green")
                            elif ask_f <= 0.01:
                                return (f"❌ PERDEU{race_suffix}", "bold red")
                        break

        # Para dicts (posições em memória do live_bot)
        if isinstance(pos_obj, dict):
            # Verificar se tem flag de resolvido
            if pos_obj.get("sold_by_stop") or pos_obj.get("resolved"):
                pnl = pos_obj.get("realized_pnl", 0)
                lbl = "✅ GANHOU" if pnl >= 0 else "❌ PERDEU"
                return (f"{lbl}{race_suffix}", "bold green" if pnl >= 0 else "bold red")
            # Verificar preço actual se temos cd
            if cd and cd.market:
                pos_label = pos_obj.get("bracket_label") or pos_obj.get("bracket")
                for b in cd.market.get("brackets", []):
                    if b.get("label") == pos_label:
                        ask = b.get("ask") or b.get("price")
                        try:
                            ask_f = float(ask) if ask is not None else None
                        except Exception:
                            ask_f = None
                        if ask_f is not None:
                            if ask_f >= 0.99:
                                return (f"✅ GANHOU{race_suffix}", "bold green")
                            elif ask_f <= 0.01:
                                return (f"❌ PERDEU{race_suffix}", "bold red")
                        break
            return (f"🔵 ABERTA{race_suffix}", "cyan")

        if _HAS_CLOB:
            _status_map = {
                PositionStatus.OPEN:    (f"🔵 ABERTA{race_suffix}",    "cyan"),
                PositionStatus.WON:     (f"✅ GANHOU{race_suffix}",    "bold green"),
                PositionStatus.LOST:    (f"❌ PERDEU{race_suffix}",    "bold red"),
                PositionStatus.EXPIRED: (f"⏱ EXPIROU{race_suffix}",   "dim"),
                PositionStatus.UNKNOWN: ("❓",            "dim"),
            }
            s_lbl, s_sty = _status_map.get(s_val, ("❓", "dim"))
            return s_lbl, s_sty
        return (f"🔵 ABERTA{race_suffix}", "cyan")

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
        cd = next((c for c in city_data if c.city.name == city_name), None)

        if pos is None:
            if not cd or not cd.position:
                continue

            ask = cd.position.get("ask", 0)
            if ask == 0 or ask == 0.01:
                if cd.market:
                    for bracket in cd.market.get("brackets", []):
                        if bracket.get("label") == cd.position.get("bracket"):
                            ask = bracket.get("ask") or bracket.get("price")
                            break

            bkt = str(cd.position.get("bracket", "?"))[:18]

            entry_time = cd.position.get("timestamp") or cd.position.get("time")
            if entry_time:
                d_op = _format_opened_at(entry_time, city_name, city_data)
            else:
                d_op = _format_opened_at(date.today().isoformat(), city_name, city_data)

            entry_ask = ask
            current_ask = entry_ask
            size_usdc = cd.position.get("size_usdc", 1.0)

            if cd.market and cd.position:
                pos_label = cd.position.get("bracket", "")
                for b in cd.market.get("brackets", []):
                    if b.get("label") == pos_label:
                        bid = b.get("bid") or b.get("price") or entry_ask
                        ask_mkt = b.get("ask") or b.get("price") or entry_ask
                        current_ask = (bid + ask_mkt) / 2.0
                        break

            shares = math.floor(size_usdc / entry_ask) if entry_ask > 0 else 0
            if shares > 0 and current_ask > 0:
                pnl_u = shares * (current_ask - entry_ask)
                pnl_p = ((current_ask / entry_ask) - 1.0) * 100 if entry_ask > 0 else 0.0
            else:
                pnl_u = None
                pnl_p = None

            s_lbl, s_sty = _status_for_row(cd.position, city_name, cd)
            # Se o display detecta GANHOU/PERDEU por preço, mover para resolvidas
            resolved = _is_resolved_status(s_lbl)
            if resolved:
                _add_row_to(tbl_resolved, clbl, d_op, bkt, entry_ask, current_ask, pnl_u, pnl_p, shares, s_lbl, s_sty)
                n_resolved += 1
                if pnl_u is not None:
                    total_pnl_resolved += float(pnl_u)
            else:
                _add_row_to(tbl_open, clbl, d_op, bkt, entry_ask, current_ask, pnl_u, pnl_p, shares, s_lbl, s_sty)
                n_open += 1
            continue

        # Helper: getattr para objects, .get() para dicts
        def _g(key, default=None):
            if isinstance(pos, dict):
                return pos.get(key, default)
            return getattr(pos, key, default)

        mid   = _g("current_mid")
        pnl_u = _g("pnl_usd")
        pnl_p = _g("pnl_pct")
        st_raw = getattr(getattr(pos, "status", None), "value",
                         getattr(pos, "status", None))
        if str(st_raw).lower() in ("won", "lost"):
            mid = 1.0 if str(st_raw).lower() == "won" else 0.0
        entry = _g("entry_ask", 0)
        shr   = _g("shares", 0)
        d_op_raw = _g("opened_at") or _g("date_opened", "?")
        d_op = _format_opened_at(d_op_raw, city_name, city_data)
        b_lbl = str(_g("bracket_label", "?"))[:18]

        s_lbl, s_sty = _status_for_row(pos, city_name, cd)
        resolved = _is_resolved_status(s_lbl)
        if resolved:
            _add_row_to(tbl_resolved, clbl, d_op, b_lbl, entry, mid, pnl_u, pnl_p, shr, s_lbl, s_sty)
            n_resolved += 1
            if pnl_u is not None:
                total_pnl_resolved += float(pnl_u)
        else:
            _add_row_to(tbl_open, clbl, d_op, b_lbl, entry, mid, pnl_u, pnl_p, shr, s_lbl, s_sty)
            n_open += 1

    # Adicionar linha "vazio" se tabela estiver vazia (para manter estrutura)
    if n_open == 0:
        tbl_open.add_row("—", "—", "—", "—", "—", "—", "—", "—", Text("sem posições", style="dim"))
    if n_resolved == 0:
        tbl_resolved.add_row("—", "—", "—", "—", "—", "—", "—", "—", Text("sem posições", style="dim"))

    if n_resolved > 0 and total_pnl_resolved != 0.0:
        pc = "bold green" if total_pnl_resolved >= 0 else "bold red"
        tbl_resolved.add_section()
        tbl_resolved.add_row("", "", "", "", "TOTAL P&L", "",
                             Text(f"{total_pnl_resolved:+.2f}$", style=pc), "", "")

    return tbl_open, tbl_resolved


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

def _format_opened_at(d_op_raw, city_name: str, city_data: list) -> str:
    """Formata a data de abertura com hora local da cidade.
    FIX P2-10: suporta múltiplos formatos de data de forma robusta.
    """
    if d_op_raw is None or d_op_raw == "?":
        return "?"

    # Find city's timezone
    city_tz = None
    for cd in city_data:
        if cd.city.name == city_name:
            try:
                city_tz = ZoneInfo(cd.city.timezone)
            except Exception:
                pass
            break

    # Parse the raw date — tentar múltiplos formatos em cascata
    dt = None
    if hasattr(d_op_raw, 'isoformat'):
        # datetime object
        dt = d_op_raw
        if not (hasattr(dt, 'tzinfo') and dt.tzinfo):
            dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    elif isinstance(d_op_raw, (int, float)):
        # Unix timestamp
        try:
            dt = datetime.fromtimestamp(d_op_raw, tz=ZoneInfo("UTC"))
        except Exception:
            pass
    elif isinstance(d_op_raw, str):
        s = d_op_raw.strip()
        # 1) ISO 8601 com timezone (ex: 2024-01-15T14:30:00+00:00)
        for fmt in ["%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z"]:
            try:
                dt = datetime.strptime(s, fmt)
                break
            except ValueError:
                continue
        # 2) ISO 8601 sem timezone
        if dt is None:
            for fmt in ["%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"]:
                try:
                    dt = datetime.strptime(s, fmt).replace(tzinfo=ZoneInfo("UTC"))
                    break
                except ValueError:
                    continue
        # 3) Formato EU: dd/mm/yyyy HH:MM:SS
        if dt is None:
            for fmt in ["%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M"]:
                try:
                    dt = datetime.strptime(s, fmt).replace(tzinfo=ZoneInfo("UTC"))
                    break
                except ValueError:
                    continue
        # 4) Formato US: mm/dd/yyyy HH:MM:SS
        if dt is None:
            for fmt in ["%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M"]:
                try:
                    dt = datetime.strptime(s, fmt).replace(tzinfo=ZoneInfo("UTC"))
                    break
                except ValueError:
                    continue
        # 5) Formato simples: yyyy-mm-dd HH:MM:SS
        if dt is None:
            for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"]:
                try:
                    dt = datetime.strptime(s, fmt).replace(tzinfo=ZoneInfo("UTC"))
                    break
                except ValueError:
                    continue
        # 6) Só data
        if dt is None:
            for fmt in ["%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"]:
                try:
                    dt = datetime.strptime(s, fmt).replace(tzinfo=ZoneInfo("UTC"))
                    break
                except ValueError:
                    continue
        # 7) Fallback: truncar string
        if dt is None:
            return s[:19] if len(s) > 19 else s

    if dt is None:
        return str(d_op_raw)[:19]

    # Convert to city timezone
    if city_tz:
        try:
            dt_local = dt.astimezone(city_tz)
            return dt_local.strftime("%Y-%m-%d %H:%M") + f" ({dt_local.strftime('%z')[:3]})"
        except Exception:
            pass

    return dt.strftime("%Y-%m-%d %H:%M") + " (UTC)"



def _city_to_snapshot(cd: "CityDisplayData") -> dict:
    city_dt = datetime.now(tz=ZoneInfo(cd.city.timezone))
    threshold, hour_min = _active_params(cd)
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

    try:
        from city_groups import group_of
        _grp = group_of(cd.city.name)
    except Exception:
        _grp = "ATLANTIC"
    return {
        "name": cd.city.name,
        "label": _label(cd.city.name),
        "flag": _flag(cd.city.name),
        "group": _grp,
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
        # "om_forecast": removido — Open-Meteo descontinuado
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
            # §106: sinal = mesmo critério dos cards (status "SIGNAL!" do
            # _city_status, que já sabe que no rebound se compra p < threshold)
            "n_signal": sum(1 for c in cities if "SIGNAL" in (c.get("status") or "")),
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
    def _has_signal(cd):
        p = cd.p_rebound if getattr(cd, "strategy_name", None) == "cassiopeia" and getattr(cd, "p_rebound", None) is not None else cd.p_ensemble
        thr = getattr(cd, "signal_threshold", None) or (cd.city.threshold if cd.city.threshold is not None else 0.65)
        if p is None or cd.bought:
            return False
        return (p < thr) if _signals_low(cd) else (p >= thr)
    n_signal    = sum(1 for cd in city_data if _has_signal(cd))
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
            d_open_raw = getattr(pos, "date_opened", None)
            # Garantir que ambos são strings no formato ISO para comparação segura
            d_open = d_open_raw.isoformat() if hasattr(d_open_raw, 'isoformat') else str(d_open_raw or "")
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
    # SEMPRE mostrar ambas as tabelas, mesmo vazias
    pos_open_tbl, pos_resolved_tbl = _positions_tables(city_data, trading_mode_str)
    _con.print()
    _con.print(Panel(pos_open_tbl, border_style="dim cyan", padding=(0, 1)))
    _con.print()
    _con.print(Panel(pos_resolved_tbl, border_style="dim cyan", padding=(0, 1)))

    # ── FOOTER ─────────────────────────────────────────────────────
    # HOJE (dados do dia actual de cada cidade)
    pnl_dia   = sum(cd.daily_pnl  for cd in city_data)
    trd_dia   = sum(cd.n_trades   for cd in city_data)
    wins_dia  = sum(1 for cd in city_data if cd.daily_pnl > 0 and cd.n_trades > 0)

    # ATÉ AGORA (sessão: desde que o bot arrancou)
    total_pnl_session = session_stats.get("total_pnl", 0.0)
    total_trades_session = session_stats.get("total_trades", 0)

    # Posições resolvidas na sessão (contar de todos os dias desde o arranque)
    n_resolved_session = 0
    for cd in city_data:
        if cd.positions_all:
            for pos in cd.positions_all:
                status = getattr(getattr(pos, "status", None), "value", getattr(pos, "status", None))
                if status and str(status).lower() in ("won", "lost", "expired"):
                    n_resolved_session += 1

    # Cores
    pnl_dia_c = "bold green" if pnl_dia >= 0 else "bold red"
    pnl_sess_c = "bold green" if total_pnl_session >= 0 else "bold red"

    footer = Text()

    # ── Linha 1: ATÉ AGORA (sessão) ──
    footer.append("  ATÉ AGORA: ", style="bold dim")
    footer.append(f"{total_trades_session} trades", style="bold white")
    footer.append(f"  ({n_resolved_session} resolv.)  ", style="dim")
    footer.append("PnL: ", style="dim")
    footer.append(f"{total_pnl_session:+.2f}$  ", style=pnl_sess_c)

    # ── Linha 2: HOJE ──
    footer.append("│  ", style="dim")
    footer.append("HOJE: ", style="bold dim")
    footer.append(f"{trd_dia} trades", style="bold white")
    footer.append(f"  ({wins_dia}/{n_cities} cidades +)  ", style="dim")
    footer.append("PnL: ", style="dim")
    footer.append(f"{pnl_dia:+.2f}$   ", style=pnl_dia_c)

    # Uptime
    if session_stats.get("start_time"):
        elapsed = lisbon_now - session_stats["start_time"]
        h, rem  = divmod(int(elapsed.total_seconds()), 3600)
        m, _    = divmod(rem, 60)
        footer.append(f"│  uptime {h}h{m:02d}m  ", style="dim")
    footer.append(f"actualizado {lisbon_str}", style="dim")
    footer.append("   Ctrl+C para parar", style="dim")

    _con.print()
    _con.print(footer)
    _con.print()
