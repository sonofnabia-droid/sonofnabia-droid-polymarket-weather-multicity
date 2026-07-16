"""
modules/single_entry.py
=======================
Single Entry genérico para multi-cidade.

1 compra de $5 com stop-loss por temperatura.
Lê thresholds de cities/{city}/strategy_config_{city}.json.

Baseado em POLY-IRIS munich_phased_entry.py::SingleEntry.
"""
import sys
import json
import math
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from cities.config import CityConfig


class SingleEntry:
    """Single Entry — 1 compra com stop-loss.

    Comportamentos importantes:
      • Filtro de plateau: rejeita compra se temp subiu >0.2°C nos últimos 30min.
        Isto evita comprar em subida acelerada, mas pode bloquear compras
        num dia de subida constante. Ajustar stop_loss_delta se necessário.
      • Após stop-loss: bought=True, sold_by_stop=True → evaluate() bloqueia
        recompra no mesmo dia. O PnL realizado é registado em record["realized_pnl"].
    """

    is_single = True

    def __init__(self, city_config: CityConfig, **kwargs):
        self.city = city_config

        # Tentar carregar config calibrada da pasta da cidade.
        _cfg_path = city_config.strategy_config_path
        threshold = None
        hour_min = None
        stop_loss_delta = None
        min_buy_ask = None
        max_buy_ask = None

        if _cfg_path.exists():
            try:
                cfg = json.loads(_cfg_path.read_text())
                sc = cfg.get("single", {})
                threshold = sc.get("threshold")
                hour_min = sc.get("hour_min")
                stop_loss_delta = sc.get("stop_loss_delta")
                min_buy_ask = sc.get("min_buy_ask")
                max_buy_ask = sc.get("max_buy_ask")
            except Exception:
                pass

        # Fallback: kwargs → CityConfig → defaults
        self.parcel_size = kwargs.get("parcel_size", 5.0)
        self.threshold = (
            kwargs.get("threshold")
            or threshold
            or city_config.threshold
            or 0.65
        )
        self.hour_min = (
            kwargs.get("hour_min")
            or hour_min
            or city_config.hour_min
            or 11
        )
        self.stop_loss_delta = (
            kwargs.get("stop_loss_delta")
            or stop_loss_delta
            or 1.0
        )
        self.min_buy_ask = (
            kwargs.get("min_buy_ask")
            or min_buy_ask
            or 0.15
        )
        self.max_buy_ask = (
            kwargs.get("max_buy_ask")
            or max_buy_ask
            or 0.85
        )

        self.bought = False
        self.record: dict | None = None
        self.sold_by_stop = False
        self.strategy_used: str | None = None

    def evaluate(self, p_ensemble: float, hour: int, market: dict | None,
                 running_max: float, forecast_agreement: dict | None,
                 slots_so_far: list[dict] | None = None) -> list[dict]:
        if self.bought:
            return [{
                "parcel_idx": 0,
                "size_usdc": 0,
                "reason": "SINGLE: já comprado nesta sessão",
                "model_ok": True,
                "market_ok": None,
            }]

        if hour < self.hour_min:
            return [{
                "parcel_idx": 0,
                "size_usdc": 0,
                "reason": f"SINGLE: hora={hour}h < hour_min={self.hour_min}h (ainda cedo)",
                "model_ok": None,
                "market_ok": None,
            }]

        # --- FILTRO DE ESTABILIDADE (PLATEAU) ---
        if slots_so_far and len(slots_so_far) >= 2:
            # Pegar as temperaturas dos últimos 30 minutos (últimos 2 slots)
            temps = [s["temp_c"] for s in slots_so_far[-2:]]
            delta_30m = temps[-1] - temps[0]
            if delta_30m > 0.2:
                return [{
                    "parcel_idx": 0,
                    "size_usdc": 0,
                    "reason": f"SINGLE: temp ainda a subir ({delta_30m:+.2f}°C em 30m > +0.20°C). À espera de plateau.",
                    "model_ok": True,
                    "market_ok": None,
                }]

        if p_ensemble >= self.threshold:
            bracket = self._select_target_bracket(market, running_max) if market else None
            if bracket is not None:
                ask = float(bracket.get("ask", bracket.get("price", 1.0)) or 1.0)
                if ask < self.min_buy_ask:
                    return [{
                        "parcel_idx": 0,
                        "size_usdc": 0,
                        "reason": (
                            f"SINGLE: bracket barato demais ({ask*100:.1f}¢ < "
                            f"{self.min_buy_ask*100:.0f}¢)"
                        ),
                        "model_ok": True,
                        "market_ok": False,
                        "bracket": bracket,
                    }]
                if ask > self.max_buy_ask:
                    return [{
                        "parcel_idx": 0,
                        "size_usdc": 0,
                        "reason": (
                            f"SINGLE: bracket caro demais ({ask*100:.0f}¢ > "
                            f"{self.max_buy_ask*100:.0f}¢)"
                        ),
                        "model_ok": True,
                        "market_ok": False,
                        "bracket": bracket,
                    }]
            return [{
                "parcel_idx": 0,
                "size_usdc": self.parcel_size,
                "reason": f"SINGLE: p={p_ensemble*100:.0f}% >= {self.threshold*100:.0f}% @ {hour}h",
                "model_ok": True,
                "market_ok": True,
                "bracket": bracket,
            }]

        return [{
            "parcel_idx": 0,
            "size_usdc": 0,
            "reason": f"SINGLE: p={p_ensemble*100:.0f}% < {self.threshold*100:.0f}%",
            "model_ok": False,
            "market_ok": None,
        }]

    @staticmethod
    def _select_target_bracket(market: dict | None, running_max: float) -> dict | None:
        if not market:
            return None
        brackets = market.get("brackets") or []
        if not brackets:
            return None

        target_temp = int(math.floor(running_max))
        best = None
        for bracket in brackets:
            lo = bracket.get("temp_lo")
            hi = bracket.get("temp_hi")
            if lo is None or hi is None:
                continue
            if lo <= target_temp <= hi:
                best = bracket
                break
        if best is None and brackets:
            # Fallback: bracket mais próximo do running_max
            # Proteger contra brackets com temp_lo/temp_hi malformados
            valid_brackets = [
                b for b in brackets
                if b.get("temp_lo") is not None and b.get("temp_hi") is not None
            ]
            if valid_brackets:
                best = min(
                    valid_brackets,
                    key=lambda b: abs(((float(b.get("temp_lo", 0.0)) + float(b.get("temp_hi", 0.0))) / 2) - target_temp),
                )
        return best

    def check_stop_loss(self, current_temp: float) -> dict | None:
        if not self.bought or self.sold_by_stop or self.record is None:
            return None

        bracket_hi = self.record.get("temp_hi")
        if bracket_hi is None or bracket_hi >= 99:
            return None

        trigger_temp = bracket_hi + self.stop_loss_delta
        if current_temp >= trigger_temp:
            return {
                "trigger_temp": trigger_temp,
                "current_temp": current_temp,
                "bracket_hi": bracket_hi,
                "position": self.record,
                "reason": (f"STOP-LOSS: temp={current_temp:.1f}°C >= "
                           f"bracket_hi={bracket_hi:.0f}°C + "
                           f"{self.stop_loss_delta:.1f}°C"),
            }
        return None

    def mark_bought(self, parcel_idx: int, record: dict) -> None:
        self.bought = True
        self.record = record
        self.sold_by_stop = False
        self.strategy_used = record.get("strategy") if isinstance(record, dict) else None

    def restore(self, record: dict, strategy_used: str | None = None) -> None:
        self.bought = True
        self.record = record
        self.sold_by_stop = bool(record.get("sold_by_stop", False)) if isinstance(record, dict) else False
        self.strategy_used = strategy_used or (record.get("strategy") if isinstance(record, dict) else None)

    def mark_sold_by_stop(self, sell_price: float, pnl: float) -> None:
        self.sold_by_stop = True
        if self.record is not None:
            self.record["sold_by_stop"] = True
            self.record["sell_price"] = float(sell_price) if sell_price is not None else 0.0
            self.record["realized_pnl"] = float(pnl) if pnl is not None else 0.0

    def reset(self) -> None:
        self.bought = False
        self.record = None
        self.sold_by_stop = False

    @property
    def total_invested(self) -> float:
        return self.parcel_size if self.bought else 0.0

    @property
    def n_parcels_bought(self) -> int:
        return 1 if self.bought else 0

    @property
    def parcel_bought(self) -> list[bool]:
        return [self.bought, False, False]

    @property
    def parcel_records(self) -> list[dict | None]:
        return [self.record, None, None]


if __name__ == "__main__":
    from cities.config import get_city

    print("=" * 60)
    print(" modules/single_entry.py — self-test")
    print("=" * 60)

    city = get_city("munich")
    single = SingleEntry(city)

    print(f"\n[1] SingleEntry config:")
    print(f"    City: {city.name}")
    print(f"    Threshold: {single.threshold}")
    print(f"    Hour min: {single.hour_min}h")
    print(f"    Stop-loss delta: {single.stop_loss_delta}°C")

    # Teste: abaixo do threshold
    actions = single.evaluate(0.5, 15, None, 25.0, None)
    print(f"\n[2] p=0.50 @ 15h: {actions[0]['reason']}")

    # Teste: acima do threshold
    actions = single.evaluate(0.85, 15, None, 25.0, None)
    print(f"[3] p=0.85 @ 15h: {actions[0]['reason']}")

    # Teste: hora demasiado cedo
    actions = single.evaluate(0.85, 8, None, 25.0, None)
    print(f"[4] p=0.85 @  8h: {actions[0]['reason']}")

    print("\nOK")
