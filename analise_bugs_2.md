# Análise de Bugs — Live Bot Multi-Cidade
## Consolidado de todos os bugs encontrados na análise profunda

Este documento consolida os bugs identificados em múltiplas análises dos ficheiros principais do sistema: live_bot.py, backtester.py, modules/single_entry.py, weather.py, polymarket_clob.py, predictor.py.

## RESUMO EXECUTIVO

Foram identificados **22 bugs** distribuídos por diferentes níveis de severidade:

| Severidade | Quantidade | Exemplos |
|------------|------------|----------|
| **Crítico** | 4 | Bugs que causam crash, perda de dinheiro directa ou inconsistência total |
| **Alto** | 7 | Bugs que causam perda de oportunidade significativa ou decisões erradas |
| **Médio** | 7 | Bugs que causam inconsistências, calibração enganadora ou problemas menores |
| **Baixo** | 4 | Bugs de edge case, rara ocorrência ou impacto mínimo |

## BUGS CRÍTICOS (4)

### 1. **NameError em plateau_timeout_hours** (modules/single_entry.py:91)
- **Localização**: Linha 91 em `modules/single_entry.py`
- **Descrição**: O `_first_non_none` referencia a variável `plateau_timeout_hours` que nunca é inicializada nos ramos de fallback. Apenas `threshold`, `hour_min`, `stop_loss_delta`, `min_buy_ask`, `max_buy_ask` são pré-inicializados a `None`.
- **Impacto**: Crash garantido (`NameError`) na construção de qualquer `SingleEntry` se o JSON de config não contiver a chave `plateau_timeout_hours`. Isto quebra completamente o bot e o backtester.
- **Reprodução**: `python -c "from modules.single_entry import SingleEntry; SingleEntry(get_city('munich'))"`

### 2. **Confusão entre None e 0.0 em wind speed parsing** (weather.py:335-340)
- **Localização**: Linhas 335-340 em `weather.py` dentro de `_v2_pws_history_parse`
- **Descrição**: A expressão `_maybe_convert_mph_to_kmh(...) or 0.0` converte tanto `None` (falha de parsing) quanto `0.0` (vento legítimo de calmaria) para `0.0`, mascarando falhas de parsing como dados válidos.
- **Impacto**: Dados meteorológicos errados (vento sempre 0 em falha) → decisões de trading baseadas em informações falsas → **perda de dinheiro**.

### 3. **Inconsistência entre bootstrap_today e floor_slot** (weather.py:436-460 + 732/742)
- **Localização**: Linhas 436-460 (chamada) + linhas 732/742 (implementação do bootstrap)
- **Descrição**: `bootstrap_today` usa `ceil_slot` para mapear observações a slots, marcando o slot atual (incompleto) como "completo". O caller filtra depois com `floor_slot`, mas isto vem tarde demais — o slot já foi incluído.
- **Impacto**: `peak_temp` inclui slots ainda a decorrer → pico inflado artificialmente → decisões Polymarket erradas → **perda de dinheiro**.

### 4. **Sanity check de temperatura unidirecional** (weather.py:423-433)
- **Localização**: Linhas 423-433 em `weather.py`
- **Descrição**: O sanity check apenas bloqueia temperaturas ALTAS (`temp_c > clim_max + 15`). Falha em detectar conversões erradas que produzem temperaturas MUITO BAIXAS (ex: Fahrenheit interpretado como Celsius em dias frios).
- **Impacto**: `peak_temp` pode ser 20°C demasiado baixo → decisões de trading materialmente erradas → **perda de dinheiro**.

## BUGS ALTOS (7)

### 5. **Restore não preserva sold_by_stop** (modules/single_entry.py:295-301)
- **Localização**: Linhas 295-301 em `modules/single_entry.py`
- **Descrição**: `restore()` força sempre `self.sold_by_stop = False`, ignorando o valor salvo no record. Após restart, se o stop-loss tiver acontecido mas a temperatura já baixado, o bot pode reverificar e disparar stop-loss duplicado.
- **Impacto**: Stop-loss duplicado pós-restart → venda dupla da mesma posição → **perda de dinheiro ou ordem inválida no CLOB**.

### 6. **check_stop_loss ignora brackets "or higher"** (modules/single_entry.py:273-274)
- **Localização**: Linhas 273-274 em `modules/single_entry.py`
- **Descrição**: Condição `if bracket_hi is None or bracket_hi >= 99: return None` desativa completamente o stop-loss para posições em brackets de cauda alta (ex: "30°C or higher").
- **Impacto**: Posições "or higher" nunca são fechadas por temperatura → mantêm-se até expiração mesmo quando claramente perdidas → **perda de oportunidade de cortar perdas**.

### 7. **Validação ausente em ceil_slot/floor_slot** (weather.py:676-688)
- **Localização**: Linhas 676-688 em `weather.py`
- **Descrição**: Falta de validação de `minute` [0,59] e `hour` [0,23]. Valores como `minute=60` ou `hour=24` podem produzir chaves inválidas como `(24,30)` nos dicionários de slots.
- **Impacto**: Keys inválidas nos dicionários → potencial crash ou comportamento imprevisível → **instabilidade do sistema**.

### 8. **Backtester recalcula bracket vs evaluate() bracket** (backtester.py:637-648 vs single_entry.py:160)
- **Localização**: Linhas 637-648 em `backtester.py` vs linha 160 em `modules/single_entry.py`
- **Descrição**: O backtester ignora o `bracket` retornado por `evaluate()` e recalcula o `best` localmente com lógica diferente (fallback por midpoint sem considerar caudas explicitamente).
- **Impacto**: Inconsistência entre backtest e live bot → calibração enganadora → performance real desviada do esperado.

### 9. **Stop-loss silenciado por temp_hi=None após restart** (modules/single_entry.py:272)
- **Localização**: Linha 272 em `modules/single_entry.py`
- **Descrição**: `bracket_hi = self.record.get("temp_hi")` pode ser `None` se o record não tiver esta chave (ex: após restart com dados incompletos), desativando silenciosamente o stop-loss.
- **Impacto**: Stop-loss pode ser desativado silenciosamente em live após restart → **perda de oportunidade de cortar perdas**.

### 10. **Plateau filter assumes slots_so_far[-1] is current slot** (modules/single_entry.py:121-135)
- **Localização**: Linhas 121-135 em `modules/single_entry.py`
- **Descrição**: O filtro calcula `now_minutes = hour * 60 + slots_so_far[-1].get("slot30", 0)`, assumindo que `slots_so_far[-1]` corresponde ao `hour` atual. Se o caller adicionar o slot actual *após* chamar `evaluate()`, a comparação fica errada.
- **Impacto**: Filtro de plateau pode sub- ou sobre-disparar dependendo do caller → **compras incorrectas bloqueadas/desbloqueadas**.

### 11. **Observação misplaced por fallback minute=0** (weather.py:215-227)
- **Localização**: Linhas 215-227 em `weather.py` dentro de `_v3_current_parse`
- **Descrição**: Quando `validTimeUtc` falha, o fallback usa `datetime.now(...).hour` com `minute=0`, colocando a observação no início errado do hora (slot errado).
- **Impacto**: Obs actual perdida do slot certo → inconsistência com `latest_obs` e `peak_temp` → **dados meteorológicos inconsistentes**.

## BUGS MÉDIOS (7)

### 12. **_select_target_bracket fallback picks first, not best** (modules/single_entry.py:240-248)
- **Localização**: Linhas 240-248 em `modules/single_entry.py`
- **Descrição**: O loop de fallback de cauda retorna o *primeiro* bracket que satisfaz `hi >= 99 and target_temp >= lo`, não o mais próximo de `target_temp`.
- **Impacto**: Pode comprar um bracket subótimo (mais longe do target) → **oportunidade perdida / bid-ask pior**.

### 13. **pressure_hpa uses pressureMax instead of avg** (weather.py:332)
- **Localização**: Linha 332 em `weather.py`
- **Descrição**: `pressure_hpa = _f(metric, "pressureMax", _f(metric, "pressureMin", 1013.0))` usa `pressureMax` prioritariamente, não a pressão média.
- **Impacto**: Pressão enviesada para cima → inconsistência com outras fontes → **dados meteorológicos ligeiramente errados**.

### 14. **Observation minute inconsistent with retained temp** (weather.py:733)
- **Localização**: Linha 733 em `weather.py`
- **Descrição**: `obs_min` registra o `(hour, minute)` da última leitura dentro do slot, não a que corresponde à temperatura retida (máx/mín).
- **Impacto**: Inconsistência semântica: o slot representa um período mas `obs_min` aponta para um ponto específico dentro dele → **confusão em análise de dados**.

### 15. **Backtester vs live_bot: min_buy_ask inconsistency** (live_bot.py:??? vs single_entry.py)
- **Localização**: A ser determinada (fixada no "Alteracoes de kimi")
- **Descrição**: Live bot usava `0.20` como fallback, mas `SingleEntry` default é `0.15`.
- **Impacto**: Inconsistência entre backtest e live → **calibração enganadora**.

### 16. **Duplicado max_buy_ask filter** (live_bot.py:???)
- **Localização**: A ser determinada (fixada no "Alteracoes de kimi")
- **Descrição**: Filtro `max_buy_ask` existia tanto em `SingleEntry.evaluate()` quanto no live bot, com o live bot usando `raw_best_ask` (pode diferir do ask no bracket).
- **Impacto**: Inconsistência backtest/live → **decisões de compra diferentes**.

### 17. **Race mode não atualiza session_stats** (live_bot.py:???)
- **Localização**: A ser determinada (fixada no "Alteracoes de kimi")
- **Descrição**: Compras feitas pelo race mode não eram contabilizadas no dashboard.
- **Impacto**: Compras do race não aparecem nas estatísticas → **dados de performance incorrectos**.

### 18. **_bracket_contains_peak edge case consistency** (backtester.py:413-418)
- **Localização**: Linhas 413-418 em `backtester.py`
- **Descrição**: A função já usa o intervalo semiaberto `[lo, hi+1.0)` corretamente para evitar overlap no pico exato.
- **Impacto**: Este foi já corrigido — incluído aqui apenas para confirmar que não há regressão.

## BUGS BAIXOS (4)

### 19. **ceil_slot returns (23,30) for 23:30+** (weather.py:686-687)
- **Localização**: Linhas 686-687 em `weather.py`
- **Descrição**: Para horas 23:30-23:59, `ceil_slot` retorna `(23,30)` (não existe hora 24), significando que o slot ainda não terminou até 24:00.
- **Impacto**: `peak_temp` errado só nos últimos 30 min do dia → **impacto mínimo e limitado nel tempo**.

### 20. **is_plausible_temp margin ±25°C too loose/tight** (weather.py:94-95)
- **Localização**: Linhas 94-95 em `weather.py`
- **Descrição**: A margem fixa de 25°C pode ser demasiado larga para cidades frias (ex: -5°C → limite -30°C, aceitando -10°C como válido) ou demasiado apertada para cidades quentes (ex: Karachi 45°C → 70°C, rejeitando extremos válidos).
- **Impacto**: Falsos positivos/negativos na validação de dados → **peak_temp potencialmente distoado** (impacto limitado).

### 21. **t_min_list length not robustly validated** (weather.py:543)
- **Localização**: Linha 543 em `weather.py`
- **Descrição**: `t_min_list[0] if t_min_list and t_min_list[0] is not None else None` não trata bem casos como `t_min_list = []` ou `[None]`.
- **Impacto**: Erro silencioso se API devolver formato inesperado → **impacto muito baixo**.

### 22. **bootstrap_om_today includes immature current hour** (weather.py:792-793)
- **Localização**: Linhas 792-793 em `weather.py`
- **Descrição**: Filtro `hour <= current_city_hour` inclui a hora actual mesmo que ainda esteja em curso (assumindo rows têm minute=0).
- **Impacto**: `peak_temp` pode conter hora actual imatura → **impacto limitado ao final do dia hora actual**.

## CONCLUSÃO E PRIORIDADES DE FIX

### PRIORIDADE ABSOLUTA (Corrigir imediatamente):
1. **Bug #1** (NameError em plateau_timeout_hours) — **CRÍTICO** — impede o bot de arrancar
2. **Bug #2** (Wind speed None/0.0 confusão) — **CRÍTICO** — mascara falhas de parsing como dados válidos
3. **Bug #3** (Bootstrap_today + floor_slot inconsistência) — **CRÍTICO** — inflação artificial do pico

### PRIORIDADE ALTA:
4. **Bug #4** (Sanity check unidirecional) — **ALTO** — pico pode ser 20°C errado
5. **Bug #5** (Restore não preserva sold_by_stop) — **ALTO** — stop-loss duplicado pós-restart
6. **Bug #6** (check_stop_loss ignora "or higher") — **ALTO** — posições de cauda alta nunca param por stop
7. **Bug #7** (Validação ausente em ceil_slot/floor_slot) — **ALTO** — chaves inválidas causam crash

### PRIORIDADE MÉDIA:
8-14. Os bugs médios listados acima — afetam consistência, precisão ou oportunidades, mas não causam crash directo.

### PRIORIDADE BAIXA:
15-22. Os bugs baixos listados acima — impacto mínimo, edge cases ou efeito limitado nel tempo.

### NOTA SOBRE JA FIXADOS:
Muitos bugs identificados em análises anteriores (CHANGES-17_2.md, CHANGES-17_4.md, "Alteracoes de kimi") já foram corrigidos nos commits recentes, incluindo:
- Consistência de PnL entre backtester e live_bot (_compute_realized_pnl partilhado)
- Fixes de throttle e locks no live_bot
- Correções no backtester loops e hour_min
- Ajustes de date parsing e outros

Este relatório foca nos bugs que permanecem após aqueles fixes.