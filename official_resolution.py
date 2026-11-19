#!/usr/bin/env python3
"""official_resolution.py — resolução OFICIAL dos mercados Polymarket (§98).

O mercado resolve pelo METAR do ICAO da cidade; a nossa fonte live (WU)
diverge em ~20% dos dias (v5_station_audit). Settle e reconcile passam a
preferir o vencedor oficial via Gamma API, com cache partilhado em
live_bot_logs/market_winners.json. Fallback fica a cargo do chamador.
"""
import json
import time
from pathlib import Path

from resolution_rules import parse_label as _parse_label, position_won_by_label

CACHE = Path("live_bot_logs/market_winners.json")
GAMMA = "https://gamma-api.polymarket.com/events"

def _load_cache() -> dict:
    try:
        return json.loads(CACHE.read_text())
    except Exception:
        return {}


def _save_cache(cache: dict) -> None:
    try:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        tmp = CACHE.with_suffix(".tmp")
        tmp.write_text(json.dumps(cache, indent=1))
        tmp.replace(CACHE)
    except Exception:
        pass


def fetch_winners(slug: str, timeout: int = 15):
    """Lista de labels vencedoras do evento, ou None se (ainda) não resolvido.
    Cache primeiro; fetch à Gamma com 3 tentativas se falhar/em falta."""
    cache = _load_cache()
    rec = cache.get(slug)
    if rec and rec.get("resolved") and rec.get("winners"):
        return list(rec["winners"])

    import requests
    for attempt in range(3):
        try:
            r = requests.get(GAMMA, params={"slug": slug}, timeout=timeout)
            if r.status_code == 429:
                time.sleep(5)
                continue
            if r.status_code != 200:
                time.sleep(2)
                continue
            ev = r.json()
            ev = ev[0] if isinstance(ev, list) and ev else (ev or {})
            winners = []
            any_resolved = False
            for m in ev.get("markets", []):
                label = m.get("groupItemTitle") or m.get("question", "")
                prices = m.get("outcomePrices")
                if isinstance(prices, str):
                    try:
                        prices = json.loads(prices)
                    except Exception:
                        prices = None
                p0 = None
                if isinstance(prices, (list, tuple)) and prices:
                    try:
                        p0 = float(prices[0])
                    except Exception:
                        p0 = None
                if m.get("resolved") or p0 in (0.0, 1.0):
                    any_resolved = True
                if m.get("winner") is True or p0 == 1.0:
                    winners.append(label)
            if winners:
                cache[slug] = {"winners": winners, "resolved": True}
                _save_cache(cache)
                return winners
            if any_resolved:
                # resolvido mas sem vencedora clara — não cachear como final
                return None
            return None  # mercado ainda aberto
        except Exception:
            time.sleep(2)
    return None


def position_won(market_slug: str, temp_lo: float, temp_hi: float):
    """True/False pela resolução oficial; None se indisponível."""
    if not market_slug:
        return None
    winners = fetch_winners(market_slug)
    if not winners:
        return None
    for label in winners:
        w = position_won_by_label(label, temp_lo, temp_hi)
        if w is True:
            return True
    # nenhuma vencedora cobre a bracket -> perda (só se pelo menos uma
    # vencedora foi parseável; senão não sabemos)
    if any(_parse_label(l) is not None for l in winners):
        return False
    return None
