```markdown
# 🐛 Bugfix9 — Round 10 Deep Audit & Fix Document

**Project:** Polymarket Temperature Bot (Multi-City)  
**Date:** 2024-05 (Round 10)  
**Focus:** ML Target Leakage & The "Race Condition" in Real-Time Peak Detection  
**Total Issues Found:** 5  
**Severity Breakdown:** 🔴 Critical (2) | 🟠 High (3)

---

## 📋 Executive Summary

Round 10 focused on the **fundamental alignment between the Machine Learning objective and the Financial Viability** of the strategy. The model is correctly designed to answer: *"Are we at the peak NOW?"* rather than *"When will the peak be?"*. However, this creates a severe **Race Condition with the Market**.

By the time the model is confident that the peak has been reached (temperature stops rising, `accel ≤ 0`), the Polymarket market makers and other traders *also* know the peak has been reached. The bracket price instantly jumps to 90¢+, meaning the bot is trying to buy a 95¢ contract that only pays $1.00. The Expected Value (EV) of these trades is devastatingly negative.

The fixes below re-align the training target and strategy filters to force the model to act **slightly before the inflection point**, ensuring the bot buys while there is still upside left.

---

## 🔴 CRITICAL BUGS (Negative Expected Value & False Peaks)

### BUG 95: O modelo deteta o pico tarde demais — Compras a 95¢ com ROI negativo garantido

**File:** `train.py`, `modules/single_entry.py`  
**Severity:** 🔴 CRITICAL  
**Impact:** O label `1 if (i == peak_idx)` treina o modelo para maximizar a probabilidade no *exato slot* em que a temperatura atinge o máximo e para de subir. Quando o modelo dispara o sinal "P(pico) = 0.95", o mercado do Polymarket já viu a temperatura estabilizar. O ask do bracket salta instantaneamente para 90¢-95¢. O bot arrisca 95¢ para ganhar 5¢.

**Broken Code (em `train.py`, `build_dataset`):**
```python
        peak_temp = valid_temps.max()
        # ...
        label = 1 if (i == peak_idx) else 0
```

**Fix:** Treinar o modelo para detetar o **início do plateau do pico** (quando a temperatura atinge 98% do pico e ainda está a subir), em vez do ponto exato da viragem. Isto dá ao bot uma janela de 30-60 minutos para comprar antes de o mercado se ajustar.

```python
        peak_temp = valid_temps.max()
        # FIX 95: Alargar a label para incluir os slots que antecipam o pico
        near_peak_threshold = peak_temp * 0.98  # 98% do pico absoluto
        
        for row in day_df.itertuples(index=True):
            i = row.Index
            temp = float(row.temp_c)
            
            # Marca 1 se está no pico OU se está muito perto do pico E antes do pico absoluto
            # Isto ensina o modelo a disparar no "início do plateau"
            label = 1 if (temp >= near_peak_threshold and i <= peak_idx) else 0
```

---

### BUG 96: A Armadilha do Pico Local — Compras em falsos picos causadas por nuvens passageiras

**File:** `train.py`, `live_bot.py`  
**Severity:** 🔴 CRITICAL  
**Impact:** O label só marca o *pico global* do dia. O modelo reage ao `accel < 0`. Em dias de clima variável, uma nuvem faz a temperatura cair às 14h (Pico Local). O modelo disora "Já estamos no pico!", o bot compra o bracket "25°C". Às 16h o sol volta, a temperatura sobe para 27°C (Pico Global). O bracket expira a zero.

**Fix:** 
1. No **Treino**, marcar também picos locais significativos para que o modelo aprenda o padrão de "falso pico" vs "pico real".
2. Na **Live**, adicionar um filtro de segurança baseado na radiação solar ou na previsão do dia.

*Fix em `train.py`:*
```python
            # FIX 96: Marcar picos locais significativos (>90% do pico global)
            # para que o modelo aprenda a distingui-los dos picos globais
            is_global_peak = (i == peak_idx)
            is_significant_local_peak = False
            
            # Detetar máximos locais (subida seguida de descida)
            if 0 < i < len(day_df) - 1:
                prev_temp = float(day_df.iloc[i-1]["temp_c"])
                next_temp = float(day_df.iloc[i+1]["temp_c"])
                if temp > prev_temp and temp > next_temp and temp >= peak_temp * 0.90:
                    is_significant_local_peak = True
            
            label = 1 if (is_global_peak or is_significant_local_peak) else 0
```

*Fix em `live_bot.py` (Filtro de segurança):*
```python
            # Antes de aceitar a ação de compra do SingleEntry:
            if p_ensemble >= city.threshold:
                # FIX 96: Se a radiação solar (proxy) ainda está alta e a hora é cedo,
                # provavelmente é um pico local. Não comprar.
                slot_frac = (h_cur + s30_cur / 60.0) / 24.0
                is_late_afternoon = slot_frac > 0.60 # Depois das 14h-15h
                
                if not is_late_afternoon and p_ensemble < 0.90:
                    # É manhã/início da tarde e o modelo não tem a certeza absoluta
                    # Pode ser um pico local. Abortar para segurança.
                    pass # Skip buy
```

---

## 🟠 HIGH BUGS (Métricas e Risco/Retorno)

### BUG 97: `morning_max` é uma feature com Leakage Silencioso

**File:** `predictor.py`  
**Severity:** 🟠 HIGH  
**Impact:** A feature `morning_max` é calculada dinamicamente: `max(morn_vals)` onde `morn_vals = [s["temp_c"] for s in slots_so_far[:-1] if s.get("hour", 0) <= 12]`. Se o slot atual for às 10h, `morning_max` exclui o slot atual. Isto é inconsistente e enviesado: o modelo compara a temp atual com um passado filtrado de forma diferente dependendo da hora, criando padrões artificiais.

**Broken Code (em `build_features`):**
```python
    morn_vals = [s["temp_c"] for s in slots_so_far[:-1] if s.get("hour", 0) <= 12]
    mmax = max(morn_vals) if morn_vals else cur
```

**Fix:** Calcular o `morning_max` de forma fixa e imutável: o máximo estrito até às 12h, independentemente da hora atual.
```python
    # FIX 97: morning_max consistente
    if hour <= 12:
        # Ainda é de manhã, o max da manhã é o max atual até ao slot presente
        morn_vals = [s["temp_c"] for s in slots_so_far if s.get("hour", 0) <= 12]
    else:
        # Já passou a manhã, usar max FIXO do período 6h-12h
        morn_vals = [s["temp_c"] for s in slots_so_far if s.get("hour", 0) <= 12]
    
    mmax = max(morn_vals) if morn_vals else cur
```

---

### BUG 98: AUC não é a métrica certa — O modelo optimiza para o tempo errado

**File:** `train.py`  
**Severity:** 🟠 HIGH  
**Impact:** O LightGBM optimiza para AUC, que trata Falsos Positivos e Falsos Negativos igualmente. No Polymarket:
- Um **Falso Positivo** (comprar num falso pico) é **catastrófico** — perde-se 100%.
- Um **Falso Negativo** (não detetar o pico) é **irrelevante** — apenas perde-se lucro.
O modelo actual foca-se em não perder nenhum pico (alto recall), o que aumenta os falsos positivos.

**Fix:** Dizer ao LightGBM que a classe 1 (pico) é muito mais importante de se prever corretamente do que a classe 0.
```python
# Em train.py, no dicionário LGB_PARAMS:
LGB_PARAMS = {
    "n_estimators": 600,
    "learning_rate": 0.02,
    "max_depth": 6,
    "num_leaves": 60,
    "objective": "binary",
    # FIX 98: Penalizar pesadamente os Falsos Positivos
    # scale_pos_weight = (n_amostras_negativas / n_amostras_positivas) * fator_ajuste
    # Um fator de 0.5 força o modelo a ser mais conservador
    "is_unbalance": True,  
}
```

---

### BUG 99: O Backtester aceita sinais tardios como "sucesso" — Esconde EV negativo

**File:** `backtester.py`, `modules/single_entry.py`  
**Severity:** 🟠 HIGH  
**Impact:** O backtester compra quando o modelo diz "Já estamos no pico!". O `SimulatedMarket` reage à estabilização e dá um ask de 90¢. O backtester compra a 90¢, ganha 10¢, e soma ao PnL como sucesso. Na realidade, este trade tem um risco/retorno horrível (arriscar 90¢ para ganhar 10¢). O backtester parece lucrativo, mas a estratégia é um dreno de capital na vida real.

**Fix:** Adicionar um filtro estrito de Risco/Retorno (MAX_ASK_BUY): Nunca comprar se o ask exceder um limiar.

```python
# Em backtester.py, definir constante no topo:
MAX_ASK_BUY = 0.75  # Payoff mínimo de 33% (1/0.75 - 1)

# Na lógica de compra do run_backtest:
                for act in entry_single.evaluate(p_ens, h, market_sim, running_max, fc_agreement):
                    if act.get("size_usdc", 0) > 0:
                        best = act.get("bracket")
                        if not best:
                            import math
                            target_temp = int(math.floor(running_max))
                            best = next((b for b in brackets if b["temp_lo"] <= target_temp <= b["temp_hi"]), None)
                        
                        # FIX 99: Rejeitar entradas tarde demais (ask demasiado alto)
                        if best and best["ask"] > MAX_ASK_BUY:
                            # Mercado já precificou o pico, não há lucro possível
                            break
                        
                        if best:
                            entry_single.mark_bought(0, {
                                "hour": h, "slot30": s,
                                "ask": best["ask"],
                                "bracket_label": best["label"],
                                "temp_lo": best["temp_lo"],
                                "temp_hi": best["temp_hi"],
                                "size_usdc": act["size_usdc"],
                            })
                        break
```

---

## 📊 Resumo da Ronda 10

| Bug # | Severity | Componente | Impacto Principal |
|-------|----------|------------|-------------------|
| 95 | 🔴 CRÍTICO | Train/Predictor | Modelo dispara tardiamente; mercado já a 95¢, ROI negativo |
| 96 | 🔴 CRÍTICO | Train/Live | Armadilha de Pico Local; bot compra e depois a temp sobe mais |
| 97 | 🟠 ALTO | Predictor | `morning_max` inconsistente causa leakage de comparação enviesada |
| 98 | 🟠 ALTO | Train | AUC trata FP e FN igualmente; FPs deviam ser penalizados |
| 99 | 🟠 ALTO | Backtester | Backtester valida compras a 90¢ como sucesso, escondendo EV negativo |
---

## ❌ VOID / INCORRECT BUGS

### ~~BUG 80: Gas Fees (Rede Polygon) ignoradas no ROI acumulado~~
**Status:** INVALID  
**Reason:** Polymarket operates on the Polygon network where gas fees are negligible and covered by the platform/relayer. No gas fee deductions should be applied to the trading PnL.
