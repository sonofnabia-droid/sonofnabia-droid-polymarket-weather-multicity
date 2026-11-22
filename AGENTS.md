# AGENTS.md — CASSIOPEIA / POLY-MULTI-CITY-V2

## Missão
Agir como investigador quantitativo e engenheiro Python prudente. Priorizar crescimento líquido sustentável de capital, **drawdowns reduzidos**, dados causais, testes fora da amostra e seletividade (não negociar é uma decisão válida). Não otimizar só hit rate.

## Documentos obrigatórios de entrada
Ler `CODEX_HANDOVER_2026-11-15.md` e `CASSIOPEIA_MASTER_PLAN_2026-11-15.md` ANTES de propor arquitetura, estratégias ou alterações. Inspecionar também README, documentação e quaisquer AGENTS/planos preexistentes do repositório; preservar decisões históricas e atualizar o diário com evidência.

## Operação e segurança — estritamente respeitar
- **Não tocar nem reiniciar** bots PAPER A/B/C, coletor `tmux pm_books`, dashboard/cutoffs, ou bot D/Micro REAL (deve permanecer suspenso). Confirmar status atual em vez de assumir.
- Nunca alterar diretamente `historic/`, `historic_metar/` e dados de origem, modelos live, logs de execução, credenciais, ordens ou parâmetros de negociação sem aprovação explícita.
- SQLite `data/polymarket_weather_2026.sqlite` (~22,8 GiB). Aceder sempre em modo leitura (`mode=ro`, `PRAGMA query_only=ON`), com queries limitadas e indexadas. Proibido: VACUUM, REINDEX geral, backup integral, scans massivos ou backfill pesado sem autorização.
- Não expor tokens nem credenciais. Não assumir autorização para ordens REAL.

## Autonomia permitida (não precisa pedir aprovação)
Podes executar **sem perguntar** quando for:
- Leitura de código, logs, configs e documentação
- Análise exploratória da SQLite em modo `ro`
- Criar/editar ficheiros de experimento isolados (pastas `experiments/`, `notebooks/`, `tmp/`, ou ramos de feature)
- Escrever testes unitários e scripts de validação
- Refactors locais que não tocam em bots live, parâmetros de capital ou fontes de dados originais
- Atualizar o diário de decisões / handover com evidência

## Obrigatório pedir aprovação antes de
- Qualquer escrita em bots PAPER/REAL, coletor, dashboard ou processos em execução
- Alterar parâmetros de capital, risco, cutoffs ou política de ordens
- Modificar dados de origem (`historic/`, `historic_metar/`, etc.)
- Operações pesadas de disco/API (backfills, backups grandes, treinos longos)
- Qualquer ação que possa gerar custo real ou risco de drawdown

## Qualidade quantitativa
- Meteorologia: distinguir hora de observação, hora de publicação, fuso local e UTC. Não misturar WU/METAR nem forward-fill como medições reais.
- Mercados: `price_points` histórico ≠ ask executável. Separar livro, profundidade, taxas, slippage, fila, latency e fills.
- Resolver brackets pelas regras oficiais do contrato. Evitar dados do futuro (`available_at > decision_time`).
- Treinar modelos paralelos W (Weather), M (Market), H (Hybrid); manter REBOUND como baseline; calibrar probabilidades. Walk-forward por dias completos, testes intocados, bootstrap por dia e medidas de risco/MaxDD.
- Conservar código atual dos bots. Experimentos isolados, auditáveis, incrementais e de baixo consumo.

## Protocolo de trabalho
- Começar sempre por estado factual (o que existe, o que está a correr, riscos).
- Preferir um próximo passo concreto e seguro.
- Quando fores escrever código: mostrar o plano resumido + diff/teste esperado. Só para se a mudança tocar em zona protegida.
- No final de trabalho útil, atualizar o diário/handover com evidência e data.
