"""
munich_live_bot.py
==================
Bot de trading ao vivo — Temperatura Máxima Munich — Polymarket.

Todas as apostas agora são de $5 (single = 1×$5, phased = 3×$5)
"""

import argparse
import json
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import numpy as np
import requests

from munich_config import (
    R, B, DIM, C,
    WU_API_KEY, POLY_PRIVATE_KEY, POLY_MAX_DAILY_LOSS,
    LOG_DIR, GAMMA_API, MONTH_NAMES,
    DAY_START, DAY_END, MIN_HOUR,
    BOT_ACTIVE_START, BOT_ACTIVE_END,
    berlin_now, berlin_date, local_now, ceil_slot,
    smart_sleep,
)
from munich_weather import (
    make_wu_session, make_om_session,
    fetch_wu_latest, fetch_wu_forecast_max,
    fetch_om_forecast_max,
    bootstrap_today, bootstrap_om_today, cloud_from_series,
    forecasts_agree,
    _bootstrap_rows_cache, _bootstrap_obs_min,
)
from munich_model import (
    load_models, predict_ensemble,
    set_seasonal_prior, compute_prev7,
    init_history_max, update_history_max,
)
from munich_phased_entry import PhasedEntry, SingleEntry
from munich_display import display, log_tick
from polymarket_clob import ClobClient, TradingMode
# INTEGRATION: `polymarket_orders` foi consolidado dentro de `polymarket_clob.py`.
# As funções que aqui estavam (OrderExecutor, paper_buy) são agora métodos de
# ClobClient: clob.buy_yes() faz tudo (simula em PAPER, envia em REAL) e
# regista automaticamente a posição em clob.positions.

# Import robusto do tg.py local. Se houver conflito com um pacote `tg` no
# sys.path (ex: TurboGears no PyPI), forçamos a carregar o ficheiro local.
try:
    from tg import TG
    # Sanity check — se o `tg` importado não vier do nosso ficheiro local,
    # avisar e tentar carregar manualmente
    import tg as _tg_module
    _expected_path = Path(__file__).parent / "tg.py"
    if not str(_tg_module.__file__).startswith(str(Path(__file__).parent)):
        raise ImportError(
            f"módulo 'tg' importado de {_tg_module.__file__} (esperado: {_expected_path})"
        )
except ImportError as _e:
    # Fallback: carregar tg.py explicitamente do mesmo directório
    import importlib.util
    _tg_path = Path(__file__).parent / "tg.py"
    if not _tg_path.exists():
        raise FileNotFoundError(
            f"\n  tg.py não encontrado em {_tg_path}\n"
            f"  Garante que o ficheiro está na mesma pasta que munich_live_bot.py.\n"
            f"  Erro original: {_e}"
        )
    _spec = importlib.util.spec_from_file_location("tg", _tg_path)
    _tg_module = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_tg_module)
    TG = _tg_module.TG
    print(f"  [tg] carregado manualmente de {_tg_path}")


PARCEL_SIZE = 5.0   # Todas as apostas são de $5


# ══════════════════════════════════════════════════════
#  DATACLASSES
# ══════════════════════════════════════════════════════

@dataclass
class DailyStats:
    date:                    date
    trades:                  list = field(default_factory=list)
    total_invested:          float = 0.0
    daily_pnl:               float = 0.0
    stop_losses_triggered:   int   = 0
    max_concurrent_positions:int   = 0


@dataclass
class SessionStats:
    start_time:   datetime
    total_trades: int   = 0
    total_pnl:    float = 0.0
    wins:         int   = 0
    losses:       int   = 0

    @property
    def win_rate(self) -> float:
        return (self.wins / self.total_trades * 100) if self.total_trades > 0 else 0.0

    @property
    def duration(self):
        return datetime.now() - self.start_time


# ══════════════════════════════════════════════════════
#  POLYMARKET FETCHER
# ══════════════════════════════════════════════════════

class PolymarketFetcher:
    def __init__(self, api_url: str = GAMMA_API):
        self.api_url = api_url

    def date_to_slug(self, d: date) -> str:
        return f"highest-temperature-in-munich-on-{MONTH_NAMES[d.month]}-{d.day}-{d.year}"

    def fetch_market(self, d: date) -> Optional[dict]:
        import re as _re
        slug = self.date_to_slug(d)

        def _try(params):
            try:
                r = requests.get(f"{self.api_url}/events", params=params, timeout=15)
                r.raise_for_status()
                ev = r.json()
                return ev if isinstance(ev, list) else ([ev] if ev else [])
            except Exception:
                return []

        month_s = MONTH_NAMES[d.month].capitalize()
        events = (
            _try({"slug": slug}) or
            _try({"q": f"highest temperature Munich {month_s} {d.day} {d.year}", "limit": 10}) or
            _try({"q": f"Munich temperature {d.year}", "limit": 10})
        )
        if not events:
            return None

        def is_munich(e):
            t = str(e.get("title", "")).lower()
            return (("munich" in t or "munchen" in t) and ("temp" in t or "temperature" in t or "highest" in t))

        munich = [e for e in events if isinstance(e, dict) and is_munich(e)]
        if not munich:
            munich = [e for e in events if isinstance(e, dict)]
        if not munich:
            return None

        event = max(munich, key=lambda e: float(e.get("volume", 0) or 0))
        brackets = []

        for m in event.get("markets", []):
            raw_label = (m.get("groupItemTitle") or m.get("outcomeTitle") or m.get("title") or m.get("question") or "")
            label = self._normalize_label(raw_label)
            v = self._extract_temp(label)
            if v is None:
                continue

            def _jload(x):
                if isinstance(x, str):
                    try: return json.loads(x)
                    except: return []
                return x

            outcomes = _jload(m.get("outcomes", "[]"))
            prices = _jload(m.get("outcomePrices", "[]"))
            token_ids = _jload(m.get("clobTokenIds", "[]"))

            price_yes, token_yes = None, None
            for i, out in enumerate(outcomes):
                if str(out).lower() in ("yes", "true", "1"):
                    price_yes = float(prices[i]) if i < len(prices) and prices[i] else None
                    token_yes = token_ids[i] if i < len(token_ids) else None
                    break
            if price_yes is None and prices:
                try: price_yes = float(prices[0])
                except: price_yes = 0.5
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
            "title": event.get("title", "Munich Max Temp"),
            "end_date": event.get("endDate", ""),
            "volume": float(event.get("volume", 0) or 0),
            "brackets": brackets,
            "n_outcomes": len(brackets),
            "slug": slug,
        }

    def _extract_temp(self, text: str) -> Optional[float]:
        import re
        for pat in [r"([-]?\d+)\s*°?\s*[cC]\b", r"([-]?\d+)\s+or\s+(?:higher|lower|above|below)",
                    r"be\s+([-]?\d+)", r"^\s*([-]?\d+)\s*$"]:
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
        return 99.0 if any(x in s for x in ("or higher", "or above", ">=")) else v

    def _normalize_label(self, text: str) -> str:
        if len(text) <= 25:
            return text
        v = self._extract_temp(text)
        if v is None:
            return text
        s = text.lower()
        if any(x in s for x in ("higher", "above", ">=", "≥")):
            return f"{v:.0f}°C or higher"
        if any(x in s for x in ("lower", "below", "<=", "≤")):
            return f"{v:.0f}°C or lower"
        return f"{v:.0f}°C"

    @staticmethod
    def find_bracket(market: dict, temp: float, forecast_max: float = None) -> Optional[dict]:
        if not market:
            return None
        if forecast_max is not None:
            target = int(round(forecast_max))
        else:
            target = int(np.floor(temp))
        for b in market["brackets"]:
            lo, hi = b["temp_lo"], b["temp_hi"]
            if lo == hi and target == round(lo): return b
            if hi >= 99 and target >= lo: return b
            if lo <= -99 and target <= hi: return b
            if lo <= temp <= hi: return b
        return min(market["brackets"], key=lambda b: abs(target - (
            b["temp_lo"] if b["temp_hi"] >= 99 else
            b["temp_hi"] if b["temp_lo"] <= -99 else
            (b["temp_lo"] + b["temp_hi"]) / 2
        )))


# ══════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════

# Nota: a função smart_sleep é agora importada de munich_config (ver topo
# deste ficheiro). A versão que aqui estava era um workaround temporário;
# a nova versão em munich_config faz polling ativo à WU nas janelas EDDM
# e detecta novas observações em tempo real.


def compute_ev(p: float, ask: float) -> Optional[dict]:
    if not ask or not (0 < ask < 1) or ask >= 0.95:
        return None
    ev = p - ask
    b = (1 - ask) / ask
    kelly = max(0.0, (p * b - (1 - p)) / b)
    return {
        "ev": round(ev, 4),
        "ev_cents": round(ev * 100, 2),
        "kelly": round(kelly, 4),
        "edge_pct": round((p / ask - 1) * 100, 2),
        "ev_positive": ev > 0,
        "ask": round(ask, 4),
    }


def get_real_usdc_balance(private_key: str) -> Optional[float]:
    try:
        from py_clob_client.client import ClobClient as _CC
        from py_clob_client.clob_types import BalanceAllowanceParams, AssetType
        _c = _CC(host="https://clob.polymarket.com", key=private_key, chain_id=137)
        _c.set_api_creds(_c.create_or_derive_api_creds())
        best = 0.0
        for sig in [0, 1, 2]:
            try:
                info = _c.get_balance_allowance(params=BalanceAllowanceParams(
                    asset_type=AssetType.COLLATERAL, signature_type=sig))
                bal = int(info.get("balance", "0")) / 1e6
                if bal > best:
                    best = bal
            except Exception:
                pass
        return best
    except Exception:
        return None


def _save_daily_stats(stats: DailyStats) -> None:
    LOG_DIR.mkdir(exist_ok=True)
    path = LOG_DIR / f"daily_{stats.date.isoformat()}.json"
    data = {
        "date": stats.date.isoformat(),
        "trades": len(stats.trades),
        "total_invested": stats.total_invested,
        "daily_pnl": stats.daily_pnl,
        "stop_losses_triggered": stats.stop_losses_triggered,
        "max_concurrent_positions": stats.max_concurrent_positions,
    }
    path.write_text(json.dumps(data, indent=2))


def ask_trading_mode() -> TradingMode:
    print(f"\n  {B}{C['cyan']}── Munich Live Bot — Modo ──────────{R}")
    print(f"  {C['yellow']}[P]{R} PAPER")
    print(f"  {C['red']}[R]{R} REAL")
    while True:
        ans = input(f"  Modo? {C['yellow']}[P]{R}aper / {C['red']}[R]{R}eal : ").strip().lower()
        if ans in ("p", "paper", ""):
            print(f"\n  {C['yellow']}{B}PAPER seleccionado{R}\n")
            return TradingMode.PAPER
        if ans in ("r", "real"):
            if not POLY_PRIVATE_KEY:
                print(f"  {C['red']}POLY_PRIVATE_KEY não definida{R}")
                continue
            confirm = input(f"  Escreve {C['red']}REAL{R} para confirmar: ").strip()
            if confirm == "REAL":
                print(f"\n  {C['red']}{B}REAL activado{R}\n")
                return TradingMode.REAL
            print("  Confirmação inválida — a usar PAPER\n")
            return TradingMode.PAPER
        print("  Opção inválida.")


def confirm_real_order(bet: dict) -> bool:
    print(f"\n  {C['red']}{B}⚠  CONFIRMAR ORDEM REAL ⚠{R}")
    print(f"    Bracket : {bet['bracket']}  Ask: {bet['ask']*100:.1f}¢")
    print(f"    Aposta  : ${bet['bet_size']:.2f}  Parcela: P{bet.get('parcel_idx', 0)+1}")
    ans = input("  Enviar? (y/n): ").strip().lower()
    return ans == "y"


# ══════════════════════════════════════════════════════
#  MAIN LOOP
# ══════════════════════════════════════════════════════

def run(wu_key: str, bankroll: float, interval: int,
        headless: bool = False, mode: str = "single",
        force_trading_mode: Optional[str] = None) -> None:

    LOG_DIR.mkdir(exist_ok=True)

    if not wu_key:
        raise ValueError(f"\n  {C['red']}WU_API_KEY não definida{R}")

    if force_trading_mode == "real":
        trading_mode = TradingMode.REAL
    elif force_trading_mode == "paper":
        trading_mode = TradingMode.PAPER
    elif headless:
        trading_mode = TradingMode.REAL if POLY_PRIVATE_KEY else TradingMode.PAPER
    else:
        trading_mode = ask_trading_mode()

    clob_mode_str = "real" if trading_mode == TradingMode.REAL else "paper"

    tg = TG()
    fetcher = PolymarketFetcher()
    wu_sess = make_wu_session()
    om_sess = make_om_session()

    clob = None
    if POLY_PRIVATE_KEY:
        try:
            clob = ClobClient(private_key=POLY_PRIVATE_KEY, mode=trading_mode,
                              max_daily_loss=POLY_MAX_DAILY_LOSS, log_dir=LOG_DIR)
        except Exception as e:
            print(f"  {C['red']}CLOB init falhou: {e}{R}")

    print("[1/4] A carregar modelos...")
    models = load_models()
    set_seasonal_prior(models["prior_map"])

    _last_forecast_min = -1
    _last_market_min = -1

    today = berlin_date()
    print(f"\n[2/4] Bootstrap — {today}...")
    try:
        _s, _sl = bootstrap_today(wu_key, wu_sess)
        if len(_sl) < 4:
            print(f"  {C['yellow']}WU com poucos dados, fallback OM{R}")
            _s, _sl = bootstrap_om_today(om_sess)
        series_today = _s
        slots_so_far = _sl
    except Exception as e:
        print(f"  {C['yellow']}WU falhou, usando OM: {e}{R}")
        _s, _sl = bootstrap_om_today(om_sess)
        series_today = _s
        slots_so_far = _sl

    import munich_weather as _mw
    obs_min_today = dict(_mw._bootstrap_obs_min)
    rows_cache = list(_mw._bootstrap_rows_cache)

    # cloud_from_series(series_today, rows_cache) — primeiro arg é unused na
    # implementação actual mas a assinatura exige-o. Passamos slots_so_far.
    cloud_by_hour = cloud_from_series(slots_so_far, rows_cache)
    temps_by_hour = {s["hour"]: s["temp_c"] for s in slots_so_far}
    history_max = init_history_max()
    update_history_max(history_max, slots_so_far)

    # Decisão 2026-04: LightGBM puro (sem z-score). Não criamos detector.

    if mode == "single":
        entry = SingleEntry(parcel_size=PARCEL_SIZE)   # defaults: thr=0.68, hour_min=15h
        mode_label = (f"SINGLE 1×${PARCEL_SIZE}  "
                      f"threshold={entry.threshold*100:.0f}%  "
                      f"hour_min={entry.hour_min}h")
    else:
        entry = PhasedEntry(parcel_size=PARCEL_SIZE)
        mode_label = f"PHASED 3×${PARCEL_SIZE}"
    print(f"  Entry mode: {mode_label}")

    wu_forecast = fetch_wu_forecast_max(wu_key, wu_sess)
    om_forecast = fetch_om_forecast_max(om_sess)
    forecast_agreement = forecasts_agree(wu_forecast, om_forecast)

    print(f"\n[3/4] A aplicar modelo ao histórico...")
    month = today.month
    doy = today.timetuple().tm_yday
    signals = {}

    for i, slot in enumerate(slots_so_far):
        h, s = slot["hour"], slot["slot30"]
        if h < MIN_HOUR or i < 3:
            continue
        current_extra = {
            "hour": h, "slot30": s, "temp_c": slot["temp_c"],
            "cloud_cover": slot.get("cloud_cover", 50),
            "humidity": slot.get("humidity", 70),
            "dewpoint_c": slot.get("dewpoint_c", slot["temp_c"] - 10),
            "pressure_hpa": slot.get("pressure_hpa", 1013),
            "wind_dir_deg": slot.get("wind_dir_deg", 0),
            "wind_speed_kmh": slot.get("wind_speed_kmh", 5),
            "wind_gust_kmh": slot.get("wind_gust_kmh", 8),
            "uv_index": slot.get("uv_index", 3),
            "prev_7d_avg_max": compute_prev7(history_max, today),
        }
        ens = predict_ensemble(models, slots_so_far[:i+1], current_extra, month, doy, None)
        signals[(h, s)] = ens["p_ensemble"]

    print(f"\n[4/4] A carregar mercado...")
    market = fetcher.fetch_market(today)
    if market and clob:
        market["brackets"] = [clob.enrich_bracket(b) for b in market["brackets"]]

    usdc_balance = get_real_usdc_balance(POLY_PRIVATE_KEY) if trading_mode == TradingMode.REAL else None
    # INTEGRATION: open_orders vem agora do PositionManager do próprio clob.
    open_orders = clob.positions.open_positions() if clob else None

    log_path = LOG_DIR / f"live_{today}.csv"
    bets_path = LOG_DIR / f"bets_{today}.json"
    bets = []

    daily_stats = DailyStats(date=today)
    session_stats = SessionStats(start_time=datetime.now())

    # Passar threshold e hour_min reais do entry (em vez de 0.80 hardcoded)
    _thr = getattr(entry, 'threshold', 0.80)
    _hmin = getattr(entry, 'hour_min', None)
    tg.alert_started(clob_mode_str, bankroll, _thr, _thr, month, market, today,
                     hour_min=_hmin)
    if not market:
        tg.alert_no_market(today)

    latest_obs = None
    if slots_so_far:
        last = slots_so_far[-1]
        latest_obs = {"temp_c": last["temp_c"], "humidity": last.get("humidity", 70),
                      "cloud_cover": last.get("cloud_cover", 50), "wx": "", "hour": last["hour"], "minute": last["slot30"]}

    _tg_last_dashboard = 0
    _tg_dashboard_interval = 30 * 60

    print(f"\n  {DIM}Loop iniciado — Ctrl+C para parar{R}\n")

    def _handle_new_day(new_date: date):
        nonlocal today, month, doy, series_today, slots_so_far, obs_min_today, rows_cache
        nonlocal cloud_by_hour, temps_by_hour, signals, market, log_path, bets_path, bets
        nonlocal latest_obs, wu_forecast, om_forecast, forecast_agreement, daily_stats

        _save_daily_stats(daily_stats)

        today = new_date
        month = today.month
        doy = today.timetuple().tm_yday
        series_today = {}
        slots_so_far = []
        obs_min_today = {}
        rows_cache = []
        cloud_by_hour = {}
        temps_by_hour = {}
        signals = {}
        bets = []
        latest_obs = None
        daily_stats = DailyStats(date=today)
        entry.reset()
        latest_obs = None

        # INTEGRATION: reset do daily loss é feito automaticamente dentro
        # do ClobClient (via _reset_daily_if_needed quando muda a data).
        # Não precisamos de chamada explícita aqui.

        log_path = LOG_DIR / f"live_{today}.csv"
        bets_path = LOG_DIR / f"bets_{today}.json"

        market = fetcher.fetch_market(today)
        if market and clob:
            market["brackets"] = [clob.enrich_bracket(b) for b in market["brackets"]]

        try:
            _s, _sl = bootstrap_today(wu_key, wu_sess)
            if len(_sl) < 4:
                _s, _sl = bootstrap_om_today(om_sess)
            series_today = _s
            slots_so_far = _sl
            import munich_weather as _mw2
            obs_min_today = dict(_mw2._bootstrap_obs_min)
            rows_cache = list(_mw2._bootstrap_rows_cache)
            cloud_by_hour = cloud_from_series(series_today, rows_cache)
            temps_by_hour = {s["hour"]: s["temp_c"] for s in slots_so_far}
        except Exception as e:
            print(f"  {C['yellow']}Bootstrap falhou: {e}{R}")

        update_history_max(history_max, slots_so_far)

        wu_forecast = fetch_wu_forecast_max(wu_key, wu_sess)
        om_forecast = fetch_om_forecast_max(om_sess)
        forecast_agreement = forecasts_agree(wu_forecast, om_forecast)

        tg.alert_started(clob_mode_str, bankroll, _thr, _thr, month, market, today,
                         hour_min=_hmin)

    try:
        while True:
            now = local_now()

            station_date = berlin_date()
            if station_date != today:
                _handle_new_day(station_date)

            _berlin_h = berlin_now().hour
            if _berlin_h < BOT_ACTIVE_START or _berlin_h >= BOT_ACTIVE_END:
                time.sleep(300)
                continue

            new_obs = fetch_wu_latest(wu_key, wu_sess)
            if new_obs:
                latest_obs = new_obs
                h_obs, m_obs = new_obs["hour"], new_obs["minute"]
                h_slot, s30 = ceil_slot(h_obs, m_obs)

                if DAY_START <= h_slot <= DAY_END:
                    series_today[(h_slot, s30)] = new_obs["temp_c"]
                    obs_min_today[(h_slot, s30)] = (h_obs, m_obs)
                    slot_entry = {
                        "hour": h_slot, "slot30": s30, "temp_c": new_obs["temp_c"],
                        "cloud_cover": new_obs.get("cloud_cover", 50),
                        "humidity": new_obs.get("humidity", 70),
                        "dewpoint_c": new_obs.get("dewpoint_c", new_obs["temp_c"] - 10),
                        "pressure_hpa": new_obs.get("pressure_hpa", 1013),
                        "wind_dir_deg": new_obs.get("wind_dir_deg", 0),
                        "wind_speed_kmh": new_obs.get("wind_speed_kmh", 5),
                        "wind_gust_kmh": new_obs.get("wind_gust_kmh", 8),
                        "uv_index": new_obs.get("uv_index", 3),
                    }
                    exists = any(sl["hour"] == h_slot and sl["slot30"] == s30 for sl in slots_so_far)
                    if exists:
                        for sl in slots_so_far:
                            if sl["hour"] == h_slot and sl["slot30"] == s30:
                                sl.update(slot_entry)
                                break
                    else:
                        slots_so_far.append(slot_entry)
                        slots_so_far.sort(key=lambda x: x["hour"] * 60 + x["slot30"])

                cloud_by_hour[h_slot] = new_obs.get("cloud_cover", 50)

            update_history_max(history_max, slots_so_far)

            h_now = berlin_now().hour
            m_now = berlin_now().minute
            h_cur, s30_cur = ceil_slot(h_now, m_now)

            p = 0.0
            ensemble_result = None

            if len(slots_so_far) >= 4 and h_cur >= MIN_HOUR:
                current_extra = {
                    "hour": h_cur, "slot30": s30_cur,
                    "temp_c": latest_obs["temp_c"] if latest_obs else 0,
                    "cloud_cover": cloud_by_hour.get(h_cur, 50.0),
                    "humidity": latest_obs.get("humidity", 70) if latest_obs else 70,
                    "dewpoint_c": latest_obs.get("dewpoint_c", (latest_obs["temp_c"] - 10) if latest_obs else 10),
                    "pressure_hpa": latest_obs.get("pressure_hpa", 1013) if latest_obs else 1013,
                    "wind_dir_deg": latest_obs.get("wind_dir_deg", 0) if latest_obs else 0,
                    "wind_speed_kmh": latest_obs.get("wind_speed_kmh", 5) if latest_obs else 5,
                    "wind_gust_kmh": latest_obs.get("wind_gust_kmh", 8) if latest_obs else 8,
                    "uv_index": latest_obs.get("uv_index", 3) if latest_obs else 3,
                    "prev_7d_avg_max": compute_prev7(history_max, today),
                }
                ensemble_result = predict_ensemble(models, slots_so_far, current_extra, month, doy, None)
                p = ensemble_result["p_ensemble"]
                signals[(h_cur, s30_cur)] = p

            if now.minute != _last_forecast_min and now.minute % 30 == 0:
                _last_forecast_min = now.minute
                wu_forecast = fetch_wu_forecast_max(wu_key, wu_sess)
                om_forecast = fetch_om_forecast_max(om_sess)
                forecast_agreement = forecasts_agree(wu_forecast, om_forecast)

            if now.minute != _last_market_min and (now.minute % 10 == 0 or not market):
                _last_market_min = now.minute
                market = fetcher.fetch_market(today)
                if market and clob:
                    market["brackets"] = [clob.enrich_bracket(b) for b in market["brackets"]]
                # INTEGRATION: open positions vêm do PositionManager, e fazemos
                # também um refresh() para actualizar mid/pnl/status em REAL.
                if clob:
                    try:
                        clob.positions.refresh(clob)
                    except Exception:
                        pass
                    open_orders = clob.positions.open_positions()
                    # Verificar se posições de dias anteriores foram resolvidas
                    if trading_mode == TradingMode.REAL:
                        try:
                            clob.positions.resolve_closed_positions(today)
                        except Exception:
                            pass

            if series_today:
                rmax_slot = max(series_today, key=series_today.get)
                rmax = series_today[rmax_slot]
                rmax_real_ts = obs_min_today.get(rmax_slot)
                rmax_time_str = f"{rmax_real_ts[0]}:{rmax_real_ts[1]:02d}" if rmax_real_ts else f"{rmax_slot[0]}h"
            elif temps_by_hour:
                rmax = max(temps_by_hour.values())
                rmax_time_str = f"{max(temps_by_hour, key=temps_by_hour.get)}h"
            else:
                rmax, rmax_time_str = 0, "?"

            actions = entry.evaluate(p, h_cur, market, rmax, forecast_agreement)

            # ─── STOP-LOSS CHECK (só SINGLE) ───────────────────────
            # Verificar em cada tick se temp subiu >= bracket_hi + delta.
            # Se sim, vender ao bid corrente para recuperar capital.
            if mode == "single" and hasattr(entry, "check_stop_loss") and latest_obs:
                current_temp = latest_obs["temp_c"]
                stop_signal = entry.check_stop_loss(current_temp)
                if stop_signal and clob and market:
                    pos = stop_signal["position"]
                    # Encontrar bracket correspondente no mercado actual
                    matching = [b for b in market.get("brackets", [])
                                if b.get("temp_lo") == pos.get("temp_lo")
                                and b.get("temp_hi") == pos.get("temp_hi")]
                    if matching:
                        bracket = matching[0]
                        bid_price = bracket.get("bid")

                        # Criar Position sintética para sell_yes (baseado no bet_record)
                        # Só vendemos se temos bid razoável
                        if bid_price and bid_price >= 0.02:
                            from polymarket_clob import Position, PositionStatus
                            from datetime import datetime as _dt

                            # Procurar posição no PositionManager do clob
                            poll = [p for p in clob.positions.open_positions()
                                    if p.token_id == pos.get("token_id")]
                            if poll:
                                sell_result = clob.sell_yes(poll[0], bid_price)
                                if sell_result.success:
                                    # Calcular PnL realizado
                                    entry_ask = pos.get("ask", 0)
                                    shares = pos.get("size_usdc", 0) / entry_ask if entry_ask > 0 else 0
                                    realized_pnl = shares * bid_price - pos.get("size_usdc", 0)

                                    entry.mark_sold_by_stop(bid_price, realized_pnl)
                                    session_stats.stop_losses_triggered += 1
                                    daily_stats.stop_losses_triggered += 1
                                    if realized_pnl >= 0:
                                        session_stats.wins += 1
                                    else:
                                        session_stats.losses += 1

                                    print(f"\n  {C['yellow']}⚠  {stop_signal['reason']}{R}")
                                    print(f"  {C['yellow']}   Vendido @ {bid_price:.4f}, PnL={realized_pnl:+.2f}{R}")

                                    try:
                                        tg.alert_stop_loss_triggered(
                                            position=pos,
                                            current_temp=current_temp,
                                            bid_price=bid_price,
                                            realized_pnl=realized_pnl,
                                        )
                                    except Exception:
                                        pass
            # ───────────────────────────────────────────────────────

            bet = None
            bet_blocked_reason = None
            target_bracket = None
            ev = None

            for action in actions:
                if action["size_usdc"] <= 0:
                    bet_blocked_reason = action["reason"]
                    continue

                pidx = action["parcel_idx"]

                if pidx == 0 and market:
                    rmax_int = int(round(rmax))
                    wu_max = wu_forecast.get("temp_max") if wu_forecast else rmax_int + 2
                    target_temp = max(rmax_int, wu_max)
                    target_bracket = PolymarketFetcher.find_bracket(market, target_temp, wu_forecast.get("temp_max") if wu_forecast else None)
                    if not target_bracket or target_bracket.get("temp_hi", 0) < target_temp:
                        target_bracket = next((b for b in market["brackets"] if b["temp_hi"] >= 99 and b["temp_lo"] <= target_temp),
                                              max(market["brackets"], key=lambda b: b.get("ask") or 0))
                elif pidx == 1 and market:
                    valid_brackets = [b for b in market["brackets"] if b["temp_lo"] > -99]
                    target_bracket = max(valid_brackets, key=lambda b: b.get("ask") or b.get("price") or 0) if valid_brackets else PolymarketFetcher.find_bracket(market, rmax)
                elif market:
                    target_bracket = PolymarketFetcher.find_bracket(market, rmax)
                else:
                    bet_blocked_reason = "sem mercado"
                    continue

                if not target_bracket:
                    bet_blocked_reason = f"P{pidx+1}: sem bracket"
                    continue

                ask_price = target_bracket.get("ask") or target_bracket.get("price")
                if not ask_price:
                    bet_blocked_reason = f"P{pidx+1}: sem ask"
                    continue

                ev = compute_ev(p, ask_price)

                bet_record = {
                    "parcel_idx": pidx,
                    "mode": trading_mode.value,
                    "bracket": target_bracket["label"],
                    "token_id": target_bracket.get("token_id"),
                    "ask": round(ask_price, 4),
                    "p_true": round(p, 3),
                    "ev_cents": ev["ev_cents"] if ev else None,
                    "bet_size": action["size_usdc"],
                    "shares": round(action["size_usdc"] / ask_price, 2),
                    "reason": action["reason"],
                    "timestamp": datetime.now().isoformat(),
                }

                # INTEGRATION: uma única chamada clob.buy_yes() trata de tudo:
                # - em PAPER simula e regista a posição em clob.positions
                # - em REAL assina + submete a ordem, e regista se aceite
                # - respeita o stop-loss diário automaticamente
                # Não precisa mais de OrderExecutor/paper_buy.
                if clob is None:
                    bet_blocked_reason = "CLOB não inicializado (POLY_PRIVATE_KEY em falta?)"
                    continue

                proceed = True
                if trading_mode == TradingMode.REAL and not headless:
                    proceed = confirm_real_order(bet_record)

                if not proceed:
                    continue

                result = clob.buy_yes(
                    token_id      = target_bracket.get("token_id", ""),
                    price         = ask_price,
                    size_usdc     = action["size_usdc"],
                    bracket_label = f"P{pidx+1}: {target_bracket['label']}",
                    market_slug   = (market or {}).get("slug", ""),
                    temp_lo       = target_bracket.get("temp_lo", 0.0),
                    temp_hi       = target_bracket.get("temp_hi", 0.0),
                )

                if result.success:
                    bet_record["order_id"] = result.order_id
                    bet_record["status"] = result.status
                    bet = bet_record
                    entry.mark_bought(pidx, bet_record)
                    bets.append(bet)
                    bets_path.write_text(json.dumps(bets, indent=2, default=str))
                    daily_stats.trades.append(bet_record)
                    daily_stats.total_invested += action["size_usdc"]
                    session_stats.total_trades += 1
                else:
                    bet_blocked_reason = f"Ordem rejeitada: {result.error or result.status}"

                if bet:
                    if entry.n_parcels_bought == 1 and mode == "phased":
                        tg.alert_order_placed(bet, clob_mode_str)
                    elif entry.n_parcels_bought == 1 and mode == "single":
                        tg.alert_peak_detected(p_ensemble=p, rmax=rmax, rmax_time=rmax_time_str,
                                               bracket=target_bracket, ensemble_result=ensemble_result, market=market)
                    else:
                        tg.alert_order_placed(bet, clob_mode_str)
                elif bet_blocked_reason:
                    tg.alert_bet_blocked(bet_blocked_reason, p)

                break

            # Display
            signals_by_hour = {}
            for (sh, ss), sp in signals.items():
                if sh not in signals_by_hour or sp > signals_by_hour[sh]:
                    signals_by_hour[sh] = sp

            temp_now = latest_obs["temp_c"] if latest_obs else 0

            display(
                now, latest_obs, temps_by_hour, series_today, signals_by_hour, p,
                market, target_bracket, ev, bet, len(series_today), bankroll,
                getattr(entry, "threshold", 0.80),    # threshold real do entry
                entry.n_parcels_bought > 0, trading_mode=trading_mode,
                daily_loss=clob.daily_loss() if clob else 0.0,
                max_daily_loss=POLY_MAX_DAILY_LOSS, usdc_balance=usdc_balance,
                positions=clob.positions if clob else None,
                bet_blocked_reason=bet_blocked_reason, bet_placed=entry.n_parcels_bought > 0,
                forecast_max=wu_forecast, berlin_now_dt=berlin_now(), market_date=today,
                executor=None, open_orders=open_orders, obs_min_today=obs_min_today,
                phased=entry, forecast_agreement=forecast_agreement, om_forecast=om_forecast,
                ensemble_result=ensemble_result, show_dual_forecast=(mode == "phased"),
            )

            log_tick(now, temp_now, p, entry.n_parcels_bought > 0, target_bracket, ev, bet, log_path,
                     trading_mode=trading_mode, bet_blocked_reason=bet_blocked_reason if not bet else None)

            if time.time() - _tg_last_dashboard >= _tg_dashboard_interval:
                _tg_last_dashboard = time.time()
                tg.dashboard(today=today, p=p, rmax=rmax, rmax_time=rmax_time_str, temp_now=temp_now,
                             forecast_max=wu_forecast, market=market, bracket=target_bracket, ev=ev,
                             peak_detected=entry.n_parcels_bought > 0, bet=bets[-1] if bets else None,
                             clob_mode=clob_mode_str, om_forecast=om_forecast,
                             forecast_agreement=forecast_agreement, ensemble_result=ensemble_result,
                             positions_summary=(clob.positions.pnl_summary() if clob else None))

            # Nota: o guard `_berlin_h < BOT_ACTIVE_START or _berlin_h >= BOT_ACTIVE_END`
            # na zona de topo do loop (ver acima) já garante que aqui estamos sempre
            # dentro do horário ativo (8h-19h). Logo o antigo teste `_berlin_h >= DAY_END`
            # (21h) era código morto.
            smart_sleep(interval, wu_key, wu_sess, latest_obs["temp_c"] if latest_obs else None)

    except KeyboardInterrupt:
        print(f"\n\n  {DIM}Parado. Logs em ./{LOG_DIR}/{R}")
        _save_daily_stats(daily_stats)
        print(f"\n  {B}Sessão:{R} trades={session_stats.total_trades} win_rate={session_stats.win_rate:.1f}% "
              f"pnl=${session_stats.total_pnl:+.2f}")
        tg.alert_stopped(bets, clob_mode_str)


def main() -> None:
    parser = argparse.ArgumentParser(description="Munich Max Temp — Live Bot")
    parser.add_argument("--bankroll", type=float, default=200.0)
    parser.add_argument("--interval", type=int, default=60)
    parser.add_argument("--yes", "-y", action="store_true")
    parser.add_argument("--mode", choices=["phased", "single"], default="single")
    parser.add_argument("--run", choices=["paper", "real"], default=None)
    args = parser.parse_args()

    run(
        wu_key=WU_API_KEY,
        bankroll=args.bankroll,
        interval=args.interval,
        headless=args.yes,
        mode=args.mode,
        force_trading_mode=args.run,
    )


if __name__ == "__main__":
    main()