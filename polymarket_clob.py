"""
polymarket_clob.py — V2 Híbrida Definitiva (Multi-Cidade)
=========================================================
Camada de acesso ao Polymarket CLOB usando o SDK unificado Polymarket.

Responsabilidades:
  - Derivar credenciais L2 a partir da private key Polygon
  - Consultar order book (bid, ask, spread, depth)
  - Enriquecer brackets do mercado com dados CLOB em tempo real
  - Colocar ordens (modo REAL) ou simular (modo PAPER)
  - Suporte a dry_run (assina ordem mas não submete)

Dependência:
    pip install polymarket-client

Variáveis de ambiente:
    POLY_PRIVATE_KEY=0x...    (obrigatória)
    POLY_FUNDER=0x...         (opcional — contas delegadas)
    POLY_API_KEY / POLY_API_SECRET / POLY_API_PASSPHRASE  (alternativa)
"""
from __future__ import annotations
from polymarket_clob_redeem_patch import RedeemMixin, POLYGON_RPC, CONDITIONAL_TOKENS_ADDR, CTF_EXCHANGE_ADDR, REDEEM_ABI
import json, logging, os, math, time
import threading
import io
import contextlib
from trade_ledger import append_event, make_position_id
from resolution_rules import bracket_contains
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)
CLOB_HOST = "https://clob.polymarket.com"
CHAIN_ID = 137
TICK_SIZE = 0.01
MIN_SIZE = 1.0
FEE_RATE = 0.0
# D0 (A4): fee Weather REAL = feeRate × p × (1-p) × shares (não linear!)
TAKER_FEE_RATE = 0.05

def weather_taker_fee(price: float, shares: float) -> float:
    """Fee taker Polymarket Weather: 0.05 × p × (1-p) × shares."""
    p = min(max(float(price), 0.0), 1.0)
    return 0.05 * p * (1.0 - p) * float(shares)

# Reduz ruído de libs externas no terminal live (ex: 404 "No orderbook exists").
logging.getLogger("polymarket").setLevel(logging.ERROR)
logging.getLogger("httpx").setLevel(logging.ERROR)
logging.getLogger("httpcore").setLevel(logging.ERROR)


def _city_from_slug(market_slug: str) -> str:
    if not market_slug:
        return ""
    prefix = market_slug.split("-on-")[0]
    marker = "-in-"
    if marker in prefix:
        return prefix.split(marker, 1)[1]
    return prefix


def round_to_tick(price: float, tick_size: float = TICK_SIZE, direction: str = "nearest") -> float:
    if tick_size <= 0:
        return round(price, 4)
    steps = price / tick_size
    if direction == "up":
        return round(math.ceil(steps) * tick_size, 4)
    if direction == "down":
        return round(math.floor(steps) * tick_size, 4)
    return round(round(steps) * tick_size, 4)

# ==========================================
# CLOUDFLARE BYPASS (apenas para Orderbooks Públicos)
# ==========================================
try:
    from curl_cffi import requests as cffi_requests
    import httpx as _httpx
    import json as _json

    class _FakeResponse:
        def __init__(self, status_code, headers, content):
            self.status_code = status_code
            self.headers = _httpx.Headers(headers)
            self._content = content
            self.url = ""
            self.method = "GET"
            self.reason_phrase = "OK" if status_code < 400 else "Error"

        @property
        def content(self):
            return self._content

        @property
        def text(self):
            return self._content.decode("utf-8")

        def json(self):
            return _json.loads(self.text)

        def raise_for_status(self):
            if self.status_code >= 400:
                raise _httpx.HTTPStatusError(
                    f"Erro {self.status_code}", request=None, response=self
                )
except ImportError:
    cffi_requests = None
    _httpx = None
    _json = None
    logger.warning("curl_cffi não instalado — Cloudflare bypass desactivado.")


class TradingMode(Enum):
    PAPER = "paper"
    REAL  = "real"


@dataclass
class OrderBookLevel:
    price: float
    size:  float


@dataclass
class OrderBook:
    token_id: str
    timestamp: float
    bids: list[OrderBookLevel] = field(default_factory=list)
    asks: list[OrderBookLevel] = field(default_factory=list)

    @property
    def best_bid(self): return self.bids[0].price if self.bids else None
    @property
    def best_ask(self): return self.asks[0].price if self.asks else None
    @property
    def mid(self):
        if self.best_bid and self.best_ask: return round((self.best_bid + self.best_ask) / 2, 4)
        return self.best_ask or self.best_bid
    @property
    def spread(self):
        if self.best_bid and self.best_ask: return round(self.best_ask - self.best_bid, 4)
        return None
    @property
    def bid_depth_usdc(self): return round(sum(l.price * l.size for l in self.bids[:5]), 2)
    @property
    def ask_depth_usdc(self): return round(sum(l.price * l.size for l in self.asks[:5]), 2)


@dataclass
class OrderResult:
    success: bool
    mode: TradingMode
    order_id: str | None = None
    token_id: str | None = None
    side: str = "BUY"
    outcome: str = "YES"
    price: float = 0.0
    size_usdc: float = 0.0
    shares: float = 0.0
    status: str = ""
    error: str | None = None
    timestamp: str = ""
    simulated: bool = False
    time_in_force: str = ""
    fee_usdc: float = 0.0

    def to_dict(self):
        return {
            "success": self.success, "mode": self.mode.value,
            "order_id": self.order_id, "token_id": self.token_id,
            "side": self.side, "outcome": self.outcome,
            "price": self.price, "size_usdc": self.size_usdc,
            "shares": self.shares, "status": self.status,
            "error": self.error, "timestamp": self.timestamp,
            "simulated": self.simulated, "time_in_force": self.time_in_force,
            "fee_usdc": self.fee_usdc,
        }


class ClobClient(RedeemMixin):
    """
    Cliente CLOB para o Polymarket (v2).

    Suporta PAPER (simulado), REAL (ordens reais) e dry_run (assina sem submeter).
    """

    def __init__(self, private_key: str, mode: TradingMode = TradingMode.PAPER,
                 max_daily_loss: float = 50.0, log_dir: Path = Path("live_bot_logs")):
        if not private_key and mode == TradingMode.REAL:
            raise ValueError("POLY_PRIVATE_KEY não definida.")
        self.mode = mode
        self.max_daily_loss = max_daily_loss
        # Optional hard rails for an isolated REAL pilot. These remain unset
        # for existing PAPER processes and therefore do not change their sizing.
        self.real_max_order_usdc = self._positive_env("CASS_REAL_MAX_ORDER_USDC")
        self.real_max_open_exposure_usdc = self._positive_env(
            "CASS_REAL_MAX_OPEN_EXPOSURE_USDC"
        )
        self.real_max_cumulative_loss_usdc = self._positive_env(
            "CASS_REAL_MAX_CUMULATIVE_LOSS_USDC"
        )
        self.log_dir = log_dir
        self.log_dir.mkdir(exist_ok=True)
        self._daily_loss = 0.0
        self._daily_date = None
        self._order_log = []
        self.positions = PositionManager(mode, log_dir)
        self._client = self._init_clob_client(
            private_key,
            allow_read_only=(mode == TradingMode.PAPER),
        )

    @staticmethod
    def _positive_env(name: str) -> float | None:
        raw = os.environ.get(name, "").strip()
        if not raw:
            return None
        try:
            value = float(raw)
        except ValueError as exc:
            raise ValueError(f"{name} tem de ser um número positivo") from exc
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"{name} tem de ser um número positivo")
        return value

    def _init_clob_client(self, private_key: str, allow_read_only: bool = False):
        """Cria cliente público PAPER ou cliente autenticado do SDK unificado."""
        from polymarket import PublicClient, SecureClient

        if private_key:
            from eth_account import Account

            funder = os.environ.get("POLY_FUNDER", "").strip()
            signature_type = int(os.environ.get("POLY_SIGNATURE_TYPE", 0))
            if signature_type != 0 and not funder:
                raise ValueError(
                    "POLY_FUNDER é obrigatório quando POLY_SIGNATURE_TYPE não é 0"
                )
            # EOA mode acts as the signer. For proxy/safe/deposit wallets, the
            # unified SDK classifies the configured funder and selects signing.
            wallet = funder if signature_type != 0 else Account.from_key(private_key).address
            client = SecureClient.create(private_key=private_key, wallet=wallet)
            logger.info("SDK unificado autenticado (%s)", client.wallet_type)
            return client

        if allow_read_only:
            logger.info("SDK unificado público inicializado (PAPER)")
            return PublicClient()
        return None

    def _coerce_orderbook_levels(self, levels):
        parsed = []
        if not levels:
            return parsed
        for lvl in levels:
            if isinstance(lvl, dict):
                price = lvl.get("price", lvl.get("p"))
                size = lvl.get("size", lvl.get("quantity", lvl.get("q")))
            else:
                price = getattr(lvl, "price", None)
                size = getattr(lvl, "size", None)
            if price is None or size is None:
                continue
            try:
                parsed.append(OrderBookLevel(float(price), float(size)))
            except Exception:
                continue
        return parsed

    def _orderbook_from_payload(self, token_id: str, payload) -> OrderBook | None:
        if payload is None:
            return None

        if isinstance(payload, dict):
            bids_raw = payload.get("bids") or payload.get("buy") or payload.get("bid") or []
            asks_raw = payload.get("asks") or payload.get("sell") or payload.get("ask") or []
        else:
            bids_raw = getattr(payload, "bids", []) or []
            asks_raw = getattr(payload, "asks", []) or []

        bids = sorted(self._coerce_orderbook_levels(bids_raw), key=lambda x: -x.price)
        asks = sorted(self._coerce_orderbook_levels(asks_raw), key=lambda x: x.price)
        if not bids and not asks:
            return None
        return OrderBook(token_id=token_id, timestamp=time.time(), bids=bids, asks=asks)

    def _fetch_public_orderbook(self, token_id: str):
        if cffi_requests is None:
            return None

        for params in ({"token_id": token_id}, {"asset_id": token_id}):
            try:
                resp = cffi_requests.get(
                    f"{CLOB_HOST}/book",
                    params=params,
                    timeout=15,
                    impersonate="chrome",
                )
                if resp.status_code >= 400:
                    continue
                payload = resp.json()
                if payload:
                    return payload
            except Exception:
                continue
        return None

    # ── Order Book ─────────────────────────────────────

    def get_orderbook(self, token_id: str) -> OrderBook | None:
        if not token_id or self._client is None:
            return None
        try:
            book_raw = self._client.get_order_book(token_id=token_id)
            book = self._orderbook_from_payload(token_id, book_raw)
            if book is not None:
                return book
        except Exception as e:
            if "404" not in str(e):
                logger.warning("get_orderbook falhou: %s", e)
            payload = self._fetch_public_orderbook(token_id)
            book = self._orderbook_from_payload(token_id, payload)
            if book is not None:
                return book
            return None

    def enrich_bracket(self, bracket: dict) -> dict:
        b = dict(bracket)
        token_id = b.get("token_id")
        if not token_id:
            b["ask"] = b.get("price")
            b["bid"] = b.get("price")
            b["spread"] = None
            b["book"] = None
            return b
        book = self.get_orderbook(token_id)
        if book and book.best_ask is not None:
            b["gamma_price"] = b.get("price")
            b["ask"] = book.best_ask
            b["bid"] = book.best_bid
            b["spread"] = book.spread
            b["mid"] = book.mid
            b["book"] = book
            b["price"] = book.best_ask
        else:
            estimated_price = float(b.get("price", 0.5) or 0.5)
            b["ask"] = estimated_price
            b["bid"] = round(estimated_price * 0.90, 4)
            b["spread"] = round(b["ask"] - b["bid"], 4)
            b["mid"] = estimated_price
            b["book"] = None
            # FIX: book NAO e real — consumidores devem recusar executar contra
            # estes valores estimados (verificar b.get("book_unavailable") antes de comprar)
            b["book_unavailable"] = True
            logger.warning("enrich_bracket sem order book real — preco estimado")
        return b

    # ── Gestão de risco ────────────────────────────────

    def _reset_daily_if_needed(self):
        today = date.today()
        if self._daily_date != today:
            self._daily_date = today
            self._daily_loss = 0.0

    def daily_loss(self):
        self._reset_daily_if_needed()
        return self._daily_loss

    def stop_loss_triggered(self):
        return self.daily_loss() >= self.max_daily_loss

    def record_loss(self, amount: float):
        self._reset_daily_if_needed()
        self._daily_loss = round(self._daily_loss + amount, 4)

    # ── dry_run helper ─────────────────────────────────

    def _dry_run_result(self, signed_order, side, token_id, price,
                        size_usdc, shares, otype, bracket_label, ts):
        """Constrói OrderResult para dry_run — assina mas NÃO submete."""
        try:
            order_dict = signed_order.dict() if hasattr(signed_order, 'dict') else dict(signed_order)
        except Exception:
            order_dict = {"_unserializable": str(signed_order)[:200]}

        logger.warning(
            "DRY-RUN — ordem assinada mas NÃO submetida. "
            "side=%s token_id=%s... price=%.4f size_usdc=$%.2f shares=%s type=%s",
            side, (token_id or "")[:16], price, size_usdc, shares, otype,
        )
        print(f"\n{'='*60}")
        print(f"DRY-RUN BUY (não submetido ao Polymarket)")
        print(f"{'='*60}")
        print(f"  token_id     : {token_id}")
        print(f"  side         : {side}")
        print(f"  price        : {price}")
        print(f"  size_usdc    : ${size_usdc:.2f}")
        print(f"  shares       : {shares}")
        print(f"  order_type   : {otype}")
        print(f"  bracket      : {bracket_label}")
        print(f"{'='*60}\n")

        return OrderResult(
            success=True, mode=TradingMode.REAL,
            order_id="DRYRUN-" + str(int(time.time())),
            token_id=token_id, side=side, outcome="YES",
            price=round(price, 4), size_usdc=round(size_usdc, 2),
            shares=shares, status="DRY_RUN_OK", timestamp=ts,
            simulated=True, error=None,
        )

    # ── Colocação de ordens ────────────────────────────

    def buy_yes(self, token_id: str, price: float, size_usdc: float,
                bracket_label: str = "", market_slug: str = "",
                order_type: str = "FOK", dry_run: bool = False,
                temp_lo: float | None = None, temp_hi: float | None = None,
                is_race: bool = False) -> OrderResult:
        from datetime import datetime as _dt
        self._reset_daily_if_needed()
        ts = _dt.now().isoformat()

        if self.stop_loss_triggered():
            return OrderResult(success=False, mode=self.mode,
                               error=f"Stop-loss diário atingido ({self._daily_loss:.2f} >= {self.max_daily_loss:.2f})",
                               timestamp=ts)

        if size_usdc < MIN_SIZE:
            return OrderResult(success=False, mode=self.mode,
                               error=f"Tamanho ${size_usdc:.2f} abaixo do mínimo ${MIN_SIZE:.2f}",
                               timestamp=ts)

        if market_slug:
            today = ts[:10]
            # Verificar se já existe posição aberta para este mercado hoje
            existing_position = next(
                (p for p in self.positions.open_positions() 
                 if p.market_slug == market_slug and p.date_opened == today),
                None
            )
            if existing_position:
                return OrderResult(
                    success=False, mode=self.mode,
                    error=f"Posição já aberta para {market_slug} hoje.",
                    timestamp=ts,
                )

        # ── Preço e Shares (com proteção para Market Orders FOK) ──
        if order_type.upper() == "FOK":
            # Em FOK, limita o worst-case price a +5% do ask atual, máximo 0.99
            # Isto previne slippage absurdo mas garante que a ordem não é killed à toa.
            protected_price = min(0.99, price * 1.05)
            buy_price = round_to_tick(protected_price, TICK_SIZE, "up")
        else:
            buy_price = round_to_tick(price, TICK_SIZE, "up")

        # FIX S1-2: em PAPER, o entry_ask deve ser o ASK REAL visto pelo entry
        # (o FOK-protected e um limite de execucao REAL; gravar +5% inflava
        #  as entradas paper e contamina a analise D7 por faixa de preco).
        paper_entry_ask = round_to_tick(price, TICK_SIZE, "up")

        # Always use floor for shares - CLOB requires whole shares
        shares = math.floor(size_usdc / buy_price)

        # Fase 3 (P0.6): validação centralizada — notional >= $1.00 (regras CLOB).
        # Mesmo que o caller (cassiopeia_live_bot) já valide, esta é a camada
        # defensiva no ClobClient. Bump up ao mínimo se insuficiente.
        from clob_sizing import compute_min_shares as _compute_min_shares
        _min_shares_clob = _compute_min_shares(buy_price)
        if shares < _min_shares_clob:
            shares = _min_shares_clob
            size_usdc = round(shares * buy_price, 2)
            logger.info(
                "size bumped to $%.2f (%d shares a %.2f¢) — mínimo CLOB $1.00",
                size_usdc, shares, buy_price * 100,
            )

        # Verificação de shares mínimas (evita enviar ordens inválidas de $1)
        if shares < 1:
            return OrderResult(
                success=False, mode=self.mode,
                error=f"Shares calculadas = 0 (size_usdc={size_usdc} insuficiente para price={buy_price})",
                timestamp=ts
            )

        # A pilot can set these caps in its own process environment. Check the
        # actual integer-share notional at the protected FOK limit, after the
        # minimum-size bump; never silently increase beyond the configured cap.
        if self.mode == TradingMode.REAL:
            projected_notional = round(shares * buy_price, 2)
            if (self.real_max_order_usdc is not None
                    and projected_notional > self.real_max_order_usdc + 1e-9):
                return OrderResult(
                    success=False, mode=self.mode, token_id=token_id,
                    price=buy_price, size_usdc=projected_notional,
                    shares=shares, status="BLOCKED_RISK_CAP", timestamp=ts,
                    error=(f"Notional projetado ${projected_notional:.2f} excede "
                           f"teto por ordem ${self.real_max_order_usdc:.2f}"),
                )
            if self.real_max_open_exposure_usdc is not None:
                open_exposure = sum(
                    max(0.0, float(getattr(p, "size_usdc", 0) or 0))
                    for p in self.positions.open_positions()
                )
                if open_exposure + projected_notional > self.real_max_open_exposure_usdc + 1e-9:
                    return OrderResult(
                        success=False, mode=self.mode, token_id=token_id,
                        price=buy_price, size_usdc=projected_notional,
                        shares=shares, status="BLOCKED_RISK_CAP", timestamp=ts,
                        error=(f"Exposição aberta projetada ${open_exposure + projected_notional:.2f} "
                               f"excede teto ${self.real_max_open_exposure_usdc:.2f}"),
                    )
            if self.real_max_cumulative_loss_usdc is not None:
                all_positions = self.positions.all_positions()
                realized_gross_losses_and_entry_fees = sum(
                    max(0.0, -float(getattr(p, "pnl_usd", 0) or 0))
                    + weather_taker_fee(float(getattr(p, "entry_ask", 0) or 0),
                                        float(getattr(p, "shares", 0) or 0))
                    for p in all_positions
                    if getattr(p, "status", None) != PositionStatus.OPEN
                )
                open_exposure = sum(
                    max(0.0, float(getattr(p, "size_usdc", 0) or 0))
                    for p in all_positions
                    if getattr(p, "status", None) == PositionStatus.OPEN
                )
                projected_pilot_loss = (
                    realized_gross_losses_and_entry_fees + open_exposure
                    + projected_notional + weather_taker_fee(buy_price, shares)
                )
                if projected_pilot_loss > self.real_max_cumulative_loss_usdc + 1e-9:
                    return OrderResult(
                        success=False, mode=self.mode, token_id=token_id,
                        price=buy_price, size_usdc=projected_notional,
                        shares=shares, status="BLOCKED_RISK_CAP", timestamp=ts,
                        error=(f"Perda bruta acumulada, exposição aberta e custo projetado "
                               f"seriam ${projected_pilot_loss:.2f}; "
                               f"teto do piloto ${self.real_max_cumulative_loss_usdc:.2f}"),
                    )

        # ── PAPER MODE ────────────────────────────────
        if self.mode == TradingMode.PAPER:
            position_id = make_position_id(
                ts[:10], market_slug.split("-on-")[0] if market_slug else "unknown",
                token_id, f"PAPER-{int(time.time())}", market_slug
            )
            result = OrderResult(
                success=True, mode=TradingMode.PAPER,
                order_id=f"PAPER-{int(time.time())}",
                token_id=token_id, side="BUY", outcome="YES",
                price=buy_price, size_usdc=round(size_usdc, 2),
                shares=shares, status="SIMULATED", timestamp=ts, simulated=True,
            )
            self._log_order(result, bracket_label)
            self.positions.add(Position(
                position_id=position_id,
                date_opened=ts[:10], opened_at=ts, bracket_label=bracket_label,
                token_id=token_id, entry_ask=paper_entry_ask,
                shares=shares, size_usdc=round(size_usdc, 2),
                mode="paper", order_id=result.order_id,
                market_slug=market_slug,
                temp_lo=float(temp_lo) if temp_lo is not None else 0.0,
                temp_hi=float(temp_hi) if temp_hi is not None else 0.0,
                is_race=is_race,
            ))
            append_event({
                "event_type": "BET_OPEN",
                "position_id": position_id,
                "city": _city_from_slug(market_slug),
                "market_slug": market_slug,
                "token_id": token_id,
                "order_id": result.order_id,
                "opened_at": ts,
                "entry_ask": paper_entry_ask,
                "shares": shares,
                "size_usdc": round(size_usdc, 2),
                "mode": "paper",
            })
            return result

        # ── REAL MODE: unified SDK, TAKER FOK only ─────────────────
        try:
            if order_type.upper() != "FOK":
                raise ValueError("Política TAKER-only: apenas ordens FOK são permitidas")
            if self._client is None:
                raise RuntimeError("Cliente autenticado do SDK unificado indisponível")

            # Build/sign first, then post explicitly. This avoids the SDK's
            # convenience allowance-recovery path from sending approval txs.
            signed_order = self._client.create_market_order(
                token_id=token_id,
                side="BUY",
                amount=projected_notional,
                max_spend=projected_notional,
                max_price=buy_price,
                order_type="FOK",
            )
            if dry_run:
                return self._dry_run_result(
                    signed_order, "BUY", token_id, buy_price, projected_notional,
                    shares, "FOK", bracket_label, ts,
                )
            response = self._client.post_order(signed_order)
            status = str(getattr(response, "status", "unknown"))
            order_id = getattr(response, "order_id", None)
            if getattr(response, "ok", False):
                filled_shares = float(response.taking_amount)
                filled_size_usdc = float(response.making_amount)
                actual_price = (filled_size_usdc / filled_shares
                                if filled_shares > 0 else buy_price)
                success = status == "matched" and filled_shares > 0 and filled_size_usdc > 0
                error = None if success else f"FOK não preenchido (status: {status})"
            else:
                filled_shares = filled_size_usdc = 0.0
                actual_price = buy_price
                status = str(getattr(response, "code", status))
                success = False
                error = str(getattr(response, "message", "Ordem FOK rejeitada"))

            result = OrderResult(
                success=success, mode=TradingMode.REAL,
                order_id=order_id, token_id=token_id, side="BUY", outcome="YES",
                price=actual_price,
                size_usdc=round(filled_size_usdc, 2),
                shares=filled_shares, status=status, timestamp=ts,
                simulated=False, error=error, time_in_force="FOK",
                fee_usdc=(weather_taker_fee(actual_price, filled_shares) if success else 0.0),
            )
        except Exception as e:
            result = OrderResult(
                success=False, mode=TradingMode.REAL,
                token_id=token_id, error=f"{type(e).__name__}: {e}",
                timestamp=ts, simulated=False,
            )
            logger.error("Falha ordem REAL (SDK unificado): %s", e)

        self._log_order(result, bracket_label)
        if result.success:
            position_id = make_position_id(
                ts[:10], market_slug.split("-on-")[0] if market_slug else "unknown",
                token_id, result.order_id or "", market_slug
            )
            self.positions.add(Position(
                position_id=position_id,
                date_opened=ts[:10], opened_at=ts, bracket_label=bracket_label,
                token_id=token_id, entry_ask=result.price,
                shares=result.shares, size_usdc=result.size_usdc,
                mode="real", order_id=result.order_id or "",
                market_slug=market_slug,
                temp_lo=float(temp_lo) if temp_lo is not None else 0.0,
                temp_hi=float(temp_hi) if temp_hi is not None else 0.0,
                is_race=is_race,
            ))
            append_event({
                "event_type": "BET_OPEN",
                "position_id": position_id,
                "city": _city_from_slug(market_slug),
                "market_slug": market_slug,
                "token_id": token_id,
                "order_id": result.order_id,
                "opened_at": ts,
                "entry_ask": result.price,
                "shares": result.shares,
                "size_usdc": result.size_usdc,
                "fee_usdc": result.fee_usdc,
                "execution_type": "TAKER",
                "order_type": result.time_in_force,
                "mode": "real",
            })
        return result

    # ── TAKER-only policy ─────────────────────────────────────────
    def place_maker_buy(self, token_id: str, price: float, shares: float) -> dict:
        """Compatibilidade com D4 legado: criação maker está bloqueada."""
        logger.error("Maker recusado pela política TAKER-only (token %s…)", (token_id or "")[:12])
        return {"error": "Maker desativado: política TAKER-only; nenhuma ordem foi submetida."}

    def poll_maker_order(self, order_id: str) -> dict:
        """Consulta read-only de uma ordem histórica; não cria nem altera ordens."""
        try:
            resp = self._client.get_order(order_id=order_id)
            return resp.model_dump(mode="json") if hasattr(resp, "model_dump") else dict(resp)
        except Exception as e:
            return {"error": str(e)[:200]}

    def cancel_maker_order(self, order_id: str) -> bool:
        if not order_id:
            return False
        try:
            response = self._client.cancel_order(order_id=order_id)
            return bool(getattr(response, "canceled", None) or getattr(response, "ok", False))
        except Exception as e:
            logger.warning("cancel maker %s falhou: %s", order_id, e)
            return False

    # ── Venda / Fecho de posição ──────────────────────

    def sell_yes(self, position: "Position", bid_price: float) -> "OrderResult":
        from datetime import datetime as _dt
        ts = _dt.now().isoformat()

        if position.status != PositionStatus.OPEN:
            return OrderResult(success=False, mode=self.mode,
                               error=f"Posição já fechada ({position.status.value})", timestamp=ts)

        sell_price = round_to_tick(bid_price, TICK_SIZE, "down")
        gross_pnl = (sell_price - position.entry_ask) * position.shares
        # D0: fee taker Weather = 0.05 × p × (1-p) × shares, sobre AMBOS os lados
        _fee_sell = weather_taker_fee(sell_price, position.shares)
        _fee_entry = weather_taker_fee(position.entry_ask, position.shares)
        pnl_usd = round(gross_pnl - _fee_sell - _fee_entry, 2)
        pnl_pct = round((sell_price / position.entry_ask - 1) * 100, 2) if position.entry_ask else 0.0

        # ── PAPER MODE ────────────────────────────────
        if self.mode == TradingMode.PAPER:
            position.status = PositionStatus.WON if pnl_usd >= 0 else PositionStatus.LOST
            position.pnl_usd = pnl_usd
            position.pnl_pct = pnl_pct
            position.current_mid = sell_price
            position.last_updated = ts
            self.positions._save()
            append_event({
                "event_type": "BET_CLOSE",
                "position_id": position.position_id,
                "market_slug": position.market_slug,
                "token_id": position.token_id,
                "closed_at": ts,
                "exit_price": sell_price,
                "realized_pnl_usd": pnl_usd,
                "result": position.status.value,
                "mode": "paper",
            })
            return OrderResult(
                success=True, mode=TradingMode.PAPER,
                order_id=f"PAPER-SELL-{int(time.time())}",
                token_id=position.token_id, side="SELL", outcome="YES",
                price=sell_price,
                size_usdc=round(sell_price * position.shares, 2),
                shares=position.shares, status="SIMULATED_SELL",
                timestamp=ts, simulated=True,
            )

        # ── REAL MODE: unified SDK, TAKER FOK only ─────────────────
        try:
            if self._client is None:
                raise RuntimeError("Cliente autenticado do SDK unificado indisponível")
            # A saída é FOK taker: aceita no máximo 5% de deterioração face ao
            # bid observado e deixa a posição aberta se o livro não preencher.
            min_price = round_to_tick(max(TICK_SIZE, bid_price * 0.95), TICK_SIZE, "down")
            signed_order = self._client.create_market_order(
                token_id=position.token_id, side="SELL", shares=position.shares,
                min_price=min_price, order_type="FOK",
            )
            response = self._client.post_order(signed_order)
            order_id = getattr(response, "order_id", None)
            status = str(getattr(response, "status", getattr(response, "code", "unknown")))
            success = bool(getattr(response, "ok", False)) and status == "matched"

            if success:
                filled_shares = float(response.making_amount)
                proceeds = float(response.taking_amount)
                if filled_shares <= 0 or proceeds <= 0:
                    raise RuntimeError("SDK reportou matched sem quantidades de fill válidas")
                fill_price = proceeds / filled_shares
                _gross = (fill_price - position.entry_ask) * position.shares
                _fee_s = weather_taker_fee(fill_price, position.shares)
                _fee_e = weather_taker_fee(position.entry_ask, position.shares)
                pnl_real = round(_gross - _fee_s - _fee_e, 2)
                position.status = PositionStatus.WON if pnl_real >= 0 else PositionStatus.LOST
                position.pnl_usd = pnl_real
                position.pnl_pct = round((fill_price / position.entry_ask - 1) * 100, 2) if position.entry_ask else None
                position.current_mid = fill_price
                position.last_updated = ts
                self.positions._save()
                append_event({
                    "event_type": "BET_CLOSE",
                    "position_id": position.position_id,
                    "market_slug": position.market_slug,
                    "token_id": position.token_id,
                    "closed_at": ts,
                    "exit_price": fill_price,
                    "gross_pnl_usd": round(_gross, 4),
                    "fees_usd": round(_fee_s + _fee_e, 4),
                    "realized_pnl_usd": pnl_real,
                    "result": position.status.value,
                    "mode": "real",
                    "execution_type": "TAKER",
                    "order_type": "FOK",
                })
            else:
                logger.warning(
                    "SELL FOK %s nao executada (status=%s) — posicao %s permanece ABERTA.",
                    order_id, status, position.position_id)

            return OrderResult(
                success=success, mode=TradingMode.REAL,
                order_id=order_id, token_id=position.token_id,
                side="SELL", outcome="YES",
                price=(fill_price if success else sell_price),
                size_usdc=round((fill_price if success else sell_price) * position.shares, 2),
                shares=position.shares, status=status,
                timestamp=ts, simulated=False,
                error=None if success else f"Status: {status}",
                time_in_force="FOK",
                fee_usdc=(weather_taker_fee(fill_price, position.shares) if success else 0.0),
            )
        except Exception as e:
            logger.error("Falha fechar REAL: %s", e)
            return OrderResult(
                success=False, mode=TradingMode.REAL,
                token_id=position.token_id, error=str(e),
                timestamp=ts, simulated=False,
            )

    # ── Saldo ──────────────────────────────────────────

    def get_usdc_balance(self) -> float | None:
        try:
            info = self._client.get_balance_allowance(asset_type="COLLATERAL")
            return int(info.balance) / 1e6
        except Exception as e:
            logger.error("get_usdc_balance falhou: %s", e)
            return None

    def has_open_orders(self, token_id: str) -> bool:
        try:
            orders = self._client.list_open_orders(token_id=token_id).iter_items()
            return any(str(getattr(o, "status", "")).lower() in ("live", "delayed")
                       for o in orders)
        except Exception:
            return False

    # ── Logging ────────────────────────────────────────

    def _log_order(self, result: OrderResult, bracket_label: str = ""):
        entry = result.to_dict()
        entry["bracket_label"] = bracket_label
        try:
            from importlib.metadata import version
            entry["sdk"] = {"name": "polymarket-client",
                            "version": version("polymarket-client")}
        except Exception:
            entry["sdk"] = {"name": "polymarket-client", "version": "unavailable"}
        self._order_log.append(entry)
        log_path = self.log_dir / f"orders_{date.today()}.json"
        try:
            existing = json.loads(log_path.read_text()) if log_path.exists() else []
            existing.append(entry)
            log_path.write_text(json.dumps(existing, indent=2))
        except Exception as e:
            logger.warning("Falha log: %s", e)

    def order_log(self):
        return list(self._order_log)


# ══════════════════════════════════════════════════════
#  POSIÇÕES — gestão de portfolio
# ══════════════════════════════════════════════════════

GAMMA_API = "https://gamma-api.polymarket.com"


class PositionStatus(Enum):
    OPEN    = "open"
    WON     = "won"
    LOST    = "lost"
    EXPIRED = "expired"
    UNKNOWN = "unknown"


@dataclass
class Position:
    position_id: str
    date_opened: str
    opened_at: str
    bracket_label: str
    token_id: str
    entry_ask: float
    shares: float
    size_usdc: float
    mode: str
    order_id: str
    market_slug: str = ""
    temp_lo: float = 0.0
    temp_hi: float = 0.0
    current_mid: float | None = None
    status: PositionStatus = PositionStatus.OPEN
    pnl_usd: float | None = None
    pnl_pct: float | None = None
    last_updated: str = ""
    is_race: bool = False

    def to_dict(self):
        return {
            "position_id": self.position_id,
            "date_opened": self.date_opened, "bracket_label": self.bracket_label,
            "opened_at": self.opened_at,
            "token_id": self.token_id, "entry_ask": self.entry_ask,
            "shares": self.shares, "size_usdc": self.size_usdc,
            "mode": self.mode, "order_id": self.order_id,
            "market_slug": self.market_slug,
            "temp_lo": self.temp_lo, "temp_hi": self.temp_hi,
            "current_mid": self.current_mid, "status": self.status.value,
            "pnl_usd": self.pnl_usd, "pnl_pct": self.pnl_pct,
            "last_updated": self.last_updated,
            "is_race": self.is_race,
        }

    @classmethod
    def from_dict(cls, d):
        p = cls(
            position_id=d.get("position_id", ""),
            date_opened=d["date_opened"],
            opened_at=d.get("opened_at", d.get("date_opened", "")),
            bracket_label=d["bracket_label"],
            token_id=d.get("token_id", ""), entry_ask=float(d["entry_ask"]),
            shares=float(d["shares"]), size_usdc=float(d["size_usdc"]),
            mode=d.get("mode", "paper"), order_id=d.get("order_id", ""),
            market_slug=d.get("market_slug", ""),
            temp_lo=float(d.get("temp_lo", 0.0)),
            temp_hi=float(d.get("temp_hi", 0.0)),
            current_mid=d.get("current_mid"),
            last_updated=d.get("last_updated", ""),
            is_race=bool(d.get("is_race", False)),
        )
        try:
            p.status = PositionStatus(d.get("status", "open"))
        except ValueError:
            p.status = PositionStatus.UNKNOWN
        p.pnl_usd = d.get("pnl_usd")
        p.pnl_pct = d.get("pnl_pct")
        if not p.position_id:
            p.position_id = make_position_id(
                p.date_opened, p.market_slug.split("-on-")[0] if p.market_slug else "unknown",
                p.token_id, p.order_id, p.market_slug
            )
        return p


# §107: um único store por ficheiro dentro do processo. Antes, cada cidade
# criava o seu PositionManager e o último _save() truncava as posições das
# outras cidades (clobber de 11/11).
_POSITION_MANAGERS: dict[tuple[str, str], "PositionManager"] = {}
_POSITION_MANAGERS_LOCK = threading.Lock()


class PositionManager:
    """Gere portfolio de posições abertas/fechadas com persistência em JSON."""

    def __new__(cls, mode: TradingMode, log_dir: Path = Path("live_bot_logs")):
        key = (mode.name, str(Path(log_dir).resolve()))
        with _POSITION_MANAGERS_LOCK:
            inst = _POSITION_MANAGERS.get(key)
            if inst is None:
                inst = super().__new__(cls)
                inst._shared_key = key
                _POSITION_MANAGERS[key] = inst
            return inst

    def __init__(self, mode: TradingMode, log_dir: Path = Path("live_bot_logs")):
        key = (mode.name, str(Path(log_dir).resolve()))
        if getattr(self, "_shared_key", None) == key and getattr(self, "_initialized", False):
            return
        self.mode = mode
        self.log_dir = log_dir
        self.log_dir.mkdir(exist_ok=True)
        fname = "paper_positions.json" if mode == TradingMode.PAPER else "real_positions.json"
        self._path = log_dir / fname
        self._lock = threading.RLock()
        self._positions = self._load()
        self._deduplicate()
        self._initialized = True

    def _load(self):
        if not self._path.exists():
            return []
        try:
            return [Position.from_dict(d) for d in json.loads(self._path.read_text())]
        except Exception as e:
            # FIX S1-7b: NUNCA evaporar silenciosamente — backup e aviso.
            # (16 posicoes do Dia 1 perderam-se assim num restart)
            backup = self._path.with_suffix(".json.corrupt")
            try:
                backup.write_text(self._path.read_text())
                logger.error("positions %s CORROMPIDO — backup em %s (%s)",
                             self._path, backup, e)
            except Exception:
                logger.error("positions %s ilegivel (%s)", self._path, e)
            return []

    def _save(self):
        with self._lock:
            try:
                data = json.dumps([p.to_dict() for p in self._positions], indent=2)
                tmp_path = self._path.with_name(self._path.name + ".tmp")
                tmp_path.write_text(data)
                os.replace(tmp_path, self._path)
            except Exception as e:
                logger.error("Falha ao guardar %s: %s", self._path, e)

    def add(self, position: Position):
        with self._lock:
            # Prevenir duplicados do mesmo dia
            if any(p.status == PositionStatus.OPEN and p.date_opened == position.date_opened
                   and p.token_id == position.token_id
                   and p.market_slug == position.market_slug
                   for p in self._positions):
                return
            self._positions.append(position)
            self._save()

    def _deduplicate(self):
        with self._lock:
            seen = set()
            cleaned = []
            changed = False
            for p in reversed(self._positions):
                if p.status == PositionStatus.OPEN:
                    key = (p.date_opened, p.token_id, p.market_slug)
                    if key in seen:
                        changed = True
                        continue
                    seen.add(key)
                cleaned.append(p)
            if changed:
                self._positions = list(reversed(cleaned))
                self._save()

    def open_positions(self):
        with self._lock:
            return [p for p in self._positions if p.status == PositionStatus.OPEN]

    def all_positions(self):
        with self._lock:
            return list(self._positions)

    def today_position(self):
        today = date.today().isoformat()
        for p in reversed(self._positions):
            if p.date_opened == today:
                return p
        return None

    def refresh(self, clob_client):
        from datetime import datetime as _dt
        now_str = _dt.now().isoformat()
        for pos in self.open_positions():
            # PAPER: NUNCA resolver aqui. O settle oficial é responsabilidade
            # do live bot, depois do dia fechar. O bloco antigo resolvia
            # posições de dias passados com history_max (WU) e fechava-as
            # prematuramente, sem BET_CLOSE.
            if self.mode == TradingMode.REAL and pos.market_slug:
                resolved, won = self._check_resolution(pos)
                if resolved:
                    self._close_position(
                        pos, won, 1.0 if won else 0.0,
                        source="official_gamma",
                    )
                    continue

            mid = self._get_mid(pos, clob_client)
            if mid is not None:
                pos.current_mid = round(mid, 4)
                _mark = (mid - pos.entry_ask) * pos.shares
                if self.mode == TradingMode.REAL:
                    _mark -= weather_taker_fee(pos.entry_ask, pos.shares)
                    _mark -= weather_taker_fee(mid, pos.shares)
                pos.pnl_usd = round(_mark, 2)
                pos.pnl_pct = round((mid / pos.entry_ask - 1) * 100, 2) if pos.entry_ask else None
            pos.last_updated = now_str
        self._save()

    def _close_position(self, pos: "Position", won: bool, exit_price: float,
                        source: str) -> bool:
        """Fecha uma posição OPEN de forma idempotente e regista BET_CLOSE."""
        from datetime import datetime as _dt

        with self._lock:
            if pos.status != PositionStatus.OPEN:
                return False

            entry = float(getattr(pos, "entry_ask", 0) or 0)
            shares = float(getattr(pos, "shares", 0) or 0)
            size = float(getattr(pos, "size_usdc", 0) or 0)
            gross_pnl = (float(exit_price) - entry) * shares
            fees = 0.0
            if self.mode == TradingMode.REAL:
                fees = weather_taker_fee(entry, shares) + weather_taker_fee(exit_price, shares)
            net_pnl = round(gross_pnl - fees, 2)
            if won:
                pos.status = PositionStatus.WON
                pos.pnl_usd = net_pnl
                pos.pnl_pct = round(net_pnl / size * 100, 2) if size else None
            else:
                # FIX CONTAB: loss = capital investido (entry*shares)
                pos.status = PositionStatus.LOST
                pos.pnl_usd = net_pnl if (entry and shares) else round(-size - fees, 2)
                pos.pnl_pct = round(pos.pnl_usd / size * 100, 2) if size else -100.0

            pos.current_mid = None
            pos.last_updated = _dt.now().isoformat()
            self._save()
            append_event({
                "event_type": "BET_CLOSE",
                "position_id": pos.position_id,
                "market_slug": pos.market_slug,
                "token_id": pos.token_id,
                "closed_at": pos.last_updated,
                "exit_price": float(exit_price),
                "gross_pnl_usd": round(gross_pnl, 4),
                "fees_usd": round(fees, 4),
                "realized_pnl_usd": pos.pnl_usd,
                "result": pos.status.value,
                "mode": "paper" if self.mode == TradingMode.PAPER else "real",
                "resolution_source": source,
                "source": source,
                "redemption_required": bool(won and self.mode == TradingMode.REAL),
            })
            return True

    def resolve_paper_position_official(self, pos: "Position", won: bool) -> bool:
        """§98: resolve pela resolução OFICIAL do mercado (Gamma), sem peak."""
        return self._close_position(pos, won, 1.0 if won else 0.0,
                                    source="official")

    def resolve_paper_position(self, pos: "Position", peak_temp: float) -> bool:
        # Regras oficiais: half-up; bracket X cobre [X-0.5, X+0.5).
        won = bracket_contains(pos.temp_lo, pos.temp_hi, peak_temp)
        return self._close_position(pos, won, 1.0 if won else 0.0,
                                    source="peak_no_slug")

    def _get_mid(self, pos, clob_client):
        if not clob_client or not pos.token_id:
            return None
        try:
            book = clob_client.get_orderbook(pos.token_id)
            if book:
                return book.best_bid or book.mid
        except Exception:
            pass
        return None

    def _check_resolution(self, pos):
        import requests as _req
        if not pos.market_slug:
            return False, False
        try:
            r = _req.get(f"{GAMMA_API}/events", params={"slug": pos.market_slug}, timeout=10)
            r.raise_for_status()
            events = r.json()
            if not events:
                return False, False
            event = events[0] if isinstance(events, list) else events
            for m in event.get("markets", []):
                tids = m.get("clobTokenIds", "[]")
                if isinstance(tids, str):
                    try:
                        tids = json.loads(tids)
                    except Exception:
                        tids = []
                if pos.token_id not in (tids or []):
                    continue
                if not m.get("resolved", False):
                    return False, False
                winner = str(m.get("winner") or "").strip().lower()
                if not winner:
                    # FIX: resolved=true mas winner ainda null (delay da API)
                    # -> NAO marcar LOST; aguarda proximo refresh
                    logger.warning("Mercado %s resolved sem winner; a aguardar.",
                                   pos.market_slug)
                    return False, False
                return True, winner in ("yes", "true", "1")
        except Exception:
            pass
        return False, False

    def resolve_closed_positions(self, current_date: date) -> None:
        """
        Verifica se posições abertas de dias anteriores foram resolvidas.
        Em PAPER: compara temperatura contra bracket. Em REAL: refresh() trata.
        """
        # Em PAPER, a resolução é feita pelo live_bot com contexto da cidade.
        # Em REAL, o refresh() já cuida disto via API.
        return None

    def pnl_summary(self):
        invested = sum(p.size_usdc for p in self._positions)
        pnl_sum = sum(p.pnl_usd for p in self._positions if p.pnl_usd is not None)
        return {
            "total_invested": round(invested, 2),
            "total_pnl_usd": round(pnl_sum, 2),
            "total_pnl_pct": round(pnl_sum / invested * 100, 2) if invested else 0.0,
            "n_open": sum(1 for p in self._positions if p.status == PositionStatus.OPEN),
            "n_won": sum(1 for p in self._positions if p.status == PositionStatus.WON),
            "n_lost": sum(1 for p in self._positions if p.status == PositionStatus.LOST),
            "n_unknown": sum(1 for p in self._positions if p.status == PositionStatus.UNKNOWN),
        }
