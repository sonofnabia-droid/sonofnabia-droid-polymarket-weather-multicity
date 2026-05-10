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
        @property
        def content(self): return self._content
        @property
        def text(self): return self._content.decode('utf-8')
        def json(self): return _json.loads(self.text)
        def raise_for_status(self):
            if self.status_code >= 400:
                raise _httpx.HTTPStatusError(f'Erro {self.status_code}', request=None, response=self)

    _orig_send = _httpx.Client.send
    def _patched_send(self, request, **kwargs):
        url_str = str(request.url)
        if 'polymarket.com' in url_str and '/book' in url_str:
            bad = ['user-agent', 'accept-encoding', 'host', 'connection', 'transfer-encoding']
            clean = {k: v for k, v in request.headers.items() if k.lower() not in bad}
            if not request.content: clean.pop('content-length', None)
            resp = cffi_requests.request(method=request.method, url=url_str, headers=clean, data=request.content, impersonate='chrome')
            return _FakeResponse(resp.status_code, dict(resp.headers), resp.content)
        return _orig_send(self, request, **kwargs)
    _httpx.Client.send = _patched_send
    logger.info("Cloudflare Bypass ativo (apenas /book).")
except ImportError:
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
        self._client = self._init_clob_client(private_key) if private_key else None

    def _init_clob_client(self, private_key: str):
        """Inicializa py_clob_client_v2 e obtém credenciais."""
        from py_clob_client_v2 import ClobClient as _ClobClient

        funder = os.environ.get("POLY_FUNDER", "").strip()
        signature_type = 2 if funder else int(os.environ.get("POLY_SIGNATURE_TYPE", 0))

        client_kwargs = {"host": CLOB_HOST, "chain_id": CHAIN_ID, "key": private_key}
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

    # ── Order Book ─────────────────────────────────────

    def get_orderbook(self, token_id: str) -> OrderBook | None:
        if not token_id or self._client is None:
            return None
        try:
            book_raw = self._client.get_order_book(token_id)
            if isinstance(book_raw, dict):
                return None
            bids = sorted(
                [OrderBookLevel(float(b.price), float(b.size)) for b in (book_raw.bids or [])],
                key=lambda x: -x.price,
            )
            asks = sorted(
                [OrderBookLevel(float(a.price), float(a.size)) for a in (book_raw.asks or [])],
                key=lambda x: x.price,
            )
            return OrderBook(token_id=token_id, timestamp=time.time(), bids=bids, asks=asks)
        except Exception as e:
            if "404" not in str(e):
                logger.warning("get_orderbook falhou: %s", e)
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
            b["ask"] = book.best_ask
            b["bid"] = book.best_bid
            b["spread"] = book.spread
            b["mid"] = book.mid
            b["book"] = book
            b["price"] = book.best_ask
        else:
            b["ask"] = b.get("price")
            b["bid"] = b.get("price")
            b["spread"] = None
            b["mid"] = b.get("price")
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
                order_type: str = "FOK", dry_run: bool = False,
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

        shares = math.floor(size_usdc / price) if order_type.upper() == "FOK" else round(size_usdc / price, 4)

        # ── PAPER MODE ────────────────────────────────
        if self.mode == TradingMode.PAPER:
            result = OrderResult(
                success=True, mode=TradingMode.PAPER,
                order_id=f"PAPER-{int(time.time())}",
                token_id=token_id, side="BUY", outcome="YES",
                price=round(price, 4), size_usdc=round(size_usdc, 2),
                shares=shares, status="SIMULATED", timestamp=ts, simulated=True,
            )
            self._log_order(result, bracket_label)
            self.positions.add(Position(
                date_opened=ts[:10], bracket_label=bracket_label,
                token_id=token_id, entry_ask=round(price, 4),
                shares=shares, size_usdc=round(size_usdc, 2),
                mode="paper", order_id=result.order_id,
                market_slug=market_slug,
                temp_lo=float(temp_lo) if temp_lo is not None else 0.0,
                temp_hi=float(temp_hi) if temp_hi is not None else 0.0,
            ))
            return result

        # ── REAL MODE ─────────────────────────────────
        try:
            from py_clob_client_v2 import OrderArgs, Side, OrderType, PartialCreateOrderOptions

            if order_type.upper() == "FOK":
                order_args = OrderArgs(token_id=token_id, price=price, side=Side.BUY, size=shares)
                signed_order = self._client.create_market_order(order_args)
                if dry_run:
                    return self._dry_run_result(
                        signed_order, "BUY", token_id, price, size_usdc, shares, "FOK", bracket_label, ts,
                    )
                response = self._client.create_and_post_market_order(order_args=order_args)
            else:
                order_args = OrderArgs(token_id=token_id, price=price, side=Side.BUY, size=shares)
                signed_order = self._client.create_order(order_args)
                if dry_run:
                    return self._dry_run_result(
                        signed_order, "BUY", token_id, price, size_usdc, shares, "GTC", bracket_label, ts,
                    )
                response = self._client.create_and_post_order(
                    order_args=order_args,
                    options=PartialCreateOrderOptions(tick_size=str(TICK_SIZE)),
                    order_type=OrderType.GTC,
                )

            order_id = response.get("orderID") or response.get("id") or "?"
            status = response.get("status", "unknown")

            if order_type.upper() == "FOK":
                _success = status == "matched"
            else:
                _success = status in ("matched", "live", "delayed")

            result = OrderResult(
                success=_success, mode=TradingMode.REAL,
                order_id=order_id, token_id=token_id,
                side="BUY", outcome="YES",
                price=round(price, 4), size_usdc=round(size_usdc, 2),
                shares=shares, status=status, timestamp=ts,
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
            self.positions.add(Position(
                date_opened=ts[:10], bracket_label=bracket_label,
                token_id=token_id, entry_ask=round(price, 4),
                shares=shares, size_usdc=round(size_usdc, 2),
                mode="real", order_id=result.order_id or "",
                market_slug=market_slug,
                temp_lo=float(temp_lo) if temp_lo is not None else 0.0,
                temp_hi=float(temp_hi) if temp_hi is not None else 0.0,
            ))
        return result

    # ── Venda / Fecho de posição ──────────────────────

    def sell_yes(self, position: "Position", bid_price: float) -> "OrderResult":
        from datetime import datetime as _dt
        ts = _dt.now().isoformat()

        if position.status != PositionStatus.OPEN:
            return OrderResult(success=False, mode=self.mode,
                               error=f"Posição já fechada ({position.status.value})", timestamp=ts)

        pnl_usd = round((bid_price - position.entry_ask) * position.shares, 2)
        pnl_pct = round((bid_price / position.entry_ask - 1) * 100, 2) if position.entry_ask else 0.0

        # ── PAPER MODE ────────────────────────────────
        if self.mode == TradingMode.PAPER:
            position.status = PositionStatus.WON if pnl_usd >= 0 else PositionStatus.LOST
            position.pnl_usd = pnl_usd
            position.pnl_pct = pnl_pct
            position.current_mid = bid_price
            position.last_updated = ts
            self.positions._save()
            return OrderResult(
                success=True, mode=TradingMode.PAPER,
                order_id=f"PAPER-SELL-{int(time.time())}",
                token_id=position.token_id, side="SELL", outcome="YES",
                price=round(bid_price, 4),
                size_usdc=round(bid_price * position.shares, 2),
                shares=position.shares, status="SIMULATED_SELL",
                timestamp=ts, simulated=True,
            )

        # ── REAL MODE ─────────────────────────────────
        try:
            from py_clob_client_v2 import OrderArgs, Side, OrderType, PartialCreateOrderOptions

            order_args = OrderArgs(
                token_id=position.token_id,
                price=round(bid_price, 4),
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
                position.current_mid = bid_price
                position.last_updated = ts
                self.positions._save()

            return OrderResult(
                success=success, mode=TradingMode.REAL,
                order_id=order_id, token_id=position.token_id,
                side="SELL", outcome="YES",
                price=round(bid_price, 4),
                size_usdc=round(bid_price * position.shares, 2),
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
    date_opened: str
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
            "date_opened": self.date_opened, "bracket_label": self.bracket_label,
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
            date_opened=d["date_opened"], bracket_label=d["bracket_label"],
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
            self._path.write_text(json.dumps([p.to_dict() for p in self._positions], indent=2))
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
        if self.mode == TradingMode.PAPER:
            for pos in self.open_positions():
                if pos.status != PositionStatus.OPEN:
                    continue
                # Para multi-cidade, precisamos da temperatura da cidade.
                # Este metodo e chamado pelo live_bot com contexto adicional.
                # A resolucao em PAPER e feita pelo live_bot directamente.
                pass
        # Em REAL, o refresh() ja cuida

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
