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
from cities.config import CityConfig, get_city, CITIES
from predictor import set_city, load_models, predict_ensemble, compute_prev7, init_history_max
from weather import (
    make_wu_session, make_om_session, fetch_wu_latest,
    fetch_wu_forecast_max, fetch_om_forecast_max, fetch_om_hourly_today,
    bootstrap_today, bootstrap_om_today, ceil_slot, is_plausible_temp,
)
from modules.strategy_factory import create_strategy
from polymarket_clob import ClobClient, TradingMode, GAMMA_API, PositionStatus, round_to_tick
from zoneinfo import ZoneInfo

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
LOG_DIR.mkdir(exist_ok=True)

PARCEL_SIZE = 5.0

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
    wu_sess = None
    om_sess = None
    clob: ClobClient | None = None
    trading_mode: TradingMode = TradingMode.PAPER
    latest_obs: dict | None = None
    last_forecast_hour: int = -1
    last_wu_forecast_max: int | None = None
    last_om_forecast_max: int | None = None
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
    data = {
        "date": str(stats.date),
        "trades": len(stats.trades),
        "total_invested": round(stats.total_invested, 2),
        "daily_pnl": round(stats.daily_pnl, 2),
        "stop_losses_triggered": stats.stop_losses_triggered,
    }
    log_path.write_text(json.dumps(data, indent=2))


def _append_bet_record(bet_record: dict, city_name: str, d: date) -> None:
    """Persistir trades para anti-duplicado entre restarts."""
    bets_path = LOG_DIR / f"bets_{city_name}_{d}.json"
    try:
        existing = json.loads(bets_path.read_text()) if bets_path.exists() else []
        existing.append(bet_record)
        bets_path.write_text(json.dumps(existing, indent=2))
    except Exception as e:
        print(f"  {C['yellow']}{city_name}: falha a guardar bet record: {e}{R}")


def _bootstrap_state_today(state: CityState) -> None:
    """Carrega slots já conhecidos do dia, sem incluir slots futuros."""
    city = state.city
    now_city = city_now(city)
    limit_h, limit_s = ceil_slot(now_city.hour, now_city.minute)
    limit_idx = limit_h * 60 + limit_s

    try:
        if city.wu_history_path:
            series, slots = bootstrap_today(
                city, state.wu_key, state.wu_sess, verbose=not state.dashboard_enabled
            )
            if len(slots) < 4 and not getattr(state, "wu_only", False):
                print(f"  {C['yellow']}{city.name}: WU com poucos dados, fallback OM{R}")
                series, slots = bootstrap_om_today(
                    city, state.om_sess, verbose=not state.dashboard_enabled
                )
        else:
            series, slots = bootstrap_om_today(
                city, state.om_sess, verbose=not state.dashboard_enabled
            )
    except Exception as e:
        print(f"  {C['yellow']}{city.name}: bootstrap falhou, usando OM: {e}{R}")
        series, slots = bootstrap_om_today(
            city, state.om_sess, verbose=not state.dashboard_enabled
        )

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

        target_key = target_day.strftime("%d/%m/%Y")
        max_temp: Optional[float] = None
        try:
            with hist_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if str(row.get("date", "")).strip() != target_key:
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


def _get_tg():
    """Singleton lazy de tg.TG() — None se Telegram não configurado."""
    if not hasattr(_get_tg, "_instance"):
        try:
            from tg import TG
            _get_tg._instance = TG()
        except Exception:
            _get_tg._instance = None
    return _get_tg._instance


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
#  TICK por cidade
# ════════════════════════════════════════════════════

def _tick_city(state: CityState, trading_mode_str: str, bankroll: float) -> DailyStats:
    city = state.city
    set_city(city.name)
    now = bot_now()
    city_today = city_date(city)

    # Reset diário (Fix 11)
    if not hasattr(state, '_last_date'):
        state._last_date = city_today
    if city_today != state._last_date:
        state.slots_so_far = []
        state.series_today = {}
        state.cloud_by_hour = {}
        state.entry = create_strategy(city, mode=state.strategy_mode, parcel_size=PARCEL_SIZE)
        if hasattr(state.entry, '_stop_loss_blocked_alerted'):
            state.entry._stop_loss_blocked_alerted = False
        state._last_date = city_today
        state.daily_stats = DailyStats(date=city_today)  # ← Reset no novo dia
        _bootstrap_state_today(state)

    # Em vez de: stats = DailyStats(date=city_today)
    stats = state.daily_stats  # ← Usar o objecto persistente

    if getattr(state, "_bootstrap_pending", False) and len(state.slots_so_far) < 4:
        try:
            _bootstrap_state_today(state)
        except Exception:
            state._bootstrap_pending = True

    # Fetch WU (se disponível)
    new_obs = None
    if city.wu_history_path:
        try:
            new_obs = fetch_wu_latest(city, state.wu_key, state.wu_sess)
        except Exception as e:
            print(f"  {C['yellow']}WU fetch failed: {e}{R}")

    # Se não há WU, usar Open-Meteo
    if not new_obs:
        try:
            om_hourly = fetch_om_hourly_today(city, state.om_sess)
            if om_hourly:
                h_now = city_now(city).hour
                new_obs = min(om_hourly, key=lambda r: abs(r["hour"] - h_now))
        except Exception as e:
            print(f"  {C['yellow']}OM fetch failed: {e}{R}")

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
            wu_forecast = (
                fetch_wu_forecast_max(city, state.wu_key, state.wu_sess)
                if city.wu_history_path else None
            )
            om_forecast = fetch_om_forecast_max(city, state.om_sess)
            state.last_wu_forecast_max = (
                wu_forecast.get("temp_max") if isinstance(wu_forecast, dict) else None
            )
            state.last_om_forecast_max = (
                om_forecast.get("temp_max") if isinstance(om_forecast, dict) else None
            )
            state.last_forecast_hour = h_forecast
        except Exception as e:
            print(f"  {C['yellow']}{city.name}: Forecast fetch failed: {e}{R}")

    # Atualizar slots
    if new_obs:
        h_obs, m_obs = new_obs["hour"], new_obs["minute"]
        h_slot, s30 = ceil_slot(h_obs, m_obs)

        if city.day_start <= h_slot <= city.day_end:
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
                            slot_entry["temp_c"] = s["temp_c"]
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

    from predictor import update_history_max, init_history_max
    history_max_for_features = dict(state.history_max)
    update_history_max(state.history_max, state.slots_so_far, city.name)

    # Fetch market (a cada 10 minutos ou se não existe)
    now_city = city_now(city)
    market_key = (now_city.hour, now_city.minute // 10)
    if state.last_market_min != market_key or state.market is None:
        try:
            state.market = state.fetcher.fetch_market(city_today)
            if state.market and state.clob:
                running_max_ref = (
                    max((s["temp_c"] for s in state.slots_so_far), default=15.0)
                    if state.slots_so_far
                    else (state.latest_obs.get("temp_c", 15.0) if state.latest_obs else 15.0)
                )
                rmax_floor = int(math.floor(running_max_ref))
                enriched_brackets = []
                for b in state.market["brackets"]:
                    mid_temp = (float(b.get("temp_lo", 0.0)) + float(b.get("temp_hi", 0.0))) / 2.0
                    if (
                        abs(mid_temp - rmax_floor) <= 3.0
                        or float(b.get("temp_lo", 0.0)) <= -99.0
                        or float(b.get("temp_hi", 0.0)) >= 99.0
                    ):
                        enriched_brackets.append(state.clob.enrich_bracket(b))
                    else:
                        enriched_brackets.append(b)
                state.market["brackets"] = enriched_brackets
            state.last_market_min = market_key
        except Exception as e:
            print(f"  {C['yellow']}{city.name}: Fetch market failed: {e}{R}")

    # ── Anti-duplicado: verificar DUAS fontes ──
    if state.entry and state.clob:
        _skip = False
        _rec = None
        current_market_slug = state.fetcher.date_to_slug(city_today)

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
                    }
            except Exception:
                pass

        if _skip and _rec and state.entry:
            if hasattr(state.entry, "restore"):
                state.entry.restore(_rec, state.strategy_mode)
            else:
                state.entry.bought = True
                state.entry.record = _rec
                if hasattr(state.entry, 'strategy_used'):
                    state.entry.strategy_used = _rec.get("strategy") or state.strategy_mode
            if hasattr(state.entry, "_stop_loss_blocked_alerted"):
                state.entry._stop_loss_blocked_alerted = False
            print(f"  {C['yellow']}{city.name}: Posição existente detectada "
                  f"— a saltar entrada{R}")

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
        _temp       = obs.get("temp_c") if obs.get("temp_c") is not None else last_slot.get("temp_c", 0)
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
        
        actions = state.entry.evaluate(
            p_ensemble=p_ensemble,
            hour=h_cur,
            market=state.market,
            running_max=running_max,
            forecast_agreement=None,
            slots_so_far=state.slots_so_far,
        )

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

                min_buy_ask = getattr(state.entry, "min_buy_ask", 0.20)
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
                    "shares":        size_usdc / ask if ask > 0 else 0,
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
                    else:
                        err = result.error or result.status
                        print(f"  {C['red']}{city.name.upper()} BUY [PAPER] REJEITADO: {err}{R}")

                break  # Apenas uma ação por tick

    # ─── STOP-LOSS CHECK ────────────────────────────
    if state.entry and state.clob and state.latest_obs:
        current_temp = state.latest_obs["temp_c"]
        if hasattr(state.entry, 'check_stop_loss'):
            stop_signal = state.entry.check_stop_loss(current_temp)
            if stop_signal and state.market:
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
                    pos_lo = float(pos.get("temp_lo", 0))
                    pos_hi = float(pos.get("temp_hi", 0))
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
                else:
                    bracket = matching[0]
                    bid_price = bracket.get("bid")

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
                        current_market_slug = state.fetcher.date_to_slug(city_today)
                        poll = [p for p in state.clob.positions.open_positions()
                                if p.token_id == pos.get("token_id")
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
                            sell_result = state.clob.sell_yes(poll[0], bid_price)
                            if sell_result.success:
                                entry_ask = pos.get("ask", 0)
                                shares = pos.get("size_usdc", 0) / entry_ask if entry_ask > 0 else 0
                                realized_pnl = shares * bid_price - pos.get("size_usdc", 0)

                                state.entry.mark_sold_by_stop(bid_price, realized_pnl)
                                settled_id = str(pos.get("order_id") or pos.get("timestamp") or pos.get("bracket_label") or "")
                                if settled_id:
                                    state._settled_position_ids.add(settled_id)
                                stats.stop_losses_triggered += 1

                                stats.daily_pnl += realized_pnl

                                print(f"\n  {C['yellow']}⚠  [{city.name}] {stop_signal['reason']}{R}")
                                print(f"  {C['yellow']}   Vendido @ {bid_price:.4f}, "
                                      f"PnL={realized_pnl:+.2f}{R}")

                                _tg_alert_stop_loss_triggered(
                                    city.name, pos, current_temp,
                                    bid_price=bid_price, realized_pnl=realized_pnl,
                                )
                            else:
                                # ── Caso 3c: ordem de venda falhou ──
                                if not _already_alerted:
                                    err = getattr(sell_result, 'error', None) or 'erro desconhecido'
                                    print(f"\n  {C['red']}⚠  [{city.name}] {stop_signal['reason']}{R}")
                                    print(f"  {C['red']}   FALHA na venda @ {bid_price:.4f}: {err}{R}")
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

    _save_daily_stats(stats, city.name)
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
    parser.add_argument("--wu-only", action="store_true",
                        help="Para cidades com WU, não usa fallback Open-Meteo")
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
        print(
            f"  {city.name}: estratégia carregada "
            f"(threshold={getattr(entry, 'threshold', 'n/a')}, "
            f"hour_min={getattr(entry, 'hour_min', 'n/a')})"
        )

        state = CityState(
            city=city,
            strategy_mode=args.mode,
            models=models,
            entry=entry,
            fetcher=PolymarketFetcher(city),
            history_max=init_history_max(city_name),  # ← carregar do disco
            daily_stats=DailyStats(date=city_date(city)),  # ← NOVO
            dashboard_enabled=dashboard_enabled,
        )
        state.wu_only = bool(args.wu_only)

        import os
        state.wu_key = os.environ.get("WU_API_KEY", "")

        if city.wu_history_path and not state.wu_key:
            print(f"  {C['yellow']}{city.name}: WU_API_KEY não definida, usando apenas OM{R}")
        if city.wu_history_path and state.wu_only:
            print(f"  {C['cyan']}{city.name}: WU-only ativo (sem fallback OM){R}")

        state.wu_sess = make_wu_session()
        state.om_sess = make_om_session()
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
        f"  Intervalo: <b>{args.interval}s</b>"
    )

    # Daily stats por cidade — para passar ao dashboard                          # ← NOVO
    daily_stats: dict = {cn: None for cn in city_names}                         # ← NOVO
    session_pnl_cumulative = {cn: 0.0 for cn in city_names}
    session_last_reported_pnl = {cn: 0.0 for cn in city_names}
    session_last_dates = {cn: None for cn in city_names}
    
    _tg_last_dashboard = time.time()  # Primeiro dashboard após 1h
    _tg_dashboard_interval = 60 * 60  # 1 hora
    _tg_last_summary_date = None

    if is_multi:
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
                        city_bankrolls[city_name] = max(0.0, default_bankroll + stats.daily_pnl)

                    if is_multi:                                                  # ← NOVO
                        session_stats["total_trades"] = sum(                    # ← NOVO
                            len(getattr(s.daily_stats, "trades", []))           # ← NOVO
                            for s in states.values()                             # ← NOVO
                            if getattr(s, "daily_stats", None)                  # ← NOVO
                        )                                                        # ← NOVO
                        current_stats = daily_stats.get(city_name)
                        if current_stats:
                            current_date = current_stats.date
                            if session_last_dates.get(city_name) != current_date:
                                session_last_dates[city_name] = current_date
                                session_last_reported_pnl[city_name] = 0.0
                            current_daily_pnl = float(getattr(current_stats, "daily_pnl", 0.0) or 0.0)
                            delta = current_daily_pnl - session_last_reported_pnl[city_name]
                            session_pnl_cumulative[city_name] += delta
                            session_last_reported_pnl[city_name] = current_daily_pnl
                        session_stats["total_pnl"] = sum(session_pnl_cumulative.values())  # ← NOVO

                except Exception as e:
                    print(f"  {C['red']}{city.name}: Tick failed: {e}{R}")

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
                                cities_data.append({"name": cn, "pnl": pnl})
                            
                            tg_inst.alert_multi_city_summary(
                                mode_str=args.run.upper(),
                                total_pnl=session_stats["total_pnl"],
                                n_trades=session_stats["total_trades"],
                                cities_data=cities_data
                            )
                        _tg_last_dashboard = now_ts

                except Exception as e:
                    print(f"  {C['red']}Dashboard/snapshot error: {e}{R}")
            # ── single-city: _tick_city já faz os seus próprios prints ─────

            time.sleep(args.interval)

    except KeyboardInterrupt:
        print()
        print(f"{C['yellow']}Interruptido pelo utilizador{R}")
        print(f"  A guardar estatísticas...")
        for city_name, state in states.items():
            city_today = city_date(state.city)
            stats_path = LOG_DIR / f"{city_name}_{city_today}.json"
            if stats_path.exists():
                print(f"  {city_name}: {stats_path}")
        print(f"{C['green']}Done.{R}")

if __name__ == "__main__":
    main()
