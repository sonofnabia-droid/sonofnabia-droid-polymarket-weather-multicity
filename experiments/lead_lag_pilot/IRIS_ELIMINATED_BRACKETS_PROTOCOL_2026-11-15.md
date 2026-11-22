# IRIS — protocolo confirmatório de brackets eliminadas

**Versão:** 0.1 · **Registado:** 15/11/2026 · **Estado:** protocolo de investigação, não executado

IRIS é a linha de teste de disponibilidade da informação meteorológica e reação do mercado. Este documento congela uma proposta para investigação prospectiva. Não inicia recolha, altera serviços, envia ordens ou toca nos bots PAPER A/B/C; D/REAL continua suspenso. Os 99 eventos históricos usados para formular a hipótese ficam apenas em discovery e nunca contam como validação independente.

## Pergunta e âmbito

Quando uma leitura meteorológica **elegível segundo o contrato e já recebida/publicada** eleva o máximo diário acima do teto de uma bracket, o mercado continua a cotar YES dessa bracket acima de zero ou NO abaixo do payout de $1 por tempo suficiente para haver valor económico?

Objetivo: testar se o sinal pode complementar Cassiopeia como confirmação de risco/mercado. O teste não substitui a previsão W/M/H, não altera o target Cassiopeia e não considera uma bracket eliminada apenas porque um CSV retrospectivo contém uma temperatura mais alta.

## Unidade e definição do evento

Uma observação independente é um **cidade-dia**; várias brackets do mesmo dia são correlacionadas e ficam agrupadas nessa unidade para inferência.

1. Congelar, antes de ver os preços/outcome, a descrição completa Gamma do contrato, `resolutionSource`, fonte primária/fallback, estação, fuso, janela local, precisão e regras de revisão.
2. **NOAA/Weather.gov:** usar a coluna oficial `Temp` para todo o dia e precisão indicada no contrato. Distinguir a fonte primária do fallback Weather Underground e registar qual fonte realmente determinou o settlement. Não inferir isso apenas pelo URL de `resolutionSource`.
3. **Weather Underground:** exigir que a página/série consultada corresponda à estação exata nomeada no contrato. Distinguir história/observação da previsão diária: campos como `temperatureMax` e `validTimeLocal` do endpoint forecast não são máximos realizados nem provam uma nova observação. Arquivar, quando a fonte o disponibilizar, payload bruto, ID da estação, timestamp/validade do reporte, máximo diário e revisões; registar também request start, response received UTC e cabeçalhos temporais. Se a página só expuser máximo diário acumulado, o primeiro response recebido que mostre o valor acima do teto é o instante conservador em que o consumidor local o conhece; não atribuir publicação anterior sem prova.
4. **AWC:** contar apenas METAR de rotina elegível. Aplicar o grupo de temperatura T quando existir, senão a temperatura no corpo; excluir SPECI; converter timestamp para o dia local do aeroporto; arredondar ao inteiro mais próximo com metade para cima; conservar correções até ao limite especificado pelo contrato.
5. O evento começa no primeiro instante em que a fonte indicada como efetivamente usada no contrato fornece uma leitura elegível cujo máximo acumulado, segundo a resolução do contrato, excede estritamente o teto da bracket. Leituras já acima do teto no primeiro ponto observado do dia são censuradas à esquerda e excluídas.
5. `obsTime`, hora do lote, `collected_utc`, `updatedAt`, `closedTime` e `umaEndDate` não substituem hora de publicação/receção. `receiptTime` só pode ser usado depois de validar a sua semântica para a fonte/endpoint.

**Disponibilidade conservadora:** registar a hora UTC após a resposta HTTP que primeiro contém o reporte elegível, além da hora do servidor e do campo temporal do próprio reporte. Isto prova quando o consumidor local já tinha acesso, não necessariamente o primeiro instante em que a informação ficou pública. Se não existir timestamp fiável da resposta, o evento não é causalmente elegível.

## Observações de mercado

Usar apenas dados já recolhidos pelo `pm_books` existente, sem o reiniciar ou alterar. Para o token YES e NO da bracket eliminada e da bracket fronteira (a que contém o máximo elegível corrente), guardar timestamp por token, best bid/ask, tamanho do melhor nível e níveis completos.

- Baseline exploratório: último snapshot anterior à disponibilidade, idealmente entre −15 e −5 minutos.
- Reação: primeiro snapshot posterior à disponibilidade, depois +5, +10 e +15 minutos. Identificar sempre hora real do snapshot; não confundir corte nominal com idade do quote.
- Para comparações entre tokens, exigir amplitude temporal ≤60s no mesmo corte. Reportar separadamente quantos eventos ficam excluídos por falta de book, snapshot stale ou skew.
- As amostras de `price_points` podem ser mostradas como contexto, nunca como ask, bid, liquidez ou fill.
- **Sem fill presumido:** testar o NO com ask disponível e profundidade observada. Calcular custo por níveis para um tamanho fixo de 1 share e também para uma ordem mínima especificada no contrato; aplicar a tabela de fees vigente/arquivada para esse mercado. Se o tamanho não estiver todo disponível, reportar fill parcial/zero, sem completar com preço médio ou book futuro.

## Comparações e métricas

**Hipótese de microestrutura:** após disponibilidade comprovada, YES eliminado cai e NO correspondente sobe, relativamente à bracket fronteira que ainda pode vencer. Reportar mudanças em níveis e em diferença-em-diferenças; placebo pré-evento −30 a −15 minutos; distribuições medianas, médias, quantis e bootstrap agrupado por data local. Não deixar várias brackets do mesmo evento contarem como amostras independentes.

**Hipótese económica:** uma decisão de NO só é candidata se o ask e a profundidade posteriores à disponibilidade permitirem custo total abaixo do payout, após fees e um haircut de latência/slippage pré-registado. Comparar com no-trade, Cassiopeia sem filtro, líder de mercado e W/M/H nas mesmas cidade-datas. Medir cobertura, retorno líquido por oportunidade, capital exposto, drawdown e resultados por cidade/fonte. Não otimizar preço máximo de entrada no holdout.

## Separação e critérios de interpretação

- O período histórico March–November já foi inspecionado e não serve como validação independente.
- Reutilizar o calendário congelado em `PROTOCOL_FUTURE_2026-11-16.md`: primeiros 40 dias locais elegíveis desde 16/11 para desenvolvimento; 20 seguintes permanecem holdout intocado. Congelar a implementação e este protocolo no fim do desenvolvimento antes de abrir qualquer outcome do holdout. Agrupar por data local para bootstrap; não dividir brackets do mesmo dia entre blocos. Se o holdout tiver poucos eventos elegíveis para uma conclusão, reportar inconclusivo; não estender/reselecionar datas depois de ver rótulos.
- Falta de fonte elegível, publicação verificável, livro posterior ou settlement rastreável torna o evento inelegível; publicar cobertura e motivo da falta. Não preencher ausências com zero.
- A amostra só pode ser chamada repetível depois de uma replicação independente em eventos/datas novos, com resultado líquido conservador positivo e sem dependência de poucas datas/cidade. Hit rate ou reprecificação histórica não são critério suficiente.
- Mesmo uma confirmação de preço não autoriza alteração de Cassiopeia, PAPER, cutoff, sizing, serviço ou execução REAL. Qualquer integração futura exige decisão separada após revisão dos resultados concretos.

## Lacunas verificadas antes deste protocolo

Nos 25 cidade-dias PAPER, 20 URLs Gamma primárias apontam NOAA e cinco AWC; o máximo METAR local concorda com o bracket final Gamma em 24/25. A divergência Lucknow 06/09 (31°C Gamma vs 37°C local) foi excluída. O restante histórico usado na reação de preços tem `price_points`, não orderbooks. `book_snapshots` não tinha dados para os 550 tokens destes dias.

Nos 1.036 cruzamentos WU Munich/Lucknow (16/03–17/07), o `resolutionSource` aponta WU. Máximos WU locais concordam com o winner Gamma indicado em 263/264 cidade-dias encontrados. Lucknow 25/04: a fonte Gamma e `cities/config.py` apontam a estação VILK; o CSV WU local salta 14:30, enquanto `historic_metar` VILK observa 43°C nesse instante e Gamma indica 43°C. A leitura mais provável é uma observação omitida pelo CSV, ainda sem snapshot bruto da página WU. `forecast_benchmark/wu_raw.jsonl` guarda previsões e `collected_utc`, não observações realizadas/`receiptTime`; não satisfaz o requisito de disponibilidade. A replicação de preços não tem books históricos nos 2.490 token-dias selecionados.

`forecast_benchmark/metar_raw.jsonl` contém `receiptTime` aninhado no bruto apenas para obs dates 13–15/11, sem intersecção com aqueles 25 cidade-dias. `collected_utc` é registado antes dos pedidos HTTP e `receiptTime` ainda não está validado como instante de publicação. Os CSV `historic_metar/` não preservam T-group, marca SPECI, resposta bruta nem hora de receção. Assim, o estudo retrospetivo não satisfaz a definição de evento elegível deste protocolo.

Auditoria de viabilidade dos livros, leitura read-only de tokens específicos em 14–15/11: `book_snapshots` guarda `sampled_at`, best bid/ask e tamanhos, mas não timestamp do servidor nem `src`; a PK/index é `(token_id,sampled_at)`. Nas 22 outcomes por evento em 14/11, Lucknow não tinha snapshots; Munique tinha 814 linhas, 407 com bid e 407 com ask (nenhuma linha com ambos). Em 15/11, Lucknow tinha 5.148 linhas, 3.541 com bid, 3.541 com ask e 1.934 com ambos; Munique 4.928, 3.738, 3.738 e 2.548, respetivamente. Cadência intrasséries mediana 300s e lacunas internas até 11.374s. São apenas estes dois dias parciais; não garantem a mesma cobertura futura nem execução. Queries posteriores devem sempre filtrar primeiro por `token_id` e depois por `sampled_at` para aproveitar o índice composto; evitar filtros temporais isolados que varram a tabela.

**Próxima fase:** uma análise de viabilidade read-only dos snapshots existentes e dos metadados por token/dia, com filtros pela PK composta, seguida de um esquema isolado de registo que não toque nos serviços. A instrumentação de hora de resposta/publicação não está autorizada por este documento e permanece fora de âmbito.
