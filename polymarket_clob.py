"""
polymarket_clob.py — V2 Híbrida Definitiva (Multi-Cidade)
=========================================================
Camada de acesso ao Polymarket CLOB usando py_clob_client_v2.

Responsabilidades:
  - Derivar credenciais L2 a partir da private key Polygon
  - Consultar order book (bid, ask, spread, depth)
  - Enriquecer brackets do mercado com dados CLOB em tempo real
  - Colocar ordens (modo REAL) ou simular (modo PAPER)
  - Suporte a dry_run (assina ordem mas não submete)

Dependência:
    pip install py_clob_client_v2

Variáveis de ambiente:
    POLY_PRIVATE_KEY=0x...    (obrigatória)
    POLY_FUNDER=0x...         (opcional — contas delegadas)
    POLY_API_KEY / POLY_API_SECRET / POLY_API_PASSPHRASE  (alternativa)
"""
from __future__ import annotations
import json, logging, os, math, time, sys
import io
import contextlib
from trade_ledger import append_event, make_position_id
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)
CLOB_HOST = "https://clob.polymarket.com"
CHAIN_ID = 137
TICK_SIZE = 0.01
MIN_SIZE = 5.0
FEE_RATE = 0.0
TAKER_FEE_RATE = float(os.environ.get("POLY_TAKER_FEE_RATE", "0.02"))

# Reduz ruído de libs externas no terminal live (ex: 404 "No orderbook exists").
logging.getLogger("py_clob_client_v2").setLevel(logging.ERROR)
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

    def to_dict(self):
        return {
            "success": self.success, "mode": self.mode.value,
            "order_id": self.order_id, "token_id": self.token_id,
            "side": self.side, "outcome": self.outcome,
            "price": self.price, "size_usdc": self.size_usdc,
            "shares": self.shares, "status": self.status,
            "error": self.error, "timestamp": self.timestamp,
            "simulated": self.simulated,
        }


class ClobClient:
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

    def _init_clob_client(self, private_key: str, allow_read_only: bool = False):
        """Inicializa py_clob_client_v2 e obtém credenciais."""
        from py_clob_client_v2 import ClobClient as _ClobClient

        funder = os.environ.get("POLY_FUNDER", "").strip()
        signature_type = 2 if funder else int(os.environ.get("POLY_SIGNATURE_TYPE", 0))

        client_kwargs = {"host": CLOB_HOST, "chain_id": CHAIN_ID}
        if private_key:
            client_kwargs["key"] = private_key
        elif allow_read_only:
            read_only_attempts = [
                {"host": CLOB_HOST, "chain_id": CHAIN_ID, "key": ""},
                {"host": CLOB_HOST, "chain_id": CHAIN_ID},
            ]
            last_error = None
            for kwargs in read_only_attempts:
                try:
                    client = _ClobClient(**kwargs)
                    logger.info("CLOB read-only client inicializado (PAPER)")
                    return client
                except Exception as e:
                    last_error = e
            logger.warning("CLOB read-only init falhou: %s", last_error)
            return None
        else:
            return None
        if signature_type != 0:
            client_kwargs["signature_type"] = signature_type
            client_kwargs["funder"] = funder

        creds_ok = False
        last_error = None

        # Tentativa 1: derive via funder (proxy wallet)
        if funder:
            try:
                client = _ClobClient(**client_kwargs)
                creds = client.derive_api_key()
                client.set_api_creds(creds)
                logger.info("Creds via derive_api_key (Proxy)")
                creds_ok = True
            except Exception as e:
                last_error = e

        # Tentativa 2: creds via env vars
        if not creds_ok:
            env_key = os.environ.get("POLY_API_KEY", "")
            env_secret = os.environ.get("POLY_API_SECRET", "")
            env_pass = os.environ.get("POLY_API_PASSPHRASE", "")
            if env_key and env_secret and env_pass:
                try:
                    from py_clob_client_v2 import ApiCreds
                    client_kwargs["creds"] = ApiCreds(
                        api_key=env_key, api_secret=env_secret, api_passphrase=env_pass
                    )
                    client = _ClobClient(**client_kwargs)
                    creds_ok = True
                except Exception as e:
                    last_error = e
                    client_kwargs.pop("creds", None)

        # Tentativa 3: create_or_derive
        if not creds_ok:
            try:
                client = _ClobClient(**client_kwargs)
                for m in ["create_or_derive_api_key", "derive_api_key"]:
                    if hasattr(client, m):
                        creds = getattr(client, m)()
                        client.set_api_creds(creds)
                        creds_ok = True
                        break
            except Exception as e:
                last_error = e

        if not creds_ok and self.mode == TradingMode.REAL:
            raise RuntimeError(f"Impossível obter creds REAL! Erro: {last_error}")

        return client

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
            # py_clob_client_v2 por vezes escreve 404 diretamente em stderr.
            # Silenciamos apenas esta chamada para não poluir a dashboard.
            with contextlib.redirect_stderr(io.StringIO()):
                book_raw = self._client.get_order_book(token_id)
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
                order_type: str = "GTC", dry_run: bool = False,
                temp_lo: float | None = None, temp_hi: float | None = None) -> OrderResult:
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
            if any(
                p.status == PositionStatus.OPEN
                and p.date_opened == today
                and p.market_slug == market_slug
                for p in self.positions.open_positions()
            ):
                return OrderResult(
                    success=False, mode=self.mode,
                    error=f"Posição já aberta para {market_slug} hoje.",
                    timestamp=ts,
                )

        buy_price = round_to_tick(price, TICK_SIZE, "up")
        shares = math.floor(size_usdc / buy_price) if order_type.upper() == "FOK" else round(size_usdc / buy_price, 4)

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
                token_id=token_id, entry_ask=buy_price,
                shares=shares, size_usdc=round(size_usdc, 2),
                mode="paper", order_id=result.order_id,
                market_slug=market_slug,
                temp_lo=float(temp_lo) if temp_lo is not None else 0.0,
                temp_hi=float(temp_hi) if temp_hi is not None else 0.0,
            ))
            append_event({
                "event_type": "BET_OPEN",
                "position_id": position_id,
                "city": _city_from_slug(market_slug),
                "market_slug": market_slug,
                "token_id": token_id,
                "order_id": result.order_id,
                "opened_at": ts,
                "entry_ask": buy_price,
                "shares": shares,
                "size_usdc": round(size_usdc, 2),
                "mode": "paper",
            })
            return result

        # ── REAL MODE ─────────────────────────────────
        try:
            from py_clob_client_v2 import OrderArgs, Side, OrderType, PartialCreateOrderOptions

            if order_type.upper() == "FOK":
                order_args = OrderArgs(token_id=token_id, price=buy_price, side=Side.BUY, size=shares)
                signed_order = self._client.create_market_order(order_args)
                if dry_run:
                    return self._dry_run_result(
                        signed_order, "BUY", token_id, buy_price, size_usdc, shares, "FOK", bracket_label, ts,
                    )
                response = self._client.create_and_post_market_order(order_args=order_args)
            else:
                order_args = OrderArgs(token_id=token_id, price=buy_price, side=Side.BUY, size=shares)
                signed_order = self._client.create_order(order_args)
                if dry_run:
                    return self._dry_run_result(
                        signed_order, "BUY", token_id, buy_price, size_usdc, shares, "GTC", bracket_label, ts,
                    )
                response = self._client.create_and_post_order(
                    order_args=order_args,
                    options=PartialCreateOrderOptions(tick_size=str(TICK_SIZE)),
                    order_type=OrderType.GTC,
                )

            order_id = response.get("orderID") or response.get("id") or "?"
            status = response.get("status", "unknown")

            def _coerce_float(value):
                try:
                    if value is None:
                        return None
                    return float(value)
                except Exception:
                    return None

            filled_shares = None
            filled_size_usdc = None
            for key in (
                "filledShares", "filled_shares", "sizeFilled", "size_filled",
                "filledSize", "filled_size", "filledAmount", "filled_amount",
            ):
                if key not in response:
                    continue
                val = _coerce_float(response.get(key))
                if val is None:
                    continue
                if "share" in key.lower():
                    filled_shares = val
                else:
                    filled_size_usdc = val

            if filled_shares is None and filled_size_usdc is not None and price > 0:
                filled_shares = filled_size_usdc / price
            if filled_size_usdc is None and filled_shares is not None:
                filled_size_usdc = filled_shares * price

            actual_shares = filled_shares if filled_shares is not None else shares
            actual_size_usdc = filled_size_usdc if filled_size_usdc is not None else size_usdc
            if status == "live" and filled_shares is None and filled_size_usdc is None:
                logger.warning(
                    "Ordem LIVE sem metadados de fill; a registar tamanho solicitado "
                    "como fallback (order_id=%s, token_id=%s)",
                    order_id, token_id,
                )

            if order_type.upper() == "FOK":
                _success = status == "matched"
            else:
                _success = status in ("matched", "live", "delayed")

            result = OrderResult(
                success=_success, mode=TradingMode.REAL,
                order_id=order_id, token_id=token_id,
                side="BUY", outcome="YES",
                price=buy_price, size_usdc=round(actual_size_usdc, 2),
                shares=actual_shares, status=status, timestamp=ts,
                simulated=False,
                error=None if _success else f"Status: {status}",
            )
        except Exception as e:
            result = OrderResult(
                success=False, mode=TradingMode.REAL,
                token_id=token_id, error=str(e),
                timestamp=ts, simulated=False,
            )
            logger.error("Falha ordem REAL: %s", e)

        self._log_order(result, bracket_label)
        if result.success:
            position_id = make_position_id(
                ts[:10], market_slug.split("-on-")[0] if market_slug else "unknown",
                token_id, result.order_id or "", market_slug
            )
            self.positions.add(Position(
                position_id=position_id,
                date_opened=ts[:10], opened_at=ts, bracket_label=bracket_label,
                token_id=token_id, entry_ask=buy_price,
                shares=actual_shares, size_usdc=round(actual_size_usdc, 2),
                mode="real", order_id=result.order_id or "",
                market_slug=market_slug,
                temp_lo=float(temp_lo) if temp_lo is not None else 0.0,
                temp_hi=float(temp_hi) if temp_hi is not None else 0.0,
            ))
            append_event({
                "event_type": "BET_OPEN",
                "position_id": position_id,
                "city": _city_from_slug(market_slug),
                "market_slug": market_slug,
                "token_id": token_id,
                "order_id": result.order_id,
                "opened_at": ts,
                "entry_ask": buy_price,
                "shares": actual_shares,
                "size_usdc": round(actual_size_usdc, 2),
                "mode": "real",
            })
        return result

    # ── Venda / Fecho de posição ──────────────────────

    def sell_yes(self, position: "Position", bid_price: float) -> "OrderResult":
        from datetime import datetime as _dt
        ts = _dt.now().isoformat()

        if position.status != PositionStatus.OPEN:
            return OrderResult(success=False, mode=self.mode,
                               error=f"Posição já fechada ({position.status.value})", timestamp=ts)

        sell_price = round_to_tick(bid_price, TICK_SIZE, "down")
        gross_pnl = (sell_price - position.entry_ask) * position.shares
        pnl_usd = round(gross_pnl - abs(gross_pnl) * TAKER_FEE_RATE, 2)
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

        # ── REAL MODE ─────────────────────────────────
        try:
            from py_clob_client_v2 import OrderArgs, Side, OrderType, PartialCreateOrderOptions

            order_args = OrderArgs(
                token_id=position.token_id,
                price=sell_price,
                size=position.shares,
                side=Side.SELL,
            )
            response = self._client.create_and_post_order(
                order_args=order_args,
                options=PartialCreateOrderOptions(tick_size=str(TICK_SIZE)),
                order_type=OrderType.GTC,
            )
            order_id = response.get("orderID") or response.get("id") or "?"
            status = response.get("status", "unknown")
            success = status in ("matched", "live", "delayed")

            if success:
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
                    "mode": "real",
                })

            return OrderResult(
                success=success, mode=TradingMode.REAL,
                order_id=order_id, token_id=position.token_id,
                side="SELL", outcome="YES",
                price=sell_price,
                size_usdc=round(sell_price * position.shares, 2),
                shares=position.shares, status=status,
                timestamp=ts, simulated=False,
                error=None if success else f"Status: {status}",
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
            from py_clob_client_v2.clob_types import BalanceAllowanceParams, AssetType
            info = self._client.get_balance_allowance(
                params=BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
            )
            return int(info.get("balance", "0")) / 1e6
        except Exception as e:
            logger.error("get_usdc_balance falhou: %s", e)
            return None

    def has_open_orders(self, token_id: str) -> bool:
        try:
            orders = self._client.get_open_orders()
            return any(
                o.get("asset_id") == token_id and o.get("status") in ("live", "delayed")
                for o in orders
            ) if orders else False
        except Exception:
            return False

    # ── Logging ────────────────────────────────────────

    def _log_order(self, result: OrderResult, bracket_label: str = ""):
        entry = result.to_dict()
        entry["bracket_label"] = bracket_label
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


class PositionManager:
    """Gere portfolio de posições abertas/fechadas com persistência em JSON."""

    def __init__(self, mode: TradingMode, log_dir: Path = Path("live_bot_logs")):
        self.mode = mode
        self.log_dir = log_dir
        self.log_dir.mkdir(exist_ok=True)
        fname = "paper_positions.json" if mode == TradingMode.PAPER else "real_positions.json"
        self._path = log_dir / fname
        self._positions = self._load()
        self._deduplicate()

    def _load(self):
        if not self._path.exists():
            return []
        try:
            return [Position.from_dict(d) for d in json.loads(self._path.read_text())]
        except Exception:
            return []

    def _save(self):
        try:
            data = json.dumps([p.to_dict() for p in self._positions], indent=2)
            tmp_path = self._path.with_name(self._path.name + ".tmp")
            tmp_path.write_text(data)
            os.replace(tmp_path, self._path)
        except Exception:
            pass

    def add(self, position: Position):
        # Prevenir duplicados do mesmo dia
        if any(p.status == PositionStatus.OPEN and p.date_opened == position.date_opened
               and p.token_id == position.token_id
               and p.market_slug == position.market_slug
               for p in self._positions):
            return
        self._positions.append(position)
        self._save()

    def _deduplicate(self):
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
        return [p for p in self._positions if p.status == PositionStatus.OPEN]

    def all_positions(self):
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
            mid = self._get_mid(pos, clob_client)
            if mid is not None:
                pos.current_mid = round(mid, 4)
                pos.pnl_usd = round((mid - pos.entry_ask) * pos.shares, 2)
                pos.pnl_pct = round((mid / pos.entry_ask - 1) * 100, 2) if pos.entry_ask else None
            if self.mode == TradingMode.REAL and pos.market_slug:
                resolved, won = self._check_resolution(pos)
                if resolved:
                    if won:
                        pos.status = PositionStatus.WON
                        pos.pnl_usd = round((1.0 - pos.entry_ask) * pos.shares, 2)
                        pos.pnl_pct = round((1.0 / pos.entry_ask - 1) * 100, 2)
                    else:
                        pos.status = PositionStatus.LOST
                        pos.pnl_usd = round(-pos.size_usdc, 2)
                        pos.pnl_pct = -100.0
            pos.last_updated = now_str
        self._save()

    def resolve_paper_position(self, pos: "Position", peak_temp: float) -> bool:
        from datetime import datetime as _dt

        if pos.status != PositionStatus.OPEN:
            return False

        peak_int = int(math.floor(peak_temp))
        if pos.temp_hi >= 99:
            won = peak_int >= int(math.floor(pos.temp_lo))
        elif pos.temp_lo <= -99:
            won = peak_int <= int(math.floor(pos.temp_hi))
        else:
            won = int(math.floor(pos.temp_lo)) <= peak_int <= int(math.floor(pos.temp_hi))

        if won:
            pos.status = PositionStatus.WON
            gross = (1.0 - pos.entry_ask) * pos.shares
            pos.pnl_usd = round(gross - abs(gross) * TAKER_FEE_RATE, 2)
            pos.pnl_pct = round((1.0 / pos.entry_ask - 1) * 100, 2) if pos.entry_ask else None
        else:
            pos.status = PositionStatus.LOST
            gross = -pos.size_usdc
            pos.pnl_usd = round(gross - abs(gross) * TAKER_FEE_RATE, 2)
            pos.pnl_pct = -100.0

        pos.current_mid = None
        pos.last_updated = _dt.now().isoformat()
        self._save()
        append_event({
            "event_type": "BET_CLOSE",
            "position_id": pos.position_id,
            "market_slug": pos.market_slug,
            "token_id": pos.token_id,
            "closed_at": pos.last_updated,
            "exit_price": None,
            "realized_pnl_usd": pos.pnl_usd,
            "result": pos.status.value,
            "mode": "paper",
            "source": "resolve_paper_position",
        })
        return True

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
                winner = str(m.get("winner") or "").lower()
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
