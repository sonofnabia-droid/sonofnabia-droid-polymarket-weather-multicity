# Plano de Integração - POLY-IRIS Features em POLY-MULTI-CITY

**Data:** 2026-04-29
**Objetivo:** Integrar features avançadas do POLY-IRIS (Dual Strategy, Forecast Confidence) mantendo a arquitetura genérica multi-cidade
**Abordagem:** Opção C - Híbrido (SingleEntry + Dual Strategy opcional por cidade)

---

## 🎯 Visão Geral

Transformar o sistema multi-cidade para suportar:
1. **SingleEntry** (genérico, já validado em 3 cidades)
2. **DualStrategy** (opcional, por cidade) - inovação do IRIS
3. **Forecast Confidence** (genérico) - suporte a forecast WU
4. **Configuração flexível** - permite escolher estratégia por cidade

**Meta:** Manter simplicidade genérica enquanto adiciona inteligência avançada opcional.

---

## 📋 Fases de Integração

### Fase 1: Harmonização de Estruturas (1-2 dias)

#### Objetivo
Preparar código genérico para suportar features IRIS sem quebrar multi-cidade.

#### Tarefas

**1.1 Separar SingleEntry de PhasedEntry**
- **Atual:** `phased_entry.py` contém `PhasedEntry` e `SingleEntry`
- **Alvo:** Criar `single_entry.py` separado
- **Motivo:** SingleEntry é usado em live_bot, PhasedEntry é alternativo
- **Estrutura:**
  ```python
  # single_entry.py
  class SingleEntry:
      def __init__(self, parcel_size=5.0, threshold=0.65, hour_min=11, stop_loss_delta=1.0)
      def evaluate(...)
      def mark_bought(...)
      def check_stop_loss(...)
      def reset(...)
      # ... (mesma lógica que IRIS, mas genérico)
  ```

**1.2 Criar `forecast_confidence.py` genérico**
- **Base:** `munich_forecast_confidence.py` (IRIS)
- **Mudanças:**
  - Remover hardcoded de Munique
  - Tornar parameters configuráveis por cidade
  - Manter lógica de P(forecast correcto)
- **Estrutura:**
  ```python
  # forecast_confidence.py
  def p_forecast_correct(month, cloud_cover, humidity, om_agrees, temp_gap, uv_index)
  def max_ask_for_ev_positive(p_forecast, margin=0.05)
  def p_forecast_correct_with_om_penalty(month, cloud, humidity, wu_max, om_max, temp_gap, uv)
  # ... (mesma lógica, mas genérico)
  ```

**1.3 Criar `dual_strategy.py` genérico**
- **Base:** `munich_dual_strategy.py` (IRIS)
- **Mudanças:**
  - Remover hardcoded de Munique
  - Adicionar parâmetros configuráveis por cidade
  - Usar `forecast_confidence.py` genérico
- **Estrutura:**
  ```python
  # dual_strategy.py
  class DualStrategy:
      def __init__(self, city_name, config, parcel_size=5.0):
          self.city_name = city_name
          self.config = config
          self.fc_hour_min = config.get("fc_hour_min", 10)
          # ... outros parâmetros de city config
      def evaluate(p_peak, hour, market, running_max, wu_forecast_max, om_forecast_max, ...):
          # Strategy A: Forecast Early
          # Strategy B: Peak Detection
          # ... (mesma lógica, mas genérico)
      def check_stop_loss(...)
      def mark_bought(...)
      def reset(...)
  ```

**1.4 Atualizar `cities/config.py`**
- **Adicionar novos parâmetros por cidade:**
  ```python
  "munich": CityConfig(
      # ... params existentes ...
      strategy="single",  # 'single' | 'dual'
      fc_hour_min=10,     # para dual
      fc_hour_max=14,     # para dual
      fc_p_min=0.75,      # para dual
      fc_ev_margin=0.05,  # para dual
      pk_threshold=0.650, # para dual
      pk_hour_min=11,    # para dual
      stop_loss_delta=1.0, # stop-loss
  ),
  ```

**1.5 Atualizar imports em `live_bot.py`**
- Adicionar imports para novos módulos genéricos
- Remover imports específicos de Munique

#### Deliverables
- ✅ `single_entry.py` - SingleEntry genérico
- ✅ `forecast_confidence.py` - Forecast confidence genérico
- ✅ `dual_strategy.py` - Dual strategy genérico
- ✅ `cities/config.py` atualizado com novos params
- ✅ `live_bot.py` atualizado com imports

#### Validação
- [ ] SingleEntry genérico funciona em Munique
- [ ] Imports não quebram
- [ ] Config parsing funciona para todas as cidades

---

### Fase 2: Integração de Dual Strategy (2-3 dias)

#### Objetivo
Integrar DualStrategy no live_bot mantendo compatibilidade com SingleEntry.

#### Tarefas

**2.1 Atualizar `live_bot.py` para suportar múltiplas estratégias**
- **Atual:** Suporta apenas uma estratégia
- **Alvo:** Suporta SingleEntry ou DualStrategy baseado em config
- **Lógica:**
  ```python
  if city.strategy == "dual":
      entry = DualStrategy(city_name, city)
  else:
      entry = SingleEntry(threshold=city.threshold, hour_min=city.hour_min)
  ```

**2.2 Atualizar loop principal do live_bot**
- **Atual:** Chamada uniforme para entry.evaluate()
- **Alvo:** Passar parâmetros diferentes por estratégia
- **Dual Strategy precisa de:**
  - `p_peak` (modelo ML)
  - `wu_forecast_max` (forecast WU)
  - `om_forecast_max` (forecast OM)
  - `cloud_cover`, `humidity`, `month`, `uv_index`
- **SingleEntry precisa de:**
  - `p_ensemble` (modelo ML)
  - `forecast_agreement` (para P1 se for PhasedEntry)

**2.3 Adicionar fetch de forecasts por cidade**
- **Atual:** Fetch WU/OM hardcoded para Munique
- **Alvo:** Genérico por cidade via config
- **Lógica:**
  ```python
  if city.strategy == "dual":
      wu_forecast = fetch_wu_forecast_max(city.icao, wu_key, wu_sess)
      om_forecast = fetch_om_forecast_max(city.icao, om_sess)
  ```

**2.4 Atualizar display para mostrar estratégia usada**
- Mostrar "Single" ou "Dual" no display
- Mostrar P(fc) se for Dual
- Mostrar detalhes da estratégia que triggerou

**2.5 Adicionar stop-loss genérico**
- **Atual:** Stop-loss em SingleEntry apenas
- **Alvo:** Stop-loss em DualStrategy também
- **Lógica:** Mesma lógica, aplicada a ambas

#### Deliverables
- ✅ `live_bot.py` atualizado com suporte dual/single
- ✅ `weather.py` atualizado com fetch genérico de forecasts
- ✅ `display.py` atualizado para mostrar estratégia
- ✅ Stop-loss funcional em ambas as estratégias

#### Validação
- [ ] SingleEntry funciona em todas as cidades
- [ ] DualStrategy funciona em Munique (validado)
- [ ] DualStrategy funciona em Dallas (NOVO)
- [ ] DualStrategy funciona em Ankara (NOVO)
- [ ] Stop-loss funciona em ambas as estratégias

---

### Fase 3: Validação e Calibração (3-5 dias)

#### Objetivo
Validar SingleEntry e DualStrategy em todas as cidades.

#### Tarefas

**3.1 Validar SingleEntry (já parcialmente feito)**
- Munique: ✅ (já validado no backtest)
- Dallas: ✅ (calibrado, win=96.2%)
- Ankara: ✅ (calibrado, win=89.9%)

**3.2 Calibrar Dual Strategy por cidade**
- **Munique:** Calibrar parâmetros:
  - `fc_hour_min/max`, `fc_p_min`, `pk_threshold`, etc.
- **Dallas:** Calibrar forecast confidence:
  - Validar WU/OM forecasts para Dallas
  - Calibrar parâmetros de `p_forecast_correct`
- **Ankara:** Calibrar forecast confidence:
  - Validar WU/OM forecasts para Ankara
  - Calibrar parâmetros de `p_forecast_correct`

**3.3 Backtest Dual Strategy**
- Criar backtester para DualStrategy (ou adaptar existente)
- Comparar resultados: Single vs Dual
- Métricas: ROI, Win%, Trades/ano, Complexidade

**3.4 Documentar thresholds recomendados**
- Atualizar `cities/config.py` com thresholds calibrados
- Documentar Single vs Dual para cada cidade
- Recomendações por cidade

#### Deliverables
- ✅ Thresholds calibrados por cidade e estratégia
- ✅ Backtest results para Dual Strategy
- ✅ Documentação de quando usar Single vs Dual
- ✅ Config atualizada com melhores thresholds

#### Validação
- [ ] DualStrategy tem ROI positivo em todas as cidades
- [ ] Win% não cai abaixo de 80% em nenhuma cidade
- [ ] Dual Strategy não causa mais trades que SingleEntry (controle de risco)
- [ ] Stop-loss funciona corretamente em ambas as estratégias

---

### Fase 4: Otimizações Avançadas (opcional, 5-7 dias)

#### Objetivo
Incorporar melhorias avançadas do IRIS mantendo simplicidade.

#### Tarefas

**4.1 Melhorar display avançado**
- Incorporar melhorias de `munich_display.py`
- Adicionar gráficos e tabelas avançadas
- Mostrar detalhes de forecast confidence

**4.2 Adicionar alertas e monitoring**
- Alertas Telegram diferentes por estratégia
- Monitoramento de performance por cidade e estratégia
- Dashboard de comparação Single vs Dual

**4.3 Otimizar performance**
- Vetorizar operações onde possível
- Otimizar I/O e database access
- Reduzir redundâncias

**4.4 Testes e validação finais**
- Testar todas as combinações (cidade × estratégia)
- Validar em paper trading por 2 semanas
- Documentar bugs encontrados e corrigidos

#### Deliverables
- ✅ Display melhorado com gráficos
- ✅ Sistema de alertas avançado
- ✅ Performance otimizada
- ✅ Testes completos e validação documentada

#### Validação
- [ ] Performance não degrada com nova funcionalidade
- [ Não há regressões em SingleEntry
- [ ] Não há crashes ou erros em Dual Strategy
- [ ] Sistema está estável em produção

---

## 📁 Novos Ficheiros a Criar

### Fase 1
- `single_entry.py` - SingleEntry genérico
- `forecast_confidence.py` - Forecast confidence genérico
- `dual_strategy.py` - DualStrategy genérico

### Fase 2
- Atualizar `cities/config.py` - Novos parâmetros
- Atualizar `live_bot.py` - Suporte dual/single
- Atualizar `weather.py` - Fetch genérico de forecasts
- Atualizar `display.py` - Mostrar estratégia

### Fase 3
- Calibrações por cidade/estratégia
- Backtests de comparação
- Documentação

### Fase 4
- Display melhorado
- Alertas avançados
- Performance tuning
- Documentação final

---

## 🔧 Estratégias de Migração

### Para SingleEntry (Backward Compatibility)
```python
# Código existente continua a funcionar
from phased_entry import SingleEntry

entry = SingleEntry(threshold=0.65, hour_min=11)
actions = entry.evaluate(p_ensemble, hour, market, running_max, forecast_agreement)
```

### Para DualStrategy (Novo)
```python
# Novo código para dual strategy
from dual_strategy import DualStrategy
from cities.config import CITIES

city = CITIES["dallas"]
entry = DualStrategy(city.name, city)

actions = entry.evaluate(
    p_peak=p_peak,               # do modelo ML
    hour=hour,
    market=market,
    running_max=running_max,
    wu_forecast_max=wu_fc,    # forecast WU
    om_forecast_max=om_fc,    # forecast OM
    cloud_cover=cloud,
    humidity=humidity,
    month=month,
    uv_index=uv
)
```

### Por Cidade (Configuração)
```python
# cities/config.py
"dallas": CityConfig(
    # ... outros params ...
    strategy="dual",              # <-- NOVO
    fc_hour_min=10,
    fc_hour_max=14,
    fc_p_min=0.75,
    fc_ev_margin=0.05,
    pk_threshold=0.650,
    pk_hour_min=11,
    stop_loss_delta=1.0,
),

"ankara": CityConfig(
    strategy="single",             # <-- Pode ser diferente por cidade
    threshold=0.35,
    hour_min=15,
    stop_loss_delta=1.0,
),
```

---

## 📊 Matriz de Risco

| Aspecto | Risco | Mitigação |
|--------|------|-----------|
| **Complexidade** | Médio | Manter SingleEntry como default, Dual opcional |
| **Performance** | Baixo | Testar exaustivamente antes de prod |
| **Regressão** | Baixo | Manter backward compatibility |
| **Manutenção** | Baixo | Código genérico é mais fácil |
| **Validação** | Médio | Calibração por cidade/estratégia |
| **Testes** | Alto | Matriz cidade × estratégia × tempo |
| **Documentação** | Médio | Documentar tudo exaustivamente |

---

## 🎯 Critérios de Sucesso

### Mínimo (MVP)
- ✅ SingleEntry funciona em todas as cidades
- ✅ DualStrategy funciona em pelo menos 1 cidade
- ✅ No regressões em funcionalidade existente
- ✅ Sistema estável em paper trading

### Recomendado
- ✅ SingleEntry validado em todas as 3 cidades
- ✅ DualStrategy calibrado em pelo menos 2 cidades
- ✅ ROI positivo em todas as estratégias
- ✅ Win% > 85% em todas as estratégias
- ✅ Documentação completa

### Otimizado
- ✅ Todas as 3 cidades suportam ambas estratégias
- ✅ ROI melhor em Dual vs Single (em pelo menos 2 cidades)
- ✅ Performance otimizada
- ✅ Monitoramento avançado implementado
- ✅ Documentação exaustiva

---

## 📅 Cronograma

- **Fase 1:** 1-2 dias
- **Fase 2:** 2-3 dias
- **Fase 3:** 3-5 dias
- **Fase 4:** 5-7 dias (opcional)
- **Total:** 11-17 dias (sem Fase 4: 6-10 dias)

---

## 🚦 Próximos Passos

1. ✅ Análise completa concluída
2. ⏳ **INICIAR FASE 1** - Harmonização de Estruturas
3. ⏳ Continuar pelas fases subsequentes
4. ⏳ Validar e documentar progresso

---

**Status:** Fase 1 (Harmonização de Estruturas) COMPLETA ✅
**Plano documentado em:** `plano-integration.md`
**Progresso será documentado em:** `progresso_integration.md`

---

## 📝 Progresso Atual (2026-04-29)

### Fase 1: Harmonização de Estruturas - ✅ COMPLETA

**Criados:**
- ✅ `modules/__init__.py` - Package initialization
- ✅ `modules/forecast_confidence.py` - Forecast confidence genérico (testado)
- ✅ `modules/dual_strategy.py` - Dual strategy genérico (testado)
- ✅ `modules/phased_entry.py` - SingleEntry + PhasedEntry genéricos (testado)
- ✅ `modules/strategy_factory.py` - Factory para criar estratégias

**Modificados:**
- ✅ `cities/config.py` - Adicionado StrategyConfig e subclasses
  - SingleEntryConfig, DualStrategyConfig, PhasedEntryConfig, ForecastConfidenceConfig
  - Campo `strategy` em CityConfig

**Configurações Atuais:**
- Munich: SingleEntry (threshold=0.55, hour_min=15), ForecastConfidence enabled
- Dallas: SingleEntry (threshold=0.35, hour_min=17), ForecastConfidence disabled (sem WU)
- Ankara: SingleEntry (threshold=0.35, hour_min=15), ForecastConfidence disabled (sem WU)

### Próxima Fase: Integração no Live Bot

Para ativar Dual Strategy numa cidade:
1. Set `strategy.mode = "dual"` em `cities/config.py`
2. Configurar `strategy.dual` com parâmetros específicos da cidade
3. Integrar em `live_bot.py` usando `create_strategy()` factory
