"""
munich_phased_entry.py
======================
Lógica de entrada: modo PHASED (3 parcelas) ou SINGLE (1 compra).

Alterações:
- parcel_size default agora é $5 em ambos os modos
- SingleEntry reason correto quando já comprou
- Phased P2/P3 com janela horária (não compra perto do fecho)
"""

class PhasedEntry:
    def __init__(self, parcel_size: float = 5.0):   # ← Alterado para $5
        self.parcel_size = parcel_size
        self.thr_p1_min = 0.30
        self.thr_p1_max = 0.65
        self.thr_p2     = 0.70
        self.thr_p3     = 0.85
        self.temp_tolerance = 1

        self.p1_hour_min = 10
        self.p1_hour_max = 12

        self.parcel_bought:  list[bool]       = [False, False, False]
        self.parcel_records: list[dict | None] = [None,  None,  None]

    # ── helpers internos ──────────────────────────────

    def _find_highest_ask_bracket(self, market: dict | None) -> dict | None:
        if not market or not market.get("brackets"):
            return None
        return max(market["brackets"],
                   key=lambda b: b.get("ask") or b.get("price") or 0)

    def _market_confirms_model(self, market: dict | None,
                               running_max: float) -> tuple[bool, str]:
        best = self._find_highest_ask_bracket(market)
        if best is None:
            return False, "sem mercado"

        best_ask   = best.get("ask") or best.get("price") or 0
        best_lo    = best["temp_lo"]
        best_hi    = best["temp_hi"]
        best_label = best["label"]
        rmax_int   = int(round(running_max))

        if best_lo <= -99:
            return False, f"mercado={best_label} (or lower)"

        if best_lo <= rmax_int <= best_hi:
            return True, f"mercado={best_label} ({best_ask*100:.0f}¢) = {rmax_int}°C"

        mid = best_lo if best_hi >= 99 else (best_lo + best_hi) / 2
        if abs(mid - rmax_int) <= self.temp_tolerance:
            return True, f"mercado={best_label} ({best_ask*100:.0f}¢) ≈ {rmax_int}°C"

        return False, f"mercado={best_label} ({best_ask*100:.0f}¢) ≠ {rmax_int}°C"

    # ── evaluate ──────────────────────────────────────

    def evaluate(self, p_ensemble: float, hour: int, market: dict | None,
                 running_max: float, forecast_agreement: dict | None) -> list[dict]:
        actions = []

        # ── P1: Value Early ───────────────────────────
        if not self.parcel_bought[0]:
            in_morning     = self.p1_hour_min <= hour < self.p1_hour_max
            fc_ok          = (forecast_agreement is not None and forecast_agreement.get("valid", False))
            mkt_ok, mkt_detail = self._market_confirms_model(market, running_max)
            model_in_range = self.thr_p1_min <= p_ensemble <= self.thr_p1_max

            if in_morning and fc_ok and mkt_ok and model_in_range:
                actions.append({
                    "parcel_idx": 0,
                    "size_usdc":  self.parcel_size,
                    "reason":     (f"P1: manhã ({hour}h) + fc agree + "
                                   f"{mkt_detail} + p={p_ensemble*100:.0f}% (value early)"),
                    "model_ok":   True,
                    "market_ok":  True,
                })
            else:
                reasons = []
                if not in_morning:
                    reasons.append(f"hora={hour}h fora de [{self.p1_hour_min},{self.p1_hour_max})")
                if not fc_ok:
                    reasons.append("forecast disagree")
                if not mkt_ok:
                    reasons.append(f"mercado NÃO ({mkt_detail})")
                if not model_in_range:
                    if p_ensemble < self.thr_p1_min:
                        reasons.append(f"p={p_ensemble*100:.0f}% < {self.thr_p1_min*100:.0f}%")
                    else:
                        reasons.append(f"p={p_ensemble*100:.0f}% > {self.thr_p1_max*100:.0f}%")
                actions.append({
                    "parcel_idx": 0,
                    "size_usdc":  0,
                    "reason":     f"P1 BLOQUEADA: {' | '.join(reasons)}",
                    "model_ok":   model_in_range,
                    "market_ok":  mkt_ok,
                })

        # ── P2: Dupla confirmação (com janela horária) ──
        if not self.parcel_bought[1]:
            model_ok           = p_ensemble >= self.thr_p2
            mkt_ok, mkt_detail = self._market_confirms_model(market, running_max)
            hour_ok            = 10 <= hour < 19   # não comprar perto do fecho

            if model_ok and mkt_ok and hour_ok:
                actions.append({
                    "parcel_idx": 1,
                    "size_usdc":  self.parcel_size,
                    "reason":     (f"P2: p={p_ensemble*100:.0f}% >= "
                                   f"{self.thr_p2*100:.0f}% + {mkt_detail}"),
                    "model_ok":   True,
                    "market_ok":  True,
                })
            elif model_ok and mkt_ok and not hour_ok:
                actions.append({
                    "parcel_idx": 1,
                    "size_usdc":  0,
                    "reason":     f"P2 BLOQUEADA: hora={hour}h (mercado a encerrar)",
                    "model_ok":   True,
                    "market_ok":  True,
                })
            elif model_ok and not mkt_ok:
                actions.append({
                    "parcel_idx": 1,
                    "size_usdc":  0,
                    "reason":     (f"P2 BLOQUEADA: modelo OK, mercado NÃO ({mkt_detail})"),
                    "model_ok":   True,
                    "market_ok":  False,
                })

        # ── P3: Alta confiança ────────────────────────
        if not self.parcel_bought[2]:
            if p_ensemble >= self.thr_p3:
                actions.append({
                    "parcel_idx": 2,
                    "size_usdc":  self.parcel_size,
                    "reason":     (f"P3: p={p_ensemble*100:.0f}% >= "
                                   f"{self.thr_p3*100:.0f}%"),
                    "model_ok":   True,
                    "market_ok":  True,
                })

        return actions

    # ── state management ──────────────────────────────

    def mark_bought(self, parcel_idx: int, record: dict) -> None:
        self.parcel_bought[parcel_idx]  = True
        self.parcel_records[parcel_idx] = record

    def reset(self) -> None:
        self.parcel_bought  = [False, False, False]
        self.parcel_records = [None,  None,  None]

    @property
    def total_invested(self) -> float:
        return sum(self.parcel_size for b in self.parcel_bought if b)

    @property
    def n_parcels_bought(self) -> int:
        return sum(self.parcel_bought)


# ══════════════════════════════════════════════════════
#  SINGLE ENTRY — 1 compra de $5 com stop-loss por temperatura
# ══════════════════════════════════════════════════════
#
# Stop-loss (adicionado 2026-04):
#   Se a temperatura subir stop_loss_delta°C acima do bracket_hi
#   da posição aberta, o bracket está "morto" (quase de certeza
#   não ganha) mas ainda tem valor residual no mercado. Vender
#   cedo recupera parte do capital.
#
# Exemplo: comprei YES no bracket 24°C (bracket_hi=24) às 13h.
#   Pelas 15h a temperatura sobe a 25°C. Com delta=1.0:
#     25.0 >= 24 + 1.0 → trigger → vender ao bid corrente.

class SingleEntry:
    # Flag explícita para o display saber distinguir Single vs Phased
    # (a heurística hasattr não funciona porque temos parcel_bought
    # como property de compatibilidade com o backtester).
    is_single = True

    def __init__(self,
                 parcel_size: float = 5.0,
                 threshold: float = 0.55,
                 hour_min: int = 15,
                 stop_loss_delta: float = 1.0):
        # Thresholds calibrados em 2026-04-25 com munich_calibrate.py
        # (--mode full --metric outcome, 5 anos de dados):
        #
        #   threshold=0.55, hour_min=15h
        #   ~110 trades/ano, win=89%, prem%=40%, score=179
        #
        # Compromisso entre volume e qualidade:
        # - 5x mais trades que o anterior (0.68 @ 15h dava 23 trades/ano)
        # - Win-rate 89% (vs 94% do conservador) — ainda muito sólido
        # - Prem 40% ainda saudável (menos triggers de stop-loss)
        # - Lag mediano +0.5h — entradas próximas do pico real
        #
        # NOTA: o calibrador --metric outcome ignora preços simulados.
        # ROI esperado em produção ainda depende dos asks reais Polymarket.
        # Validação em paper trading durante 4-6 semanas é essencial.
        self.parcel_size      = parcel_size
        self.threshold        = threshold
        self.hour_min         = hour_min            # não entrar antes desta hora
        self.stop_loss_delta  = stop_loss_delta     # °C acima de bracket_hi para trigger
        self.bought           = False
        self.record:     dict | None = None
        self.sold_by_stop     = False               # flag para evitar double-trigger

    def evaluate(self, p_ensemble: float, hour: int, market: dict | None,
                 running_max: float, forecast_agreement: dict | None) -> list[dict]:
        if self.bought:
            return [{
                "parcel_idx": 0,
                "size_usdc":  0,
                "reason":     "SINGLE: já comprado nesta sessão",
                "model_ok":   True,
                "market_ok":  None,
            }]

        # Filtro de hora — só entrar a partir de hour_min
        if hour < self.hour_min:
            return [{
                "parcel_idx": 0,
                "size_usdc":  0,
                "reason":     (f"SINGLE: hora={hour}h < hour_min={self.hour_min}h "
                               f"(ainda cedo)"),
                "model_ok":   None,
                "market_ok":  None,
            }]

        if p_ensemble >= self.threshold:
            return [{
                "parcel_idx": 0,
                "size_usdc":  self.parcel_size,
                "reason":     (f"SINGLE: p={p_ensemble*100:.0f}% >= "
                               f"{self.threshold*100:.0f}% @ {hour}h"),
                "model_ok":   True,
                "market_ok":  True,
            }]

        return [{
            "parcel_idx": 0,
            "size_usdc":  0,
            "reason":     (f"SINGLE: p={p_ensemble*100:.0f}% < "
                           f"{self.threshold*100:.0f}%"),
            "model_ok":   False,
            "market_ok":  None,
        }]

    def check_stop_loss(self, current_temp: float) -> dict | None:
        """
        Verifica se deve vender a posição aberta por stop-loss.

        Retorna None se não há posição aberta, se já foi vendida,
        ou se a temperatura ainda está dentro do bracket + tolerância.

        Retorna {trigger_temp, bracket_hi, position} se deve vender.
        Chamador é responsável por:
          1. Encontrar o bid do bracket no mercado
          2. Chamar clob.sell_yes() com esse bid
          3. Chamar mark_sold_by_stop() em caso de sucesso
        """
        if not self.bought or self.sold_by_stop or self.record is None:
            return None

        bracket_hi = self.record.get("temp_hi")
        if bracket_hi is None or bracket_hi >= 99:
            # Bracket "or higher" não faz sentido vender — só ganha se temp ↑
            return None

        trigger_temp = bracket_hi + self.stop_loss_delta
        if current_temp >= trigger_temp:
            return {
                "trigger_temp":  trigger_temp,
                "current_temp":  current_temp,
                "bracket_hi":    bracket_hi,
                "position":      self.record,
                "reason":        (f"STOP-LOSS: temp={current_temp:.1f}°C >= "
                                  f"bracket_hi={bracket_hi:.0f}°C + "
                                  f"{self.stop_loss_delta:.1f}°C"),
            }
        return None

    def mark_bought(self, parcel_idx: int, record: dict) -> None:
        self.bought = True
        self.record = record
        self.sold_by_stop = False

    def mark_sold_by_stop(self, sell_price: float, pnl: float) -> None:
        """Marca a posição como vendida via stop-loss."""
        self.sold_by_stop = True
        if self.record is not None:
            self.record["sold_by_stop"] = True
            self.record["sell_price"]   = sell_price
            self.record["realized_pnl"] = pnl

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