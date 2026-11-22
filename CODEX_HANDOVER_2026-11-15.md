# CODEX — START HERE (15/11/2026)

## Para que serve este handover
O projeto foi investigado extensamente numa conversa ChatGPT externa ao Codex CLI. **Não existe importação automática da conversa:** este documento e o plano-mestre versionado são o registo explícito de contexto. O repo local é a fonte de verdade sobre o código e o estado dos serviços.

## Ler obrigatoriamente
1. `AGENTS.md` (instruções persistentes; se já existir um ficheiro próprio, mesclar instruções sem o sobrescrever).
2. `CASSIOPEIA_MASTER_PLAN_2026-11-15.md` (texto completo do plano original de 14/11 + **Anexo A** com atualizações de 15/11).
3. Outros README, planos e logs de discovery existentes no repo. Identificar se há um master anterior; nunca apagar nem sobrepor sem autorização.

## Resumo de alta prioridade
- Missão: desenvolver estratégias para brackets de máxima diária da Polymarket com edge líquido verificável, poucas trades, risco/MaxDD controlados. Modelos W/M/H e novas hipóteses de antecipação e reação dos preços.
- 34 cidades. A/B/C PAPER e `pm_books` LIVE em funcionamento no último snapshot; D REAL suspenso. Não interferir. Base SQLite ~22,8 GiB, espaço livre 13 GiB (95% ocupado). Não fazer backfill pesado, VACUUM, alterações WAL nem downloads em massa.
- Munique e Lucknow: METAR nativo atualizado até 15/11/2026 e reamostrado a 30m. WU só até julho. Temperatura coincidente em ~100% dos timestamps partilhados, mas cobertura e outras features diferem. 268/269 dias com mesma bracket aproximada.
- Anomalia Lucknow 25/04/2026: WU não tem reporte 14:30 IST de 43°C, METAR de rotina VILK `250900Z` tem. Gamma identifica 43°C. Replay YES 43°C: 71% 12:00; 87,5% 14:20; 84,5% 14:30; 92,5% 14:40; 99,4% 15:10. **Preço histórico 5m NÃO é ask**, e `METAR valid time` não é publicação. Não declarar latência ou lucro ex-ante sem provas.

## Primeira tarefa sugerida — somente leitura
Lê os 3 documentos de contexto, verifica `git status`, espaço em disco, processos, scripts e a cobertura real de dados usando queries SQLite **indexadas e read-only**. Reconcili­a as prioridades do plano de 14/11 com os resultados de 15/11. Entrega um diagnóstico factual, riscos e uma proposta concreta para o primeiro experimento isolado (lead-lag Lucknow 25/04 e extensão multi-dia com validação causal). **Não alteres ainda scripts, bots, dados, SQLite, serviços, ficheiros originais ou configurações.** Pede aprovação antes de implementar.

## Estratégias que NÃO podem desaparecer do roadmap
- Weather-only / Market-only / Hybrid, target da bracket final, previsão dos quantis do máximo diário e REBOUND auxiliar.
- Backfill/discovery sob limites de espaço; pipeline causal por fonte e contrato; resolução oficial; label de evento.
- Early anticipation, price reaction, weather-market disagreement, book microstructure, maker/taker, seleção ex-ante, controle de custos e drawdowns.
- Calibração Brier/LogLoss, p_win conservadora, limite de exposição e risco por grupo, no-trade, walk-forward temporal, teste externo intocado, multi-cidade e PAPER prospectivo.

## Regra de comunicação
Comunicar em português de Portugal, ser factual, desconfiar de métricas excessivamente boas e separar **facto verificado**, **inferência** e **hipótese a testar**. Primeira interação deve ser uma auditoria, não uma implementação.
