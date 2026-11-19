"""
cassiopeia_live_bot.py
======================
Bot de trading ao vivo — Multi-cidade (Cassiopeia + Andromeda via env vars).

Uso:
    python live_bot.py --cities munich --mode single --run paper
    python live_bot.py --cities munich,dallas --mode single --run real
"""

import argparse
import csv
import math
import json
import time
import os
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Optional
import threading
from cities.config import CityConfig, get_city
from predictor import set_city, load_models, predict_ensemble, compute_prev7, init_history_max
# D0-fix: fee Weather REAL — 0.05×p×(1-p)×shares (a do backtester era
# 0.02 linear só-lucros, triplo errada). Wrapper local, mesma assinatura:
import math as _math
from polymarket_clob import weather_taker_fee as _wt_fee


def _compute_realized_pnl(entry_ask: float, sell_bid: float, size_usdc: float,
                          taker_fee_rate: float = None) -> dict:
    if entry_ask <= 0 or sell_bid <= 0:
        return {"shares": 0, "actual_invested": 0.0, "recovered": 0.0,
                "realized_pnl": 0.0, "fee": 0.0}
    shares = _math.floor(size_usdc / entry_ask)
    if shares <= 0:
        return {"shares": 0, "actual_invested": 0.0, "recovered": 0.0,
                "realized_pnl": 0.0, "fee": 0.0}
    actual_invested = shares * entry_ask
    recovered = shares * sell_bid
    gross = recovered - actual_invested
    fee = _wt_fee(entry_ask, shares) + _wt_fee(sell_bid, shares)
    return {"shares": shares, "actual_invested": round(actual_invested, 4),
            "recovered": round(recovered, 4),
            "realized_pnl": round(gross - fee, 2), "fee": round(fee, 2)}
from weather import (
    make_wu_session, fetch_wu_latest,
    fetch_wu_forecast_max,
    bootstrap_today, ceil_slot, floor_slot, is_plausible_temp,
)
from weather_v3 import (
    v3_fetch_current, v3_fetch_forecast_daily, v3_bootstrap_today,
)
from modules.strategy_factory import create_strategy
from polymarket_clob import ClobClient, TradingMode, GAMMA_API, PositionStatus, Position, round_to_tick
from resolution_rules import bracket_contains, find_bracket as _official_find_bracket, round_half_up
from zoneinfo import ZoneInfo
import copy

# ── NOVO: logger de telemetria para backtest offline
try:
    from tick_logger import get_tick_logger
    _TICK_LOGGER = get_tick_logger()
except Exception as e:
    print(f"  [tick_logger] Aviso: tick_logger não carregado ({e}) — telemetria desactivada")
    _TICK_LOGGER = None

# ── Month names para Polymarket slug (usado em todos os eventos)
MONTH_NAMES = {
    1: "january", 2: "february", 3: "march", 4: "april", 5: "may",
    6: "june", 7: "july", 8: "august", 9: "september", 10: "october",
    11: "november", 12: "december",
}

# ANSI
R = "\033[0m"
B = "\033[1m"
DIM = "\033[2m"
C = {
    "cyan": "\033[96m", "green": "\033[92m", "yellow": "\033[93m",
    "red": "\033[91m", "blue": "\033[94m",
    "gray": "\033[90m", "white": "\033[97m",
}

LOG_DIR = Path(os.environ.get("CASS_LOG_DIR", "live_bot_logs"))
_TG_TRADING_MODE: str = "paper"  # Module-level trading mode for Telegram token selection
LOG_DIR.mkdir(exist_ok=True)
# User policy: all active strategies use immediate TAKER execution. Legacy
# maker/shadow branches remain readable for old ledgers but cannot be activated.
TAKER_ONLY = True




PARCEL_SIZE = 1.0
DEFAULT_BANKROLL = 100.0  # FIX MÉDIO-13: separado de PARCEL_SIZE
# D4/era v4.1-emenda (07/10): override opcional do min_buy_ask via CLI
# (--min-buy-ask). None = a config ativa manda (comportamento habitual).
# Usado para pinar a banda do micro (real) sem tocar na config partilhada.
_MIN_BUY_ASK_OVERRIDE = None


def _load_paper_state(city_name: str) -> dict:
    """Carrega estado PAPER persistido. FIX S1-13: JSON corrupto -> backup
    + aviso (nunca evaporar silenciosamente como o positions do Dia 1)."""
    path = LOG_DIR / f"paper_state_{city_name}.json"
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception as e:
            backup = path.with_suffix(".json.corrupt")
            try:
                backup.write_text(path.read_text())
                print(f"  [AVISO] paper_state {city_name} CORROMPIDO — "
                      f"backup em {backup.name} ({e})")
            except Exception:
                print(f"  [AVISO] paper_state {city_name} ilegivel ({e})")
    return {}


def _save_paper_state(city_name: str, state_dict: dict, city_today: date = None, bankroll: float = None) -> None:
    """Persiste estado PAPER de forma atómica."""
    path = LOG_DIR / f"paper_state_{city_name}.json"
    tmp_path = LOG_DIR / f".tmp_paper_state_{city_name}_{int(time.time()*1000)}.json"
    # FIX P2-1a: incluir data no estado persistido
    payload = dict(state_dict)
    if city_today is not None:
        payload["_last_date"] = str(city_today)
    # FIX MÉDIO-12: persistir bankroll para consistência após restart
    if bankroll is not None:
        payload["_bankroll"] = float(bankroll)
    try:
        tmp_path.write_text(json.dumps(payload, indent=2, default=str))
        tmp_path.replace(path)
    except Exception as e:
        print(f"  {C['yellow']}{city_name}: falha a guardar paper_state: {e}{R}")
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except Exception:
                pass


# ════════════════════════════════════════════════════
#  POLYMARKET FETCHER
# ════════════════════════════════════════════════════

class PolymarketFetcher:
    """Fetch do Polymarket API para obter mercado de temperatura."""

    def __init__(self, city_config: CityConfig):
        self.city = city_config

    def date_to_slug(self, d: date) -> str:
        """Gera o slug do mercado para a data."""
        month_name = MONTH_NAMES[d.month]
        return f"{self.city.polymarket_slug_pfx}-{month_name}-{d.day}-{d.year}"

    def fetch_market(self, d: date) -> Optional[dict]:
        """Busca o mercado do Polymarket para a data."""
        import requests

        slug = self.date_to_slug(d)

        def _try(params):
            try:
                all_events = []
                page = 1
                while True:
                    params_copy = dict(params)
                    params_copy["limit"] = 100
                    params_copy["offset"] = (page - 1) * 100
                    r = requests.get(f"{GAMMA_API}/events", params=params_copy, timeout=15)
                    r.raise_for_status()
                    ev = r.json()
                    if isinstance(ev, list):
                        all_events.extend(ev)
                        if len(ev) < 100:
                            break
                        page += 1
                    else:
                        if ev:
                            all_events.append(ev)
                        break
                return all_events
            except Exception:
                return []

        # Tentativas com diferentes queries
        month_name = MONTH_NAMES[d.month].capitalize()
        events = (
            _try({"slug": slug}) or
            _try({"q": f"highest temperature {self.city.name} {month_name} {d.day} {d.year}", "limit": 10}) or
            _try({"q": f"{self.city.name} temperature {d.year}", "limit": 10})
        )

        if not events:
            print(f"  {C['yellow']}  [DEBUG] {self.city.name}: NENHUM evento encontrado na API para {d} (slug={slug}){R}")
            return None

        # Filtrar eventos relevantes (contendo nome da cidade e temperatura)
        city_names = {
            self.city.name.lower(),
            self.city.name.replace("_", " ").lower(),
            self.city.name.replace("_", "-").lower(),
        }
        def is_relevant(e):
            t = str(e.get("title", "")).lower()
            s = str(e.get("slug", "")).lower()
            # Obrigatório: nome da cidade. Opcional: menção a temperatura.
            city_ok = any(name in t or name in s for name in city_names)
            temp_ok = ("temperature" in t or "highest" in t or "temp" in t)
            return city_ok and temp_ok

        relevant = [e for e in events if isinstance(e, dict) and is_relevant(e)]
        if not relevant:
            print(f"  {C['yellow']}  [DEBUG] {self.city.name}: Eventos encontrados, mas nenhum relevante para temp/cidade.{R}")
            return None

        event = max(relevant, key=lambda e: float(e.get("volume", 0) or 0))
        brackets = []

        for m in event.get("markets", []):
            raw_label = (m.get("groupItemTitle") or m.get("outcomeTitle") or
                         m.get("title") or m.get("question") or "")
            label = self._normalize_label(raw_label)
            v = self._extract_temp(label)
            if v is None:
                continue

            def _jload(x):
                if isinstance(x, str):
                    try: return json.loads(x)
                    except (json.JSONDecodeError, TypeError, ValueError):
                        return []
                return x

            outcomes = _jload(m.get("outcomes", "[]"))
            prices = _jload(m.get("outcomePrices", "[]"))
            token_ids = _jload(m.get("clobTokenIds", []))

            price_yes, token_yes = None, None
            for i, out in enumerate(outcomes):
                if str(out).lower() in ("yes", "true", "1"):
                    price_yes = float(prices[i]) if i < len(prices) and prices[i] else None
                    token_yes = token_ids[i] if i < len(token_ids) else None
                    break

            if price_yes is None and prices:
                try: price_yes = float(prices[0])
                except (TypeError, ValueError):
                    price_yes = 0.5
            if price_yes is None:
                continue

            brackets.append({
                "label": label,
                "price": round(price_yes, 4),
                "ask": round(price_yes, 4),
                "token_id": token_yes,
                "temp_lo": self._bracket_lo(label),
                "temp_hi": self._bracket_hi(label),
                "volume": float(m.get("volume", 0) or 0),
            })

        if not brackets:
            print(f"  {C['yellow']}  [DEBUG] {self.city.name}: Evento relevante encontrado, mas sem brackets válidos.{R}")
            return None

        brackets.sort(key=lambda b: b["temp_lo"])
        return {
            "title": event.get("title", f"{self.city.name} Max Temp"),
            "end_date": event.get("endDate", ""),
            "volume": float(event.get("volume", 0) or 0),
            "brackets": brackets,
            "n_outcomes": len(brackets),
            "slug": slug,
        }

    def _extract_temp(self, text: str) -> Optional[float]:
        """Extrai temperatura de um label, convertendo Fahrenheit para Celsius se necessário."""
        import re
        # 1. Tentar detectar Celsius explicitamente
        m_c = re.search(r"([-]?\d+(?:\.\d+)?)\s*°?\s*[cC]\b", str(text), re.IGNORECASE)
        if m_c:
            return float(m_c.group(1))

        # 2. Tentar detectar Fahrenheit explicitamente
        m_f = re.search(r"([-]?\d+(?:\.\d+)?)\s*°?\s*[fF]\b", str(text), re.IGNORECASE)
        if m_f:
            f = float(m_f.group(1))
            return round((f - 32) * 5 / 9, 1)

        # 3. Fallback: outros padrões numéricos
        for pat in [
            r"([-]?\d+(?:\.\d+)?)\s+or\s+(?:higher|lower|above|below)",
            r"be\s+([-]?\d+(?:\.\d+)?)",
            r"between\s+([-]?\d+(?:\.\d+)?)\s+and",
            r"([-]?\d+(?:\.\d+)?)\s*[-–]\s*\d+",
            r"^\s*([-]?\d+(?:\.\d+)?)\s*$",
        ]:
            m = re.search(pat, str(text), re.IGNORECASE)
            if m:
                return float(m.group(1))
        return None

    def _bracket_lo(self, label: str) -> float:
        v = self._extract_temp(label)
        if v is None: return 0.0
        s = str(label).lower()
        return -99.0 if any(x in s for x in ("or lower", "or below", "<=")) else v

    def _bracket_hi(self, label: str) -> float:
        v = self._extract_temp(label)
        if v is None: return 99.0
        s = str(label).lower()
        return 99.0 if any(x in s for x in ("or higher", "or above", ">=", "≥")) else v

    def _normalize_label(self, text: str) -> str:
        """Normaliza o label do bracket, garantindo que exibe Celsius."""
        v = self._extract_temp(text)
        if v is None:
            return text
        s = text.lower()
        if any(x in s for x in ("higher", "above", ">=", "≥")):
            return f"{v:.1f}°C or higher"
        if any(x in s for x in ("lower", "below", "<=", "≤")):
            return f"{v:.1f}°C or lower"
        return f"{v:.1f}°C"

    @staticmethod
    def find_bracket(market: dict, temp: float) -> Optional[dict]:
        """Encontra o bracket que contém a temperatura fornecida.

        Args:
            market: dict do mercado com lista de brackets.
            temp: temperatura actual (running_max ou forecast) em °C.
        Returns:
            Bracket dict mais próximo ou que contém a temperatura.
        """
        if not market:
            return None
        return _official_find_bracket(market.get("brackets", []), float(temp), fallback=True)

# ════════════════════════════════════════════════════
#  DATACLASSES
# ════════════════════════════════════════════════════

@dataclass
class DailyStats:
    date: date
    trades: list = field(default_factory=list)
    total_invested: float = 0.0
    daily_pnl: float = 0.0
    stop_losses_triggered: int = 0


@dataclass
class SessionStats:
    start_time: datetime
    total_trades: int = 0
    total_pnl: float = 0.0


@dataclass
class CityState:
    """Estado de uma cidade no bot multi-cidade."""
    city: CityConfig
    models: dict
    strategy_mode: str = "single"
    slots_so_far: list[dict] = field(default_factory=list)
    series_today: dict[tuple, float] = field(default_factory=dict)
    cloud_by_hour: dict[int, int] = field(default_factory=dict)
    history_max: dict = field(default_factory=dict)
    entry: any = None
    market: dict | None = None
    fetcher: PolymarketFetcher | None = None
    wu_key: str = os.environ.get("WU_API_KEY", "")   # fix saga: key do .env
    wu_sess: any = None
    # ── REMOVIDO: om_sess (Open-Meteo removido)
    clob: ClobClient | None = None
    trading_mode: TradingMode = TradingMode.PAPER
    latest_obs: dict | None = None
    last_forecast_hour: int = -1
    last_wu_forecast_max: int | None = None
    # ── REMOVIDO: last_om_forecast_max (Open-Meteo removido)
    last_market_min: tuple[int, int] | None = None
    daily_stats: DailyStats = None  # ← NOVO
    last_p_ensemble: float = 0.0
    last_p_lgbm: Optional[float] = None
    last_target_bracket: Optional[dict] = None
    _last_date: Optional[date] = None
    _last_bankroll_hour: int = -1
    _settled_position_ids: set[str] = field(default_factory=set)
    # FIX CRÍTICO-2: timestamps para TTL de settled IDs (7 dias)
    _settled_ids_timestamps: dict[str, float] = field(default_factory=dict)
    _bootstrap_pending: bool = True
    dashboard_enabled: bool = False
    # ── NOVOS: filtros ──
    max_buy_ask: float = 0.85
    _last_near_signal_ts: float = 0.0
    # ── FIX bankroll PAPER: tracking de delta ──
    _last_applied_pnl: float = 0.0
    # ── FIX 1: guardar threshold_override para reaplicar no reset diário ──
    threshold_override: Optional[float] = None
    # ── FIX 4: throttle para _save_daily_stats ──
    _last_stats_save: float = 0.0
    _last_saved_trades: int = 0
    _last_saved_stops: int = 0
    # ── FIX 5: backoff para bootstrap ──
    _last_bootstrap_attempt: float = 0.0
    # ── FIX 7: throttle para persistir history_max ──
    _last_history_save: float = 0.0
    # ── FIX C2: lock para thread safety (Telegram polling vs main loop) ──
    _lock: threading.Lock = field(default_factory=threading.Lock)
    # FIX P2-8: contador de falhas consecutivas de bootstrap
    _bootstrap_failure_count: int = 0

# ════════════════════════════════════════════════════
#  HELPERS
# ════════════════════════════════════════════════════

# ════════════════════════════════════════════════════
#  SNAPSHOT SEGURO PARA DISPLAY (FIX CRÍTICO-3)
# ════════════════════════════════════════════════════

def _snapshot_for_display(state: CityState):
    """Cria uma snapshot thread-safe dos dados do state para o display.

    Evita race conditions quando a thread do Telegram ou o dashboard
    acedem a dados enquanto o main loop os está a modificar.
    """
    with state._lock:
        snap = copy.copy(state)
        # Copiar estruturas mutáveis
        snap.slots_so_far = list(state.slots_so_far)
        snap.latest_obs = dict(state.latest_obs) if state.latest_obs else None
        snap.market = dict(state.market) if state.market else None
        snap.series_today = dict(state.series_today)
        snap.cloud_by_hour = dict(state.cloud_by_hour)
        snap.history_max = dict(state.history_max)
        # entry é mutável mas geralmente está estável durante o display
        # não copiamos para manter referência aos métodos
        return snap


def city_now(city: CityConfig) -> datetime:
    return datetime.now(tz=ZoneInfo(city.timezone))


def city_date(city: CityConfig) -> date:
    return city_now(city).date()


def bot_now() -> datetime:
    return datetime.now(tz=ZoneInfo("Europe/Lisbon"))


# ── FIX Bug ALTO-8: helper para marcar bets como resolved ──
def _mark_bet_resolved(city_name: str, d: date, settled_pnl: float) -> None:
    """Marca a bet do dia como resolved no ficheiro bets_*.json."""
    bets_path = LOG_DIR / f"bets_{city_name}_{d}.json"
    if not bets_path.exists():
        return
    try:
        bets = json.loads(bets_path.read_text())
        if bets:
            # Marcar a última bet do dia (a que está aberta)
            last_bet = bets[-1]
            last_bet["resolved"] = True
            last_bet["status"] = "won" if settled_pnl >= 0 else "lost"
            last_bet["realized_pnl"] = settled_pnl
            last_bet["exit_time"] = bot_now().isoformat()
            tmp_path = LOG_DIR / f".tmp_bets_{city_name}_{d}_{int(time.time()*1000)}.json"
            tmp_path.write_text(json.dumps(bets, indent=2))
            tmp_path.replace(bets_path)
    except Exception as e:
        print(f"  {C['yellow']}{city_name}: falha a marcar bet como resolved: {e}{R}")


def _save_daily_stats(stats: DailyStats, city_name: str) -> None:
    log_path = LOG_DIR / f"{city_name}_{stats.date}.json"
    tmp_path = LOG_DIR / f".tmp_{city_name}_{stats.date}_{int(time.time()*1000)}.json"
    data = {
        "date": str(stats.date),
        "trades": len(stats.trades),
        "total_invested": round(stats.total_invested, 2),
        "daily_pnl": round(stats.daily_pnl, 2),
        "stop_losses_triggered": stats.stop_losses_triggered,
    }
    try:
        tmp_path.write_text(json.dumps(data, indent=2))
        tmp_path.replace(log_path)
    except Exception as e:
        print(f"  {C['yellow']}{city_name}: falha a guardar stats: {e}{R}")
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except Exception:
                pass


def _append_bet_record(bet_record: dict, city_name: str, d: date) -> None:
    """Persistir trades para anti-duplicado entre restarts (atómico)."""
    bets_path = LOG_DIR / f"bets_{city_name}_{d}.json"
    tmp_path = LOG_DIR / f".tmp_bets_{city_name}_{d}_{int(time.time()*1000)}.json"
    try:
        existing = json.loads(bets_path.read_text()) if bets_path.exists() else []
        existing.append(bet_record)
        tmp_path.write_text(json.dumps(existing, indent=2))
        tmp_path.replace(bets_path)  # atómico rename
    except Exception as e:
        print(f"  {C['yellow']}{city_name}: falha a guardar bet record: {e}{R}")
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except Exception:
                pass


def _bootstrap_state_today(state: CityState) -> None:
    """Carrega slots já conhecidos do dia via V3 ICAO, fallback V2 ICAO.

    Apenas ICAO — sem PWS.
    """
    city = state.city
    now_city = city_now(city)
    limit_h, limit_s = floor_slot(now_city.hour, now_city.minute)
    limit_idx = limit_h * 60 + limit_s

    series, slots = {}, []

    # §98: METAR primeiro — é a fonte em que o mercado resolve
    if city.icao:
        try:
            from metar import fetch_metar_today_slots
            from weather import _get_city_timezone, _city_date
            _m_slots = fetch_metar_today_slots(
                city.icao, _get_city_timezone(city), _city_date(city))
            if len(_m_slots) >= 3:
                slots = _m_slots
                print(f"  {C['green']}{city.name}: METAR bootstrap OK "
                      f"({len(slots)} slots){R}")
        except Exception as e:
            print(f"  {C['yellow']}{city.name}: METAR bootstrap falhou: {e}{R}")

    if len(slots) < 3 and city.icao and state.wu_key:
        # Tentar V3 ICAO primeiro
        try:
            series, slots = v3_bootstrap_today(city.icao, state.wu_key)
            if len(slots) >= 4:
                print(f"  {C['green']}{city.name}: V3 ICAO bootstrap OK ({len(slots)} slots){R}")
        except Exception as e:
            print(f"  {C['yellow']}{city.name}: V3 ICAO bootstrap falhou: {e}{R}")

        # Fallback V2 ICAO se V3 falhou ou devolveu poucos slots
        if len(slots) < 4:
            try:
                series, slots = bootstrap_today(
                    city, state.wu_key, state.wu_sess, verbose=not state.dashboard_enabled
                )
                print(f"  {C['green']}{city.name}: V2 ICAO bootstrap OK ({len(slots)} slots){R}")
            except Exception as e2:
                print(f"  {C['red']}{city.name}: V2 ICAO bootstrap também falhou: {e2}{R}")
    elif not city.icao:
        print(f"  {C['red']}{city.name}: SEM ICAO — bootstrap impossível{R}")

    # FIX P2-8: health check bootstrap
    if len(slots) < 4:
        state._bootstrap_failure_count += 1
        count = state._bootstrap_failure_count
        print(f"  {C['yellow']}{city.name}: Aviso — {len(slots)} slots (falha #{count}){R}")
        if count == 5:
            _tg_alert(f"⚠️ <b>{city.name.title()}</b> bootstrap falhou 5x seguidas — "
                      f"dados meteorológicos em falta. Modelo pode estar a operar cego.")
        elif count == 10:
            _tg_alert(f"🚨 <b>{city.name.title()}</b> bootstrap falhou 10x seguidas — "
                      f"CRÍTICO: sem dados há ~{(count * 60)//60}min. "
                      f"Verificar API WU / ICAO.")
    else:
        if state._bootstrap_failure_count >= 5:
            _tg_alert(f"✅ <b>{city.name.title()}</b> bootstrap recuperado — "
                      f"{len(slots)} slots carregados.")
        state._bootstrap_failure_count = 0

    filtered_slots = [
        s for s in slots
        if city.day_start <= int(s["hour"]) <= city.day_end
        and (int(s["hour"]) * 60 + int(s.get("slot30", 0))) <= limit_idx
    ]

    state.slots_so_far = sorted(
        filtered_slots,
        key=lambda s: int(s["hour"]) * 60 + int(s.get("slot30", 0)),
    )
    state.series_today = {
        (int(s["hour"]), int(s.get("slot30", 0)), idx): float(s["temp_c"])
        for idx, s in enumerate(state.slots_so_far)
    }
    state.cloud_by_hour = {
        int(s["hour"]): int(s.get("cloud_cover", 50))
        for s in state.slots_so_far
    }
    state._bootstrap_pending = not bool(state.slots_so_far)


def _reconcile_bets_from_csv(state: CityState) -> float:
    """S1-7c: bets nao-resolvidos de dias PASSADOS -> resolver via CSV historico
    e marcar no proprio json. Reconstrui o que o restart evaporou."""
    city = state.city
    total = 0.0
    today = city_date(city)
    # FIX: o CSV historico acaba em 2026-07-18 — os dias do paper NAO estao la.
    # Fonte correta: {city}_history_max.json (maximos diarios reais, escrito ao vivo)
    hist_path = LOG_DIR / f"{city.name}_history_max.json"
    hist_max = {}
    if hist_path.exists():
        try:
            hist_max = {k: float(v) for k, v in
                        json.loads(hist_path.read_text()).items()}
        except Exception:
            hist_max = {}

    for bets_path in LOG_DIR.glob(f"bets_{city.name}_*.json"):
        try:
            day_str = bets_path.stem.split("_")[-1]
            d = date.fromisoformat(day_str)
        except Exception:
            continue
        if d >= today:
            continue
        try:
            bets = json.loads(bets_path.read_text())
        except Exception:
            continue
        changed = False
        for b in bets:
            if b.get("resolved"):
                continue
            won = None
            peak = None
            # §98: preferir a resolução OFICIAL do mercado (Gamma) — o WU
            # diverge do METAR oficial em ~20% dos dias (basis risk).
            slug = b.get("market_slug") or ""
            if slug:
                try:
                    from official_resolution import position_won
                    won = position_won(slug, float(b.get("temp_lo", -99)),
                                       float(b.get("temp_hi", 99)))
                except Exception:
                    won = None
            if won is None:
                # fallback: peak do dia no histórico WU gravado ao vivo
                peak = hist_max.get(d.isoformat())
                if peak is None:
                    continue
                lo, hi = float(b.get("temp_lo", -99)), float(b.get("temp_hi", 99))
                won = bracket_contains(lo, hi, peak)
            pnl = ((1.0 - float(b.get("ask", 0))) * float(b.get("shares", 1))
                   if won else -float(b.get("size_usdc", 1)))
            b["resolved"] = True
            b["status"] = "won" if won else "lost"
            b["realized_pnl"] = round(pnl, 2)
            if peak is not None:
                b["peak_temp"] = peak
            b["resolution_source"] = "official" if slug and peak is None else "wu"
            total += pnl
            changed = True
        if changed:
            tmp = bets_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(bets, indent=2))
            tmp.replace(bets_path)
            print(f"  {C['green']}{city.name}: bets de {day_str} reconciliados (oficial Gamma > WU){R}")
    return total


def _settle_paper_positions_for_day(state, city_today: date,
                                    settle_today: bool = True) -> float:
    """Resolve PAPER positions abertas — apenas com resolução OFICIAL para o
    dia atual; peak completo do histórico apenas para dias passados.

    P0.2 (Fase 2): o settlement prematuro com `max(slots_so_far)` parcial
    foi eliminado. Posições do dia atual só resolvem quando a Gamma API
    confirmar o vencedor oficial (que ocorre tipicamente 1-3h após o
    market close). Até lá, a posição fica OPEN — o que é o comportamento
    correto (o mercado real também não fechou).

    settle_today=False (startup): posições do PRÓPRIO dia são saltadas
    (igual ao comportamento anterior — o peak ainda é parcial).
    """
    if not state.clob or not hasattr(state.clob, "positions"):
        return 0.0

    def _peak_for_date(target_day: date) -> Optional[float]:
        """Peak OFICIAL do dia target.

        Para hoje (target_day == city_today): devolve sempre None — o peak
        parcial intra-day não é a resolução oficial e NUNCA deve ser usado
        para fechar posições paper (P0.2).

        Para dias passados: lê primeiro {city}_history_max.json (escrito ao
        vivo pelo predictor.save_history_max), fallback para historic CSV.
        """
        if target_day == city_today:
            # P0.2 FIX: nunca usar partial peak para fechar o dia.
            return None

        # 1) history_max.json — gravado ao vivo, fonte primária
        hist_max_path = state.clob.log_dir / f"{state.city.name}_history_max.json"
        if hist_max_path.exists():
            try:
                hist_max = json.loads(hist_max_path.read_text())
                v = hist_max.get(target_day.isoformat())
                if v is not None:
                    return float(v)
            except Exception:
                pass

        # 2) Fallback CSV (pode não ter o dia mais recente)
        csv_path = Path("historic") / f"{state.city.name}.csv"
        if not csv_path.exists():
            return None

        target_keys = {
            target_day.strftime("%Y-%m-%d"),
            target_day.strftime("%d/%m/%Y"),
        }
        max_temp: Optional[float] = None
        try:
            with csv_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if str(row.get("date", "")).strip() not in target_keys:
                        continue
                    t_raw = row.get("temp_c")
                    if t_raw in (None, ""):
                        continue
                    try:
                        t = float(t_raw)
                        max_temp = t if max_temp is None else max(max_temp, t)
                    except (TypeError, ValueError):
                        continue
        except Exception:
            return None
        return max_temp

    settled_pnl = 0.0
    peaks_cache: dict[str, Optional[float]] = {}

    for pos in state.clob.positions.open_positions():
        pos_day_raw = str(getattr(pos, "date_opened", "") or "")
        try:
            pos_day = date.fromisoformat(pos_day_raw)
        except Exception:
            continue

        # Skip future positions
        if pos_day > city_today:
            continue

        # §106: ficheiro partilhado pela frota — só settles posições DESTA
        # cidade (senão cada cidade settle as posições das outras com o SEU
        # peak, como aconteceu em 11/11 com KL).
        _pos_slug = str(getattr(pos, "market_slug", "") or "")
        _pos_city = ""
        if _pos_slug:
            _pos_city = (
                _pos_slug.split("-on-")[0].split("-in-")[-1].lower()
            )
        if _pos_city and _pos_city != state.city.name.replace("_", "-"):
            continue

        # Startup: skip today's positions
        if not settle_today and pos_day == city_today:
            continue

        pos_id = str(
            getattr(pos, "order_id", "")
            or getattr(pos, "token_id", "")
            or getattr(pos, "bracket_label", "")
        )
        if pos_id and pos_id in state._settled_position_ids:
            continue

        # §98: PRIMEIRO tenta resolução OFICIAL via Gamma API
        slug = str(getattr(pos, "market_slug", "") or "")
        won_official = None
        if slug:
            try:
                from official_resolution import position_won as _official_won
                won_official = _official_won(
                    slug,
                    float(getattr(pos, "temp_lo", -99)),
                    float(getattr(pos, "temp_hi", 99)),
                )
            except Exception:
                won_official = None

        if won_official is not None:
            # Resolução oficial disponível — settle com base nela
            if state.clob.positions.resolve_paper_position_official(pos, won_official):
                settled_pnl += float(getattr(pos, "pnl_usd", 0.0) or 0.0)
                if pos_id:
                    state._settled_position_ids.add(pos_id)
                    state._settled_ids_timestamps[pos_id] = time.time()
            continue

        # P0.2 FIX: para o dia ATUAL sem resolução oficial ainda — SKIP.
        # Não usar partial peak. O próximo tick voltará a tentar a Gamma.
        if pos_day == city_today:
            continue

        # Dia PASSADO sem resolução oficial (ex.: Gamma em maintenance) —
        # usa peak completo do histórico. Para o dia fechado, o max(slots)
        # já não é parcial.
        day_key = pos_day.isoformat()
        if day_key not in peaks_cache:
            peaks_cache[day_key] = _peak_for_date(pos_day)
        peak_temp = peaks_cache[day_key]
        if peak_temp is None:
            continue
        if state.clob.positions.resolve_paper_position(pos, peak_temp):
            settled_pnl += float(getattr(pos, "pnl_usd", 0.0) or 0.0)
            if pos_id:
                state._settled_position_ids.add(pos_id)
                state._settled_ids_timestamps[pos_id] = time.time()

    return settled_pnl
def _get_tg(trading_mode: str = None):
    """Singleton lazy de tg.TG() — None se Telegram não configurado.

    Args:
        trading_mode: "paper" ou "real". Se None, usa _TG_TRADING_MODE.
    """
    mode = (trading_mode or _TG_TRADING_MODE).lower()
    cache_key = f"_instance_{mode}"
    if not hasattr(_get_tg, cache_key):
        try:
            import os
            from tg import TG
            # Selecionar token baseado no modo de trading
            if mode == "real":
                token = os.environ.get("TELEGRAM_TOKEN_REAL", os.environ.get("TELEGRAM_TOKEN", ""))
            else:
                token = os.environ.get("TELEGRAM_TOKEN_PAPER", os.environ.get("TELEGRAM_TOKEN", ""))
            if token:
                os.environ["TELEGRAM_TOKEN"] = token
            setattr(_get_tg, cache_key, TG())
        except Exception:
            setattr(_get_tg, cache_key, None)
    return getattr(_get_tg, cache_key)


def _safe_tg_call(fn, *args, **kwargs):
    """Wrapper defensivo para chamadas TG que ignora argumentos inesperados.

    Prevencao de crashes quando o modulo tg.py nao aceita certos kwargs.
    Loga o erro em vez de crashar o bot inteiro.
    """
    try:
        return fn(*args, **kwargs)
    except TypeError as e:
        if "unexpected keyword argument" in str(e) or "got an unexpected keyword argument" in str(e):
            err_msg = str(e)
            arg_name = err_msg.split("'")[1] if "'" in err_msg else "unknown"
            fn_name = getattr(fn, '__name__', str(fn))
            print(f"  [TG] ⚠️  Chamada ignorada: {fn_name} — "
                  f"argumento inesperado '{arg_name}'. "
                  f"Atualize o tg.py ou remova este argumento do live_bot.py")
            return None
        # Outros TypeErrors (assinatura errada, etc.) — propagar
        raise

def _tg_thread(fn, *args, **kwargs) -> None:
    """Thread daemon para chamadas TG com protecao contra argumentos inesperados."""
    import threading
    threading.Thread(target=_safe_tg_call, args=(fn,) + args, kwargs=kwargs, daemon=True).start()


def _tg_alert(msg: str) -> None:
    """Alerta genérico (texto livre) — fallback quando não há método dedicado."""
    print(f"[TG] {msg}")
    tg = _get_tg()
    if tg:
        try:
            _tg_thread(tg.send, msg)
        except Exception:
            pass


# FIX TG-SPAM (27/09): o bloqueio de banda repete a cada tick (~120x/hora
# com sinal persistente — 179 sends no log do A). Alerta de bloqueio 1x
# por cidade/dia; o log continua a ter todas as ocorrências.
_blocked_tg_sent: dict = {}


def _tg_alert_blocked_once(city: str, msg: str) -> None:
    key = (city, str(date.today()))
    if _blocked_tg_sent.get(key):
        print("[TG] bloqueado (dedup diário — ver log)")
        return
    _blocked_tg_sent[key] = True
    _tg_alert(msg)


def _tg_alert_order_placed(bet_record: dict, trading_mode_str: str) -> None:
    """Alerta de ordem colocada com identificação de cidade e estratégia."""
    city_name = bet_record.get("city", "?")
    print(f"[TG] {city_name}: Bought {bet_record.get('bracket')} @ "
          f"{bet_record.get('ask', 0)*100:.1f}¢")
    tg = _get_tg()
    if tg:
        try:
            # Adicionar tag de cidade ao bracket label se não estiver presente
            label = bet_record.get("bracket_label", "")
            if city_name and not label.startswith(f"[{city_name}]"):
                bet_with_city = dict(bet_record)
                bet_with_city["bracket_label"] = f"[{city_name}] {label}"
                _tg_thread(tg.alert_order_placed, bet_with_city, trading_mode_str)
            else:
                _tg_thread(tg.alert_order_placed, bet_record, trading_mode_str)
        except Exception as e:
            print(f"[TG] alert failed: {e}")


def _tg_alert_stop_loss_triggered(city_name: str, position: dict, current_temp: float,
                                   bid_price: float, realized_pnl: float) -> None:
    """Alerta de stop-loss disparado com identificação de cidade."""
    tg = _get_tg()
    if tg:
        try:
            pos_with_city = dict(position)
            pos_with_city["bracket_label"] = f"[{city_name}] " + str(
                position.get("bracket_label", position.get("bracket", "?"))
            )
            _tg_thread(
                tg.alert_stop_loss_triggered,
                position=pos_with_city, current_temp=current_temp,
                bid_price=bid_price, realized_pnl=realized_pnl,
            )
        except Exception as e:
            print(f"[TG] stop_loss_triggered failed: {e}")


def _tg_alert_stop_loss_blocked(city_name: str, position: dict, current_temp: float,
                                 reason: str) -> None:
    """Alerta de stop-loss bloqueado com identificação de cidade."""
    tg = _get_tg()
    if tg:
        try:
            pos_with_city = dict(position)
            pos_with_city["bracket_label"] = f"[{city_name}] " + str(
                position.get("bracket_label", position.get("bracket", "?"))
            )
            _tg_thread(
                tg.alert_stop_loss_blocked,
                position=pos_with_city, current_temp=current_temp, reason=reason,
            )
        except Exception as e:
            print(f"[TG] stop_loss_blocked failed: {e}")


# ════════════════════════════════════════════════════
#  HELPERS PARA DASHBOARD TELEGRAM PERIÓDICO (single-city)
# ════════════════════════════════════════════════════

def _build_ascii_chart(slots: list, width: int = 28, height: int = 6) -> list:
    """
    Constrói um chart ASCII multi-linha de temperatura ao longo do dia.
    Adequado para Telegram (monospace, ~28 chars de largura).

    Retorna uma lista de strings (uma por linha), prontas para enviar.
    """
    if not slots:
        return ["  sem dados suficientes"]

    temps = []
    for s in slots:
        try:
            t = float(s.get("temp_c")) if s.get("temp_c") is not None else None
            if t is not None:
                temps.append((int(s["hour"]), int(s.get("slot30", 0)), t))
        except (TypeError, ValueError):
            continue

    if not temps:
        return ["  sem dados válidos"]

    # Ordenar por tempo
    temps.sort(key=lambda x: x[0] * 60 + x[1])

    t_min = min(t[2] for t in temps)
    t_max = max(t[2] for t in temps)
    t_rng = max(t_max - t_min, 1.0)

    # Amostrar para a largura desejada
    n = len(temps)
    if n > width:
        sampled = [temps[int(i * n / width)] for i in range(width)]
    else:
        sampled = temps

    lines = []
    for row in range(height, 0, -1):
        # Threshold do meio desta linha
        threshold = t_min + (t_rng * (row - 0.5) / height)
        line_chars = []
        for h, m, t in sampled:
            if t >= threshold + (t_rng / height / 2):
                line_chars.append("█")
            elif t >= threshold:
                line_chars.append("▄")
            elif t >= threshold - (t_rng / height / 2):
                line_chars.append("▁")
            else:
                line_chars.append(" ")
        label = f"{threshold:>4.0f}°C"
        lines.append(f"  {label} │{''.join(line_chars)}")

    # Eixo X
    lines.append(f"       └{'─' * width}")

    # Labels de hora nas extremidades
    if len(sampled) >= 2:
        first_h = sampled[0][0]
        last_h = sampled[-1][0]
        first_label = f"{first_h:02d}h"
        last_label = f"{last_h:02d}h"
        gap = max(1, width - len(first_label) - len(last_label))
        lines.append(f"        {first_label}{' ' * gap}{last_label}")

    # Anotação do pico
    peak_t = t_max
    peak_idx = max(range(len(sampled)), key=lambda i: sampled[i][2])
    peak_h = sampled[peak_idx][0]
    lines.append(f"  Pico: {peak_t:.1f}°C @ {peak_h:02d}h  |  Min: {t_min:.1f}°C  Range: {t_rng:.1f}°C")

    return lines


def _send_single_city_dashboard(tg_inst, states, city_name, daily_stats,
                                 run_mode, bankroll, session_stats=None) -> None:
    """
    Constrói e envia um dashboard completo para uma única cidade via Telegram.
    Inclui: curva de temperatura ASCII, P(pico), tabela de brackets, forecast,
    posição, P&L acumulado.

    Chamado a cada args.tg_interval segundos pelo main loop quando is_multi=False.
    """
    if city_name not in states:
        return
    state = states[city_name]
    city = state.city

    # FIX CRÍTICO-1: snapshot de slots e latest_obs sob lock
    # (corrigido: variáveis não estavam definidas — eram state.slots_so_far e state.latest_obs)
    with state._lock:
        slots_snapshot = list(state.slots_so_far)
        latest_obs_snapshot = dict(state.latest_obs) if state.latest_obs else None

    # rmax e rmax_time
    if slots_snapshot:
        valid_slots = [s for s in slots_snapshot if s.get("temp_c") is not None]
        if valid_slots:
            rmax_slot = max(valid_slots, key=lambda s: float(s["temp_c"]))
            rmax = float(rmax_slot["temp_c"])
            rmax_time = f"{int(rmax_slot['hour']):02d}:{int(rmax_slot.get('slot30', 0)):02d}"
        else:
            rmax = 0.0
            rmax_time = "—"
    else:
        rmax = 0.0
        rmax_time = "—"

    # temp_now
    temp_now = None
    if latest_obs_snapshot:
        temp_now = latest_obs_snapshot.get("temp_c")

    # forecasts
    forecast_max = None
    if state.last_wu_forecast_max is not None:
        forecast_max = {"temp_max": int(state.last_wu_forecast_max)}

    # ── REMOVIDO: om_forecast (Open-Meteo removido)
    # ── REMOVIDO: om_forecast block (Open-Meteo removido)


    # forecast agreement (no formato esperado por tg.dashboard)
    wu = state.last_wu_forecast_max
    om = None  # ── REMOVIDO: Open-Meteo removido
    forecast_agreement = None
    if wu is not None and om is not None:
        forecast_agreement = {
            "valid": abs(wu - om) <= 1,
            "diff": abs(wu - om),
            "consensus_max": (wu + om) // 2,
            "reason": "" if abs(wu - om) <= 1 else f"WU={wu}°C vs OM={om}°C",
        }

    # peak detected?
    thr = city.threshold if city.threshold is not None else 0.65
    peak_detected = state.last_p_ensemble >= thr

    # Bet (posição actual)
    bet = None
    if state.entry and getattr(state.entry, "bought", False):
        rec = getattr(state.entry, "record", None) or {}
        bet = dict(rec)
        bet.setdefault("city", city.name)
        try:
            bet.setdefault("market_slug", state.fetcher.date_to_slug(city_date(city)))
        except Exception:
            bet.setdefault("market_slug", "")

    # positions_summary — lê do CLOB se disponível
    positions_summary = None
    if state.clob and hasattr(state.clob, "positions"):
        try:
            all_pos = state.clob.positions.all_positions()
            n_won = sum(1 for p in all_pos if getattr(p, 'status', None) and p.status.value == "won")
            n_lost = sum(1 for p in all_pos if getattr(p, 'status', None) and p.status.value == "lost")
            n_open = sum(1 for p in all_pos if getattr(p, 'status', None) and p.status.value == "open")
            total_pnl = sum(float(getattr(p, 'pnl_usd', 0) or 0) for p in all_pos)
            total_invested = sum(float(getattr(p, 'size_usdc', 0) or 0) for p in all_pos)
            nc = n_won + n_lost
            total_pnl_pct = (total_pnl / total_invested * 100) if total_invested > 0 else 0.0
            positions_summary = {
                "n_won": n_won,
                "n_lost": n_lost,
                "n_open": n_open,
                "total_pnl_usd": total_pnl,
                "total_invested": total_invested,
                "total_pnl_pct": total_pnl_pct,
            }
        except Exception as e:
            print(f"  {C['yellow']}positions_summary build error: {e}{R}")

    # Chart ASCII
    chart_lines = _build_ascii_chart(slots_snapshot)

    # ensemble_result
    ensemble_result = None
    if state.last_p_ensemble > 0:
        ensemble_result = {
            "p_ensemble": state.last_p_ensemble,
            "p_lgbm": state.last_p_lgbm,
        }

    # City today
    city_today = city_date(city)

    # Saldo USDC (apenas REAL mode)
    usdc_balance = None
    if str(run_mode).upper() == "REAL" and state.clob and hasattr(state.clob, "get_usdc_balance"):
        try:
            usdc_balance = state.clob.get_usdc_balance()
        except Exception:
            pass

    # Enviar
    try:
        _safe_tg_call(tg_inst.dashboard, 
            today=city_today.isoformat(),
            p=state.last_p_ensemble,
            rmax=rmax,
            rmax_time=rmax_time,
            temp_now=temp_now,
            forecast_max=forecast_max,
    # ── REMOVIDO: om_forecast param (Open-Meteo removido)
            forecast_agreement=forecast_agreement,
            market=state.market,
            bracket=state.last_target_bracket,
            ensemble_result=ensemble_result,
            peak_detected=peak_detected,
            bet=bet,
            trading_mode=run_mode,
            chart=chart_lines,
            reason="periodic",
            positions_summary=positions_summary,
            usdc_balance=usdc_balance,
            city_name=city.name,
        )
    except Exception as e:
        print(f"  {C['yellow']}TG dashboard send failed: {e}{R}")


# ════════════════════════════════════════════════════
#  TICK por cidade
# ════════════════════════════════════════════════════



def _check_paper_auto_close(state: CityState, stats: DailyStats, trading_mode_str: str) -> None:
    """FIX P1-3 (Opção A): Auto-close PAPER removido.

    No Polymarket as bets resolvem a 100¢ (1.0) se ganham ou 0¢ se perdem.
    O modo PAPER deve comportar-se como o REAL: deixar a posição aberta
    até ao settlement do fim do dia. O PnL só é calculado com a temp
    máxima real no _settle_paper_positions_for_day.
    """
    pass


def _handle_day_rollover(state: "CityState", city: "CityConfig",
                         city_today: "date", trading_mode_str: str,
                         _settle_paper_positions_for_day,
                         _save_daily_stats, create_strategy,
                         DailyStats, PARCEL_SIZE: float, C: dict, R: str) -> None:
    """FASE 1 do tick: mudança de dia — settlement do anterior + reset completo.

    Ordem (crítica, não reordenar):
      1. Settlement PAPER das posições do dia anterior (antes de perder daily_pnl)
      2. Persistir daily_stats do dia que fecha
      3. Limpar settled IDs > 7 dias (TTL)
      4. Recriar a estratégia (novo threshold do config se houver override)
      5. Breaker EOD (D1: record_result + record_global_city_total)
      6. Reset daily_stats / _last_applied_pnl
      7. Persistir estado resetado
    """
    # 1. Settlement PAPER do dia anterior:
    if trading_mode_str == "paper" and state.clob:
        try:
            prev_day = state._last_date
            settled_pnl = _settle_paper_positions_for_day(state, prev_day)
            if settled_pnl and hasattr(state, 'daily_stats') and state.daily_stats:
                state.daily_stats.daily_pnl += settled_pnl
                _save_daily_stats(state.daily_stats, city.name)
        except Exception as e:
            print(f"  {C['yellow']}{city.name}: PAPER settlement no reset falhou: {e}{R}")

    # 1b. §97 (9/11): reconciliar bets de dias passados que ficaram por
    # resolver. As posições paper evaporam num restart (paper_positions.json
    # volátil); sem este passo as bets ficam "SIMULATED" para sempre e os
    # resumos escondem perdas — caso real: crash de 8/11 12:44 deixou 10
    # bets por resolver (3 eram LOSS) e o resumo mostrava "11W/0L".
    # O PnL retornado não entra nos daily_stats de hoje (pertence a dias
    # passados; os resumos leem os ficheiros de bets diretamente).
    if trading_mode_str == "paper":
        try:
            _rec = _reconcile_bets_from_csv(state)
            if _rec:
                print(f"  {C['green']}{city.name}: reconcile no rollover "
                      f"recuperou {_rec:+.2f}$ de bets antigos{R}")
        except Exception as _e:
            print(f"  {C['yellow']}{city.name}: reconcile no rollover falhou: {_e}{R}")

    # 2. Persistir stats do dia anterior:
    if hasattr(state, 'daily_stats') and state.daily_stats:
        _save_daily_stats(state.daily_stats, city.name)

    # 3. Limpar settled IDs antigos (TTL 7 dias):
    now_ts = time.time()
    expired = [sid for sid, ts in getattr(state, '_settled_ids_timestamps', {}).items()
               if now_ts - ts > 604800]
    for sid in expired:
        state._settled_position_ids.discard(sid)
        state._settled_ids_timestamps.pop(sid, None)

    # 4. Recriar a estratégia:
    state.slots_so_far = []
    state.series_today = {}
    state.cloud_by_hour = {}
    state.entry = create_strategy(city, mode=state.strategy_mode, parcel_size=PARCEL_SIZE,
                                  min_buy_ask=_MIN_BUY_ASK_OVERRIDE)
    if state.threshold_override is not None and hasattr(state.entry, 'threshold'):
        state.entry.threshold = float(state.threshold_override)
    if hasattr(state.entry, '_stop_loss_blocked_alerted'):
        state.entry._stop_loss_blocked_alerted = False

    # 5. Breaker EOD (D1) — ANTES do reset de daily_stats:
    try:
        from v6_breaker import record_result, record_global_city_total
        record_result(city.name, float(state.daily_stats.daily_pnl or 0))
        record_global_city_total(city.name, float(state.daily_stats.daily_pnl or 0))
    except Exception as _e:
        print(f"  [breaker] registo EOD falhou (inofensivo): {_e}")

    # 6. Reset:
    state._last_date = city_today
    state.daily_stats = DailyStats(date=city_today)
    state._last_applied_pnl = 0.0
    state._last_saved_trades = 0
    state._last_saved_stops = 0

    # 7. Persistir estado resetado:
    _save_paper_state(state.city.name, {
        "_last_applied_pnl": 0.0,
        "_settled_ids": list(state._settled_position_ids),
    }, city_today)



def _sync_entry_with_clob(state: "CityState", C: dict, R: str) -> None:
    """FASE 2: se o entry está bought mas o CLOB já reporta resolvido
    (won/lost/expired), limpar o entry — permite novo ciclo no dia seguinte."""
    if not (state.entry and getattr(state.entry, 'bought', False) and state.clob):
        return
    try:
        rec = getattr(state.entry, 'record', None) or {}
        pos_token = rec.get('token_id')
        pos_label = rec.get('bracket_label') or rec.get('bracket')
        for pos in state.clob.positions.all_positions():
            status = getattr(getattr(pos, 'status', None), 'value',
                             getattr(pos, 'status', None))
            if str(status).lower() not in ('won', 'lost', 'expired'):
                continue
            pos_token_c = getattr(pos, 'token_id', None)
            pos_label_c = getattr(pos, 'bracket_label', None)
            if (pos_token and pos_token == pos_token_c) or \
               (pos_label and pos_label == pos_label_c):
                print(f"  {C['yellow']}{_city_name_helper(state)}: Entry sincronizado — "
                      f"CLOB reporta {status}, limpar entry{R}")
                state.entry.bought = False
                state.entry.record = None
                if hasattr(state.entry, 'sold_by_stop'):
                    state.entry.sold_by_stop = False
                break
    except Exception:
        pass


def _city_name_helper(state) -> str:
    return getattr(getattr(state, 'city', None), 'name', '?')



def _ensure_bootstrap(state: "CityState", C: dict, R: str,
                      _bootstrap_state_today) -> None:
    """FASE 3: bootstrap recovery com backoff 60s + health alerts (5x/10x)."""
    if not (getattr(state, "_bootstrap_pending", False)
            and len(state.slots_so_far) < 4):
        return
    now_ts_boot = time.time()
    if now_ts_boot - state._last_bootstrap_attempt < 60:
        return
    state._last_bootstrap_attempt = now_ts_boot
    try:
        _bootstrap_state_today(state)
        if len(state.slots_so_far) >= 4:
            state._bootstrap_pending = False
    except Exception:
        pass  # mantém pending, tenta de novo em 60s



def _fetch_current_obs(state: "CityState", C: dict, R: str) -> Optional[dict]:
    """FASE 4: observação atual — METAR (fonte oficial de resolução, §98) →
    V3 ICAO → V2 ICAO → validação de plausibilidade. None se tudo falhar."""
    city = state.city

    # §98: METAR primeiro — é a fonte em que o mercado resolve
    new_obs = None
    if city.icao:
        try:
            from metar import fetch_metar_current
            new_obs = fetch_metar_current(city.icao)
            if new_obs:
                # contrato do tick: hour/minute locais (o dict METAR traz só
                # obs_time UTC-aware — derivar aqui na tz da cidade)
                if "hour" not in new_obs and new_obs.get("obs_time") is not None:
                    from zoneinfo import ZoneInfo
                    loc = new_obs["obs_time"].astimezone(ZoneInfo(city.timezone))
                    new_obs["hour"], new_obs["minute"] = loc.hour, loc.minute
                print(f"  {C['green']}{city.name}: METAR current OK "
                      f"({new_obs['temp_c']}°C){R}")
        except Exception as e:
            print(f"  {C['yellow']}{city.name}: METAR current falhou: {e}{R}")
            new_obs = None

    if new_obs is None and not (city.icao and state.wu_key):
        print(f"  {C['red']}{city.name}: SEM ICAO — current obs impossível{R}")
        return None

    # V3 ICAO fallback:
    if new_obs is None:
        try:
            new_obs = v3_fetch_current(city.icao, state.wu_key)
            if new_obs:
                print(f"  {C['green']}{city.name}: V3 ICAO current OK "
                      f"({new_obs['temp_c']}°C){R}")
            else:
                print(f"  {C['yellow']}{city.name}: V3 ICAO current retornou None "
                      f"(ICAO={city.icao}){R}")
        except Exception as e:
            print(f"  {C['yellow']}{city.name}: V3 ICAO current falhou: {e} "
                  f"(ICAO={city.icao}){R}")

    # Fallback V2 ICAO:
    if new_obs is None:
        try:
            new_obs = fetch_wu_latest(city, state.wu_key, state.wu_sess)
            if new_obs:
                print(f"  {C['green']}{city.name}: V2 ICAO current OK "
                      f"({new_obs['temp_c']}°C){R}")
        except Exception as e2:
            print(f"  {C['red']}{city.name}: V2 ICAO current também falhou: {e2}{R}")

    if new_obs is None:
        print(f"  {C['red']}{city.name}: SEM DADOS ATUAIS — ICAO falhou{R}")
        return None

    # Validação de plausibilidade:
    if not is_plausible_temp(new_obs.get("temp_c"), city):
        print(f"  {C['red']}{city.name}: rejected implausible temp "
              f"{new_obs.get('temp_c')}°C{R}")
        return None

    return new_obs



def _tick_city(state: CityState, trading_mode_str: str, bankroll: float, is_race: bool = False) -> DailyStats:
    city = state.city
    set_city(city.name)
    now = bot_now()
    city_today = city_date(city)
    # FIX Bug 4.11: calcular current_market_slug UMA VEZ no início do tick
    # e reutilizar durante todo o processamento. Isto evita inconsistências
    # se a meia-noite passar durante o processamento do tick.
    current_market_slug = state.fetcher.date_to_slug(city_today)

    # ── Variáveis para tick_logger (inicializadas c/ defaults) ──
    _actions_logged: list = []

    # Reset diário (Fix 11) + FIX 2: guardar stats anterior antes de resetar
    if state._last_date is None:
        state._last_date = city_today
    # FIX CRITICAL: settlement of previous day positions on startup
    # The old code set _last_date = city_today BEFORE this check, making it always false
    # Now we check FIRST, then update _last_date after settlement
    if city_today != state._last_date:
        # ── FASE 1: rollover completo (delegado a _handle_day_rollover) ──
        _handle_day_rollover(state, city, city_today, trading_mode_str,
                             _settle_paper_positions_for_day,
                             _save_daily_stats, create_strategy,
                             DailyStats, PARCEL_SIZE, C, R)
        _bootstrap_state_today(state)

    # Em vez de: stats = DailyStats(date=city_today)
    stats = state.daily_stats  # ← Usar o objecto persistente

    # ── FASE 2: sincronização entry↔CLOB (delegada) ──
    _sync_entry_with_clob(state, C, R)

    # ── FASE 3: bootstrap recovery (delegada — backoff 60s) ──
    _ensure_bootstrap(state, C, R, _bootstrap_state_today)

    # ── FASE 4: observação atual (delegada — V3→V2→plausibilidade) ──
    new_obs = _fetch_current_obs(state, C, R)
    state.latest_obs = new_obs

    # Forecasts apenas informativos para dashboard/alertas; não entram na decisão.
    h_forecast = city_now(city).hour
    if state.last_forecast_hour != h_forecast:
        try:
            wu_forecast = None
            if city.icao and state.wu_key:
                # Tentar V3 ICAO primeiro
                wu_forecast = v3_fetch_forecast_daily(city.icao, state.wu_key)
                if wu_forecast:
                    print(f"  {C['green']}{city.name}: V3 ICAO forecast OK (max={wu_forecast.get('temp_max')}°C){R}")
                else:
                    print(f"  {C['yellow']}{city.name}: V3 ICAO forecast retornou None{R}")

                # Fallback V2 ICAO se V3 falhou
                if wu_forecast is None:
                    try:
                        wu_forecast = fetch_wu_forecast_max(city, state.wu_key, state.wu_sess)
                        if wu_forecast:
                            print(f"  {C['green']}{city.name}: V2 ICAO forecast OK (max={wu_forecast.get('temp_max')}°C){R}")
                    except Exception as e2:
                        print(f"  {C['red']}{city.name}: V2 ICAO forecast também falhou: {e2}{R}")
            else:
                print(f"  {C['yellow']}{city.name}: SEM ICAO — forecast impossível{R}")

            state.last_wu_forecast_max = (
                wu_forecast.get("temp_max") if isinstance(wu_forecast, dict) else None
            )
            state.last_forecast_hour = h_forecast
        except Exception as e:
            print(f"  {C['red']}{city.name}: V3 ICAO forecast falhou: {e}{R}")

    # Atualizar slots (zona crítica — protegida contra a thread do Telegram)
    if new_obs:
        h_obs, m_obs = new_obs["hour"], new_obs["minute"]
        h_slot, s30 = ceil_slot(h_obs, m_obs)

        if city.day_start <= h_slot <= city.day_end:
            with state._lock:
                same_slot_count = sum(
                    1 for s in state.slots_so_far
                    if s["hour"] == h_slot and s["slot30"] == s30
                )
                state.series_today[(h_slot, s30, same_slot_count)] = new_obs["temp_c"]
                if "cloud_cover" in new_obs and new_obs["cloud_cover"] is not None:
                    state.cloud_by_hour[h_slot] = new_obs["cloud_cover"]

                slot_entry = {
                    "date": city_today,
                    "hour": h_slot,
                    "slot30": s30,
                    "temp_c": new_obs["temp_c"],
                    "cloud_cover": new_obs.get("cloud_cover", 50),
                    "humidity": new_obs.get("humidity", 70),
                    "dewpoint_c": new_obs.get("dewpoint_c", new_obs["temp_c"] - 10),
                    "pressure_hpa": new_obs.get("pressure_hpa", 1013),
                    "wind_dir_deg": new_obs.get("wind_dir_deg", 0),
                    "wind_speed_kmh": new_obs.get("wind_speed_kmh", 5),
                    "wind_gust_kmh": new_obs.get("wind_gust_kmh", 8),
                    "uv_index": new_obs.get("uv_index", 3),
                }

                exists = any(s["hour"] == h_slot and s["slot30"] == s30 for s in state.slots_so_far)
                if exists:
                    current_rmax = max(s["temp_c"] for s in state.slots_so_far) if state.slots_so_far else None
                    latest_slot_key = max(
                        (int(s["hour"]) * 60 + int(s.get("slot30", 0)) for s in state.slots_so_far),
                        default=None,
                    )
                    new_slot_key = h_slot * 60 + s30
                    for s in state.slots_so_far:
                        if s["hour"] == h_slot and s["slot30"] == s30:
                            if (
                                state.entry and state.entry.bought
                                and latest_slot_key is not None
                                and new_slot_key < latest_slot_key
                                and current_rmax is not None
                                and slot_entry["temp_c"] > current_rmax
                            ):
                                print(
                                    f"  {C['yellow']}{city.name}: clamped late high temp "
                                    f"at {h_slot:02d}:{s30:02d}{R}"
                                )
                                # Guardar temp real para o modelo usar
                                s["temp_c_real"] = slot_entry["temp_c"]
                                slot_entry["temp_c"] = s["temp_c"]
                            else:
                                # Sincronizar temp real quando não há clamp
                                s["temp_c_real"] = slot_entry["temp_c"]
                            s["date"] = city_today
                            s["temp_c"] = slot_entry["temp_c"]
                            if "hour" in slot_entry:
                                s["hour"] = slot_entry["hour"]
                            if "slot30" in slot_entry:
                                s["slot30"] = slot_entry["slot30"]
                            for key in (
                                "cloud_cover", "humidity", "dewpoint_c", "pressure_hpa",
                                "wind_dir_deg", "wind_speed_kmh", "wind_gust_kmh", "uv_index",
                            ):
                                if key in new_obs and new_obs[key] is not None:
                                    s[key] = slot_entry[key]
                            break
                else:
                    state.slots_so_far.append(slot_entry)
                    state.slots_so_far.sort(key=lambda x: x["hour"] * 60 + x["slot30"])

    # FIX P2-3: limitar janela a 96 entradas (~48h)
    MAX_SLOTS = 96
    if len(state.slots_so_far) > MAX_SLOTS:
        removed = state.slots_so_far[:-MAX_SLOTS]
        state.slots_so_far = state.slots_so_far[-MAX_SLOTS:]
        # FIX MÉDIO-10: remover entradas antigas de series_today em vez de reconstruir tudo
        for old_s in removed:
            key = (int(old_s["hour"]), int(old_s.get("slot30", 0)), 0)
            # Remover todas as chaves que correspondem a este slot
            keys_to_remove = [k for k in state.series_today.keys()
                              if k[0] == key[0] and k[1] == key[1]]
            for k in keys_to_remove:
                state.series_today.pop(k, None)
    # FIX MÉDIO-10: NÃO reconstruir series_today inteiro.
    # As entradas são adicionadas individualmente quando há nova obs (acima).
    # Isso evita O(n) desnecessário a cada tick.

    from predictor import update_history_max
    history_max_for_features = dict(state.history_max)
    update_history_max(state.history_max, state.slots_so_far, city.name)
    # FIX 7: persistir history_max a cada hora (evita perda de dados em restart)
    now_ts_hist = time.time()
    if now_ts_hist - state._last_history_save >= 3600:  # 1 hora
        try:
            from predictor import save_history_max
            save_history_max(state.history_max, city.name)
            state._last_history_save = now_ts_hist
        except Exception:
            pass

    # Fetch market (a cada 10 minutos ou se não existe)
    now_city = city_now(city)
    market_key = (now_city.hour, now_city.minute // 10)
    if state.last_market_min != market_key or state.market is None:
        try:
            _market = state.fetcher.fetch_market(city_today)
            if _market:
                print(f"  {C['green']}{city.name}: Mercado OK "
                      f"({len(_market.get('brackets', []))} brackets, "
                      f"vol=${_market.get('volume', 0):,.0f}){R}")
                if state.clob:
                    running_max_ref = (
                        max((s["temp_c"] for s in state.slots_so_far), default=15.0)
                        if state.slots_so_far
                        else (state.latest_obs.get("temp_c", 15.0) if state.latest_obs else 15.0)
                    )
                    rmax_center = round_half_up(running_max_ref)
                    enriched_brackets = []
                    for b in _market["brackets"]:
                        mid_temp = (float(b.get("temp_lo", 0.0)) + float(b.get("temp_hi", 0.0))) / 2.0
                        if (
                            abs(mid_temp - rmax_center) <= 3.0
                            or float(b.get("temp_lo", 0.0)) <= -99.0
                            or float(b.get("temp_hi", 0.0)) >= 99.0
                        ):
                            enriched_brackets.append(state.clob.enrich_bracket(b))
                        else:
                            enriched_brackets.append(b)
                    _market["brackets"] = enriched_brackets
                # Escrita protegida contra a thread do Telegram
                with state._lock:
                    state.market = _market
                    state.last_market_min = market_key
            else:
                print(f"  {C['yellow']}{city.name}: Mercado NÃO ENCONTRADO "
                      f"para {city_today} (slug={state.fetcher.date_to_slug(city_today)}){R}")
                # Se _market é None, mantém o market anterior (não sobrescreve)
        except Exception as e:
            print(f"  {C['red']}{city.name}: Fetch market failed: {e}{R}")

    # ── Anti-duplicado: verificar DUAS fontes ──
    # FIX Bug 4.1: todo o bloco anti-duplicado dentro do lock para
    # evitar race condition com a thread do Telegram.
    with state._lock:
        if state.entry and state.clob:
            _skip = False
            _rec = None

            # Fonte 1: arquivo bets_{date}.json
            bets_path = LOG_DIR / f"bets_{city.name}_{city_today}.json"
            if bets_path.exists():
                try:
                    existing_bets = json.loads(bets_path.read_text())
                    existing_bets = [
                        b for b in existing_bets
                        if b.get("market_slug") is not None
                        and b.get("market_slug") == current_market_slug
                    ]
                    if existing_bets:
                        _skip = True
                        first = existing_bets[-1]
                        _rec = {
                            "ask": first.get("ask"),
                            "temp_hi": first.get("temp_hi"),
                            "temp_lo": first.get("temp_lo"),
                            "token_id": first.get("token_id"),
                            "size_usdc": first.get("bet_size"),
                            "market_slug": first.get("market_slug", current_market_slug),
                            "strategy": first.get("strategy"),
                            "bracket": first.get("bracket") or first.get("bracket_label"),
                            "bracket_label": first.get("bracket_label") or first.get("bracket"),
                            "order_id": first.get("order_id"),
                            "shares": first.get("shares"),
                            "p_ensemble": first.get("p_ensemble"),
                        }
                except Exception:
                    pass

            # Fonte 2: CLOB positions
            if not _skip:
                try:
                    _existing = [p for p in state.clob.positions.open_positions()
                                 if str(p.date_opened) == str(city_today)
                                 and getattr(p, "market_slug", "") == current_market_slug]
                    if _existing:
                        _skip = True
                        _pos = _existing[-1]
                        _rec = {
                            "ask": getattr(_pos, 'entry_ask', None),
                            "temp_hi": getattr(_pos, 'temp_hi', None),
                            "temp_lo": getattr(_pos, 'temp_lo', None),
                            "token_id": getattr(_pos, 'token_id', None),
                            "size_usdc": getattr(_pos, 'size_usdc', None),
                            "order_id": getattr(_pos, 'order_id', None),
                            "market_slug": getattr(_pos, 'market_slug', current_market_slug),
                            "strategy": "single",
                            "bracket": getattr(_pos, 'bracket_label', None),
                            "bracket_label": getattr(_pos, 'bracket_label', None),
                            "shares": getattr(_pos, 'shares', None),
                        }
                except Exception:
                    pass

            if _skip and _rec and state.entry:
                if hasattr(state.entry, "restore"):
                    state.entry.restore(_rec, state.strategy_mode)
                    print(f"  {C['green']}{city.name}: Posição restaurada via restore() "
                          f"— bracket={_rec.get('bracket','?')} @ {_rec.get('ask',0)*100:.1f}¢{R}")
                else:
                    state.entry.bought = True
                    state.entry.record = _rec
                    if hasattr(state.entry, 'strategy_used'):
                        state.entry.strategy_used = _rec.get("strategy") or state.strategy_mode
                    print(f"  {C['yellow']}{city.name}: Posição restaurada (fallback) "
                          f"— bracket={_rec.get('bracket','?')} @ {_rec.get('ask',0)*100:.1f}¢{R}")

                # Verificar se stop-loss já foi disparado antes do restart
                if state.slots_so_far and state.entry.record:
                    current_temp = max(s["temp_c"] for s in state.slots_so_far)
                    sl_check = state.entry.check_stop_loss(current_temp)
                    if sl_check:
                        # Marcar como vendida sem enviar alerta duplicado
                        state.entry.sold_by_stop = True
                        state.entry.record["sold_by_stop"] = True
                        if hasattr(state.entry, '_stop_loss_blocked_alerted'):
                            state.entry._stop_loss_blocked_alerted = True
                        print(f"  {C['yellow']}{city.name}: stop-loss já disparado antes do restart — marcando como vendida{R}")
                    else:
                        # Só resetar o flag se NÃO foi triggerado antes do restart
                        if hasattr(state.entry, '_stop_loss_blocked_alerted'):
                            state.entry._stop_loss_blocked_alerted = False

    # Predição e entrada
    h_now = city_now(city).hour
    m_now = city_now(city).minute
    h_cur, s30_cur = ceil_slot(h_now, m_now)

    p_ensemble = 0.0
    ensemble_result = None

    if len(state.slots_so_far) >= 4:
        # ─── FIX 17 & 18: Fallback para dados meteorológicos ───
        # Se a API falhar (latest_obs é None), usamos o último slot válido
        # que já está no state.slots_so_far, em vez de meter 0°C ou genéricos.
        obs = state.latest_obs if state.latest_obs else {}
        last_slot = state.slots_so_far[-1] if state.slots_so_far else {}

        # Extrair valor: 1º tenta a obs live, 2º tenta o último slot, 3º default seguro
        # Fallback: climatologia do mês em vez de 0 (mais realista quando dados falham)
        clim_fallback = city.climatology.get(city_today.month, 15.0) if city.climatology else 15.0
        _temp       = obs.get("temp_c") if obs.get("temp_c") is not None else last_slot.get("temp_c", clim_fallback)
        _humidity   = obs.get("humidity") if obs.get("humidity") is not None else last_slot.get("humidity", 70)
        _dewpoint   = obs.get("dewpoint_c") if obs.get("dewpoint_c") is not None else last_slot.get("dewpoint_c", _temp - 10)
        _pressure   = obs.get("pressure_hpa") if obs.get("pressure_hpa") is not None else last_slot.get("pressure_hpa", 1013)
        _wind_dir   = obs.get("wind_dir_deg") if obs.get("wind_dir_deg") is not None else last_slot.get("wind_dir_deg", 0)
        _wind_speed = obs.get("wind_speed_kmh") if obs.get("wind_speed_kmh") is not None else last_slot.get("wind_speed_kmh", 5)
        _wind_gust  = obs.get("wind_gust_kmh") if obs.get("wind_gust_kmh") is not None else last_slot.get("wind_gust_kmh", 8)
        _uv_index   = obs.get("uv_index") if obs.get("uv_index") is not None else last_slot.get("uv_index", 3)

        prev7_value = compute_prev7(history_max_for_features, city_today, city.name)
        # FIX MÉDIO-9: NÃO sobrescrever com rmax. O compute_prev7 já retorna
        # climatologia como fallback quando não há histórico. Usar rmax enviesa
        # o modelo no início do dia (temp_vs_climatology fica artificialmente
        # positivo quando ainda não aqueceu).

        current_extra = {
            "hour": h_cur,
            "slot30": s30_cur,
            "temp_c": _temp,
            "cloud_cover": state.cloud_by_hour.get(h_cur, 50),
            "humidity": _humidity,
            "dewpoint_c": _dewpoint,
            "pressure_hpa": _pressure,
            "wind_dir_deg": _wind_dir,
            "wind_speed_kmh": _wind_speed,
            "wind_gust_kmh": _wind_gust,
            "uv_index": _uv_index,
            "prev_7d_avg_max": prev7_value,
        }

        ensemble_result = predict_ensemble(
            state.models, state.slots_so_far, current_extra,
            city_today.month, city_today.timetuple().tm_yday
        )
        p_ensemble = ensemble_result["p_ensemble"]
    
    # ← INSERIR AQUI (fora do if, cobre também o caso slots < 4)
    state.last_p_ensemble = p_ensemble
    state.last_p_lgbm     = ensemble_result.get("p_lgbm") if ensemble_result else None


    # Trade decision
    if state.entry and state.market and state.clob:
        # S1-15: slots _spike_suspect NAO contam para o rmax efetivo
        # (so entram quando o slot seguinte os confirma)
        _valid_temps = [s["temp_c"] for s in state.slots_so_far
                        if not s.get("_spike_suspect")]
        running_max = max(_valid_temps) if _valid_temps else 0.0

         # ← INSERIR AQUI
        state.last_target_bracket = PolymarketFetcher.find_bracket(
            state.market, running_max
        )

        # ── D4 MAKER REAL: poll de fills/cancelamentos ──
        # (independente do entry.bought — a bid descansa mesmo sem posição)
        if not TAKER_ONLY and trading_mode_str == "real" and os.environ.get("D4_MAKER") \
                and getattr(state, "clob", None):
            try:
                import d4_maker as _d4
                _r4 = _d4.poll_city(state, city,
                                    end_hour=getattr(state.entry, "end_hour", None))
                if _r4 == "FILLED":
                    _safe_tg_call(_get_tg(trading_mode_str).send,
                                  f"🎯 <b>{city.name.title()}</b> D4 MAKER FILL "
                                  f"@ 0.75¢ (fee 0) — posição aberta")
                elif _r4 == "CANCELLED":
                    _safe_tg_call(_get_tg(trading_mode_str).send,
                                  f"⏳ <b>{city.name.title()}</b> D4 bid maker "
                                  f"cancelada (TTL/fim de janela)")
            except Exception as _e:
                print(f"  {C['red']}[d4] {city.name} poll: {_e}{R}")

        # FIX MÉDIO-14: forecast_agreement simplificado (Open-Meteo removido).
        # Apenas verifica se o forecast WU é plausível vs running_max.
        wu = state.last_wu_forecast_max
        fc_agreement = {
            "valid": True,
            "diff": None,
            "consensus_max": wu,
            "reason": "",
        }
        if wu is not None and running_max is not None:
            diff = abs(wu - int(running_max))
            if diff > 5:
                fc_agreement = {
                    "valid": False,
                    "diff": diff,
                    "consensus_max": wu,
                    "reason": f"WU={wu}°C vs RMax={int(running_max)}°C (diff={diff})",
                }

        # FIX P1-1: proteger evaluate() e execução de compra com lock
        with state._lock:
            # Double-check: outra thread pode já ter comprado
            if state.entry.bought:
                _actions_logged = []
            else:
                # ── V6 MAKER: fills pendentes desta cidade (market fresco) ──
                if not TAKER_ONLY and os.environ.get("V6_MAKER") and state.market:
                    try:
                        from v6_maker import check_fills as _vm_cf
                        _asks = {b.get("token_id"): float(b.get("ask") or 1)
                                 for b in state.market.get("brackets", [])
                                 if b.get("token_id")}
                        _fills, _expired = _vm_cf(_asks, city.name)
                        for _fo in _fills:
                            br = _fo.get("bet_record") or {}
                            # §92: completar o br ANTES do alerta — sem isto o
                            # alerta do fill maker saía "Ordem colocada $0.00 →
                            # 0.00 shares ID ?" com o ask de quando a bid foi
                            # posta (ex.: busan 8/11, ask 93¢ no alerta vs fill
                            # real a 75¢).
                            br["size_usdc"] = float(_fo["size_usdc"])
                            br["shares"] = round(float(_fo["size_usdc"]) /
                                                 max(float(_fo["price"]), 1e-9), 4)
                            br["order_id"] = f"MAKER-{float(_fo['price'])*100:.0f}c"
                            br["ask"] = float(_fo["price"])  # fill ao NOSSO limite
                            result = state.clob.buy_yes(
                                token_id=_fo["token_id"], price=_fo["price"],
                                size_usdc=float(_fo["size_usdc"]),
                                bracket_label=br.get("bracket_label") or br.get("bracket", "?"),
                                market_slug=br.get("market_slug", ""),
                                order_type="GTC",
                                temp_lo=br.get("temp_lo"), temp_hi=br.get("temp_hi"))
                            if result.success:
                                state.entry.mark_bought(0, br)
                                stats.trades.append(br)
                                stats.total_invested += float(_fo["size_usdc"])
                                _append_bet_record(br, city.name, city_today)
                                _tg_alert_order_placed(br, trading_mode_str)
                                print(f"  {C['green']}{city.name.upper()} ⚡ MAKER FILL: "
                                      f"fee 0 poupada{R}")
                        if _expired:
                            state._v6_pending = False   # dia pode continuar
                    except Exception as _e:
                        print(f"  [v6-maker] check erro: {_e}")

                actions = state.entry.evaluate(
                    p_ensemble=p_ensemble,
                    hour=h_cur,
                    market=state.market,
                    running_max=running_max,
                    forecast_agreement=fc_agreement,
                    slots_so_far=state.slots_so_far,
                )
                _actions_logged = actions  # capturar para tick_logger

                # Processar ações (primeira que tenha size > 0)
                for action in actions:
                    if action.get("size_usdc", 0) > 0:
                        bracket = action.get("bracket") or state.last_target_bracket
                        if not bracket:
                            continue

                        # Double-check dentro do loop de ações
                        if state.entry.bought:
                            break

                        ask = bracket.get("ask") or bracket.get("price", 1.0)
                        size_usdc = action["size_usdc"]
                        token_id = bracket.get("token_id")
                        # §93 / Fase 3: sizing centralizado em clob_sizing.
                        # Garante shares inteiras + notional >= $1.00 (regras CLOB).
                        # Substitui o cálculo inline (P0.6).
                        from clob_sizing import enforce_min_size as _enforce_min_size
                        _effective_size, _effective_shares = _enforce_min_size(size_usdc, ask)
                        if _effective_size > size_usdc:
                            print(f"  {C['cyan']}{city.name}: size $1.00 → "
                                  f"${_effective_size:.2f} (mín. $1: {_effective_shares} shares "
                                  f"a {float(ask)*100:.0f}¢){R}")
                            size_usdc = _effective_size
                        raw_best_ask = None

                        if token_id and state.clob:
                            try:
                                fresh_book = state.clob.get_orderbook(token_id)
                                if fresh_book and getattr(fresh_book, "best_ask", None) is not None:
                                    raw_best_ask = float(fresh_book.best_ask)
                                    ask = round_to_tick(raw_best_ask, direction="up")
                                    # FIX P1-4: validar ask > 0 após round_to_tick
                                    if ask <= 0:
                                        print(f"  {city.name}: ask={ask} after round_to_tick, skipping buy")
                                        break
                                    bracket = dict(bracket)
                                    bracket["ask"] = ask
                                    bracket["raw_ask"] = raw_best_ask
                                    if getattr(fresh_book, "best_bid", None) is not None:
                                        bracket["bid"] = round_to_tick(float(fresh_book.best_bid), direction="down")
                            except Exception:
                                pass

                        # FIX Bug 4.10: usar min_buy_ask do SingleEntry (default 0.15),
                        # não 0.20 hardcoded. Alinha backtest com live.
                        min_buy_ask = getattr(state.entry, "min_buy_ask", 0.15)
                        effective_ask = raw_best_ask if raw_best_ask is not None else float(ask)
                        # D6-fix: re-verificar MAX buy ask contra o preco FRESCO
                        # (o entry viu o ask do market dict; o livro pode ter subido
                        #  entretanto — caso Munich dia 1: entry viu <=0.85, comprou a 0.94)
                        max_buy_ask_fresco = getattr(state.entry, "max_buy_ask", 0.85)
                        if effective_ask > max_buy_ask_fresco:
                            print(f"  {C['yellow']}{city.name.upper()} BUY BLOQUEADO: "
                                  f"ask fresco {effective_ask*100:.0f}¢ > "
                                  f"máx {max_buy_ask_fresco*100:.0f}¢{R}")
                            # ── D4 MAKER quando o MÁXIMO bloqueou ──
                            # (desenho queimado 03/10: maker = volume ADICIONAL
                            # onde o taker não chega; maybe_place/place têm o
                            # guarda nunca-cruzar e o dedup de slot partilhado)
                            if not TAKER_ONLY and trading_mode_str == "real" and os.environ.get("D4_MAKER"):
                                try:
                                    import d4_maker as _d4
                                    _r4 = _d4.maybe_place(state, city, bracket,
                                                          effective_ask)
                                    if _r4 == "PLACED":
                                        print(f"  {C['cyan']}{city.name} ⏳ D4-MAKER: "
                                              f"bid GTC 0.75¢ colocada (ask "
                                              f"{effective_ask*100:.0f}¢) — à espera{R}")
                                        _safe_tg_call(
                                            _get_tg(trading_mode_str).send,
                                            f"⏳ <b>{city.name.title()}</b> D4 bid GTC "
                                            f"0.75¢ colocada (ask {effective_ask*100:.0f}¢)")
                                    elif not _r4.startswith(("LIVE_EXISTS",
                                                             "HAS_POSITION")):
                                        print(f"  {C['yellow']}{city.name} D4-MAKER: "
                                              f"{_r4}{R}")
                                except Exception as _e:
                                    print(f"  {C['red']}{city.name} D4-MAKER erro: "
                                          f"{_e}{R}")
                            elif not TAKER_ONLY and os.environ.get("V6_MAKER"):
                                # SHADOW paper (bot B): mesma lógica, fill por
                                # touch no hook de ticks (check_fills)
                                try:
                                    from v6_maker import place as _vm_place
                                    _vm_place(city.name, bracket.get("token_id"),
                                              float(effective_ask), 1.0, {
                                                  "city": city.name,
                                                  "bracket": bracket.get("label"),
                                                  "bracket_label": bracket.get("label"),
                                                  "token_id": bracket.get("token_id"),
                                                  "market_slug": current_market_slug,
                                                  "ask": effective_ask,
                                                  "temp_lo": bracket.get("temp_lo"),
                                                  "temp_hi": bracket.get("temp_hi"),
                                              })
                                except Exception as _e:
                                    print(f"  {C['red']}{city.name} V6-MAKER erro: "
                                          f"{_e}{R}")
                            break
                        if effective_ask < min_buy_ask:
                            print(
                                f"  {C['yellow']}{city.name.upper()} BUY BLOQUEADO: "
                                f"ask {effective_ask*100:.1f}¢ < mínimo {min_buy_ask*100:.0f}¢{R}"
                            )
                            _tg_alert_blocked_once(
                                city.name,
                                f"🚫 <b>{city.name.title()}</b> buy bloqueado: "
                                f"ask {effective_ask*100:.1f}¢ < mínimo {min_buy_ask*100:.0f}¢"
                            )
                            # §92: near-miss (sinal disparou, preço abaixo do piso)
                            # -> log p/ análise posterior do piso 0.60 (§86/§90)
                            try:
                                _nm = {"ts": datetime.now().isoformat(timespec="seconds"),
                                       "city": city.name,
                                       "ask": round(float(effective_ask), 4),
                                       "min_buy_ask": round(float(min_buy_ask), 4),
                                       "p_ensemble": round(float(p_ensemble), 4)}
                                _le_nm = getattr(state.entry, "last_eval", None) or {}
                                if _le_nm.get("p_rebound") is not None:
                                    _nm["p_rebound"] = round(float(_le_nm["p_rebound"]), 4)
                                    _nm["threshold"] = _le_nm.get("threshold")
                                with open(LOG_DIR / "near_misses.jsonl", "a") as _f_nm:
                                    _f_nm.write(json.dumps(_nm) + "\n")
                            except Exception:
                                pass
                            break

                        # FIX Bug 4.9: REMOVER filtro max_buy_ask duplicado aqui.
                        # O SingleEntry.evaluate() já faz esta verificação com o ask
                        # do bracket. Refazê-la aqui com raw_best_ask (que pode diferir)
                        # cria inconsistências entre backtest e live.

                        # bet_record completo (campos necessários para stop-loss + tracking)
                        bet_record = {
                            "city":          city.name,
                            "hour":          h_cur,        # ← NOVO
                            "slot30":        s30_cur,      # ← NOVO
                            "bracket":       bracket["label"],
                            "bracket_label": bracket["label"],
                            "ask":           ask,
                            "size_usdc":     size_usdc,
                            "bet_size":      size_usdc,         # alias para compat
                            "shares":        math.floor(size_usdc / ask) if ask > 0 else 0,
                            "temp_lo":       bracket.get("temp_lo"),
                            "temp_hi":       bracket.get("temp_hi"),
                            "token_id":      token_id,
                            "raw_ask":       raw_best_ask,
                            "time":          city_now(city).isoformat(),
                            "timestamp":     city_now(city).isoformat(),
                            "strategy":      action.get("strategy") or state.strategy_mode,
                            "p_rebound":     action.get("p_rebound"),
                            "p_ensemble":    p_ensemble,
                            "p_lgbm":        ensemble_result.get("p_lgbm") if ensemble_result else None,
                            "running_max":   running_max,
                            "is_race":       is_race,
                            "trigger":       "race" if is_race else "normal",
                        }
                        bet_record["market_slug"] = current_market_slug

                        # ── V6 FILTER (só ativo com V6_FILTER=1) ──
                        # D-v5 (§87): segmentação em braços por faixa de ask —
                        # v5 (sem F1) / dead (nunca compra) / f1 (gate normal).
                        # Sem V6_V5_MAX_ASK/V6_F1_MIN_ASK → comportamento
                        # anterior inalterado (arm_decision devolve 'f1').
                        if os.environ.get("V6_FILTER"):
                            try:
                                from v6_filter import arm_decision as _v6_arm
                                _v5_max = float(os.environ.get("V6_V5_MAX_ASK") or 0)
                                _f1_min = float(os.environ.get("V6_F1_MIN_ASK") or 0)
                                _arm = _v6_arm(effective_ask, _v5_max, _f1_min)
                            except Exception as _e:
                                _arm = "f1"  # fail-open p/ segmentação; o gate abaixo é fail-closed
                            if _arm == "dead":
                                print(f"  {C['yellow']}{city.name} ⛔ ZONA MORTA "
                                      f"{_v5_max*100:.0f}–{_f1_min*100:.0f}¢ "
                                      f"(ask {effective_ask*100:.1f}¢) — sem compra{R}")
                                stats.v6_blocked = getattr(stats, "v6_blocked", 0) + 1
                                break
                            if _arm == "v5":
                                print(f"  {C['green']}{city.name} 🟢 BRAÇO V5 "
                                      f"(ask {effective_ask*100:.1f}¢ ≤ "
                                      f"{_v5_max*100:.0f}¢) — sem F1, regra v5 pura{R}")
                            else:
                              try:
                                  from v6_filter import gate as _v6_gate
                                  _slots = getattr(state, "slots_so_far", None)
                                  _hm = getattr(state, "history_max", None) or {}
                                  _tdy = city_now(city).date()
                                  _hv = [float(v) for k, v in _hm.items() if hasattr(k, "year") and k < _tdy][-7:]
                                  _p7 = (sum(_hv) / len(_hv)) if len(_hv) >= 4 else None
                                  _hr = int(city_now(city).hour)
                                  _doy = city_now(city).timetuple().tm_yday
                                  _hi = float(bracket.get("temp_hi") or
                                              (float(bracket.get("temp_lo") or 0) + 1.0))
                                  _rmax = float(getattr(state.entry, "running_max", 0) or
                                                0) or float(bracket.get("temp_lo") or 0) + 0.8
                                  _ok = _v6_gate(city.name, _hr, city_now(city).month,
                                                 _doy, _rmax, _hi, _slots, _p7)
                                  if not _ok:
                                      print(f"  {C['yellow']}{city.name} ⛔ V6: p_win "
                                            f"abaixo do limiar — entrada cortada{R}")
                                      stats.v6_blocked = getattr(stats, "v6_blocked", 0) + 1
                                      break
                              except Exception as _e:
                                  print(f"  {C['red']}{city.name} V6 filter ERRO: {_e} "
                                        f"→ fail-closed (sem compra){R}")
                                  break

                        # ── D2: Gamma check (mercado aberto?) ──
                        if trading_mode_str == "real":
                            try:
                                from v6_gamma_check import market_open
                                _open, _why = market_open(current_market_slug)
                                if not _open:
                                    print(f"  {C['red']}{city.name} D2: mercado "
                                          f"fechado ({_why}) — sem compra{R}")
                                    break
                            except Exception as _e:
                                print(f"  [D2] erro gamma: {_e} (fail-open)")

                        # ── D2: Gamma check (mercado aberto? — só REAL) ──
                        if trading_mode_str == "real":
                            try:
                                from v6_gamma_check import market_open as _mk_open
                                _open, _why = _mk_open(current_market_slug)
                                if not _open:
                                    print(f"  {C['red']}{city.name} D2: mercado "
                                          f"fechado ({_why}) — sem compra{R}")
                                    break
                            except Exception as _e:
                                print(f"  [D2] gamma erro (fail-open): {_e}")

                        # ── D1: circuit breaker por cidade ──
                        try:
                            from v6_breaker import can_trade
                            _ok, _why = can_trade(city.name)
                            if not _ok:
                                print(f"  {C['yellow']}{city.name} ⛔ breaker: "
                                      f"{_why}{R}")
                                break
                        except Exception:
                            pass

                        # ── V6 MAKER (D4): hook ANTIGO removido em 03/10 (v2) ──
                        # O place() estava aqui — ANTES do filtro da banda — e
                        # transformava TODAS as compras do B em pendentes maker,
                        # matando o torneio e medindo a coisa errada (maker
                        # in-band em vez do pool bloqueado-pelo-máximo). O shadow
                        # paper passou a registar-se no ramo do bloqueio máximo
                        # (mesmo gatilho que o maker real D4).

                        # D4 MAKER: slot partilhado — com bid maker live, o
                        # taker da cidade fica em espera (1 posição total/dia)
                        if not TAKER_ONLY and trading_mode_str == "real" and os.environ.get("D4_MAKER"):
                            try:
                                import d4_maker as _d4
                                if _d4.has_live_bid(city.name):
                                    print(f"  {C['cyan']}{city.name}: D4 bid maker "
                                          f"live — taker em espera (slot partilhado){R}")
                                    break
                            except Exception:
                                pass

                        if trading_mode_str == "real":
                            if not token_id:
                                print(f"  {C['red']}{city.name} BUY FALHOU: token_id em falta no bracket{R}")
                                break

                            # FIX P2-6: usar current_market_slug calculado no início do tick
                            market_slug = current_market_slug
                            bracket_lbl_full = (
                                f"{action['strategy'].upper()}: {bracket['label']}"
                                if action.get("strategy")
                                else bracket["label"]
                            )

                            result = state.clob.buy_yes(
                                token_id=token_id,
                                price=ask,
                                size_usdc=size_usdc,
                                bracket_label=bracket_lbl_full,
                                market_slug=market_slug,
                                order_type="FOK",
                                temp_lo=bracket.get("temp_lo"),
                                temp_hi=bracket.get("temp_hi"),
                                is_race=is_race,
                            )

                            if result.success:
                                bet_record["order_id"] = result.order_id
                                bet_record["status"] = result.status
                                bet_record["simulated"] = result.simulated
                                state.entry.mark_bought(0, bet_record)
                                stats.trades.append(bet_record)
                                stats.total_invested += size_usdc
                                _append_bet_record(bet_record, city.name, city_today)
                                buy_color = C['magenta'] if is_race else C['green']
                                buy_tag = "BUY [RACE]" if is_race else "BUY"
                                print(f"  {buy_color}{city.name.upper()} {buy_tag}: {bracket['label']} "
                                      f"@ {ask*100:.1f}¢  ${size_usdc:.2f}  ({action['reason']}){R}")
                                _tg_alert_order_placed(bet_record, trading_mode_str)
                                # ── NOVO: registar bet no tick_logger ──
                                if _TICK_LOGGER is not None:
                                    try:
                                        _TICK_LOGGER.log_bet(
                                            bet_record=bet_record,
                                            city_name=city.name,
                                            date_str=city_today.isoformat(),
                                            trigger="race" if is_race else "normal",
                                            p_ensemble=p_ensemble,
                                            market_volume=float(state.market.get("volume", 0) or 0) if state.market else None,
                                        )
                                    except Exception as e:
                                        print(f"  [tick_logger] log_bet failed: {e}")
                            else:
                                err = result.error or result.status
                                print(f"  {C['red']}{city.name.upper()} BUY REJEITADO: {err}{R}")
                        else:
                            # PAPER mode
                            # FIX P2-6: usar current_market_slug calculado no início do tick
                            market_slug = current_market_slug
                            result = state.clob.buy_yes(
                                token_id=token_id,
                                price=ask,
                                size_usdc=size_usdc,
                                bracket_label=bracket["label"],
                                market_slug=market_slug,
                                order_type="FOK",
                                temp_lo=bracket.get("temp_lo"),
                                temp_hi=bracket.get("temp_hi"),
                                is_race=is_race,
                            )

                            if result.success:
                                bet_record["order_id"] = result.order_id
                                bet_record["status"] = result.status
                                bet_record["simulated"] = result.simulated
                                state.entry.mark_bought(0, bet_record)
                                stats.trades.append(bet_record)
                                stats.total_invested += size_usdc
                                _append_bet_record(bet_record, city.name, city_today)
                                buy_color = C['magenta'] if is_race else C['yellow']
                                buy_tag = "BUY [PAPER-RACE]" if is_race else "BUY [PAPER]"
                                print(f"  {buy_color}{city.name.upper()} {buy_tag}: {bracket['label']} "
                                      f"@ {ask*100:.1f}¢  ${size_usdc:.2f}  ({action['reason']}){R}")
                                _tg_alert_order_placed(bet_record, trading_mode_str)
                                # ── NOVO: registar bet no tick_logger ──
                                if _TICK_LOGGER is not None:
                                    try:
                                        _TICK_LOGGER.log_bet(
                                            bet_record=bet_record,
                                            city_name=city.name,
                                            date_str=city_today.isoformat(),
                                            trigger="race" if is_race else "normal",
                                            p_ensemble=p_ensemble,
                                            market_volume=float(state.market.get("volume", 0) or 0) if state.market else None,
                                        )
                                    except Exception as e:
                                        print(f"  [tick_logger] log_bet failed: {e}")
                            else:
                                err = result.error or result.status
                                print(f"  {C['red']}{city.name.upper()} BUY [PAPER] REJEITADO: {err}{R}")

                        break  # Apenas uma ação por tick

        # ─── STOP-LOSS CHECK ────────────────────────────
    # FIX Bugs 4.3 + 4.4 + 4.5: bloco atómico completo sob lock;
    # resetar _stop_loss_blocked_alerted quando condições mudam;
    # usar get_orderbook fresh para obter bid actual.
    with state._lock:
        if state.entry and state.clob and state.latest_obs and state.market:
            current_temp = state.latest_obs["temp_c"]
            if hasattr(state.entry, 'check_stop_loss'):
                stop_signal = state.entry.check_stop_loss(current_temp)
                if stop_signal:
                    pos = stop_signal["position"]
                    # Throttle: só alertar 1× por trigger (evita spam)
                    _already_alerted = getattr(state.entry, '_stop_loss_blocked_alerted', False)

                    matching = []
                    pos_token = pos.get("token_id")
                    if pos_token:
                        matching = [
                            b for b in state.market.get("brackets", [])
                            if b.get("token_id") == pos_token
                        ]
                    if not matching:
                        pos_lo = float(pos.get("temp_lo") or 0)
                        pos_hi = float(pos.get("temp_hi") or 0)
                        matching = [
                            b for b in state.market.get("brackets", [])
                            if abs(float(b.get("temp_lo", 0)) - pos_lo) < 0.1
                            and abs(float(b.get("temp_hi", 0)) - pos_hi) < 0.1
                        ]

                    # ── Caso 1: bracket desapareceu do mercado ──
                    if not matching:
                        if not _already_alerted:
                            print(f"\n  {C['red']}⚠  [{city.name}] {stop_signal['reason']}{R}")
                            print(f"  {C['red']}   BLOQUEADO: bracket {pos.get('label','?')} "
                                  f"sem match no mercado actual{R}")
                            _tg_alert_stop_loss_blocked(
                                city.name, pos, current_temp,
                                reason="bracket sem match no mercado",
                            )
                            state.entry._stop_loss_blocked_alerted = True
                        # FIX 4.4: NÃO manter bloqueado para sempre. Se o bracket
                        # reaparecer no próximo tick, matching será True e o
                        # flag é resetado no else abaixo.
                    else:
                        bracket = matching[0]
                        bid_price = bracket.get("bid")

                        # FIX 4.4: resetar flag quando bracket existe
                        # (condições melhoraram desde o último bloqueio)
                        if hasattr(state.entry, '_stop_loss_blocked_alerted'):
                            state.entry._stop_loss_blocked_alerted = False

                        # ── Caso 2: bid muito baixo ou ausente ──
                        if not bid_price or bid_price < 0.02:
                            if not _already_alerted:
                                bid_str = f"{bid_price*100:.2f}¢" if bid_price else "—"
                                print(f"\n  {C['yellow']}⚠  [{city.name}] {stop_signal['reason']}{R}")
                                print(f"  {C['yellow']}   BLOQUEADO: bid={bid_str} "
                                      f"(< 2¢, não vale vender) — deixar expirar{R}")
                                _tg_alert_stop_loss_blocked(
                                    city.name, pos, current_temp,
                                    reason=f"bid muito baixo ({bid_str})",
                                )
                                state.entry._stop_loss_blocked_alerted = True
                        else:
                            # ── Caso 3: bid OK, tentar vender ──
                            # FIX 4.5: obter bid fresh do orderbook antes de vender
                            fresh_bid = bid_price
                            pos_token_id = pos.get("token_id")
                            if pos_token_id and state.clob:
                                try:
                                    fresh_book = state.clob.get_orderbook(pos_token_id)
                                    if fresh_book and getattr(fresh_book, "best_bid", None) is not None:
                                        fresh_bid = round_to_tick(float(fresh_book.best_bid), direction="down")
                                except Exception:
                                    pass  # usa o bid do snapshot

                            # FIX Bug ALTO-7: não filtrar por current_market_slug
                            # porque posições de dias anteriores têm slug diferente.
                            # O token_id é suficiente para identificar a posição.
                            poll = [p for p in state.clob.positions.open_positions()
                                    if getattr(p, "token_id", None) == pos_token_id]

                            # ── Caso 3a: posição não encontrada no CLOB ──
                            if not poll:
                                if not _already_alerted:
                                    tid = pos.get("token_id") or ""
                                    tid_short = tid[:16] + "..." if tid else "?"
                                    print(f"\n  {C['red']}⚠  [{city.name}] {stop_signal['reason']}{R}")
                                    print(f"  {C['red']}   BLOQUEADO: posição "
                                          f"token_id={tid_short} "
                                          f"não encontrada no CLOB{R}")
                                    _tg_alert_stop_loss_blocked(
                                        city.name, pos, current_temp,
                                        reason="posição não encontrada no CLOB",
                                    )
                                    state.entry._stop_loss_blocked_alerted = True
                            else:
                                # ── Caso 3b: tentar vender ──
                                sell_result = state.clob.sell_yes(poll[0], fresh_bid)
                                if sell_result.success:
                                    # Use the reported fill (REAL FOK may execute
                                    # below the observed bid within its price cap).
                                    _exit_fill_price = float(
                                        getattr(sell_result, "price", None) or fresh_bid
                                    )
                                    # Usar função partilhada para consistência com backtester
                                    # FIX F821 (03/10): TAKER_FEE_RATE não existia
                                    # (NameError adormecido); o wrapper já aplica
                                    # weather fee internamente — 4º arg suprimido.
                                    pnl_result = _compute_realized_pnl(
                                        pos.get("ask", 0), _exit_fill_price,
                                        pos.get("size_usdc", 0)
                                    )
                                    realized_pnl = pnl_result["realized_pnl"]

                                    state.entry.mark_sold_by_stop(_exit_fill_price, realized_pnl)
                                    settled_id = str(pos.get("order_id") or pos.get("timestamp") or pos.get("bracket_label") or "")
                                    if settled_id:
                                        state._settled_position_ids.add(settled_id)
                                        # FIX CRÍTICO-2: registar timestamp para TTL
                                        state._settled_ids_timestamps[settled_id] = time.time()
                                    stats.stop_losses_triggered += 1

                                    stats.daily_pnl += realized_pnl

                                    print(f"\n  {C['yellow']}⚠  [{city.name}] {stop_signal['reason']}{R}")
                                    print(f"  {C['yellow']}   Vendido @ {fresh_bid:.4f}, "
                                          f"PnL={realized_pnl:+.2f} "
                                          f"(shares={pnl_result['shares']}, "
                                          f"fee=${pnl_result['fee']:.2f}){R}")

                                    _tg_alert_stop_loss_triggered(
                                        city.name, pos, current_temp,
                                        bid_price=fresh_bid, realized_pnl=realized_pnl,
                                    )
                                else:
                                    # ── Caso 3c: ordem de venda falhou ──
                                    if not _already_alerted:
                                        err = getattr(sell_result, 'error', None) or 'erro desconhecido'
                                        print(f"\n  {C['red']}⚠  [{city.name}] {stop_signal['reason']}{R}")
                                        print(f"  {C['red']}   FALHA na venda @ {fresh_bid:.4f}: {err}{R}")
                                        _tg_alert_stop_loss_blocked(
                                            city.name, pos, current_temp,
                                            reason=f"sell_yes falhou: {err}",
                                        )
                                        state.entry._stop_loss_blocked_alerted = True
    # ───────────────────────────────────────────────────────

    # FIX P1-3: auto-close PAPER removido — posição fica aberta até ao settlement
    # do fim do dia (comportamento idêntico ao REAL)

    # Display simples (apenas quando dashboard multi-cidade não está ativa)
    if state.latest_obs and not state.dashboard_enabled:
        rmax = max(s["temp_c"] for s in state.slots_so_far) if state.slots_so_far else state.latest_obs["temp_c"]

        print(f"{C['cyan']}{city.name.upper():<8}{R} "
              f"{h_cur:02d}:{s30_cur:02d} | "
              f"Temp: {state.latest_obs['temp_c']:>5.1f}°C | "
              f"RMax: {rmax:>5.1f}°C | "
              f"P: {p_ensemble:>4.2f} | "
              f"Mode: SINGLE | "
              f"Bought: {state.entry.bought if state.entry else 'No'}")

    # ── NOVO: registar tick no logger de telemetria ──
    # Para análise offline: distribuição de p_ensemble, quase-sinais, evolução do mercado, etc.
    if _TICK_LOGGER is not None:
        try:
            _TICK_LOGGER.log_tick(
                state=state,
                city_today=city_today,
                race_active=False,  # race é controlado no main loop, não no _tick_city
                race_threshold=None,
                eod_active=False,
                actions=_actions_logged,
                errors=[],
            )
        except Exception as e:
            print(f"  [tick_logger] log_tick failed: {e}")

    # FIX 4: throttle _save_daily_stats (I/O excessivo — 30s * 2880 ticks/dia)
    # Basear em MUDANÇA (trades/stops novos desde último save), não no
    # estado total — senão após o 1º trade grava em todos os ticks.
    now_ts_save = time.time()
    n_trades = len(stats.trades)
    n_stops = stats.stop_losses_triggered
    _has_new = (n_trades != state._last_saved_trades
                or n_stops != state._last_saved_stops)
    if (now_ts_save - state._last_stats_save >= 300  # 5 min
            or _has_new):
        _save_daily_stats(stats, city.name)
        state._last_stats_save = now_ts_save
        state._last_saved_trades = n_trades
        state._last_saved_stops = n_stops
    return stats


# ════════════════════════════════════════════════════
#  MAIN
# ════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Live Bot Multi-Cidade")
    parser.add_argument("--cities", type=str, default="munich",
                        help="Cidades separadas por vírgula (ex: munich,dallas)")
    parser.add_argument("--mode", type=str, default="single", choices=["single", "cassiopeia", "calipso"],
                        help="Modo de estratégia: single, cassiopeia, calipso")
    parser.add_argument("--run", type=str, default="paper", choices=["paper", "real"],
                        help="Modo de execução: paper, real")
    parser.add_argument("--interval", type=int, default=30,
                        help="Intervalo em segundos entre ticks")
    parser.add_argument("--no-dashboard", action="store_true",
                        help="Desativa dashboard rich (útil para logs/daemon)")
    parser.add_argument("--force-dashboard", action="store_true",
                        help="Força dashboard rich mesmo se stdout não parecer TTY")
    # ── REMOVIDO: --wu-only (Open-Meteo removido)

    # ── NOVOS: controlo de trade frequency e dashboard periódico ──
    parser.add_argument("--tg-interval", type=int, default=1800,
                        help="Intervalo em segundos para dashboard Telegram periódico "
                             "(default 1800=30min). Aplica-se a single e multi-cidade.")
    parser.add_argument("--threshold-override", type=float, default=None,
                        help="Override do threshold para TODAS as cidades (ex: 0.55). "
                             "Útil para forçar mais trades quando os thresholds calibrados "
                             "estão altos demais.")
    parser.add_argument("--max-buy-ask", type=float, default=0.90,
                        help="Ask máximo para comprar em fracção 0..1 (default 0.90=90¢). "
                             "Blocks buys acima deste valor — brackets quase certos têm "
                             "payout mínimo.")
    parser.add_argument("--min-buy-ask", type=float, default=None,
                        help="Ask MÍNIMO para comprar (override explícito; default None "
                             "= a config ativa por cidade manda). Usado para pinar a "
                             "banda de instâncias reais (ex: micro fica 0.80 enquanto "
                             "o paper testa a perna 0.75-0.80).")
    # ── NOVOS: Top-K Race mode ──
    parser.add_argument("--race-top-k", type=int, default=0,
                        help="Top-K Race mode: a cada N minutos, ordena todas as cidades "
                             "não compradas por p_ensemble desc e baixa temporariamente o "
                             "threshold das top-K (com p >= --race-min-threshold). "
                             "Default 0 = desactivado. Recomendado: 2 (1-2 bets/dia).")
    parser.add_argument("--race-min-threshold", type=float, default=0.50,
                        help="Threshold mínimo absoluto para Race mode (default 0.50). "
                             "Race nunca compra abaixo deste valor — garante qualidade. "
                             "Ex: 0.55 = só dispara se P(pico) >= 55%%.")
    parser.add_argument("--race-eval-interval", type=int, default=300,
                        help="Segundos entre race evals (default 300=5min). Race não corre "
                             "em todos os ticks para evitar overhead de predict.")
    args = parser.parse_args()

    # --min-buy-ask: override global para as construções de entry (init + rollover)
    global _MIN_BUY_ASK_OVERRIDE
    _MIN_BUY_ASK_OVERRIDE = args.min_buy_ask
    if _MIN_BUY_ASK_OVERRIDE is not None:
        print(f"[args] min_buy_ask override ativo: {_MIN_BUY_ASK_OVERRIDE}")

    raw_city_names = [c.strip() for c in args.cities.split(",") if c.strip()]
    if "all" in [cn.lower() for cn in raw_city_names]:
        from cities.config import get_all_cities
        all_configs = get_all_cities()
        # Filtrar apenas as cidades em Celsius no Polymarket
        city_names = [cfg.name for cfg in all_configs if cfg.market_unit == "celsius"]
    else:
        # Evita cidades duplicadas (ex: "...,karachi,...,karachi") mantendo ordem.
        city_names = list(dict.fromkeys(raw_city_names))
    trading_mode = TradingMode.REAL if args.run == "real" else TradingMode.PAPER
    trading_mode_str = args.run.lower()
    is_multi     = len(city_names) > 1
    global _TG_TRADING_MODE
    _TG_TRADING_MODE = args.run.lower()
    has_tty = sys.stdout.isatty()
    dashboard_enabled = (is_multi or args.force_dashboard) and (not args.no_dashboard)

    # Import dashboard multi-cidade apenas se necessário
    if is_multi or args.force_dashboard:
        from display import extract_display_data, render_dashboard, write_live_snapshot

    print("=" * 60)
    print(f" {B}Live Bot — Multi-Cidade{R}")
    print("=" * 60)
    print(f"  Cidades:  {', '.join(city_names)}")
    print(f"  Modo:     {args.mode}")
    print(f"  Execução: {args.run.upper()}")
    print(f"  Intervalo:{args.interval}s")
    if dashboard_enabled:
        dash_label = "display.py (multi-cidade)" if is_multi else "display.py (mono-cidade forçado)"
    elif is_multi and not has_tty:
        dash_label = "desativada (stdout sem TTY)"
    elif is_multi and args.no_dashboard:
        dash_label = "desativada (--no-dashboard)"
    else:
        dash_label = "mono-cidade (legacy)"
    print(f"  Dashboard:{dash_label}")
    print()

    # Inicializar estados por cidade
    states = {}
    for city_name in city_names:
        city = get_city(city_name)
        set_city(city_name)
        models = load_models(city_name)

        entry = create_strategy(city, mode=args.mode, parcel_size=PARCEL_SIZE,
                                min_buy_ask=_MIN_BUY_ASK_OVERRIDE)
        # ── NOVO: aplicar threshold override se fornecido via CLI ──
        if args.threshold_override is not None:
            if hasattr(entry, 'threshold') and entry.threshold is not None:
                original_thr = float(entry.threshold)
                entry.threshold = float(args.threshold_override)
                print(f"  {C['yellow']}{city.name}: threshold override "
                      f"{original_thr:.3f} → {args.threshold_override}{R}")
            else:
                # Alguns strategies podem não ter threshold; tenta atribuir à mesma
                try:
                    entry.threshold = float(args.threshold_override)
                    print(f"  {C['yellow']}{city.name}: threshold set to {args.threshold_override}{R}")
                except Exception:
                    print(f"  {C['red']}{city.name}: não consegui aplicar threshold_override{R}")
        print(
            f"  {city.name}: estratégia carregada "
            f"(threshold={getattr(entry, 'threshold', 'n/a')}, "
            f"hour_min={getattr(entry, 'hour_min', 'n/a')})"
        )

        # ── FIX 5: restaurar daily_stats do disco ──
        stats_path = LOG_DIR / f"{city.name}_{city_date(city)}.json"
        restored_stats = DailyStats(date=city_date(city))
        if stats_path.exists():
            try:
                saved = json.loads(stats_path.read_text())
                restored_stats.daily_pnl = saved.get("daily_pnl", 0.0)
                restored_stats.total_invested = saved.get("total_invested", 0.0)
                restored_stats.stop_losses_triggered = saved.get("stop_losses_triggered", 0)
                # FIX MÉDIO-11: restaurar trades do bets_*.json para consistência
                bets_path = LOG_DIR / f"bets_{city.name}_{city_date(city)}.json"
                if bets_path.exists():
                    try:
                        bets = json.loads(bets_path.read_text())
                        restored_stats.trades = bets
                        print(f"  {C['cyan']}{city.name}: daily_stats restaurado "
                              f"(PnL={restored_stats.daily_pnl:+.2f}$, "
                              f"trades={len(restored_stats.trades)}, "
                              f"stops={restored_stats.stop_losses_triggered}){R}")
                    except Exception:
                        print(f"  {C['cyan']}{city.name}: daily_stats restaurado "
                              f"(PnL={restored_stats.daily_pnl:+.2f}$, "
                              f"stops={restored_stats.stop_losses_triggered}){R}")
                else:
                    print(f"  {C['cyan']}{city.name}: daily_stats restaurado "
                          f"(PnL={restored_stats.daily_pnl:+.2f}$, "
                          f"stops={restored_stats.stop_losses_triggered}){R}")
            except Exception:
                pass

        state = CityState(
            city=city,
            strategy_mode=args.mode,
            models=models,
            entry=entry,
            fetcher=PolymarketFetcher(city),
            history_max=init_history_max(city_name),  # ← carregar do disco
            daily_stats=restored_stats,  # ← Alterado para usar o restaurado
            dashboard_enabled=dashboard_enabled,
            threshold_override=args.threshold_override,  # ← FIX 1
        )

        # FIX S1-8: garantir city_bankrolls ANTES do restore (o bloco de
        # restauração escreve nele; sem init, UnboundLocalError no arranque)
        if 'city_bankrolls' not in dir():
            city_bankrolls = {}
        # Restaurar estado PAPER do disco (bankroll + settled IDs)
        paper_state = _load_paper_state(city.name)
        saved_last_date = paper_state.get("_last_date", "")
        city_today_iso = city_date(city).isoformat()
        # FIX P2-1b: se a data persistida for de outro dia, resetar o PnL aplicado
        if saved_last_date and saved_last_date != city_today_iso:
            print(f"  {C['yellow']}{city.name}: paper_state de {saved_last_date} (hoje: {city_today_iso}), "
                  f"resetando bankroll PAPER{R}")
            state._last_applied_pnl = 0.0
        else:
            state._last_applied_pnl = paper_state.get("_last_applied_pnl", 0.0)
        state._settled_position_ids = set(paper_state.get("_settled_ids", []))
        # FIX MÉDIO-12: restaurar bankroll PAPER do disco
        saved_bankroll = paper_state.get("_bankroll")
        if saved_bankroll is not None and saved_last_date == city_today_iso:
            city_bankrolls[city_name] = float(saved_bankroll)
            print(f"  {C['cyan']}{city.name}: Bankroll PAPER restaurado "
                  f"${city_bankrolls[city_name]:.2f}{R}")
        # FIX CRÍTICO-2: inicializar timestamps para IDs existentes (compatibilidade retroativa)
        if not hasattr(state, '_settled_ids_timestamps') or state._settled_ids_timestamps is None:
            state._settled_ids_timestamps = {}
        for sid in state._settled_position_ids:
            if sid not in state._settled_ids_timestamps:
                state._settled_ids_timestamps[sid] = time.time()
    # ── REMOVIDO: wu_only (Open-Meteo removido)

        # ── NOVO: restaurar posição existente antes do primeiro tick ──
        # FIX HOTFIX: prevenir restauração de posições já resolvidas ou com estado inconsistente
        bets_path = LOG_DIR / f"bets_{city.name}_{city_date(city)}.json"
        if bets_path.exists():
            try:
                existing_bets = json.loads(bets_path.read_text())
                current_slug = state.fetcher.date_to_slug(city_date(city))
                matching = [b for b in existing_bets if b.get("market_slug") == current_slug]
                if matching and state.entry:
                    first = matching[-1]
                    # FIX P2-5: não restaurar se já resolvida
                    if first.get("resolved") or first.get("status") in ("won", "lost", "expired"):
                        print(f"  {C['yellow']}{city.name}: Posição já resolvida ({first.get('status')}), "
                              f"não restaurando{R}")
                        # HOTFIX: garantir que entry está limpo
                        state.entry.bought = False
                        state.entry.record = None
                        if hasattr(state.entry, 'sold_by_stop'):
                            state.entry.sold_by_stop = False
                    else:
                        _rec = {
                            "ask": first.get("ask"),
                            "bracket": first.get("bracket") or first.get("bracket_label"),
                            "bracket_label": first.get("bracket_label") or first.get("bracket"),
                            "token_id": first.get("token_id"),
                            "size_usdc": first.get("bet_size") or first.get("size_usdc"),
                            "temp_hi": first.get("temp_hi"),
                            "temp_lo": first.get("temp_lo"),
                            "market_slug": first.get("market_slug", current_slug),
                            "strategy": first.get("strategy"),
                            "shares": first.get("shares"),
                            "p_ensemble": first.get("p_ensemble"),
                        }
                        if hasattr(state.entry, "restore"):
                            state.entry.restore(_rec, args.mode)
                        else:
                            state.entry.bought = True
                            state.entry.record = _rec
                        # FIX settlement-órfãos (03/10): restore() só reidrata o
                        # entry — se a posição não estiver em paper_positions.json
                        # (ex.: ficheiro limpo/rotacionado após reboot), o settle
                        # por dia nunca a vê. §106b: o re-persist em si corre
                        # DEPOIS do CLOB init (ver abaixo) — aqui o clob ainda
                        # não existe e o add() falhava sempre.
                        state._repersist_rec = _rec
                        print(f"  {C['green']}{city.name}: Posição restaurada na init "
                              f"— {_rec.get('bracket','?')} @ {_rec.get('ask',0)*100:.1f}¢{R}")
            except Exception as e:
                print(f"  {C['yellow']}{city.name}: Restore init falhou: {e}{R}")

        # ── NOVO: configurar filtros no state ──
        state.max_buy_ask = float(args.max_buy_ask)
        state._last_near_signal_ts = 0.0

        import os
        state.wu_key = os.environ.get("WU_API_KEY", "")

        if not state.wu_key:
            print(f"  {C['red']}{city.name}: WU_API_KEY não definida — V3 ICAO impossível{R}")

        state.wu_sess = make_wu_session()
        # ── REMOVIDO: state.om_sess = make_om_session() (Open-Meteo removido)
        _bootstrap_state_today(state)

        private_key = ""
        if args.run == "real":
            private_key = os.environ.get("POLY_PRIVATE_KEY", "")
        try:
            state.clob = ClobClient(
                private_key=private_key,
                mode=trading_mode,
                max_daily_loss=city.max_daily_loss,
                log_dir=LOG_DIR,
            )
            print(f"  {C['green']}{city.name}: CLOB inicializado ({trading_mode.name}){R}")
        except Exception as e:
            print(f"  {C['red']}{city.name}: CLOB init failed: {e}{R}")

        # §106b: re-persist da posição restaurada — agora COM clob.
        # (dedup-safe: ignora se já existe OPEN com mesma data+token+slug)
        _rec = getattr(state, "_repersist_rec", None)
        if _rec and state.clob:
            try:
                from datetime import datetime as _dt
                state.clob.positions.add(Position(
                    position_id=str(_rec.get("order_id")
                                    or f"RESTORE-{_rec.get('token_id') or city.name}"),
                    date_opened=city_date(city).isoformat(),
                    opened_at=_dt.now().isoformat(),
                    bracket_label=str(_rec.get("bracket_label")
                                      or _rec.get("bracket") or ""),
                    token_id=str(_rec.get("token_id") or ""),
                    entry_ask=float(_rec.get("ask") or 0),
                    shares=float(_rec.get("shares") or 0),
                    size_usdc=float(_rec.get("size_usdc") or 0),
                    mode=str(getattr(args, "run", "paper")),
                    order_id=str(_rec.get("order_id") or ""),
                    market_slug=str(_rec.get("market_slug") or ""),
                    temp_lo=float(_rec.get("temp_lo") or 0),
                    temp_hi=float(_rec.get("temp_hi") or 0),
                ))
            except Exception as _e:
                print(f"  {C['yellow']}{city.name}: re-persist do restore falhou: {_e}{R}")

        states[city_name] = state

    print()
    print(f"{DIM}Loop iniciado — Ctrl+C para parar{R}")
    
    # Inicializar polling do Telegram Bot com menu interativo
    tg = _get_tg()
    if tg:
        try:
            # Passar os estados dos bots para o menu
            # FIX BAIXO-15: usar _safe_tg_call para compatibilidade com tg.py antigo
            # V6: Andromeda send-only — sem polling = sem getUpdates = sem conflicts
            if not os.environ.get("V6_NO_POLLING"):
                _safe_tg_call(tg.start_polling, bot_states=states)
            else:
                print("  [v6] polling desativado (send-only) — menus vivem na Cassiopeia")
            print(f"  {C['green']}✓ Menu interativo do Telegram ativado{R}")
            
            # Enviar menu automaticamente quando o bot inicia
            print(f"  {C['green']}✓ Enviando menu inicial para o Telegram{R}")
            tg.send_menu()
        except Exception as e:
            print(f"  {C['yellow']}! Falha ao iniciar polling do Telegram: {e}{R}")
    
    print()

    city_bankrolls  = {}
    default_bankroll = DEFAULT_BANKROLL

    # FIX P2-9: limpar ficheiros .tmp antigos no arranque
    now_ts = time.time()
    for tmp_file in LOG_DIR.glob(".tmp_*"):
        try:
            if (now_ts - tmp_file.stat().st_mtime) > 86400:
                tmp_file.unlink()
        except Exception:
            pass

    #------
    for city_name in city_names:
        state = states[city_name]
    
    #    Atualizar bankroll a cada hora (ou se nunca foi buscado)
        if state.clob and trading_mode == TradingMode.REAL:
            h_now = city_now(state.city).hour
            if not hasattr(state, '_last_bankroll_hour') or state._last_bankroll_hour != h_now:
                try:
                    usdc_balance = state.clob.get_usdc_balance()
                    if usdc_balance is not None:
                        city_bankrolls[city_name] = usdc_balance
                    state._last_bankroll_hour = h_now
                except Exception:
                    pass
        else:
            city_bankrolls[city_name] = default_bankroll
    print()

    # Session stats — apenas para dashboard multi-cidade                         # ← NOVO
    session_stats = {                                                             # ← NOVO
        "total_trades": 0,                                                       # ← NOVO
        "total_pnl":    0.0,                                                     # ← NOVO
        "start_time":   datetime.now(tz=ZoneInfo("Europe/Lisbon")),              # ← NOVO
    }                                                                            # ← NOVO

    _tg_alert(
        "🟡 <b>Live bot iniciado</b>\n"
        f"  Modo: <b>{args.run.upper()}</b>\n"
        f"  Estratégia: <b>{args.mode}</b>\n"
        f"  Cidades: <b>{len(city_names)}</b> — {', '.join(city_names)}\n"
        f"  Intervalo: <b>{args.interval}s</b>\n"
        f"  Dashboard TG: <b>every {args.tg_interval}s</b>"
        + (f"\n  Threshold override: <b>{args.threshold_override}</b>" if args.threshold_override else "")
        + (f"\n  Race mode: top-{args.race_top_k} "
           f"(min_thr={args.race_min_threshold*100:.0f}%, "
           f"eval every {args.race_eval_interval}s)" if args.race_top_k > 0 else "")
        + (f"\n  Max buy ask: <b>{args.max_buy_ask*100:.0f}¢</b>")
    )

    # Daily stats por cidade — para passar ao dashboard                          # ← NOVO
    daily_stats: dict = {cn: states[cn].daily_stats for cn in city_names}        # ← NOVO
    session_pnl_cumulative = {cn: 0.0 for cn in city_names}
    session_last_reported_pnl = {cn: 0.0 for cn in city_names}
    session_last_dates = {cn: None for cn in city_names}
    session_last_trade_counts = {cn: 0 for cn in city_names}  # FIX P3-2b: delta trades
    
    _tg_last_dashboard = time.time()  # Primeiro dashboard após intervalo
    _tg_dashboard_interval = args.tg_interval  # default 1800s = 30 min (single E multi)
    # §92: relatório multi-cidade só com actividade (1º do dia / estado mudou / 21h)
    _tg_last_report_sig = None
    _tg_last_report_date = ""
    _tg_sent_daily_summary = False
    _tg_last_summary_date = None
    _tg_last_race_eval = 0.0  # Throttle para race phase (Top-K selection)
    # FIX BAIXO-17: throttle para write_live_snapshot (evita I/O excessivo)
    _last_snapshot_write = 0.0
    _snapshot_write_interval = min(10, args.interval)  # max 1 write a cada 10s

    if is_multi or args.force_dashboard:
        # ── FIX 1: tick inicial de todas as cidades antes do primeiro render ──
        print(f"  {C['cyan']}Tick inicial antes do dashboard...{R}")
        for city_name in city_names:
            state = states[city_name]
            city_h_now = city_now(state.city).hour
            if not (state.city.day_start <= city_h_now <= state.city.day_end):
                continue
            try:
                stats = _tick_city(state, args.run, city_bankrolls.get(city_name, default_bankroll))
                daily_stats[city_name] = stats
            except Exception as e:
                print(f"  {C['red']}{city_name}: tick inicial falhou: {e}{R}")
        
        try:
            initial_display = []
            for cn in city_names:
                # FIX CRÍTICO-3: usar snapshot thread-safe para o display
                state_snap = _snapshot_for_display(states[cn])
                cd = extract_display_data(
                    state_snap,
                    daily_stats=daily_stats.get(cn),
                    bankroll=city_bankrolls.get(cn, default_bankroll),
                )
                cd.p_ensemble = getattr(states[cn], "last_p_ensemble", 0.0)
                cd.p_lgbm = getattr(states[cn], "last_p_lgbm", None)
                cd.target_bracket = getattr(states[cn], "last_target_bracket", None)
                initial_display.append(cd)

            # FIX BAIXO-17: throttle write_live_snapshot no arranque
            if time.time() - _last_snapshot_write >= _snapshot_write_interval:
                write_live_snapshot(
                    initial_display,
                    trading_mode_str=args.run.upper(),
                    session_stats=session_stats,
                )
                _last_snapshot_write = time.time()
            if dashboard_enabled:
                render_dashboard(
                    initial_display,
                    trading_mode_str=args.run.upper(),
                    session_stats=session_stats,
                )
        except Exception as e:
            print(f"  {C['red']}Dashboard/snapshot init error: {e}{R}")

    # FIX: Settle any pending paper positions from previous days on startup
    # E verificar mudança de dia para posições ainda "abertas" no estado
    for city_name in city_names:
        state = states[city_name]
        city = state.city
        city_today = city_date(city)

        # Verificar se há posição no entry de dia anterior
        if state.entry and getattr(state.entry, "bought", False):
            rec = getattr(state.entry, "record", None) or {}
            entry_date_str = rec.get("date_opened") or str(rec.get("timestamp", ""))[:10]
            try:
                entry_date = date.fromisoformat(str(entry_date_str)[:10])
                if entry_date < city_today:
                    print(f"  {C['yellow']}{city.name}: Posição de {entry_date} detectada no arranque. "
                          f"A resolver...{R}")
                    # Forçar settlement do dia anterior
                    if trading_mode_str == "paper" and state.clob:
                        settled_pnl = _settle_paper_positions_for_day(state, entry_date)
                        if settled_pnl:
                            stats = state.daily_stats
                            stats.daily_pnl += settled_pnl
                            _save_daily_stats(stats, city.name)
                    # Limpar estado entry para novo dia
                    state.entry.bought = False
                    state.entry.record = None
                    if hasattr(state.entry, 'sold_by_stop'):
                        state.entry.sold_by_stop = False
            except Exception as e:
                print(f"  {C['yellow']}{city.name}: Erro a verificar data da posição: {e}{R}")

        # S1-7c: reconciliar bets nao-resolvidos de dias passados (via CSV)
        if trading_mode_str == "paper":
            try:
                rec_pnl = _reconcile_bets_from_csv(state)
                if rec_pnl:
                    print(f"  {C['green']}{city.name}: reconciliacao bets PnL={rec_pnl:+.2f}${R}")
                    if hasattr(state, 'daily_stats') and state.daily_stats:
                        state.daily_stats.daily_pnl += rec_pnl
            except Exception as e:
                print(f"  {C['yellow']}{city.name}: reconcile falhou: {e}{R}")

        # Settlement normal de posições pendentes nos CLOBs
        if trading_mode_str == "paper" and state.clob:
            try:
                settled_pnl = _settle_paper_positions_for_day(state, city_today,
                                                              settle_today=False)
                if settled_pnl:
                    print(f"  {C['green']}{city.name}: Startup settlement PnL={settled_pnl:+.2f}${R}")
                    if hasattr(state, 'daily_stats') and state.daily_stats:
                        state.daily_stats.daily_pnl += settled_pnl
                        _save_daily_stats(state.daily_stats, city.name)
            except Exception as e:
                print(f"  {C['yellow']}{city.name}: Startup settlement failed: {e}{R}")

    try:
        while True:
            now = bot_now()

            for city_name in city_names:
                state      = states[city_name]
                city       = state.city
                city_now_dt = city_now(city)          # FIX P3-2a: consolidar
                city_today = city_now_dt.date()       # FIX P3-2a: reutilizar

                city_h_now = city_now_dt.hour
                if trading_mode == TradingMode.PAPER and city_h_now > city.day_end:
                    try:
                        settled_pnl = _settle_paper_positions_for_day(state, city_today)
                        if settled_pnl:
                            stats = daily_stats.get(city_name) or state.daily_stats
                            stats.daily_pnl += settled_pnl
                            daily_stats[city_name] = stats
                            if is_multi:
                                session_pnl_cumulative[city_name] += settled_pnl
                                session_last_reported_pnl[city_name] = getattr(
                                    stats, "daily_pnl", 0.0
                                )
                                session_last_dates[city_name] = stats.date
                                session_stats["total_pnl"] = sum(session_pnl_cumulative.values())

                            # FIX Bug ALTO-5: limpar entry imediatamente após settlement
                            # para evitar estado "sujo" entre settlement e reset diário
                            if state.entry and getattr(state.entry, 'bought', False):
                                print(f"  {C['cyan']}{city.name}: Posição PAPER resolvida, "
                                      f"limpar entry (PnL={settled_pnl:+.2f}$){R}")
                                state.entry.bought = False
                                state.entry.record = None
                                if hasattr(state.entry, 'sold_by_stop'):
                                    state.entry.sold_by_stop = False
                                if hasattr(state.entry, '_stop_loss_blocked_alerted'):
                                    state.entry._stop_loss_blocked_alerted = False

                            # FIX Bug ALTO-8: marcar bets_*.json como resolved para o display
                            _mark_bet_resolved(city.name, city_today, settled_pnl)

                            # ── NOVO: notificar no Telegram quando posição resolve ──
                            tg_notify = _get_tg()
                            if tg_notify and state.entry and getattr(state.entry, 'bought', False):
                                rec = getattr(state.entry, 'record', None) or {}
                                try:
                                    # Determinar se ganhou ou perdeu
                                    peak_temp = None
                                    if state.slots_so_far:
                                        valid = [s for s in state.slots_so_far if s.get("temp_c") is not None]
                                        if valid:
                                            peak_slot = max(valid, key=lambda s: float(s["temp_c"]))
                                            peak_temp = float(peak_slot["temp_c"])

                                    if peak_temp is not None and state.market:
                                        # Verificar se o bracket ganhou
                                        bracket_won = False
                                        for b in state.market.get("brackets", []):
                                            lo = float(b.get("temp_lo", -99))
                                            hi = float(b.get("temp_hi", 99))
                                            contains = bracket_contains(lo, hi, peak_temp)
                                            if contains:
                                                buy_label = rec.get("bracket_label") or rec.get("bracket")
                                                if buy_label and b.get("label") == buy_label:
                                                    bracket_won = True
                                                break

                                        # Criar posição fictícia para o alerta
                                        pos_info = {
                                            "bracket_label": rec.get("bracket_label") or rec.get("bracket", "?"),
                                            "entry_ask": rec.get("ask", 0),
                                            "shares": rec.get("shares", 0),
                                            "size_usdc": rec.get("size_usdc", 0),
                                            "date_opened": str(city_today),
                                            "pnl_usd": settled_pnl,
                                            "pnl_pct": (settled_pnl / rec.get("size_usdc", 1) * 100) if rec.get("size_usdc") else 0,
                                        }

                                        # Enviar notificação apropriada
                                        if bracket_won:
                                            pos_info["status"] = type("Status", (), {"value": "won"})()
                                            _tg_thread(tg_notify.alert_position_resolved, pos_info)
                                        else:
                                            pos_info["status"] = type("Status", (), {"value": "lost"})()
                                            _tg_thread(tg_notify.alert_position_resolved, pos_info)
                                except Exception as e:
                                    print(f"  [TG] Notificação de resolução falhou: {e}")

                            # ── NOVO: registar outcome no tick_logger ──
                            if _TICK_LOGGER is not None:
                                try:
                                    # Calcular temp_max_actual
                                    temp_max_actual = None
                                    temp_max_hour = None
                                    if state.slots_so_far:
                                        valid = [s for s in state.slots_so_far if s.get("temp_c") is not None]
                                        if valid:
                                            peak_slot = max(valid, key=lambda s: float(s["temp_c"]))
                                            temp_max_actual = float(peak_slot["temp_c"])
                                            temp_max_hour = int(peak_slot["hour"])

                                    # Bracket resolvido: regra oficial half-up.
                                    bracket_resolved = None
                                    win = None
                                    if state.market and temp_max_actual is not None:
                                        for b in state.market.get("brackets", []):
                                            lo = float(b.get("temp_lo", -99))
                                            hi = float(b.get("temp_hi", 99))
                                            if not bracket_contains(lo, hi, temp_max_actual):
                                                continue
                                            bracket_resolved = b.get("label")
                                            # Win se comprou este bracket — limites oficiais.
                                            if state.entry and getattr(state.entry, "bought", False):
                                                rec = getattr(state.entry, "record", None) or {}
                                                try:
                                                    plo = float(rec.get("temp_lo", b.get("temp_lo", -99)))
                                                    phi = float(rec.get("temp_hi", b.get("temp_hi", 99)))
                                                    win = bracket_contains(plo, phi, temp_max_actual)
                                                except (TypeError, ValueError):
                                                    # Fallback final: comparar labels
                                                    buy_label = rec.get("bracket_label") or rec.get("bracket")
                                                    win = (buy_label == bracket_resolved) if buy_label is not None else None
                                            break

                                    # Stats do dia
                                    n_buys = len(getattr(stats, "trades", []))
                                    n_stops = getattr(stats, "stop_losses_triggered", 0)
                                    bought = bool(state.entry and getattr(state.entry, "bought", False))
                                    pnl_total = float(getattr(stats, "daily_pnl", 0.0) or 0.0)
                                    invested = float(getattr(stats, "total_invested", 0.0) or 0.0)

                                    _TICK_LOGGER.log_outcome(
                                        city_name=city.name,
                                        date_str=city_today.isoformat(),
                                        temp_max_actual=temp_max_actual,
                                        temp_max_hour=temp_max_hour,
                                        bracket_resolved=bracket_resolved,
                                        n_buys=n_buys,
                                        n_sells=0,
                                        n_stops=n_stops,
                                        bought=bought,
                                        win=win,
                                        pnl_total=pnl_total,
                                        invested=invested,
                                        race_used=False,  # race info não disponível aqui
                                        eod_used=False,
                                    )
                                except Exception as e:
                                    print(f"  [tick_logger] log_outcome failed: {e}")
                    except Exception as e:
                        print(f"  {C['yellow']}{city.name}: PAPER settlement failed: {e}{R}")

                if not (city.day_start <= city_h_now <= city.day_end):
                    continue

                try:
                    city_bankroll = city_bankrolls.get(city_name, DEFAULT_BANKROLL)
                    stats = _tick_city(state, args.run, city_bankroll)

                    daily_stats[city_name] = stats                               # ← NOVO

                    if state.clob and hasattr(state.clob, "positions"):
                        try:
                            state.clob.positions.refresh(state.clob)
                            today_key = city_today.isoformat()
                            for pos in state.clob.positions.all_positions():
                                pos_id = str(getattr(pos, "order_id", "") or "")
                                if not pos_id or pos_id in state._settled_position_ids:
                                    continue
                                if getattr(pos, "date_opened", "") != today_key:
                                    continue
                                # §106: ficheiro partilhado pela frota — só
                                # posições DESTA cidade (mesmo bug do settle)
                                _pslug = str(getattr(pos, "market_slug", "") or "")
                                _pcity = (_pslug.split("-on-")[0].split("-in-")[-1].lower()
                                          if _pslug else "")
                                if _pcity and _pcity != city_name.replace("_", "-"):
                                    continue
                                if getattr(pos, "status", None) in (
                                    PositionStatus.WON,
                                    PositionStatus.LOST,
                                    PositionStatus.EXPIRED,
                                ):
                                    pnl = float(getattr(pos, "pnl_usd", 0.0) or 0.0)
                                    stats.daily_pnl += pnl
                                    state._settled_position_ids.add(pos_id)
                                    # FIX P1-2: limpar entry quando CLOB reporta resolvido
                                    if state.entry and getattr(state.entry, "bought", False):
                                        state.entry.bought = False
                                        state.entry.record = None
                                        if hasattr(state.entry, "sold_by_stop"):
                                            state.entry.sold_by_stop = False
                                        if hasattr(state.entry, "_stop_loss_blocked_alerted"):
                                            state.entry._stop_loss_blocked_alerted = False
                        except Exception:
                            pass

                    if trading_mode == TradingMode.REAL:
                        h_now = city_now_dt.hour      # FIX P3-2a: reutilizar
                        if state._last_bankroll_hour != h_now:
                            try:
                                usdc_balance = state.clob.get_usdc_balance() if state.clob else None
                                if usdc_balance is not None:
                                    city_bankrolls[city_name] = usdc_balance
                                state._last_bankroll_hour = h_now
                            except Exception:
                                pass
                    else:
                        # FIX P3-2c: só atualizar bankroll PAPER quando há delta
                        last_applied = getattr(state, '_last_applied_pnl', 0.0)
                        delta = stats.daily_pnl - last_applied
                        if delta != 0:
                            prev_bankroll = city_bankrolls.get(city_name, default_bankroll)
                            city_bankrolls[city_name] = max(100.0, prev_bankroll + delta)
                            state._last_applied_pnl = stats.daily_pnl
                            # Persistir estado PAPER para consistência após restart
                            _save_paper_state(city.name, {"_last_applied_pnl": state._last_applied_pnl}, city_today, city_bankrolls.get(city_name, DEFAULT_BANKROLL))

                    if is_multi:
                        current_stats = daily_stats.get(city_name)
                        if current_stats:
                            current_date = current_stats.date
                            n_trades_now = len(getattr(current_stats, "trades", []))
                            if session_last_dates.get(city_name) != current_date:
                                # FIX 9: dia mudou — acumular trades do dia anterior
                                session_stats["total_trades"] += len(
                                    getattr(states[city_name].daily_stats, "trades", [])
                                )
                                session_last_dates[city_name] = current_date
                                session_last_reported_pnl[city_name] = 0.0
                                # FIX P3-2b: resetar contador de trades do dia
                                session_last_trade_counts[city_name] = 0
                            # FIX P3-2b: delta de trades (só contar novos)
                            prev_count = session_last_trade_counts.get(city_name, 0)
                            if n_trades_now > prev_count:
                                session_stats["total_trades"] += (n_trades_now - prev_count)
                                session_last_trade_counts[city_name] = n_trades_now
                            current_daily_pnl = float(getattr(current_stats, "daily_pnl", 0.0) or 0.0)
                            delta = current_daily_pnl - session_last_reported_pnl[city_name]
                            session_pnl_cumulative[city_name] += delta
                            session_last_reported_pnl[city_name] = current_daily_pnl
                        session_stats["total_pnl"] = sum(session_pnl_cumulative.values())

                except Exception as e:
                    print(f"  {C['red']}{city.name}: Tick failed: {e}{R}")

            # ── RACE PHASE: Top-K selection (alternativa ao EOD, sem forçar) ────
            # Em multi-city com --race-top-k > 0, a cada race_eval_interval segundos:
            #   1. Conta quantas cidades já compraram hoje
            #   2. Se < race_top_k, há slots disponíveis
            #   3. Filtra cidades elegíveis: não compradas + p_ensemble >= race_min_threshold
            #      + ask <= max_buy_ask + em janela de trading
            #   4. Ordena por p_ensemble desc, pega nas top-K
            #   5. Baixa temporariamente threshold dessas top-K e chama _tick_city
            #   6. Restaura threshold original
            #
            # Diferença vs EOD: Race NÃO força. Só dispara se p_ensemble >= race_min_threshold
            # (default 0.50). Se nenhuma cidade atinge esse mínimo, não há buy — mantém qualidade.
            if is_multi and args.race_top_k > 0:
                now_ts_race = time.time()
                if now_ts_race - _tg_last_race_eval >= args.race_eval_interval:
                    _tg_last_race_eval = now_ts_race
                    try:
                        # Contar quantas cidades já compraram hoje
                        n_bought_now = sum(
                            1 for s in states.values()
                            if s.entry and getattr(s.entry, 'bought', False)
                        )
                        if n_bought_now < args.race_top_k:
                            slots_avail = args.race_top_k - n_bought_now
                            # Filtrar cidades elegíveis
                            candidates = []
                            n_eligible_evaluated = 0
                            for cn, s in states.items():
                                if not s.entry or getattr(s.entry, 'bought', False):
                                    continue
                                # Verificar se está em janela de trading
                                city_h = city_now(s.city).hour
                                if not (s.city.day_start <= city_h <= s.city.day_end):
                                    continue
                                n_eligible_evaluated += 1
                                p = float(getattr(s, 'last_p_ensemble', 0.0) or 0.0)
                                if p < args.race_min_threshold:
                                    continue
                                bracket = getattr(s, 'last_target_bracket', None)
                                if not bracket:
                                    continue
                                ask = float(bracket.get('ask') or bracket.get('price', 1.0) or 1.0)
                                # Respeitar max_buy_ask
                                if ask > float(getattr(s, 'max_buy_ask', 0.85)):
                                    continue
                                # Respeitar min_buy_ask
                                if ask < float(getattr(s.entry, 'min_buy_ask', 0.20)):
                                    continue
                                candidates.append((cn, p, ask, bracket))
                            # Ordenar por p_ensemble desc
                            candidates.sort(key=lambda x: x[1], reverse=True)
                            top_n = candidates[:slots_avail]

                            if not top_n:
                                # Sem candidatos elegíveis neste eval
                                print(f"  {DIM}RACE: sem candidatos elegíveis "
                                      f"(avaliadas {n_eligible_evaluated}, "
                                      f"min_thr={args.race_min_threshold*100:.0f}%){R}")
                                # Throttled alert (só a cada 30 min) para não spammar
                                tg_race = _get_tg()
                                if tg_race and (now_ts_race - getattr(tg_race, '_last_no_cand_alert', 0)) >= 1800:
                                    try:
                                        _tg_thread(
                                            tg_race.alert_race_no_candidates,
                                            args.race_min_threshold, n_eligible_evaluated,
                                        )
                                        tg_race._last_no_cand_alert = now_ts_race
                                    except Exception:
                                        pass
                            else:
                                # Iterar pelas top-K candidatas, preenchendo slots
                                # até atingir slots_avail. Cidades com race_thr >=
                                # original_thr são skipadas (já deviam ter disparado
                                # no tick normal) e NÃO contam para o limite.
                                slots_filled = 0
                                for cn, p, ask, bracket in top_n:
                                    if slots_filled >= slots_avail:
                                        break
                                    s = states[cn]
                                    original_thr = float(getattr(s.entry, 'threshold', 0.65) or 0.65)
                                    # Race threshold: max(min_abs * 0.95, p * 0.95)
                                    # Garante que evaluate() dispara (p >= race_thr)
                                    race_thr = max(args.race_min_threshold * 0.95, p * 0.95)
                                    if race_thr >= original_thr:
                                        # Já deveria ter disparado no tick normal, skip
                                        # NÃO conta para o limite — passa à próxima
                                        print(f"  {DIM}RACE: {cn.upper()} já acima do threshold "
                                              f"original ({original_thr:.2f}), skip{R}")
                                        continue
                                    s.entry.threshold = race_thr
                                    print(f"  {C['cyan']}{cn.upper()} RACE: thr "
                                          f"{original_thr:.2f}→{race_thr:.2f}, "
                                          f"p={p:.2f}, ask={ask*100:.0f}¢ "
                                          f"(slot {slots_filled+1}/{slots_avail}){R}")
                                    # Avisar via Telegram
                                    tg_race = _get_tg()
                                    if tg_race:
                                        try:
                                            _tg_thread(
                                                tg_race.alert_race_selected,
                                                cn, p, original_thr, race_thr,
                                                bracket.get('label'), ask,
                                                slots_filled+1, slots_avail,
                                            )
                                        except Exception:
                                            pass
                                    # FIX Bug ALTO-4: verificação dupla antes de race tick
                                    if s.entry and getattr(s.entry, 'bought', False):
                                        print(f"  {C['yellow']}{cn}: RACE skip — já comprado durante eval{R}")
                                        slots_filled += 1
                                        # Restaurar threshold original
                                        s.entry.threshold = original_thr
                                        continue

                                    # Fazer tick again para executar buy com threshold baixado
                                    race_did_buy = False
                                    try:
                                        city_bankroll_race = city_bankrolls.get(cn, DEFAULT_BANKROLL)
                                        race_stats = _tick_city(s, args.run, city_bankroll_race, is_race=True)
                                        # FIX Bug 4.16: atualizar session_stats após race buy
                                        if race_stats and race_stats.trades:
                                            race_did_buy = True
                                            daily_stats[cn] = race_stats
                                            if is_multi:
                                                session_stats["total_trades"] = max(
                                                    session_stats["total_trades"],
                                                    sum(len(getattr(st.daily_stats, "trades", [])) for st in states.values())
                                                )
                                    except Exception as e:
                                        print(f"  {C['red']}{cn}: RACE tick failed: {e}{R}")
                                    finally:
                                        # Restaurar threshold original
                                        s.entry.threshold = original_thr
                                    # FIX Bug ALTO-4: só contabiliza slot se realmente comprou
                                    if race_did_buy:
                                        slots_filled += 1
                    except Exception as e:
                        print(f"  {C['red']}RACE phase error: {e}{R}")

            # ── DISPLAY ──────────────────────────────────────────────────────
            if is_multi or args.force_dashboard:
                try:
                    cities_display = []
                    for cn in city_names:
                        # FIX CRÍTICO-3: usar snapshot thread-safe para o display
                        state_snap = _snapshot_for_display(states[cn])
                        cd = extract_display_data(
                            state_snap,
                            daily_stats=daily_stats.get(cn),
                            bankroll=city_bankrolls.get(cn, default_bankroll),
                        )
                        # p_ensemble e target_bracket guardados pelo _tick_city
                        cd.p_ensemble = getattr(states[cn], "last_p_ensemble", 0.0)
                        cd.p_lgbm = getattr(states[cn], "last_p_lgbm", None)
                        cd.target_bracket = getattr(states[cn], "last_target_bracket", None)
                        cities_display.append(cd)

                    # FIX BAIXO-17: throttle write_live_snapshot no main loop
                    if now_ts - _last_snapshot_write >= _snapshot_write_interval:
                        write_live_snapshot(
                            cities_display,
                            trading_mode_str=args.run.upper(),
                            session_stats=session_stats,
                        )
                        _last_snapshot_write = now_ts

                    if dashboard_enabled:
                        render_dashboard(
                            cities_display,
                            trading_mode_str=args.run.upper(),
                            session_stats=session_stats,
                        )

                    # ── TELEGRAM PERIODIC REPORT ──────────────────────────────
                    now_ts = time.time()
                    if now_ts - _tg_last_dashboard >= _tg_dashboard_interval:
                        tg_inst = _get_tg()
                        if tg_inst:
                            cities_data = []
                            for cn in city_names:
                                ds = daily_stats.get(cn)
                                pnl = float(getattr(ds, "daily_pnl", 0.0) or 0.0) if ds else 0.0
                                st_c = states.get(cn)
                                city_cfg = st_c.city if st_c else None
                                p_ens = float(getattr(st_c, "last_p_ensemble", 0.0) or 0.0) if st_c else 0.0
                                # §92: threshold REAL da estratégia activa
                                # (CassiopeiaEntry.threshold = cassiopeia_active_config),
                                # NÃO o city_cfg.threshold (strategy_config do
                                # mundo SingleEntry — 0.35/0.40/0.55 errados aqui)
                                thr = None
                                if st_c and getattr(st_c, "entry", None) is not None:
                                    thr = getattr(st_c.entry, "threshold", None)
                                if thr is None:
                                    thr = (city_cfg.threshold if city_cfg and city_cfg.threshold is not None else 0.65)
                                hmin = (city_cfg.hour_min if city_cfg and city_cfg.hour_min is not None else 14)
                                bought = bool(st_c.entry.bought) if (st_c and st_c.entry) else False
                                temp_now = st_c.latest_obs.get("temp_c") if (st_c and st_c.latest_obs) else None
                                rmax = None
                                if st_c and st_c.slots_so_far:
                                    try:
                                        rmax = max(float(s["temp_c"]) for s in st_c.slots_so_far if s.get("temp_c") is not None)
                                    except Exception:
                                        rmax = None
                                _now_local = city_now(city_cfg) if city_cfg else None
                                local_hhmm = _now_local.strftime("%H:%M") if _now_local else ""
                                # §92: p_rebound/ask só se o last_eval for de HOJE
                                # (fora da janela 12-18/14-20 o last_eval fica
                                # com os valores da véspera — mostrar P(pico) em vez)
                                _le = (getattr(getattr(st_c, "entry", None), "last_eval", None) or {})
                                _le_ok = bool(_le) and _now_local is not None \
                                    and str(_le.get("date")) == str(_now_local.date())
                                cities_data.append({
                                    "name": cn,
                                    "pnl": pnl,
                                    "p_ensemble": p_ens,
                                    "threshold": thr,
                                    "hour_min": hmin,
                                    "bought": bought,
                                    "temp_now": temp_now,
                                    "running_max": rmax,
                                    "local_hhmm": local_hhmm,
                                    "p_rebound": _le.get("p_rebound") if _le_ok else None,
                                    "ask": _le.get("ask") if _le_ok else None,
                                    "daily_pnl": pnl,
                                    "daily_trades": len(getattr(states[cn].daily_stats, "trades", [])) if states[cn].daily_stats else 0,
                                })

                            # §92: relatório só com actividade — envia se
                            # (a) primeiro do dia, (b) estado mudou vs o último
                            # enviado, ou (c) 21h (resumo diário garantido).
                            _sig = tuple(
                                (cd["name"],
                                 round(float(cd.get("p_ensemble") or 0.0), 3),
                                 round(float(cd.get("p_rebound")
                                           if cd.get("p_rebound") is not None else -1.0), 3),
                                 round(float(cd.get("ask") or 0.0), 3),
                                 round(float(cd.get("threshold") or 0.0), 3),
                                 bool(cd.get("bought")))
                                for cd in cities_data
                            ) + (int(session_stats["total_trades"]),
                                 round(float(session_stats["total_pnl"]), 2))
                            _today_str = datetime.now().strftime("%Y-%m-%d")
                            _hora_now = datetime.now().hour
                            _primeiro_do_dia = (_tg_last_report_date != _today_str)
                            if _primeiro_do_dia and _hora_now < 21:
                                _tg_sent_daily_summary = False
                            _resumo_diario = (not _tg_sent_daily_summary) and _hora_now >= 21
                            if (_sig != _tg_last_report_sig) or _primeiro_do_dia or _resumo_diario:
                                _safe_tg_call(tg_inst.alert_multi_city_summary,
                                    mode_str=args.run.upper(),
                                    total_pnl=session_stats["total_pnl"],
                                    n_trades=session_stats["total_trades"],
                                    cities_data=cities_data
                                )
                                _tg_last_report_sig = _sig
                                _tg_last_report_date = _today_str
                                if _hora_now >= 21:
                                    _tg_sent_daily_summary = True
                        _tg_last_dashboard = now_ts

                except Exception as e:
                    import traceback as _tb
                    print(f"  {C['red']}Dashboard/snapshot error: {e}{R}")
                    _tb.print_exc()
            # ── SINGLE-CITY: dashboard periodico detalhado + near-signal alert ──
            else:
                now_ts = time.time()
                # 1) Dashboard completo a cada args.tg_interval segundos
                if now_ts - _tg_last_dashboard >= args.tg_interval:
                    tg_inst = _get_tg()
                    if tg_inst:
                        try:
                            _send_single_city_dashboard(
                                tg_inst, states, city_names[0],
                                daily_stats, args.run,
                                city_bankrolls.get(city_names[0], default_bankroll),
                                session_stats=session_stats,
                            )
                        except Exception as e:
                            print(f"  {C['yellow']}Single-city TG dashboard error: {e}{R}")
                    _tg_last_dashboard = now_ts

                # 2) Near-signal alert (throttled a 30 min)
                #    Dispara quando p_ensemble esta entre threshold*0.85 e threshold
                #    e ainda nao houve buy - ajuda a perceber porque nao dispara.
                try:
                    st = states[city_names[0]]
                    city_cfg = st.city
                    thr = city_cfg.threshold if city_cfg.threshold is not None else 0.65
                    p = float(getattr(st, "last_p_ensemble", 0.0) or 0.0)
                    if (st.entry
                        and not st.entry.bought
                        and thr * 0.85 <= p < thr
                        and (now_ts - st._last_near_signal_ts) >= 1800):
                        tg_inst = _get_tg()
                        if tg_inst:
                            temp_now = st.latest_obs.get("temp_c") if st.latest_obs else None
                            rmax = None
                            if st.slots_so_far:
                                try:
                                    rmax = max(float(s["temp_c"]) for s in st.slots_so_far
                                               if s.get("temp_c") is not None)
                                except Exception:
                                    pass
                            try:
                                _safe_tg_call(tg_inst.alert_near_signal, 
                                    city_cfg.name, p, thr,
                                    rmax=rmax, temp_now=temp_now,
                                )
                            except Exception as e:
                                print(f"  {C['yellow']}near_signal alert failed: {e}{R}")
                        st._last_near_signal_ts = now_ts
                except Exception as e:
                    print(f"  {C['yellow']}near_signal check failed: {e}{R}")
            # ── FIM single-city telegram ──

            time.sleep(args.interval)

    except KeyboardInterrupt:
        print()
        print(f"{C['yellow']}Interruptido pelo utilizador{R}")
        
        # Parar polling do Telegram Bot
        tg = _get_tg()
        if tg and tg.polling_active:
            try:
                tg.stop_polling()
                print(f"  {C['green']}✓ Polling do Telegram parado{R}")
            except Exception as e:
                print(f"  {C['yellow']}! Erro ao parar polling: {e}{R}")
        
        print(f"  A guardar estatísticas...")
        for city_name, state in states.items():
            city_today = city_date(state.city)
            stats_path = LOG_DIR / f"{city_name}_{city_today}.json"
            if stats_path.exists():
                print(f"  {city_name}: {stats_path}")
        print(f"{C['green']}Done.{R}")

if __name__ == "__main__":
    main()
