# Live Bot Integration — CLI Mode Complete

**Data:** 2026-04-29
**Status:** ✅ Completo

---

## 🎯 Implementação Realizada

### 1. CLI Arguments Atualizados

```bash
python live_bot.py --cities munich --mode single --run paper
python live_bot.py --cities munich --mode dual --run paper
python live_bot.py --cities munich --mode phased --run paper
```

### 2. Live Bot Modificações

**`live_bot.py`** — Principais alterações:

1. **Imports atualizados:**
   ```python
   from modules.strategy_factory import create_strategy  # substitui phased_entry.SingleEntry
   ```

2. **CityState atualizado:**
   ```python
   strategy_mode: str = "single"  # "single", "dual", "phased"
   entry: any = None  # Aceita qualquer estratégia
   last_wu_forecast_max: int | None = None  # Cache de forecast
   last_om_forecast_max: int | None = None
   ```

3. **Fetch de forecasts para Dual Strategy:**
   ```python
   # A cada hora (minutos 0-5)
   if state.strategy_mode == "dual" and city.wu_history_path:
       wu_forecast_max = fetch_wu_forecast_max(...)
       om_forecast_max = fetch_om_forecast_max(...)
       state.last_wu_forecast_max = wu_forecast_max
       state.last_om_forecast_max = om_forecast_max
   ```

4. **Trade decision genérico:**
   ```python
   # Avalia estratégia dependendo do mode
   if state.strategy_mode == "dual":
       actions = state.entry.evaluate(
           p_peak=p_ensemble,
           hour=h_cur,
           market=state.market,
           running_max=running_max,
           wu_forecast_max=wu_forecast_max,
           om_forecast_max=om_forecast_max,
           cloud_cover=...,
           humidity=...,
           month=...,
           uv_index=...,
       )
   else:
       # SingleEntry e PhasedEntry
       actions = state.entry.evaluate(
           p_ensemble=p_ensemble,
           hour=h_cur,
           market=state.market,
           running_max=running_max,
           forecast_agreement=forecast_agreement,
       )
   ```

5. **Display atualizado:**
   ```
   MUNICH    12:30 | Temp:  22.3°C | RMax:  23.5°C | FC: 25°C | P: 0.92 | Mode: D | Bought: No
                                                                       ^
                                                                       └─ Mostra "D" para Dual
   ```

6. **Inicialização de estratégias via factory:**
   ```python
   entry = create_strategy(city, mode=args.mode, parcel_size=PARCEL_SIZE)
   ```

---

## 📋 Estratégias Disponíveis

### SingleEntry (default)
```bash
python live_bot.py --mode single
```
- Usa `city.threshold` e `city.hour_min`
- Valida em: Munich, Dallas, Ankara
- Win rate: Munich 85%+, Dallas 96%+, Ankara 90%+

### DualStrategy
```bash
python live_bot.py --mode dual
```
- Forecast Early (10-14h) + Peak Detection (11h+)
- Usa forecast WU/OM para P(forecast correcto)
- Requer: cidade com WU (Munich)
- Estado: Disponível, requer calibração

### PhasedEntry
```bash
python live_bot.py --mode phased
```
- 3 parcelas (P1: Value Early, P2: Dupla Confirmação, P3: Alta Confiança)
- P1: manhã + forecast agree + market confirma
- P2: P >= 70% + market confirma (10-19h)
- P3: P >= 85%
- Estado: Disponível, requer validação

---

## 🔧 Arquivos Modificados

1. **`cities/config.py`**
   - Removido: Campo `strategy` do `CityConfig`
   - Mantido: `threshold`, `hour_min` para SingleEntry

2. **`modules/strategy_factory.py`**
   - Atualizado: `create_strategy()` aceita `**kwargs`

3. **`live_bot.py`**
   - Imports: Adicionado `create_strategy`
   - CityState: Adicionado `strategy_mode` e forecast caches
   - _tick_city: Adicionado fetch de forecasts para Dual
   - Trade decision: Genérico para todas as estratégias
   - Display: Mostra modo e forecast (para Dual)
   - main: Cria estratégias via factory

---

## ✅ Validação

### Testes Realizados

1. **Strategy Factory:**
   ```bash
   python test_live_bot_modes.py
   ```
   - SingleEntry: ✅
   - DualStrategy: ✅
   - PhasedEntry: ✅

2. **Live Bot Help:**
   ```bash
   python live_bot.py --help
   ```
   - Mostra: --mode {single,dual,phased} ✅

3. **Módulos individuais:**
   - `modules/forecast_confidence.py` ✅
   - `modules/dual_strategy.py` ✅
   - `modules/phased_entry.py` ✅
   - `modules/strategy_factory.py` ✅

---

## 🎯 Como Usar

### SingleEntry (default, validado)
```bash
python live_bot.py --cities munich --mode single --run paper
```

### DualStrategy (para testar)
```bash
python live_bot.py --cities munich --mode dual --run paper
```
- Requer: cidade com WU (Munich)
- Nota: Calibração necessária antes de produção

### PhasedEntry (para testar)
```bash
python live_bot.py --cities munich --mode phased --run paper
```
- Nota: Validação necessária

### Multi-cidade
```bash
python live_bot.py --cities munich,dallas,ankara --mode single --run paper
```

---

## 📊 Próximos Passos

### Fase 1: Validação (imediato)
- [ ] Testar SingleEntry em paper trading (já validado)
- [ ] Testar DualStrategy em paper trading (14 dias)
- [ ] Testar PhasedEntry em paper trading (14 dias)

### Fase 2: Calibração
- [ ] Calibrar Dual Strategy para Munich
- [ ] Calibrar Phased Entry para Munich
- [ ] Comparar resultados: Single vs Dual vs Phased

### Fase 3: Produção
- [ ] Atualizar config.py com thresholds calibrados
- [ ] Documentar quando usar cada estratégia
- [ ] Implementar alertas Telegram diferenciados

---

## 📝 Notas Técnicas

### Forecast Fetching
- Fetch WU forecast: A cada hora, minutos 0-5
- Cache em `last_wu_forecast_max` e `last_om_forecast_max`
- Apenas para Dual Strategy

### Strategy Evaluation
- SingleEntry: Usa `p_ensemble`, `hour`, `market`, `running_max`
- DualStrategy: Usa `p_peak`, `hour`, `market`, `running_max`, `wu_forecast_max`, `om_forecast_max`, `cloud_cover`, `humidity`, `month`, `uv_index`
- PhasedEntry: Usa `p_ensemble`, `hour`, `market`, `running_max`, `forecast_agreement`

### Display
- SingleEntry: Mostra `Mode: S`
- DualStrategy: Mostra `Mode: D` + forecast
- PhasedEntry: Mostra `Mode: P`

---

**Última Atualização:** 2026-04-29
**Pronto para:** Testes em paper trading
