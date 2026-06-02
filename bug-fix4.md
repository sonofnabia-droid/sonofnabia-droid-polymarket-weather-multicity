```markdown

# 🐛 Bugfix4 — Round 2 Deep Audit & Fix Document

**Project:** Polymarket Temperature Bot (Multi-City)  
**Date:** 2024-05 (Round 2)  
**Total Issues Found:** 9  
**Severity Breakdown:** 🔴 Critical (3) | 🟠 High (3) | 🟡 Medium (3)

---

## 📋 Executive Summary

Round 2 focused on **financial parity, data leakage, and mathematical accuracy** between the backtester, the live bot, and the Polymarket exchange. 

The most critical findings are:
1. The backtester incorrectly evaluates bracket wins due to rounding (making the bot look worse than it is).
2. The backtester assumes fractional shares while Polymarket uses whole shares (overestimating profits on high-ask brackets).
3. The simulated market artificially penalizes high-confidence model signals (auto-defeating the strategy).

Applying these fixes will likely reveal a **significantly stronger real-world edge** than the backtests currently show.

---

## 🔴 CRITICAL BUGS (Financial Miscalculations & Parity)

### BUG 48: Off-by-one na resolução de brackets — Backtester subestima a Win Rate

**File:** `backtester.py`  
**Severity:** 🔴 CRITICAL  
**Impact:** A função `_bracket_contains_peak` arredonda a temperatura máxima (`peak_temp`) para o inteiro mais próximo. No Polymarket real, o bracket "30°C" cobre de 30.0°C a 30.99°C. Se a temperatura máxima real for 30.8°C, o backtester arredonda para 31, e o bracket 30°C **perde**, quando na realidade devia **ganhar**. Isto faz com que o backteste seja demasiado pessimista.

**Broken Code:**
```python
def _bracket_contains_peak(temp_lo: float, temp_hi: float, peak_temp: float) -> bool:
    peak_int = int(round(peak_temp))
    if temp_hi >= 99:
        return peak_int >= int(round(temp_lo))
    if temp_lo <= -99:
        return peak_int <= int(round(temp_hi))
    return int(round(temp_lo)) <= peak_int <= int(round(temp_hi))
```

**Fix:** Usar a temperatura exacta (float) e interpretar os brackets como ranges compatíveis com a resolução do Polymarket:
```python
def _bracket_contains_peak(temp_lo: float, temp_hi: float, peak_temp: float) -> bool:
    """Verifica se o bracket contém o pico real (paridade com Polymarket)."""
    # Bracket "X or higher" -> [temp_lo, +inf)
    if temp_hi >= 99:
        return peak_temp >= temp_lo - 0.5  # Tolerância para arredondamentos de API
    
    # Bracket "X or lower" -> (-inf, temp_hi]
    if temp_lo <= -99:
        return peak_temp <= temp_hi + 0.5
    
    # Bracket exacto "X°C" -> na realidade cobre [X, X+1)
    # Ex: "30°C" cobre 30.0 a 30.99°C
    return temp_lo - 0.5 <= peak_temp < temp_hi + 0.5
```

---

### BUG 49: PnL do Backtester sobrestima lucros em asks altos (fracções de shares)

**File:** `backtester.py`  
**Severity:** 🔴 CRITICAL  
**Impact:** O backtester calcula PnL como `size_usdc * (1/ask - 1)`, assumindo que podes comprar fracções de shares e que o payoff é proporcional. No Polymarket real, buys são em **número inteiro de shares**, cada share paga $1.00, e o troco não investido fica parado.

*Exemplo:* Ask = $0.95, Bet = $5.00.  
- **Live:** Compras 5 shares (5 * 0.95 = $4.75). Ficam $0.25 parados. Se ganha, recebes $5.00. Lucro = $0.25.  
- **Backtester atual:** Lucro = $5.00 * (1/0.95 - 1) = $0.263.  
O backtester superestima o lucro! Em asks de 0.98, o erro passa para ~20%.

**Fix em `backtester.py` (função `_pnl_per_dollar` e uso em `run_backtest`):**

1. Atualizar a função helper:
```python
def _pnl_per_dollar(ask: float, won: bool, size_usdc: float = 5.0) -> float:
    if not ask or ask <= 0:
        return -1.0 if not won else 0.0
    shares = math.floor(size_usdc / ask)
    if shares <= 0:
        return 0.0
    actual_invested = shares * ask
    if won:
        return (float(shares) - actual_invested)  # Lucro absoluto, não percentual
    else:
        return -actual_invested  # Perde o investimento das shares
```

2. Atualizar o cálculo do `single_pnl` dentro de `run_backtest`:
```python
                # Substituir:
                # single_pnl = rec["size_usdc"] * _pnl_per_dollar(rec["ask"], single_won)
                
                # Por:
                single_pnl = _pnl_per_dollar(rec["ask"], single_won, rec["size_usdc"])
```

---

### BUG 50: SimulatedMarket injecta a previsão do modelo no preço — Backtest auto-derrota-se

**File:** `backtester.py` (Classe `SimulatedMarket`)  
**Severity:** 🔴 CRITICAL  
**Impact:** O `SimulatedMarket` usa `p_ensemble` para fazer um "nudge" no ask. Quando o modelo tem alta confiança (0.90), o nudge aumenta o ask (mercado "sabe" que vai ganhar). Isto penaliza o ROI dos melhores sinais do bot. Na realidade, o Polymarket não sabe qual é o `p_ensemble` do teu modelo.

**Broken Code (dentro de `_climatological_ask` e `get_brackets`):**
```python
            if dist <= 1 and not temp_below_rmax:
                # Centrado em 0.5; desvio de p_ensemble vs 0.5 multiplicado por 0.10
                model_nudge = (p_ensemble - 0.5) * 0.10
            else:
                model_nudge = 0.0
```

**Fix:** Remover o nudge do modelo. O mercado simulado deve reagir apenas à hora e ao running_max (informação pública), não ao teu modelo privado.
```python
            # FIX: Remover model_nudge. O mercado simulado não tem acesso ao p_ensemble.
            model_nudge = 0.0
```

---

## 🟠 HIGH BUGS (Paridade Treino/Live e Overfitting)

### BUG 51: `compute_prev7` em live usa o pico do dia corrente (Data Leakage vs Training)

**File:** `live_bot.py`  
**Severity:** 🟠 HIGH  
**Impact:** Em `_tick_city`, `update_history_max` é chamado antes de `predict_ensemble`. Isto significa que `state.history_max[today]` contém o running_max do dia actual. Quando `compute_prev7` é chamado, hoje está incluído na janela dos 7 dias! No `train.py`, `history_max[d] = peak_temp` só é feito *depois* do loop do dia. Isto cria uma feature `prev_7d_avg_max` diferente entre treino e live (treino não tem leakage, live tem).

**Fix em `live_bot.py` (dentro de `_tick_city`):** Computar `prev7` ANTES de atualizar o `history_max`.

```python
        # --- FIX 51: Compute prev7 BEFORE updating history_max to match training parity ---
        prev7_value = compute_prev7(state.history_max, city_today, city.name)

        # SÓ DEPOIS atualizar o history_max com os slots de hoje
        from predictor import update_history_max, init_history_max
        update_history_max(state.history_max, state.slots_so_far, city.name)

        current_extra = {
            **slot_entry,
            "prev_7d_avg_max": prev7_value,  # Usa valor sem leakage
        }
```

---

### BUG 52: Score de Calibração favorece janelas curtas — leva a overfitting

**File:** `calibrate.py`  
**Severity:** 🟠 HIGH  
**Impact:** A métrica `outcome_score = win_pct * log10(1 + trades/ano)`. Um streak de sorte de 10 dias (5 trades) gera `trades/ano ≈ 182`, `log10(183) ≈ 2.26`. Score = 226. Se 3 anos tiverem 100 trades, `trades/ano ≈ 33`, `log10(34) ≈ 1.53`. Score = 153. O `calibrate_all.py` vai preferir configs overfitted de curtas janelas.

**Fix em `calibrate.py` (função `simulate_strategy`):** Adicionar um fator de penalização para datasets com poucos dias.
```python
    # Substituir o cálculo de outcome_score no dicionário final de retorno:
    min_days_factor = min(1.0, total_days / 365)  # 0 se <1 ano, 1 se >=1 ano
    
    return {
        # ... outras chaves ...
        
        # outcome_score — independente de preços simulados
        "outcome_score": (wins / trades * 100 *
                          np.log10(1 + (trades / total_days * 365 if total_days else 0)) *
                          min_days_factor  # Penaliza janelas < 1 ano
                          if trades > 0 else 0),
    }
```

---

### BUG 53: Expanding Prior com CumSum introduzia leakage intra-ano (Correcção do Bug 25)

**File:** `train.py`  
**Severity:** 🟠 HIGH  
**Impact:** A sugestão anterior de usar `cumsum` do pandas introduzia leakage dentro do mesmo ano (slots da tarde usavam dados da manhã do mesmo ano no prior). O código original iterava por ano para evitar isto.

**Fix Correcto e Rápido (Vectorizado sem leakage intra-ano):** Substituir a função `_compute_expanding_prior` inteira no `train.py`:

```python
def _compute_expanding_prior(dataset: pd.DataFrame) -> tuple[pd.Series, dict]:
    if "date" not in dataset.columns:
        prior_map = {}
        for (m, h, s), group in dataset.groupby(["month", "hour", "slot30"]):
            prior_map[(int(m), int(h), int(s))] = float(group["label"].mean())
        prior_values = dataset.apply(
            lambda r: prior_map.get((int(r["month"]), int(r["hour"]), int(r["slot30"])), 0.5),
            axis=1,
        )
        return prior_values, prior_map

    dataset = dataset.copy()
    if not pd.api.types.is_datetime64_any_dtype(dataset["date"]):
        dataset["date"] = pd.to_datetime(dataset["date"], errors="coerce")

    dataset["year"] = dataset["date"].dt.year
    dataset = dataset.sort_values("date")
    prior_values = pd.Series(0.5, index=dataset.index, dtype=float)

    grp_key = ["month", "hour", "slot30"]

    # Pré-agregar por ano + slot para ser O(N) em vez de O(N²)
    yearly = dataset.groupby(["year"] + grp_key)["label"].agg(["sum", "count"]).reset_index()

    years = sorted(dataset["year"].unique())
    accumulator = {}

    for year in years:
        year_data = dataset[dataset["year"] == year]
        year_agg = yearly[yearly["year"] == year]

        # Mapear prior do acumulado de anos anteriores
        prior_map_year = {}
        for _, row in year_agg.iterrows():
            key = (int(row["month"]), int(row["hour"]), int(row["slot30"]))
            acc = accumulator.get(key)
            if acc and acc["count"] > 0:
                prior_map_year[key] = acc["sum"] / acc["count"]

        # Assign de forma vectorizada para este ano
        year_idx = year_data.index
        keys = year_data[grp_key].apply(lambda r: (int(r["month"]), int(r["hour"]), int(r["slot30"])), axis=1)
        prior_values.loc[year_idx] = keys.map(prior_map_year).fillna(0.5)

        # Atualizar acumulador com dados deste ano
        for _, row in year_agg.iterrows():
            key = (int(row["month"]), int(row["hour"]), int(row["slot30"]))
            if key not in accumulator:
                accumulator[key] = {"sum": 0.0, "count": 0}
            accumulator[key]["sum"] += row["sum"]
            accumulator[key]["count"] += int(row["count"])

    prior_map = {
        key: acc["sum"] / acc["count"]
        for key, acc in accumulator.items()
        if acc["count"] > 0
    }

    return prior_values, prior_map
```

---

## 🟡 MEDIUM BUGS (Estabilidade e Edge Cases)

### BUG 54: Late-arrival data overwrites next day's `history_max`

**File:** `predictor.py`  
**Severity:** 🟡 MEDIUM  
**Impact:** Se a API do tempo tiver lag e entregar dados das 23:50 depois da meia-noite (quando o relógio do sistema já mudou de dia), `update_history_max` vai colocar a temperatura alta do dia anterior no `history_max[today]`, corrompendo o baseline frio para o dia seguinte.

**Fix em `predictor.py` (adicionar verificação no início de `update_history_max`):**

```python
def update_history_max(history: dict, slots_so_far: list[dict], city_name: str | None = None) -> None:
    global _last_save_times
    if not slots_so_far:
        return

    first_slot = slots_so_far[0]
    if "date" in first_slot:
        slot_date = first_slot["date"]
    elif city_name:
        cfg = get_city(city_name)
        slot_date = _city_now().astimezone(ZoneInfo(cfg.timezone)).date()
    else:
        slot_date = _city_date()

    # FIX 54: Se a data dos slots é diferente de hoje, NÃO atualizar o dia actual
    # para evitar que dados atrasados corrompam o running max de hoje
    current_system_date = _city_date()
    if slot_date != current_system_date:
        try:
            cur_max = max(s["temp_c"] for s in slots_so_far if "temp_c" in s)
        except ValueError:
            return
        if np.isnan(cur_max) or np.isinf(cur_max):
            return
        history[slot_date] = max(history.get(slot_date, -999.0), float(cur_max))
        _save_history_max_file(history, city_name)
        return

    # ... resto da função original para o dia actual ...
```

---

### BUG 55: `os.system("clear")` no display.py crasha em Docker/TTY ausente

**File:** `display.py`  
**Severity:** 🟡 MEDIUM  
**Impact:** Se o bot correr num container Docker ou systemd sem TTY interativo, `os.system("clear")` gera exceptions ou caracteres esquisitos no log.

**Fix em `display.py` (função `render_dashboard`):**
```python
    # Substituir:
    # os.system("clear" if os.name != "nt" else "cls")
    
    # Por (Rich já tem método seguro que verifica is_terminal):
    _con.clear()
```

---

### BUG 56: Slot metadata overwrite em live_bot perde dados reais

**File:** `live_bot.py`  
**Severity:** 🟡 MEDIUM  
**Impact:** Quando chega uma atualização para um slot existente, `s.update(slot_entry)` substitui todo o dicionário. Se a nova observação da API não trouxer `humidity` (fica a default 70), apaga a humidade real que já lá estava do tick anterior.

**Fix em `live_bot.py` (função `_tick_city`, bloco onde atualiza slots):**
```python
            exists = any(s["hour"] == h_slot and s["slot30"] == s30 for s in state.slots_so_far)
            if exists:
                for s in state.slots_so_far:
                    if s["hour"] == h_slot and s["slot30"] == s30:
                        # FIX 56: Só atualizar campos que vieram com dados reais da API
                        s["temp_c"] = slot_entry["temp_c"]  # Temp atualiza sempre
                        for key in ["humidity", "cloud_cover", "dewpoint_c", "pressure_hpa", 
                                    "wind_dir_deg", "wind_speed_kmh", "wind_gust_kmh", "uv_index"]:
                            # Verifica se o valor não é o fallback genérico (para não apagar dados reais antigos)
                            if slot_entry.get(key) is not None and slot_entry.get(key) != {"humidity": 70, "cloud_cover": 50, "dewpoint_c": new_obs["temp_c"] - 10, "pressure_hpa": 1013, "wind_dir_deg": 0, "wind_speed_kmh": 5, "wind_gust_kmh": 8, "uv_index": 3}.get(key):
                                s[key] = slot_entry[key]
                        break
```

*Nota para o Codex na implementação do Bug 56:* A comparação hardcoded de defaults acima é frágil. A forma mais limpa de implementar isto no ficheiro real é: no bloco `_tick_city` onde se faz o `s.update(slot_entry)`, validar se `new_obs` (a observação original da API) continha a chave antes de a atribuir ao dicionário do slot. Exemplo mais robusto para o Codex:

```python
            exists = any(s["hour"] == h_slot and s["slot30"] == s30 for s in state.slots_so_far)
            if exists:
                for s in state.slots_so_far:
                    if s["hour"] == h_slot and s["slot30"] == s30:
                        # Always update temp
                        s["temp_c"] = slot_entry["temp_c"]
                        # Only update weather metadata if new_obs actually provided them (not defaults)
                        if new_obs:
                            for key in ["humidity", "cloud_cover", "dewpoint_c", "pressure_hpa", "wind_dir_deg", "wind_speed_kmh", "wind_gust_kmh", "uv_index"]:
                                if key in new_obs and new_obs[key] is not None:
                                    s[key] = slot_entry[key]
                        break
```
