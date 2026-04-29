# MULTI-CITY EXPANSION PLAN — Munich + Madrid

> Documento de planeamento para a expansão do sistema POLY-IRIS de 1 cidade para multi-cidade.
> Decisões tomadas em sessão de brainstorming (Apr 26, 2026).

---

## Decisões arquiteturais

### Arquitetura de bot
- **1 bot multi-cidade** (não 2 bots separados)
- **Loop sequencial** dentro do bot (city A → city B → sleep)
- `try/except` por cidade para failure isolation
- CLI: `python live_bot.py --cities munich,madrid`

### Bankroll
- **Separado por cidade** (`max_daily_loss` em CityConfig)
- Cada cidade tem o seu limite independente
- Quando escalar para 4+ cidades, reconsiderar bankroll global com sub-limites

### Modelos
- **Mesma arquitetura LightGBM** para todas as cidades
- **Features genéricas** (25 actuais) como base universal
- **Features específicas** opcionais por cidade (`extra_features` em CityConfig)
- Disciplina: feature específica só após passar 3 testes:
  1. Hipótese física clara
  2. Disponível em histórico + live
  3. Importância empírica top-15

---

## Cidades alvo

### Munich (já em paper)
- ICAO: EDDM
- Timezone: Europe/Berlin
- AUC actual: 0.954
- Config calibrado: thr=0.55, hour_min=15h
- **NÃO MEXER durante refactor**

### Madrid (a adicionar)
- ICAO: LEMD (Adolfo Suárez Madrid-Barajas)
- Timezone: Europe/Madrid
- Volume Polymarket: ~$130-200k/dia (excelente)
- Resolution source: WU em °C
- AUC esperada: 0.93-0.96

---

## Estrutura de ficheiros final

```
POLY-IRIS/
├── cities/
│   ├── __init__.py
│   ├── config.py              # CITIES dict, CityConfig dataclass
│   ├── munich_features.py     # MUNICH_SPECIFIC_FEATURES (vazio inicial)
│   └── madrid_features.py     # MADRID_SPECIFIC_FEATURES (vazio inicial)
├── historic/
│   ├── munich.csv             # já tens
│   └── madrid.csv             # a recolher
├── munich_peak_model/         # já tens (renomear?)
├── madrid_peak_model/         # a treinar
├── train.py                   # ex munich_train.py + --city
├── backtester.py              # ex munich_backtester.py + --city
├── calibrate.py               # ex munich_calibrate.py + --city
├── live_bot.py                # ex munich_live_bot.py + --cities
├── weather.py                 # ex munich_weather.py, recebe city
├── display.py                 # multi-cidade
├── predictor.py               # ex munich_model.py, genérico
├── phased_entry.py            # já genérico
├── polymarket_clob.py         # já genérico
└── tg.py                      # já genérico
```

---

## Refactor em 5 sprints

### Sprint 1 — Munich genérico (5 dias)

Objectivo: Munich funciona com código novo, idêntico ao actual.

#### 1.1 Criar `cities/config.py`
```python
@dataclass
class CityConfig:
    name: str
    icao: str
    timezone: str
    latitude: float
    longitude: float
    polymarket_slug_pfx: str
    wu_history_path: str
    csv_path: str
    model_dir: str
    unit: str
    temp_range: range
    max_daily_loss: float
    max_per_trade: float
    extra_features: list[str]
    threshold: float | None
    hour_min: int | None

CITIES = {
    "munich": CityConfig(
        name="munich",
        icao="EDDM",
        timezone="Europe/Berlin",
        latitude=48.354, longitude=11.786,
        polymarket_slug_pfx="highest-temperature-in-munich-on",
        wu_history_path="de/munich/EDDM",
        csv_path="historic/munich.csv",
        model_dir="munich_peak_model",
        unit="celsius",
        temp_range=range(-5, 45),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=0.55,
        hour_min=15,
    ),
    "madrid": CityConfig(
        # ... preenchido depois
    ),
}

def get_city(name: str) -> CityConfig:
    if name not in CITIES:
        raise ValueError(f"Cidade desconhecida: {name}")
    return CITIES[name]
```

**Teste**: `python -c "from cities.config import get_city; print(get_city('munich').icao)"` → "EDDM"

#### 1.2 Refactor `weather.py` (era munich_weather.py)
- `bootstrap_today()` → aceita `city: CityConfig`
- `make_wu_session()` → URL construído a partir de `city.wu_history_path`
- `forecasts_agree()` → genérico, sem mudança

#### 1.3 Refactor `predictor.py` (era munich_model.py)
- `build_features(city, ...)` → considera `city.extra_features`
- `set_seasonal_prior()` → guarda por cidade

#### 1.4 Refactor `train.py`
- CLI: `python train.py --city munich`
- Carrega config da cidade, treina, guarda em `city.model_dir`

#### 1.5 Refactor `backtester.py`, `calibrate.py`
- CLI: `python backtester.py --city munich --years 5 ...`

#### 1.6 Refactor `live_bot.py`
- CLI: `python live_bot.py --cities munich --run paper`
- Loop principal:
  ```python
  cities = [get_city(c) for c in args.cities.split(",")]
  while True:
      for city in cities:
          try:
              tick(city, ...)
          except Exception as e:
              logger.error(f"[{city.name}] tick failed: {e}", exc_info=True)
      time.sleep(args.interval)
  ```

#### 1.7 Validação de regressão Munich
- Correr `python live_bot.py --cities munich` deve produzir output idêntico ao `munich_live_bot.py`
- Backtest Munich antes vs depois: AUC igual, win-rate igual, ROI igual
- **Critério de aceitação**: Munich em paper sem diferenças observáveis

---

### Sprint 2 — Madrid baseline (3 dias)

#### 2.1 Recolher dados Madrid

Open-Meteo Archive API (grátis, 25+ anos):
```python
url = "https://archive-api.open-meteo.com/v1/archive"
params = {
    "latitude": 40.466,
    "longitude": -3.566,
    "start_date": "2001-01-01",
    "end_date": "2025-12-31",
    "hourly": "temperature_2m,relative_humidity_2m,wind_speed_10m,"
              "wind_direction_10m,pressure_msl,cloud_cover,precipitation",
    "timezone": "Europe/Madrid",
}
```

Output esperado: `historic/madrid.csv` com colunas idênticas a `munich.csv`.

#### 2.2 Treinar modelo Madrid

```bash
python train.py --city madrid
```

- Mesmas 25 features genéricas
- LightGBM com mesmos hyperparameters de Munich
- AUC esperada walk-forward: 0.93-0.96

#### 2.3 Calibrar Madrid

```bash
python calibrate.py --city madrid --years 5 --mode full --metric outcome
```

- Esperado: thr ≈ 0.50-0.60, hour_min ≈ 14-16h
- **Madrid pode preferir hour_min mais cedo** (verão chega ao pico mais cedo no clima continental)
- Aplicar config recomendado em `cities/config.py`

#### 2.4 Backtest Madrid

```bash
python backtester.py --city madrid --years 5 --ordertype percent --bet 2
```

- Critérios de sucesso:
  - Win-rate ≥ 80%
  - EV/$ ≥ +5%
  - Trades/ano ≥ 80
  - Edge POSITIVA na diagnose económica

---

### Sprint 3 — Bot multi-cidade (2 dias)

#### 3.1 Display multi-cidade

Opção C escolhida: empilhado vertical.

```
══ Munich ════════════════════════════════════════
[curva temperatura Munich]
[posição Munich]
[mercado Munich]

══ Madrid ════════════════════════════════════════
[curva temperatura Madrid]
[posição Madrid]
[mercado Madrid]
```

`display.py` recebe lista de `CityState` objects.

#### 3.2 Estado por cidade

Estrutura `CityState` que mantém:
- `series_today` (temperatura observada hoje)
- `slots_so_far` (slots actuais)
- `market` (Polymarket data)
- `entry` (SingleEntry instance)
- `daily_stats` (stats do dia)
- `clob` (ClobClient com seu max_daily_loss)

#### 3.3 Validação

- Munich + Madrid em paper, 24h sem crashes
- Erros numa cidade não afectam outra
- Display claro e legível

---

### Sprint 4 — Features específicas (FUTURO, opcional)

**SÓ FAZER** depois de Sprint 3 estável e Madrid em paper há ≥ 4 semanas.

#### 4.1 Análise de residuals
Para cada cidade, identificar dias onde modelo errou mais:
- Há padrão climático?
- Há features genéricas em falta?

#### 4.2 Candidatas Madrid
- `saharan_air_intrusion`: HRR < 25% + wind_dir SE + dust
- `levante_wind`: wind_dir E + 80-90% RH (vento marítimo)
- `heat_wave_indicator`: 7-day rolling max > climatology + 5°C
- `urban_heat_island_factor`: hora + month interaction

#### 4.3 Candidatas Munich
- `foehn_indicator`: wind_dir S + temp_jump_2h > 5°C + low humidity
- `alpine_lee_wave`: pressure_change_3h + wind speed

#### 4.4 Validação por feature
Para cada candidata:
1. Implementar em `build_features` com `if city.name == "...": ...`
2. Retreinar modelo dessa cidade
3. Comparar AUC walk-forward antes vs depois
4. Manter SE AUC sobe ≥ 0.005 E feature_importance > top-15

---

## Cronograma realista

Assumindo trabalho concentrado em fins-de-semana / horas livres:

| Semana | Sprint | Status Munich |
|--------|--------|----------------|
| 1 | Sprint 1 (refactor) | Continua em paper inalterado |
| 2 | Sprint 1 (cont.) + validação | Continua em paper |
| 3 | Sprint 2 (Madrid baseline) | Continua em paper |
| 4 | Sprint 3 (multi-cidade) | Munich + Madrid em paper paralelo |
| 5+ | Observação 4-8 semanas | Acumular dados reais |
| ... | Sprint 4 (features específicas) | Só se necessário |

---

## Risk register

| Risco | Probabilidade | Mitigação |
|-------|---------------|-----------|
| Refactor parte Munich | Média | Validação regressão obrigatória cada sprint |
| Madrid AUC < 0.90 | Baixa | Mais features genéricas? Investigar dados |
| Tampering em Madrid (caso Paris) | Baixa-média | Detector de anomalias futuro |
| Falha API Open-Meteo histórico | Baixa | Fallback NOAA GHCN |
| Polymarket muda formato slug Madrid | Baixa | Detecção automática via Gamma API |
| Bankroll Madrid esgota num dia mau | Média | max_daily_loss=$20 limita exposição |

---

## Métricas de sucesso

### Sprint 1 (refactor)
- ✅ Munich em paper produz output idêntico antes/depois
- ✅ Zero divergências em backtests
- ✅ Código mais limpo (linhas reduzidas, mais reuse)

### Sprint 2 (Madrid baseline)
- ✅ AUC Madrid walk-forward ≥ 0.93
- ✅ Backtest Madrid: edge positiva (>+5%/$)
- ✅ Calibração estável (vizinhos no grid não caem >5pp)

### Sprint 3 (multi-cidade)
- ✅ Bot Munich+Madrid corre 24h sem crashes
- ✅ Display claro e útil
- ✅ Erros isolados (Madrid down ≠ Munich down)

### Final
- ✅ 4-8 semanas de paper duplo
- ✅ Total trades/semana 4-6 (vs 2-3 só Munich)
- ✅ Win-rate combined ≥ 85%

---

## Decisões pendentes (futuras)

- [ ] Quando passar Madrid de paper → real?
- [ ] Quando adicionar 3ª cidade (Atlanta? Shanghai?)?
- [ ] Quando consolidar bankroll global vs separado?
- [ ] Implementar Kelly fractional?
- [ ] Detector de anomalias (anti-tampering)?

---

## Notas operacionais

### Comandos finais (depois do refactor)

```bash
# Treino
python train.py --city munich
python train.py --city madrid

# Backtest
python backtester.py --city munich --years 5 --ordertype percent --bet 2
python backtester.py --city madrid --years 5 --ordertype percent --bet 2

# Calibração
python calibrate.py --city munich --years 5 --mode full --metric outcome
python calibrate.py --city madrid --years 5 --mode full --metric outcome

# Live bot multi-cidade
python live_bot.py --cities munich,madrid --mode single --run paper
python live_bot.py --cities munich,madrid --mode single --run real
```

### Variáveis de ambiente

Já existentes (Munich):
```
POLY_PRIVATE_KEY
POLY_FUNDER
POLY_SIGNATURE_TYPE=2
POLY_MAX_DAILY_LOSS=20
WU_API_KEY
TELEGRAM_TOKEN
TELEGRAM_CHAT_ID
```

Não mudam — `max_daily_loss` agora vem de `cities/config.py` por cidade. `POLY_MAX_DAILY_LOSS` continua a ser fallback global.

---

**Documento criado**: 2026-04-26
**Próxima revisão**: após Sprint 1 completo
