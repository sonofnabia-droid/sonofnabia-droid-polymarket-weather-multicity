#!/usr/bin/env python3
"""resolution_rules.py — regras oficiais de resolução dos mercados de temperatura.

Fonte: descrições dos mercados Polymarket + HANDOVER §98b.
  - O valor oficial é o máximo diário arredondado HALF-UP.
  - Bracket numérico X cobre peak em [X-0.5, X+0.5).
  - "X or below" cobre peak < X+0.5.
  - "X or above" cobre peak >= X-0.5.

Este módulo é a única fonte de verdade para entry, settle, backtest, gate,
display e testes. Nunca reimplementar geometria localmente.
"""
from __future__ import annotations

import re
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

_INF = float("inf")
_NUM_RE = re.compile(r"(-?\d+(?:\.\d+)?)")


def round_half_up(value):
    """Polymarket rounding: nearest integer, ties toward +infinity."""
    import math
    return math.floor(value + 0.5)


def _label_value(value: float) -> float:
    return float(Decimal(str(float(value))).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def parse_label(label: str):
    """'11°C' -> ('num', 11.0); '6°C or below' -> ('below', 6.0);
    '16°C or higher' -> ('above', 16.0). None se não parseável."""
    s = str(label).lower().replace("°c", "").strip()
    m = _NUM_RE.search(s)
    if not m:
        return None
    v = _label_value(m.group(1))
    if any(w in s for w in ("below", "less", "or under")):
        return ("below", v)
    if any(w in s for w in ("higher", "above", "or more", "or over")):
        return ("above", v)
    return ("num", v)


def position_token(temp_lo: float, temp_hi: float):
    """Identidade da bracket nos mesmos tokens de parse_label()."""
    lo, hi = float(temp_lo), float(temp_hi)
    if hi >= 99:
        return ("above", _label_value(lo))
    if lo <= -99:
        return ("below", _label_value(hi))
    return ("num", _label_value(lo))


def bracket_bounds(temp_lo: float, temp_hi: float):
    """Limites oficiais [low, high) da bracket."""
    lo, hi = float(temp_lo), float(temp_hi)
    if hi >= 99:
        return (lo - 0.5, _INF)
    if lo <= -99:
        return (-_INF, hi + 0.5)
    if abs(hi - lo) < 1e-9:
        return (lo - 0.5, lo + 0.5)
    return (lo - 0.5, hi + 0.5)


def bracket_contains(temp_lo: float, temp_hi: float, peak: float) -> bool:
    """True se o peak oficial (half-up) cai nesta bracket."""
    low, high = bracket_bounds(temp_lo, temp_hi)
    return low <= float(peak) < high


def bracket_label_value(temp_lo: float, temp_hi: float) -> int:
    """Valor inteiro X que representa a bracket."""
    lo, hi = float(temp_lo), float(temp_hi)
    if hi >= 99:
        return round_half_up(lo)
    if lo <= -99:
        return round_half_up(hi)
    return round_half_up(lo)


def position_won_by_label(winner_label: str, temp_lo: float, temp_hi: float):
    """True/False se o label vencedor oficial é esta bracket.
    None se o label não for parseável."""
    w = parse_label(winner_label)
    if w is None:
        return None
    return w == position_token(temp_lo, temp_hi)


def bracket_for_peak(brackets: list, peak: float) -> Optional[dict]:
    """Bracket oficial que contém peak, ou None."""
    for b in brackets or []:
        try:
            if bracket_contains(b.get("temp_lo", 0), b.get("temp_hi", 99), peak):
                return b
        except (TypeError, ValueError):
            continue
    return None


def bracket_for_target(brackets: list, target: int) -> Optional[dict]:
    """Bracket cujo valor inteiro é target (inclui below/above)."""
    for b in brackets or []:
        try:
            lo = float(b.get("temp_lo", 0))
            hi = float(b.get("temp_hi", 99))
            v = bracket_label_value(lo, hi)
        except (TypeError, ValueError):
            continue
        if hi >= 99 and target >= v:
            return b
        if lo <= -99 and target <= v:
            return b
        if lo <= target <= hi:
            return b
    return None


def find_bracket(brackets: list, temp: float, fallback: bool = True) -> Optional[dict]:
    """Bracket oficial para temp; fallback opcional para a mais próxima."""
    if not brackets:
        return None
    b = bracket_for_peak(brackets, float(temp))
    if b is not None:
        return b
    target = round_half_up(temp)
    b = bracket_for_target(brackets, target)
    if b is not None or not fallback:
        return b
    return min(
        brackets,
        key=lambda x: abs((float(x.get("temp_lo", 0)) + float(x.get("temp_hi", 99))) / 2 - target),
    )
