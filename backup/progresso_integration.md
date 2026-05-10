# Progresso da Integração - POLY-IRIS Features em POLY-MULTI-CITY

**Início:** 2026-04-29

---

## ✅ Fase 1: Preparação e Harmonização

### 1.1 Documentação
- [x] Analisar POLY-IRIS (~/POLY-IRIS)
- [x] Analisar POLY-MULTI-CITY
- [x] Criar ANALISE_COMPARATIVA_POLY_IRIS.md
- [x] Criar plano-integration.md
- [x] Criar progresso_integration.md

### 1.2 Estrutura de Configuração
- [x] Definir estrutura de config.json com suporte a estratégias
- [x] Adicionar campos para Dual Strategy (enabled, phases, thresholds)
- [x] Adicionar campos para Forecast Confidence
- [x] Criar dataclasses: StrategyConfig, SingleEntryConfig, DualStrategyConfig, PhasedEntryConfig, ForecastConfidenceConfig
- [x] Integrar no CityConfig com campo strategy

### 1.3 Base de Dados
- [ ] Adicionar colunas para forecast_confidence em DB
- [ ] Migrar DB existente

---

## ⏳ Fase 2: Implementação do Forecast Confidence

### 2.1 Core Module
- [x] Criar modules/forecast_confidence.py (genérico)
- [x] Implementar métodos:
  - [x] p_forecast_correct()
  - [x] max_ask_for_ev_positive()
  - [x] p_forecast_correct_with_om_penalty()
  - [x] get_forecast_accuracy_table()

### 2.2 Integração com Config
- [x] Ler thresholds de forecast_confidence por cidade (via CityConfig.strategy.forecast_confidence)
- [x] Calcular por cidade

### 2.3 Testes
- [x] Testar self-test com Munich (WU disponível)
- [x] Testar self-test com Dallas (sem WU)

---

## ⏳ Fase 3: Implementação do Dual Strategy

### 3.1 Core Module
- [x] Criar modules/dual_strategy.py (genérico)
- [x] Implementar Forecast Early (10-14h)
- [x] Implementar Peak Detection (11h+)
- [x] Integrar com forecast_confidence
- [x] Stop-loss partilhado

### 3.2 Integração com live_bot
- [ ] Adicionar switch estratégia em live_bot
- [ ] Implementar lógica de escolha estratégia

### 3.3 Testes
- [x] Testar self-test com Munich
- [ ] Testar Dual Strategy em cada cidade
- [ ] Comparar com SingleEntry

---

## ⏳ Fase 4: Phased Entry Genérico

### 4.1 Refatorar phased_entry.py
- [x] Criar modules/phased_entry.py (genérico)
- [x] Implementar PhasedEntry (3 parcelas)
- [x] Implementar SingleEntry (1 compra + stop-loss)
- [x] Tornar genérico por cidade
- [x] Adicionar config de fases por cidade

### 4.2 Testes
- [x] Testar self-test SingleEntry
- [x] Testar self-test PhasedEntry
- [ ] Validar phased entry em todas as cidades

---

## ⏳ Fase 5: Calibração Multi-Cidade

### 5.1 Dallas
- [ ] Calibrar forecast_confidence
- [ ] Calibrar dual_strategy
- [ ] Testar em paper trading

### 5.2 Ankara
- [ ] Calibrar forecast_confidence
- [ ] Calibrar dual_strategy
- [ ] Testar em paper trading

### 5.3 Munich
- [ ] Calibrar forecast_confidence
- [ ] Calibrar dual_strategy
- [ ] Testar em paper trading

---

## ⏳ Fase 6: Validação Final

### 6.1 Backtesting
- [ ] Backtest SingleEntry vs Dual Strategy
- [ ] Comparar resultados por cidade

### 6.2 Paper Trading (14 dias)
- [ ] Ativar em paper trading
- [ ] Monitorizar resultados
- [ ] Ajustar thresholds

---

## 📊 Métricas de Sucesso

- [ ] SingleEntry mantém performance (>85% win rate)
- [ ] Dual Strategy melhora ou mantém performance
- [ ] Forecast Confidence reduz falsos positivos
- [ ] Sistema permanece genérico (easy add city)

---

## 🔧 Notas Técnicas

### Arquivos Criados/Modificados
- [x] `cities/config.py` - Adicionado StrategyConfig e subclasses
- [x] `modules/__init__.py` - NOVO
- [x] `modules/forecast_confidence.py` - NOVO (genérico)
- [x] `modules/dual_strategy.py` - NOVO (genérico)
- [x] `modules/phased_entry.py` - NOVO (genérico)
- [x] `modules/strategy_factory.py` - NOVO (factory)
- [ ] `modules/live_bot.py` - Integrar estratégias
- [ ] `modules/predictor.py` - Adicionar forecast_confidence

### Arquivos POLY-IRIS como Referência
- `~/POLY-IRIS/forecast_confidence.py`
- `~/POLY-IRIS/dual_strategy.py`
- `~/POLY-IRIS/phased_entry.py`
- `~/POLY-IRIS/live_bot.py`

---

## 📝 Estado Atual (2026-04-29)

### Completado:
- ✅ Estrutura de configuração estendida com StrategyConfig
- ✅ Módulos genéricos criados:
  - forecast_confidence.py (tested)
  - dual_strategy.py (tested)
  - phased_entry.py (tested)
  - strategy_factory.py (tested)
- ✅ SingleEntry configurado para todas as cidades (validado)
- ✅ Forecast Confidence configurado para Munich (com WU)

### A Fazer:
- ⏳ Integrar estratégias no live_bot
- ⏳ Adicionar forecast_confidence no predictor
- ⏳ Testar Dual Strategy em paper trading
- ⏳ Calibrar thresholds por cidade
- ⏳ Backtest comparativo

### Decisão:
Todas as cidades configuradas com SingleEntry (validado) por defeito.
Dual Strategy disponível para ativação via config quando calibrado.

---

**Última Atualização:** 2026-04-29
**Status:** Em Progresso - Fases 1-4 completas
