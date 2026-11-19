#!/usr/bin/env python3
"""v6_gamma_check.py — D2: verificar estado do mercado no Gamma antes de comprar.
Evita comprar em mercado fechado/suspenso/liquidado.
Cache de 5 min por slug (evita martelar a API)."""
import time
import requests

_cache = {}   # slug -> (ts, closed)
TTL = 300


def market_open(slug: str) -> tuple[bool, str]:
    now = time.time()
    if slug in _cache and now - _cache[slug][0] < TTL:
        return (not _cache[slug][1]), _cache[slug][2]
    closed, reason = False, ""
    try:
        r = requests.get("https://gamma-api.polymarket.com/events",
                         params={"slug": slug}, timeout=10)
        ev = r.json()
        ev = ev[0] if isinstance(ev, list) and ev else (ev or {})
        # fechado se: closed=true OU qualquer market liquidado/resolvido prematuro
        closed = bool(ev.get("closed"))
        if not closed:
            for m in ev.get("markets", []):
                if m.get("closed") or m.get("archived"):
                    closed = True
                    reason = "market fechado/archived"
                    break
        if closed and not reason:
            reason = "event closed"
    except Exception as e:
        # política fail-open em ERRO de rede (o FOK real morre sozinho se fechado);
        # regista e deixa passar
        reason = f"gamma indisponível ({e}) — fail-open"
        _cache[slug] = (now, closed)
        return True, reason
    _cache[slug] = (now, closed)
    return (not closed), reason
