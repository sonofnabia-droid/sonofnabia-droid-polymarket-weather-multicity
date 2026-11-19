"""
cassiopeia_entry.py v3 — adaptado ao contrato do cassiopeia_live_bot.
evaluate() -> list[dict] de ações {size_usdc, bracket, strategy, reason}.
Fail-closed: sem modelo ML, sem prev7 ou sem slots suficientes -> [].
"""
from datetime import date, timedelta
from typing import Optional, Dict, Any, List

try:
    from cassiopeia_params import resolve_params
except ImportError:
    resolve_params = None
from resolution_rules import find_bracket as _official_find_bracket


class CassiopeiaEntry:
    def __init__(self, city: str, tg=None, clob=None, models_rebound=None,
                 rebound_threshold=None, min_spread=None, bracket_half=None,
                 start_hour=None, end_hour=None, outlier_cap=None,
                 trading_mode: str = "paper", auto_params: bool = True,
                 parcel_size: float = 1.0, min_buy_ask: Optional[float] = None,
                 max_buy_ask: Optional[float] = None, **kwargs):
        self.city = city.lower().strip()
        self.tg, self.clob = tg, clob
        self.trading_mode = trading_mode
        self.parcel_size = float(parcel_size)
        self.bought = False
        self.record: Optional[dict] = None
        self.strategy_used = "cassiopeia"
        self._warned: set = set()

        if auto_params and resolve_params is not None:
            p = resolve_params(self.city, threshold=rebound_threshold,
                               min_spread=min_spread, bracket_half=bracket_half,
                               start_hour=start_hour, end_hour=end_hour,
                               outlier_cap=outlier_cap)
            # O print tem de mostrar os valores EFETIVOS (argumento explícito
            # > config) — antes mostrava só a config, escondendo o override
            # --min-buy-ask (confusão real na verificação do pin do micro, 07/10)
            if min_buy_ask is not None:
                p["min_buy_ask"] = float(min_buy_ask)
            if max_buy_ask is not None:
                p["max_buy_ask"] = float(max_buy_ask)
            print(f"[CassiopeiaEntry] Params ativos {self.city}: {p}")
        else:
            p = {"threshold": rebound_threshold if rebound_threshold is not None else 0.35,  # paridade com cassiopeia_params.DEFAULT_PARAMS
                 "min_spread":  min_spread if min_spread is not None else 0.5,
                 "bracket_half":bracket_half if bracket_half is not None else 0.5,
                 "start_hour":  start_hour if start_hour is not None else 13,
                 "end_hour":    end_hour if end_hour is not None else 19,
                 "outlier_cap": outlier_cap if outlier_cap is not None else 4.0,
                 "min_buy_ask": 0.60,   # paridade com DEFAULT_PARAMS
                 "max_buy_ask": 0.85}

        # FIX banda v4 (19/09): banda ask (D-V1: 0.80-0.86) chega AQUI a partir
        # da config ativa — antes os defaults 0.60/0.85 eram sempre usados
        # (o caller do live bot não os passa; a D7 foi escrita na config que
        # ninguém lia). Prioridade: argumento explícito > config > default.
        self.min_buy_ask = float(min_buy_ask if min_buy_ask is not None
                                 else p.get("min_buy_ask", 0.60))
        self.max_buy_ask = float(max_buy_ask if max_buy_ask is not None
                                 else p.get("max_buy_ask", 0.85))
        self.threshold = float(p["threshold"])
        self.min_spread = float(p["min_spread"])
        self.bracket_half = float(p["bracket_half"])
        self.start_hour, self.end_hour = int(p["start_hour"]), int(p["end_hour"])
        self.outlier_cap = float(p["outlier_cap"])

        # Modelo: dict {cidade: models}, models direto, ou lazy-load fail-closed
        self.models = None
        if isinstance(models_rebound, dict):
            self.models = models_rebound.get(self.city, models_rebound if "model_lgb" in models_rebound else None)
        if self.models is None:
            try:
                from cassiopeia_predictor import load_models_rebound
                self.models = load_models_rebound(self.city)
            except Exception as e:
                print(f"[CassiopeiaEntry] {self.city}: SEM modelo rebound ({e}) -> BLOQUEIA entradas")

        # Histórico p/ prev7 (bootstrap best-effort do CSV)
        self.history_max = {}
        try:
            from cassiopeia_backtester import load_csv, _get_temp_col
            df = load_csv(self.city)
            tcol = _get_temp_col(df)
            dcol = df["timestamp"].dt.date
            self.history_max = {d: float(g[tcol].max()) for d, g in df.groupby(dcol)}
        except Exception:
            pass  # sem historico -> prev7 None -> fail-closed

    # ── helpers ──
    def _warn_once(self, key, msg):
        if key not in self._warned:
            print(f"[CassiopeiaEntry] {self.city}: {msg}")
            self._warned.add(key)

    def _get_prev7(self, d) -> Optional[float]:
        try:
            from cassiopeia_predictor import compute_prev7
            v = compute_prev7(self.history_max, d, self.city)
            return float(v) if v is not None else None
        except Exception:
            pass
        vals = [self.history_max[d - timedelta(days=i)] for i in range(1, 8)
                if (d - timedelta(days=i)) in self.history_max]
        return sum(vals) / len(vals) if vals else None

    @staticmethod
    def _find_bracket(market: dict, temp: float) -> Optional[dict]:
        """Bracket de mercado que contem temp (mesma logica do live find_bracket)."""
        if not market:
            return None
        return _official_find_bracket(market.get("brackets", []), float(temp), fallback=True)

    # ── interface do live ──
    def evaluate(self, p_ensemble: float = 0.0, hour: int = 12, market: dict = None,
                 running_max: float = None, forecast_agreement: dict = None,
                 slots_so_far: list = None, **kwargs) -> List[Dict[str, Any]]:
        if self.bought or self.models is None:
            return []
        if not market or not slots_so_far or len(slots_so_far) < 4:
            return []

        hour = int(hour)
        if not (self.start_hour <= hour <= self.end_hour):
            return []
        if running_max is None:
            running_max = max(float(s["temp_c"]) for s in slots_so_far)
        rmax = float(running_max)
        rmin = min(float(s["temp_c"]) for s in slots_so_far)
        if (rmax - rmin) < self.min_spread:
            return []

        # data local do dia (do ultimo slot; fallback hoje)
        d = slots_so_far[-1].get("date") or date.today()
        if isinstance(d, str):
            d = date.fromisoformat(d[:10])
        month, doy = d.month, d.timetuple().tm_yday

        prev7 = self._get_prev7(d)
        if prev7 is None:
            self._warn_once("prev7", "prev7 indisponivel -> BLOQUEIA (fail-closed)")
            return []
        if rmax > prev7 + self.outlier_cap:
            return []

        from cassiopeia_predictor import predict_rebound_prob
        current = dict(slots_so_far[-1])
        current["hour"] = hour
        current["prev_7d_avg_max"] = prev7
        try:
            _raw_p = predict_rebound_prob(self.models, list(slots_so_far),
                                          current, month, doy)["p_rebound"]
            if _raw_p is None:
                self._warn_once("ml_none", "p_rebound None (slots/hora insuficientes) -> BLOQUEIA")
                return []
            p = float(_raw_p)
            # D5: expor ao display (P(rebound) + janela proprias do modo cassiopeia)
            self.last_eval = {"p_rebound": p, "threshold": self.threshold,
                              "start_hour": self.start_hour,
                              "end_hour": self.end_hour,
                              "date": d.isoformat()}  # §92: p/ display filtrar staleness
        except Exception as e:
            self._warn_once("ml", f"ML erro: {e} -> BLOQUEIA")
            return []

        if p >= self.threshold:
            return []

        bracket = self._find_bracket(market, rmax)
        if not bracket:
            return []
        # max_buy_ask gate (o min é aplicado no live com book fresco)
        try:
            ask = float(bracket.get("ask") or bracket.get("price") or 0.0)
        except (TypeError, ValueError):
            return []
        # §92: expor ask/bracket ao display TG (last_eval) ANTES dos gates —
        # mesmo quando a compra é bloqueada por ask, o relatório mostra
        # onde está o mercado no bracket alvo.
        self.last_eval["ask"] = ask
        self.last_eval["bracket"] = bracket.get("label")
        if not (0.01 < ask <= self.max_buy_ask):
            return []

        return [{
            "size_usdc": self.parcel_size,
            "bracket": bracket,
            "strategy": "cassiopeia",
            "p_rebound": p,
            "reason": f"p_rebound={p:.2f}<{self.threshold} rmax={rmax:.1f}h{hour}",
        }]

    def mark_bought(self, price=0, record=None):
        self.bought = True
        self.record = record or {}

    def restore(self, rec: dict, mode: str = None):
        self.bought = True
        self.record = rec or {}
        self.strategy_used = (rec or {}).get("strategy") or "cassiopeia"

    def check_stop_loss(self, temp_now: float, market=None, **kw):
        return None  # sem exit antecipado — resolução a EOD como no backtest

    def is_bought(self): return self.bought
    def get_entry_record(self): return self.record
    @property
    def entry_record(self): return self.record

    def reset(self):
        self.bought = False
        self.record = None
        self._warned.clear()