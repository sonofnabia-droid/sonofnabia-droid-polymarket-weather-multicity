"""
modules/dual_strategy.py
========================
Dual Strategy genérico para multi-cidade.

Orquestra duas vias de entrada independentes para 1 trade por dia:

  Estratégia A — Forecast Early:
    Entra cedo (10h-14h) baseado na confiança do forecast.
    Compra o bracket do forecast quando P(forecast correcto) é alta
    e o ask ainda tem EV positivo.

  Estratégia B — Peak Detection:
    Entra mais tarde (11h+) baseado no modelo ML.
    Compra o bracket do running_max quando P(pico) >= threshold.

Regras:
  - 1 trade por dia. A primeira que trigger ganha, a outra desactiva.
  - Stop-loss partilhado (se A comprou e stop triggers, B não activa).
  - Se forecast indisponível, A desactiva-se automaticamente.
  - Se já comprou, só verifica stop-loss.

Versão: 1.0 — 2026-04-29
Genérico para multi-cidade
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from typing import Optional
from cities.config import CityConfig, DualStrategyConfig
from modules.forecast_confidence import p_forecast_correct_with_om_penalty, max_ask_for_ev_positive


class DualStrategy:
    """
    Dual Strategy genérico para qualquer cidade.

    A configuração é fornecida via kwargs. Se não fornecidos,
    usa valores padrão.
    """

    def __init__(self, city_config: CityConfig, **kwargs):
        self.city = city_config

        # Configuração via kwargs ou defaults
        self.parcel_size = kwargs.get("parcel_size", 5.0)
        self.fc_hour_min = kwargs.get("fc_hour_min", 10)
        self.fc_hour_max = kwargs.get("fc_hour_max", 14)
        self.fc_p_min = kwargs.get("fc_p_min", 0.75)
        self.fc_ev_margin = kwargs.get("fc_ev_margin", 0.05)
        self.pk_threshold = kwargs.get("pk_threshold", 0.650)
        self.pk_hour_min = kwargs.get("pk_hour_min", 11)
        self.stop_loss_delta = kwargs.get("stop_loss_delta", 1.0)

        self.bought = False
        self.record = None
        self.strategy_used = None
        self.sold_by_stop = False
        self.fc_available = True

        # Último P(forecast correct) calculado — exposto para display/logging
        self.last_p_fc = None
        self.last_max_ask = None

    def evaluate(
        self,
        p_peak: float,
        hour: int,
        market: dict | None,
        running_max: float,
        wu_forecast_max: int | None = None,
        om_forecast_max: int | None = None,
        cloud_cover: float = 50.0,
        humidity: float = 70.0,
        month: int = 4,
        uv_index: float | None = None,
    ) -> list[dict]:
        """Avalia se deve entrar no mercado com uma das duas estratégias."""
        if self.bought:
            return [self._no_action("já comprado neste dia")]

        actions = []

        # Strategy A: Forecast Early
        if (self.fc_available
                and self.fc_hour_min <= hour <= self.fc_hour_max
                and wu_forecast_max is not None):

            temp_gap = float(wu_forecast_max - running_max)

            p_fc = p_forecast_correct_with_om_penalty(
                month=month,
                cloud_cover=cloud_cover,
                humidity=humidity,
                wu_max=wu_forecast_max,
                om_max=om_forecast_max,
                temp_gap=temp_gap,
                uv_index=uv_index,
            )

            max_ask = max_ask_for_ev_positive(p_fc, self.fc_ev_margin)

            # Guardar para display/logging
            self.last_p_fc = p_fc
            self.last_max_ask = max_ask

            if p_fc >= self.fc_p_min:
                if max_ask > 0:
                    bracket = self._find_bracket(market, wu_forecast_max)
                    if bracket:
                        ask = bracket.get("ask") or bracket.get("price", 1.0)
                        if ask <= max_ask:
                            actions.append({
                                "strategy": "forecast_early",
                                "size_usdc": self.parcel_size,
                                "reason": (
                                    "FC EARLY: P(fc)="
                                    + str(round(p_fc * 100, 1))
                                    + "% ask="
                                    + str(round(ask * 100, 1))
                                    + "¢ max="
                                    + str(round(max_ask * 100, 1))
                                    + "¢ fc="
                                    + str(wu_forecast_max)
                                    + "°C "
                                    + bracket["label"]
                                ),
                                "bracket": bracket,
                                "target_temp": wu_forecast_max,
                                "model_ok": True,
                                "market_ok": True,
                            })

        # Strategy B: Peak Detection
        if not actions and hour >= self.pk_hour_min:
            if p_peak >= self.pk_threshold:
                target = int(round(running_max))
                bracket = self._find_bracket(market, target)
                if bracket:
                    ask = bracket.get("ask") or bracket.get("price", 1.0)
                    actions.append({
                        "strategy": "peak_detection",
                        "size_usdc": self.parcel_size,
                        "reason": (
                            "PEAK: P="
                            + str(round(p_peak * 100, 1))
                            + "% ask="
                            + str(round(ask * 100, 1))
                            + "¢ "
                            + bracket["label"]
                        ),
                        "bracket": bracket,
                        "target_temp": target,
                        "model_ok": True,
                        "market_ok": True,
                    })

        if not actions:
            reasons = self._build_no_entry_reasons(
                p_peak, hour, wu_forecast_max, cloud_cover, humidity,
                month, om_forecast_max, uv_index,
                temp_gap=float(wu_forecast_max - running_max)
                         if wu_forecast_max is not None else 5.0,
            )
            actions.append(self._no_action(reasons))

        return actions

    def check_stop_loss(self, current_temp: float) -> dict | None:
        """Verifica se deve activar stop-loss."""
        if not self.bought or self.sold_by_stop or self.record is None:
            return None

        bracket_hi = self.record.get("temp_hi")
        if bracket_hi is None or bracket_hi >= 99:
            return None

        trigger_temp = bracket_hi + self.stop_loss_delta
        if current_temp >= trigger_temp:
            strat_tag = self.strategy_used or "unknown"
            return {
                "trigger_temp": trigger_temp,
                "current_temp": current_temp,
                "bracket_hi": bracket_hi,
                "position": self.record,
                "reason": (
                    "STOP-LOSS ["
                    + strat_tag
                    + "]: temp="
                    + str(round(current_temp, 1))
                    + "°C >= bracket_hi="
                    + str(round(bracket_hi))
                    + "°C + "
                    + str(round(self.stop_loss_delta, 1))
                    + "°C"
                ),
            }
        return None

    def mark_bought(self, parcel_idx: int, record: dict) -> None:
        """Marca que uma posição foi aberta."""
        self.bought = True
        self.record = record
        self.strategy_used = record.get("strategy")
        self.sold_by_stop = False

    def mark_sold_by_stop(self, sell_price: float, pnl: float) -> None:
        """Marca posição como vendida via stop-loss."""
        self.sold_by_stop = True
        if self.record is not None:
            self.record["sold_by_stop"] = True
            self.record["sell_price"] = sell_price
            self.record["realized_pnl"] = pnl

    def reset(self) -> None:
        """Reseta o estado para novo dia."""
        self.bought = False
        self.record = None
        self.strategy_used = None
        self.sold_by_stop = False
        self.fc_available = True
        self.last_p_fc = None
        self.last_max_ask = None

    @property
    def total_invested(self) -> float:
        """Valor total investido."""
        return self.parcel_size if self.bought else 0.0

    @property
    def n_parcels_bought(self) -> int:
        """Número de parcelas compradas."""
        return 1 if self.bought else 0

    @property
    def parcel_bought(self) -> list[bool]:
        """Estado das parcelas (compatibilidade com PhasedEntry)."""
        return [self.bought, False, False]

    @property
    def parcel_records(self) -> list[dict | None]:
        """Registos das parcelas (compatibilidade com PhasedEntry)."""
        return [self.record, None, None]

    def _find_bracket(self, market: dict | None, target_temp: int | float
                     ) -> dict | None:
        """Encontra o bracket mais próximo da temperatura alvo."""
        if not market or not market.get("brackets"):
            return None
        target = int(round(target_temp))
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
        dists = []
        for b in market["brackets"]:
            if b["temp_hi"] >= 99:
                mid = b["temp_lo"]
            elif b["temp_lo"] <= -99:
                mid = b["temp_hi"]
            else:
                mid = (b["temp_lo"] + b["temp_hi"]) / 2
            dists.append((abs(mid - target), b))
        if dists:
            return min(dists, key=lambda x: x[0])[1]
        return None

    def _no_action(self, reason: str) -> dict:
        """Cria um dicionário de não-ação."""
        return {
            "strategy": None,
            "size_usdc": 0,
            "reason": reason,
            "bracket": None,
            "target_temp": None,
            "model_ok": None,
            "market_ok": None,
        }

    def _build_no_entry_reasons(
        self,
        p_peak: float,
        hour: int,
        wu_forecast_max: int | None,
        cloud_cover: float,
        humidity: float,
        month: int,
        om_forecast_max: int | None,
        uv_index: float | None,
        temp_gap: float = 5.0,
    ) -> str:
        """Constrói a string de razões para não entrar."""
        parts = []

        if hour < self.fc_hour_min:
            parts.append("hora=" + str(hour) + "h < " + str(self.fc_hour_min) + "h")
        elif self.fc_hour_max < hour < self.pk_hour_min:
            parts.append("hora=" + str(hour) + "h entre A_max=" + str(self.fc_hour_max) + "h e B_min=" + str(self.pk_hour_min) + "h")

        if not self.fc_available:
            parts.append("sem forecast WU")
        elif wu_forecast_max is not None:
            p_fc = p_forecast_correct_with_om_penalty(
                month=month,
                cloud_cover=cloud_cover,
                humidity=humidity,
                wu_max=wu_forecast_max,
                om_max=om_forecast_max,
                temp_gap=temp_gap,
                uv_index=uv_index,
            )
            if p_fc < self.fc_p_min:
                parts.append("P(fc)=" + str(round(p_fc * 100, 1)) + "% < " + str(round(self.fc_p_min * 100, 1)) + "%")

        if p_peak < self.pk_threshold:
            parts.append("P(pk)=" + str(round(p_peak * 100, 1)) + "% < " + str(round(self.pk_threshold * 100, 1)) + "%")

        if parts:
            return "DUAL: " + " | ".join(parts)
        return "DUAL: sem trigger"


if __name__ == "__main__":
    from cities.config import get_city

    print("=" * 60)
    print(" modules/dual_strategy.py — self-test")
    print("=" * 60)

    city = get_city("munich")
    dual = DualStrategy(city)

    # Teste 1: Forecast Early trigger
    print(f"\n[1] Forecast Early Trigger:")
    print(f"    City: {city.name}")
    print(f"    FC config: {dual.fc_hour_min}-{dual.fc_hour_max}h, P_min={dual.fc_p_min}")

    # Teste 2: Peak Detection trigger
    print(f"\n[2] Peak Detection Trigger:")
    print(f"    Pk config: {dual.pk_hour_min}h+, threshold={dual.pk_threshold}")

    # Teste 3: No trigger (early hour)
    actions = dual.evaluate(
        p_peak=0.8, hour=9, market=None, running_max=20.0,
    )
    print(f"\n[3] Hour=9h (too early):")
    print(f"    Actions: {actions[0]['reason']}")

    print("\nOK")
