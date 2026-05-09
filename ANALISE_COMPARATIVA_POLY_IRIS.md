# Análise Comparativa: POLY-IRIS (ZAI) vs POLY-MULTI-CITY

**Data:** 2026-04-29

## 📋 Visão Geral

### POLY-IRIS (Versão ZAI)
- **Sistema base**: Single-city (Munich apenas)
- **Estratégias**: SingleEntry, PhasedEntry (3 parcelas), DualStrategy (2 vias)
- **Bug fixes**: Todos os bugs das sprints 1-3 corrigidos
- **Foco**: Otimização de trading com forecast confidence e dual strategy

### POLY-MULTI-CITY (Nossa versão)
- **Sistema base**: Multi-cidade genérico (Munique, Dallas, Ankara, extensível)
- **Estratégias**: SingleEntry (simplificada, genérica)
- **Bug fixes**: Todos os bugs das sprints 1-3 corrigidos
- **Foco**: Arquitetura genérica para fácil adição de novas cidades

---

## 🔍 Análise Detalhada por Componente

### 1. Estratégia de Entrada

#### POLY-IRIS

**SingleEntry:**
- Threshold calibrado: 0.650, hour_min=11h
- Stop-loss: temperature-based (1°C acima do bracket)
- 1 compra de $5 por dia
- Reason correto quando já comprou

**PhasedEntry:**
- 3 parcelas: P1 (10-12h), P2 (10-19h), P3 (qualquer hora)
- Thresholds: P1 (0.30-0.65), P2 (0.70), P3 (0.85)
- Janela horária para P2/P3 (não compra perto do fecho)
- Stop-loss compartilhado entre parcelas
- Reasons explícitos para bloqueios

**DualStrategy (NOVO e IMPORTANTE):**
- **Strategy A - Forecast Early**: 10h-14h, baseado em WU forecast
  - Trigger: P(forecast correcto) >= 75% e EV positivo
  - Compra bracket do forecast
  - Usa `munich_forecast_confidence.py` para calcular P(fc correcto)
  - Considera: cloud_cover, humidity, temp_gap, uv_index, OM agreement

- **Strategy B - Peak Detection**: 11h+, baseado em ML
  - Trigger: P(peak) >= 65%
  - Compra bracket do running_max
  - Mesma lógica que SingleEntry

- **Regras:**
  - 1 trade por dia (primeira a trigger ganha)
  - Stop-loss partilhado
  - Se forecast indisponível, A desativa automaticamente
  - Se já comprou, só verifica stop-loss

#### POLY-MULTI-CITY

**SingleEntry (única estratégia):**
- Threshold por cidade: Munique (0.55), Dallas (0.35), Ankara (0.35)
- hour_min por cidade: Munique (15h), Dallas (17h), Ankara (15h)
- 1 compra de $5 por dia
- Stop-loss: temperature-based (1°C acima do bracket)
- Genérico - funciona para qualquer cidade via config

**Diferença Importante:**
- POLY-IRIS: 3 estratégias complexas com forecast confidence
- POLY-MULTI-CITY: 1 estratégia simples, genérica e extensível

---

### 2. Forecast Confidence (NOVO em POLY-IRIS)

#### POLY-IRIS

**`munich_forecast_confidence.py`**:
- Heurística para estimar P(forecast WU correcto)
- Considera:
  - Mês do ano (accuracy sazonal)
  - Cloud cover (céu limpo → mais fiável)
  - Humidity (ar seco → mais fiável)
  - Consenso WU-OM (concordância aumenta confiança)
  - Temp gap (forecast - current)
  - UV index (radiação forte → mais fiável)
- Calcula max_ask para EV positivo
- Penalização por discordância OM ≥ 2°C

**Uso**: DualStrategy Strategy A (Forecast Early)

#### POLY-MULTI-CITY

**Não existe** forecast confidence - apenas modelo ML.

**Diferença:**
- POLY-IRIS: Combina forecast WU com heurísticas complexas
- POLY-MULTI-WINDOW: Depende apenas do modelo ML (mais simples, mas perde oportunidade de entrada antecipada)

---

### 3. Arquitetura de Código

#### POLY-IRIS

```
munich_live_bot.py (Principal)
├── munich_model.py (Modelo ML)
├── munich_weather.py (Dados meteorológicos - WU/OM)
├── munich_phased_entry.py (Phased/Single)
├── munich_dual_strategy.py (Dual - NOVO)
├── munich_forecast_confidence.py (Confiança forecast - NOVO)
├── munich_display.py (Display/logging)
├── polymarket_clob.py (CLOB integration)
└── munich_config.py (Configuração)
```

**Características:**
- Todos os ficheiros têm prefixo `munich_`
- Hardcoded para Munique
- Complexa, mas otimizada para Munique
- Dual strategy integrada
- Forecast confidence avançada

#### POLY-MULTI-CITY

```
live_bot.py (Principal, multi-cidade)
├── predictor.py (Preditor genérico multi-cidade)
│   ├── StreamingPeakDetector (Peak detection)
│   ├── compute_prev7() (Climatologia por cidade)
│   └── init_history_max/update_history_max
├── weather.py (Dados meteorológicos genérico)
├── phased_entry.py (SingleEntry genérico)
├── backtester.py (Backtester genérico)
├── calibrate.py (Calibrador genérico)
├── train.py (Treinador genérico)
├── polymarket_clob.py (CLOB integration, mesmo que IRIS)
├── cities/
│   ├── __init__.py
│   └── config.py (Configuração multi-cidade)
└── *_peak_model/ (Modelos por cidade)
```

**Características:**
- Ficheiros genéricos (sem prefixo `munich_`)
- Multi-cidade nativo via `cities/config.py`
- Dual strategy NÃO implementada (apenas SingleEntry)
- Simples, mas extensível
- Fácil adicionar novas cidades

---

### 4. Configuração

#### POLY-IRIS

**`munich_config.py`**:
- Hardcoded para Munique
- Parâmetros: thresholds, horários, clima
- Funções utilitárias (ceil_slot, smart_sleep)
- Acesso direto a WU/OM APIs

#### POLY-MULTI-CITY

**`cities/config.py`**:
- `CITIES` dict com configuração por cidade
- CityConfig dataclass com todos os parâmetros
- Climatologia por cidade
- Thresholds calibrados por cidade
- Extensível para novas cidades

**Exemplo:**
```python
CITIES = {
    "munich": CityConfig(
        name="munich",
        icao="EDDM",
        timezone="Europe/Berlin",
        threshold=0.55,
        hour_min=15,
        climatology={1: 3.0, 2: 5.0, ...},
    ),
    "dallas": CityConfig(
        name="dallas",
        icao="KDFW",
        timezone="America/Chicago",
        threshold=0.35,
        hour_min=17,
        climatology={1: 13.0, 2: 16.0, ...},
    ),
    # ...
}
```

**Diferença Importante:**
- POLY-IRIS: Hardcoded, difícil de adicionar cidades
- POLY-MULTI-CITY: Config-driven, fácil extensão

---

### 5. Modelos e Treinamento

#### POLY-IRIS

**`munich_train.py`**:
- Hardcoded para Munique
- Walk-forward validation
- Data leakage fix para seasonal_peak_prior
- DOY threshold optimization
- Ensemble: LightGBM + XGBoost
- Otimizações específicas para Munique

#### POLY-MULTI-CITY

**`train.py`**:
- Genérico, aceita `--city` parâmetro
- Mesma walk-forward validation
- Data leakage fix para seasonal_peak_prior (aplicado por cidade)
- Ensemble: LightGBM + XGBoost (pode variar por cidade)
- Features genéricas funcionam para qualquer cidade

**Diferença:**
- POLY-IRIS: Modelo único otimizado para Munique
- POLY-MULTI-CITY: Modelos independentes por cidade

---

### 6. Calibração

#### POLY-IRIS

**`munich_calibrate.py`**:
- Hardcoded para Munique
- Grid search com ROI simulado
- Recomenda thresholds para Munique
- Métricas: ROI, Win%, trades/ano

#### POLY-MULTI-CITY

**`calibrate.py`**:
- Genérico, aceita `--city` parâmetro
- Mesmo grid search
- Recomenda thresholds por cidade
- Modos: fast, standard, detailed, full

**Diferença:**
- POLY-IRIS: Calibração única para Munique
- POLY-MULTI-CITY: Calibração independente por cidade

---

### 7. Bug Fixes

#### EM COMUM (Ambas têm os mesmos fixes)

Ambas as versões incluem todos os bug fixes das sprints 1-3:

✅ **Sprint 1 - Bugs Críticos:**
1.1 Falsy check vento (0 km/h tratado como ausente)
1.2 Throttling fetch APIs
1.3 Tracking trades/stats diárias

✅ **Sprint 2 - Bugs Moderados:**
2.1 Comentários invertidos no Backtester
2.2 ZScoreStreaming duplicada
2.3 SingleEntry reason enganoso
2.4 Pesos hardcoded
2.5 Deduplicar ceil_slot
2.6 `compute_prev7` fallback inconsistente
2.7 P2 pode comprar "or lower"
2.8 `init_history_max` usa LOG_DIR
2.9 `save_history_max` com throttling I/O
2.10 Posições resolvidas periodicamente
2.11 Falsy check pressão atmosférica e direção do vento
2.12 Comentários invertidos em `backtester.py`

✅ **Sprint 3 - Bugs de Lógica e Trading:**
3.1 P1 compra bracket do running_max que VAI PERDER
3.2 Backtester idxmax() encontra o PRIMEIRO máximo
3.3 `prev7` OOD (climatologia)
3.4 `find_bracket` usa forecast para P1
3.5 Telegram alert_peak disparado na P1
3.6 Z-Score running_max resetado
3.7 Features janelas diferentes (OK)
3.8 PolymarketFetcher labels ≥/≤

**Diferença:**
- POLY-IRIS: Aplicados manualmente via instructions-zai.md
- POLY-MULTI-CITY: Aplicados e validados, integrados na arquitetura genérica

---

### 8. Dados Históricos

#### POLY-IRIS

**`historic/munich.csv`**:
- CSV específico para Munique
- Estrutura WU/Meteo
- Dados limpos de 2025 (sem 2026)
- ~434k linhas

#### POLY-MULTI-CITY

**`historic/*.csv`**:
- `historic/dallas.csv`: 231,916 linhas, Dallas data
- `historic/ankara.csv`: 436,809 linhas, Ankara data
- `historic/munich.csv`: 434,475 linhas, Munich data
- + backups de outras cidades (Atlanta, Buenos Aires, etc.)

**Diferença:**
- POLY-IRIS: Dados apenas de Munique
- POLY-MULTI-CITY: Dados de múltiplas cidades, extensível

---

### 9. Integração Polymarket

#### EM COMUM

**`polymarket_clob.py`**:
- ClobClient para paper/real trading
- Position e PositionManager
- Order placement
- Balance tracking
- Stop-loss suportado

**Diferença:**
- A implementação é IDÊNTICA em ambas as versões
- POLY-IRIS usa diretamente em `munich_live_bot.py`
- POLY-MULTI-CITY usa em `live_bot.py` (genérico)

---

## 🎯 Diferenças Chave

| Aspecto | POLY-IRIS (ZAI) | POLY-MULTI-CITY |
|--------|------------------|----------------|
| **Cidades** | Apenas Munique | Munique + Dallas + Ankara + extensível |
| **Estratégias** | Single, Phased, Dual (3) | Single (1) |
| **Forecast Confidence** | ✅ (avançada) | ❌ (só modelo) |
| **Arquitetura** | Hardcoded, complexa | Genérica, simples |
| **Configuração** | Hardcoded em munich_config.py | Dinâmica em cities/config.py |
| **Extensibilidade** | Difícil | Fácil (adicionar cidade = add config + treino) |
| **Performance** | Otimizada para Munique | Genérica, boa para todas |
| **Complexidade** | Alta | Baixa-Média |
| **Manutenção** | Média-Alta | Baixa |

---

## 💡 Recomendações de Integração

### Opção A: Manter Arquitetura Genérica, Adicionar Features IRIS

**Vantagens:**
- Mantém simplicidade e extensibilidade
- Multi-cidade nativo
- Fácil manutenção
- Já testado em produção (Munique)

**Mudanças:**
1. Adicionar `DualStrategy` genérico ao `phased_entry.py`
2. Adicionar `forecast_confidence.py` genérico (multi-cidade)
3. Atualizar `live_bot.py` para suportar dual strategy
4. Calibrar thresholds para dual strategy por cidade

**Risco:**
- Aumenta complexidade
- Dual strategy precisa de validação em Dallas/Ankara

### Opção B: Manter Estratégia Simples, Melhorar Genérico

**Vantagens:**
- Mantém simplicidade
- Fácil debug e manutenção
- SingleEntry já validada em todas as cidades
- Menos risco de regressão

**Mudanças:**
1. Otimizar `predictor.py` com features avançadas do IRIS
2. Adicionar stop-loss avançado (já implementado)
3. Melhorar display e logging
4. Adicionar monitoring e alertas

**Risco:**
- Perde oportunidade de entrada antecipada (forecast early)

### Opção C: Híbrido - SingleEntry Genérico + Opcional Dual

**Vantagens:**
- SingleEntry simples como default (já validado)
- Dual strategy opcional para cidades com bons dados de forecast
- Flexível para testar A/B

**Mudanças:**
1. Adicionar `dual_strategy.py` genérico
2. Adicionar parâmetro `strategy: single|dual` em `cities/config.py`
3. Atualizar `live_bot.py` para usar a estratégia configurada
4. Calibrar thresholds por cidade e estratégia

**Risco:**
- Complexidade moderada
- Precisa de validação cuidadosa

---

## 📋 Plano de Integração Recomendado

### Fase 1: Harmonização de Estruturas (1-2 dias)

**Objetivo:** Alinhar arquitetura mantendo genérico

1. **Mapear componentes IRIS → MULTI-CITY:**
   ```
   munich_model.py → predictor.py (já similar)
   munich_weather.py → weather.py (já similar)
   munich_phased_entry.py → phased_entry.py (já similar)
   munich_dual_strategy.py → phased_entry.py (NOVO - adicionar)
   munich_forecast_confidence.py → forecast_confidence.py (NOVO - adicionar)
   munich_live_bot.py → live_bot.py (já similar, mas adicionar dual)
   ```

2. **Adicionar componentes NOVOS:**
   - `forecast_confidence.py` (genérico, multi-cidade)
   - `dual_strategy.py` (integrado em `phased_entry.py`)
   - `single_entry.py` (separar do phased_entry.py)

### Fase 2: Integração de Dual Strategy (2-3 dias)

**Objetivo:** Adicionar dual strategy mantendo genérico

1. **Converter `munich_dual_strategy.py` para genérico:**
   - Remover referências a Munique específicas
   - Adicionar parâmetros de cidade
   - Usar `forecast_confidence.py` genérico

2. **Integrar em `phased_entry.py`:**
   - Adicionar `DualStrategy` como opção
   - Manter `SingleEntry` como default

3. **Atualizar `cities/config.py`:**
   - Adicionar `strategy: single|dual` por cidade
   - Adicionar parâmetros de dual por cidade

4. **Atualizar `live_bot.py`:**
   - Suportar ambas as estratégias
   - Logging diferente para cada estratégia

### Fase 3: Validação e Calibração (3-5 dias)

**Objetivo:** Validar em todas as cidades

1. **Testar SingleEntry (já validado):**
   - Dallas: ✅ (win=96.2%, ROI=+79.5%)
   - Ankara: ✅ (win=89.9%, ROI=+106.8%)
   - Munique: ✅ (win=~90%, ROI=~70%)

2. **Testar Dual Strategy (NOVO):**
   - Munique: Calibrar e validar
   - Dallas: Calibrar forecast confidence, validar
   - Ankara: Calibrar forecast confidence, validar

3. **Comparar resultados:**
   - ROI: Single vs Dual
   - Trades/ano: Single vs Dual
   - Win%: Single vs Dual
   - Complexidade: Vale a pena?

### Fase 4: Otimizações Avançadas (opcional, 5-7 dias)

**Objetivo:** Incorporar melhorias do IRIS mantendo genérico

1. **Forecast confidence avançada:**
   - Adicionar parâmetros por cidade em config
   - Calibrar accuracy por cidade/estação

2. **Stop-loss avançado:**
   - Já implementado em ambas versões
   - Validar por cidade

3. **Display melhorado:**
   - Incorporar melhorias do `munich_display.py`

4. **Alertas e monitoring:**
   - Integrar melhorias de telegram/alertas

---

## 🎯 Conclusão

### POLY-IRIS (ZAI) - Pontos Fortes
✅ Dual strategy inovador (Forecast Early + Peak Detection)
✅ Forecast confidence avançado
✅ Tudo otimizado para Munique
✅ Todos os bugs corrigidos

### POLY-IRIS (ZAI) - Pontos Fracos
❌ Hardcoded para Munique
❌ Difícil de adicionar cidades
❌ Complexo de manter
❌ Não suporta multi-cidade nativo

### POLY-MULTI-CITY - Pontos Fortes
✅ Arquitetura genérica multi-cidade
✅ Fácil adicionar novas cidades
✅ Simples de manter
✅ SingleEntry validado em 3 cidades
✅ Todos os bugs corrigidos
✅ Calibração automatizada por cidade

### POLY-MULTI-CITY - Pontos Fracos
❌ Sem dual strategy (perde oportunidade de entrada antecipada)
❌ Sem forecast confidence
❌ Menos "inteligente" que IRIS

---

## 🔮 Recomendação Final

**Opção C (Híbrido) é a melhor escolha:**

1. **Mantém SingleEntry genérico** (já validado em 3 cidades)
2. **Adiciona Dual Strategy opcional** (para quem quiser testar)
3. **Mantém arquitetura genérica multi-cidade**
4. **Adiciona forecast_confidence genérico** (pode ser usado por outras estratégias)

**Vantagens:**
- Flexibilidade: Single vs Dual por cidade
- Extensibilidade: Fácil adicionar cidades
- Validação: Single já validado, Dual opcional
- Manutenção: Código genérico é mais fácil de manter

**Razão:** Combina a simplicidade e validação do POLY-MULTI-CITY com a inovação inteligente do POLY-IRIS, mantendo a capacidade multi-cidade que é o diferencial do projeto.

---

## 📝 Próximos Passos

1. ✅ **Análise completa concluída**
2. ⏳ **Escolher plano de integração** (Recomendação: Opção C)
3. ⏳ **Implementar integração** (Fases 1-4)
4. ⏳ **Validar em todas as cidades**
5. ⏳ **Deploy em paper trading**
6. ⏳ **Monitorizar e iterar**

---

**Status da Análise:** ✅ COMPLETA
