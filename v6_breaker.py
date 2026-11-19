#!/usr/bin/env python3
"""v6_breaker.py — D1: circuit breaker (proteção de capital).
REGRAS PRÉ-REGISTADAS (A5):
  CB-1: cidade com 3 dias negativos CONSECUTIVOS → cidade pausada 2 dias
  CB-2: drawdown global desde pico >= $15 → TUDO pausado até revisão humana
Estado persistido (sobrevive a restarts): live_bot_logs/breaker_state.json
Consulta: v6_breaker.can_trade(city) -> (bool, motivo)
Registo: v6_breaker.record_result(city, pnl_do_dia)
"""
import json
import os
from pathlib import Path
from datetime import date

# §88 (07/11): breaker por BOT — o estado vive no log_dir do processo
# (CASS_LOG_DIR). Antes era um ficheiro único partilhado por A+B+D, o que
# deixou o D (real) bloqueado por drawdown acumulado no PAPER de eras
# pré-reboot. Sem CASS_LOG_DIR mantém o default histórico (live_bot_logs).
STATE = Path(os.environ.get("CASS_LOG_DIR", "live_bot_logs")) / "breaker_state.json"
GLOBAL_DD_LIMIT = 15.0     # $ (A5 §3)
CITY_LOSS_STREAK = 3
CITY_COOLDOWN_DAYS = 2


def _load():
    try:
        return json.load(open(STATE))
    except Exception:
        return {"peak_pnl": 0.0, "global_paused_until": None, "cities": {}}


def _save(s):
    # escrita atómica (tmp+rename): o PC tem reboots súbitos e write_text
    # directo deixava JSON truncado/duplicado (§88: mesmo sintoma corrompeu
    # o v6_gate_stats.json)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(s, indent=1, default=str))
    tmp.replace(STATE)


def record_result(city: str, pnl_day: float):
    """Chamar no fim do dia (EOD) com o P&L resolvido do dia da cidade."""
    s = _load()
    today = date.today().isoformat()
    # streak por cidade
    c = s["cities"].setdefault(city, {"streak": 0, "paused_until": None})
    if pnl_day < 0:
        c["streak"] = c.get("streak", 0) + 1
        if c["streak"] >= CITY_LOSS_STREAK:
            c["paused_until"] = (date.today() +
                                 __import__("datetime").timedelta(days=CITY_COOLDOWN_DAYS)).isoformat()
            c["streak"] = 0
            print(f"[breaker] {city}: {CITY_LOSS_STREAK} dias negativos → pausa "
                  f"{CITY_COOLDOWN_DAYS}d (até {c['paused_until']})")
    else:
        c["streak"] = 0
        c["paused_until"] = None
    # pico global (soma de pnl resolvido acumulado — o caller passa o total?)
    _save(s)


def record_global_city_total(city: str, day_pnl: float):
    """soma os dailies por cidade e avalia o drawdown global combinado."""
    s = _load()
    totals = s.setdefault("city_totals", {})
    totals[city] = round(totals.get(city, 0.0) + day_pnl, 4)
    grand = round(sum(totals.values()), 4)
    if grand > s.get("peak_pnl", 0.0):
        s["peak_pnl"] = grand
    dd = s["peak_pnl"] - grand
    if dd >= GLOBAL_DD_LIMIT and not s.get("global_paused_until"):
        s["global_paused_until"] = "9999-12-31"
        print(f"[breaker] ⚠️ DRAWDOWN GLOBAL {dd:.2f} >= ${GLOBAL_DD_LIMIT} → PAUSA TOTAL")
    _save(s)


def record_global(total_pnl: float):
    """Atualiza o pico e dispara pausa global se drawdown >= limite."""
    s = _load()
    if total_pnl > s.get("peak_pnl", 0.0):
        s["peak_pnl"] = total_pnl
    if not s.get("global_paused_until"):
        dd = s["peak_pnl"] - total_pnl
        if dd >= GLOBAL_DD_LIMIT:
            s["global_paused_until"] = "9999-12-31"   # só revisão humana levanta
            _save(s)
            print(f"[breaker] ⚠️ DRAWDOWN GLOBAL {dd:.2f} >= ${GLOBAL_DD_LIMIT} "
                  f"→ TUDO PAUSADO (revisão humana)")
            return
    _save(s)


def can_trade(city: str) -> tuple[bool, str]:
    s = _load()
    today = date.today().isoformat()
    if s.get("global_paused_until") and today <= s["global_paused_until"]:
        return False, "drawdown global — revisão humana"
    c = s["cities"].get(city, {})
    if c.get("paused_until") and today <= c["paused_until"]:
        return False, f"cooldown pós-{CITY_LOSS_STREAK} dias negativos"
    return True, "ok"


if __name__ == "__main__":
    import sys
    s = _load()
    print(json.dumps(s, indent=1, default=str))
    for c in (sys.argv[1:] or ["munich"]):
        print(c, can_trade(c))
