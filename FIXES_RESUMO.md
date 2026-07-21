# Bot Fixes — Resumo das Correções

## single_entry.py

### Bug 1.1 — Filtro de Plateau Timeout
**Problema:** Em dias de subida constante de temperatura (>0.2°C/30min), o filtro bloqueava compras indefinidamente.

**Fix:** Adicionado `plateau_timeout_hours` (default 4h). Após 4 horas de subida constante, o filtro deixa de bloquear.

```python
# Linha ~65
self.plateau_timeout_hours = self._first_non_none(
    kwargs.get("plateau_timeout_hours"),
    plateau_timeout_hours,
) or 4.0

# No evaluate() — antes de rejeitar por plateau:
elapsed_hours = (now_minutes - first_slot_minutes) / 60.0
if elapsed_hours < self.plateau_timeout_hours:
    return [{"reason": "... à espera de plateau ..."}]
# else: continua para avaliar compra
```

---

### Bug 1.5 — restore() não reseta sold_by_stop
**Problema:** `restore()` copiava `sold_by_stop` do record. Se o record não tinha essa chave, mantinha o valor anterior (possivelmente `True`).

**Fix:** Reset explícito para `False`.

```python
# Antes:
self.sold_by_stop = bool(record.get("sold_by_stop", False))

# Depois:
self.sold_by_stop = False  # sempre reset ao restaurar
```

---

## weather.py

### Bug 5.2 — Wind Speed em mph (PWS)
**Problema:** Algumas estações PWS ignoram `units=m` e devolvem wind speed em mph.

**Fix:** Função `_maybe_convert_mph_to_kmh()` que detecta valores >150 km/h (impossíveis meteorologicamente) e converte.

```python
def _maybe_convert_mph_to_kmh(value, threshold=150.0):
    if value is None: return None
    v = float(value)
    if v > threshold:
        return round(v * 1.60934, 1)  # mph -> km/h
    return v

# Usado em _v2_pws_history_parse:
"wind_speed_kmh": _maybe_convert_mph_to_kmh(
    _f(metric, "windspeedAvg", 0.0)
) or 0.0,
```

---

### Bug 5.3 — fetch_om_latest nome enganoso
**Problema:** `fetch_om_latest()` retornava **forecast**, não observação real. O nome era confuso.

**Fix:** Renomeado para `fetch_om_forecast_current_hour()` + alias para compatibilidade.

```python
def fetch_om_forecast_current_hour(city, session):
    """Previsão horária do Open-Meteo para a hora atual."""
    ...

fetch_om_latest = fetch_om_forecast_current_hour  # alias
```

---

## live_bot.py

### Bug 4.11 — city_today calculado múltiplas vezes
**Problema:** `city_today` e `current_market_slug` eram recalculados várias vezes no mesmo tick. Se passasse a meia-noite entre cálculos, usava slugs de dias diferentes.

**Fix:** Calculados **uma vez** no início de `_tick_city()`.

```python
def _tick_city(state, trading_mode_str, bankroll):
    city_today = city_date(city)
    current_market_slug = state.fetcher.date_to_slug(city_today)  # UMA VEZ
    # ... resto do tick usa estas variáveis locais
```

---

### Bug 4.13 — Settlement não feito no reset diário
**Problema:** Settlement PAPER só acontecia se `city_h_now > day_end`. Se o dia mudasse à meia-noite (00:00), o settlement do dia anterior nunca era feito.

**Fix:** Settlement movido para o **bloco de reset diário**, antes de limpar o estado.

```python
if city_today != state._last_date:
    # NOVO: settlement do dia anterior ANTES de resetar
    if trading_mode_str == "paper" and state.clob:
        settled_pnl = _settle_paper_positions_for_day(state, state._last_date)
        if settled_pnl:
            state.daily_stats.daily_pnl += settled_pnl

    # ... depois faz o reset normal
```

---

### Bug 4.1 — Anti-duplicado fora do lock
**Problema:** A thread do Telegram podia aceder/modificar `state.entry` enquanto o anti-duplicado verificava posições.

**Fix:** Todo o bloco anti-duplicado movido para dentro do `state._lock`.

```python
with state._lock:
    if state.entry and state.clob:
        _skip = False
        _rec = None
        # ... verificação de bets.json + CLOB positions
        # ... restore() se posição existir
```

---

### Bug 4.3 — Stop-loss fora do lock atómico
**Problema:** Snapshot do estado era feito sob lock, mas o processamento (venda) era feito fora. Race condition possível.

**Fix:** Todo o stop-lock (check + venda) consolidado num bloco `with state._lock:`.

---

### Bug 4.4 — Stop-loss bloqueado permanentemente
**Problema:** Se um stop-loss falhava (ex: bid < 0.02), `_stop_loss_blocked_alerted = True` e **nunca** era resetado. Mesmo que o bid subisse depois, nunca vendia.

**Fix:** Flag resetado quando as condições melhoram (bracket existe, bid é válido).

```python
else:  # matching bracket encontrado
    # RESET do flag quando condições melhoram
    if hasattr(state.entry, '_stop_loss_blocked_alerted'):
        state.entry._stop_loss_blocked_alerted = False

    if not bid_price or bid_price < 0.02:
        # ... bloqueia e SETA o flag
        state.entry._stop_loss_blocked_alerted = True
    else:
        # ... tenta vender (flag já foi resetado acima)
```

---

### Bug 4.5 — Sell usa bid stale
**Problema:** Venda stop-loss usava o bid do snapshot do mercado (pode ser desatualizado).

**Fix:** Obtém bid **fresh** do orderbook antes de vender.

```python
fresh_bid = bid_price  # do snapshot
pos_token_id = pos.get("token_id")
if pos_token_id and state.clob:
    try:
        fresh_book = state.clob.get_orderbook(pos_token_id)
        if fresh_book and fresh_book.best_bid is not None:
            fresh_bid = round_to_tick(float(fresh_book.best_bid), direction="down")
    except Exception:
        pass  # usa o bid do snapshot

sell_result = state.clob.sell_yes(poll[0], fresh_bid)
```

---

### Bug 4.10 — min_buy_ask inconsistente
**Problema:** Live bot usava `0.20` como fallback, mas `SingleEntry` default é `0.15`.

**Fix:** Alinhado com o default do `SingleEntry`.

```python
# Antes:
min_buy_ask = getattr(state.entry, "min_buy_ask", 0.20)

# Depois:
min_buy_ask = getattr(state.entry, "min_buy_ask", 0.15)  # alinha com SingleEntry
```

---

### Bug 4.9 — max_buy_ask duplicado
**Problema:** Filtro `max_buy_ask` existia em `SingleEntry.evaluate()` **e** no live bot. O live bot usava `raw_best_ask` (pode diferir do ask no bracket), criando inconsistências backtest/live.

**Fix:** Removido o filtro duplicado do live bot. Confia no `evaluate()`.

```python
# REMOVIDO do live_bot.py:
# max_buy_ask = float(getattr(state, "max_buy_ask", 0.85))
# if effective_ask > max_buy_ask:
#     ... bloqueia compra ...

# O SingleEntry.evaluate() já faz isto com o ask do bracket.
```

---

### Bug 4.16 — Race mode não atualiza session_stats
**Problema:** Compras feitas pelo race mode não eram contabilizadas no dashboard.

**Fix:** Atualização de `session_stats` após race buy.

```python
race_stats = _tick_city(s, args.run, city_bankroll_race)
if race_stats and race_stats.trades:
    daily_stats[cn] = race_stats
    if is_multi:
        session_stats["total_trades"] = max(
            session_stats["total_trades"],
            sum(len(getattr(st.daily_stats, "trades", [])) for st in states.values())
        )
```

---

## Resumo por Impacto

| Impacto | Bugs | Risco se não corrigido |
|---------|------|------------------------|
| 🔴 **Crítico (perda de dinheiro)** | 4.1, 4.3, 4.4, 4.5 | Compra duplicada, stop-loss falha, venda a preço errado |
| 🟡 **Alto (oportunidade perdida)** | 1.1, 4.11, 4.13 | Não compra em dias bons, settlement perdido |
| 🟢 **Médio (inconsistência)** | 1.5, 4.9, 4.10, 4.16, 5.2, 5.3 | Backtest != live, dados meteorológicos errados |

---

## Como Aplicar

```bash
cd /caminho/para/o/teu/bot
patch -p1 < bot_fixes.patch
```

Para reverter:
```bash
patch -p1 -R < bot_fixes.patch
```
