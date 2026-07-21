"""
live_bot.py
============
Bot de trading ao vivo — Multi-cidade genérico.

Uso:
    python live_bot.py --cities munich --mode single --run paper
    python live_bot.py --cities munich,dallas --mode single --run real
"""

import argparse
import csv
import math
import json
import time
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Optional
import threading
from cities.config import CityConfig, get_city, CITIES
from predictor import set_city, load_models, predict_ensemble, compute_prev7, init_history_max
from backtester import _compute_realized_pnl, TAKER_FEE_RATE
from weather import (
    make_wu_session, fetch_wu_latest,
    fetch_wu_forecast_max,
    bootstrap_today, ceil_slot, floor_slot, is_plausible_temp,
)
from weather_v3 import (
    v3_fetch_current, v3_fetch_forecast_daily, v3_fetch_forecast_hourly,
    v3_bootstrap_today,
)
from modules.strategy_factory import create_strategy
from polymarket_clob import ClobClient, TradingMode, GAMMA_API, PositionStatus, round_to_tick
from zoneinfo import ZoneInfo

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

LOG_DIR = Path("live_bot_logs")
_TG_TRADING_MODE: str = "paper"  # Module-level trading mode for Telegram token selection
LOG_DIR.mkdir(exist_ok=True)


# ── FIX: usar PWS do config; só fallback para ICAO se não houver PWS ──
def _city_with_icao_station(city):
    """Retorna cópia da city garantindo pws_station_id válido.

    Prioridade:
    1. pws_station_id do config (se existir e não estiver vazio)
    2. icao como fallback (se a API key suportar estações oficiais)
    3. cidade original se nenhum dos dois existir
    """
    # Se já tem PWS definido no config, usa-o diretamente
    if getattr(city, 'pws_station_id', None) and city.pws_station_id:
        return city

    # Se não tem PWS mas tem ICAO, tenta usar ICAO como fallback
    if not city.icao:
        return city

    # Criar shallow copy e substituir pws_station_id pelo ICAO
    city_icao = city.__class__(
        name=city.name,
        icao=city.icao,
        timezone=city.timezone,
        latitude=city.latitude,
        longitude=city.longitude,
        polymarket_slug_pfx=city.polymarket_slug_pfx,
        wu_history_path=city.wu_history_path,
        csv_path=city.csv_path,
        model_dir=city.model_dir,
        unit=city.unit,
        temp_range=city.temp_range,
        max_daily_loss=city.max_daily_loss,
        max_per_trade=city.max_per_trade,
        extra_features=city.extra_features,
        threshold=city.threshold,
        hour_min=city.hour_min,
        pws_station_id=city.icao,  # ← Fallback para ICAO
        market_unit=city.market_unit,
        day_start=city.day_start,
        day_end=city.day_end,
        bot_timezone=city.bot_timezone,
        climatology=city.climatology,
    )
    return city_icao



PARCEL_SIZE = 5.0


def _load_paper_state(city_name: str) -> dict:
    """Carrega estado PAPER persistido (inclui _last_applied_pnl)."""
    path = LOG_DIR / f"paper_state_{city_name}.json"
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    return {}


def _save_paper_state(city_name: str, state_dict: dict) -> None:
    """Persiste estado PAPER de forma atómica."""
    path = LOG_DIR / f"paper_state_{city_name}.json"
    tmp_path = LOG_DIR / f".tmp_paper_state_{city_name}_{int(time.time()*1000)}.json"
    try:
        tmp_path.write_text(json.dumps(state_dict, indent=2, default=str))
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
    def find_bracket(market: dict, temp: float, forecast_max: float = None) -> Optional[dict]:
        """Encontra o bracket mais próximo da temperatura."""
        if not market:
            return None
        if forecast_max is not None:
            target = int(math.floor(forecast_max))
        else:
            target = int(math.floor(temp))

        for b in market["brackets"]:
            lo, hi = b["temp_lo"], b["temp_hi"]
            if lo == hi and target == round(lo):
                return b
            if hi >= 99 and target >= lo:
                return b
            if lo <= -99 and target <= hi:
                return b
            if lo <= target <= hi:
                return b

        # Fallback: bracket mais próximo
        min_b = min(market["brackets"],
                    key=lambda b: abs((b["temp_lo"] + b["temp_hi"]) / 2 - target))
        return min_b

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
    wu_key: str = ""
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

# ════════════════════════════════════════════════════
#  HELPERS
# ════════════════════════════════════════════════════

def city_now(city: CityConfig) -> datetime:
    return datetime.now(tz=ZoneInfo(city.timezone))


def city_date(city: CityConfig) -> date:
    return city_now(city).date()


def bot_now() -> datetime:
    return datetime.now(tz=ZoneInfo("Europe/Lisbon"))


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
    """Carrega slots já conhecidos do dia, sem incluir slots futuros.

    SEM FALLBACK PARA OM — só usa WU. Se WU falha, slots_so_far fica vazio
    e o caller decide o que fazer. Os prints do fetch_wu_day mostram a causa real.
    """
    city = state.city
    now_city = city_now(city)
    limit_h, limit_s = floor_slot(now_city.hour, now_city.minute)
    limit_idx = limit_h * 60 + limit_s

    # ── NOVO: Tentar V3 ICAO primeiro ──
    series, slots = {}, []

    if city.icao and state.wu_key:
        try:
            series, slots = v3_bootstrap_today(city.icao, state.wu_key)
            if len(slots) >= 4:
                print(f"  {C['green']}{city.name}: V3 ICAO bootstrap OK ({len(slots)} slots){R}")
            else:
                print(f"  {C['yellow']}{city.name}: V3 ICAO devolveu {len(slots)} slots — tentando V2 PWS{R}")
                # Fallback para V2 PWS
                if city.wu_history_path and city.pws_station_id:
                    city_wu = _city_with_icao_station(city)
                    series, slots = bootstrap_today(
                        city_wu, state.wu_key, state.wu_sess, verbose=not state.dashboard_enabled
                    )
        except Exception as e:
            print(f"  {C['yellow']}{city.name}: V3 ICAO falhou: {e} — tentando V2 PWS{R}")
            # Fallback para V2 PWS
            if city.wu_history_path and city.pws_station_id:
                try:
                    city_wu = _city_with_icao_station(city)
                    series, slots = bootstrap_today(
                        city_wu, state.wu_key, state.wu_sess, verbose=not state.dashboard_enabled
                    )
                except Exception as e2:
                    print(f"  {C['red']}{city.name}: V2 PWS também falhou: {e2}{R}")

    # Se ainda não temos slots suficientes, avisar
    if len(slots) < 4:
        print(f"  {C['red']}{city.name}: SEM DADOS — V3 ICAO e V2 PWS falharam ({len(slots)} slots){R}")

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


def _settle_paper_positions_for_day(state: CityState, city_today: date) -> float:
    """Resolve PAPER positions abertas (dia atual e pendentes antigas)."""
    if not state.clob or not hasattr(state.clob, "positions"):
        return 0.0

    def _peak_for_date(target_day: date) -> Optional[float]:
        if target_day == city_today:
            if state.slots_so_far:
                return max(float(s["temp_c"]) for s in state.slots_so_far)
            if state.latest_obs and state.latest_obs.get("temp_c") is not None:
                return float(state.latest_obs["temp_c"])
            return None

        hist_path = Path("historic") / f"{state.city.name}.csv"
        if not hist_path.exists():
            return None

        # Tenta múltiplos formatos comuns de data para evitar falhas de parsing
        target_keys = {
            target_day.strftime("%Y-%m-%d"),  # ISO 8601
            target_day.strftime("%d/%m/%Y"),  # EU (formato mais comum nos dados)
        }
        max_temp: Optional[float] = None
        try:
            with hist_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if str(row.get("date", "")).strip() not in target_keys:
                        continue
                    t_raw = row.get("temp_c")
                    if t_raw in (None, ""):
                        continue
                    t = float(t_raw)
                    max_temp = t if max_temp is None else max(max_temp, t)
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
        if pos_day > city_today:
            continue

        pos_id = str(
            getattr(pos, "order_id", "")
            or getattr(pos, "token_id", "")
            or getattr(pos, "bracket_label", "")
        )
        if pos_id and pos_id in state._settled_position_ids:
            continue
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


def _tg_thread(fn, *args, **kwargs) -> None:
    import threading
    threading.Thread(target=fn, args=args, kwargs=kwargs, daemon=True).start()


def _tg_alert(msg: str) -> None:
    """Alerta genérico (texto livre) — fallback quando não há método dedicado."""
    print(f"[TG] {msg}")
    tg = _get_tg()
    if tg:
        try:
            _tg_thread(tg.send, msg)
        except Exception:
            pass


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

    # rmax e rmax_time
    if state.slots_so_far:
        valid_slots = [s for s in state.slots_so_far if s.get("temp_c") is not None]
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
    if state.latest_obs:
        temp_now = state.latest_obs.get("temp_c")

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
    chart_lines = _build_ascii_chart(state.slots_so_far)

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
        tg_inst.dashboard(
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

def _tick_city(state: CityState, trading_mode_str: str, bankroll: float) -> DailyStats:
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
        # FIX Bug 4.13: settlement do dia anterior ANTES de resetar o estado.
        # Anteriormente o settlement só acontecia se city_h_now > day_end,
        # o que falhava quando o dia mudava para um novo dia (00:00).
        if trading_mode_str == "paper" and state.clob:
            try:
                prev_day = state._last_date
                settled_pnl = _settle_paper_positions_for_day(state, prev_day)
                if settled_pnl and hasattr(state, 'daily_stats') and state.daily_stats:
                    state.daily_stats.daily_pnl += settled_pnl
                    _save_daily_stats(state.daily_stats, city.name)
            except Exception as e:
                print(f"  {C['yellow']}{city.name}: PAPER settlement no reset falhou: {e}{R}")

        # Guardar stats do dia anterior antes de perder
        if hasattr(state, 'daily_stats') and state.daily_stats:
            _save_daily_stats(state.daily_stats, city.name)
        # FIX 3: limpar settled IDs antigos (manter só últimos 30 dias de memória)
        if len(state._settled_position_ids) > 10000:
            state._settled_position_ids.clear()
        state.slots_so_far = []
        state.series_today = {}
        state.cloud_by_hour = {}
        state.entry = create_strategy(city, mode=state.strategy_mode, parcel_size=PARCEL_SIZE)
        # FIX 1: reaplicar threshold_override se existir
        if state.threshold_override is not None and hasattr(state.entry, 'threshold'):
            state.entry.threshold = float(state.threshold_override)
        if hasattr(state.entry, '_stop_loss_blocked_alerted'):
            state.entry._stop_loss_blocked_alerted = False
        state._last_date = city_today
        state.daily_stats = DailyStats(date=city_today)  # ← Reset no novo dia
        # Resetar o delta PnL aplicado ao bankroll PAPER — senão o tick
        # seguinte subtrai o PnL do dia anterior (daily_pnl=0 vs last_applied>0).
        state._last_applied_pnl = 0.0
        # Resetar contadores do throttle para o novo dia.
        state._last_saved_trades = 0
        state._last_saved_stops = 0
        _bootstrap_state_today(state)

    # Em vez de: stats = DailyStats(date=city_today)
    stats = state.daily_stats  # ← Usar o objecto persistente

    # FIX 5: backoff para bootstrap (evita spam de tentativas se API down)
    if getattr(state, "_bootstrap_pending", False) and len(state.slots_so_far) < 4:
        now_ts_boot = time.time()
        if now_ts_boot - state._last_bootstrap_attempt >= 60:  # só a cada 60s
            state._last_bootstrap_attempt = now_ts_boot
            try:
                _bootstrap_state_today(state)
                # Só desativa o flag se realmente resolveu o problema
                if len(state.slots_so_far) >= 4:
                    state._bootstrap_pending = False
            except Exception:
                pass  # mantém pending, tenta de novo daqui a 60s

    # Fetch WU (única fonte — sem fallback OM)
    new_obs = None
    # ── NOVO: Tentar V3 ICAO current primeiro ──
    new_obs = None
    if city.icao and state.wu_key:
        try:
            new_obs = v3_fetch_current(city.icao, state.wu_key)
            if new_obs:
                print(f"  {C['green']}{city.name}: V3 ICAO current OK ({new_obs['temp_c']}°C){R}")
            else:
                print(f"  {C['yellow']}{city.name}: V3 ICAO current retornou None (ICAO={city.icao}){R}")
        except Exception as e:
            print(f"  {C['yellow']}{city.name}: V3 ICAO current falhou: {e} (ICAO={city.icao}){R}")

    # Fallback para V2 PWS se V3 falhar
    if new_obs is None and city.wu_history_path and city.pws_station_id:
        try:
            city_wu = _city_with_icao_station(city)
            new_obs = fetch_wu_latest(city_wu, state.wu_key, state.wu_sess)
        except Exception as e:
            print(f"  {C['yellow']}WU V2 fetch failed: {e}{R}")

    # Sem mais fallbacks — V3 ICAO e V2 PWS são as únicas fontes
    if new_obs is None:
        print(f"  {C['red']}{city.name}: SEM DADOS ATUAIS — V3 ICAO e V2 PWS falharam{R}")

    state.latest_obs = new_obs
    if new_obs and not is_plausible_temp(new_obs.get("temp_c"), city):
        print(
            f"  {C['red']}{city.name}: rejected implausible temp "
            f"{new_obs.get('temp_c')}°C{R}"
        )
        new_obs = None
        state.latest_obs = None

    # Forecasts apenas informativos para dashboard/alertas; não entram na decisão.
    h_forecast = city_now(city).hour
    if state.last_forecast_hour != h_forecast:
        try:
            # ── NOVO: V3 ICAO forecast primeiro ──
            wu_forecast = None
            if city.icao and state.wu_key:
                wu_forecast = v3_fetch_forecast_daily(city.icao, state.wu_key)
                if wu_forecast:
                    print(f"  {C['green']}{city.name}: V3 ICAO forecast OK (max={wu_forecast.get('temp_max')}°C){R}")

            # Fallback V2 PWS
            if wu_forecast is None and city.wu_history_path and city.pws_station_id:
                city_wu = _city_with_icao_station(city)
                wu_forecast = fetch_wu_forecast_max(city_wu, state.wu_key, state.wu_sess)

            # ── REMOVIDO: fetch_om_forecast_max (Open-Meteo removido)
            state.last_wu_forecast_max = (
                wu_forecast.get("temp_max") if isinstance(wu_forecast, dict) else None
            )
            # ── REMOVIDO: last_om_forecast_max (Open-Meteo removido)


            state.last_forecast_hour = h_forecast
        except Exception as e:
            print(f"  {C['yellow']}{city.name}: Forecast fetch failed: {e}{R}")

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
                            # FIX: actualizar series_today para slot existente
                            for key in list(state.series_today.keys()):
                                if key[0] == h_slot and key[1] == s30:
                                    state.series_today[key] = s["temp_c"]
                            break
                else:
                    state.slots_so_far.append(slot_entry)
                    state.slots_so_far.sort(key=lambda x: x["hour"] * 60 + x["slot30"])
                    # FIX: adicionar a series_today para novo slot
                    new_idx = len(state.slots_so_far) - 1
                    state.series_today[(h_slot, s30, new_idx)] = slot_entry["temp_c"]

    from predictor import update_history_max, init_history_max
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
                    rmax_floor = int(math.floor(running_max_ref))
                    enriched_brackets = []
                    for b in _market["brackets"]:
                        mid_temp = (float(b.get("temp_lo", 0.0)) + float(b.get("temp_hi", 0.0))) / 2.0
                        if (
                            abs(mid_temp - rmax_floor) <= 3.0
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
        if not history_max_for_features and state.slots_so_far:
            prev7_value = max(float(s["temp_c"]) for s in state.slots_so_far)

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
        running_max = max(s["temp_c"] for s in state.slots_so_far) if state.slots_so_far else 0.0

         # ← INSERIR AQUI
        state.last_target_bracket = PolymarketFetcher.find_bracket(
            state.market, running_max
        )

        # Usar forecasts WU+OM reais para agreement (logging/telemetria, não bloqueia compra)
        wu = state.last_wu_forecast_max
        om = None  # ── REMOVIDO: Open-Meteo removido
        if wu is not None and om is not None:
            diff = abs(wu - om)
            fc_agreement = {
                "valid": diff <= 2,
                "diff": diff,
                "consensus_max": (wu + om) // 2,
                "reason": "" if diff <= 2 else f"WU={wu}°C vs OM={om}°C",
            }
        else:
            fc_agreement = {
                "valid": True,  # se um falta, não bloqueamos
                "diff": None,
                "consensus_max": wu or om,
                "reason": "forecast missing",
            }

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

                ask = bracket.get("ask") or bracket.get("price", 1.0)
                size_usdc = action["size_usdc"]
                token_id = bracket.get("token_id")
                raw_best_ask = None

                if token_id and state.clob:
                    try:
                        fresh_book = state.clob.get_orderbook(token_id)
                        if fresh_book and getattr(fresh_book, "best_ask", None) is not None:
                            raw_best_ask = float(fresh_book.best_ask)
                            ask = round_to_tick(raw_best_ask, direction="up")
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
                if effective_ask < min_buy_ask:
                    print(
                        f"  {C['yellow']}{city.name.upper()} BUY BLOQUEADO: "
                        f"ask {effective_ask*100:.1f}¢ < mínimo {min_buy_ask*100:.0f}¢{R}"
                    )
                    _tg_alert(
                        f"🚫 <b>{city.name.title()}</b> buy bloqueado: "
                        f"ask {effective_ask*100:.1f}¢ < mínimo {min_buy_ask*100:.0f}¢"
                    )
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
                    "p_ensemble":    p_ensemble,
                    "p_lgbm":        ensemble_result.get("p_lgbm") if ensemble_result else None,
                    "running_max":   running_max,
                }
                bet_record["market_slug"] = current_market_slug

                if trading_mode_str == "real":
                    if not token_id:
                        print(f"  {C['red']}{city.name} BUY FALHOU: token_id em falta no bracket{R}")
                        break

                    market_slug = state.fetcher.date_to_slug(city_today)
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
                        order_type="GTC",
                        temp_lo=bracket.get("temp_lo"),
                        temp_hi=bracket.get("temp_hi"),
                    )

                    if result.success:
                        bet_record["order_id"] = result.order_id
                        bet_record["status"] = result.status
                        bet_record["simulated"] = result.simulated
                        state.entry.mark_bought(0, bet_record)
                        stats.trades.append(bet_record)
                        stats.total_invested += size_usdc
                        _append_bet_record(bet_record, city.name, city_today)
                        print(f"  {C['green']}{city.name.upper()} BUY: {bracket['label']} "
                              f"@ {ask*100:.1f}¢  ${size_usdc:.2f}  ({action['reason']}){R}")
                        _tg_alert_order_placed(bet_record, trading_mode_str)
                        # ── NOVO: registar bet no tick_logger ──
                        if _TICK_LOGGER is not None:
                            try:
                                _TICK_LOGGER.log_bet(
                                    bet_record=bet_record,
                                    city_name=city.name,
                                    date_str=city_today.isoformat(),
                                    trigger="normal",
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
                    market_slug = state.fetcher.date_to_slug(city_today)
                    result = state.clob.buy_yes(
                        token_id=token_id,
                        price=ask,
                        size_usdc=size_usdc,
                        bracket_label=bracket["label"],
                        market_slug=market_slug,
                        order_type="GTC",
                        temp_lo=bracket.get("temp_lo"),
                        temp_hi=bracket.get("temp_hi"),
                    )

                    if result.success:
                        bet_record["order_id"] = result.order_id
                        bet_record["status"] = result.status
                        bet_record["simulated"] = result.simulated
                        state.entry.mark_bought(0, bet_record)
                        stats.trades.append(bet_record)
                        stats.total_invested += size_usdc
                        _append_bet_record(bet_record, city.name, city_today)
                        print(f"  {C['yellow']}{city.name.upper()} BUY [PAPER]: {bracket['label']} "
                              f"@ {ask*100:.1f}¢  ${size_usdc:.2f}  ({action['reason']}){R}")
                        _tg_alert_order_placed(bet_record, trading_mode_str)
                        # ── NOVO: registar bet no tick_logger ──
                        if _TICK_LOGGER is not None:
                            try:
                                _TICK_LOGGER.log_bet(
                                    bet_record=bet_record,
                                    city_name=city.name,
                                    date_str=city_today.isoformat(),
                                    trigger="normal",
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

                            poll = [p for p in state.clob.positions.open_positions()
                                    if p.token_id == pos_token_id
                                    and getattr(p, "market_slug", "") == current_market_slug]

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
                                    # Usar função partilhada para consistência com backtester
                                    pnl_result = _compute_realized_pnl(
                                        pos.get("ask", 0), fresh_bid, 
                                        pos.get("size_usdc", 0), TAKER_FEE_RATE
                                    )
                                    realized_pnl = pnl_result["realized_pnl"]

                                    state.entry.mark_sold_by_stop(fresh_bid, realized_pnl)
                                    settled_id = str(pos.get("order_id") or pos.get("timestamp") or pos.get("bracket_label") or "")
                                    if settled_id:
                                        state._settled_position_ids.add(settled_id)
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
    parser.add_argument("--mode", type=str, default="single", choices=["single"],
                        help="Modo de estratégia: single")
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
    parser.add_argument("--max-buy-ask", type=float, default=0.85,
                        help="Ask máximo para comprar em fracção 0..1 (default 0.85=85¢). "
                             "Blocks buys acima deste valor — brackets quase certos têm "
                             "payout mínimo.")
    # ── NOVOS: Top-K Race mode ──
    parser.add_argument("--race-top-k", type=int, default=0,
                        help="Top-K Race mode: a cada N minutos, ordena todas as cidades "
                             "não compradas por p_ensemble desc e baixa temporariamente o "
                             "threshold das top-K (com p >= --race-min-threshold). "
                             "Default 0 = desactivado. Recomendado: 2 (1-2 bets/dia).")
    parser.add_argument("--race-min-threshold", type=float, default=0.50,
                        help="Threshold mínimo absoluto para Race mode (default 0.50). "
                             "Race nunca compra abaixo deste valor — garante qualidade. "
                             "Ex: 0.55 = só dispara se P(pico) >= 55%.")
    parser.add_argument("--race-eval-interval", type=int, default=300,
                        help="Segundos entre race evals (default 300=5min). Race não corre "
                             "em todos os ticks para evitar overhead de predict.")
    args = parser.parse_args()

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
    global _TG_TRADING_MODE
    _TG_TRADING_MODE = args.run.lower()  # "paper" ou "real"
    is_multi     = len(city_names) > 1
    has_tty = sys.stdout.isatty()
    dashboard_enabled = is_multi and (not args.no_dashboard)

    # Import dashboard multi-cidade apenas se necessário
    if is_multi:
        from display import extract_display_data, render_dashboard, write_live_snapshot

    print("=" * 60)
    print(f" {B}Live Bot — Multi-Cidade{R}")
    print("=" * 60)
    print(f"  Cidades:  {', '.join(city_names)}")
    print(f"  Modo:     {args.mode}")
    print(f"  Execução: {args.run.upper()}")
    print(f"  Intervalo:{args.interval}s")
    if dashboard_enabled:
        dash_label = "multi-cidade (display.py)"
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

        entry = create_strategy(city, mode=args.mode, parcel_size=PARCEL_SIZE)
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

        # Restaurar _last_applied_pnl do disco (para bankroll PAPER consistente após restart)
        paper_state = _load_paper_state(city.name)
        state._last_applied_pnl = paper_state.get("_last_applied_pnl", 0.0)
    # ── REMOVIDO: wu_only (Open-Meteo removido)

        # ── NOVO: restaurar posição existente antes do primeiro tick ──
        bets_path = LOG_DIR / f"bets_{city.name}_{city_date(city)}.json"
        if bets_path.exists():
            try:
                existing_bets = json.loads(bets_path.read_text())
                current_slug = state.fetcher.date_to_slug(city_date(city))
                matching = [b for b in existing_bets if b.get("market_slug") == current_slug]
                if matching and state.entry:
                    first = matching[-1]
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
                    print(f"  {C['green']}{city.name}: Posição restaurada na init "
                          f"— {_rec.get('bracket','?')} @ {_rec.get('ask',0)*100:.1f}¢{R}")
            except Exception as e:
                print(f"  {C['yellow']}{city.name}: Restore init falhou: {e}{R}")

        # ── NOVO: configurar filtros no state ──
        state.max_buy_ask = float(args.max_buy_ask)
        state._last_near_signal_ts = 0.0

        import os
        state.wu_key = os.environ.get("WU_API_KEY", "")

        if city.wu_history_path and not state.wu_key:
            print(f"  {C['yellow']}{city.name}: WU_API_KEY não definida, usando apenas OM{R}")
    # ── REMOVIDO: wu_only (Open-Meteo removido)
            print(f"  {C['cyan']}{city.name}: WU-only ativo (sem fallback OM){R}")

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

        states[city_name] = state

    print()
    print(f"{DIM}Loop iniciado — Ctrl+C para parar{R}")
    
    # Inicializar polling do Telegram Bot com menu interativo
    tg = _get_tg()
    if tg:
        try:
            # Passar os estados dos bots para o menu
            tg.start_polling(bot_states=states)
            print(f"  {C['green']}✓ Menu interativo do Telegram ativado{R}")
            
            # Enviar menu automaticamente quando o bot inicia
            print(f"  {C['green']}✓ Enviando menu inicial para o Telegram{R}")
            tg.send_menu()
        except Exception as e:
            print(f"  {C['yellow']}! Falha ao iniciar polling do Telegram: {e}{R}")
    
    print()

    city_bankrolls  = {}
    default_bankroll = PARCEL_SIZE * 100
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
    
    _tg_last_dashboard = time.time()  # Primeiro dashboard após intervalo
    _tg_dashboard_interval = args.tg_interval  # default 1800s = 30 min (single E multi)
    _tg_last_summary_date = None
    _tg_last_race_eval = 0.0  # Throttle para race phase (Top-K selection)

    if is_multi:
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
                cd = extract_display_data(
                    states[cn],
                    daily_stats=daily_stats.get(cn),
                    bankroll=city_bankrolls.get(cn, default_bankroll),
                )
                cd.p_ensemble = getattr(states[cn], "last_p_ensemble", 0.0)
                cd.p_lgbm = getattr(states[cn], "last_p_lgbm", None)
                cd.target_bracket = getattr(states[cn], "last_target_bracket", None)
                initial_display.append(cd)

            # Escreve snapshot logo no arranque (web não fica parcial/stale).
            write_live_snapshot(
                initial_display,
                trading_mode_str=args.run.upper(),
                session_stats=session_stats,
            )
            if dashboard_enabled:
                render_dashboard(
                    initial_display,
                    trading_mode_str=args.run.upper(),
                    session_stats=session_stats,
                )
        except Exception as e:
            print(f"  {C['red']}Dashboard/snapshot init error: {e}{R}")

    # FIX: Settle any pending paper positions from previous days on startup
    # This handles the case where the bot was stopped overnight and restarted
    for city_name in city_names:
        state = states[city_name]
        city = state.city
        city_today = city_date(city)
        if trading_mode_str == "paper" and state.clob:
            try:
                # Check for positions from yesterday and before
                settled_pnl = _settle_paper_positions_for_day(state, city_today)
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
                city_today = city_date(city)

                city_h_now = city_now(city).hour
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
                                            if hi >= 99:
                                                contains = peak_temp >= lo
                                            elif lo <= -99:
                                                contains = peak_temp <= hi
                                            else:
                                                contains = lo <= peak_temp < (hi + 1.0)
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

                                    # Bracket resolvido: o que contém temp_max_actual
                                    # Usar intervalo semiaberto [lo, hi+1.0) como o backtester
                                    # (_bracket_contains_peak) para evitar overlap no pico exato.
                                    bracket_resolved = None
                                    win = None
                                    if state.market and temp_max_actual is not None:
                                        for b in state.market.get("brackets", []):
                                            lo = float(b.get("temp_lo", -99))
                                            hi = float(b.get("temp_hi", 99))
                                            if hi >= 99:
                                                _contains = temp_max_actual >= lo
                                            elif lo <= -99:
                                                _contains = temp_max_actual <= hi
                                            else:
                                                _contains = lo <= temp_max_actual < (hi + 1.0)
                                            if not _contains:
                                                continue
                                            bracket_resolved = b.get("label")
                                            # Win se comprou este bracket — preferir
                                            # limites numéricos (robusto a normalização).
                                            if state.entry and getattr(state.entry, "bought", False):
                                                import math as _m
                                                rec = getattr(state.entry, "record", None) or {}
                                                try:
                                                    plo = float(rec.get("temp_lo", b.get("temp_lo", -99)))
                                                    phi = float(rec.get("temp_hi", b.get("temp_hi", 99)))
                                                    peak_int = int(_m.floor(temp_max_actual))
                                                    if phi >= 99:
                                                        win = peak_int >= int(_m.floor(plo))
                                                    elif plo <= -99:
                                                        win = peak_int <= int(_m.floor(phi))
                                                    else:
                                                        win = int(_m.floor(plo)) <= peak_int <= int(_m.floor(phi))
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
                    city_bankroll = city_bankrolls.get(city_name, PARCEL_SIZE * 100)
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
                                if getattr(pos, "status", None) in (
                                    PositionStatus.WON,
                                    PositionStatus.LOST,
                                    PositionStatus.EXPIRED,
                                ):
                                    pnl = float(getattr(pos, "pnl_usd", 0.0) or 0.0)
                                    stats.daily_pnl += pnl
                                    state._settled_position_ids.add(pos_id)
                        except Exception:
                            pass

                    if trading_mode == TradingMode.REAL:
                        h_now = city_now(state.city).hour
                        if state._last_bankroll_hour != h_now:
                            try:
                                usdc_balance = state.clob.get_usdc_balance() if state.clob else None
                                if usdc_balance is not None:
                                    city_bankrolls[city_name] = usdc_balance
                                state._last_bankroll_hour = h_now
                            except Exception:
                                pass
                    else:
                        # FIX: bankroll PAPER — aplicar apenas o delta desde a última vez
                        prev_bankroll = city_bankrolls.get(city_name, default_bankroll)
                        last_applied = getattr(state, '_last_applied_pnl', 0.0)
                        delta = stats.daily_pnl - last_applied
                        city_bankrolls[city_name] = max(100.0, prev_bankroll + delta)
                        state._last_applied_pnl = stats.daily_pnl

                        # Persistir estado PAPER para consistência após restart
                        _save_paper_state(city.name, {"_last_applied_pnl": state._last_applied_pnl})

                    if is_multi:
                        current_stats = daily_stats.get(city_name)
                        if current_stats:
                            current_date = current_stats.date
                            if session_last_dates.get(city_name) != current_date:
                                # FIX 9: dia mudou — acumular trades do dia anterior
                                session_stats["total_trades"] += len(
                                    getattr(states[city_name].daily_stats, "trades", [])
                                )
                                session_last_dates[city_name] = current_date
                                session_last_reported_pnl[city_name] = 0.0
                            current_daily_pnl = float(getattr(current_stats, "daily_pnl", 0.0) or 0.0)
                            delta = current_daily_pnl - session_last_reported_pnl[city_name]
                            session_pnl_cumulative[city_name] += delta
                            session_last_reported_pnl[city_name] = current_daily_pnl
                        # Total trades = acumulado + trades do dia atual de todas as cidades
                        trades_today = sum(
                            len(getattr(s.daily_stats, "trades", []))
                            for s in states.values()
                            if getattr(s, "daily_stats", None)
                        )
                        session_stats["total_trades"] = max(session_stats["total_trades"], trades_today)
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
                                    # Fazer tick again para executar buy com threshold baixado
                                    try:
                                        city_bankroll_race = city_bankrolls.get(cn, PARCEL_SIZE * 100)
                                        race_stats = _tick_city(s, args.run, city_bankroll_race)
                                        # FIX Bug 4.16: atualizar session_stats após race buy
                                        if race_stats and race_stats.trades:
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
                                    # Só incrementa slots_filled se realmente tentámos
                                    # o buy (mesmo que falhe — contabiliza a tentativa)
                                    slots_filled += 1
                    except Exception as e:
                        print(f"  {C['red']}RACE phase error: {e}{R}")

            # ── DISPLAY ──────────────────────────────────────────────────────
            if is_multi:
                try:
                    cities_display = []
                    for cn in city_names:
                        cd = extract_display_data(
                            states[cn],
                            daily_stats=daily_stats.get(cn),
                            bankroll=city_bankrolls.get(cn, default_bankroll),
                        )
                        # p_ensemble e target_bracket guardados pelo _tick_city
                        cd.p_ensemble = getattr(states[cn], "last_p_ensemble", 0.0)
                        cd.p_lgbm = getattr(states[cn], "last_p_lgbm", None)
                        cd.target_bracket = getattr(states[cn], "last_target_bracket", None)
                        cities_display.append(cd)

                    # Snapshot web sempre atualizado, mesmo sem render Rich.
                    write_live_snapshot(
                        cities_display,
                        trading_mode_str=args.run.upper(),
                        session_stats=session_stats,
                    )

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
                                local_hhmm = city_now(city_cfg).strftime("%H:%M") if city_cfg else ""
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
                                    "daily_pnl": pnl,
                                    "daily_trades": len(getattr(states[cn].daily_stats, "trades", [])) if states[cn].daily_stats else 0,
                                })
                            
                            tg_inst.alert_multi_city_summary(
                                mode_str=args.run.upper(),
                                total_pnl=session_stats["total_pnl"],
                                n_trades=session_stats["total_trades"],
                                session_pnl=session_stats["total_pnl"],
                                session_trades=session_stats["total_trades"],
                                cities_data=cities_data
                            )
                        _tg_last_dashboard = now_ts

                except Exception as e:
                    print(f"  {C['red']}Dashboard/snapshot error: {e}{R}")
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
                                tg_inst.alert_near_signal(
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
