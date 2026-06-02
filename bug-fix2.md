```markdown
# Bugfix Document — Polymarket Temperature Bot

**Data da Análise:** 2024-05
**Alvo:** Backtester, Live Bot, Predictor, Training Pipeline, Display, Polymarket CLOB

Este documento detalha 24 bugs encontrados no projeto, organizados por severidade. 
Cada bug contém a localização exata, descrição do problema, impacto e o código de fix (Before/After) para aplicação automatizada via Codex.

---

## 🔴 CRITICAL — Decisões de Trading Incorretas ou Perdas Financeiras

### Bug 1: Conversão de Unidades de Vento Errada (3.6× demasiado alto)
**Ficheiro:** `weather.py`
**Localização:** `_wu_parse_obs()` (aprox. linha 170)

**Descrição:** A API do Weather Underground com `units=m` (métrico) retorna velocidade do vento em **km/h**, não em m/s. O código multiplica por 3.6, inflando os valores 3.6×.
**Impacto:** Features `wind_speed_kmh`, `wind_gust_kmh` e `foehn_indicator` ficam corruptas. O modelo treina e infere com dados de vento totalmente errados.

**Before:**
```python
"wind_speed_kmh": float(obs.get("wspd") or 5) * 3.6 if obs.get("wspd") else 5.0,
"wind_gust_kmh":  float(obs.get("gust") or 8) * 3.6 if obs.get("gust") else 8.0,
```

**After:**
```python
"wind_speed_kmh": float(obs.get("wspd") or 5) if obs.get("wspd") else 5.0,
"wind_gust_kmh":  float(obs.get("gust") or 8) if obs.get("gust") else 8.0,
```

---

### Bug 2: Train/Test Mismatch — Treino Não Filtra Horas Noturnas
**Ficheiro:** `train.py`
**Localização:** `build_dataset()`, loop interno `for i, row in day_df.iterrows():`

**Descrição:** O backtester e o live bot filtram observações para `hour ∈ [day_start, day_end]`, mas o pipeline de treino processa **todas as horas** incluindo a noite. O modelo aprende padrões de horas em que nunca opera em produção.
**Impacto:** O modelo fica enviesado para padrões noturnos que não existem durante o dia de trading, baixando a performance real.

**Before:**
```python
        for i, row in day_df.iterrows():
            h = int(row["hour"])
            slot30 = int(row.get("slot30", 0))
            temp = float(row["temp_c"])
            label = 1 if (i == peak_idx) else 0
```

**After:**
```python
        for i, row in day_df.iterrows():
            h = int(row["hour"])
            if h < city.day_start or h > city.day_end:
                continue
            slot30 = int(row.get("slot30", 0))
            temp = float(row["temp_c"])
            label = 1 if (i == peak_idx) else 0
```

---

### Bug 3: `prev_7d_avg_max` Inconsistente entre Backtester e Live
**Ficheiros:** `predictor.py` e `backtester.py`
**Localização:** `predictor.py -> compute_prev7()`, `backtester.py -> _compute_prev7_map()`

**Descrição:** O backtester usa janela de 7 dias corridos (`(d - dd).days <= 7`). O predictor (live) usa os 7 índices anteriores do dicionário (`days[max(0, idx - 7):idx]`). Com dados faltantes, o live calcula médias de mais de 7 dias. Além disso, ambos usam fallback hardcoded de `15.0` em vez da climatologia da cidade.
**Impacto:** As features de entrada durante a inferência live divergem do treino/backtest. Fallback de 15°C é absurdo para cidades quentes (Lagos, Phoenix).

**Before (predictor.py):**
```python
    idx = days.index(d)
    if idx == 0:
        return float(history[d])
    window = days[max(0, idx - 7):idx]
    vals = [history[x] for x in window]
    return float(np.mean(vals)) if vals else float(history[d])
```

**After (predictor.py):**
```python
    idx = days.index(d)
    if idx == 0:
        return float(history[d])
    
    from datetime import timedelta
    cutoff = d - timedelta(days=7)
    window = [dd for dd in days[:idx] if dd >= cutoff]
    
    vals = [history[x] for x in window]
    return float(np.mean(vals)) if vals else climatology.get(d.month, 15.0)
```

**Before (backtester.py):**
```python
def _compute_prev7_map(df: pd.DataFrame) -> dict:
    # ...
        if not window_dates:
            prev7[d] = 15.0
        else:
            window = daily_max[window_dates]
            prev7[d] = float(window.mean()) if len(window) else 15.0
    return prev7
```

**After (backtester.py):** (Adicionar parâmetro `city: CityConfig` à assinatura)
```python
def _compute_prev7_map(df: pd.DataFrame, city: CityConfig) -> dict:
    daily_max = df.groupby("date")["temp_c"].max().sort_index()
    dates_list = list(daily_max.index)
    climatology = city.climatology if city.climatology else {i: 15.0 for i in range(1, 13)}
    prev7 = {}
    for d in dates_list:
        window_dates = [dd for dd in dates_list if dd < d and (d - dd).days <= 7]
        if not window_dates:
            prev7[d] = climatology.get(d.month, 15.0)
        else:
            window = daily_max[window_dates]
            prev7[d] = float(window.mean()) if len(window) else climatology.get(d.month, 15.0)
    return prev7
```
*(Nota ao Codex: Atualizar a chamada em `run_backtest()` para passar o `city` argumento: `prev7_map = _compute_prev7_map(df, city)`)*

---

### Bug 4: `ceil_slot` Inconsistente — Retorna Hora Inválida (24, 0)
**Ficheiro:** `weather.py`
**Localização:** `ceil_slot()`

**Descrição:** Quando `hour=23` e `minute>=30`, `weather.py` retorna `(24, 0)`, que é um índice inválido. O `backtester.py` trata isto corretamente retornando `(23, 30)`.
**Impacto:** Chaves de dicionário inválidas, perda de dados das 23:30 em produção, e paridade quebrada com o backtest.

**Before:**
```python
def ceil_slot(hour: int, minute: int) -> tuple[int, int]:
    if minute < 30:
        return (hour, 30)
    else:
        return (hour + 1, 0)
```

**After:**
```python
def ceil_slot(hour: int, minute: int) -> tuple[int, int]:
    if minute < 30:
        return (hour, 30)
    h = hour + 1
    if h == 24:
        return (23, 30)
    return (h, 0)
```

---

### Bug 5: Stop-Loss PnL Não Guardado no Record
**Ficheiros:** `backtester.py` e `modules/single_entry.py`
**Localização:** Avaliação fim-de-dia em `backtester.py`

**Descrição:** O `backtester.py` assume que `realized_pnl` está no `entry_single.record` após um stop-loss, mas se `SingleEntry.mark_sold_by_stop()` não o guardar explicitamente, o branch falha e é usado o PnL normal incorreto.
**Impacto:** PnL de trades com stop-loss é calculado incorretamente, mascarando perdas reais.

**After (Garantir em `modules/single_entry.py`):**
```python
# No método mark_sold_by_stop da classe SingleEntry:
def mark_sold_by_stop(self, sell_bid: float, realized_pnl: float):
    self.sold_by_stop = True
    if self.record:
        self.record["realized_pnl"] = realized_pnl  # Assegurar que esta linha existe
        self.record["sell_bid"] = sell_bid
```

---

## 🟠 HIGH — Relatórios Incorretos ou Decisões Subóptimas

### Bug 6: Dashboard Mostra Apenas PnL de Stop-Loss, Ignora Wins
**Ficheiro:** `live_bot.py`
**Localização:** Secção "STOP-LOSS CHECK"

**Descrição:** `stats.daily_pnl` só é incrementado quando um stop-loss dispara. Vendas normais ou ganhos não são somados ao PnL diário do dashboard.
**Impacto:** Dashboard mostra PnL diário sempre negativo ou zero, mesmo em dias lucrativos.

**Fix:** Adicionar à lógica de fim de dia ou de fecho de posição normal:
```python
# Quando uma posição é vendida ou expirada com sucesso, adicionar ao daily_pnl:
stats.daily_pnl += realized_or_final_pnl
```

---

### Bug 7: `stop_loss_hit` Usa Investimento em Vez de Perda
**Ficheiro:** `display.py`
**Localização:** `extract_display_data()`

**Descrição:** O cálculo usa `total_invested` para determinar se o stop-loss diário foi atingido. Investir $20 em trades vencedores ativa o stop-loss visual, o que é errado. Deve usar a perda real.
**Impacto:** Bot mostra estado "⛔ STOP-LOSS" indevidamente.

**Before:**
```python
    daily_loss = getattr(daily_stats, "total_invested", 0.0)
    # ...
    stop_loss_hit = daily_loss >= city.max_daily_loss,
```

**After:**
```python
    # Calcular perda real (soma de PnLs negativos)
    trades_list = getattr(daily_stats, "trades", [])
    daily_loss = sum(t.get("realized_pnl", 0) for t in trades_list if t.get("realized_pnl", 0) < 0)
    # Manter fallback para perdas de stop-loss realizadas fora da lista de trades
    if daily_loss == 0:
        daily_loss = abs(getattr(daily_stats, "daily_pnl", 0.0)) if getattr(daily_stats, "daily_pnl", 0.0) < 0 else 0.0
        
    stop_loss_hit = daily_loss >= city.max_daily_loss,
```

---

### Bug 8: Poluição de Estado Global em Multi-Cidade
**Ficheiro:** `predictor.py`
**Localização:** Variáveis globais `_city_config`, `_city_zoneinfo`, `_SEASONAL_PRIOR`

**Descrição:** Em modo multi-cidade, variáveis globais são partilhadas. Embora `set_city()` seja chamado antes de prever, entre os ticks de cidades diferentes, qualquer acesso a essas globais sofre de race condition lógica.
**Impacto:** Prior sazonal da cidade A pode ser usado na previsão da cidade B se a execução falhar a meio.

**Fix:** Tornar o estado dependente do `models` dict passado à função, em vez de globais. Na linha `predict_ensemble`, assegurar que o prior vem sempre do dict:
```python
# Em predictor.py, predict_ensemble:
def predict_ensemble(models, slots_so_far, current, month, doy, zscore_detector=None) -> dict:
    city = models.get("_city", _get_city())
    # Forçar priors do modelo carregado para esta cidade específica
    set_seasonal_prior(models.get("prior_map", {}))
    # ...
```

---

### Bug 9: Calibração Usa Ruído Diferente do Backtest
**Ficheiro:** `calibrate.py`
**Localização:** `simulate_strategy()` e `run_grid_search()`

**Descrição:** A calibração instancia `SimulatedMarket` com `noise_std=0.05`. O backtester usa default `noise_std=0.08`. Parâmetros otimizados para 0.05 falham em 0.08.
**Impacto:** Thresholds e hour_min calibrados não reproduzem o mesmo desempenho no backtest.

**Before:**
```python
                market_sim = (
                    SimulatedMarket(temp_range=city.temp_range, noise_std=0.05, seed=42)
                    if realistic else None
                )
```

**After:**
```python
                market_sim = (
                    SimulatedMarket(temp_range=city.temp_range, noise_std=0.08, seed=42)
                    if realistic else None
                )
```

---

### Bug 10: Patch Global do httpx Afecta Toda a Aplicação
**Ficheiro:** `polymarket_clob.py`
**Localização:** Topo do ficheiro, bloco `try...except ImportError`

**Descrição:** `_httpx.Client.send = _patched_send` substitui o método globalmente, afectando o Flask, Open-Meteo, etc. Pode causar falhas silenciosas noutros clientes HTTP.
**Impacto:** Instabilidade em APIs de terceiros que usem httpx.

**Before:**
```python
    _httpx.Client.send = _patched_send
```

**After:**
```python
    # Aplicar patch apenas uma vez e garantir que não afeta urls fora da polymarket
    if not getattr(_httpx.Client, '_poly_patch_applied', False):
        _orig_send = _httpx.Client.send
        def _patched_send_safe(self, request, **kwargs):
            url_str = str(request.url)
            if 'polymarket.com' in url_str and '/book' in url_str:
                # (lógica de bypass aqui, igual à atual)
                pass
            return _orig_send(self, request, **kwargs)
        _httpx.Client.send = _patched_send_safe
        _httpx.Client._poly_patch_applied = True
```

---

## 🟡 MEDIUM — Confusão ou Problemas Menores

### Bug 11: PnL Zero em Wins com ask >= 1.0
**Ficheiro:** `backtester.py`
**Localização:** `_pnl_per_dollar()`

**Before:**
```python
    if not ask or ask <= 0 or ask >= 1:
        return -1.0 if not won else 0.0
```

**After:**
```python
    if not ask or ask <= 0:
        return -1.0 if not won else 0.0
    if won:
        return (1.0 / ask) - 1.0  # PnL pode ser negativo se ask > 1.0
    return -1.0
```

---

### Bug 12: `premature_s` Compara Apenas Horas
**Ficheiro:** `backtester.py`
**Localização:** Avaliação fim-de-dia

**Before:**
```python
            premature_s = rec["hour"] < peak_h
```

**After:**
```python
            entry_slot_idx = _slot_idx(rec["hour"], rec["slot30"])
            peak_slot_idx = _slot_idx(peak_h, peak_s)
            premature_s = entry_slot_idx < peak_slot_idx
```

---

### Bug 13: Backtester Não Deduplica Slots
**Ficheiro:** `backtester.py`
**Localização:** `load_data()`

**Before:**
```python
    df = raw[
        (raw["hour"] >= city.day_start) & (raw["hour"] <= city.day_end)
    ].dropna(subset=["temp_c"]).sort_values(
        ["date", "hour", "slot30"]
    ).reset_index(drop=True)
```

**After:**
```python
    df = raw[
        (raw["hour"] >= city.day_start) & (raw["hour"] <= city.day_end)
    ].dropna(subset=["temp_c"]).sort_values(
        ["date", "hour", "slot30"]
    ).drop_duplicates(subset=["date", "hour", "slot30"], keep="last"
    ).reset_index(drop=True)
```

---

### Bug 14: `__post_init__` de CityConfig Nunca Normaliza Paths
**Ficheiro:** `cities/config.py`
**Localização:** `CityConfig.__post_init__()`

**Before:**
```python
    def __post_init__(self) -> None:
        model_path = Path(self.model_dir)
        if not model_path.is_absolute() and model_path.parent == Path("."):
            self.model_dir = str(self.city_dir / model_path)
```

**After:**
```python
    def __post_init__(self) -> None:
        model_path = Path(self.model_dir)
        if not model_path.is_absolute():
            self.model_dir = str(self.city_dir / model_path.name)
```

---

### Bug 15: `enrich_bracket` Coloca bid = ask Quando Não Há Orderbook
**Ficheiro:** `polymarket_clob.py`
**Localização:** `ClobClient.enrich_bracket()`

**Before:**
```python
        else:
            b["ask"] = b.get("price")
            b["bid"] = b.get("price")
            b["spread"] = None
```

**After:**
```python
        else:
            estimated_price = b.get("price", 0.5)
            b["ask"] = estimated_price
            b["bid"] = round(estimated_price * 0.90, 4)  # Estimar spread de 10%
            b["spread"] = round(b["ask"] - b["bid"], 4)
```

---

## 🔵 LOW — Qualidade de Código / Edge Cases

### Bug 16: Chave "date" Inexistente em Slots
**Ficheiro:** `predictor.py`
**Localização:** `update_history_max()`
**Fix:** Remover o branch morto `if "date" in first_slot:` e usar sempre a lógica de fallback a partir da timezone da cidade, ou garantir que o `live_bot.py` adiciona a chave `"date"` ao slot.

### Bug 17: Falsos Plateaus com Poucos Pontos
**Ficheiro:** `predictor.py`
**Localização:** `build_features()`
**Before:** `plateau = 1.0 if (np.std(vals[-6:]) < 0.4 and n >= 4) else 0.0`
**After:** `plateau = 1.0 if (n >= 6 and np.std(vals[-6:]) < 0.4) else 0.0`

### Bug 18: Fallback Hardcoded 15.0°C
**Ficheiro:** `backtester.py`
**Localização:** Vários sítios.
**Fix:** Coberto pelo Bug 3 (usar `city.climatology`).

### Bug 19: `_compute_prev7_map` O(n²)
**Ficheiro:** `backtester.py`
**Localização:** `_compute_prev7_map()`
**After:**
```python
def _compute_prev7_map(df: pd.DataFrame, city: CityConfig) -> dict:
    daily_max = df.groupby("date")["temp_c"].max().sort_index()
    dates_list = list(daily_max.index)
    climatology = city.climatology if city.climatology else {i: 15.0 for i in range(1, 13)}
    prev7 = {}
    from collections import deque
    window = deque()
    for d in dates_list:
        while window and (d - window[0]).days > 7:
            window.popleft()
        if not window:
            prev7[d] = climatology.get(d.month, 15.0)
        else:
            prev7[d] = float(np.mean([daily_max[dd] for dd in window]))
        window.append(d)
    return prev7
```

### Bug 20: Anti-Duplicado Ignora Brackets Diferentes
**Ficheiro:** `live_bot.py`
**Localização:** Bloco "Anti-duplicado"
**Fix:** Adicionar verificação de `temp_lo` e `temp_hi` ao buscar bets existentes para só saltar se for exatamente no mesmo bracket.

### Bug 21: Parâmetro Não Usado
**Ficheiro:** `weather.py`
**Localização:** `cloud_from_series()`
**Fix:** Remover `city_name: str` da assinatura.

### Bug 22: Tipo de Data Inconsistente no Walk-Forward
**Ficheiro:** `train.py`
**Localização:** `walk_forward_auc()`
**Fix:** Forçar `dataset["date"] = pd.to_datetime(dataset["date"], errors="coerce")` antes do loop de anos.

### Bug 23: Cliente CLOB Nulo em Paper Mode
**Ficheiro:** `polymarket_clob.py`
**Fix:** Inicializar cliente só de leitura (sem creds de trading) em modo Paper, para poder obter orderbooks reais para simulação.

### Bug 24: `PositionManager.refresh()` Nunca Chamado
**Ficheiro:** `live_bot.py`
**Localização:** Loop principal `while True:`
**Fix:** Chamar `state.clob.positions.refresh(state.clob)` uma vez por hora ou antes de renderizar o dashboard.
```