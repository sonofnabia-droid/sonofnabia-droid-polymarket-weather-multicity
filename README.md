# Multi-City Peak Temperature Trading Bot

Sistema de trading automatizado para mercados de previsão de temperatura (Polymarket) com suporte a múltiplas cidades.

## 📋 Índice

- [Visão Geral](#visão-geral)
- [Arquitetura](#arquitetura)
- [Instalação](#instalação)
- [Configuração](#configuração)
- [Como Usar](#como-usar)
- [Estrutura do Projeto](#estrutura-do-projeto)
- [Treinamento de Modelos](#treinamento-de-modelos)
- [Calibração](#calibração)
- [Adicionando Novas Cidades](#adicionando-novas-cidades)
- [Troubleshooting](#troubleshooting)
- [Licença](#licença)

---

## Visão Geral

Este bot de trading identifica oportunidades de compra em mercados de "temperatura máxima diária" em várias cidades, usando machine learning para prever quando a temperatura atingirá o pico do dia.

### Cidades Suportadas

| Cidade | Aeroporto | Timezone | Trades/ano | Win% | ROI% |
|--------|-----------|----------|------------|------|------|
| **Munique** | EDDM | Europe/Berlin | ~250 | ~90% | ~70% |
| **Dallas** | KDFW | America/Chicago | 232 | 96.2% | +79.5% |
| **Ankara** | LTAC | Europe/Istanbul | 281 | 89.9% | +106.8% |

### Estratégia de Trading

- **Entrada**: SingleEntry - compra quando o modelo indica alta probabilidade de pico
- **Horário de trading**: 6h-21h (hora local de cada cidade)
- **Threshold mínimo**: Variável por cidade (0.35-0.55)
- **Parcela**: $5 por trade

---

## Arquitetura

```
┌─────────────────────────────────────────────────────────────┐
│                     Live Bot (Multi-Cidade)                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │   Dallas     │  │   Ankara     │  │   Munich     │      │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘      │
│         │                 │                 │                │
│         └─────────────────┴─────────────────┘                │
│                           │                                   │
│                    ┌──────▼───────┐                           │
│                    │ Predictor.py │                           │
│                    │  (Peak Detect)│                          │
│                    └──────┬───────┘                           │
│                           │                                   │
│                    ┌──────▼───────┐                           │
│                    │ Live Bot Loop │                          │
│                    │  (30s ticks)  │                          │
│                    └──────┬───────┘                           │
└───────────────────────────┼───────────────────────────────────┘
                            │
                    ┌───────▼────────┐
                    │ Polymarket CLOB│
                    │   (Paper/Real) │
                    └────────────────┘
```

### Componentes Principais

- **`predictor.py`**: Preditor multi-cidade genérico
- **`train.py`**: Treinamento de modelos LightGBM
- **`calibrate.py`**: Calibração de thresholds por cidade
- **`live_bot.py`**: Bot principal com suporte multi-cidade
- **`phased_entry.py`**: Estratégia de entrada SingleEntry
- **`backtester.py`**: Backtesting de estratégias
- **`cities/config.py`**: Configuração de cidades

---

## Instalação

### Pré-requisitos

- Python 3.12+
- pip

### Passos

1. **Clonar o repositório**
```bash
cd /path/to/your/projects
git clone <URL_DO_REPOSITORIO>
cd POLY-MULTI-CITY
```

2. **Criar ambiente virtual**
```bash
python3 -m venv venv
source venv/bin/activate  # Linux/Mac
# ou
venv\Scripts\activate  # Windows
```

3. **Instalar dependências**
```bash
pip install -r requirements.txt
```

### Dependências Principais

- `lightgbm`: Machine learning para predição de picos
- `pandas`: Manipulação de dados
- `numpy`: Computação numérica
- `polymarket-api`: Integração com Polymarket CLOB

---

## Configuração

### Variáveis de Ambiente

```bash
# Opcional - apenas para modo real
export POLY_PRIVATE_KEY="your_private_key_here"

# Opcional - para dados do Wunderground (não usado no sistema atual)
export WU_API_KEY="your_wunderground_api_key"
```

### Configuração de Cidades

Edita `cities/config.py` para ajustar parâmetros por cidade:

```python
"dallas": CityConfig(
    name="dallas",
    icao="KDFW",
    timezone="America/Chicago",
    # ... outros parâmetros
    threshold=0.350,      # Threshold de confiança (0-1)
    hour_min=17,          # Hora mínima para trading (6-21)
    max_per_trade=5.0,    # Valor máximo por trade ($)
)
```

---

## Como Usar

### Paper Trading (Recomendado para Testes)

**Uma cidade:**
```bash
python live_bot.py --cities dallas --mode single --run paper --interval 30
```

**Múltiplas cidades:**
```bash
python live_bot.py --cities dallas,ankara --mode single --run paper --interval 30
```

**Todas as cidades:**
```bash
python live_bot.py --cities munich,dallas,ankara --mode single --run paper --interval 30
```

### Real Trading

⚠️ **Aviso**: Use apenas após validar com sucesso em paper trading por 2+ semanas.

```bash
python live_bot.py --cities dallas,ankara --mode single --run real --interval 30
```

### Parâmetros

- `--cities`: Cidades separadas por vírgula
- `--mode`: Modo de entrada (apenas `single` implementado)
- `--run`: `paper` ou `real`
- `--interval`: Segundos entre ticks (padrão: 30)

### Monitorização

Logs são guardados em `live_bot_logs/{cidade}_{data}.json`:

```bash
# Ver estatísticas do dia
cat live_bot_logs/dallas_2024-04-29.json

# Ver logs em tempo real
tail -f live_bot_logs/dallas_2024-04-29.json
```

---

## Estrutura do Projeto

```
POLY-MULTI-CITY/
├── cities/
│   ├── __init__.py
│   └── config.py              # Configuração das cidades
├── historic/
│   ├── dallas.csv             # Dados históricos Dallas (231k linhas)
│   ├── ankara.csv             # Dados históricos Ankara (436k linhas)
│   └── munich.csv             # Dados históricos Munich
├── *_peak_model/              # Modelos treinados
│   ├── lgbm_peak.pkl          # Modelo LightGBM
│   └── peak_model_config.json # Configuração do modelo
├── live_bot_logs/             # Logs do bot (paper/real)
├── backtest_results/          # Resultados de backtest
├── predictor.py               # Preditor multi-cidade
├── train.py                   # Treinamento de modelos
├── calibrate.py               # Calibração de thresholds
├── live_bot.py                # Bot principal
├── phased_entry.py            # Estratégia de entrada
├── backtester.py              # Backtesting
├── polymarket_clob.py         # Integração Polymarket CLOB
├── weather.py                 # Dados meteorológicos
├── requirements.txt           # Dependências Python
└── README.md                  # Este ficheiro
```

---

## Treinamento de Modelos

### Preparar Dados Históricos

Os dados históricos devem estar no formato CSV com colunas:

```
date,time_local,timestamp_utc,temp_c,dewpt_c,humidity_pct,pressure_hpa,wind_dir_deg,wind_dir_card,wind_speed_kmh,wind_gust_kmh,precip_mm,condition,uv_index,visibility_km,sky_cover,heat_index_c,windchill_c
```

### Treinar Modelo para uma Cidade

```bash
python train.py --city dallas
```

**O que acontece:**
1. Carrega dados históricos da cidade
2. Extrai features (temperatura, umidade, pressão, etc.)
3. Treina modelo LightGBM com validação walk-forward
4. Guarda modelo em `{city}_peak_model/`
5. Gera `peak_model_config.json` com metadados

### Resultados Esperados

- **AUC**: > 0.95 (excelente discriminação)
- **Features**: 25 features principais
- **Validação**: Walk-forward por ano

---

## Calibração

### Calibrar Thresholds para uma Cidade

```bash
# Calibração rápida
python calibrate.py --city dallas --mode fast --years 3

# Calibração completa (recomendada)
python calibrate.py --city dallas --mode full --years 5
```

### Modos de Calibração

| Modo | Grid | Anos | Tempo |
|------|------|------|-------|
| `fast` | 10×10 | 3 | ~1 min |
| `standard` | 30×10 | 5 | ~3 min |
| `detailed` | 57×10 | 5 | ~8 min |
| `full` | 57×10 | 5 | ~10 min |

### Resultados da Calibração

A calibração gera 3 perfis recomendados:

| Perfil | Threshold | Hour Min | Trades/ano | Win% | ROI% |
|--------|-----------|----------|------------|------|------|
| 🛡 Conservador | 0.600 | 16h | 211 | 96.0% | +40.2% |
| ⚖ Balanceado | 0.350 | 17h | 232 | 96.2% | +79.5% |
| 🚀 Agressivo | 0.350 | 17h | 232 | 96.2% | +79.5% |

**Aplicar threshold ao config:**
```python
# cities/config.py
threshold=0.350,  # Balanceado
hour_min=17,
```

---

## Adicionando Novas Cidades

### 1. Obter Dados Históricos

Baixa dados do Wunderground ou Open-Meteo para o aeroporto desejado.

### 2. Adicionar Configuração em `cities/config.py`

```python
"novacidade": CityConfig(
    name="novacidade",
    icao="XXXX",                    # Código ICAO do aeroporto
    timezone="Europe/Lisbon",       # Timezone
    latitude=38.7,
    longitude=-9.1,
    polymarket_slug_pfx="highest-temperature-in-novacidade-on",
    wu_history_path=None,           # Ou caminho do WU
    csv_path="historic/novacidade.csv",
    model_dir="novacidade_peak_model",
    unit="celsius",
    temp_range=range(-5, 45),
    max_daily_loss=20.0,
    max_per_trade=5.0,
    extra_features=[],
    threshold=None,                # A calibrar
    hour_min=None,                 # A calibrar
    bot_timezone="Europe/Lisbon",
    climatology={
        1: 10.0, 2: 11.0, 3: 14.0, 4: 17.0, 5: 20.0, 6: 25.0,
        7: 28.0, 8: 28.0, 9: 24.0, 10: 19.0, 11: 14.0, 12: 11.0
    },
),
```

### 3. Treinar Modelo

```bash
python train.py --city novacidade
```

### 4. Calibrar Thresholds

```bash
python calibrate.py --city novacidade --mode full --years 5
```

### 5. Atualizar Config com Thresholds

Copia os valores recomendados da calibração para `cities/config.py`.

---

## Troubleshooting

### Erro: `name '_last_save_time' is not defined`

**Solução**: Já corrigido. O bug estava no `predictor.py` linha 415.

### Erro: `Mixed timezones detected`

**Causa**: CSV com timezones mistas (daylight saving).

**Solução**: Usa `pd.to_datetime(..., utc=True)` ao carregar o CSV.

### Erro: `No module named 'lightgbm'`

**Solução**:
```bash
pip install lightgbm
```

### Win% muito baixa (< 70%)

**Possíveis causas**:
1. Dados futuros no CSV (data leakage)
2. Modelo overfitado
3. Threshold muito alto/baixo

**Verificação**:
```bash
# Verificar datas no CSV
tail historic/dallas.csv | cut -d',' -f1

# Retreinar modelo
python train.py --city dallas --clean
```

### Bot não está a fazer trades

**Verificações**:
1. Horário atual está dentro de `day_start` a `day_end`?
2. `p_ensemble` está acima do `threshold`?
3. Logs em `live_bot_logs/` para ver erros

```bash
# Ver logs recentes
cat live_bot_logs/dallas_$(date +%Y-%m-%d).json | tail -20
```

---

## Referências

### Documentação

- `PROGRESSO_ATUALIZADO.md` - Histórico de desenvolvimento
- `ESTADO_FINAL.md` - Estado do sistema
- `architecture.md` - Arquitetura técnica

### Scripts Úteis

- `clean_future_data.py` - Limpa dados de 2026
- `check_balance.py` - Verifica saldo na Polymarket
- `test_clob_dryrun.py` - Teste do CLOB sem trades reais

---

## Licença

© 2024 Multi-City Peak Trading Bot

---

## Suporte

Para questões ou bugs, verifica:
1. Logs em `live_bot_logs/`
2. Configuração em `cities/config.py`
3. Documentação nos ficheiros `.md`

**Notas Importantes:**
- Sempre testa em paper trading antes de usar real money
- Valida por 2+ semanas antes de confiar no sistema
- Monitoriza logs regularmente para detectar anomalias
- Mantém backups dos modelos treinados
