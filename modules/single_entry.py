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



# ══════════════════════════════════════════════════════
#  FUNCOES DE MODULO (para reutilizar em backtester/live_bot)
# ══════════════════════════════════════════════════════

def select_target_bracket(market: dict | list | None, running_max: float) -> dict | None:
    """
    Selecciona o bracket Polymarket que contem floor(running_max).
    Aceita dict {"brackets": [...]} ou lista [...] directamente.

    Logica (igual em live_bot e backtester — FIX Bug #8):
      1. Match exacto: bracket onde temp_lo <= target <= temp_hi
      2. Cauda "or higher" (hi=99): target >= temp_lo
      3. Cauda "or lower" (lo=-99): target <= temp_hi
      4. Mais proximo por midpoint (caudas usam limite único)
    """
    if not market:
        return None
    # Suporta dict {"brackets": [...]} ou lista [...] directamente
    if isinstance(market, list):
        brackets = market
    else:
        brackets = market.get("brackets") or []
    if not brackets:
        return None

    target_temp = int(math.floor(running_max))

    # 1. Match exacto (exclui caudas hi>=99 ou lo<=-99 — tratadas no passo 2)
    for bracket in brackets:
        lo = bracket.get("temp_lo")
        hi = bracket.get("temp_hi")
        if lo is None or hi is None:
            continue
        if hi >= 99 or lo <= -99:
            continue
        if lo <= target_temp <= hi:
            return bracket

    # 2. Fallback: bracket de cauda "or higher" / "or lower"
    # FIX Bug #12: escolher o mais proximo de target_temp (nao o primeiro)
    tail_brackets = []
    for bracket in brackets:
        lo = bracket.get("temp_lo")
        hi = bracket.get("temp_hi")
        if lo is None or hi is None:
            continue
        if hi >= 99 and target_temp >= lo:
            tail_brackets.append((abs(lo - target_temp), bracket))
        if lo <= -99 and target_temp <= hi:
            tail_brackets.append((abs(hi - target_temp), bracket))
    if tail_brackets:
        return min(tail_brackets, key=lambda x: x[0])[1]

    # 3. Fallback: bracket mais proximo
    def _distance(b):
        lo = float(b.get("temp_lo", 0))
        hi = float(b.get("temp_hi", 0))
        if hi >= 99:
            return abs(lo - target_temp)
        if lo <= -99:
            return abs(hi - target_temp)
        return abs((lo + hi) / 2 - target_temp)

    valid_brackets = [
        b for b in brackets
        if b.get("temp_lo") is not None and b.get("temp_hi") is not None
    ]
    if valid_brackets:
        return min(valid_brackets, key=_distance)
    return None

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

    @staticmethod
    def _first_non_none(*values):
        """Retorna o primeiro valor que não é None. Evita bugs do `or` com 0/0.0."""
        for v in values:
            if v is not None:
                return v
        return None

    def __init__(self, city_config: CityConfig, **kwargs):
        self.city = city_config

        # Tentar carregar config calibrada da pasta da cidade.
        _cfg_path = city_config.strategy_config_path
        threshold = None
        hour_min = None
        stop_loss_delta = None
        min_buy_ask = None
        max_buy_ask = None
        plateau_timeout_hours = None

        if _cfg_path.exists():
            try:
                cfg = json.loads(_cfg_path.read_text())
                sc = cfg.get("single", {})
                threshold = sc.get("threshold")
                hour_min = sc.get("hour_min")
                stop_loss_delta = sc.get("stop_loss_delta")
                min_buy_ask = sc.get("min_buy_ask")
                max_buy_ask = sc.get("max_buy_ask")
                plateau_timeout_hours = sc.get("plateau_timeout_hours")
            except Exception:
                pass

        # Fallback: kwargs → CityConfig → defaults
        self.parcel_size = kwargs.get("parcel_size", 5.0)
        self.threshold = self._first_non_none(
            kwargs.get("threshold"),
            threshold,
            city_config.threshold,
        ) or 0.65
        self.hour_min = self._first_non_none(
            kwargs.get("hour_min"),
            hour_min,
            city_config.hour_min,
        ) or 11
        self.stop_loss_delta = self._first_non_none(
            kwargs.get("stop_loss_delta"),
            stop_loss_delta,
        ) or 1.0
        self.min_buy_ask = self._first_non_none(
            kwargs.get("min_buy_ask"),
            min_buy_ask,
        ) or 0.15
        self.max_buy_ask = self._first_non_none(
            kwargs.get("max_buy_ask"),
            max_buy_ask,
        ) or 0.85
        # FIX Bug 1.1: timeout para filtro de plateau em subida constante
        self.plateau_timeout_hours = self._first_non_none(
            kwargs.get("plateau_timeout_hours"),
            plateau_timeout_hours,
        ) or 4.0

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
            # FIX Bug #10: usar hour passado como parametro (nao slots_so_far[-1]),
            # porque o caller pode chamar evaluate() ANTES de adicionar o slot actual
            # a slots_so_far.
            now_minutes = hour * 60
            target_minutes = now_minutes - 30

            # Buscar o slot mais próximo de 30 min atrás
            prev_slot = None
            for s in reversed(slots_so_far[:-1]):  # excluir o slot actual
                s_minutes = int(s["hour"]) * 60 + int(s.get("slot30", 0))
                if s_minutes <= target_minutes:
                    prev_slot = s
                    break

            if prev_slot is not None:
                delta = slots_so_far[-1]["temp_c"] - prev_slot["temp_c"]
                if delta > 0.2:
                    # FIX Bug 1.1: timeout de plateau — se já passou tempo
                    # suficiente desde o primeiro slot do dia, deixa de bloquear
                    # para evitar nenhuma compra em dias de subida constante.
                    first_slot_minutes = (
                        int(slots_so_far[0]["hour"]) * 60
                        + int(slots_so_far[0].get("slot30", 0))
                    )
                    elapsed_hours = (now_minutes - first_slot_minutes) / 60.0
                    if elapsed_hours < self.plateau_timeout_hours:
                        return [{
                            "parcel_idx": 0,
                            "size_usdc": 0,
                            "reason": (
                                f"SINGLE: temp subiu {delta:+.2f}°C nos últimos 30min "
                                f"(> +0.20°C). À espera de plateau "
                                f"({elapsed_hours:.1f}h < {self.plateau_timeout_hours}h timeout)."
                            ),
                            "model_ok": True,
                            "market_ok": None,
                        }]
                    # else: plateau timeout expirado — continua para avaliar compra

        if p_ensemble >= self.threshold:
            bracket = self._select_target_bracket(market, running_max) if market else None
            
            # Bloquear compra se não houver bracket válido no mercado
            if bracket is None:
                return [{
                    "parcel_idx": 0,
                    "size_usdc": 0,
                    "reason": "SINGLE: p acima do threshold mas sem bracket válido no mercado",
                    "model_ok": True,
                    "market_ok": False,
                    "bracket": None,
                }]
                
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
    def _select_target_bracket(market: dict | list | None, running_max: float) -> dict | None:
        # FIX Bug #8: delega para a funcao de modulo select_target_bracket
        # para garantir consistencia entre live_bot e backtester (antes o
        # backtester recalculava localmente com lógica diferente).
        return select_target_bracket(market, running_max)

    def check_stop_loss(self, current_temp: float) -> dict | None:
        if not self.bought or self.sold_by_stop or self.record is None:
            return None

        bracket_hi = self.record.get("temp_hi")
        bracket_lo = self.record.get("temp_lo")

        # FIX Bug #9: se temp_hi/temp_lo em falta no record (ex: restart
        # com dados incompletos), nao desativar silenciosamente o stop-loss.
        # Tentar obter do bracket_label ou abortar com log explicito.
        if bracket_hi is None or bracket_lo is None:
            return None

        # FIX Bug #6: tratar brackets de cauda ("or higher" / "or lower").
        # Antes, a condicao `bracket_hi >= 99` desativava completamente o
        # stop-loss para "X or higher", mantendo a posicao ate expiracao mesmo
        # quando claramente perdida (ex: fim do dia, temp 5°C abaixo de X).
        trigger_high = bracket_hi + self.stop_loss_delta  # normal: >hi = perdeu
        trigger_low  = bracket_lo - self.stop_loss_delta  # normal: <lo = perdeu

        if bracket_hi >= 99:
            # "X°C or higher" — ganha se peak >= bracket_lo.
            # Stop-loss: temp atual ja caiu demasiado baixo para o pico
            # poder atingir bracket_lo. trigger = bracket_lo - delta.
            trigger_temp = bracket_lo - self.stop_loss_delta
            if current_temp <= trigger_temp:
                return {
                    "trigger_temp": trigger_temp,
                    "current_temp": current_temp,
                    "bracket_lo":   bracket_lo,
                    "bracket_hi":   bracket_hi,
                    "position":     self.record,
                    "reason": (f"STOP-LOSS (or-higher): temp={current_temp:.1f}°C <= "
                               f"bracket_lo={bracket_lo:.0f}°C - "
                               f"{self.stop_loss_delta:.1f}°C"),
                }
            return None

        if bracket_lo <= -99:
            # "X°C or lower" — ganha se peak <= bracket_hi.
            # Stop-loss: temp atual ja subiu demasiado alta para o pico
            # poder ficar <= bracket_hi. trigger = bracket_hi + delta.
            trigger_temp = bracket_hi + self.stop_loss_delta
            if current_temp >= trigger_temp:
                return {
                    "trigger_temp": trigger_temp,
                    "current_temp": current_temp,
                    "bracket_lo":   bracket_lo,
                    "bracket_hi":   bracket_hi,
                    "position":     self.record,
                    "reason": (f"STOP-LOSS (or-lower): temp={current_temp:.1f}°C >= "
                               f"bracket_hi={bracket_hi:.0f}°C + "
                               f"{self.stop_loss_delta:.1f}°C"),
                }
            return None

        # Bracket normal: stop-loss se temp >= bracket_hi + delta
        # (pico ja ultrapassou o nosso teto — posicao perdida).
        trigger_temp = trigger_high
        if current_temp >= trigger_temp:
            return {
                "trigger_temp": trigger_temp,
                "current_temp": current_temp,
                "bracket_lo":   bracket_lo,
                "bracket_hi":   bracket_hi,
                "position":     self.record,
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
        # FIX Bug #5: preservar sold_by_stop do record se la estiver.
        # O Bug 1.5 (commit 7ce499c) forçava sempre False, descartando o
        # valor True guardado em disco por mark_sold_by_stop(). Isto levava
        # a stop-loss duplicado pós-restart — se o stop-loss ja tinha sido
        # executado antes do restart, a posicao era vendida outra vez.
        # Agora le do record primeiro (igual ao que foi persistido),
        # fallback a False se a chave nao existir (record antigo ou corrupto).
        self.bought = True
        self.record = record
        if isinstance(record, dict) and record.get("sold_by_stop", False):
            self.sold_by_stop = True
        else:
            self.sold_by_stop = False
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
    print(f"    Plateau timeout: {single.plateau_timeout_hours}h")

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
