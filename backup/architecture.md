# POLY-IRIS — Munich Peak Temperature Trading Bot

> Arquitetura, estratégia e operação. Última atualização: 2026-04-25

## TL;DR

Bot de trading automático que compra contratos binários no [Polymarket](https://polymarket.com) sobre **a temperatura máxima diária de Munich (EDDM Airport)**. Usa um modelo LightGBM treinado em 25 anos de dados meteorológicos para detectar quando o pico do dia já ocorreu, comprando o bracket correspondente no momento certo.

**Estado atual**: 5+ iterações de bug fixing, modelo LightGBM puro (AUC 0.954), thresholds calibrados, stop-loss implementado, em **paper trading** desde Abril 2026.

---

## 1. Problema de mercado

O Polymarket cria diariamente um mercado de "Highest temperature in Munich on [data]" com brackets de 1°C. Cada bracket é um contrato binário YES/NO:

- "21°C" YES → ganha $1 se a temperatura máxima do dia for exactamente 21°C
- "22°C or higher" YES → ganha $1 se a temperatura máxima for ≥ 22°C
- "12°C or below" YES → ganha $1 se a temperatura máxima for ≤ 12°C

**Mecânica de preço**: Cada YES tem ask (compra) e bid (venda), em centavos. Se compras 1 share a 0.65, e ganha, recebes $1 → lucro de $0.35 (54% de retorno). Se perde, perdes os 0.65.

**Resolução**: à meia-noite do dia, baseado em dados oficiais (geralmente Wunderground EDDM).

---

## 2. Insight central — porque pode ser lucrativo

A temperatura máxima diária em Munich é **previsível com algumas horas de antecedência** se observarmos a curva da manhã/tarde:

- Subida monótona até atingir um pico (geralmente 14h-16h)
- Após o pico, descida lenta
- O `running_max` (máximo até agora) é um excelente proxy do pico final, **especialmente após 14-15h**

O nosso modelo aprende a **detectar quando o pico já passou** olhando a 25 features (curva, derivadas, agregados horários, climatologia). Quando convicto (P > threshold), compra o bracket correspondente ao `running_max` atual.

**Valor esperado positivo** existe quando:

```
P(running_max é o pico final) × payoff > custo_total
P × (1/ask - 1) - (1-P) × 1 > 0
```

Para `ask = 0.65`, precisas de `P > 0.65` para ter EV positivo. O modelo dispara quando isto é verdadeiro com margem.

---

## 3. Arquitetura

### Diagrama

```
┌─────────────────┐     ┌─────────────────┐
│ Wunderground    │     │ Open-Meteo      │
│ EDDM Airport    │     │ Munich          │
│ (temp, humid)   │     │ (forecast)      │
└────────┬────────┘     └────────┬────────┘
         │ 30/30min              │ daily
         ▼                       ▼
    ┌─────────────────────────────────┐
    │ munich_weather.py               │
    │ - bootstrap (manhã do dia)      │
    │ - fetch contínuo                │
    │ - cloud_from_series             │
    │ - forecasts_agree (consenso)    │
    └────────┬────────────────────────┘
             │
             ▼
    ┌─────────────────────────────────┐
    │ munich_model.py                 │
    │ - build_features() — 25 vars    │
    │ - predict_ensemble() = LGBM     │
    │ - 0..1 → P(pico já ocorreu)     │
    └────────┬────────────────────────┘
             │
             ▼
    ┌─────────────────────────────────┐
    │ munich_phased_entry.py          │
    │ - SingleEntry (estratégia)      │
    │   - threshold = 0.55            │
    │   - hour_min = 15               │
    │   - stop_loss_delta = 1.0°C     │
    └────────┬────────────────────────┘
             │
             ▼
    ┌─────────────────────────────────┐
    │ munich_live_bot.py — orquestrador│
    │ - tick a cada 30 segundos       │
    │ - paper ou real                 │
    └────────┬───────────┬────────────┘
             │           │
             ▼           ▼
    ┌──────────────┐ ┌────────────┐
    │ polymarket_  │ │ tg.py      │
    │ clob.py      │ │ Telegram   │
    │ (CLOB API)   │ │ alerts     │
    └──────────────┘ └────────────┘
```

### Ficheiros e responsabilidades

| Ficheiro | Responsabilidade |
|----------|-----------------|
| `munich_config.py` | Constantes: ENSEMBLE_WEIGHTS, paths, smart_sleep |
| `munich_train.py` | Treina o modelo LightGBM com walk-forward AUC |
| `munich_train_optuna.py` | Versão alternativa com hyperparameter tuning (não usada por defeito) |
| `munich_model.py` | `build_features()`, `predict_ensemble()` (LGBM puro) |
| `munich_weather.py` | Fetch WU + Open-Meteo, bootstrap, consenso forecasts |
| `munich_phased_entry.py` | Estratégias `SingleEntry` (ativa) e `PhasedEntry` (legacy) |
| `munich_backtester.py` | Backtest histórico com `SimulatedMarket` climatológico |
| `munich_calibrate.py` | Grid search de thresholds, recomenda 3 perfis |
| `munich_live_bot.py` | Orquestrador principal — tick, decisão, execução |
| `munich_display.py` | Dashboard ASCII no terminal |
| `polymarket_clob.py` | Cliente CLOB (compra, venda, posições) |
| `tg.py` | Notificações Telegram |

---

## 4. O modelo

### Features (25 inputs)

Geradas em cada slot de 30 minutos a partir do início do dia:

**Temperatura atual & curva**:
- `temp_c`, `temp_lag_1`, `temp_lag_2`, `temp_lag_3` (atual e -30/60/90min)
- `delta_30`, `delta_60` (variação)
- `running_max`, `running_max_age` (pico até agora e há quanto tempo)

**Hora & climatologia**:
- `hour`, `hour_sin`, `hour_cos` (cíclico)
- `month`, `month_sin`, `month_cos`
- `seasonal_prior` (P pico baseado só no mês — baseline)

**Meteorológicas**:
- `humidity_pct`, `dewpoint_c`, `pressure_hpa`
- `wind_speed_kmh`, `cloud_cover`
- `uv_index_avg_morning` (proxy de insolação)

**Tendência**:
- `temp_above_morning_avg` (sinal de aquecimento)
- `slots_since_subida` (quanto tempo a subir)

### Treino

```bash
python munich_train.py
```

- Dataset: 2001-2026 (9168 dias × ~32 slots = 289k linhas)
- Train/test: split temporal — **2001-2020 treino, 2021-2026 walk-forward**
- AUC walk-forward (out-of-sample): **0.9540**
- AUC in-sample: 0.9653 → gap 1.1pp (modelo bem regularizado, não overfit)

### Hiperparâmetros (LightGBM)

```python
n_estimators   = 600
learning_rate  = 0.02
max_depth      = 6
num_leaves     = 60
+ defaults LightGBM
```

Estes valores foram escolhidos por bom-senso. Optuna pode otimizar (não está em uso — ver `munich_train_optuna.py`).

### Ensemble (legacy, hoje vestigial)

Antes da iteração 4 (Abril 2026), o `predict_ensemble()` combinava:
- LightGBM (peso 0.68)
- XGBoost (peso 0.0 — descartado por redundância)
- StreamingPeakDetector z-score (peso 0.32 — descartado por sinal **invertido** para entrada)

A mistura gerava um plateau artificial em P~0.75 mesmo quando LGBM dizia 0.95. **Solução: LightGBM puro** (peso 1.0). Dimensionalidade reduzida, decisão mais clara, ROI melhor.

---

## 5. Estratégia (SingleEntry)

### Parâmetros calibrados (Abril 2026)

```python
threshold       = 0.55    # ponto de equilíbrio volume vs precision
hour_min        = 15      # só entrar a partir das 15h (Munich CET/CEST)
stop_loss_delta = 1.0     # vender se temp >= bracket_hi + 1°C
parcel_size     = 5.0     # $5 USDC por trade
```

Calibrado com `munich_calibrate.py --metric outcome` (métrica honesta sem preços simulados).
Critério: win-rate × log(volume), maximizando qualidade do sinal sem depender do SimulatedMarket.

### Lógica de entrada

```
A cada 30 segundos:
  1. Fetch nova observação WU
  2. Atualiza features
  3. predict_ensemble() → P(pico já ocorreu)
  4. Se P >= threshold AND hour >= hour_min AND posição ainda não aberta:
     - Identifica bracket cujo intervalo contém running_max
     - Lê ask actual no Polymarket
     - Compra YES (clob.buy_yes())
     - Marca SingleEntry como bought
```

### Stop-loss (NOVO 2026-04)

```
A cada tick após compra:
  Se temperature_actual >= bracket_hi + stop_loss_delta:
    - Bracket comprado está "morto"
    - Lê bid corrente do bracket
    - Vende YES (clob.sell_yes())
    - Marca SingleEntry como sold_by_stop
    - Notifica Telegram
```

**Exemplo**: Comprei YES @ 0.65 no bracket "21°C" às 15h. Às 16:30 a temperatura sobe a 22°C → trigger (22 >= 21+1). Vendo ao bid corrente (~0.10) → recupero $0.83 dos $5. Sem stop-loss perderia os $5 inteiros.

### Resolução (final do dia)

- À meia-noite, Polymarket resolve o mercado
- `clob.positions` reconcilia: posições abertas → won/lost
- PnL calculado: `won × $1 − pago` ou `−pago`
- Resumo enviado por Telegram
- Recomeça no dia seguinte

---

## 6. SimulatedMarket (apenas para backtest)

O backtester precisa de "asks históricos" do Polymarket que **não existem** (a API só dá granularidade ≥12h para mercados resolvidos). O `SimulatedMarket` v2 inventa preços plausíveis baseados em **climatologia**:

```python
ask = baseline_climatology(hour, dist_to_running_max) + model_nudge + noise

# baseline_climatology(): hora dominante
# - 6h:  bracket central ~35¢ (muita incerteza)
# - 14h: bracket central ~62¢
# - 20h: bracket central ~90¢ (consolidado)

# model_nudge: ±5¢ máximo (modelo influencia ligeiramente)
# noise: gauss(0, 5¢)
```

**Importante**: o `SimulatedMarket` é **só para backtest**. O bot live usa **dados reais** do Polymarket via API.

---

## 7. Operação

### Comandos principais

```bash
# Treinar/retreinar modelo
python munich_train.py

# Backtest histórico
python munich_backtester.py --mode single --years 5 --ordertype percent --bet 2

# Calibrar thresholds (10min)
python munich_calibrate.py --years 5 --mode full --realistic

# Live bot (paper)
python munich_live_bot.py --mode single --run paper

# Live bot (real — precisa POLY_PRIVATE_KEY)
python munich_live_bot.py --mode single --run real
```

### Variáveis de ambiente

```bash
# Telegram (opcional)
export TELEGRAM_TOKEN="..."
export TELEGRAM_CHAT_ID="..."

# Wunderground (necessário)
export WU_API_KEY="..."

# Polymarket (necessário para --run real)
export POLY_PRIVATE_KEY="0x..."
export POLY_FUNDER="0x..."
export POLY_MAX_DAILY_LOSS=50    # limite seguro
```

### Modos

- `--run paper`: simula tudo, $0 em risco, registo completo
- `--run real`: ordens reais no Polymarket (USDC)

### Métricas no display

- **P(pico já ocorreu)**: probabilidade do running_max ser o pico final
- **Threshold**: `0.68` — barra para disparar
- **Hour_min**: `15h` — só entrar a partir desta hora
- **Running max**: máximo até agora e quando ocorreu
- **Forecast Dual**: WU vs Open-Meteo, consenso só se idênticos
- **Mercado**: brackets, asks/bids, volume

---

## 8. Resultados esperados (calibrados em backtest)

Com **BALANCEADO** (`thr=0.55 @ 15h`):

| Métrica | Valor |
|---------|-------|
| Trades/ano | ~110 |
| Win-rate | ~89% |
| Premature rate | ~40% |
| Lag mediano | +0.5h |
| Outcome score | 179 |
| Profile risk | médio |

**Caveats**:
- Calibrado em dados in-sample (modelo viu 2001-2025) → estimativa otimista
- Métrica `outcome` ignora ROI em $ (não temos asks históricos reais)
- Win-rate em paper deve ser observado por 4-6 semanas antes de decisões
- **Premature 40%** significa que ~44 trades/ano entram antes do pico — destes, alguns podem disparar stop-loss em produção

---

## 9. Histórico de bugs corrigidos (2026-04)

Lista resumida das correções aplicadas:

1. **Modelo**: `init/update_history_max` em falta, threshold hardcoded, `temp_lag_3` em falta, AUC fake, ensemble redundante (XGB descartado, z-score invertido)
2. **Backtester**: `json` não importado, RESUMO TOTAL não acumulava, PnL hardcoded, SimulatedMarket circular
3. **Estratégia**: PhasedEntry comprava múltiplas parcelas/slot, fake Sharpe ratio
4. **Calibrador**: Optuna não otimizava, AUC in-sample em vez de walk-forward, bracket matching falhava em dias frios (rmax<5°C)
5. **SimulatedMarket v2**: substituído por climatológico (hora + distância) em vez de proxy do modelo
6. **SingleEntry**: stop-loss por temperatura, hour_min filter, threshold calibrado
7. **Live bot**: import robusto do tg.py, threshold dinâmico no display, `cloud_from_series` argumentos
8. **Calibrador `--metric outcome`**: nova métrica honesta que ignora preços simulados, optimiza `win_pct × log10(1 + trades/ano)`. Permite calibrar configs sem enviesar pelo SimulatedMarket.
9. **Threshold sazonal estrito**: `forecasts_agree` só valida consenso se WU e OM forem exactamente iguais (em vez de tolerar diff ≤ 1°C).

---

## 10. Próximos passos

### Curto prazo (semanas)

- [ ] Acumular 30+ trades em paper para validar win-rate real
- [ ] Comparar asks reais do Polymarket vs SimulatedMarket
- [ ] Detectar derivas (modelo a falhar em dias específicos)

### Médio prazo (meses)

- [ ] Recolher histórico de preços Polymarket para substituir SimulatedMarket
- [ ] Testar Optuna se win-rate observado < 88%
- [ ] Considerar features adicionais (jet stream, anomalias térmicas)

### Longo prazo (após validação)

- [ ] Escalar para `--run real` com bankroll pequeno
- [ ] Multi-cidade (Berlim, Frankfurt, Hamburgo)
- [ ] Estratégia de hedge cross-bracket

---

## Apêndice — Decisões de design

### Por que LightGBM puro?

XGBoost tinha desempenho equivalente (correlação 0.97 com LGBM). Z-score detector tinha sinal **invertido** para entrada (slope_signal positivo = pós-pico). Combinar diluía. LGBM sozinho dá decisões mais nítidas.

### Por que `hour_min = 15`?

O pico em Munich ocorre maioritariamente entre 13h-16h. Antes das 15h há demasiada ambiguidade — o modelo pode ter convicção alta (P>0.7) mas o pico real ainda virá. Filtro reduz drasticamente premature_pct sem afetar muito win-rate.

### Por que `stop_loss_delta = 1.0`?

Se temperatura sobe 1°C acima do bracket comprado, é praticamente certo que esse bracket não vence. Vender ao bid (mesmo que baixo, ~10¢) recupera capital que de outra forma seria perdido inteiramente. Delta=0.5 dispararia falsos positivos (volatilidade normal). Delta=2.0 chega tarde demais.

### Por que paper antes de real?

Mesmo com AUC 0.954 e backtest robusto, há dimensões que só a operação real revela: latência da API, comportamento real dos asks vs simulados, qualidade das observações WU em condições adversas. 4-8 semanas em paper são essenciais.

---

*Marco · POLY-IRIS · 2026*