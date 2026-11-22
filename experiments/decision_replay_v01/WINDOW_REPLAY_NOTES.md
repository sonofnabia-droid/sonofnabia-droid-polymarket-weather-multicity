# Replay e janelas de entrada — Seoul e Panama

**Data da análise:** 16/11/2026  
**Âmbito:** auditoria local de logs; nenhum bot, serviço, configuração, dashboard ou dado de origem foi alterado.  
**Mínimo de preço:** fora do âmbito desta continuação, conforme decisão do utilizador. O critério de ask 0,75–0,90 abaixo é apenas o intervalo existente usado para comparar inícios de janela, não uma otimização do mínimo.

## 1. O que os logs explicam nos dois exemplos

### Seoul — 16/11 local

- O ficheiro contém 728 ticks. O dia começa às 06:00 locais, com máxima acumulada de 8°C.
- Às 13:05, a máxima acumulada passa a 17°C; o ask registado para essa bracket era 47¢. Ainda estava antes da janela ativa 14–18.
- Às 13:35, a observação sobe a 18°C. O ask registado para a bracket de 18°C era 93,5¢, acima do limite configurado de 90¢.
- Às 14:00, esse ask era 94,8¢. Logo, nesse replay, a combinação observável de início às 14h e ask máximo 90¢ não permitiria entrada nesse momento.
- Os ticks registam `p_ensemble`, mas não `p_rebound` nem o motivo de rejeição quando não existe ação. Não é possível afirmar se o modelo rejeitou o sinal, qual era a probabilidade real usada pelo gate, ou se uma janela às 12h/13h teria produzido uma entrada elegível.
- Há ticks com livro CLOB e profundidade, mas também preços de origem Gamma. A presença de um book não prova que uma ordem teria sido preenchida ao preço indicado.

**Conclusão do caso:** existe uma explicação operacional plausível para a oportunidade não ter sido considerada: o máximo 18°C surgiu antes das 14h e o ask já excedia o teto. Não se pode atribuir a decisão ao modelo com os logs atuais. O `p_ensemble` visível na dashboard não é substituto de `p_rebound`.

### Panama City — 16/11 local

- O ficheiro contém 318 ticks. O máximo registado chegou a 32°C; a série depois desceu, sem retirar esse máximo acumulado.
- Foram emitidos sinais Cassiopeia com `p_rebound` no texto de `reason`, abaixo de 0,35, para a bracket 32°C. Às 12:32 locais, `p_rebound=0,09`, ask 20¢, bid 3¢ e profundidade agregada de asks de $17,44; às 12:41, `p_rebound=0,27`, ask 21¢, bid 15¢ e depth de asks $22,36. A origem do alvo estava marcada `clob` nesses dois ticks.
- Os logs de execução examinados indicam bloqueio pelo mínimo de ask 60¢. Isto explica por que o sinal não se transformou em compra; não é uma falha do modelo em gerar candidato.
- Mais tarde o preço de mercado passou a favorecer 31°C, apesar de a máxima meteorológica do tick permanecer 32°C. O winner oficial de 16/11 não estava disponível no cache consultado. É necessário reconciliar o grupo METAR elegível, a fonte/regra exata do evento e a liquidação oficial antes de classificar 32°C como vencedora ou o estado visual da dashboard como settlement.

**Conclusão do caso:** o bloqueio efetivo conhecido é o preço mínimo. O sinal muito barato não deve ser reintroduzido como oportunidade sem confirmar bracket vencedora e execução; a análise preliminar de 15 casos abaixo de 60¢ foi fraca e foi retirada da agenda de otimização, por decisão do utilizador.

## 2. Comparação exploratória de janelas em Seoul

Uma análise anterior dos 68 dias Seoul com resultado oficial disponível selecionou, em cada dia, o primeiro tick horário do máximo acumulado cuja cotação-alvo estava no intervalo 75–90¢. É uma comparação de cobertura/consistência da bracket, não um backtest Cassiopeia: não aplica `p_rebound`, não prova executabilidade, e a maioria dos quotes históricos não tinha origem CLOB + profundidade verificável.

| Início hipotético | Dias com candidato 75–90¢ | Bracket alvo venceu | Dias com CLOB + depth exatos |
|---:|---:|---:|---:|
| 12h | 46 | 44 (95,7%) | 1 |
| 13h | 44 | 42 (95,5%) | 1 |
| 14h (atual) | 37 | 36 (97,3%) | 1 |

Como referência sem filtro de preço, a bracket do máximo acumulado coincide com o winner oficial em cerca de 16% dos casos à primeira observação horária das 12h, 34% às 13h, 60% às 14h e 84% às 15h. Essa subida é compatível com o mercado e a informação meteorológica a resolverem incerteza ao longo do dia; não significa que a janela tardia tenha melhor EV depois do ask pago.

### Interpretação

- Passar o início de 14h para 13h acrescenta sete dias com uma cotação na banda estudada; de 14h para 12h acrescenta nove. Na amostra, esses dias adicionais incluem mais erros absolutos de bracket, e não há verificação de CLOB/depth suficiente para medir um resultado económico.
- A elevada taxa de acerto condicional à banda 75–90¢ é compatível com seleção pelo próprio preço. Tem de ser comparada com o retorno implícito e com a regra de mercado, não apenas com hit rate.
- A configuração ativa da cidade usa 14–18h. O modelo tem amostras meteorológicas desde hora 12, mas isso não prova que a pipeline live possa fornecer um `p_rebound` válido, causal e suficientemente calibrado desde as 12h.
- O calibrador existente pesquisa `min_hour` e `max_hour` no CSV meteorológico e pode usar holdout temporal; o argumento `entry_price` é um preço fixo para o backtester, não uma série histórica de asks com bid/ask e profundidade. Portanto, essa calibração não reconstrói por si só o gate de execução real.

## 3. Plano recomendado para o teste seguinte de janela

1. **Preservar o gate de preço e os restantes parâmetros ativos.** A única variável experimental será a hora de início.
2. **Braços shadow/PAPER comparáveis:** janela atual 14–18 como baseline; variantes 13–18 e 12–18. Não alterar o bot de produção.
3. **Guardar a cada tick** `p_rebound` do Cassiopeia, `p_ensemble` com nome semântico próprio, `start_hour/end_hour`, todos os gates com pass/fail/reason, bracket selecionada, origem e idade do quote, bid/ask e níveis/depth, e se houve tentativa/fill.
4. **Target e informação causal:** temperatura elegível por fonte, observation time, publication/availability time, timezone, transformação/rounding e regra/estação de settlement daquele contrato.
5. **Avaliar por dia completo** com o winner oficial: cobertura de oportunidades, Brier/LogLoss do target final se existir, P&L líquido executável ou cenários conservadores, MaxDD e exposição; baseline de mercado no mesmo timestamp. Não contar cada snapshot como amostra independente.
6. **Validação:** os 68 dias Seoul já inspecionados são exploratórios. Pré-registar variantes/métricas e avaliar primeiro em período posterior intocado; depois acompanhar PAPER prospectivo. Se os resultados forem avaliados repetidamente, reservar novo holdout.

## 3A. Experiência separada: stake por banda de preço

O teste pedido percorre 35–90¢ com a grelha **[0,35–0,50): $1; [0,50–0,60): $2; [0,60–0,75): $3; [0,75–0,90]: $4**. É diagnóstico contrafactual, sem alteração de bots/configuração.

Há uma restrição path-dependent importante: `CassiopeiaEntry` permite uma entrada por cidade/mercado. Portanto, os braços do replay não podem somar uma compra em cada faixa como se fossem independentes. O simulador toma a primeira ação Cassiopeia com ask CLOB no espectro e não compra de novo; essa entrada antecipada pode impedir uma compra posterior mais cara. Compara:

1. **Espectro, $1 fixo:** primeira ação no intervalo 35–90¢, uma entrada.
2. **Espectro, stake variável:** a mesma primeira ação e outcome do braço anterior, stake por banda.
3. **Gate atual, $1 fixo:** primeira ação que passa o min/max ativo da cidade.
4. **Gate atual, stake variável:** a mesma primeira entrada do braço 3, stake pela banda.

Os braços 1–2 isolam stake mantendo a decisão/entrada idêntica; a comparação 2 vs 4 mistura entrada mais cedo e stake, por isso não é “efeito puro” da curva. Qualquer entrada abaixo do mínimo ativo só existe no replay contrafactual, não no bot/PAPER.

Para cada braço, calcular shares e fills simulados na ladder observada, P&L bruto, fees, P&L líquido, ROI sobre capital gasto, percentagem de contratos e dias lucrativos, profit factor, Sharpe/Sortino de retornos diários e MaxDD. A profundidade top-five é limite superior de fill, não garantia. Sharpe/Sortino numa amostra de poucos dias são descritivos e instáveis. O estudo deve reportar distribuição e diferenças emparelhadas por dia, não escolher uma schedule por melhor número.

O relatório executado está em [`STAKE_SPECTRUM_DIAGNOSTIC.md`](STAKE_SPECTRUM_DIAGNOSTIC.md); os eventos e braços estão em [`stake_spectrum_events.csv`](stake_spectrum_events.csv). Os outcomes vêm do cache local e não foram auditados independentemente contra a fonte oficial. Não se usa `p_rebound` como probabilidade final `p_win`.

## 4. Lacunas de instrumentação que o replay expõe

- `p_rebound` e rejeição por gate não são persistidos em todos os ticks sem ação; isso impede reconstruir retrospectivamente a decisão real do Cassiopeia.
- O dashboard combina visualmente `p_ensemble` com um threshold de Cassiopeia, embora o gate use `predict_rebound_prob` em separado.
- “RESOLVIDO” na interface pode ser uma heurística baseada em ask próximo de 1, não a confirmação de resultado do contrato.
- Ticks de mercado e snapshots meteorológicos estão sincronizados por log, mas falta prova completa de availability/publication da observação meteorológica e de fill no CLOB.

## 5. Artefactos

- `index.html`: visualização local interativa para os dois dias, sem dependências externas.
- `build_replay.py`: construtor read-only a partir dos JSONL já existentes. Remove token IDs e não consulta nem escreve na SQLite.

