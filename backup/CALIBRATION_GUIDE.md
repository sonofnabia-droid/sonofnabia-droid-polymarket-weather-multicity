# Guia de Calibração de Estratégias

**Data:** 2026-04-29
**Status:** Scripts de calibração prontos

---

## Scripts Disponíveis

### 1. `calibrate_dual.py` - Calibração Dual Strategy

Optimiza parâmetros:
- `fc_hour_min`, `fc_hour_max` - Janela Forecast Early
- `fc_p_min` - Threshold P(forecast correct)
- `fc_ev_margin` - Margem EV positiva
- `pk_threshold` - Threshold P(peak)
- `pk_hour_min` - Hora mínima Peak Detection
- `stop_loss_delta` - Delta de stop-loss

**Uso:**
```bash
# Fast mode (~30s, 9 combos)
python calibrate_dual.py --city munich --mode fast --years 1

# Standard mode (~2min, 54 combos)
python calibrate_dual.py --city munich --mode standard --years 3

# Detailed mode (~10min, 288 combos)
python calibrate_dual.py --city munich --mode detailed --years 3
```

**Notas:**
- Requer cidade com WU (Munich) para funcionar corretamente
- Para Dallas e Ankara, use defaults sem Forecast Early

---

### 2. `calibrate_phased.py` - Calibração Phased Entry

Optimiza parâmetros:
- `thr_p1_min`, `thr_p1_max` - Range P1 (value early)
- `thr_p2` - Threshold P2 (dupla confirmação)
- `thr_p3` - Threshold P3 (alta confiança)
- `p1_hour_min`, `p1_hour_max` - Janela P1

**Uso:**
```bash
# Fast mode (~20s, 9 combos)
python calibrate_phased.py --city munich --mode fast --years 1

# Standard mode (~1min, 81 combos)
python calibrate_phased.py --city munich --mode standard --years 3

# Detailed mode (~5min, 450 combos)
python calibrate_phased.py --city munich --mode detailed --years 3
```

**Notas:**
- Usa PhasedEntrySimple para calibração (ignora restrições market_ok/fc_ok)
- Para produção, usar PhasedEntry completo com restrições

---

### 3. `backtest_compare.py` - Backtest Comparativo

Compara Single vs Dual vs Phased em paralelo.

**Uso:**
```bash
# Usar defaults da cidade
python backtest_compare.py --city munich --years 3

# Customizar parâmetros
python backtest_compare.py --city munich --years 3 \
  --single-threshold 0.45 \
  --dual-params '{"fc_p_min":0.65,"pk_threshold":0.55}' \
  --phased-params '{"thr_p2":0.5,"thr_p3":0.65}'

# Todas as cidades
python backtest_compare.py --all --years 3
```

**Métricas:**
- Trd/y - Trades por ano
- Win% - Win rate
- ROI% - Return on Investment (SimulatedMarket)
- Score - outcome_score (win% × log(volume))
- Sharpe - Sharpe ratio anualizado
- Sortino - Sortino ratio anualizado
- MaxDD - Máximo drawdown
- LagMed - Mediana do lag (horas antes do pico)

---

## Recomendações de Calibração

### Munich (com WU)

**SingleEntry** (já calibrado):
- threshold: 0.55
- hour_min: 15

**Dual Strategy** (calibrar com `calibrate_dual.py`):
- Começar com fast mode para estimar
- Usar detailed mode para finalizar
- Verificar se Forecast Early ou Peak Detection é mais usado

**Phased Entry** (calibrar com `calibrate_phased.py`):
- thr_p2 deve ser > thr_p1_max
- thr_p3 deve ser > thr_p2
- P1 janela: manhã (10-12h)

### Dallas (sem WU)

**SingleEntry** (já calibrado):
- threshold: 0.350
- hour_min: 17

**Dual Strategy**:
- Desactivar Forecast Early (fc_available=False)
- Apenas Peak Detection

**Phased Entry**:
- Mesmos princípios que Munich

### Ankara (sem WU)

**SingleEntry** (já calibrado):
- threshold: 0.350
- hour_min: 15

**Dual Strategy** e **Phased Entry**: Mesmos princípios que Dallas

---

## Próximos Passos

1. **Executar calibração standard/detailed para cada cidade**
   ```bash
   python calibrate_dual.py --city munich --mode standard --years 3
   python calibrate_phased.py --city munich --mode standard --years 3
   ```

2. **Comparar resultados com backtest**
   ```bash
   python backtest_compare.py --city munich --years 3
   ```

3. **Validar em paper trading (14 dias)**
   ```bash
   python live_bot.py --cities munich --mode dual --run paper
   python live_bot.py --cities munich --mode phased --run paper
   ```

4. **Documentar parâmetros finais** em `cities/config.py`

---

## Resultados Preliminares (Munich, 1 ano, fast mode)

### Dual Strategy - Top Config
```
fc_hour_min=10, fc_hour_max=14
fc_p_min=0.70, fc_ev_margin=0.05
pk_threshold=0.70, pk_hour_min=11
stop_loss_delta=1.0

Resultados: 350 trades/ano, win=100%, score=254.6
```

### Phased Entry - Top Config
```
thr_p1_min=0.30, thr_p1_max=0.65
thr_p2=0.45, thr_p3=0.65
p1_hour_min=10, p1_hour_max=12

Resultados: 29 trades/ano, win=100%, score=148.0
```

### Comparação (1 ano)
```
┌────────────┬───────┬────────┬─────────┬───────┐
│ Estratégia │ Trd/y │   Win% │    ROI% │ Score │
├────────────┼───────┼────────┼─────────┼───────┤
│ SingleEntry│    29 │ 100.0% │  +47.3% │ 148.0 │
│ DualStrategy│   365 │  66.7% │ +51230% │ 170.9 │
│ PhasedEntry│    29 │ 100.0% │  +59.4% │ 148.0 │
└────────────┴───────┴────────┴─────────┴───────┘
```

---

## Notas Técnicas

**SimulatedMarket:**
- Usa climatologia da cidade + ruído 5%
- Não é preço real Polymarket
- ROI inflado é esperado

**Forecast Agreement (PhasedEntry):**
- No calibrate_phased: usa PhasedEntrySimple (ignora restrições)
- No backtest_compare: usa PhasedEntry completo
- Para produção, validar restrições

**Stop-loss:**
- Implementado em SingleEntry e DualStrategy
- PhasedEntry: não tem stop-loss implementado ainda
