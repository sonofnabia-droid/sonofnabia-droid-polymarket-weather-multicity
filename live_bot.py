"""
live_bot.py
============
Bot de trading ao vivo — Multi-cidade genérico.

Uso:
    python live_bot.py --cities munich --mode single --run paper
    python live_bot.py --cities munich,dallas --mode single --run real
"""

import argparse
import json
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone as _tz, timedelta
from pathlib import Path
from typing import Optional

import numpy as np

from cities.config import CityConfig, get_city, CITIES
from predictor import set_city, load_models, build_features, predict_ensemble, compute_prev7
from weather import (
    make_wu_session, make_om_session, fetch_wu_latest, fetch_wu_forecast_max,
    fetch_om_forecast_max, fetch_om_hourly_today, forecasts_agree,
)
from phased_entry import SingleEntry
from polymarket_clob import ClobClient, TradingMode
from zoneinfo import ZoneInfo

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
    slots_so_far: list[dict] = field(default_factory=list)
    series_today: dict[tuple, float] = field(default_factory=dict)
    cloud_by_hour: dict[int, int] = field(default_factory=dict)
    history_max: dict = field(default_factory=dict)
    entry: SingleEntry | None = None
    market: dict | None = None
    wu_key: str = ""
    wu_sess = None
    om_sess = None
    clob: ClobClient | None = None
    trading_mode: TradingMode = TradingMode.PAPER
    latest_obs: dict | None = None
    last_forecast_min: int = -1
    last_market_min: int = -1


# ════════════════════════════════════════════════════
#  HELPERS
# ════════════════════════════════════════════════════

def city_now(city: CityConfig) -> datetime:
    return datetime.now(tz=ZoneInfo(city.timezone))


def city_date(city: CityConfig) -> date:
    return city_now(city).date()


def bot_now() -> datetime:
    return datetime.now(tz=ZoneInfo("Europe/Lisbon"))


def ceil_slot(hour: int, minute: int) -> tuple[int, int]:
    """Converte (hour, minute) para slot 30min (truncar para CIMA)."""
    if minute < 30:
        return (hour, 30)
    else:
        return (hour + 1, 0)


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


def _tg_alert(msg: str) -> None:
    """Placeholder para notificações Telegram."""
    print(f"[TG] {msg}")


# ════════════════════════════════════════════════════
#  TICK por cidade
# ════════════════════════════════════════════════════

def _tick_city(state: CityState, trading_mode_str: str, bankroll: float) -> DailyStats:
    """Executa um tick para uma cidade."""
    city = state.city
    now = bot_now()
    city_today = city_date(city)

    stats = DailyStats(date=city_today)
    session_stats = SessionStats(start_time=now)

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

    # Atualizar slots
    if new_obs:
        h_obs, m_obs = new_obs["hour"], new_obs["minute"]
        h_slot, s30 = ceil_slot(h_obs, m_obs)

        if city.day_start <= h_slot <= city.day_end:
            state.series_today[(h_slot, s30)] = new_obs["temp_c"]
            state.cloud_by_hour[h_slot] = new_obs.get("cloud_cover", 50)

            slot_entry = {
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
                for s in state.slots_so_far:
                    if s["hour"] == h_slot and s["slot30"] == s30:
                        s.update(slot_entry)
                        break
            else:
                state.slots_so_far.append(slot_entry)
                state.slots_so_far.sort(key=lambda x: x["hour"] * 60 + x["slot30"])

    from predictor import update_history_max, init_history_max
    update_history_max(state.history_max, state.slots_so_far, city.name)

    # Predição e entrada
    h_now = city_now(city).hour
    m_now = city_now(city).minute
    h_cur, s30_cur = ceil_slot(h_now, m_now)

    p_ensemble = 0.0
    ensemble_result = None

    if len(state.slots_so_far) >= 4:
        current_extra = {
            "hour": h_cur,
            "slot30": s30_cur,
            "temp_c": state.latest_obs["temp_c"] if state.latest_obs else 0,
            "cloud_cover": state.cloud_by_hour.get(h_cur, 50),
            "humidity": state.latest_obs.get("humidity", 70) if state.latest_obs else 70,
            "dewpoint_c": state.latest_obs.get("dewpoint_c", 0) if state.latest_obs else 0,
            "pressure_hpa": state.latest_obs.get("pressure_hpa", 1013) if state.latest_obs else 1013,
            "wind_dir_deg": state.latest_obs.get("wind_dir_deg", 0) if state.latest_obs else 0,
            "wind_speed_kmh": state.latest_obs.get("wind_speed_kmh", 5) if state.latest_obs else 5,
            "wind_gust_kmh": state.latest_obs.get("wind_gust_kmh", 8) if state.latest_obs else 8,
            "uv_index": state.latest_obs.get("uv_index", 3) if state.latest_obs else 3,
            "prev_7d_avg_max": compute_prev7(state.history_max, city_today, city.name),
        }

        ensemble_result = predict_ensemble(
            state.models, state.slots_so_far, current_extra,
            city_today.month, city_today.timetuple().tm_yday
        )
        p_ensemble = ensemble_result["p_ensemble"]

    # Trade decision
    if state.entry and state.market and state.clob:
        if h_cur >= (city.hour_min or 6) and p_ensemble >= (city.threshold or 0.55):
            if not state.entry.bought:
                rmax = max(s["temp_c"] for s in state.slots_so_far)
                bracket = next((b for b in state.market["brackets"]
                               if b["temp_lo"] <= rmax <= b["temp_hi"]), None)
                if bracket:
                    bet = {
                        "city": city.name,
                        "bracket": bracket["label"],
                        "ask": bracket["ask"],
                        "size": PARCEL_SIZE,
                        "time": city_now(city).isoformat(),
                    }

                    if trading_mode_str == "real":
                        state.entry.bought = state.clob.buy_yes(
                            market_slug=f"{city.polymarket_slug_pfx}-{city_today}",
                            ask=bracket["ask"],
                            shares=int(PARCEL_SIZE / bracket["ask"]),
                        )
                        if state.entry.bought:
                            stats.trades.append(bet)
                            stats.total_invested += bet["ask"] * PARCEL_SIZE
                    else:
                        stats.trades.append(bet)
                        stats.total_invested += bet["ask"] * PARCEL_SIZE
                        state.entry.bought = True

                    print(f"  {C['green']}{city.name.upper()} BUY: {bracket['label']} @ {bracket['ask']:.2f} (P={p_ensemble:.2f}){R}")
                    _tg_alert(f"{city.name}: Bought {bracket['label']} @ {bracket['ask']:.2f}")

    # Display simples
    if state.latest_obs:
        rmax = max(s["temp_c"] for s in state.slots_so_far) if state.slots_so_far else state.latest_obs["temp_c"]
        print(f"{C['cyan']}{city.name.upper():<8}{R} "
              f"{h_cur:02d}:{s30_cur:02d} | "
              f"Temp: {state.latest_obs['temp_c']:>5.1f}°C | "
              f"RMax: {rmax:>5.1f}°C | "
              f"P: {p_ensemble:>4.2f} | "
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
                        help="Modo de entrada (apenas single implementado)")
    parser.add_argument("--run", type=str, default="paper", choices=["paper", "real"],
                        help="Modo de execução")
    parser.add_argument("--interval", type=int, default=30,
                        help="Intervalo em segundos entre ticks")
    args = parser.parse_args()

    city_names = [c.strip() for c in args.cities.split(",")]
    trading_mode = TradingMode.REAL if args.run == "real" else TradingMode.PAPER

    print("=" * 60)
    print(f" {B}Live Bot — Multi-Cidade{R}")
    print("=" * 60)
    print(f"  Cidades: {', '.join(city_names)}")
    print(f"  Modo: {args.mode}")
    print(f"  Execução: {args.run.upper()}")
    print(f"  Intervalo: {args.interval}s")
    print()

    # Inicializar estados por cidade
    states = {}
    for city_name in city_names:
        city = get_city(city_name)
        set_city(city_name)
        models = load_models(city_name)

        state = CityState(
            city=city,
            models=models,
            entry=SingleEntry(parcel_size=PARCEL_SIZE),
        )

        # WU API key (de environment)
        import os
        state.wu_key = os.environ.get("WU_API_KEY", "")

        if city.wu_history_path and not state.wu_key:
            print(f"  {C['yellow']}{city.name}: WU_API_KEY não definida, usando apenas OM{R}")

        state.wu_sess = make_wu_session()
        state.om_sess = make_om_session()

        # CLOB (para real)
        if args.run == "real":
            private_key = os.environ.get("POLY_PRIVATE_KEY", "")
            if not private_key:
                print(f"  {C['red']}{city.name}: POLY_PRIVATE_KEY não definida{R}")
            else:
                try:
                    state.clob = ClobClient(
                        private_key=private_key,
                        mode=trading_mode,
                        max_daily_loss=city.max_daily_loss,
                        log_dir=LOG_DIR,
                    )
                    print(f"  {C['green']}{city.name}: CLOB inicializado{R}")
                except Exception as e:
                    print(f"  {C['red']}{city.name}: CLOB init failed: {e}{R}")

        states[city_name] = state

    print()
    print(f"{DIM}Loop iniciado — Ctrl+C para parar{R}")
    print()

    try:
        while True:
            now = bot_now()
            h_now = now.hour

            for city_name in city_names:
                state = states[city_name]
                city = state.city
                city_today = city_date(city)

                # Skip fora do horário ativo
                if not (city.day_start <= h_now <= city.day_end):
                    continue

                try:
                    stats = _tick_city(state, args.run, PARCEL_SIZE * 100)

                except Exception as e:
                    print(f"  {C['red']}{city.name}: Tick failed: {e}{R}")

            # Sleep até próximo tick
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
