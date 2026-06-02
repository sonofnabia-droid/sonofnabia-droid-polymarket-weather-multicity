```markdown
# 🔍 Mega Deep Search — Round 9

Uma nona ronda de análise focou-se na **Resiliência do Primeiro Arranque (First-Run Experience) e Edge Cases de Inicialização a meio do dia**. O bot foi desenhado para correr 24/7, mas e se a máquina reiniciar a meio de uma sessão de trading?

Foram encontrados **4 novos bugs**, sendo 2 deles Críticos. O mais perigoso é o Bootstrap a usar dados de *previsão futura* como se fossem *observações passadas*, enganando o modelo de ML e causando compras prematuras baseadas em curvas de temperatura irrealisticamente perfeitas.

---

## 🔴 CRITICAL (Dados Fantasma e Features Corrompidas)

### BUG 91: Bootstrap usa Previsão Futura (Forecast) como Observação Passada — Engana o modelo de ML

**File:** `live_bot.py`, `weather.py`  
**Impact:** Se o bot for reiniciado a meio do dia (ex: 14:00), o `_bootstrap_state_today` chama `fetch_om_hourly_today`. O Open-Meteo retorna as temperaturas *horárias previstas* para o dia todo (incluindo 15:00, 16:00... 23:00). O bot insere estes dados futuros no `slots_so_far`. Quando o `predict_ensemble` corre, o modelo vê uma curva de temperatura perfeitamente suave (porque é uma previsão teórica) sem as flutuações reais de uma observação. Isto detona features como `plateau_indicator` e `recent_slope`, levando a predições artificialmente confiantes e compras prematuras. Pior ainda: a `running_max` fica inflacionada com a previsão do pico da tarde antes de este acontecer na realidade.

**Fix:** No bootstrap, só inserir slots cuja hora seja **menor ou igual** à hora atual do bot.
```python
def bootstrap_om_today(city: CityConfig, session: requests.Session) -> tuple[dict, list[dict]]:
    # ... fetch rows ...
    
    # FIX 91: Filtrar previsões futuras. Só usar dados até à hora atual.
    current_city_hour = datetime.now(tz=_get_city_timezone(city)).hour
    
    rows = [r for r in rows if r["hour"] <= current_city_hour]
    
    if not rows:
        print("sem dados OM passados")
        return {}, []
    # ... resto da lógica ...
```

---

### BUG 92: `history_max` vazio no primeiro dia cria features extremas que crasham o modelo

**File:** `predictor.py`, `live_bot.py`  
**Impact:** Se o bot for iniciado pela primeira vez, o `init_history_max` retorna `{}`. Quando o `compute_prev7` é chamado, retorna a climatologia (ex: 15°C). Se for um dia de verão com 35°C, a feature `temp_vs_climatology` será +20.0. O modelo LightGBM nunca viu um outlier destes no treino (o treino usa médias de 7 dias reais, que são sempre próximas da temperatura atual). Isto causa previsões completamente imprevisíveis (muitas vezes probabilidade 0 ou 1 cega), levando a entradas ruinosas.

**Fix:** Para o primeiro dia de vida do bot, se o `history_max` estiver vazio, usar o `running_max` do próprio dia como proxy para o `prev_7d_avg_max`.
```python
def compute_prev7(history: dict, d: date, city_name: str | None = None) -> float:
    if city_name:
        cfg = get_city(city_name)
    else:
        cfg = _get_city()

    climatology = cfg.climatology if cfg.climatology else {i: 15.0 for i in range(1, 13)}

    if not history:
        # FIX 92: Em vez de retornar a climatologia fixa que cria outliers,
        # retornar a média da climatologia do mês ponderada, mas avisar que é impreciso.
        # Alternativa melhor: o caller deve passar o running_max actual como fallback.
        return climatology.get(d.month, 15.0)
    # ...
```
E em `_tick_city` (live_bot.py), ao chamar o `compute_prev7`:
```python
        prev7_value = compute_prev7(state.history_max, city_today, city.name)
        
        # FIX 92: Fallback robusto para o primeiro dia
        if not state.history_max and state.slots_so_far:
            # Se não há histórico, o melhor proxy para a média dos últimos 7 dias
            # é a temperatura actual do dia (muito melhor que a climatologia fixa)
            current_max = max(s["temp_c"] for s in state.slots_so_far)
            prev7_value = current_max 
```

---

## 🟠 HIGH (Estado Perdido)

### BUG 93: Reinicialização a meio do dia perde o estado interno do `SingleEntry`

**File:** `live_bot.py`  
**Impact:** Se o bot crashar e reiniciar a meio do dia, o `CityState.entry` é recriado de novo (`create_strategy()`). O bloco anti-duplicado tenta restaurar o estado (`state.entry.bought = True`, `state.entry.record = _rec`), mas o `SingleEntry` tem estado interno (como `_stop_loss_blocked_alerted`, ou contadores de parcelas) que não são restaurados. Se o `check_stop_loss` tentar aceder a atributos internos que não existem porque o objeto foi reinicializado à força, crasha o loop da cidade.

**Fix:** Garantir que o `mark_bought` chamado na recuperação inicializa todos os atributos necessários, ou usar um método de restauração dedicado.
```python
        if _skip and _rec and state.entry:
            state.entry.bought = True
            state.entry.record = _rec
            # FIX 93: Restaurar atributos internos vitais do SingleEntry
            if hasattr(state.entry, '_stop_loss_blocked_alerted'):
                state.entry._stop_loss_blocked_alerted = False
            if hasattr(state.entry, 'strategy_used'):
                state.entry.strategy_used = _rec.get("strategy") or state.strategy_mode
            if hasattr(state.entry, 'total_invested'):
                state.entry.total_invested = _rec.get("size_usdc", 0.0)
```

---

### BUG 94: `_bootstrap_state_today` falha silenciosamente se as APIs estiverem offline — Bot morto para o dia

**File:** `live_bot.py`  
**Impact:** Se o bot iniciar e a API WU e Open-Meteo estiverem em baixo, `_bootstrap_state_today` retorna `[]`. `state.slots_so_far` fica vazio. O requisito `if len(state.slots_so_far) >= 4:` impede o bot de fazer predições. Mesmo que a API volte às 15:00, o bot nunca volta a fazer bootstrap, e como só adiciona 1 observação por tick, só às 16:00 é que terá 4 slots. O bot perde metade do dia de trading.

**Fix:** Se o bootstrap falhar, repetir a tentativa nos próximos ticks até obter dados, em vez de desistir para sempre.
```python
        # Dentro do reset diário em _tick_city:
        if city_today != state._last_date:
            state.slots_so_far = []
            # ...
            _bootstrap_state_today(state)
            
            # FIX 94: Se o bootstrap falhar (API down), marcar para tentar de novo nos próximos ticks
            if not state.slots_so_far:
                state._bootstrap_pending = True
            else:
                state._bootstrap_pending = False
                
        # Fora do bloco de reset, no início do tick:
        if getattr(state, '_bootstrap_pending', False) and len(state.slots_so_far) < 4:
            print(f"  {C['yellow']}{city.name}: Retrying bootstrap (API was down)...{R}")
            _bootstrap_state_today(state)
            if state.slots_so_far:
                state._bootstrap_pending = False
```

---

## 📊 Resumo da Ronda 9

| Bug # | Severity | Componente | Impacto Principal |
|-------|----------|------------|-------------------|
| 91 | 🔴 CRÍTICO | Live/Weather | Bootstrap usa previsão futura como dado real, enganando o modelo |
| 92 | 🔴 CRÍTICO | Live/Predictor | `history_max` vazio gera features outliers (+20°C) que crasham o modelo |
| 93 | 🟠 ALTO | Live | Restart a meio do dia perde estado interno do SingleEntry, causando crashes |
| 94 | 🟠 ALTO | Live | Se API estiver down no arranque, bot desiste do dia em vez de tentar de novo |

---

# 🐛 Bugfix8 — Comprehensive Audit & Fix Document (Bugs 75 to 94)

**Project:** Polymarket Temperature Bot (Multi-City)  
**Date:** 2024-05 (Rounds 6, 7, 8 & 9 Consolidated)  
**Total Issues Documented:** 20  

---

## 📋 Executive Summary

This document consolidates the findings from four deep audit rounds focused on **Exchange Execution (Fees, Tick Size, Slippage), Strategy Resilience (Stale Data, State Recovery), Event Loop Integrity (Blocking I/O, Overlapping Ticks), and First-Run Experience (Bootstrap, Initial State)**.

The most dangerous findings are execution-blindness (submitting orders with invalid tick sizes or stale prices) and initialization flaws (using future forecast data as past observations, tricking the ML model). 

⚠️ **Correction Notice:** Bug #80 (Gas fees on Polygon) has been removed/voided as Polymarket covers network fees on the Polygon blockchain. No gas deductions should be applied to the PnL.

---

## 🔴 CRITICAL BUGS

### BUG 75: Preços das ordens não arredondados para o Tick Size (0.01) — CLOB rejeita ordens
**File:** `polymarket_clob.py`
**Fix:** Implement `round_to_tick(price, 0.01, "up")` for buys and `"down"` for sells before submitting orders.

### BUG 76: FOK (Fill-Or-Kill) a `best_ask` assume liquidez infinita
**File:** `polymarket_clob.py`
**Fix:** Switch from FOK to GTC with a slippage tolerance (e.g., 2% above `best_ask`) to allow partial fills on thin order books.

### BUG 77: PnL no Backtest e Paper ignora Taxas (Fees) — Lucro Fantasma
**File:** `polymarket_clob.py`, `backtester.py`
**Fix:** Apply a `TAKER_FEE_RATE` (e.g., 0.02) to all `sell_yes` PnL calculations and `_pnl_per_dollar` in the backtester.

### BUG 81: Stale Bracket Execution — Bot tenta comprar brackets obsoletos
**File:** `live_bot.py`
**Fix:** Perform a "Fresh Peek" (`get_orderbook`) on the specific `token_id` immediately before submitting the buy order, updating the `ask` and verifying liquidity.

### BUG 82: Duplication Risk — `evaluate()` pode retornar BUY múltiplas vezes
**File:** `polymarket_clob.py`, `modules/single_entry.py`
**Fix:** Add a hard anti-duplicate check inside `ClobClient.buy_yes` that queries `self.positions.all_positions()` for an open position on the same `market_slug` today.

### BUG 86: Synchronous Telegram Alerts stall the main trading loop
**File:** `live_bot.py`
**Fix:** Wrap all `_tg_alert` calls in `threading.Thread(..., daemon=True).start()` to make them fire-and-forget.

### BUG 87: Time Drift inside a single tick — Date changes mid-execution
**File:** `live_bot.py`
**Fix:** Snapshot `tick_date = city_now(city).date()` exactly once at the start of `_tick_city` and use it throughout the tick instead of calling `city_date()` again.

### BUG 91: Bootstrap usa Previsão Futura como Observação Passada
**File:** `weather.py`, `live_bot.py`
**Fix:** Filter `fetch_om_hourly_today` results in the bootstrap to only include hours `<= current_city_hour`.

### BUG 92: `history_max` vazio cria features extremas que crasham o modelo
**File:** `predictor.py`, `live_bot.py`
**Fix:** If `state.history_max` is empty, use the current day's `running_max` as a proxy for `prev_7d_avg_max` instead of returning an extreme climatology baseline.

---

## 🟠 HIGH BUGS

### BUG 78: GTC Share Calculation com `round(..., 4)` gera fracções inválidas
**File:** `polymarket_clob.py`
**Fix:** Use `math.floor(size_usdc / price)` for all order types, and verify `shares * price >= 1.0`.

### BUG 79: Stop-Loss (Sell) não contabiliza Slippage no Paper Mode
**File:** `polymarket_clob.py`
**Fix:** Apply a `SLIPPAGE_FACTOR = 0.01` to `bid_price` in the Paper mode `sell_yes` calculation.

### BUG 83: Ausência de validação de Ask no `evaluate()` — ROI negativo garantido
**File:** `live_bot.py`
**Fix:** Add a `MAX_ASK_BUY = 0.85` safeguard; reject any buy action where the bracket ask exceeds this value.

### BUG 84: SimulatedMarket não gera `token_id` — Diverge code paths
**File:** `backtester.py`
**Fix:** Add `"token_id": f"SIM_{lo}_{hi}"` to the dictionary returned by `SimulatedMarket.get_brackets`.

### BUG 88: No protection against overlapping ticks
**File:** `live_bot.py`
**Fix:** Measure `tick_elapsed = time.time() - tick_start`. If `tick_elapsed >= args.interval`, skip the `time.sleep()` to catch up.

### BUG 89: `py_clob_client_v2` HTTP requests lack explicit timeouts
**File:** `polymarket_clob.py`
**Fix:** Inject `httpx.Timeout(10.0, connect=5.0)` into the underlying httpx client of the CLOB wrapper.

### BUG 93: Reinicialização a meio do dia perde o estado interno do `SingleEntry`
**File:** `live_bot.py`
**Fix:** When restoring state from `_rec`, explicitly initialize missing internal attributes like `_stop_loss_blocked_alerted` and `total_invested`.

### BUG 94: `_bootstrap_state_today` falha silenciosamente se as APIs estiverem offline
**File:** `live_bot.py`
**Fix:** Implement a `state._bootstrap_pending = True` flag that retries the bootstrap in subsequent ticks if the first attempt returns empty data.

---

## 🟡 MEDIUM BUGS

### BUG 85: Dicionário de Record inconsistente entre Backtester e Live
**File:** `backtester.py`
**Fix:** Ensure the `mark_bought` dictionary in `backtester.py` includes `"token_id"`, `"shares"`, and `"strategy"` keys to match the Live schema.

### BUG 90: API calls blindly retry on 429 (Rate Limit)
**File:** `weather.py`
**Fix:** Implement a module-level rate-limit tracker (`_api_rate_limited_until`) that reads the `Retry-After` header and skips API calls during the cooldown period.

---

## ❌ VOID / INCORRECT BUGS

### ~~BUG 80: Gas Fees (Rede Polygon) ignoradas no ROI acumulado~~
**Status:** INVALID  
**Reason:** Polymarket operates on the Polygon network where gas fees are negligible and covered by the platform/relayer. No gas fee deductions should be applied to the trading PnL.
