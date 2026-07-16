# Telemetria — Sistema de logging para backtest offline

Este documento descreve o sistema de telemetria que regista tudo o que acontece no `live_bot.py` para análise posterior.

---

## 1. Visão geral

O sistema é composto por 2 ficheiros:

| Ficheiro | Função |
|---|---|
| `tick_logger.py` | Logger — regista ticks, bets e outcomes em JSONL |
| `backtest_logger.py` | Analisador — gera relatórios a partir dos logs |

### Integração no `live_bot.py`

- Import no topo (com fallback se faltar)
- `log_tick()` chamado no fim de cada `_tick_city()` → 1 linha por tick por cidade
- `log_bet()` chamado após cada buy (normal / eod / race)
- `log_outcome()` chamado em EOD quando há settlement paper

---

## 2. Ficheiros gerados

Todos os ficheiros são gravados em `live_bot_logs/ticks/`.

### 2.1 `ticks_{city}_{date}.jsonl`

**1 linha por tick** (default 30s = ~2880 linhas/dia por cidade).

Schema de cada linha (JSON):

```json
{
  "ts":                "2026-06-18T17:42:13+01:00",
  "city":              "munich",
  "date":              "2026-06-18",
  "city_local_hhmm":   "18:42",
  "tick_count":        127,
  "temp_now":          29.5,
  "running_max":       30.2,
  "running_max_hour":  15,
  "slots_count":       23,
  "p_ensemble":        0.683,
  "p_lgbm":            0.683,
  "threshold":         0.65,
  "hour_min":          11,
  "bought":            false,
  "stop_loss_hit":     false,
  "forecast_wu":       27,
  "forecast_om":       null,
  "target_bracket": {
    "label":           "30.0°C",
    "ask":             0.45,
    "bid":             0.40,
    "token_id":        "0x...",
    "temp_lo":         29.5,
    "temp_hi":         30.5
  },
  "market_top": [
    {"label": "28°C", "ask": 0.05, "bid": 0.03},
    {"label": "29°C", "ask": 0.10, "bid": 0.08},
    {"label": "30°C", "ask": 0.45, "bid": 0.40},
    {"label": "31°C", "ask": 0.30, "bid": 0.25},
    {"label": "32°C", "ask": 0.08, "bid": 0.05},
    {"label": "33°C", "ask": 0.02, "bid": 0.01}
  ],
  "market_volume":     15420.5,
  "market_n_outcomes": 9,
  "race_active":       false,
  "race_threshold":    null,
  "eod_active":        false,
  "actions":           [],
  "errors":            []
}
```

### 2.2 `bets_{city}_{date}.jsonl`

**1 linha por buy** (normal, race ou eod_fallback).

Schema:

```json
{
  ...bet_record original do live_bot...,
  "ts":                   "2026-06-18T15:30:00+01:00",
  "tick_count":           127,
  "trigger":              "normal",
  "race_rank":            null,
  "race_total":           null,
  "p_ensemble_at_buy":    0.683,
  "market_volume_at_buy": 15420.5
}
```

O campo `trigger` pode ser:
- `"normal"` — buy normal (p_ensemble >= threshold)
- `"eod_fallback"` — buy forçado pelo EOD fallback
- `"race"` — buy via Top-K race mode (futuro)

### 2.3 `outcomes_{city}_{date}.jsonl`

**1 linha por dia** (gerado em EOD quando há settlement paper).

Schema:

```json
{
  "ts":                          "2026-06-18T22:00:00+01:00",
  "city":                        "munich",
  "date":                        "2026-06-18",
  "temp_max_actual":             30.5,
  "temp_max_hour":               15,
  "bracket_resolved":            "30.0°C",
  "n_ticks":                     1247,
  "n_buys":                      2,
  "n_sells":                     0,
  "n_stops":                     0,
  "bought":                      true,
  "win":                         true,
  "pnl_total":                   12.50,
  "invested":                    10.00,
  "p_ensemble_max":              0.78,
  "p_ensemble_at_buy":           0.68,
  "p_ensemble_at_peak_temp":     0.72,
  "race_used":                   false,
  "eod_used":                    false,
  "errors_count":                0
}
```

---

## 3. Como usar o `backtest_logger.py`

### 3.1 Análise de 1 dia (detalhado)

```bash
python backtest_logger.py --city munich --date 2026-06-18
```

Output: relatório completo com:
- Estatísticas de P(pico) (min, max, mean, median, stdev)
- Estatísticas de temperatura
- Quase-sinais (ticks com p >= thr*0.85 mas < thr, sem bet)
- Race/EOD usage
- Bets do dia
- Evolução do target bracket
- Distribuição de P(pico) por hora

### 3.2 Resumo multi-dia (1 cidade)

```bash
python backtest_logger.py --city munich --last 7
```

Output: agregado dos últimos 7 dias com:
- Win rate
- P&L total
- ROI %
- Total de buys
- Dias com buy
- P(pico) máximo absoluto
- Quase-sinais totais

### 3.3 Resumo multi-cidade

```bash
python backtest_logger.py --all --last 30
```

Analisa todas as cidades com logs nos últimos 30 dias.

### 3.4 Exportar para CSV (Excel/R)

```bash
python backtest_logger.py --city munich --last 7 --csv --csv-path munich_week.csv
```

Exporta todos os ticks para CSV com colunas:
`ts, city, date, city_local_hhmm, tick_count, temp_now, running_max, slots_count, p_ensemble, p_lgbm, threshold, bought, stop_loss_hit, forecast_wu, target_bracket_label, target_bracket_ask, target_bracket_bid, market_volume, race_active, eod_active`

### 3.5 Todos os argumentos

| Argumento | Descrição |
|---|---|
| `--city NAME` | Cidade (ex: munich) |
| `--all` | Analisar todas as cidades com logs |
| `--date YYYY-MM-DD` | Data específica |
| `--last N` | Últimos N dias (default 1) |
| `--csv` | Exportar ticks para CSV |
| `--csv-path PATH` | Caminho do CSV (default: `ticks_{city}.csv`) |

---

## 4. Perguntas que podes responder

| Pergunta | Onde encontrar |
|---|---|
| Quantos ticks Munich teve com p > 0.5 mas sem bet? | `near_signals.count` no relatório |
| Qual era o ask do bracket alvo quando P(pico) = 0.7? | `target_bracket_evolution.ask_at_peak_p` |
| Em que horas do dia o modelo é mais confiante? | `p_by_hour` no relatório |
| Qual a distribuição de p_ensemble por cidade? | `p_ensemble` stats (min/max/mean/median/stdev) |
| Se tivéssemos apostado em todos os ticks com p > 0.55, qual o P&L? | Filtra ticks por `p_ensemble`, compara com `outcomes.bracket_resolved` |
| Win rate por cidade nos últimos 30 dias? | `python backtest_logger.py --all --last 30` |
| Quantas bets foram race/eod vs normal? | `bets.jsonl` — agrupar por `trigger` |
| Quantos erros por dia? | `errors_count` no outcome |
| Qual o ROI da última semana? | `--last 7` → `outcomes.roi_pct` |

---

## 5. Exemplo de relatório de 1 dia

```
======================================================================
  RELATÓRIO — MUNICH — 2026-06-18
======================================================================

  Ticks registados: 1247
  Bets registadas:  2
  Outcome gravado:  ✓

  📊 OUTCOME DO DIA:
     Temp max actual:     30.5°C @ 15h
     Bracket resolvido:   30.0°C
     Comprou:             ✓
     Win:                 True
     P&L:                 +$12.50
     Investido:           $10.00
     P(pico) máximo:      0.78
     P(pico) no buy:      0.68
     P(pico) no pico temp: 0.72
     Race usado:          ✗
     EOD usado:           ✗
     Erros no dia:        0

  🧠 P(ENSEMBLE) — LightGBM:
     Mínimo:   0.124
     Máximo:   0.780
     Média:    0.452
     Mediana:  0.421
     Std:      0.187
     Ticks acima do threshold (812): 812/1247 (65.1%)
     Ticks com p>=0.50: 987
     Ticks com p>=0.70: 142

  🌡 TEMPERATURA:
     Min: 14.2°C  Max: 30.5°C  Média: 22.8°C
     Primeira obs: 14.2°C  Última: 25.1°C
     Running max final: 30.5°C

  ⚡ QUASE-SINAIS (p >= thr*0.85 mas < thr):
     Total: 47 ticks
     Primeiros 5:
       10:30 p=0.5827 (faltam 6.7pts) temp=20.5°C rmax=22.1°C
       10:45 p=0.5912 (faltam 5.9pts) temp=21.2°C rmax=22.1°C
       ...

  🏁 RACE/EOD MODE:
     Ticks com race activo: 0
     Ticks com EOD activo:  0

  💰 BETS DO DIA:
     2026-06-18T15:30:00+01:00 | normal       | 30.0°C         ask=45¢ $5.00 | p=0.683

  🎯 TARGET BRACKET EVOLUTION:
     Observações: 1247
     Primeira: 06:30 label=27.0°C ask=5¢ (p=0.124)
     Última:   20:30 label=30.0°C ask=45¢ (p=0.683)
     Ask min/max: 5¢ / 65¢
     Ask no pico de P: 45¢ (p=0.780 @ 14:30)

  📅 DISTRIBUIÇÃO DE P(ENSEMBLE) POR HORA:
     Hora     N    Min       Méd       Max
     6        47   0.124     0.187     0.245
     7        60   0.156     0.234     0.312
     8        60   0.234     0.345     0.421
     9        60   0.345     0.456     0.567
     10       60   0.456     0.534     0.612
     11       60   0.534     0.612     0.689
     12       60   0.612     0.689     0.745
     13       60   0.689     0.756     0.780
     14       60   0.712     0.765     0.780
     15       60   0.678     0.734     0.780
     16       60   0.612     0.689     0.745
     17       60   0.534     0.612     0.689
     18       60   0.456     0.534     0.612
     19       60   0.378     0.456     0.534
     20       57   0.312     0.389     0.456
```

---

## 6. Exemplo de resumo multi-dia

```
======================================================================
  RESUMO MULTI-DIA — MUNICH — 7 dias
======================================================================

  Datas analisadas: 2026-06-12, 2026-06-13, ..., 2026-06-18

  📊 OUTCOMES:
     Dias com outcome:    7
     Wins:                4
     Losses:              2
     Win rate:            66.7%
     P&L total:           +$23.50
     Investido total:     $35.00
     ROI:                 +67.1%
     Total de buys:       7
     Dias com buy:        7/7
     Dias com race:       0
     Dias com EOD:        0

  🧠 P(ENSEMBLE) AGGREGATE:
     Média das médias diárias: 0.452
     Média dos máximos diários: 0.765
     Máximo absoluto:          0.812

  ⚡ QUASE-SINAIS:
     Total:        312
     Média/dia:    44.6
     Máximo/dia:   78
```

---

## 7. Performance e disco

### 7.1 Estimativa de espaço

Cada tick gera ~1.5KB de JSON. Com 30s interval e 14 cidades:

- ~2880 ticks/dia × 14 cidades = **40,320 linhas/dia**
- ~60MB/dia em disco
- ~1.8GB/mês

### 7.2 Limpeza automática (recomendado)

Adiciona ao crontab para apagar logs com mais de 30 dias:

```bash
# Editar crontab
crontab -e

# Adicionar linha (corre às 04:00 todos os dias):
0 4 * * * find ~/POLY-MULTI-CITY/live_bot_logs/ticks -name "*.jsonl" -mtime +30 -delete
```

### 7.3 Comprimir logs antigos (alternativa)

Em vez de apagar, comprimir:

```bash
# Comprimir logs com mais de 7 dias (gzip reduz ~80%)
0 4 * * * find ~/POLY-MULTI-CITY/live_bot_logs/ticks -name "*.jsonl" -mtime +7 -exec gzip {} \;
```

---

## 8. Notas técnicas

### 8.1 Fail-safe

- O logger é **fail-safe**: se algo falha ao escrever, apenas loga no stderr — não quebra o bot
- Se `tick_logger.py` não estiver disponível, o bot continua a funcionar sem telemetria (import tem `try/except`)

### 8.2 Append-only

- Os ficheiros JSONL são **append-only** — safe para correr em paralelo com o bot
- Podes ler os ficheiros enquanto o bot escreve (cada linha é independente)

### 8.3 Reset diário

- O `tick_count` reinicia em cada novo dia (detectado pela data da cidade)
- O `_p_ensemble_max` também reinicia em cada novo dia
- O `_p_ensemble_at_buy` é limpo em cada novo dia

### 8.4 Timezone

- `ts` (timestamp) está em `Europe/Lisbon` (timezone do bot)
- `city_local_hhmm` está na timezone da cidade (ex: `Europe/Berlin` para Munich)
- Isto permite saber tanto "quando o bot viu isto" como "que horas eram na cidade"

### 8.5 Compatibilidade com logs existentes

- Os ficheiros `live_bot_logs/bets_{city}_{date}.json` (formato antigo) continuam a ser escritos pelo `_append_bet_record` do `live_bot.py`
- Os ficheiros `live_bot_logs/ticks/bets_{city}_{date}.jsonl` (formato novo) têm informação extra (trigger, p_at_buy, market_volume)
- Podes usar qualquer um dos dois para análise, mas o novo tem mais contexto

---

## 9. Workflow recomendado

### 9.1 Setup inicial (1 vez)

1. Copiar `tick_logger.py` e `backtest_logger.py` para a VPS
2. Configurar cron job para limpar logs antigos (ver secção 7.2)

### 9.2 Rotina diária

1. Bot corre em paper mode durante o dia
2. Logs são gravados automaticamente em `live_bot_logs/ticks/`
3. No fim do dia (ou manhã seguinte), analisar:

```bash
# Resumo de ontem (1 cidade)
python backtest_logger.py --city munich --date 2026-06-18

# Resumo dos últimos 7 dias (1 cidade)
python backtest_logger.py --city munich --last 7

# Resumo de todas as cidades (últimos 30 dias)
python backtest_logger.py --all --last 30
```

### 9.3 Análise semanal

```bash
# Exportar CSV para Excel/R
python backtest_logger.py --city munich --last 7 --csv --csv-path munich_week.csv
python backtest_logger.py --city madrid --last 7 --csv --csv-path madrid_week.csv
```

### 9.4 Quando tomar decisões

Após 1-2 semanas de telemetria, podes responder a:

- **"O threshold está bem calibrado?"** — se `near_signals.count` é sempre alto mas `n_buys` é baixo, threshold está muito alto
- **"Race mode está a ajudar?"** — compara `outcomes.n_buys` com/sem `race_used=True`
- **"EOD fallback está a perder dinheiro?"** — filtra outcomes por `eod_used=True`, calcula win rate
- **"Em que horas apostar?"** — `p_by_hour` mostra horas de pico de confiança
- **"Vale a pena retrain?"** — se `p_ensemble_max` é consistentemente < 0.5, modelo pode estar underfit

---

## 10. Estrutura de ficheiros

```
live_bot_logs/
├── ticks/                                    ← NOVO: telemetria
│   ├── ticks_munich_2026-06-18.jsonl         ← 1 linha por tick
│   ├── ticks_munich_2026-06-19.jsonl
│   ├── ticks_madrid_2026-06-18.jsonl
│   ├── bets_munich_2026-06-18.jsonl          ← 1 linha por buy
│   ├── outcomes_munich_2026-06-18.jsonl      ← 1 linha por dia
│   └── ...
├── bets_munich_2026-06-18.json               ← existente: anti-duplicado
├── munich_2026-06-18.json                    ← existente: daily stats
├── paper_positions.json                      ← existente: posições paper
├── real_positions.json                       ← existente: posições real
└── live_snapshot.json                        ← existente: snapshot web
```

---

## 11. Troubleshooting

### 11.1 "Sem dados para exportar"

```bash
$ python backtest_logger.py --city munich --date 2026-06-18
  ❌ sem ticks
```

**Causa**: não há ficheiro `ticks_munich_2026-06-18.jsonl`.

**Solução**: verifica se o bot correu nesse dia e se `tick_logger.py` está no path.

### 11.2 Logger falha silenciosamente

Se vires no output do bot:
```
  [tick_logger] log_tick failed: ...
```

**Causa**: provável problema de permissões no directório `live_bot_logs/ticks/`.

**Solução**:
```bash
mkdir -p live_bot_logs/ticks
chmod 755 live_bot_logs/ticks
```

### 11.3 Ficheiros muito grandes

Se um ficheiro `ticks_*.jsonl` crescer demasiado (>100MB):

```bash
# Verificar tamanho
ls -lh live_bot_logs/ticks/

# Comprimir logs antigos
gzip live_bot_logs/ticks/ticks_munich_2026-06-*.jsonl
```

### 11.4 Análise rápida via jq

Para análise ad-hoc sem o `backtest_logger.py`, podes usar `jq`:

```bash
# Contar ticks por cidade
jq -r '.city' live_bot_logs/ticks/ticks_*_2026-06-18.jsonl | sort | uniq -c

# Ver P(pico) máximo do dia para Munich
jq -s 'map(.p_ensemble) | max' live_bot_logs/ticks/ticks_munich_2026-06-18.jsonl

# Ver todos os buys com trigger
jq -c '{ts, city, trigger, bracket_label, ask, p_ensemble_at_buy}' live_bot_logs/ticks/bets_*_2026-06-18.jsonl

# Win rate do dia
jq -s 'map(.win) | {wins: map(select(.==true)) | length, losses: map(select(.==false)) | length}' live_bot_logs/ticks/outcomes_*_2026-06-18.jsonl
```

---

## 12. Próximos passos sugeridos

1. **Copia os ficheiros** para a VPS:
   ```bash
   scp tick_logger.py backtest_logger.py live_bot.py user@vps:~/POLY-MULTI-CITY/
   ```

2. **Configura cron** para limpeza (secção 7.2)

3. **Arranca o bot em paper mode** e deixa correr 1-2 dias

4. **Analisa** com `backtest_logger.py`

5. **Ajusta parâmetros** com base na análise:
   - Se `near_signals` muito alto → baixar `--threshold-override`
   - Se `p_ensemble_max` consistentemente < 0.5 → considerar retrain
   - Se `errors_count` > 0 → investigar causa
