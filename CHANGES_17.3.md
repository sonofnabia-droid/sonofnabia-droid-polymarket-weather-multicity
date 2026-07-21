Bug 1 – Bankroll PAPER corrompido na mudança de dia. Na linha 852, state.daily_stats = DailyStats(date=city_today) repõe daily_pnl para 0.0, mas state._last_applied_pnl (linha 329) mantém o valor acumulado do dia anterior. No tick seguinte, no main() (linhas 1913–1916), delta = stats.daily_pnl - last_applied = 0 - <pnl_anterior> é negativo, subtraindo o PnL do dia anterior do bankroll.

Deixa-me procurar mais bugs. Um olhar à lógica do stop-loss "já disparado antes do restart" (linhas 1101–1114).

→ Read live_bot.py [limit=20, offset=1100]

Há um bug lógico aqui: na linha 1109–1110, se o stop-loss já disparou, definem _stop_loss_blocked_alerted = True. Mas depois, linhas 1113–1114, incondicionalmente definem _stop_loss_blocked_alerted = False. Isto apaga o que foi definido nas linhas 1109–1110 imediatamente a seguir. Assim, a guarda contra alertas duplicados é anulada — o alerta de stop-loss vai disparar de novo. Isto é provavelmente um bug: as linhas 1113–1114 deviam estar dentro de um else ou apenas executadas se não foi detectado stop-loss.

Deixa-me olhar à lógica de _next_race_tick — segunda chamada a _tick_city poderia causar duplicação de trades/apostas.

Já notei outro bug: na linha 2054, _tick_city(s, args.run, city_bankroll_race) é chamado dentro do race loop. Mas _tick_city contém a lógica anti-duplicado (linhas 1027–1114). Se já comprou, vai saltar. Mas no race, slots_filled é incrementado de qualquer maneira (linha 2062), mesmo que o tick não produza buy (porque p < race_thr mesmo após baixar). Isto é documentado como "contabiliza a tentativa". OK.

Deixa-me procurar problemas de chia/throttle no _save_daily_stats.

→ Read live_bot.py [offset=1503, limit=15]

Atenção: stats.trades e stats.stop_losses_triggered são avaliados como booleanos (truthy). stats.trades é uma lista (truthy se não vazia). stats.stop_losses_triggered é um int (truthy se >0). Mas o throttle tem um bug: se houve um trade no tick, ele guarda; mas no tick seguinte (sem novo trade mas ainda dentro dos 5 min), a condição or stats.trades ainda é true porque a lista ainda tem o trade antigo. Por isso, na prática grava em todos os ticks após o primeiro trade. Isto derrota o propósito do throttle. O throttle devia basear-se em "mudança desde último save", não no estado total. Mas é um bug menor (apenas I/O extra).

Deixa-me procurar mais bugs potenciais relacionados com current_market_slug usado no race e no stop-loss.

Deixa-me também verificar se há uso de current_market_slug antes de ser definido no race tick (linha 2054).

$ cd /home/marco/POLY-MULTI-CITY && grep -n "current_market_slug" live_bot.py

1031:        current_market_slug = state.fetcher.date_to_slug(city_today)
1041:            and b.get("market_slug") == current_market_slug
1052:            "market_slug": first.get("market_slug", current_market_slug),
1068:            and getattr(p, "market_slug", "") == current_market_slug
1079:            "market_slug": getattr(pos, "market_slug", current_market_slug),
1268:        bet_record["market_slug"] = current_market_slug
1419:        current_market_slug = state.fetcher.date_to_slug(city_today)
1422:            and getattr(p, "market_slug", "") == current_market_slug

Na linha 1268, bet_record["market_slug"] = current_market_slug — current_market_slug foi definida na linha 1031, dentro do bloco anti-duplicado. Mas note que a linha 1031 está dentro de if state.entry and state.market and state.clob. Na linha 1172, o bloco de trade decision é if state.entry and state.market and state.clob. E current_market_slug (linha 1031) foi definido se state.entry and state.clob, então provavelmente está disponível. OK.

Deixa-me agora verificar o cálculo de shares no stop-loss (linha 1444) — usa size_usdc / entry_ask sem math.floor. Deveria ser math.floor para ser consistente com a compra (linha 1256) que usa math.floor.

→ Read live_bot.py [limit=8, offset=1441]

Bug confirmado: Linha 1444 usa size_usdc / entry_ask (float) enquanto a compra (linha 1256) usa math.floor(size_usdc / ask). Isto causa inconsistência: o número real de shares comprados é floor(50.11)=45, mas o PnL calcula com 45.45... shares virtuais. Assim realized_pnl é inflado. Deveria ser math.floor.

Deixa-me comparar com o backtester, que já foi corrigido (linha 612 usa math.floor).

→ Read backtester.py [limit=5, offset=610]

Sim — o backtester usa math.floor, o live_bot não. Inconsistência confirmada.

Deixa-me verificar outro problema: o filtro de plateau no evaluate.

Na linha 118, now_minutes = hour * 60 + (slots_so_far[-1].get("slot30", 0) if slots_so_far else 0). Mas hour é parâmetro de hora passada ao evaluate, e slots_so_far[-1] é o último slot. Se o hour não corresponde ao último slot (por exemplo, se o slot atual ainda não foi adicionado), o cálculo está errado. Mas normalmente correspondem.

Deixa-me olhar um possível problema com hour_min = 11 por defeito (linha 75) enquanto noutras partes usam city.hour_min ou 06. Vou só verificar.

Deixa-me agora ver se há bugs na lógica de settle de posições de dias anteriores (PAPER) — _settle_paper_positions_for_day.

→ Read live_bot.py [offset=485, limit=35]

Potencial bug: pos_id construído com or — se getattr(pos, "order_id", "") é string vazia, vai para o próximo. Mas se order_id é "0" ou similar, é truthy. OK.

Mas atenção: pos_id só é adicionado ao settled_position_ids se for truthy (linha 511). Se pos_id é string vazia (todos os gets falham), não é adicionado, e a posição pode ser settled repetidamente a cada tick. Isto causaria PnL duplicado! Mas no PAPER mode, depois de resolve_paper_position, a posição passa a LOST/WON e deixa de estar em open_positions(), então não é revisitada. OK, provavelmente não é bug.

Deixa-me olhar agora ao cálculo de bracket resolvido no bloco de log outcome (linhas 1813–1840).

→ Read live_bot.py [offset=1809, limit=30]

Atenção ao bug aqui: a linha 1816 if lo <= temp_max_actual <= hi: usa intervalo fechado [lo, hi]. Mas o backtester corrige isto para semi-aberto [lo, hi+1.0) em _bracket_contains_peak (linha 372) para evitar overlap de brackets no pico exato. Aqui no log outcome, não foi aplicada a mesma correção. Isto pode dar win=True para mais do que um bracket (se o pico é exatamente num limite), causando log inconsistente. Bug menor (apenas telemetria), mas ainda assim bug.

Aliás, há um segundo bug aqui: a verificação de win compara labels de string (linha 1824) buy_label == bracket_resolved. Mas labels podem diferir (normalização); seria melhor usar temp_lo/temp_hi. O fallback só acontece se buy_label é None, raramente.

Deixa-me olhar agora ao find_bracket (linhas 247–271) que também usa intervalo fechado lo <= target <= hi.

→ Read live_bot.py [limit=25, offset=247]

find_bracket usa lo <= target <= hi (fechado). Nos brackets Polymarket reais (de 1 grau Celsius), lo == hi é o caso (e.g., "25°C" tem lo=25, hi=25). A linha 259 trata esse caso. Brackets "or higher" têm hi=99, "or lower" têm lo=-99. Então o lo <= target <= hi na linha 265 só se aplica a brackets de 1 grau (lo==hi), que já foi tratado na linha 259. Então para brackets reais, não há overlap. Mas para brackets de intervalo múltiplo (se existirem), haveria overlap. Provavelmente OK para Polymarket.

Deixa-me agora consolidar e escrever uma análise clara dos bugs encontrados. Deixa-me também verificar o daily_stats no main loop — possivelmente há outro bug somando PnL de stop-loss duas vezes.

No _tick_city, o stop-loss adiciona realized_pnl a stats.daily_pnl (linha 1453). Depois, no main() loop, quando o dia acaba e há settlement WON/LOST/EXPIRED (linha 1895), somam PnL a stats.daily_pnl. Mas no PAPER mode, os stop-loss ainda são resolvidos via _settle_paper_positions_for_day? Vamos verificar se uma posição vendida por stop-loss ainda aparece em open_positions(). Provavelmente não — o sell_yes fecha-a. Então não duplica. OK.
