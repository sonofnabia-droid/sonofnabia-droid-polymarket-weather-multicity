#!/usr/bin/env python3
"""
clob_sizing.py — regras centralizadas de sizing para Polymarket CLOB.
=====================================================================
Fase 3 (P0.6 / sizing): uma única fonte de verdade para o cálculo de
shares mínimas e notional mínimo.

Regras oficiais do Polymarket CLOB:
  - Shares devem ser inteiras (sem frações)
  - Notional (price × shares) deve ser >= $1.00 USD
  - Ordens que não cumpram são rejeitadas pela API com
    "invalid amount ... min size: 1"

Uso típico (no ponto de entrada da ordem):

    from clob_sizing import enforce_min_size
    effective_size, shares = enforce_min_size(size_usdc, ask)
    if effective_size > size_usdc:
        print(f"size bumped: ${size_usdc} -> ${effective_size}")
        size_usdc = effective_size

Ou validação defensiva (no ClobClient.buy_yes):

    from clob_sizing import compute_min_shares
    min_shares = compute_min_shares(price)
    if shares < min_shares:
        shares = min_shares
        size_usdc = round(shares * price, 2)
"""
from __future__ import annotations

import math
from typing import Optional, Tuple


# ── Constantes oficiais ──
MIN_NOTIONAL_USD: float = 1.00
MIN_SHARES: int = 1
TICK_SIZE: float = 0.01  # Polymarket tick (1¢)


def compute_min_shares(price: float) -> int:
    """Shares mínimas para cumprir o notional mínimo ($1.00).

    Para price=0.50: ceil(1.00/0.50) = 2  (notional $1.00)
    Para price=0.77: ceil(1.00/0.77) = 2  (notional $1.54)
    Para price=0.95: ceil(1.00/0.95) = 2  (notional $1.90)
    Para price=1.00: ceil(1.00/1.00) = 1  (notional $1.00)

    Garante >= MIN_SHARES mesmo para preços altos.
    """
    p = float(price)
    if p <= 0:
        return MIN_SHARES
    return max(MIN_SHARES, math.ceil(MIN_NOTIONAL_USD / p))


def compute_min_notional(price: float) -> float:
    """Notional mínimo em USD para o preço dado.

    = compute_min_shares(price) * price, arredondado a 2 casas.
    """
    p = float(price)
    if p <= 0:
        return 0.0
    return round(compute_min_shares(p) * p, 2)


def enforce_min_size(size_usdc: float, price: float) -> Tuple[float, int]:
    """Garante que (size_usdc, shares) cumpre as regras CLOB.

    Se size_usdc for insuficiente para o notional mínimo, BUMPS UP
    ao mínimo (consistente com o comportamento histórico do bot).

    Args:
        size_usdc: tamanho pretendido em USD
        price: preço por share (0..1)

    Returns:
        (effective_size_usdc, effective_shares)

    Exemplos:
        enforce_min_size(0.50, 0.77) → (1.54, 2)   # bumped up
        enforce_min_size(5.00, 0.50) → (5.00, 10)  # inalterado
        enforce_min_size(0.00, 0.50) → (1.00, 2)   # bumped from zero
        enforce_min_size(5.00, 0)     → (0.00, 0)   # preço inválido
    """
    p = float(price)
    if p <= 0:
        return (0.0, 0)

    requested_shares = math.floor(float(size_usdc) / p)
    min_shares = compute_min_shares(p)

    effective_shares = max(requested_shares, min_shares)
    effective_size = round(effective_shares * p, 2)

    return (effective_size, effective_shares)


def validate_order(size_usdc: float, shares: int, price: float) -> Optional[str]:
    """Valida uma ordem contra as regras CLOB.

    Returns:
        None se a ordem é válida; mensagem de erro caso contrário.
    """
    p = float(price)
    if p <= 0:
        return f"preço inválido: {price}"
    if int(shares) < MIN_SHARES:
        return f"shares={shares} abaixo do mínimo ({MIN_SHARES})"
    notional = round(int(shares) * p, 2)
    if notional < MIN_NOTIONAL_USD:
        min_shares_needed = compute_min_shares(p)
        return (
            f"notional ${notional:.2f} abaixo do mínimo (${MIN_NOTIONAL_USD:.2f}) — "
            f"preciso {min_shares_needed} shares a {p*100:.1f}¢ "
            f"(notional ${min_shares_needed * p:.2f})"
        )
    return None


def shares_for_size(size_usdc: float, price: float) -> int:
    """Calcula shares inteiras para um dado size_usdc e preço.

    Não enforce minimum — apenas floor. Útil para estimativas de
    capacidade (ex: "se eu tiver $5 e ask=0.50, posso comprar 10 shares").
    Para ordens reais, usar enforce_min_size().
    """
    p = float(price)
    if p <= 0:
        return 0
    return math.floor(float(size_usdc) / p)


def is_compliant(size_usdc: float, shares: int, price: float) -> bool:
    """True se a ordem cumpre todas as regras CLOB. Atalho para validate_order."""
    return validate_order(size_usdc, shares, price) is None
