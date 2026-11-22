# Adendo prospectivo — features temporais × ladder/orderbook

**Registado:** 16/11/2026. Adendo ao `PROTOCOL_FUTURE_2026-11-16.md`; não modifica os H1–H3, o corte primário das 15:00, nem os primeiros 40 dias de desenvolvimento seguidos dos 20 dias de reserva. Não foram consultados labels, preços, vencedores ou resultados a partir de 16/11 para redigir este adendo. A reserva permanece intocada.

## Pergunta e ordem de avaliação

Pergunta secundária: informação sobre hora local, estado térmico de plateau e dinâmica da ladder/orderbook melhora a probabilidade da bracket vencedora final, ou ajuda a rejeitar entradas fracas da Cassiopeia PAPER?

1. O alvo primário de W/M/H é a **distribuição calibrada da bracket final vencedora**. A probabilidade de nova subida futura é auxiliar REBOUND e não substitui esse alvo.
2. O benchmark M é a distribuição YES do mercado, normalizada apenas quando a ladder está completa e temporalmente coerente. Reportar também líder e preço do candidato atual.
3. W usa apenas meteorologia e hora/localidade; M usa mercado; H combina ambos. Comparar os três nos mesmos contratos, cortes e datas, com os PAPER/Cassiopeia como referência separada.
4. A análise económica requer ask, profundidade, taxas/custos, latência assumida e sensibilidade a fill. `price_points` isolados servem apenas para previsão/triagem, nunca como fills ou P&L executável.

## Cortes, causalidade e features candidatas

- Manter 15:00 local como corte primário do protocolo original. No bloco de desenvolvimento, analisar adicionalmente 09:00, 11:00, 13:00 e 17:00 apenas como cortes secundários predefinidos; não escolher uma hora pela reserva.
- Uma medição meteorológica só entra se a hora de observação e a hora de disponibilidade local forem conhecidas e anteriores à decisão. Para AWC, mapear `obsTime` como observação; conservar `reportTime` separadamente (não o chamar `obs_time`), e `receiptTime` como recibo do serviço AWC, nunca como prova automática da chegada/consumo local. `available_at` exige timestamp local posterior à resposta HTTP efetivamente recebida, ligado a source/station e à observação usada. Se faltar qualquer elo, marcar o corte como não causal e não imputar/forward-fill como observação nova.
- W candidato: hora local cíclica; running max; distância da temperatura atual ao máximo; tempo desde a última nova máxima; warming dos últimos 60–90 minutos; aceleração térmica em intervalos observados de 30 minutos; variabilidade recente; duração de plateau.
- Definição inicial de plateau, a testar apenas no desenvolvimento: sequência consecutiva de observações dentro de 0,5°C do running max, duração mínima candidata 90 minutos, e quebra da sequência perante lacuna >60 minutos ou temperatura abaixo da tolerância. Se forem avaliados outros limiares no desenvolvimento, registá-los todos e congelar um só procedimento antes da reserva.
- M de preços: YES normalizado da ladder completa, rank/líder, diferença candidato–líder, soma de preços acima, retornos do mesmo token a 5/15/30 minutos e aceleração de curto prazo. Timestamps próprios e idade máxima de 10 minutos; sequência temporal incompleta significa feature em falta, não zero.
- M de orderbook, quando houver CLOB completo: spread, melhor bid/ask/tamanho, imbalance de shares nos cinco melhores níveis, microprice, profundidade notional por lado e mudança/refill entre snapshots. A aceleração só pode ser calculada quando existirem pelo menos três snapshots anteriores com timestamps, mesmo token e intervalo validado. Isto mede liquidez mostrada, não fluxo de ordens/fills.
- H: testar interações pré-definidas `warming × retorno da ladder acima`, `aceleração térmica × aceleração do preço candidato` e `plateau × refill/imbalance do book`. Não adicionar interações após consultar a reserva.

## Elegibilidade e estatística

- Uma data é elegível por cobertura/identidade do contrato, nunca por outcome ou preço favorável. Requer label final e regra/fonte de settlement reconciliadas, além de inputs meteorológicos causais. Para H de book, requer os snapshots da ladder necessários no corte e antes dele; faltas são reportadas e excluídas pelas regras técnicas congeladas.
- Agrupar todos os cortes e cidades da mesma data em cada split e bootstrap. Treino, calibrador e avaliação temporalmente separados; não usar `Gamma.updatedAt` nem um embargo fixo como prova de quando o label ficou disponível. Sem timestamp comprovado de disponibilidade do label, declarar a avaliação causalmente inconclusiva.
- Em desenvolvimento, avaliar Brier, log loss, calibração, cobertura/abstenção, resultado por cidade/hora, baseline de mercado, PAPER e drawdown/custos. Congelar fórmulas, seleção, calibrador e limiares antes de abrir qualquer outcome dos 20 dias de reserva.
- A reserva só é aberta uma vez após esse congelamento. Qualquer alteração posterior inicia outro período intocado; nenhum resultado autoriza alteração automática de A/B/C ou de sistemas live.

## Relação com o screen histórico de 16/11

O screen `plateau_price_momentum_screen.py` usa março–julho de 2026, labels expostos, METAR histórico sem `available_at`, price points sem asks e um target binário “candidato METAR vence”. Serve para motivar esta pergunta e testar parsing, não para selecionar thresholds/modelos nem para substituir o alvo multiclass. O período prospectivo iniciado em 16/11 não foi consultado durante o screen.

Revisão de timestamp, 16/11: nos 140 reportes EDDM arquivados de 14–15/11, `reportTime` excede `obsTime` em 600s em metade; nos 140 VILK não há diferença. Como `metar.py::_parse_time` prefere `reportTime`, esta amostra revela risco de o campo repassado como `obs_time` ser até 10m posterior à observação bruta, com assimetria por cidade. O adendo acima fixa a semântica para análise prospectiva; não altera o parser live nem torna os registos históricos causais retroativamente.
