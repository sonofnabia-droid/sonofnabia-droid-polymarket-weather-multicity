# Análise de Bugs

Confirmado. Bug confirmado:

**Bug 1 -- Bankroll PAPER corrompido na mudança de dia.** Na linha 852,
`state.daily_stats = DailyStats(date=city_today)` repõe `daily_pnl` para
`0.0`, mas `state._last_applied_pnl` (linha 329) mantém o valor
acumulado do dia anterior. No tick seguinte, no `main()` (linhas
1913--1916),
`delta = stats.daily_pnl - last_applied = 0 - <pnl_anterior>` é
negativo, subtraindo o PnL do dia anterior do bankroll.

Deixa-me procurar mais bugs. Um olhar à lógica do stop-loss "já
disparado antes do restart" (linhas 1101--1114).

→ Read `live_bot.py` `[limit=20, offset=1100]`

Há um **bug lógico** aqui: na linha 1109--1110, se o stop-loss já
disparou, definem `_stop_loss_blocked_alerted = True`. Mas depois,
linhas 1113--1114, incondicionalmente definem
`_stop_loss_blocked_alerted = False`. Isto apaga o que foi definido nas
linhas 1109--1110 imediatamente a seguir. Assim, a guarda contra alertas
duplicados é anulada --- o alerta de stop-loss vai disparar de novo.
Isto é provavelmente um bug: as linhas 1113--1114 deviam estar dentro de
um `else` ou apenas executadas se não foi detectado stop-loss.

Deixa-me olhar à lógica de `_next_race_tick` --- segunda chamada a
`_tick_city` poderia causar duplicação de trades/apostas.

Já notei outro bug: na linha 2054,
`_tick_city(s, args.run, city_bankroll_race)` é chamado dentro do race
loop. Mas `_tick_city` contém a lógica anti-duplicado (linhas
1027--1114). Se já comprou, vai saltar. Mas no race, `slots_filled` é
incrementado de qualquer maneira (linha 2062), mesmo que o tick não
produza buy (porque `p < race_thr` mesmo após baixar). Isto é
documentado como "contabiliza a tentativa". OK.

Deixa-me procurar problemas de chia/throttle no `_save_daily_stats`.

→ Read `live_bot.py` `[offset=1503, limit=15]`

Atenção: `stats.trades` e `stats.stop_losses_triggered` são avaliados
como booleanos (truthy). `stats.trades` é uma lista (truthy se não
vazia). `stats.stop_losses_triggered` é um int (truthy se \>0). Mas o
throttle tem um bug: se houve um trade no tick, ele guarda; mas no tick
seguinte (sem novo trade mas ainda dentro dos 5 min), a condição
`or stats.trades` ainda é `true` porque a lista ainda tem o trade
antigo. Por isso, na prática grava em todos os ticks após o primeiro
trade. Isto derrota o propósito do throttle. O throttle devia basear-se
em "mudança desde último save", não no estado total. Mas é um bug menor
(apenas I/O extra).

Deixa-me procurar mais bugs potenciais relacionados com
`current_market_slug` usado no race e no stop-loss.

Na linha 1268, `bet_record["market_slug"] = current_market_slug`. A
variável foi definida anteriormente no mesmo fluxo (`state.entry`,
`state.market`, `state.clob`), pelo que parece estar disponível. OK.

**Bug confirmado:** Linha 1444 usa `size_usdc / entry_ask` (float)
enquanto a compra (linha 1256) usa `math.floor(size_usdc / ask)`. Isto
causa inconsistência: o número real de shares comprados é
`floor(50.11)=45`, mas o PnL calcula com `45.45...` shares virtuais.
Assim `realized_pnl` é inflado. Deveria ser `math.floor`.

O backtester já usa `math.floor`, confirmando a inconsistência.

O cálculo de `now_minutes` em `evaluate()` pode estar incorreto se
`hour` não corresponder ao último slot em `slots_so_far`, embora
normalmente correspondam.

Na lógica `_settle_paper_positions_for_day`, existe um potencial
problema se `pos_id` for vazio, mas na prática posições resolvidas
deixam de aparecer em `open_positions()`, pelo que não deverá causar
duplicação.

No bloco de log de outcome existe um bug: a verificação
`lo <= temp_max_actual <= hi` usa um intervalo fechado, enquanto o
backtester usa um intervalo semiaberto para evitar sobreposição de
brackets. Pode gerar telemetria inconsistente.

Existe ainda um segundo problema nesse bloco: a comparação usa labels
(`buy_label == bracket_resolved`) em vez de limites numéricos
(`temp_lo`/`temp_hi`), podendo falhar em casos de normalização.

A função `find_bracket()` também usa intervalo fechado, mas para os
brackets reais do Polymarket isso não deverá causar problemas.

No final, foi verificado que o PnL do stop-loss não parece ser somado
duas vezes em PAPER mode, porque uma posição vendida por stop-loss deixa
de existir em `open_positions()`.
