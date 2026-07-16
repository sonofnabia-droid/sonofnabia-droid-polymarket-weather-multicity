"""
tick_logger.py
==============
Logger de telemetria para o live_bot.py.

Regista 3 tipos de eventos em live_bot_logs/ticks/:

1. TICK records (1 por tick, por cidade)
   Ficheiro: ticks_{city}_{date}.jsonl
   Schema:
     {
       "ts":                "2026-06-18T17:42:13+01:00",  # ISO timestamp
       "city":              "munich",
       "date":              "2026-06-18",
       "city_local_hhmm":   "18:42",                       # hora local cidade
       "tick_count":        127,                           # nº do tick desde arranque
       "temp_now":          29.5,                          # temp actual °C
       "running_max":       30.2,                          # max do dia até agora
       "running_max_hour":  15,                            # hora do pico
       "slots_count":       23,                            # nº de slots observados
       "p_ensemble":        0.683,                         # P(pico) LightGBM
       "p_lgbm":            0.683,                         # alias
       "threshold":         0.65,                          # threshold activo
       "hour_min":          11,                            # hora mínima de entrada
       "bought":            false,                         # já comprou hoje?
       "stop_loss_hit":     false,                         # stop-loss disparou?
       "forecast_wu":       27,                            # forecast WU (°C) ou null
       "forecast_om":       null,                          # forecast OM (null se não usado)
       "target_bracket":    {                              # bracket alvo
         "label":           "30.0°C",
         "ask":             0.45,
         "bid":             0.40,
         "token_id":        "0x...",
         "temp_lo":         29.5,
         "temp_hi":         30.5
       },
       "market_top":        [                              # top 6 brackets do mercado
         {"label":"28°C","ask":0.05,"bid":0.03},
         {"label":"29°C","ask":0.10,"bid":0.08},
         {"label":"30°C","ask":0.45,"bid":0.40},
         {"label":"31°C","ask":0.30,"bid":0.25},
         {"label":"32°C","ask":0.08,"bid":0.05},
         {"label":"33°C","ask":0.02,"bid":0.01}
       ],
       "market_volume":     15420.5,
       "market_n_outcomes": 9,
       "race_active":       false,                         # race mode disparou neste tick?
       "race_threshold":    null,                          # se race activo, threshold usado
       "eod_active":        false,                         # EOD fallback disparou?
       "actions":           [],                            # lista de actions devolvidas por evaluate()
       "errors":            []                             # lista de warnings/erros não fatais
     }

2. BET records (1 por buy/sell/stop)  — suplemento ao bets_{city}_{date}.json
   Ficheiro: bets_{city}_{date}.jsonl
   Schema: igual ao bet_record do live_bot + extras:
     {
       ...bet_record original...,
       "ts":               "...",
       "tick_count":       127,
       "p_ensemble_at_buy": 0.683,
       "market_volume_at_buy": 15420.5,
       "trigger":          "normal" | "race" | "eod_fallback",
       "race_rank":        1,        # se trigger=race
       "race_total":       2         # se trigger=race
     }

3. OUTCOME records (1 por dia, por cidade) — gerado em EOD
   Ficheiro: outcomes_{city}_{date}.jsonl
   Schema:
     {
       "ts":               "2026-06-18T22:00:00+01:00",
       "city":             "munich",
       "date":             "2026-06-18",
       "temp_max_actual":  30.5,      # max do dia (WU/PWS)
       "temp_max_hour":    15,
       "bracket_resolved": "30.0°C",  # label do bracket vencedor
       "n_ticks":          1247,      # total ticks registados
       "n_buys":           2,
       "n_sells":          0,
       "n_stops":          0,
       "bought":           true,
       "win":              true,      # ganhou a aposta?
       "pnl_total":        12.50,     # P&L total do dia ($)
       "invested":         10.00,
       "p_ensemble_max":   0.78,      # pico de confiança do modelo
       "p_ensemble_at_buy":0.68,      # confiança no momento da compra
       "p_ensemble_at_peak_temp": 0.72,  # confiança quando temp_max foi atingida
       "race_used":        false,     # race mode foi usado?
       "eod_used":         false,     # EOD fallback foi usado?
       "errors_count":     0          # nº de ticks com erro
     }

Uso (no live_bot.py):
    from tick_logger import TickLogger
    logger = TickLogger()
    logger.log_tick(state, tick_count=127, race_active=False, ...)
    logger.log_bet(bet_record, trigger="normal", tick_count=127)
    logger.log_outcome(state, temp_max_actual=30.5, ...)
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo


# Diretório de logs
LOG_DIR = Path("live_bot_logs") / "ticks"
LOG_DIR.mkdir(parents=True, exist_ok=True)


class TickLogger:
    """Logger de telemetria para live_bot.py."""

    def __init__(self):
        self._tick_counts: dict[str, int] = {}  # city_name -> tick_count
        self._p_ensemble_max: dict[str, float] = {}  # city_name -> max p_ensemble do dia
        self._p_ensemble_at_buy: dict[str, float] = {}  # city_name -> p_ensemble no buy
        self._last_logged_date: dict[str, str] = {}  # city_name -> date string (para detectar mudança de dia)
        self._errors_count: dict[str, int] = {}  # city_name -> erros no dia

    def _now_iso(self) -> str:
        return datetime.now(tz=ZoneInfo("Europe/Lisbon")).isoformat(timespec="seconds")

    def _tick_file(self, city_name: str, date_str: str) -> Path:
        return LOG_DIR / f"ticks_{city_name}_{date_str}.jsonl"

    def _bet_file(self, city_name: str, date_str: str) -> Path:
        return LOG_DIR / f"bets_{city_name}_{date_str}.jsonl"

    def _outcome_file(self, city_name: str, date_str: str) -> Path:
        return LOG_DIR / f"outcomes_{city_name}_{date_str}.jsonl"

    def _write_jsonl(self, path: Path, record: dict) -> None:
        """Escreve 1 linha JSONL num ficheiro (append mode)."""
        try:
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, default=str, ensure_ascii=False) + "\n")
        except Exception as e:
            # Logger NUNCA deve quebrar o bot — logar erro no stderr
            print(f"  [tick_logger] ERRO ao escrever {path}: {e}")

    def log_tick(
        self,
        state,
        city_today,
        race_active: bool = False,
        race_threshold: Optional[float] = None,
        eod_active: bool = False,
        actions: Optional[list] = None,
        errors: Optional[list] = None,
    ) -> None:
        """Regista 1 tick no ficheiro ticks_{city}_{date}.jsonl.

        Args:
            state: CityState do live_bot
            city_today: data (date) no timezone da cidade
            race_active: se race mode disparou neste tick
            race_threshold: threshold usado pelo race (se activo)
            eod_active: se EOD fallback disparou
            actions: lista de actions devolvidas por evaluate()
            errors: lista de mensagens de erro/warning não fatais
        """
        city = state.city
        city_name = city.name
        date_str = city_today.isoformat()

        # Detectar mudança de dia (reset contadores)
        last_date = self._last_logged_date.get(city_name)
        if last_date != date_str:
            self._tick_counts[city_name] = 0
            self._p_ensemble_max[city_name] = 0.0
            self._p_ensemble_at_buy.pop(city_name, None)
            self._errors_count[city_name] = 0
            self._last_logged_date[city_name] = date_str

        self._tick_counts[city_name] = self._tick_counts.get(city_name, 0) + 1
        tick_count = self._tick_counts[city_name]

        # Track p_ensemble max
        p_ens = float(getattr(state, "last_p_ensemble", 0.0) or 0.0)
        if p_ens > self._p_ensemble_max.get(city_name, 0.0):
            self._p_ensemble_max[city_name] = p_ens

        if errors:
            self._errors_count[city_name] = self._errors_count.get(city_name, 0) + len(errors)

        # temp_now
        temp_now = None
        if state.latest_obs:
            temp_now = state.latest_obs.get("temp_c")

        # running_max + hora do pico
        running_max = None
        running_max_hour = None
        if state.slots_so_far:
            valid = [s for s in state.slots_so_far if s.get("temp_c") is not None]
            if valid:
                peak_slot = max(valid, key=lambda s: float(s["temp_c"]))
                running_max = float(peak_slot["temp_c"])
                running_max_hour = int(peak_slot["hour"])

        # Forecasts
        forecast_wu = getattr(state, "last_wu_forecast_max", None)
        forecast_om = getattr(state, "last_om_forecast_max", None)

        # Threshold / hour_min
        threshold = getattr(state.entry, "threshold", None) if state.entry else None
        hour_min = getattr(state.entry, "hour_min", None) if state.entry else None

        # Bought / stop_loss
        bought = bool(state.entry.bought) if state.entry else False
        # stop_loss_hit: inferred do daily_stats
        stop_loss_hit = False
        if state.daily_stats:
            stop_loss_hit = getattr(state.daily_stats, "stop_losses_triggered", 0) > 0

        # Target bracket
        target_bracket = None
        tb = getattr(state, "last_target_bracket", None)
        if tb:
            target_bracket = {
                "label":    tb.get("label"),
                "ask":      float(tb.get("ask") or 0),
                "bid":      float(tb.get("bid") or tb.get("ask") or 0),
                "token_id": tb.get("token_id"),
                "temp_lo":  tb.get("temp_lo"),
                "temp_hi":  tb.get("temp_hi"),
            }

        # Market top brackets (top 6)
        market_top = []
        market_volume = None
        market_n_outcomes = None
        if state.market:
            market_volume = float(state.market.get("volume", 0) or 0)
            market_n_outcomes = int(state.market.get("n_outcomes", 0) or 0)
            brackets = state.market.get("brackets", [])[:6]
            for b in brackets:
                market_top.append({
                    "label": b.get("label"),
                    "ask":   float(b.get("ask") or 0),
                    "bid":   float(b.get("bid") or b.get("ask") or 0),
                })

        # Hora local cidade
        from datetime import datetime as _dt
        try:
            city_dt = _dt.now(tz=ZoneInfo(city.timezone))
            city_local_hhmm = city_dt.strftime("%H:%M")
        except Exception:
            city_local_hhmm = None

        # Actions simplificadas
        actions_simple = []
        if actions:
            for a in actions:
                if isinstance(a, dict):
                    actions_simple.append({
                        "size_usdc": a.get("size_usdc", 0),
                        "strategy":  a.get("strategy"),
                        "reason":    str(a.get("reason", ""))[:200],
                    })

        record = {
            "ts":                self._now_iso(),
            "city":              city_name,
            "date":              date_str,
            "city_local_hhmm":   city_local_hhmm,
            "tick_count":        tick_count,
            "temp_now":          temp_now,
            "running_max":       running_max,
            "running_max_hour":  running_max_hour,
            "slots_count":       len(state.slots_so_far),
            "p_ensemble":        p_ens,
            "p_lgbm":            getattr(state, "last_p_lgbm", None),
            "threshold":         threshold,
            "hour_min":          hour_min,
            "bought":            bought,
            "stop_loss_hit":     stop_loss_hit,
            "forecast_wu":       forecast_wu,
            "forecast_om":       forecast_om,
            "target_bracket":    target_bracket,
            "market_top":        market_top,
            "market_volume":     market_volume,
            "market_n_outcomes": market_n_outcomes,
            "race_active":       race_active,
            "race_threshold":    race_threshold,
            "eod_active":        eod_active,
            "actions":           actions_simple,
            "errors":            errors or [],
        }

        self._write_jsonl(self._tick_file(city_name, date_str), record)

    def log_bet(
        self,
        bet_record: dict,
        city_name: str,
        date_str: str,
        trigger: str = "normal",
        tick_count: int = 0,
        race_rank: Optional[int] = None,
        race_total: Optional[int] = None,
        p_ensemble: Optional[float] = None,
        market_volume: Optional[float] = None,
    ) -> None:
        """Regista 1 bet no ficheiro bets_{city}_{date}.jsonl."""
        # Guardar p_ensemble no buy
        if p_ensemble is not None:
            self._p_ensemble_at_buy[city_name] = p_ensemble

        record = dict(bet_record)  # copiar
        record["ts"] = self._now_iso()
        record["tick_count"] = tick_count
        record["trigger"] = trigger  # "normal" | "race" | "eod_fallback"
        record["race_rank"] = race_rank
        record["race_total"] = race_total
        record["p_ensemble_at_buy"] = p_ensemble
        record["market_volume_at_buy"] = market_volume

        self._write_jsonl(self._bet_file(city_name, date_str), record)

    def log_outcome(
        self,
        city_name: str,
        date_str: str,
        temp_max_actual: Optional[float],
        temp_max_hour: Optional[int],
        bracket_resolved: Optional[str],
        n_buys: int,
        n_sells: int,
        n_stops: int,
        bought: bool,
        win: Optional[bool],
        pnl_total: float,
        invested: float,
        p_ensemble_at_peak_temp: Optional[float] = None,
        race_used: bool = False,
        eod_used: bool = False,
    ) -> None:
        """Regista 1 outcome (EOD) no ficheiro outcomes_{city}_{date}.jsonl."""
        record = {
            "ts":                          self._now_iso(),
            "city":                        city_name,
            "date":                        date_str,
            "temp_max_actual":             temp_max_actual,
            "temp_max_hour":               temp_max_hour,
            "bracket_resolved":            bracket_resolved,
            "n_ticks":                     self._tick_counts.get(city_name, 0),
            "n_buys":                      n_buys,
            "n_sells":                     n_sells,
            "n_stops":                     n_stops,
            "bought":                      bought,
            "win":                         win,
            "pnl_total":                   pnl_total,
            "invested":                    invested,
            "p_ensemble_max":              self._p_ensemble_max.get(city_name, 0.0),
            "p_ensemble_at_buy":           self._p_ensemble_at_buy.get(city_name),
            "p_ensemble_at_peak_temp":     p_ensemble_at_peak_temp,
            "race_used":                   race_used,
            "eod_used":                    eod_used,
            "errors_count":                self._errors_count.get(city_name, 0),
        }

        self._write_jsonl(self._outcome_file(city_name, date_str), record)

    def get_p_ensemble_at(self, city_name: str, hour: int, date_str: str) -> Optional[float]:
        """Retorna p_ensemble numa hora específica do dia (para análise).
        Lê o ficheiro ticks e encontra o tick mais próximo da hora.
        """
        path = self._tick_file(city_name, date_str)
        if not path.exists():
            return None
        try:
            closest = None
            closest_diff = 999
            with path.open() as f:
                for line in f:
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    tick_hour = int(rec.get("city_local_hhmm", "00:00").split(":")[0])
                    diff = abs(tick_hour - hour)
                    if diff < closest_diff:
                        closest_diff = diff
                        closest = rec.get("p_ensemble")
                    if diff == 0:
                        break
            return closest
        except Exception:
            return None


# Singleton (instância global para o live_bot)
_logger_instance: Optional[TickLogger] = None


def get_tick_logger() -> TickLogger:
    """Retorna singleton TickLogger."""
    global _logger_instance
    if _logger_instance is None:
        _logger_instance = TickLogger()
    return _logger_instance
