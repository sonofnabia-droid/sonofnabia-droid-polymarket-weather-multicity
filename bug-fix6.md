```markdown

# 🐛 Bugfix6 — Round 4 Deep Audit & Fix Document

**Project:** Polymarket Temperature Bot (Multi-City)  
**Date:** 2024-05 (Round 4)  
**Total Issues Found:** 6  
**Severity Breakdown:** 🔴 Critical (2) | 🟠 High (2) | 🟡 Medium (2)

---

## 📋 Executive Summary

Round 4 focused on **API data resilience (sensor glitches, late-arriving data), I/O concurrency (atomic writes), and simulation performance**. 

The most critical findings are:
1. The bot blindly trusts API temperature data. A single sensor glitch (e.g., 99.0°C in winter) permanently corrupts the `running_max` for the day, forcing the bot to buy an impossible bracket and guarantee a loss.
2. A falsy check in the WU parser swaps legitimate 0.0 km/h wind for 5.0 km/h, silently breaking the `foehn_indicator` feature.
3. The `SimulatedMarket` generates 65 dictionaries per slot, creating 3.3 million useless objects per 5-year backtest, making it extremely slow.

---

## 🔴 CRITICAL BUGS (Sensor Glitches & Data Integrity)

### BUG 63: Ausência de filtro de outliers (Spike Filter) — Glitch do sensor força compra em bracket absurdo

**File:** `live_bot.py`, `backtester.py`  
**Severity:** 🔴 CRITICAL  
**Impact:** Se a API meteorológica (WU ou Open-Meteo) retornar um glitch temporário (ex: 99.0°C no inverno), a `running_max` dessa cidade passa a 99.0°C para o resto do dia. O modelo e o `SimulatedMarket` vão tentar comprar o bracket "99°C or higher", que é garantido perder. Não existe nenhum filtro de sanidade para temperatura.

**Broken Code (em `live_bot.py`, `_tick_city`):**
```python
            slot_entry = {
                "date": city_today,
                "hour": h_slot,
                "slot30": s30,
                "temp_c": new_obs["temp_c"], # BUG: 99.0°C é aceite sem validação
                # ...
            }
            state.slots_so_far.append(slot_entry)
```

**Fix:** Adicionar uma função de validação de sanidade baseada na climatologia da cidade, e aplicar antes de inserir no `slots_so_far`.

1. Criar um helper (em `live_bot.py` ou `utils.py`):
```python
def is_plausible_temp(temp_c: float, city: CityConfig) -> bool:
    """Verifica se a temperatura é plausível para a cidade (filtra glitches de API)."""
    if temp_c is None or np.isnan(temp_c) or np.isinf(temp_c):
        return False
    if not hasattr(city, 'climatology') or not city.climatology:
        return -40.0 <= temp_c <= 60.0  # Fallback genérico extremo
    
    # Margem de 25°C sobre os records históricos da climatologia mensal
    historic_max = max(city.climatology.values()) + 25.0
    historic_min = min(city.climatology.values()) - 25.0
    return historic_min <= temp_c <= historic_max
```

2. Aplicar em `_tick_city` (live_bot.py) antes de criar o `slot_entry`:
```python
            _temp = new_obs.get("temp_c")
            
            # FIX 63: Rejeitar glitches absurdos de temperatura
            if not is_plausible_temp(_temp, city):
                print(f"  {C['red']}{city.name}: REJECTED implausible temp: {_temp}°C{R}")
                # Skip this observation entirely
            else:
                slot_entry = {
                    "date": city_today,
                    "hour": h_slot,
                    "slot30": s30,
                    "temp_c": _temp,
                    # ... restante ...
                }
                # ... lógica normal de append/update ...
```

---

### BUG 64: Falsy check substitui vento 0.0 km/h por 5.0 km/h — Corrompe features de Foehn

**File:** `weather.py`  
**Severity:** 🔴 CRITICAL  
**Impact:** Na parsing da API WU, o código usa `obs.get("wspd") or 5.0`. Em Python, `0.0` é falsy. Se a velocidade do vento for calma absoluta (0.0 km/h), o bot substitui por 5.0 km/h. Isto corrompe as features `wind_speed_kmh` e `foehn_indicator` no modelo, que dependem de saber se o vento é exatamente 0 ou Sul. O mesmo acontece com `wind_gust_kmh`.

**Broken Code (em `_wu_parse_obs`):**
```python
        "wind_speed_kmh": float(obs.get("wspd") or 5) if obs.get("wspd") else 5.0,
        "wind_gust_kmh":  float(obs.get("gust") or 8) if obs.get("gust") else 8.0,
```

**Fix:** Usar `is not None` em vez de truthiness para preservar o 0.0 legítimo:
```python
        "wind_speed_kmh": float(obs.get("wspd")) if obs.get("wspd") is not None else 5.0,
        "wind_gust_kmh":  float(obs.get("gust")) if obs.get("gust") is not None else 8.0,
```

---

## 🟠 HIGH BUGS (Concurrency & Order States)

### BUG 65: Escritas não-atómicas em `PositionManager._save()` — Corrupção em crashes

**File:** `polymarket_clob.py`  
**Severity:** 🟠 HIGH  
**Impact:** A função `_save()` escreve diretamente no ficheiro final `paper_positions.json`. Se o bot crashar, for killed, ou perder luz precisamente durante a escrita, o ficheiro fica truncado (JSON inválido). No próximo restart, o bot lê um JSON vazio/corrompido e perde o histórico de todas as posições abertas, podendo re-abrir posições duplicadas.

Note-se que o `display.py` (no `write_live_snapshot`) já implementa escrita atómica correctamente com ficheiro `.tmp` + `replace()`, mas o `PositionManager` não.

**Broken Code (em `PositionManager._save`):**
```python
    def _save(self):
        try:
            self._path.write_text(json.dumps([p.to_dict() for p in self._positions], indent=2))
        except Exception:
            pass
```

**Fix:** Usar escrita atómica (write to temp + os.replace) para garantir que o ficheiro original nunca fica truncado:
```python
    def _save(self):
        try:
            import os
            data = json.dumps([p.to_dict() for p in self._positions], indent=2)
            tmp_path = self._path.with_suffix(".json.tmp")
            tmp_path.write_text(data)
            # os.replace é atómico na maioria dos filesystems modernos
            os.replace(tmp_path, self._path)
        except Exception:
            pass
```

---

### BUG 66: Registo de Position assume "filled size" igual a "requested size" em ordens GTC/Live

**File:** `polymarket_clob.py`  
**Severity:** 🟠 HIGH  
**Impact:** Quando uma ordem GTC é submetida e fica com estado `"live"` (parcialmente preenchida), o `ClobClient.buy_yes` regista a posição com o `size_usdc` e `shares` *solicitados* e não os *preenchidos*. O bot pensa que tem 10 shares, mas na realidade só comprou 3. Isto sobreestima a exposição financeira e o PnL futuro.

**Broken Code (em `ClobClient.buy_yes`, bloco REAL MODE):**
```python
            # shares calculado antes de saber o resultado
            shares = math.floor(size_usdc / price) if order_type.upper() == "FOK" else round(size_usdc / price, 4)
            # ...
            result = OrderResult(
                # ...
                size_usdc=round(size_usdc, 2), # BUG: Usa o size pedido, não o preenchido
                shares=shares, # BUG: Usa as shares pedidas, não as preenchidas
                # ...
            )
            # ...
            self.positions.add(Position(
                # ...
                shares=shares, # BUG
                size_usdc=round(size_usdc, 2), # BUG
                # ...
            ))
```

**Fix:** Tentar extrair o tamanho preenchido da resposta da API. Se não estiver disponível e o status for "live", usar o tamanho solicitado mas adicionar um aviso crítico.
```python
            # Após receber a resposta da API (response dict):
            # A API do Polymarket costuma retornar sizeFilled ou similar
            filled_size = float(response.get("sizeFilled", 0.0) or 0.0)
            filled_shares = filled_size  # Em shares, não em USDC
            
            if status == "matched" and filled_shares > 0:
                actual_shares = filled_shares
                actual_size_usdc = filled_shares * price
            elif status == "live":
                # Ordem parcialmente preenchida - usar dados parciais se disponíveis
                actual_shares = filled_shares if filled_shares > 0 else shares
                actual_size_usdc = actual_shares * price
                logger.warning(f"Order {order_id} is LIVE. Requested {shares} shares, filled {filled_shares}.")
            else:
                actual_shares = shares
                actual_size_usdc = size_usdc

            result = OrderResult(
                # ...
                size_usdc=round(actual_size_usdc, 2),
                shares=actual_shares,
                # ...
            )
            # ...
            if result.success:
                self.positions.add(Position(
                    # ...
                    shares=actual_shares,
                    size_usdc=round(actual_size_usdc, 2),
                    # ...
                ))
```

---

## 🟡 MEDIUM BUGS (API Edge Cases & Performance)

### BUG 67: Observações atrasadas (Late-arriving) alteram retroativamente o `running_max`

**File:** `live_bot.py`  
**Severity:** 🟡 MEDIUM  
**Impact:** Por vezes, a API WU envia observações atrasadas (ex: dados das 10:00 chegam às 10:30). O bot insere estes dados no `slots_so_far`. Se a temperatura das 10:00 for mais alta do que a das 10:30, o `running_max` do dia **sobe retroativamente**. Se o bot já tinha comprado o bracket "20°C" baseado num max anterior de 20.1°C, e o dado atrasado diz 21.0°C, o bracket comprado fica agora *abaixo* do novo `running_max`, podendo triggerar um stop-loss falso ou garantir uma perda.

**Fix:** Impedir que dados de slots passados aumentem o `running_max` após uma compra já ter sido efetuada.

Em `_tick_city`, no bloco `if exists:`, ao atualizar o slot existente:
```python
            if exists:
                for s in state.slots_so_far:
                    if s["hour"] == h_slot and s["slot30"] == s30:
                        # FIX 67: Se já comprámos, não deixar um dado atrasado aumentar o running_max
                        if state.entry and state.entry.bought:
                            current_rmax = max(sl["temp_c"] for sl in state.slots_so_far)
                            current_max_hour = max(sl["hour"] for sl in state.slots_so_far)
                            
                            # Se o slot que estamos a atualizar é mais antigo que o slot mais recente
                            # E a sua temperatura é mais alta do que o running_max atual
                            if h_slot < current_max_hour and slot_entry["temp_c"] > current_rmax:
                                # Dado atrasado que aumentaria o max after buy - clamp ao max atual
                                slot_entry["temp_c"] = s["temp_c"]  # Manter temp antiga
                                print(f"  {C['yellow']}{city.name}: Clamped late-arriving high temp to protect running_max post-buy{R}")
                        
                        # Atualizar slot (código existente com o Fix 56 aplicado)
                        s["temp_c"] = slot_entry["temp_c"]
                        if new_obs:
                            for key in ["humidity", "cloud_cover", "dewpoint_c", "pressure_hpa", 
                                        "wind_dir_deg", "wind_speed_kmh", "wind_gust_kmh", "uv_index"]:
                                if key in new_obs and new_obs[key] is not None:
                                    s[key] = slot_entry[key]
                        break
```

---

### BUG 68: `SimulatedMarket` gera 65 brackets iteirados por slot — Backtest extremamente lento

**File:** `backtester.py`  
**Severity:** 🟡 MEDIUM  
**Impact:** O `SimulatedMarket` usa `self.temp_range = range(-15, 50)`. Isto gera 65 dicionários por chamada. Em 5 anos * 365 dias * 28 slots = ~51.000 chamadas, resultando na criação de **3.3 milhões de dicionários** de brackets, 95% dos quais têm `ask = 0.01` e `bid = 0.0`. Isto torna o backtest desnecessariamente lento.

**Fix:** Gerar apenas brackets relevantes (janela dinâmica em torno do `running_max`).

Em `SimulatedMarket.get_brackets`, substituir o loop `for temp in self.temp_range:` por uma janela inteligente:
```python
    def get_brackets(self, p_ensemble: float, running_max: float, hour: int) -> list[dict]:
        if np.isnan(running_max) or np.isinf(running_max):
            running_max = 15.0
        
        import math
        # O bracket alvo no Polymarket é o piso (floor) da temperatura actual (Fix 58)
        rmax_floor = int(math.floor(running_max))
        
        # FIX 68: Janela dinâmica em vez de todo o range (-15 a 49)
        # Gerar brackets de rmax - 4 até rmax + 4, mais os extremos para "or lower" / "or higher"
        relevant_temps = set()
        relevant_temps.add(self.temp_range[0])  # Ex: "-15°C or lower"
        relevant_temps.add(self.temp_range[-1]) # Ex: "49°C or higher"
        
        window_min = max(self.temp_range[0] + 1, rmax_floor - 4)
        window_max = min(self.temp_range[-1], rmax_floor + 5)
        
        for t in range(window_min, window_max):
            relevant_temps.add(t)
            
        brackets = []
        # Preservar a lógica existente, mas iterar só sobre relevant_temps
        for temp in sorted(relevant_temps):
            signed_dist = temp - rmax_floor
            dist = abs(signed_dist)
            temp_below_rmax = signed_dist < 0

            # ... (toda a lógica de _climatological_ask, model_nudge, noise, labelling existente) ...
```

Isto reduz a criação de dicionários de 65 para ~11 por slot, acelerando o backtest em ~6x sem alterar o comportamento do mercado simulado para as brackets que o bot efetivamente tenta comprar.

---

## 📊 Resumo da Ronda 4

| Bug # | Severity | Componente | Impacto Principal |
|-------|----------|------------|-------------------|
| 63 | 🔴 CRÍTICO | Live/Predictor | Sensor glitch (ex: 99°C) força compra em bracket impossível |
| 64 | 🔴 CRÍTICO | Weather | Vento 0.0 km/h substituído por 5.0, corrompendo features de Foehn |
| 65 | 🟠 ALTO | CLOB | Escrita não-atómica corrompe ficheiro de posições em crashes |
| 66 | 🟠 ALTO | CLOB | Posição regista size pedido em vez de size preenchido (parcial fill) |
| 67 | 🟡 MÉDIO | Live | Dados atrasados alteram running_max retroativamente após compra |
| 68 | 🟡 MÉDIO | Backtester | Geração de 3.3M brackets inúteis torna backtest extremamente lento |
