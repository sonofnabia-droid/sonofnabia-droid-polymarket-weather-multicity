```markdown
# Instruções de Refactoring e Bug Fixing — ZAI Sprint 1

**Contexto:** Este ficheiro contém instruções para corrigir bugs, inconsistências e aplicar melhorias de performance num sistema de trading bot para previsão de temperatura em Munique (Polymarket). 

**Regra Geral:** Não alterar a assinatura das funções públicas (especialmente `predict_ensemble`) nem quebrar a lógica de negócio existente. Aplicar as alterações ficheiro a ficheiro, por ordem de prioridade.

---

## 🔴 PRIORIDADE 1: Bugs Críticos

### 1.1. Falsy check em velocidade do vento (0 km/h tratado como ausente)
**Ficheiro:** `munich_weather.py`
**Função:** `_wu_parse_obs()`

**Problema:** Em Python, `0 or 5` retorna `5`. Quando a velocidade do vento é 0 (calmo), o código assume que o dado é inexistente e atribui 5 mph (18 km/h), distorcendo a feature `foehn_indicator`.

**Alteração:**
Substituir as linhas:
```python
"wind_speed_kmh": float(obs.get("wspd") or 5) * 3.6 if obs.get("wspd") else 5.0,
"wind_gust_kmh":  float(obs.get("gust") or 8) * 3.6 if obs.get("gust") else 8.0,
```
Por:
```python
_wspd = obs.get("wspd")
_gust = obs.get("gust")
"wind_speed_kmh": float(_wspd) * 3.6 if _wspd is not None else 5.0,
"wind_gust_kmh":  float(_gust) * 3.6 if _gust is not None else 8.0,
```

### 1.2. Throttling: Fetch de APIs chamado múltiplas vezes por minuto
**Ficheiro:** `munich_live_bot.py`
**Localização:** Dentro do `while True` loop principal.

**Problema:** As condições `now.minute % 30 == 0` e `now.minute % 10 == 0` são verdadeiras durante 60 e 60 segundos respetivamente, causando dezenas de chamadas API idênticas (rate limit risk).

**Alteração:**
1. Adicionar variáveis de estado antes do loop:
```python
_last_forecast_min = -1
_last_market_min = -1
```
2. Substituir os blocos de fetch no loop:
```python
# Forecasts (cada 30min)
if now.minute != _last_forecast_min and now.minute % 30 == 0:
    _last_forecast_min = now.minute
    wu_forecast = fetch_wu_forecast_max(wu_key, wu_sess)
    om_forecast = fetch_om_forecast_max(om_sess)
    forecast_agreement = forecasts_agree(wu_forecast, om_forecast)

# Mercado (cada 10min)
if now.minute != _last_market_min and (now.minute % 10 == 0 or not market):
    _last_market_min = now.minute
    market = fetcher.fetch_market(today)
    if market and clob:
        market["brackets"] = [clob.enrich_bracket(b) for b in market["brackets"]]
    # Fix 1.2.b: Atualizar open_orders aqui também
    if executor and trading_mode == TradingMode.REAL:
        open_orders = executor.get_open_orders()
```

### 1.3. Tracking de trades e stats diárias/sessão está morto
**Ficheiro:** `munich_live_bot.py`

**Problema:** `daily_stats.trades` nunca recebe append; `session_stats.wins/losses/pnl` nunca são atualizados. O log de shutdown e o JSON diário mentem.

**Alteração:**
1. No bloco `if trading_mode == TradingMode.PAPER:`, logo após `bets.append(bet)`:
```python
daily_stats.trades.append(bet_record)
session_stats.total_trades += 1
```
2. No bloco `else: # REAL`, dentro de `if result["success"]:`, logo após `bets.append(bet)`:
```python
daily_stats.trades.append(bet_record)
session_stats.total_trades += 1
```

---

## 🟡 PRIORIDADE 2: Bugs Moderados e Inconsistências

### 2.1. Comentários invertidos no Backtester
**Ficheiro:** `munich_backtester.py`
**Localização:** Dataclasses `Trade` e `DailyResult`

**Problema:** A lógica `lag >= 0` significa que a entrada aconteceu *depois* do pico, logo o pico ocorreu *antes*. Os comentários dizem o oposto.

**Alteração:**
```python
# Em Trade e DailyResult, trocar:
correct:   bool = False   # pico ocorreu ANTES da entrada (entrada correcta)
premature: bool = False   # pico ocorreu DEPOIS da entrada (entrada prematura)
```

### 2.2. Remover duplicação de ZScoreStreaming
**Ficheiro:** `munich_backtester.py`

**Problema:** `ZScoreStreaming` é uma cópia exata de `StreamingPeakDetector` em `munich_model.py`.

**Alteração:**
1. Apagar a classe `ZScoreStreaming` inteira de `munich_backtester.py`.
2. Alterar o import no topo do ficheiro de:
```python
from munich_model import (load_models, predict_ensemble, StreamingPeakDetector, ...)
```
para usar diretamente:
```python
from munich_model import StreamingPeakDetector
# E na função run():
zscore = StreamingPeakDetector() # era ZScoreStreaming()
```

### 2.3. SingleEntry reason enganoso quando já comprou
**Ficheiro:** `munich_phased_entry.py`
**Função:** `SingleEntry.evaluate()`

**Problema:** Se `self.bought == True`, devolve reason a dizer que `p < threshold`, o que é mentira.

**Alteração:**
Substituir o corpo de `evaluate` por:
```python
def evaluate(self, p_ensemble: float, hour: int, market: dict | None,
             running_max: float, forecast_agreement: dict | None) -> list[dict]:
    if self.bought:
        return [{
            "parcel_idx": 0,
            "size_usdc":  0,
            "reason":     "SINGLE: já comprado nesta sessão",
            "model_ok":   True,
            "market_ok":  None,
        }]
        
    if p_ensemble >= self.threshold:
        return [{
            "parcel_idx": 0,
            "size_usdc":  self.parcel_size,
            "reason":     (f"SINGLE: p={p_ensemble*100:.0f}% >= "
                           f"{self.threshold*100:.0f}%"),
            "model_ok":   True,
            "market_ok":  True,
        }]
        
    return [{
        "parcel_idx": 0,
        "size_usdc":  0,
        "reason":     (f"SINGLE: p={p_ensemble*100:.0f}% < "
                       f"{self.threshold*100:.0f}%"),
        "model_ok":   False,
        "market_ok":  None,
    }]
```

### 2.4. Pesos hardcoded na importância das features
**Ficheiro:** `munich_train.py`
**Função:** `save_models()`

**Problema:** Usa `0.5 * lgb_imp_pct + 0.3 * xgb_imp_pct` em vez dos pesos reais.

**Alteração:**
Substituir:
```python
ens_imp = 0.5 * lgb_imp_pct + 0.3 * xgb_imp_pct
```
Por:
```python
w_lgb, w_xgb = ENSEMBLE_WEIGHTS["lgbm"], ENSEMBLE_WEIGHTS["xgb"]
ens_imp = w_lgb * lgb_imp_pct + w_xgb * xgb_imp_pct
```

### 2.5. Deduplicar `ceil_slot` e `normalize_datetime_ceiling`
**Ficheiros:** `munich_backtester.py`, `munich_train.py`

**Problema:** Funções copiadas de `munich_config.py`.

**Alteração:**
Em ambos os ficheiros, apagar as definições locais de `ceil_slot` e `normalize_datetime_ceiling` e adicionar aos imports:
```python
from munich_config import ceil_slot
# (Para normalize_datetime_ceiling, se não existir em config, mover para config ou criar munich_utils.py)
```
*Nota: `normalize_datetime_ceiling` usa `BERLIN_TZ` e `timedelta`. Se a moveres para `munich_config.py`, importa lá os tipos necessários.*

---

## 🟢 PRIORIDADE 3: Melhorias de Performance e Robustez

### 3.1. Otimizar `predict_ensemble` (Remover DataFrame por predição)
**Ficheiro:** `munich_model.py`
**Função:** `predict_ensemble()`

**Problema:** `pd.DataFrame([row])[avail].fillna(0)` é extremamente lento quando chamado milhares de vezes no backtest.

**Alteração:**
Substituir:
```python
avail = [f for f in feat_cols if f in row]
X = pd.DataFrame([row])[avail].fillna(0)
```
Por (construção direta de array numpy):
```python
import numpy as np
# ... dentro de predict_ensemble ...
avail = [f for f in feat_cols if f in row]
X_array = np.array([[row.get(f, 0.0) for f in avail]], dtype=np.float32)

# E nas predições:
p_lgbm = float(models["model_lgb"].predict_proba(X_array)[0, 1])
# e
p_xgb = float(models["model_xgb"].predict_proba(X_array)[0, 1])
```

### 3.2. Aviso de Features Ausentes Silenciosas
**Ficheiro:** `munich_model.py`
**Função:** `predict_ensemble()`

**Problema:** Se uma feature V2 faltar no dict `current`, desaparece do vector sem alerta.

**Alteração:**
Adicionar verificação após `avail`:
```python
avail = [f for f in feat_cols if f in row]
if len(avail) < len(feat_cols):
    missing = [f for f in feat_cols if f not in row]
    import warnings
    warnings.warn(f"Features ausentes (a usar 0): {missing}", RuntimeWarning)
```

### 3.3. Remover parâmetro morto em `cloud_from_series`
**Ficheiro:** `munich_weather.py`
**Função:** `cloud_from_series()`

**Problema:** O primeiro argumento `series_today` nunca é usado.

**Alteração:**
1. Mudar a assinatura para `def cloud_from_series(rows_cache: list) -> dict[int, int]:`
2. Atualizar a chamada em `munich_live_bot.py` de:
   `cloud_by_hour = cloud_from_series(series_today, rows_cache)`
   para:
   `cloud_by_hour = cloud_from_series(rows_cache)`

### 3.4. Mover `smart_sleep` para quebrar dependência circular
**Ficheiros:** `munich_config.py`, `munich_live_bot.py`

**Problema:** `munich_config` faz `from munich_weather import fetch_wu_latest`, misturando constantes com I/O.

**Alteração:**
1. Cortar a função `smart_sleep` de `munich_config.py`.
2. Colar em `munich_live_bot.py`.
3. Remover o import local de `munich_weather` dentro da função (já está importado no topo do live bot).
4. Atualizar os imports de `munich_config` no `munich_live_bot.py` para remover `smart_sleep`.

### 3.5. Vetorizar Walk-Forward Validation
**Ficheiro:** `munich_train.py`
**Função:** `walk_forward_train()`

**Problema:** `dataset["date"].apply(lambda d: d.year < test_year)` executado em cada fold.

**Alteração:**
Pré-computar a coluna ano antes do loop:
```python
years = sorted(set(d.year for d in dataset["date"].unique()))
dataset["_year"] = dataset["date"].apply(lambda d: d.year) # Pré-computar

for test_year in years:
    train_df = dataset[dataset["_year"] < test_year]
    test_df  = dataset[dataset["_year"] == test_year]
    # ... resto igual ...

"---------------------------------------------------------------------------"
# Instruções de Refactoring e Bug Fixing — ZAI Sprint 2 (Deep Audit)

**Contexto:** Segunda ronda de auditoria. Foco em inconsistências comportamentais entre backtester e live bot, data leakage no pipeline de treino, edge cases que podem causar perdas financeiras e resultados irreais.

**Regra Geral:** Não alterar a assinatura das funções públicas (especialmente `predict_ensemble`) nem quebrar a lógica de negócio existente. Aplicar as alterações ficheiro a ficheiro, por ordem de prioridade.

---

## 🔴 PRIORIDADE 1: Bugs Críticos de Lógica e Financeiros

### 1.1. Backtester compra MÚLTIPLAS parcelas por slot, Live Bot compra APENAS UMA
**Ficheiro:** `munich_backtester.py`
**Função:** `run()`

**Problema:** O backtester processa TODAS as actions retornadas por `evaluate()`, permitindo comprar P1+P2+P3 no mesmo slot. O live bot tem um `break` após a primeira action, comprando apenas 1 parcela por tick. O backtester é sistematicamente optimista — mostra resultados que o bot nunca consegue replicar em produção.

**Alteração:**
Substituir o loop sobre actions:
```python
# ANTES (processa TODAS as actions):
for act in actions:
    if act["size_usdc"] > 0:
        ...
        entry.mark_bought(pidx, ...)

# DEPOIS (processa apenas a PRIMEIRA, como o live bot):
for act in actions:
    if act["size_usdc"] > 0:
        pidx = act["parcel_idx"]

        if pidx == 1:
            best = max(brackets, key=lambda b: b["ask"])
        else:
            rmax_int = int(round(running_max))
            best = next(
                (b for b in brackets
                 if b["temp_lo"] <= rmax_int <= b["temp_hi"]),
                max(brackets, key=lambda b: b["ask"])
            )

        entry.mark_bought(pidx, {
            "hour": h, "slot30": s,
            "ask": best["ask"],
            "size_usdc": act["size_usdc"],
            "bracket_label": best["label"],
        })
    break  # <-- ADICIONAR: apenas 1 parcela por slot, como no live bot
```

### 1.2. Conversão de vento mph→km/h potencialmente DUPLA no WU
**Ficheiro:** `munich_weather.py`
**Função:** `_wu_parse_obs()`

**Problema:** O endpoint WU é chamado com `units=m` (métrico). Se a API já retornar km/h, a multiplicação `* 3.6` dá valores 3.6× superiores ao real (ex: 5 km/h reportado como 18 km/h). Isto corrompe `foehn_indicator` e `wind_speed_kmh`.

**Alteração:** Aplicar a validação de nulo e remover a conversão cega (assumindo que `units=m` já devolve km/h).
```python
# Substituir as linhas:
"wind_speed_kmh": float(obs.get("wspd") or 5) * 3.6 if obs.get("wspd") else 5.0,
"wind_gust_kmh":  float(obs.get("gust") or 8) * 3.6 if obs.get("gust") else 8.0,

# Por:
_wspd_raw = obs.get("wspd")
_gust_raw = obs.get("gust")
_wspd_val = float(_wspd_raw) if _wspd_raw is not None else None
_gust_val = float(_gust_raw) if _gust_raw is not None else None

# NOTA: WU com units=m retorna km/h. NÃO multiplicar por 3.6.
"wind_speed_kmh": _wspd_val if _wspd_val is not None else 5.0,
"wind_gust_kmh":  _gust_val if _gust_val is not None else 8.0,
```
*(Atenção: Verificar empiricamente se o endpoint EDDM com `units=m` devolve de facto km/h. Se confirmar que vem mph, manter `* 3.6` mas aplicar a validação `is not None`)*.

### 1.3. Data Leakage: `seasonal_peak_prior` usa dados futuros no Walk-Forward
**Ficheiro:** `munich_train.py`
**Função:** `build_dataset()`, `walk_forward_train()`

**Problema:** O `prior_map` é calculado sobre TODO o dataset (incluindo anos futuros ao fold de teste). A feature `seasonal_peak_prior` para 2018 foi calculada com dados de 2020-2024, inflando o AUC artificialmente.

**Alteração:**
1. Em `build_dataset()`, deixar de retornar o `prior_map` calculado sobre tudo. Retornar apenas a "estrutura" vazia ou não incluir o prior na build inicial.
2. Mover o cálculo do prior para dentro do loop de walk-forward, usando apenas dados do fold de treino.
```python
# Em walk_forward_train(), ANTES do loop de folds:
dataset["_year"] = dataset["date"].apply(lambda d: d.year)

for test_year in years:
    train_df = dataset[dataset["_year"] < test_year]
    test_df  = dataset[dataset["_year"] == test_year]
    
    # Recalcular prior_map APENAS com train_df
    slot_counts = {}
    slot_peak = {}
    for d, day_df in train_df.groupby("date"):
        peak_idx = day_df["temp_c"].idxmax()
        peak_h = int(day_df.loc[peak_idx, "hour"])
        peak_s = int(day_df.loc[peak_idx, "slot30"])
        for _, row in day_df.iterrows():
            h, s, m = int(row["hour"]), int(row["slot30"]), int(row["month"])
            key = (m, h, s)
            slot_counts[key] = slot_counts.get(key, 0) + 1
            if h > peak_h or (h == peak_h and s >= peak_s):
                slot_peak[key] = slot_peak.get(key, 0) + 1
                
    prior_map_fold = {k: round(slot_peak.get(k, 0) / total, 4) for k, total in slot_counts.items()}
    
    # Mapear o prior ao test_df para este fold
    test_df = test_df.copy()
    test_df["seasonal_peak_prior"] = test_df.apply(
        lambda r: prior_map_fold.get((int(r["month"]), int(r["hour"]), int(r["slot30"])), 0.5), axis=1
    )
    # ... continuam os fits e predicts ...
```

### 1.4. Daily Loss NÃO é resetado no novo dia
**Ficheiro:** `munich_live_bot.py`
**Função:** `_handle_new_day()`

**Problema:** O `_handle_new_day()` reseta `daily_stats`, `entry`, `zscore`, mas NÃO reseta o daily loss do `ClobClient`. Se o bot atingir o stop-loss num dia, o contador persiste no dia seguinte, bloqueando ordens indevidamente.

**Alteração:**
1. Adicionar em `_handle_new_day()`:
```python
# Reset do daily loss do CLOB para o novo dia
if clob:
    clob.reset_daily_loss()
```
2. Adicionar o método em `polymarket_clob.py` (classe `ClobClient`):
```python
def reset_daily_loss(self):
    self._daily_loss = 0.0
```

---

## 🟡 PRIORIDADE 2: Bugs Moderados e Inconsistências

### 2.1. `compute_prev7` fallback inconsistente: 15.0 vs daily_max
**Ficheiro:** `munich_backtester.py`
**Função:** `_compute_prev7_map()`

**Problema:** No backtester, o 1º dia usa `daily_max[d]` (a máxima do próprio dia — data leakage!). No modelo live, usa fallback `15.0`. Isto gera features diferentes entre backtest e produção.

**Alteração:**
```python
def _compute_prev7_map(df: pd.DataFrame) -> dict:
    daily_max = df.groupby("date")["temp_c"].max().sort_index()
    dates_list = list(daily_max.index)
    prev7: dict = {}
    for i, d in enumerate(dates_list):
        if i == 0:
            prev7[d] = 15.0  # Mesmo fallback que munich_model.compute_prev7
        else:
            window = daily_max[dates_list[max(0, i - 7):i]]
            prev7[d] = float(window.mean()) if len(window) else 15.0
    return prev7
```

### 2.2. P2 pode comprar bracket "or lower" com quase zero upside
**Ficheiro:** `munich_live_bot.py`
**Localização:** Loop principal, bloco de seleção de bracket.

**Problema:** Quando `pidx == 1`, seleciona o bracket com MAIOR ask. Se esse bracket for "X°C or lower" (ask ~96¢), o lucro máximo é ~4¢ por share. P1 filtra "or lower", mas P2 não.

**Alteração:**
```python
if pidx == 1 and market:
    # Filtrar brackets "or lower" — quase sem upside
    valid_brackets = [b for b in market["brackets"] 
                      if b["temp_lo"] > -99]  # exclui "or lower"
    if valid_brackets:
        target_bracket = max(valid_brackets,
                             key=lambda b: b.get("ask") or b.get("price") or 0)
    else:
        target_bracket = PolymarketFetcher.find_bracket(market, rmax)
```

### 2.3. `init_history_max` usa path hardcoded em vez de LOG_DIR
**Ficheiro:** `munich_model.py`

**Problema:** `Path("live_history_max.json")` usa o diretório atual, enquanto todo o resto usa `LOG_DIR`.

**Alteração:**
```python
from munich_config import LOG_DIR

def init_history_max() -> dict:
    path = LOG_DIR / "live_history_max.json"
    if path.exists():
        try:
            return {
                date.fromisoformat(k): float(v)
                for k, v in json.loads(path.read_text()).items()
            }
        except Exception:
            pass
    return {}

def save_history_max(history_max: dict) -> None:
    LOG_DIR.mkdir(exist_ok=True)
    path = LOG_DIR / "live_history_max.json"
    data = {d.isoformat(): v for d, v in history_max.items()}
    path.write_text(json.dumps(data, indent=2))
```

### 2.4. `save_history_max` chamado em CADA tick — I/O de disco excessivo
**Ficheiro:** `munich_model.py`
**Função:** `update_history_max()`

**Problema:** No live bot, é chamado a cada iteração (~60s), gerando I/O desnecessário.

**Alteração:**
```python
_last_save_time = 0.0

def update_history_max(history_max: dict, slots_so_far: list[dict]) -> None:
    global _last_save_time
    if not slots_so_far:
        return
    today = berlin_date()
    max_temp = max(s["temp_c"] for s in slots_so_far)
    old_max = history_max.get(today)
    history_max[today] = max_temp
    
    # Só guardar em disco a cada 5 minutos ou se a máxima subiu
    import time
    now = time.time()
    if now - _last_save_time >= 300 or old_max is None or max_temp > old_max:
        save_history_max(history_max)
        _last_save_time = now
```

### 2.5. Posições nunca são resolvidas — status OPEN perpetuamente
**Ficheiro:** `munich_live_bot.py`

**Problema:** Não existe código que verifique se as posições abertas de dias anteriores foram resolvidas. O display mostra posições como "ABERTA" indefinidamente.

**Alteração:**
Adicionar verificação periódica no loop principal (após fetch de mercado):
```python
if clob and trading_mode == TradingMode.REAL:
    clob.positions.resolve_closed_positions(today)
```
E implementar `resolve_closed_positions(date)` no `PositionManager` (polymarket_clob.py) que verifica a temperatura real contra o bracket de cada posição aberta de dias anteriores, marcando como WON/LOST.

### 2.6. Falsy check em pressão atmosférica e direção do vento
**Ficheiro:** `munich_weather.py`
**Função:** `_wu_parse_obs()`

**Problema:** `0 or 1013` retorna 1013. `None or 0` retorna 0 (indica Norte falso).

**Alteração:**
```python
_press = obs.get("pressure")
"pressure_hpa": float(_press) if _press is not None else 1013.0,

_wdir = obs.get("wdir")
"wind_dir_deg": float(_wdir) if _wdir is not None else -1.0,  # -1 = sem direção
```
E ajustar em `munich_model.py`, função `build_features()`:
```python
wdir = float(current.get("wind_dir_deg", -1.0))

if wdir < 0:  # sem direção (vento calmo)
    wind_south_proxy = 0.0
    foehn_south = 0.0
else:
    wind_south_proxy = (1.0 - abs(wdir - 180) / 45.0) if 135 <= wdir <= 225 else 0.0
    foehn_south = 1.0 if 135 <= wdir <= 225 else 0.0
```

---

## 🟢 PRIORIDADE 3: Melhorias de Robustez e Correcção Semântica

### 3.1. `compute_doy_threshold` optimiza threshold para o PRIOR, não para o MODELO
**Ficheiro:** `munich_train.py`

**Problema:** O threshold DOY é calculado optimizando F1 sobre `seasonal_peak_prior`, mas aplicado ao `p_ensemble`. A distribuição é muito diferente.

**Alteração:** Passar as predições do walk-forward acumuladas em vez de usar o prior:
```python
def compute_doy_threshold(dataset: pd.DataFrame, 
                          wf_preds: list[float], 
                          wf_labels: list[int], 
                          degree: int = 5) -> np.ndarray:
    dataset_copy = dataset.copy()
    dataset_copy["_pred"] = wf_preds
    # (alinhamento assume que wf_preds corresponde ao dataset filtrado usado no WF)
    
    doy_thresholds = {}
    for doy in range(1, 366):
        sub = dataset_copy[dataset_copy["doy"] == doy]
        if len(sub) < 20:
            continue
        preds = sub["_pred"].values
        labels = sub["label"].values
        best_thr, best_f1 = 0.5, 0.0
        for thr in np.arange(0.3, 0.95, 0.05):
            f1 = f1_score(labels, (preds >= thr).astype(int), zero_division=0)
            if f1 > best_f1:
                best_f1, best_thr = f1, thr
        doy_thresholds[doy] = best_thr

    doys = np.array(list(doy_thresholds.keys()))
    thrs = np.array(list(doy_thresholds.values()))
    return np.polyfit((doys - 183) / 183, thrs, degree)
```

### 3.2. Backtester não simula P&L — impossível avaliar rentabilidade
**Ficheiro:** `munich_backtester.py`

**Problema:** Classifica dias como correct/premature/missed mas NÃO calcula lucro/perda.

**Alteração:**
1. Em `DailyResult`, adicionar: `pnl_usd: float = 0.0`
2. Em `BacktestStats`, adicionar: `total_pnl: float = 0.0`, `roi_pct: float = 0.0`
3. Na função `run()`, ao calcular os resultados do dia:
```python
daily_pnl = 0.0
for i in range(3):
    if entry.parcel_bought[i] and entry.parcel_records[i] is not None:
        rec = entry.parcel_records[i]
        ask = rec["ask"]
        invested = rec["size_usdc"]
        shares = invested / ask if ask > 0 else 0
        
        if correct:  # ganhou
            daily_pnl += shares * (1.0 - ask)
        elif premature:  # perdeu
            daily_pnl -= invested
            
results[-1]["pnl_usd"] = round(daily_pnl, 2)
```
4. Em `compute_metrics()`, agregar: `stats.total_pnl = round(results["pnl_usd"].sum(), 2)`

### 3.3. PhasedEntry P2 e P3 não geram action quando modelo não OK
**Ficheiro:** `munich_phased_entry.py`
**Função:** `evaluate()`

**Problema:** P2/P3 não retornam action bloqueada quando `p < threshold`, dificultando o debug e display.

**Alteração:** Adicionar reasons explícitos para P2 e P3:
```python
# P2 — adicionar caso model_ok = False:
if not model_ok:
    actions.append({
        "parcel_idx": 1,
        "size_usdc":  0,
        "reason":     (f"P2 BLOQUEADA: p={p_ensemble*100:.0f}% < "
                       f"{self.thr_p2*100:.0f}%"),
        "model_ok":   False,
        "market_ok":  None,
    })

# P3 — adicionar caso p < thr_p3:
if not self.parcel_bought[2]:
    if p_ensemble >= self.thr_p3:
        actions.append(buy_action_p3)
    else:
        actions.append({
            "parcel_idx": 2,
            "size_usdc":  0,
            "reason":     (f"P3 BLOQUEADA: p={p_ensemble*100:.0f}% < "
                           f"{self.thr_p3*100:.0f}%"),
            "model_ok":   False,
            "market_ok":  None,
        })
```

### 3.4. `_handle_new_day` não reseta variáveis de throttling
**Ficheiro:** `munich_live_bot.py`

**Problema:** Após o fix 1.2 do Sprint 1, `_last_forecast_min` e `_last_market_min` não são resetados no novo dia, podendo saltar o 1º fetch.

**Alteração:** Em `_handle_new_day()`:
```python
nonlocal _last_forecast_min, _last_market_min
# ...
_last_forecast_min = -1  # Reset
_last_market_min = -1    # Reset
```

### 3.5. `normalize_datetime_ceiling` em loop Python — extremamente lento
**Ficheiro:** `munich_backtester.py`, função `load_data()`

**Problema:** Iterar sobre timestamps com loop Python + `astimezone()` é orders of magnitude mais lento que operações vectorizadas pandas.

**Alteração:** Substituir o loop `for ts in raw["timestamp_utc"]:` por:
```python
raw["datetime_local"] = raw["timestamp_utc"].dt.tz_convert(BERLIN_TZ)

raw["hour_raw"] = raw["datetime_local"].dt.hour
raw["minute_raw"] = raw["datetime_local"].dt.minute
raw["hour"] = np.where(raw["minute_raw"] < 30, raw["hour_raw"], raw["hour_raw"] + 1)
raw["slot30"] = np.where(raw["minute_raw"] < 30, 30, 0)

mask_24 = raw["hour"] == 24
raw.loc[mask_24, "hour"] = 0
raw.loc[mask_24, "datetime_local"] += timedelta(days=1)

raw["date"] = raw["datetime_local"].dt.date
raw["month"] = raw["datetime_local"].dt.month
raw["doy"] = raw["datetime_local"].dt.dayofyear
```
Aplicar o mesmo fix em `munich_train.py`, função `load_csv()`.

### 3.6. `log_tick` não protege contra crash por I/O
**Ficheiro:** `munich_display.py`

**Alteração:** Envolver em try/except:
```python
def log_tick(...) -> None:
    row = { ... }
    try:
        write_header = not path.exists()
        with open(path, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(row.keys()))
            if write_header:
                writer.writeheader()
            writer.writerow(row)
    except OSError as e:
        print(f"  {C['yellow']}⚠ log_tick falhou: {e}{R}")
```

### 3.7. `fetch_wu_day_eddm` não faz retry
**Ficheiro:** `munich_weather.py`

**Alteração:** Adicionar retentativa com backoff:
```python
def fetch_wu_day_eddm(day: date, api_key: str,
                      session: requests.Session,
                      max_retries: int = 2) -> list[dict]:
    for attempt in range(max_retries + 1):
        try:
            r = session.get(WU_EDDM_URL, params={
                "apiKey": api_key, "units": "m",
                "startDate": day.strftime("%Y%m%d"),
            }, timeout=20)
            r.raise_for_status()
            obs = r.json().get("observations", [])
            return _wu_parse_obs(obs) if obs else []
        except Exception:
            if attempt < max_retries:
                import time
                time.sleep(2 ** attempt)
            continue
    return []
```

### 3.8. `POLY_MAX_DAILY_LOSS` pode crashar com env var inválida
**Ficheiro:** `munich_config.py`

**Alteração:**
```python
try:
    POLY_MAX_DAILY_LOSS = float(os.environ.get("POLY_MAX_DAILY_LOSS", "50"))
except ValueError:
    POLY_MAX_DAILY_LOSS = 50.0
```

# Instruções de Refactoring e Bug Fixing — ZAI Sprint 3 (Logic & Trading Audit)

**Contexto:** Terceira ronda de auditoria. Foco em falhas lógicas de trading que causam perdas financeiras directas, edge cases meteorológicos e inconsistências semânticas entre o backtester e a realidade do mercado Polymarket.

**Regra Geral:** Não alterar a assinatura das funções públicas. Aplicar as alterações por ordem de prioridade.

---

## 🔴 PRIORIDADE 1: Bugs Críticos de Trading e Lógica

### 1.1. P1 ("Value Early") compra o bracket do running_max, que VAI PERDER se a temp subir
**Ficheiros:** `munich_live_bot.py`, `munich_backtester.py`

**Problema:** A lógica de P1 entra cedo (10h-12h) quando o modelo tem 30%-65% de confiança. Nessa altura, selecciona o bracket com MAIOR ask (o bracket do `running_max` actual). O problema: se a temperatura subir mais 2°C (comum pela tarde), o bracket do `running_max` anterior RESOLVE COMO "NO". O P1 está estruturalmente desenhado para comprar brackets que vão perder.

**Fix em `munich_live_bot.py`:**
P1 deve comprar um bracket de "segurança" acima do running_max actual, baseado no forecast, ou comprar brackets "or higher".
```python
# Substituir a lógica de selecção P1:
if pidx == 0 and market:
    rmax_int = int(round(running_max))
    wu_max = wu_forecast.get("temp_max") if wu_forecast else rmax_int + 2
    
    # Estratégia: comprar o bracket do consensus_max, não do running_max
    # Se o forecast for 28°C, comprar o bracket dos 28°C, não dos 24°C (running_max atual)
    target_temp = max(rmax_int, wu_max)
    target_bracket = PolymarketFetcher.find_bracket(market, target_temp)
    
    # Fallback: se não encontrar, tentar "or higher"
    if not target_bracket or target_bracket.get("temp_hi", 0) < target_temp:
        target_bracket = next(
            (b for b in market["brackets"] if b["temp_hi"] >= 99 and b["temp_lo"] <= target_temp),
            max(market["brackets"], key=lambda b: b.get("ask") or 0)
        )
```

**Fix em `munich_backtester.py`:**
Aplicar a mesma lógica de selecção de bracket para P1. O `SimulatedMarket` tem de reflectir que P1 aponta ao forecast, não ao running_max.

### 1.2. Backtester `idxmax()` encontra o PRIMEIRO máximo — marca entradas correctas como "prematuras"
**Ficheiro:** `munich_backtester.py`
**Função:** `run()`

**Problema:** `day_df["temp_c"].idxmax()` retorna o índice da PRIMEIRA ocorrência da temperatura máxima. Se a temp atinge 25°C às 12h, baixa para 24°C, e volta a 25°C às 15h, o `peak_idx` aponta para as 12h. Qualquer entrada às 14h (mesmo que antes do verdadeiro pico da tarde) é marcada como "prematura" (lag negativo). Isto infla artificialmente a taxa de prematuros no backtest.

**Fix:**
```python
# ANTES:
peak_idx = day_df["temp_c"].idxmax()

# DEPOIS (encontrar a ÚLTIMA ocorrência do máximo):
peak_temp = day_df["temp_c"].max()
peak_idx = day_df[day_df["temp_c"] == peak_temp].index[-1]
```

### 1.3. `prev7` Out-Of-Distribution na primeira execução do Live Bot
**Ficheiro:** `munich_model.py`
**Função:** `compute_prev7()`

**Problema:** Se `live_history_max.json` não existe (primeira execução), `prev_7d_avg_max = 15.0`. No verão (máximas de 30°C), `temp_vs_climatology = 15.0`, um outlier massivo. O LightGBM extrapola mal fora da distribuição de treino, causando predições aleatórias nas primeiras horas/dias.

**Fix:** Fallback climatológico baseado no mês em vez de hardcoded 15.0.
```python
# Dados climatológicos aproximados de Munique (média de máximas)
_CLIMATOLOGY_BY_MONTH = {
    1: 3.0, 2: 5.0, 3: 10.0, 4: 15.0, 5: 20.0, 6: 23.0,
    7: 25.0, 8: 25.0, 9: 20.0, 10: 14.0, 11: 7.0, 12: 4.0
}

def compute_prev7(history: dict, d: date) -> float:
    if not history:
        # Fallback climatógico em vez de 15.0 fixo
        return _CLIMATOLOGY_BY_MONTH.get(d.month, 15.0)
    
    days = sorted(history.keys())
    if d not in days:
        recent = days[-7:]
        if recent:
            return float(np.mean([history[x] for x in recent]))
        return _CLIMATOLOGY_BY_MONTH.get(d.month, 15.0)
    
    idx = days.index(d)
    if idx == 0:
        return float(history[d])
    
    window = days[max(0, idx - 7):idx]
    vals = [history[x] for x in window]
    return float(np.mean(vals)) if vals else _CLIMATOLOGY_BY_MONTH.get(d.month, 15.0)
```

### 1.4. `find_bracket` arredonda `rmax` para o bracket errado
**Ficheiro:** `munich_live_bot.py` (classe `PolymarketFetcher`)

**Problema:** `tr = round(temp)`. Se `rmax = 24.6`, arredonda para 25. O bot compra o bracket "25°C". Mas se a temp não subir mais, o mercado resolve para 24°C, e a aposta PERDE. O Polymarket geralmente resolve baseado no truncamento ou no valor exacto da estação EDDM.

**Fix:** Usar o inteiro mais baixo (chão) para brackets exactos, a menos que o forecast confirme que vai subir.
```python
@staticmethod
def find_bracket(market: dict, temp: float, forecast_max: float = None) -> Optional[dict]:
    if not market:
        return None
    
    # Se temos forecast e é maior, apontar ao forecast
    if forecast_max is not None:
        target = int(round(forecast_max))
    else:
        target = int(np.floor(temp))  # Arredondar para BAIXO (pessimista)
        
    for b in market["brackets"]:
        lo, hi = b["temp_lo"], b["temp_hi"]
        if lo == hi and target == round(lo): return b
        if hi >= 99 and target >= lo: return b
        if lo <= -99 and target <= hi: return b
        if lo <= temp <= hi: return b
        
    # Fallback
    return min(market["brackets"],
               key=lambda b: abs(target - (
                   b["temp_lo"] if b["temp_hi"] >= 99 else
                   b["temp_hi"] if b["temp_lo"] <= -99 else
                   (b["temp_lo"] + b["temp_hi"]) / 2
               )))
```

---

## 🟡 PRIORIDADE 2: Bugs Moderados e Inconsistências

### 2.1. Telegram `alert_peak_detected` disparado na P1 (Value Early)
**Ficheiro:** `munich_live_bot.py`

**Problema:** P1 dispara quando o pico AINDA NÃO ocorreu (30-65% probabilidade). Mas o código envia `tg.alert_peak_detected()`, o que é enganoso para o utilizador.

**Fix:**
```python
if bet:
    if entry.n_parcels_bought == 1 and mode == "phased":
        # P1 é "Value Early", não pico detectado
        tg.alert_order_placed(bet, clob_mode_str)
    elif entry.n_parcels_bought == 1 and mode == "single":
        # Single é pico detectado
        tg.alert_peak_detected(
            p_ensemble=p, rmax=rmax, rmax_time=rmax_time_str,
            bracket=target_bracket, ensemble_result=ensemble_result, market=market)
    else:
        tg.alert_order_placed(bet, clob_mode_str)
```

### 2.2. Backtester `fc_agreement = {"valid": True}` — Otimismo irrealista
**Ficheiro:** `munich_backtester.py`

**Problema:** O backtester hardcodes `fc_agreement = {"valid": True}`. Isto faz com que P1 seja desbloqueada 100% das vezes, mas no Live Bot P1 é bloqueada sempre que WU e OM discordam ou estão em falta. O backtest superestima a taxa de trades P1.

**Fix:** Simular um acordo probabilístico baseado no mês (inverno = mais concordância, verão = menos) ou usar dados reais de forecast se disponíveis no CSV.
```python
# Abordagem simples: concordância sazonal
_FC_AGREE_PROB = {
    "winter": 0.95, "spring": 0.80, "summer": 0.70, "autumn": 0.85
}

# No loop do dia, em run():
season = next((s for s, ms in SEASONS.items() if month in ms), "spring")
fc_valid = np.random.random() < _FC_AGREE_PROB.get(season, 0.80)
fc_agreement = {"valid": fc_valid}
```

### 2.3. `SimulatedMarket` gera preços irreais — Edge inflacionado
**Ficheiro:** `munich_backtester.py`

**Problema:** A fórmula `ask = min(0.92, p_ensemble * 0.75 + 0.18)` assume que o mercado segue perfeitamente o modelo. Na realidade, o mercado tem spread, liquidez zero em brackets distantes, e ineficiências. O backtester pensa que consegue comprar a qualquer momento.

**Fix:** Adicionar restrições de liquidez e spread mínimo.
```python
def get_brackets(self, p_ensemble: float, running_max: float, hour: int) -> List[Dict]:
    brackets = []
    rmax_int = int(round(running_max))

    for temp in self.temp_range:
        dist = abs(temp - rmax_int)

        # Preço base
        if dist == 0:
            ask = min(0.92, p_ensemble * 0.75 + 0.18)
        elif dist == 1:
            ask = min(0.65, p_ensemble * 0.55 + 0.08)
        elif dist == 2:
            ask = min(0.35, p_ensemble * 0.30 + 0.04)
        else:
            ask = max(0.02, 0.10 - dist * 0.015)

        if temp < rmax_int - 1:
            ask = min(0.96, ask + 0.12)

        # NOVO: Brackets distantes têm liquidez zero (não são negociáveis)
        if dist > 5:
            ask = 0.01
            bid = 0.0
            brackets.append({"label": ..., "ask": 0.01, "price": 0.01, "bid": 0.0, ...})
            continue

        ask = float(np.clip(ask, 0.02, 0.97))
        # NOVO: Spread mínimo de 7% + 2% por cada distância
        spread_factor = 0.07 + dist * 0.02
        bid = ask * (1 - spread_factor)

        brackets.append({...})
```

### 2.4. Live Bot não protege contra "Market Date" do dia errado
**Ficheiro:** `munich_live_bot.py`

**Problema:** O `PolymarketFetcher` procura o mercado para a data de Berlim. Mas às 00:05 (hora de Berlim), o mercado de "hoje" ainda pode não existir, ou o mercado de "ontem" ainda está aberto para resolver. O bot pode tentar comprar num mercado que encerra em 5 minutos.

**Fix:** Não permitir compras nas primeiras/últimas horas, ou verificar a `end_date` do mercado.
```python
# Após fetch_market:
if market:
    end_date_str = market.get("end_date", "")
    try:
        # Se o mercado encerra hoje, verificar se faltam menos de 2 horas
        # (implementação depende do formato de end_date do Polymarket)
        pass
    except Exception:
        pass

# Protecção simples: não comprar antes de DAY_START ou depois de DAY_END - 1
if h_cur >= DAY_END - 1:
    bet_blocked_reason = "mercado encerra em breve"
    continue
```

### 2.5. WU `units=m` pode retornar Celsius em vez de Métrico
**Ficheiro:** `munich_weather.py`

**Problema:** O parâmetro `units=m` na API WU supostamente retorna unidades métricas. Mas para campos como pressão, a unidade métrica pode ser hPa ou mb (1 mb = 1 hPa), ou mmHg em algumas estações. Se a estação EDDM reportar pressão em hPa, `float(obs.get("pressure"))` está correto. Mas se a API devolver inHg (polegadas de mercúrio, comum nos EUA), o valor 29.92 inHg será interpretado como 29.92 hPa, quebrando a feature `pressure_trend_3h`.

**Fix:** Adicionar validação de intervalo.
```python
_press = obs.get("pressure")
_press_val = float(_press) if _press is not None else 1013.0

# Validação: pressão atmosférica ao nível do mar está entre 870 e 1084 hPa
# Se estiver fora, provavelmente está em inHg (valores ~30)
if _press_val < 100:  # Provavelmente inHg
    _press_val = _press_val * 33.8639  # Converter inHg para hPa

"pressure_hpa": _press_val,
```

---

## 🟢 PRIORIDADE 3: Melhorias de Robustez e Semântica

### 3.1. Bootstrapping do Live Bot corta slots antigos, perdendo features de lag
**Ficheiro:** `munich_live_bot.py`

**Problema:** `predict_ensemble` usa `slots_so_far` para calcular `delta_1h`, `accel`, etc. Se o bot reiniciar às 14h, o bootstrap carrega slots desde as 6h, o que é ótimo. Mas se a sessão do requests falhar, `slots_so_far` pode ter apenas 1-2 observações, e `len(slots_so_far) < 4` bloqueia a predição.

**Fix:** Fallback para Open-Meteo se WU falhar no bootstrap.
```python
try:
    _s, _sl = bootstrap_today(wu_key, wu_sess)
    if len(_sl) < 4:
        print(f"  {C['yellow']}WU com poucos dados, a usar OM como fallback{R}")
        _s, _sl = bootstrap_om_today(om_sess)
    series_today = _s
    slots_so_far = _sl
except Exception as e:
    print(f"  {C['yellow']}WU falhou, a usar OM: {e}{R}")
    _s, _sl = bootstrap_om_today(om_sess)
    series_today = _s
    slots_so_far = _sl
```

### 3.2. `normalize_datetime_ceiling` trata meia-noite de forma inconsistente
**Ficheiros:** `munich_backtester.py`, `munich_train.py`

**Problema:** Quando `hour=24`, o código substitui para `hour=0` e adiciona 1 dia. Mas a data já foi calculada a partir do timestamp original. Isto significa que uma observação às 00:00 do dia 2 pode ser atribuída ao dia 1 se o arredondamento do ceiling a empurrar para o dia seguinte. Mais importante, `mask_24` soma `timedelta(days=1)` ao timestamp, mas a coluna `date` já foi calculada. É preciso recalcular a data.

**Fix:**
```python
# Após corrigir hour=24:
mask_24 = raw["hour"] == 24
raw.loc[mask_24, "hour"] = 0
# Recalcular a data para estes casos
raw["date"] = raw["datetime_local"].dt.date  # Atualizar data após ajuste
```

### 3.3. Phased Entry P2 não verifica se já passou do horário do pico
**Ficheiro:** `munich_phased_entry.py`

**Problema:** P2 e P3 podem ser desbloqueados a qualquer hora se `p_ensemble >= threshold`. Mas às 20h (perto do fecho), o pico já passou há muito e o mercado está a resolver. Comprar às 20h com p=70% é arriscado porque o mercado pode ter baixa liquidez e o spread ser enorme.

**Fix:** Adicionar janela horária para P2/P3.
```python
# Em PhasedEntry.evaluate():
# P2: Dupla confirmação
if not self.parcel_bought[1]:
    model_ok = p_ensemble >= self.thr_p2
    mkt_ok, mkt_detail = self._market_confirms_model(market, running_max)
    hour_ok = 10 <= hour < 19  # Não comprar nas últimas 2 horas
    
    if model_ok and mkt_ok and hour_ok:
        actions.append(buy_action_p2)
    elif model_ok and mkt_ok and not hour_ok:
        actions.append({
            "parcel_idx": 1, "size_usdc": 0,
            "reason": f"P2 BLOQUEADA: hora={hour}h (mercado a encerrar)",
            "model_ok": True, "market_ok": True,
        })
```

### 3.4. Z-Score `running_max` nunca é resetado entre dias no Live Bot
**Ficheiro:** `munich_live_bot.py`

**Problema:** No live bot, `zscore.reset()` é chamado em `_handle_new_day()`. MAS se o bot não reiniciar (ou se o novo dia for detectado tarde), o `running_max` do dia anterior persiste, e uma temperatura de 10°C (normal de manhã) será comparada com 28°C (pico de ontem), gerando um z-score negativo massivo, o que faz o ensemble baixar artificialmente.

**Fix:** Garantir que `zscore.reset()` é a PRIMEIRA coisa executada no novo dia, antes de qualquer `predict_ensemble`. E invalidar `latest_obs` para não usar dados do dia anterior.
```python
def _handle_new_day(new_date: date) -> None:
    ...
    entry.reset()
    zscore.reset()  # Já existe, mas garantir que está antes de qualquer predict
    latest_obs = None  # Invalidar observação antiga
    ...
```

### 3.5. Features de treino e inferência usam janelas de lag diferentes
**Ficheiro:** `munich_train.py` vs `munich_model.py`

**Problema:** Em `build_dataset()` (treino), a feature `pressure_trend_3h` usa `slots_so_far[-6:]` (6 slots = 3h). Em `build_features()` (inferência), usa `slots_so_far[-6:]`. Isto está correito. MAS no bootstrap do live bot, `slots_so_far` pode ter menos de 6 slots nas primeiras horas. `len(press_vals) >= 2` protege, mas a "tendência" de 1h não é a mesma que a de 3h.

**Fix:** Documentar este comportamento e usar `min(6, len(slots_so_far))` para ambas as janelas, ou adicionar padding com o primeiro valor.

### 3.6. `PolymarketFetcher._normalize_label` corta labels com "≥" ou "≤"
**Ficheiro:** `munich_live_bot.py`

**Problema:** A API do Polymarket pode retornar labels como "≥ 25°C" ou "≤ 20°C". A função `_extract_temp` lida com números, mas `_normalize_label` pode não reconhecer estes símbolos e gerar labels como "25°C" em vez de "25°C or higher".

**Fix:**
```python
def _normalize_label(self, text: str) -> str:
    if len(text) <= 25:
        return text
    v = self._extract_temp(text)
    if v is None:
        return text
    s = text.lower()
    if any(x in s for x in ("higher", "above", ">=", "≥")):
        return f"{v:.0f}°C or higher"
    if any(x in s for x in ("lower", "below", "<=", "≤")):
        return f"{v:.0f}°C or lower"
    return f"{v:.0f}°C"
```
```
