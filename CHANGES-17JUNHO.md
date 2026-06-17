# Alterações — Dashboard Telegram periódico + forçar >=1 trade/dia

Ficheiros modificados:
- `live_bot.py` (1504 → 1910 linhas)
- `tg.py` (1020 → 1118 linhas)

---

## 1. Diagnóstico do problema

Em 5 dias (12-17 Jun) só 1 bet (Munich) com `live_bot.py --mode single --run paper` multi-city. Causas identificadas:

1. **Thresholds calibrados altos demais** para as condições de verão 2026 — raramente atingidos.
2. **Filtro `max_buy_ask` não aplicado no `_tick_city`** — só existia em calibrate_all.py.
3. **`is_multi=False` não tinha dashboard periódico nenhum** — só alertas de evento. Impossível acompanhar métricas ao longo do dia.
4. **Multi-city report a cada 1h** — muito espaçado para debug.
5. **Sem alerta de quase-sinal** — impossível saber quando o modelo está perto de disparar.

---

## 2. Novos argumentos CLI (live_bot.py)

```
--tg-interval SECONDS              Default 1800 (30 min). Intervalo do dashboard
                                   Telegram periódico (single E multi).
--threshold-override FLOAT         Override do threshold para TODAS as cidades.
                                   Ex: 0.55 força entradas mais fáceis.
--max-buy-ask FLOAT                Default 0.85. Bloqueia buys acima de 85¢.
                                   Brackets quase certos têm payout mau.
--force-eod-trade                  Força buy nas últimas N horas do dia se
                                   nenhuma bet foi feita hoje.
--eod-fallback-threshold FLOAT     Default 0.5. Fração do threshold original
                                   para EOD fallback. Ex: thr=0.70, fallback=0.35.
--eod-start-hours-before-close INT Default 2. Horas antes do day_end para
                                   começar a considerar EOD fallback.
```

---

## 3. Comandos recomendados para a VPS

### Single-city com dashboard de 30 min (debug detalhado)

```bash
python live_bot.py \
    --cities munich \
    --mode single \
    --run paper \
    --tg-interval 1800 \
    --max-buy-ask 0.85
```

A cada 30 minutos recebes no Telegram:
- Título com cidade + modo + data + hora
- Curva ASCII de temperatura (6 linhas) com pico e range
- Temperatura actual + running max + forecast WU/OM
- P(pico) com barra visual + threshold
- Tabela de brackets (top 6, com bid/ask e barra)
- Posição actual (se comprado)
- P&L acumulado
- Saldo USDC (se REAL mode)

A meio do caminho (entre 30 min e 30 min), se p_ensemble estiver entre `threshold*0.85` e `threshold`, recebes um **alerta de quase-sinal** dizendo "faltam X pontos".

### Multi-city com pelo menos 1 trade/dia

```bash
python live_bot.py \
    --cities munich,dallas,ankara,madrid \
    --mode single \
    --run paper \
    --tg-interval 1800 \
    --max-buy-ask 0.85 \
    --force-eod-trade \
    --eod-fallback-threshold 0.5 \
    --eod-start-hours-before-close 2
```

A cada 30 min recebes no Telegram um resumo multi-cidade com:
- P&L total + nº de apostas
- Lista ordenada por p_ensemble desc (as mais quentes primeiro)
- Para cada cidade: iconografia de estado (💼 comprado, 🔥 signal, ⚡ quase, 🔍 aprox, 💤 longe)
- P(pico) / threshold + barra visual + "faltam X pts"
- Temperatura actual / running max

E nas últimas 2h do dia, se nenhuma cidade tiver apostado:
- Threshold temporariamente baixado para `thr * 0.5`
- Alerta `⏰ EOD Fallback activado` enviado
- Buy forçado na cidade com p_ensemble mais alto

### Ainda mais agressivo (se continuares sem trades)

```bash
python live_bot.py \
    --cities munich,dallas,ankara,madrid \
    --mode single \
    --run paper \
    --threshold-override 0.55 \
    --force-eod-trade \
    --eod-fallback-threshold 0.4 \
    --tg-interval 1800
```

`--threshold-override 0.55` força TODAS as cidades a usar 55% (em vez do calibrado, normalmente 65-70%). Combinado com EOD fallback a 40% do original (=22%), praticamente garante trade todos os dias.

---

## 4. Detalhes técnicos das alterações

### `tg.py`

#### `alert_multi_city_summary()` (melhorado)
- Antes: só mostrava nome da cidade + PnL, ordenado por PnL.
- Agora: ordena por `p_ensemble` desc (vês quais estão mais perto de disparar), mostra P(pico)/threshold, barra visual, gap em pontos, iconografia de estado (💼🔥⚡🔍💤), temperatura/rmax.

#### `alert_near_signal()` (NOVO)
- Aviso de quase-sinal: p_ensemble entre `threshold*0.85` e `threshold`.
- Mostra P(pico), threshold, gap em pontos, barra visual, temp/rmax.
- Throttled a 30 min pelo caller (state._last_near_signal_ts).

#### `alert_eod_fallback()` (NOVO)
- Avisa que o EOD fallback foi activado: threshold original → fallback, P(pico), bracket alvo + ask.

#### `dashboard()` (modificado)
- Adicionado parâmetro `city_name=None`.
- Título agora dinâmico: `{City} Bot Live` em vez de hardcoded "Munich Bot Live".
- Mantém todos os parâmetros existentes (compatibilidade retroativa).

### `live_bot.py`

#### `CityState` (dataclass)
- Novos campos: `max_buy_ask=0.85`, `force_eod_trade=False`, `eod_fallback_threshold=0.5`, `eod_start_hours_before_close=2`, `_last_near_signal_ts=0.0`.

#### `_tick_city()`
- **EOD Fallback** (antes do `evaluate()`): se `force_eod_trade` activo, ainda não comprou, e `h_cur >= day_end - 2h`, baixa temporariamente o threshold para `thr * eod_fallback_threshold`. Se `p_ensemble >= fallback_thr`, o `evaluate()` vai gerar action. Restaura threshold no fim.
- **Filtro `max_buy_ask`** (depois do `min_buy_ask`): bloqueia buys acima de X¢ (default 85¢). Avisa via Telegram com motivo "bracket quase certo, payout mau".

#### `_build_ascii_chart()` (NOVO helper)
- Gera chart ASCII multi-linha (6 linhas) de temperatura ao longo do dia.
- Largura 28 chars (adequado para Telegram mobile).
- Mostra pico anotado, min, range.
- Funciona com qualquer nº de slots (sampling se >28).

#### `_send_single_city_dashboard()` (NOVO helper)
- Constrói todos os parâmetros necessários a partir de `state` e chama `tg_inst.dashboard(...)`.
- Inclui: temp_now, rmax, rmax_time, forecast_max (WU), om_forecast, forecast_agreement, market, target_bracket, ensemble_result, peak_detected, bet, positions_summary, usdc_balance, chart ASCII, city_name.

#### Main loop
- `_tg_dashboard_interval` agora usa `args.tg_interval` (default 30 min) em vez de hardcoded 1h.
- Alerta de arranque enriquecido com info sobre EOD/threshold override/max_buy_ask.
- **Branch single-city (NOVO)**: a cada `args.tg_interval` segundos, chama `_send_single_city_dashboard()`.entre ticks, verifica near-signal e envia `alert_near_signal()` se aplicável (throttled 30 min).
- **Branch multi-city (melhorado)**: `cities_data` agora inclui `p_ensemble`, `threshold`, `hour_min`, `bought`, `temp_now`, `running_max`, `local_hhmm` para cada cidade.

---

## 5. Fluxo de mensagens Telegram esperado por dia

### Single-city (munich, 30 min interval)

- 8h00: Dashboard inicial (curva temp, P(pico), brackets, etc.)
- 8h30: Dashboard
- 9h00: Dashboard + (possivel) alerta near-sinal
- ...
- 14h00: Dashboard
- 14h30: Dashboard + (possivel) `🔔 PICO DETECTADO` se thr atingido
- 14h31: `🟡 Ordem colocada [PAPER]` se buy executado
- 15h00: Dashboard (já com posição aberta)
- ...
- 22h00: Dashboard final
- ~22h30: `📅 Fim do dia` com P&L
- Total esperado: ~28 dashboards + 0-3 alertas

### Multi-city (4 cidades, 30 min interval, force-eod-trade)

- 8h00: Resumo multi-cidade (4 linhas + total)
- 8h30: Resumo
- ...
- 14h00: Resumo + `🔔 PICO DETECTADO` se thr atingido em alguma cidade
- 14h01: `🟡 Ordem colocada [PAPER]` (se comprou)
- ...
- 20h00: Resumo + possivel `⏰ EOD Fallback activado` para cidades sem trade
- 20h01: `🟡 Ordem colocada [PAPER]` para cidade em fallback
- ...
- 23h00: Resumo final
- Total esperado: ~30 resumos + 1-4 alertas EOD + 0-4 alertas BUY

---

## 6. Notas importantes

1. **Não altera a lógica do modelo** — LightGBM continua a produzir `p_ensemble` da mesma forma. Só mudam os filtros à volta (threshold, max_ask, EOD).

2. **Compatível com paper e real mode** — todas as alterações respeitam `args.run` (paper/real).

3. **`paper_positions.json` resetável** — se uma cidade ficar presa com posição antiga impedindo novas entradas, podes apagar `live_bot_logs/paper_positions.json` (em PAPER) ou usar o EOD fallback.

4. **Threshold override é persistente durante a sessão** — aplicado no arranque a todas as cidades. Não afecta o ficheiro `strategy_config_{city}.json`.

5. **EOD fallback restaura o threshold** — após o `evaluate()`, o threshold original é reposto. Não afecta o próximo tick nem o próximo dia.

6. **`alert_near_signal` só dispara em single-city** — em multi-city essa informação já vem no resumo periódico (campo `p_ensemble` vs `threshold` por cidade).

---

## 7. Rollback

Se algo correr mal, os ficheiros originais continuam em `/home/z/my-project/upload/`:
- `upload/live_bot.py` (original, 1504 linhas)
- `upload/tg.py` (original, 1020 linhas)

Basta copiar de volta:
```bash
cp upload/live_bot.py . && cp upload/tg.py .
```
