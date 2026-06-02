```markdown
# 🐛 Bugfix5 — Round 3 Deep Audit & Fix Document

**Project:** Polymarket Temperature Bot (Multi-City)  
**Date:** 2024-05 (Round 3)  
**Total Issues Found:** 6  
**Severity Breakdown:** 🔴 Critical (2) | 🟠 High (2) | 🟡 Medium (2)

---

## 📋 Executive Summary

Round 3 focused on **asynchronous data flows, mathematical parity with Polymarket's bracket resolution, and state persistence between bot restarts/ticks**. 

The most critical findings are:
1. A loop that sums PnL from historical trades on every 30-second tick, causing the dashboard PnL to inflate to infinity.
2. The backtester using `round()` instead of `floor()` for the running_max, which causes the bot to buy the wrong bracket in simulations (buying 30°C when it should buy 29°C), artificially destroying the win rate.

Applying these fixes will stop the live dashboard from showing fake millions in PnL and will likely reveal the true (much higher) win rate of the backtesting engine.

---

## 🔴 CRITICAL BUGS (Infinite Inflation & Bracket Logic)

### BUG 57: PnL de trades antigos é somado repetidamente ao `daily_pnl` a cada tick

**File:** `live_bot.py`  
**Severity:** 🔴 CRITICAL  
**Impact:** No loop principal do bot, a cada tick (30s), o código itera sobre `state.clob.positions.all_positions()`. Se uma posição está `WON` ou `LOST`, o seu PnL é adicionado a `stats.daily_pnl`. Como `all_positions()` retorna **todo o histórico** (incluindo trades de dias ou semanas anteriores), o PnL desses trades antigos é somado de novo a cada 30 segundos. O bot vai mostrar um PnL diário infinitamente crescente e completamente errado.

**Broken Code (dentro do `while True` loop em `main()`):**
```python
                    if state.clob and hasattr(state.clob, "positions"):
                        try:
                            state.clob.positions.refresh(state.clob)
                            today_key = city_today.isoformat()
                            for pos in state.clob.positions.all_positions():
                                pos_id = str(getattr(pos, "order_id", "") or "")
                                if not pos_id or pos_id in state._settled_position_ids:
                                    continue
                                if getattr(pos, "status", None) in (
                                    PositionStatus.WON,
                                    PositionStatus.LOST,
                                    PositionStatus.EXPIRED,
                                ):
                                    pnl = float(getattr(pos, "pnl_usd", 0.0) or 0.0)
                                    stats.daily_pnl += pnl  # BUG: Soma PnL de trades antigos a cada tick!
                                    state._settled_position_ids.add(pos_id)
                        except Exception:
                            pass
```

**Fix:** Iterar apenas sobre posições cuja data de abertura seja o dia atual.
```python
                    if state.clob and hasattr(state.clob, "positions"):
                        try:
                            state.clob.positions.refresh(state.clob)
                            today_key = city_today.isoformat()
                            for pos in state.clob.positions.all_positions():
                                pos_id = str(getattr(pos, "order_id", "") or "")
                                if not pos_id or pos_id in state._settled_position_ids:
                                    continue
                                
                                # FIX 57: Só contabilizar PnL de posições abertas HOJE
                                if getattr(pos, "date_opened", "") != today_key:
                                    continue
                                    
                                if getattr(pos, "status", None) in (
                                    PositionStatus.WON,
                                    PositionStatus.LOST,
                                    PositionStatus.EXPIRED,
                                ):
                                    pnl = float(getattr(pos, "pnl_usd", 0.0) or 0.0)
                                    stats.daily_pnl += pnl
                                    state._settled_position_ids.add(pos_id)
                        except Exception:
                            pass
```

---

### BUG 58: `SimulatedMarket` usa `round(running_max)` — Compra o bracket errado no backtest

**File:** `backtester.py`  
**Severity:** 🔴 CRITICAL  
**Impact:** No Polymarket real, o bracket "29°C" cobre 29.0°C a 29.99°C (lógica de chão/floor). O `SimulatedMarket` usa `rmax_int = int(round(running_max))`. Se a `running_max` for 29.6°C, o backtest arredonda para 30 e tenta comprar o bracket "30°C" (que provavelmente vai perder, porque o pico foi 29.x). O bracket "29°C", que devia ganhar, é marcado como `temp_below_rmax` e recebe preço quase zero. Isto inverte as vitórias do bot no backtest, escondendo a verdadeira edge.

**Broken Code (em `SimulatedMarket.get_brackets`):**
```python
        rmax_int = int(round(running_max))

        for temp in self.temp_range:
            signed_dist = temp - rmax_int
            dist = abs(signed_dist)
            temp_below_rmax = signed_dist < 0
```

**Broken Code (em `run_backtest`, secção de compra):**
```python
                        target_temp = int(round(running_max))
```

**Fix:** Usar `math.floor` para paridade com a realidade do Polymarket (1°C steps de 0 a 0.99).

1. Adicionar `import math` no topo do `backtester.py` se não existir.
2. Substituir em `SimulatedMarket.get_brackets`:
```python
        # O bracket alvo no Polymarket é o piso (floor) da temperatura actual
        rmax_floor = int(math.floor(running_max))

        for temp in self.temp_range:
            # Distância ao bracket que contém o running_max
            signed_dist = temp - rmax_floor
            dist = abs(signed_dist)
            
            # Se a temp é menor que o piso do rmax, está "abaixo" do pico actual
            temp_below_rmax = signed_dist < 0
```

3. Substituir em `run_backtest` (na secção "SINGLE — 1 compra por sessão"):
```python
                        # Substituir: target_temp = int(round(running_max))
                        # Por:
                        target_temp = int(math.floor(running_max))
```

---

## 🟠 HIGH BUGS (State Corruption & Infinite Leverage)

### BUG 59: Bankroll a $0 gera apostas de $5 (Alavancagem Infinita)

**File:** `backtester.py`  
**Severity:** 🟠 HIGH  
**Impact:** Quando `ordertype == "percent"`, o tamanho da aposta é `max(5.0, min(500.0, capital * 0.05))`. Se o capital vai a $0 (devido a stop-losses ou perdas), o `max(5.0, ...)` força uma aposta de $5. O bot continua a apostar dinheiro que não tem, criando PnL irrealista a partir do nada (alavancagem infinita não intencional).

**Broken Code (em `run_backtest`):**
```python
            if ordertype == "percent":
                bet_size = max(5.0, min(500.0, capital * (bet_value / 100.0)))
            else:
                bet_size = bet_value
```

**Fix:** Não apostar se o capital for insuficiente para a aposta mínima.
```python
            if ordertype == "percent":
                desired_bet = capital * (bet_value / 100.0)
                # FIX 59: Não apostar dinheiro que não se tem (alavancagem infinita)
                if capital < 5.0:
                    bet_size = 0.0  # Sem capital suficiente para aposta mínima
                else:
                    bet_size = max(5.0, min(500.0, desired_bet))
            else:
                bet_size = bet_value
```

---

### BUG 60: `update_history_max` corrompe dados do dia seguinte após a meia-noite

**File:** `live_bot.py`  
**Severity:** 🟠 HIGH  
**Impact:** A função `update_history_max` tenta inferir a data dos slots. No `live_bot.py`, os dicionários em `slots_so_far` **não contêm a chave "date"**. Isto faz com que a função caia no fallback `_city_date()` (data atual do sistema). Se o bot processar dados atrasados (ex: dados de 23:50) após a meia-noite (quando o relógio do sistema já marca 00:05), `_city_date()` retorna o dia seguinte. A temperatura alta do dia anterior é então escrita no `history_max` do dia seguinte, corrompendo o baseline de previsão `prev_7d_avg_max`.

**Broken Code (em `_tick_city`, bloco onde atualiza slots):**
```python
            slot_entry = {
                "hour": h_slot,
                "slot30": s30,
                "temp_c": new_obs["temp_c"],
                "cloud_cover": new_obs.get("cloud_cover", 50),
                "humidity": new_obs.get("humidity", 70),
                # ... missing "date" key ...
            }

            exists = any(s["hour"] == h_slot and s["slot30"] == s30 for s in state.slots_so_far)
```

**Fix:** Adicionar a data explícita do dia corrente ao slot, para que o `update_history_max` saiba sempre a que dia pertencem os dados, independentemente da hora do sistema.
```python
            slot_entry = {
                "date": city_today,  # FIX 60: Preserva a data real do slot para o predictor
                "hour": h_slot,
                "slot30": s30,
                "temp_c": new_obs["temp_c"],
                "cloud_cover": new_obs.get("cloud_cover", 50),
                "humidity": new_obs.get("humidity", 70),
                # ... restante ...
            }

            exists = any(s["hour"] == h_slot and s["slot30"] == s30 for s in state.slots_so_far)
```

---

## 🟡 MEDIUM BUGS (Anti-Duplication & Validation)

### BUG 61: Anti-duplicate check falha se o `market_slug` não foi gravado no ficheiro antigo

**File:** `live_bot.py`  
**Severity:** 🟡 MEDIUM  
**Impact:** O bot lê `bets_{city}_{date}.json` para evitar apostas duplicadas. O filtro é `b.get("market_slug", current_market_slug) == current_market_slug`. Se um registo antigo não tiver a chave `market_slug`, o `.get()` usa o default `current_market_slug`, que **passa sempre** na verificação. Isto faz o bot saltar novas apostas válidas se existir qualquer registo antigo sem slug no ficheiro.

**Broken Code (em `_tick_city`, secção "Anti-duplicado"):**
```python
            existing_bets = json.loads(bets_path.read_text())
            existing_bets = [
                b for b in existing_bets
                if b.get("market_slug", current_market_slug) == current_market_slug
            ]
```

**Fix:** Se o slug está em falta no registo antigo, assumir que é um legacy e **não** saltar a nova aposta baseada nele.
```python
            existing_bets = json.loads(bets_path.read_text())
            existing_bets = [
                b for b in existing_bets
                # FIX 61: Só considerar como duplicado se o slug existir E for igual ao atual
                if b.get("market_slug") is not None and b.get("market_slug") == current_market_slug
            ]
```

---

### BUG 62: `weather.py` não valida se a API do WU retornou Fahrenheit em vez de Celsius

**File:** `weather.py`  
**Severity:** 🟡 MEDIUM  
**Impact:** O pedido WU envia `units=m` (Métrico). No entanto, se a API Key não tiver permissões, ou o endpoint mudar comportamento, pode retornar Fahrenheit. O bot interpretaria 100°F como 100°C, gerando sinais absurdos, comprando brackets irreais, e crashando o modelo de ML.

**Fix:** Adicionar uma validação de sanidade básica no final de `fetch_wu_day`, baseada na climatologia da cidade.
```python
def fetch_wu_day(city: CityConfig, day: date,
                api_key: str, session: requests.Session) -> list[dict]:
    """Busca observações WU para um dia específico da cidade."""
    wu_url = _get_wu_url(city)
    if not wu_url:
        return []

    try:
        r = session.get(wu_url, params={
            "apiKey":    api_key,
            "units":     "m",
            "startDate": day.strftime("%Y%m%d"),
        }, timeout=20)
        r.raise_for_status()
        obs = r.json().get("observations", [])
        city_tz = _get_city_timezone(city)
        rows = _wu_parse_obs(obs, city_tz) if obs else []
        
        # FIX 62: Validação de sanidade para Fahrenheit/Celsius
        if rows and hasattr(city, 'climatology') and city.climatology:
            avg_max_clim = max(city.climatology.values())
            for r in rows:
                # Se a temperatura exceder largamente a máxima histórica, provavelmente é Fahrenheit
                if r["temp_c"] > avg_max_clim + 50:  
                    print(f"  [RED]WU API probably returned Fahrenheit instead of Celsius! Temp={r['temp_c']}[/RED]")
                    return []  # Descartar dados corrompidos para proteger o modelo
                    
        return rows
    except Exception:
        return []
```

---

## 📊 Resumo da Ronda 3

| Bug # | Severity | Componente | Impacto Principal |
|-------|----------|------------|-------------------|
| 57 | 🔴 CRÍTICO | Live Bot | PnL diário duplicado infinitamente no dashboard |
| 58 | 🔴 CRÍTICO | Backtester | Compra bracket errado (round vs floor), esconde a verdadeira win rate |
| 59 | 🟠 ALTO | Backtester | Alavancagem infinita com bankroll a 0 |
| 60 | 🟠 ALTO | Live/Predictor | Corrupção de `history_max` após meia-noite |
| 61 | 🟡 MÉDIO | Live Bot | Anti-duplicação bloqueia apostas novas incorrectamente |
| 62 | 🟡 MÉDIO | Weather | Dados em Fahrenheit interpretados como Celsius sem validação |
