# Alterações — Dashboard Telegram + Race mode + Menu Charts + WU-only

Ficheiros modificados:
- `live_bot.py` (1504 → 2050 linhas)
- `tg.py` (1020 → 1400 linhas)
- `weather.py` (550 → 580 linhas) — NOVO nesta iteração

---

## 1. Diagnóstico do problema

Em 5 dias (12-17 Jun) só 1 bet (Munich) em multi-city. Causas:

1. Thresholds calibrados altos demais para verão 2026
2. `max_buy_ask` não aplicado no `_tick_city`
3. Sem dashboard periódico em single-city
4. Multi-city report só a cada 1h
5. Sem alerta de quase-sinal

---

## 2. Novos argumentos CLI

```
--tg-interval SECONDS              Default 1800 (30min). Dashboard Telegram periódico.
--threshold-override FLOAT         Override do threshold para TODAS as cidades.
--max-buy-ask FLOAT                Default 0.85. Bloqueia buys acima de 85¢.
--race-top-k INT                   Default 0 (off). Top-K Race mode em multi-city.
                                   Recomendado: 2 (1-2 bets/dia sem forçar).
--race-min-threshold FLOAT         Default 0.50. Threshold mínimo absoluto para race.
                                   Race nunca compra abaixo deste valor — qualidade.
--race-eval-interval INT           Default 300 (5min). Segundos entre race evals.
--force-eod-trade                  [DESACONSELHADO] Força buy nas últimas N horas.
--eod-fallback-threshold FLOAT     Default 0.5. Fração do threshold para EOD.
--eod-start-hours-before-close INT Default 2. Horas antes do close para EOD.
```

---

## 3. DUAS abordagens para garantir volume em multi-city

### A. Top-K Race mode (RECOMENDADO — não força)

```
--race-top-k 2 --race-min-threshold 0.50
```

**Como funciona**:
- A cada 5 min, ordena todas as cidades não compradas por `p_ensemble` descendente
- Filtra as que têm `p_ensemble >= 0.50` (race_min_threshold) e `ask <= 0.85` (max_buy_ask)
- Pega nas **top-2** e baixa temporariamente o threshold delas para `max(0.50 * 0.95, p * 0.95)` — garante que `evaluate()` dispara
- Faz buy nessas top-2 (respeitando `min_buy_ask` e `max_buy_ask`)
- Restaura threshold original

**Porque mantém qualidade**:
- Se nenhuma cidade tem `p_ensemble >= 0.50`, **não há buy** (race skip)
- Se só 1 cidade atinge, só 1 buy
- Se 5 cidades atingem, compra as **2 melhores** (maior `p_ensemble`)
- Threshold nunca é baixado para além de `p * 0.95` — ou seja, a cidade seleccionada tem pelo menos `p_ensemble = 0.50` (não compra "lixo")

**Telegram alerts**:
- `🏁 RACE seleccionou — {City} (rank 1/2)`: quando uma cidade é seleccionada
- `🏁 RACE eval — sem candidatos`: quando nenhuma cidade atinge o mínimo (throttled 30min)

### B. EOD Fallback (DESACONSELHADO — força)

```
--force-eod-trade --eod-fallback-threshold 0.5
```

**Como funciona**:
- Nas últimas 2h do dia, se a cidade não comprou, baixa threshold para `thr * 0.5`
- Se `p_ensemble >= fallback_thr`, faz buy

**Porque NÃO recomendado**:
- "Força" buy só porque o dia está a acabar, sem considerar se a oportunidade é boa
- Pode comprar com `p_ensemble = 0.30` se o threshold calibrado for 0.60
- Degrada a qualidade dos resultados

**Mantido no código** para casos extremos, mas **usa antes o Race mode**.

---

## 4. Comandos recomendados para a VPS

### Single-city com dashboard de 30 min (debug detalhado)

```bash
python live_bot.py \
    --cities munich \
    --mode single \
    --run paper \
    --tg-interval 1800 \
    --max-buy-ask 0.85
```

A cada 30 min recebes no Telegram:
- Curva ASCII de temperatura (6 linhas) com pico e range
- P(pico) com barra visual + threshold
- Tabela de brackets (top 6, com bid/ask e barra)
- Posição actual + P&L acumulado
- Saldo USDC (se REAL mode)

Entre dashboards, se `p_ensemble` está em `[thr*0.85, thr)`, recebes `⚡ Quase-sinal — faltam X pontos` (throttled 30 min).

### Multi-city com Race mode (1-2 bets/dia, sem forçar)

```bash
python live_bot.py \
    --cities munich,dallas,ankara,madrid \
    --mode single \
    --run paper \
    --tg-interval 1800 \
    --max-buy-ask 0.85 \
    --race-top-k 2 \
    --race-min-threshold 0.50 \
    --race-eval-interval 300
```

A cada 30 min recebes no Telegram um resumo multi-cidade com:
- P&L total + nº de apostas
- Lista ordenada por `p_ensemble` desc (as mais quentes primeiro)
- Para cada cidade: iconografia de estado (💼 comprado, 🔥 signal, ⚡ quase, 🔍 aprox, 💤 longe)
- P(pico) / threshold + barra visual + "faltam X pts"
- Temperatura actual / running max

A cada 5 min, o race phase avalia:
- Se há < 2 cidades compradas, identifica top-K elegíveis
- Recebes `🏁 RACE seleccionou` para cada cidade escolhida
- Recebes `🟡 Ordem colocada [PAPER]` quando o buy executa
- Se nenhuma cidade elegível: `🏁 RACE eval — sem candidatos` (throttled 30 min)

### Ainda mais agressivo (se continuares sem trades)

```bash
python live_bot.py \
    --cities munich,dallas,ankara,madrid \
    --mode single \
    --run paper \
    --race-top-k 2 \
    --race-min-threshold 0.45 \
    --threshold-override 0.55 \
    --tg-interval 1800
```

- `--threshold-override 0.55`: força TODAS as cidades a usar 55% (threshold fixo baixo)
- `--race-min-threshold 0.45`: race aceita `p_ensemble >= 0.45`
- Mais volume, mas qualidade ligeiramente inferior

---

## 5. Comparação: Race vs EOD vs Override

| Mecanismo | Força? | Mantém qualidade? | Garante volume? | Quando usar |
|---|---|---|---|---|
| **Race mode** (top-K) | Não | Sim (`p >= min_abs`) | Sim (top-K) | **Recomendado para multi-city** |
| **Threshold override** | Sim (global) | Médio (baixa thr para todos) | Sim | Quando modelo está consistentemente baixo |
| **EOD fallback** | Sim (por hora) | Não (compra com `p` baixo) | Sim | **Desaconselhado** — só em casos extremos |

---

## 6. Detalhes técnicos das alterações

### `tg.py`

#### `alert_multi_city_summary()` (melhorado)
- Ordena por `p_ensemble` desc
- Mostra P(pico)/threshold, barra visual, gap, iconografia de estado, temp/rmax

#### `alert_near_signal()` (NOVO)
- Aviso de quase-sinal: `p_ensemble` entre `threshold*0.85` e `threshold`
- Throttled 30 min pelo caller

#### `alert_race_selected()` (NOVO)
- Avisa que race mode seleccionou uma cidade
- Mostra P(pico), threshold original → race_thr, bracket + ask, rank/total

#### `alert_race_no_candidates()` (NOVO)
- Avisa que race eval não encontrou candidatos elegíveis
- Throttled 30 min

#### `alert_eod_fallback()` (NOVO, desaconselhado)
- Avisa que EOD fallback foi activado

#### `dashboard()` (modificado)
- Adicionado parâmetro `city_name=None`
- Título dinâmico em vez de hardcoded "Munich"

### `live_bot.py`

#### `CityState` (dataclass)
- Novos campos: `max_buy_ask`, `force_eod_trade`, `eod_fallback_threshold`, `eod_start_hours_before_close`, `_last_near_signal_ts`

#### `_tick_city()`
- **EOD Fallback** (desaconselhado): baixa threshold nas últimas N horas
- **Filtro `max_buy_ask`** (depois do `min_buy_ask`): bloqueia buys > 85¢

#### `_build_ascii_chart()` (NOVO helper)
- Chart ASCII multi-linha (6 linhas) de temperatura
- Largura 28 chars, adequado para Telegram mobile

#### `_send_single_city_dashboard()` (NOVO helper)
- Constrói todos os parâmetros a partir de `state` e chama `tg_inst.dashboard(...)`

#### Main loop
- `_tg_dashboard_interval` agora usa `args.tg_interval` (default 30 min)
- **Branch single-city (NOVO)**: dashboard periódico + near-signal alert
- **Branch multi-city (melhorado)**: `cities_data` enriquecido com `p_ensemble`, `threshold`, `bought`, etc.
- **RACE PHASE (NOVO)**: em multi-city com `--race-top-k > 0`:
  - A cada `race_eval_interval` segundos
  - Conta `n_bought`, se < `race_top_k` há slots disponíveis
  - Filtra cidades elegíveis (não compradas + `p >= min_abs` + `ask <= max_buy_ask` + em janela de trading)
  - Ordena por `p_ensemble` desc, itera preenchendo slots (skips não contam para o limite)
  - Para cada slot: baixa threshold temporariamente, chama `_tick_city`, restaura threshold
  - Avisa via Telegram (`alert_race_selected` ou `alert_race_no_candidates`)

---

## 7. Fluxo de mensagens Telegram esperado por dia

### Multi-city (4 cidades, race-top-k=2, 30 min interval)

- 8h00: Resumo multi-cidade (4 linhas + total)
- 8h05: `🏁 RACE seleccionou` (se houver elegível) ou `🏁 RACE eval — sem candidatos` (se não houver)
- 8h06: `🟡 Ordem colocada [PAPER]` (se buy executou)
- 8h10: Resumo multi-cidade
- ...
- A cada 5 min: race eval (silencioso se nada muda)
- A cada 30 min: resumo multi-cidade (4-5 linhas)
- Total esperado: ~30 resumos + 1-2 race alerts + 0-2 buy alerts + 0-2 no-candidates alerts (throttled)

---

## 8. Menu Charts por Cidade (NOVO)

Em multi-city, o resumo periódico de 30 min é compacto (só P(pico)/threshold/estado por cidade). Para ver os **charts completos** de uma cidade específica a qualquer momento, há um novo botão no menu do Telegram.

### Como usar

1. No Telegram, envia `/menu` (ou abre o menu inicial enviado pelo bot no arranque)
2. Clica em **📈 Charts por Cidade**
3. Aparece lista de cidades activas (botões em colunas de 2)
4. Clica numa cidade → recebes uma mensagem com:
   - Header: cidade + data + hora local
   - Temperatura actual + running max + forecasts WU/OM
   - P(pico) com barra visual + threshold
   - **Chart ASCII de temperatura** (40x10) — curva do dia, pico anotado, min, range, nº slots
   - **Tabela completa de brackets** (até 18) — label, bid/ask, barra visual, target destacado com 🎯
   - Posição actual (se comprado)
   - Botões: **🔄 Refresh** + **← Voltar**

### Comandos Telegram disponíveis agora

| Comando | Descrição |
|---|---|
| `/start` | Mensagem de boas-vindas + menu inline + instruções (NOVO) |
| `/menu` | Menu principal com 5 botões |
| `/charts` | Menu directo de Charts por Cidade (NOVO) |
| `/resumo` | Resumo do dia (PnL, win rate) |
| `/posicoes` | Posições abertas |
| `/ultimas` | Últimas 5 vitórias |
| `/status` | Status do bot em todas as cidades |
| `/help` | Ajuda e lista de comandos (NOVO) |

### Botão "/" no Telegram (NOVO)

No arranque do bot, é feita chamada a `setMyCommands()` do BotFather API que regista os 7 comandos acima. Isto faz o Telegram mostrar um **botão "/" ao lado da caixa de input** que abre a lista de comandos — não precisas de escrever `/menu` para aceder às opções.

Depois de copiares o `tg.py` actualizado para a VPS e reiniciares o bot:
1. Abre o chat do bot no Telegram
2. Verás um botão **/** ao lado da caixa de mensagem (em baixo, à direita)
3. Clica nele → aparece a lista de comandos
4. Clica num comando → é inserido automaticamente na caixa
5. Enter para executar

Também podes enviar `/start` a qualquer momento para receber o menu inline + instruções de uso.

### Detalhes técnicos do menu de comandos

- `set_my_commands()` é chamado automaticamente no `start_polling()` do `tg.py`
- Se falhar (ex: rate limit do Telegram), o bot continua a funcionar — só aparece um aviso no terminal
- Os comandos ficam registados para **todos os utilizadores** do bot (default scope)
- Para mudar a lista de comandos, edita a lista no `start_polling()` e reinicia o bot

### Detalhes técnicos

- O callback_data tem formato `chart:{city_name}` (limite Telegram: 64 bytes)
- A mensagem pode ter até 4096 chars — se exceder, divide em 2 mensagens automaticamente
- Refresh (`🔄`) re-gera a mensagem com dados actualizados (slots, brackets, p_ensemble)
- Voltar (`←`) volta ao menu de selecção de cidades
- Lê `self.bot_states` que é passado pelo `live_bot.py` via `tg.start_polling(bot_states=states)`

---

## 9. Notas importantes

1. **Race mode é a abordagem recomendada** para garantir 1-2 bets/dia sem forçar.
2. **EOD fallback mantido no código** mas desaconselhado — só usar em casos extremos.
3. **Threshold override** é mais agressivo que race — baixa thr para TODAS as cidades. Usar só se race não chega.
4. **`max_buy_ask=0.85`** aplica-se tanto ao tick normal como ao race.
5. **Race phase chama `_tick_city` novamente** — overhead de fetch + predict extra, mas só a cada 5 min para 1-2 cidades, aceitável.
6. **Race phase respeita anti-duplicado** — só selecciona cidades com `entry.bought = False`.
7. **Race skip não conta para o limite** — se 1 das top-K já está acima do threshold original, passa à próxima.
8. **Compatível com paper e real mode**.

---

## 10. Modo WU-only (sem fallback para Open-Meteo) — NOVO

### Problema

O `weather.py` original tinha `except Exception: return []` no `fetch_wu_day` que engolia **todos** os erros silenciosamente. Quando o WU falhava (HTTP 401, 429, timeout, etc.), o bot apenas mostrava `"WU com poucos dados, fallback OM"` e usava Open-Meteo sem te avisar que algo estava mal.

### Solução

1. **`weather.py` — `fetch_wu_day` reescrito**:
   - Não engole erros — mostra mensagem específica por código HTTP
   - Mostra o body do response para debug
   - Mostra headers de rate limit (`X-RateLimit-Remaining`, `Retry-After`)
   - Trata timeout, connection error, JSON inválido, response sem `observations` (WU mudou formato)
   - Cada erro tem mensagem `[WU] {cidade}: HTTP {code} — {descrição}`

2. **`weather.py` — `bootstrap_today` sem fallback**:
   - Removida chamada a `bootstrap_om_today` no fim
   - Se WU falha, retorna `({}, [])` — caller decide
   - Mensagem `FALHOU (ver mensagens [WU] acima)` em vez de fallback silencioso

3. **`live_bot.py` — `_bootstrap_state_today` sem fallback**:
   - Removido o bloco `if len(slots) < 4: fallback OM`
   - Se WU devolve < 4 slots, mostra mensagem e mantém `slots_so_far = []`
   - Removido fallback OM no `except Exception` (em vez disso, mostra erro real)

4. **`live_bot.py` — `_tick_city` sem fallback OM**:
   - Removido o bloco `if not new_obs: om_hourly = fetch_om_hourly_today(...)`
   - Se WU falha, `latest_obs = None` e o tick faz o melhor que pode com os slots que já tem

### Como diagnosticar problemas WU agora

Quando correres o bot, vais ver mensagens como:

```
  [WU] munich: HTTP 401 — API key invalida ou expirada
  [WU] Body: {"errors":[{"code":"AUTH","message":"Invalid API key"}]}
```

ou:

```
  [WU] munich: HTTP 429 — RATE LIMIT excedido — espera antes de tentar
  [WU] Body: {"errors":[{"code":"RATE","message":"Too many requests"}]}
  [WU] X-RateLimit-Remaining: 0
  [WU] Retry-After: 60
```

ou:

```
  [WU] munich: 200 OK mas sem 'observations' no response
  [WU] Top keys: ['metadata', 'narrative']
  [WU] Body (primeiros 500 chars): {"metadata": {}, "narrative": "Sunny day"}
```

ou:

```
  [WU] munich: TIMEOUT (>20s) a pedir https://api.weather.com/v1/location/de/munich/EDDM/observations/historical.json
```

Cada uma destas mensagens diz-te exactamente o que está mal.

### Notas importantes

- Cidades sem `wu_history_path` (Dallas, Ankara, etc.) continuam sem dados em modo WU-only. Se quiseres usá-las, precisas de configurar WU history path para elas.
- `fetch_om_forecast_max` e `fetch_om_hourly_today` continuam importados (não apaguei do `weather.py`) mas não são chamados no fluxo principal. Mantenho-os caso queiras usar para diagnóstico manual.
- O `tg.py` dashboard multi-cidade ainda mostra `OM:{temp}°C` se `last_om_forecast_max` estiver no state. Como OM não é mais chamado, este campo fica sempre `None` e o dashboard omite essa linha.

---

## 10. Migracao para endpoints WU v3/v2 (free key compatível) — NOVO

### Causa raiz do problema original

Os endpoints `/v1/location/.../observations/historical.json` e `/v3/wx/historical/records/...` davam **HTTP 401 com Akamai Access Denied** para free keys do WU. O `weather.py` original engolia este erro silenciosamente e fazia fallback para Open-Meteo.

### Endpoints WU válidos para free keys (confirmados por testes curl)

Analisei o HTML do `wunderground.com/history/daily/de/munich/EDDM` e descobri que o próprio site WU usa estes endpoints com a mesma free key:

| Endpoint | Funciona? | Para que serve |
|---|---|---|
| `/v3/wx/observations/current` (com `geocode` ou `icaoCode`) | ✅ Sim | Observação actual |
| `/v3/wx/forecast/daily/5day` | ✅ Sim | Forecast 5 dias |
| `/v2/pws/history/all` (com `stationId` PWS, `units=m`) | ✅ Sim (a confirmar) | Histórico por PWS station |
| `/v2/pws/observations/current` (com `stationId` PWS, `units=m`) | ✅ Sim (a confirmar) | Observação actual por PWS |
| `/v1/location/.../observations/historical.json` | ❌ 401 Akamai | Descontinuado para free keys |
| `/v3/wx/historical/records/...` | ❌ 401 Akamai | Requer plano comercial |

### Alterações ao `weather.py`

1. **`fetch_wu_latest` reescrito** — usa `/v3/wx/observations/current` com `geocode={lat},{lon}`. Não precisa de stationId.

2. **`fetch_wu_day` reescrito** — usa `/v2/pws/history/all` com `stationId={pws_station_id}` e `units=m`. Precisa de `city.pws_station_id` configurado em `cities/config.py` (fallback para `city.icao` se não existir).

3. **`fetch_wu_forecast_max` reescrito** — usa `/v3/wx/forecast/daily/5day` com `geocode`.

4. **Novo parser `_v3_current_parse`** — para resposta do endpoint v3 current. Campos diferentes do v1:
   - `temperature` (em vez de `temp`)
   - `relativeHumidity` (em vez de `rh`)
   - `cloudCover` (inteiros 0-100, em vez de string `CLR/BKN/OVC`)
   - `temperatureDewPoint` (em vez de `dewpt`)
   - `pressureMeanSeaLevel` ou `pressureAltimeter`
   - `windDirection`, `windSpeed`, `windGust`
   - `expirationTimeUtc` para timestamp

5. **Novo parser `_v2_pws_history_parse`** — para resposta do endpoint PWS history. Formato:
   ```json
   {
     "observations": [
       {
         "obsTimeUtc": "2026-06-18T08:00:00.000-0000",
         "humidityAvg": 65,
         "winddirAvg": 245,
         "uvHigh": 4,
         "metric": {
           "tempAvg": 18.5,
           "dewptAvg": 12.0,
           "pressureMax": 1018.5,
           "windspeedAvg": 8.5,
           "windgustAvg": 12.3
         }
       }
     ]
   }
   ```

6. **`_wu_parse_obs` mantido** por compatibilidade mas NÃO é mais chamado (era para o formato v1/location descontinuado).

### IMPORTANTE: precisas configurar `pws_station_id` em `cities/config.py`

O endpoint `/v2/pws/history/all` precisa de um `stationId` PWS (Personal Weather Station), não do `icaoCode` do aeroporto. Para Munich, o site WU usa `IOBERD38` (estação PWS em Oberding, perto de Munich).

Para cada cidade precisas de adicionar:
```python
@dataclass
class CityConfig:
    # ... campos existentes ...
    pws_station_id: str = ""  # NOVO — PWS station ID para histórico
```

E configurar o `pws_station_id` para cada cidade. Podes descobrir o PWS stationId mais próximo em `https://www.wunderground.com/wundermap` — procura a estação PWS mais próxima do centro da cidade.

### Como descobrir PWS stations por cidade

Para cada cidade:
1. Vai a `https://www.wunderground.com/wundermap?lat={lat}&lon={lon}&zoom=11`
2. Procura estações PWS (círculos pequenos) perto do centro da cidade
3. Clica numa → copia o stationId (ex: `IOBERD38`)
4. Adiciona ao `cities/config.py`:
   ```python
   pws_station_id = "IOBERD38"  # Munich PWS
   ```

Se não tiveres `pws_station_id` configurado, o código faz fallback para `city.icao` (ex: `EDDM`) mas **isto pode não funcionar** porque a API PWS espera PWS stations, não aeroportos. Por isso é recomendado configurar.

---

## 11. Próximos passos sugeridos

1. **Copia os 3 ficheiros para a VPS**:
   ```bash
   scp /home/z/my-project/download/live_bot.py user@vps:~/sonofnabia-droid-polymarket-weather-multicity/
   scp /home/z/my-project/download/tg.py user@vps:~/sonofnabia-droid-polymarket-weather-multicity/
   scp /home/z/my-project/download/weather.py user@vps:~/sonofnabia-droid-polymarket-weather-multicity/
   ```

2. **Configura `pws_station_id` em `cities/config.py`** para cada cidade (ver secção 10).

3. **Reinicia o bot**:
   ```bash
   cd ~/sonofnabia-droid-polymarket-weather-multicity
   source venv/bin/activate
   python live_bot.py --cities munich --mode single --run paper --tg-interval 1800
   ```

4. **Verifica as mensagens `[WU]`** no arranque — agora devem mostrar dados reais em vez de 401.

---

## 13. Telemetria para backtest offline — NOVO

Adicionei um sistema de telemetria que regista tudo o que acontece no bot para depois poderes analisar offline.

### Ficheiros novos

| Ficheiro | Função |
|---|---|
| `tick_logger.py` | Logger — regista ticks, bets e outcomes em JSONL |
| `backtest_logger.py` | Analisador — gera relatórios a partir dos logs |

### Integração no live_bot.py

- Import no topo (com fallback se faltar)
- `log_tick()` chamado no fim de cada `_tick_city()` (1 linha por tick por cidade)
- `log_bet()` chamado após cada buy (normal/eod/race)
- `log_outcome()` chamado em EOD quando há settlement paper

### Ficheiros gerados em `live_bot_logs/ticks/`

Para cada cidade, por dia:

1. **`ticks_{city}_{date}.jsonl`** — 1 linha por tick (default 30s = ~2880 linhas/dia)
   - timestamp, temp_now, running_max, p_ensemble, threshold, target_bracket (label/ask/bid)
   - top 6 brackets do mercado com ask/bid
   - bought, stop_loss_hit, race_active, eod_active
   - actions devolvidas por evaluate()

2. **`bets_{city}_{date}.jsonl`** — 1 linha por buy
   - tudo do bet_record original + ts, tick_count, trigger, p_ensemble_at_buy, market_volume

3. **`outcomes_{city}_{date}.jsonl`** — 1 linha por dia (em EOD)
   - temp_max_actual, bracket_resolved, win, pnl_total, invested
   - p_ensemble_max (do dia), p_ensemble_at_buy, p_ensemble_at_peak_temp
   - n_ticks, n_buys, n_stops, race_used, eod_used, errors_count

### Como analisar — exemplos

```bash
# Análise de 1 dia para 1 cidade (detalhado)
python backtest_logger.py --city munich --date 2026-06-18

# Resumo dos últimos 7 dias para 1 cidade
python backtest_logger.py --city munich --last 7

# Análise de todas as cidades nos últimos 30 dias
python backtest_logger.py --all --last 30

# Exportar ticks para CSV (para Excel/R)
python backtest_logger.py --city munich --last 7 --csv --csv-path munich_week.csv
```

### Perguntas que podes responder com os logs

| Pergunta | Como |
|---|---|
| "Quantos ticks Munich teve com p > 0.5 mas sem bet?" | `near_signals.count` no relatório |
| "Qual era o ask do bracket alvo quando P(pico)=0.7?" | `target_bracket_evolution.ask_at_peak_p` |
| "Em que horas o modelo é mais confiante?" | `p_by_hour` no relatório |
| "Qual a distribuição de p_ensemble por cidade?" | `p_ensemble` stats (min/max/mean/median/stdev) |
| "Se tivéssemos apostado em todos os ticks com p > 0.55, qual o P&L?" | Filtra ticks por p_ensemble, compara com outcome |
| "Win rate por cidade nos últimos 30 dias?" | `python backtest_logger.py --all --last 30` |
| "Quantas bets foram race/eod vs normal?" | `bets.jsonl` — agrupar por `trigger` |
| "Quantos erros por dia?" | `errors_count` no outcome |

### Performance / disco

Cada tick gera ~1.5KB de JSON. Com 30s interval e 14 cidades:
- ~2880 ticks/dia × 14 cidades = 40,320 linhas/dia
- ~60MB/dia em disco
- Recomendação: rodar `cron` para apagar logs com mais de 30 dias

### Notas

- O logger é "fail-safe": se algo falha ao escrever, apenas loga no stderr — não quebra o bot
- Se `tick_logger.py` não estiver disponível, o bot continua a funcionar sem telemetria
- Os ficheiros JSONL são append-only — safe para correr em paralelo com o bot
- O `tick_count` reinicia em cada novo dia (detectado pela data da cidade)

---

## 14. Rollback

Ficheiros originais em `/home/z/my-project/upload/`:
- `upload/live_bot.py` (original, 1504 linhas)
- `upload/tg.py` (original, 1020 linhas)
- `upload/weather.py` (original, 550 linhas)
- `upload/config.py` (original, 619 linhas)

Ficheiros novos (não existiam antes, não há rollback):
- `tick_logger.py`
- `backtest_logger.py`
- `discover_pws_from_wu_pages.py`

```bash
cp upload/live_bot.py . && cp upload/tg.py . && cp upload/weather.py . && cp upload/config.py cities/
```
