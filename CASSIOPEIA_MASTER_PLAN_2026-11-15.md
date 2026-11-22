# CASSIOPEIA — Plano-mestre de investigação, dados, treino, calibração e gestão de risco

**Versão:** 1.1 · **Original:** 14 de novembro de 2026 · **Atualização:** 15 de novembro de 2026  
**Projeto:** `~/POLY-MULTI-CITY-V2` · **Estado:** plano de referência, sujeito a validação experimental  
**Decisão norteadora:** maximizar a probabilidade de **crescimento consistente do capital com drawdowns controlados**, não o hit rate isolado nem um P&L espectacular num backtest.


> **Nota de versão 1.1 (15/11/2026):** as secções 1–11 preservam as decisões e o retrato operacional de 14/11. Os valores de espaço em disco, tarefas e estado de processos aí descritos são históricos e NÃO substituem a nova medição. Consultar o **Anexo A**, no final, para as descobertas e prioridades mais recentes; confirmar sempre o estado atual no próprio Ubuntu antes de executar ações.

> **Regra de ouro:** nenhuma alteração aos bots em execução, nem promoção para REAL, sem evidência fora da amostra, verificação da execução e limites de risco explícitos. Um mercado eficiente pode proporcionar oportunidades, mas a vantagem líquida tem de ser demonstrada, não pressuposta.

---

## 1. Objetivo operacional e filosofia

O Cassiopeia acompanha, ao longo de cada dia, observações meteorológicas e cotações das brackets de temperatura máxima da Polymarket.

**Questão central no instante `t`:** «A bracket correspondente ao **máximo acumulado elegível até agora** será a vencedora final? Se sim, conseguimos comprá-la a um ask executável que compense a incerteza e os custos?»

- Privilegiar **poucas operações de elevada qualidade**; não forçar entradas diárias.
- Evitar perdas grandes e sequências de drawdown; medir risco no capital **total**, incluindo posições abertas e correlações entre cidades.
- Exigir simultaneamente **confiança meteorológica calibrada** e **vantagem económica líquida**.
- Preservar a capacidade de **não negociar** quando a vantagem não é suficiente.
- Distinguir **probabilidade de acertar**, **preço pago**, **exposição** e **crescimento composto**.

Para uma posição YES liquidada em $1 quando vence, a expectativa simplificada por share é `EV ≈ p_win − ask − custos`. Por exemplo, pagar $0,90 implica uma assimetria: uma perda de $0,90 apaga nove ganhos de $0,10, antes de custos. Uma taxa de acerto elevada não basta.

**Métricas de decisão, por ordem lógica:**
1. Segurança operacional e ausência de leakage.
2. Vantagem positiva **após** spreads, taxas, slippage e incerteza da previsão.
3. Restrições de drawdown e de exposição (limites numéricos ainda **por definir**).
4. Retorno líquido e regularidade da equity; perdas extremas e sua duração.
5. Hit rate, seletividade, antecedência e hora de entrada como métricas auxiliares.

**Não prometer** curva sempre crescente ou perdas nulas: avaliar distribuições de resultados e caudas de risco.

## 2. Situação real no fecho de 14/11/2026

### Bots (não modificar por causa desta investigação)

| Bot | Configuração | Estado conhecido |
|---|---|---|
| A — Cassiopeia | 34 cidades; PAPER; MAKER | Reiniciado após reboot; motor e logs confirmados |
| B — Andromeda | 8 cidades; PAPER; filtro F1 `p_win>=0.85`; MAKER | Motor e logs confirmados |
| C — Andromeda C | 12 cidades; PAPER; F1 `>=0.85`; TAKER direto, sem MAKER | Motor e logs confirmados; logs separados |
| D — Micro | REAL | **Suspenso**; `live_bot_logs_micro/PAUSED` presente; **não reiniciar** |

Dashboard V2: backend e frontend alterados para incluir C; APIs principais responderam HTTP 200 em Flask test client. Após reboot os motores A/B/C foram recuperados; confirmar estado em execução antes de novas intervenções. **Cutoff global da Dashboard: `2026-11-14T17:23`; cutoff válido de C: `2026-11-14T19:33:53` — não alterar.**

### Arquivo SQLite

- **DB:** `data/polymarket_weather_2026.sqlite` (nome legado; pode conter mercados de outros anos após expansão da descoberta).
- **Tabelas:** `events`, `markets`, `tokens`, `price_points`, `history_chunks`, `book_snapshots`.
- `price_points`: preços históricos YES/NO, **não** o ask histórico garantido.
- `book_snapshots`: bid/ask, tamanhos e níveis de livro observados a partir de agora, com `sampled_at` em epoch UTC.
- **LIVE:** `archive_orderbooks_live.py`, sessão tmux `pm_books`, lista de **34 cidades** de `cities_active.txt`, captura dos mercados locais de hoje/amanhã, intervalo configurado **300 segundos**; observado ciclo completo com **1.496 snapshots = 34 cidades × 2 mercados × 22 tokens** e SQLite íntegra. Isto confirma gravação, **não** que todos os tokens tenham liquidez executável.
- **Orçamento:** teto operacional SQLite + WAL **25 GiB** e reserva de disco livre **8 GiB** (o utilizador permite no máximo ~30 GB; havia ~35,9 GiB livres na medição). Verificar a ocupação e a taxa de crescimento: 1.496 snapshots/ciclo × 288 ciclos/dia ≈ **430.848 snapshots/dia**, se os mesmos mercados/tokens continuarem presentes.
- **LIVE** e **backfill histórico** são processos separados; nunca parar o LIVE para realizar o backfill. Criar alertas de espaço, falhas de API, cobertura e duração dos ciclos. Eventualmente adicionar compressão/retention política **sem apagar dados antes de backup**.

### Descoberta histórica realizada (não confundir com download de preços)

Foi concluído o comando `--mode discover` para **Munique e Lucknow, 2026-03-05 a 2026-11-14**, 255 datas/cidade, **510 verificações**:

- `found = 499` novos, `cached_found = 5`, `not_found = 6`, `error = 0`, `downloaded = 0`.
- Totais **na base**, incluindo alguns mercados futuros fora do intervalo: Munique, 253 datas marcadas `found` (início conhecido 2026-03-05, último conhecido 2026-11-15); Lucknow, 254 datas `found` (início conhecido 2026-03-05, último conhecido 2026-11-16).
- Datas 3–4/03 e diversos dias anteriores deram `not_found` para o **slug consultado**. Isto não demonstra ausência definitiva de mercados sob outras convenções de nomes.
- O download piloto de preços já recolheu ~**76.987 price_points** distribuídos por dias selecionados de março/novembro. **Os ~500 eventos descobertos não tiveram os preços integralmente descarregados.**
- O download de 05/03/2026 revelou preços com intervalos em torno de 300 segundos, com jitter; o token pode começar a cotar **dias antes** da data do mercado. Não filtrar historicamente apenas o dia da liquidação.

---

## 3. Estratégia de dados — separação de recolha, discovery e backfill

### 3.1. LIVE: manter **todas as 34 cidades**

**Prioridade absoluta:** recolher bid/ask reais e profundidade **antes de se perderem**.

- Manter `pm_books` com 34 cidades em intervalos de ~5 min, confirmando que cada ciclo cabe nos 300 s e avaliando eventuais lacunas.
- Persistir `timestamp UTC de consulta`, `timestamp da própria API` quando existir, token/bracket, top-of-book, tamanhos, todos os níveis, estado do livro, event/market ID e fonte.
- Nunca tratar `NULL bid/ask` como bid/ask de valor zero; distinguir livro vazio, mercado fechado, token não consultado e erro HTTP.
- Evoluir para snapshots mais frequentes **nas horas críticas** e WebSocket para mudanças de preço/livro, com snapshots periódicos para reconciliação. A possibilidade de usar WebSocket fica sujeita a teste prático.
- Monitorizar alterações das regras, quantidade de mercados por cidade/dia, limites de API e disco; **não** guardar segredos nos logs ou comandos.

### 3.2. Discovery histórico: expandir para **as 34 cidades totais**

Já estão pesquisadas 2 cidades; restam **32 cidades** para a mesma janela. Fazer **apenas discovery** primeiro, com barras Rich de progresso e ETA, sem saturar o disco com séries de preços.

- Janela inicial: `2026-11-14 → 2026-03-05` (255 dias/cidade). No modo das 34, ~**8.670 verificações** no total; para as 32 ainda não varridas, até ~**8.160** consultas, menos o que estiver em cache.
- Depois, procurar regressivamente períodos anteriores a março de 2026, em lotes e com segunda estratégia de pesquisa (Gamma por series/metadata) para detectar slugs alternativos.
- **Não parar ao primeiro dia `not_found`**, nem considerar automaticamente 30 dias vazios como prova; marcar estado de confiança e fazer verificação por outra via.
- `cached_found` e `cached_not_found` devem permitir retomar após interrupções; poder revalidar os `not_found` com `--retry-missing` quando fizer sentido.
- Preservar identificadores, regras de liquidação originais e o JSON da Gamma. A descoberta apenas encontra mercados, não gera preço histórico nem book.

### 3.3. Backfill de preços: primeiro qualidade em Munique e Lucknow, depois expandir

- **Fase-piloto:** descarregar a cinco minutos os contratos `found` das duas cidades, incluindo os dias de abertura anteriores ao evento e eventual pós-fecho. Monitorizar taxa de erros, lacunas, resposta de API, ocupação e latência.
- **Fase de expansão:** avançar para as **32 restantes**, por lotes, **apenas depois da avaliação de espaço**. O teto de **25 GiB** pode ser insuficiente para 34 cidades × muitos meses × YES/NO; preferir cobertura útil e manutenção do LIVE a “completar” tudo a qualquer custo.
- Resoluções alternativas (30m/3h/12h) quando 5m indisponível, marcadas **como séries distintas**; nunca apresentar interpolação como preço observado.
- Usar controlo de taxa, retries/backoff, transações curtas, índices e WAL; não executar vários backfills de escrita concorrentes na mesma DB sem coordenação.
- Manter as métricas de cobertura por cidade/dia/token e `history_chunks.status`: `ok`, `empty`, `error`; `empty` não equivale a mercado inexistente.
- Melhorar a política de armazenamento (compressão/parquet/segmentação) **antes** de atingir o teto, sem quebrar a integridade referencial e sem interromper `pm_books`.

### 3.4. Fontes meteorológicas comparáveis

Reconciliar, **por instante real de publicação** e estação/fonte:

1. **METAR/NOAA/Aviation Weather**: observações elegíveis e frequência efetiva; distinguir METAR de rotina e special reports segundo o contrato.
2. **Weather Underground (WU)**: séries e observações históricas, proveniência da estação, data de publicação e eventuais revisões.
3. **“OpenStats”**: **confirmar a identidade exata** da fonte mencionada antes de integrar (não assumir que é Open-Meteo, OpenStat ou outra).
4. **Previsões disponíveis naquele instante** (quando houver arquivos de forecast issue-time), climatologia e outras fontes experimentais.
5. **Polymarket**: preços YES/NO históricos e bid/ask **efetivamente observados**; a fonte de liquidação **pode variar por contrato**.

Exigir UTC, fuso local IANA, data local do evento, hora de observação **e** hora de disponibilidade/publicação; as-of joins que nunca selecionem informação futura. Guardar valor original e transformações de temperatura/precision/rounding. Extrair settlement final **oficial** por bracket.

---

## 4. Auditoria crítica ao `cassiopeia_train.py` atual

O atual REBOUND define `label = 1` se o máximo das **seis observações seguintes** exceder `running_max + 0.3 °C`. `label = 0` quer dizer «não houve tal rebound nessa janela», **não** «a bracket do máximo acumulado já ganhou definitivamente». Uma janela de seis linhas só significa ~3 h com amostragem regular de 30 min.

**Pontos obrigatórios de revisão:**

- [ ] **Trocar/alargar target:** prever o resultado **final elegível da bracket**, conforme as regras de liquidação; o `0.3°C` atual não coincide necessariamente com a fronteira de arredondamento. Guardar o REBOUND 3 h como modelo auxiliar/baseline.
- [ ] **Candidate bracket:** usar o **máximo acumulado elegível** e a função oficial `bracket(value)`; não a temperatura instantânea após uma descida.
- [ ] **Splits por dia completo e por tempo**, não somente por índices de linhas: impedir contaminação entre slots do mesmo dia.
- [ ] **Seleção de modelos:** não escolher vencedor pelo AUC do teste final; seleção em treino/validação e **teste final intocado** / walk-forward externo.
- [ ] **Expanding prior:** assegurar que `seasonal_peak_prior` em treino e replay só usa dias completos anteriores e que a versão do prior é coerente com o período de avaliação. O mapa final não deve retroagir para datas antigas.
- [ ] **Janelas finais incompletas:** não atribuir negativos artificiais, mas também não excluir sistematicamente as últimas horas do treino do **pico final**.
- [ ] **Features com missing/default:** auditar valores artificiais de humidade, nuvens, pressão, vento, UV e features degeneradas; registar flags de dados ausentes e diferenças treino/live.
- [ ] **Integridade temporal/meteorológica:** observar timezone, DST, arredondamento/slots e densidade de dados; evitar duplicados e mistura de estações.
- [ ] **Precisão probabilística:** além de AUC, medir Brier, Log Loss, curva de calibração e fiabilidade por hora/cidade/estação.
- [ ] **Inferência live vs treino:** lista efetiva das features, versão dos modelos, loaders e serialização; testar replays causalmente válidos.

Arquivos implicados: `cassiopeia_train.py`, `predictor.py`, `cassiopeia_predictor.py`, `cities/config.py`, `cassiopeia_backtester.py`, `phase4_rerun.py` e calibrador (confirmar caminhos exatos antes de editar).

---

## 5. Nova arquitetura de modelos e hipóteses

Criar um **projeto experimental paralelo**, sem substituir artefactos dos modelos PAPER atuais. Não supor que modelos complexos vão bater um baseline simples.

| Braço | Features | Pergunta |
|---|---|---|
| **W — Weather-only** | METAR/WU/outras, hora local, máximo e tendências, previsões issue-time | Qual a probabilidade de a bracket atual vencer? |
| **M — Market-only** | séries YES/NO, distribuição de preços por bracket, momentum, spread/depth quando observados | O que o mercado já sabe e como evolui? |
| **H — Hybrid** | W + M, somente features contemporâneas | Existe ganho adicional face a W e M? |

**Target primário:** `win_bracket_at_t = 1` se a bracket `B(max_elegível_até_t)` for igual à bracket vencedora oficial `B(max_final)`. Alternativa mais rica: distribuição de probabilidades para **todas as brackets**, em vez de um simples binário.

**Targets auxiliares:** probabilidade de subida >x em 1/3/6 h, quantis do máximo final, tempo esperado até à última subida relevante.

**Features a investigar (sem assumir utilidade):**

- `probability_above_running_max_bracket`, `market_peak_probability`, `probability_entropy` / concentração da distribuição.
- Variações de preço nos últimos 5/15/30/60 minutos, tempos de reação do mercado a METAR e divergência entre probabilidades meteorológicas e implícitas.
- Bid/ask real, spread, profundidade executável por preço, desequilíbrio do livro, cancelamento/alteração entre snapshots, indicadores de liquidez.
- Divergência WU–METAR–terceira fonte, atrasos de publicação, mudanças de pressão, vento e nebulosidade, intervalo entre observações e tempo restante até ao fecho local.

**Regra temporal:** `feature_time <= decision_time` **e** `available_at <= decision_time`. O label/resolução só entra como verdade futura, nunca como feature. Não fazer *join* de snapshots livres com dados de meteorologia revistos posteriormente sem rastreio temporal.

**Limitação de arquivo:** no histórico antigo há preços, **não há necessariamente bid/ask**. Comparar braços sobre intersecções de cobertura. Treino híbrido com books deve começar com *forward paper* e validação temporal verdadeira; não inventar preços de execução.

---

## 6. Calibration: deixar de otimizar apenas `%Hit`

Manter o modo `hit_rate` como **baseline** e implementar um novo modo experimental orientado para **risco ajustado**, sem alterar o fluxo atual.

1. **Probabilidade calibrada:** considerar `p_win` e intervalo/conservadorismo de incerteza, validação da calibração em blocos temporais.
2. **Filtro económico:** entrar apenas se `p_win_conservadora − ask_executável − custos_estimados > margem_de_segurança`.
3. **Filtro temporal:** evitar entradas demasiado tardias/caras; não antecipar sem confiança.
4. **Seletividade:** selecionar apenas oportunidades boas; nenhum requisito de operar todos os dias ou em todas as cidades.
5. **Gestão de capital:** risco por posição, máximo por cidade, correlação/grupo de cidades, exposição simultânea, perda máxima diária/semanal e travões de drawdown.
6. **Objetivo de otimização:** crescimento líquido sujeito a limites de risco, não hit rate, AUC ou lucro bruto isolados.

**KPIs:** precisão das trades, Brier/LogLoss, expectancy líquida, P&L por share e por capital, rentabilidade composta, **Max Drawdown**, **Ulcer Index**, Calmar, pior dia/semana/mês, duração de drawdown, dispersão por cidade/regime, frequência de trades, hora de decisão e *time-to-price-reaction*.

**Os limites exatos** (MaxDD tolerado, orçamento de risco, número de posições/dia, dimensão do capital) **ainda não estão decididos**; defini-los antes de promover uma estratégia a REAL. Não extrapolar diretamente do hit rate por slot para o hit rate de decisões independentes.

**Validação sem sobreajuste:** walk-forward temporal por dias completos, treino/calibração/seleção separados, teste externo intocado, bootstrap por blocos de dias, análise de mudança de regime e de dependência entre cidades. Testar baselines: climatologia, hora do dia e modelos simples, W, M, H e estratégia atual. Incluir *no-trade days* nos resultados.

---

## 7. Backtester e simulação de execução

**Objetivo:** simular a experiência de um bot que só conhece o passado no instante t.

- Reproduzir cronologicamente as observações, verificar a bracket candidata e calcular features sem olhar em frente.
- Escolher **uma política pré-registada** para entradas múltiplas e para situações em que o máximo acumulado muda.
- Distinguir três níveis de evidência: (a) hit meteorológico, (b) preço histórico indicativo, (c) **execução simulada com bid/ask e depth realmente capturados**.
- Modelar spread, custos, slippage, fila MAKER, fill incompleto, indisponibilidade e latência. Um trade no último preço histórico **não é** necessariamente executável.
- Marcar equity a mercado, incluir posições abertas e concentração; testar cenários de gaps e eventos meteorológicos inesperados.
- Reconciliar a liquidação com as **regras originais de cada contrato** e a sua estação elegível. Se a verdade de liquidação não estiver confirmada, não contar esse contrato como acerto.

**Testes de aceitação mínimos:** ausência demonstrável de leakage, integridade dos splits e datas, preços/asks etiquetados corretamente, métricas por cidade e no agregado, quantificação de piores períodos, precisão e edge conservadores fora da amostra. Definir previamente critérios numéricos para promoção a PAPER shadow e a REAL.

---

## 8. Ordem de execução recomendada

| Fase | Ação | Resultado esperado | Critério de passagem |
|---|---|---|---|
| **P0 — Feito** | Arquivo bid/ask LIVE 34 cidades | `pm_books` + SQLite | 34 cidades com snapshots por ciclo e controlo de disco |
| **P1 — Agora** | Discovery 34 cidades (as 32 restantes; Munique/Lucknow cached) | Catálogo de mercados até março/nov 2026 | Erros HTTP/SQLite explicados, cobertura por cidade/dia |
| **P2 — Agora/seguinte** | Backfill 5m **Munique/Lucknow** | Séries YES/NO; quality report | Chunk coverage, datas, jitter, disponibilidade da API |
| **P3** | Expandir backfill às restantes cidades em lotes | Arquivo histórico amplo | Consumo de disco mantém-se <25 GiB e livre >8 GiB; custo/qualidade justificados |
| **P4** | Pesquisar mercados pré-março/2026 e slugs alternativos | Início histórico verificável | Sem confundir `not_found` com inexistência definitiva |
| **P5** | Construir dataset causal e settlement labels | Fonte de verdade reproduzível | As-of joins, versões/estação, ausência de leakage |
| **P6** | Reescrever targets + modelos W/M/H paralelos | Experiências reproduzíveis | Melhoria honesta vs baseline no teste externo |
| **P7** | Nova calibração de risco e execução | Política seletiva | Edge líquido robusto, drawdowns aceitáveis fora da amostra |
| **P8** | Shadow/PAPER multi-cidade com métricas de execução | Evidência prospectiva | Performance e estabilidade sustentadas |
| **P9 — condicionada** | Rever eventual promoção para REAL | Exposição mínima + travões | Decisão explícita após P8, nunca automática |

### Sequência operacional imediata (sem tocar nos bots)

1. **Confirmar `tmux pm_books`**, cobertura 34/34, ausência de erros repetidos e espaço livre.
2. Adaptar `pm_history_reverse_rich.py` para aceitar as 34 cidades de `cities_active.txt`, com **backup**, validação de inputs e Rich por cidade + total; iniciar em modo `discover` (não baixar preços de 34 cidades cegamente).
3. Executar o `backfill` a 5 min de **Munique/Lucknow** para os 255 dias já descobertos; preservar resultados em chunks, com interrupção/retoma e ETA.
4. Medir tamanho real/volume esperado antes de fazer 32 cidades adicionais; ajustar batches/resoluções e política de compressão se necessário.
5. Só depois iniciar auditorias de treino/calibração; manter `D` suspenso.

---

## 9. Riscos, armadilhas e anti-objetivos

- **Hit rate elevado pode perder dinheiro**, especialmente com ask próximo de $1.
- **AUC alto do REBOUND 3 h não prova** identificação correta da bracket final.
- **Leakage:** prior histórico, splits por linhas, previsões publicadas depois, preços de fecho ou features de settlement usados retroativamente.
- **Mercado eficiente:** o preço implícito pode já incorporar toda a informação meteorológica; exigir edge líquido empiricamente.
- **Mudanças de fonte de liquidação e arredondamento:** guardar regras de cada evento, sem uniformizar contratos incompatíveis.
- **Histórico sem asks:** nunca classificar último trade histórico como melhor preço comprável.
- **Generalização:** dias, cidades e condições meteorológicas correlacionados; milhares de snapshots não são milhares de contratos independentes.
- **WAL/concorrência e taxa API:** evitar downloads concorrentes não coordenados, observar SQLite busy/locked e HTTP 429.
- **Disco:** 34 cidades LIVE + backfill intensivo podem atingir 25 GiB depressa; reservar 8 GiB ao sistema; não parar a recolha urgente nem apagar dados sem plano de retenção.
- **Segurança:** não alterar `ERA_CUTOFF`, cutoff C, BOTS, D/REAL ou directórios de logs durante investigação.
- **Sem garantia de retornos:** rentabilidade e drawdowns futuros podem divergir significativamente dos testes.

## 10. Checklist de fecho por sessão

- [ ] `pm_books` ativo, último ciclo completo, cobertura/erros/disco verificados.
- [ ] A/B/C PAPER e D PAUSED confirmados quando relevante.
- [ ] Dados novos etiquetados com fonte, instantes e resolução; métricas de cobertura atualizadas.
- [ ] Nenhum `not_found` interpretado sem verificação alternativa.
- [ ] Nenhuma métrica de lucro calculada com preços de execução inventados.
- [ ] Alterações de scripts acompanhadas de backup, teste de sintaxe e execução em piloto.
- [ ] Resultados de calibração registados com período de treino/validação/teste e versão dos dados.
- [ ] Plano-mestre atualizado com decisões, evidências, falhas e próximos passos.

---

## 11. Registo de decisões

| Data | Decisão | Estado |
|---|---|---|
| 14/11/2026 | Objetivo é **equity crescente e drawdowns controlados**, não `%Hit` isolado | Fixo |
| 14/11/2026 | Dados meteorológicos + mercado; testar W, M e H; target de bracket final | Planeado |
| 14/11/2026 | LIVE 34 cidades, snapshots bid/ask + books, ~5 min | Implementado e observado |
| 14/11/2026 | Histórico começou com Munique e Lucknow; pesquisa regressiva | Discovery 255 dias/cidade concluída |
| 14/11/2026 | **Expandir discovery às 34 cidades**, mas fazer backfill pesado gradualmente | Próxima ação |
| 14/11/2026 | SQLite até **25 GiB**, preservando **8 GiB** livres | Limite de segurança |
| 14/11/2026 | D REAL permanece PAUSED, sem promoção automática | Fixo |

**Manutenção:** este documento é a referência das próximas sessões. Não substituir evidências por suposições; quando um detalhe técnico não estiver confirmado, marcá-lo como **a verificar**.


---

# Anexo A — Evidência e prioridades de 15/11/2026 (handover Codex)

**Fonte:** resultados de comandos locais executados pelo utilizador, com outputs partilhados na conversa. Não supor que os dados, serviços ou scripts permanecem inalterados. Tudo o que não foi diretamente verificado é hipótese ou tarefa.

## A.1. Último estado conhecido

- **Disco:** `/dev/nvme0n1p2`: 234G total, 209G usados, **13G livres**, **95% ocupado**. Não iniciar novos backfills de preços ou operações SQLite pesadas sem rever espaço. O arquivo SQLite `data/polymarket_weather_2026.sqlite` tem cerca de **22,8 GiB**; teto operacional anteriormente acordado **25 GiB**; preservar pelo menos **8 GiB livres**. Não executar `VACUUM`, cópias integrais SQLite no mesmo filesystem, grandes ficheiros temporários ou down­loads de 34 cidades por iniciativa própria.
- **Bots/serviços**: snapshot de 14/11 dizia A/B/C PAPER ativos, D/Micro REAL suspenso e `pm_books` em tmux a recolher orderbooks de 34 cidades (~5 min). Confirmar status antes de agir. **Nunca** iniciar D, matar tmux, interromper coletores, mexer em cutoffs/dashboard, mudar credenciais ou lógica dos bots sem aprovação explícita.
- **Fonte meteorológica METAR original:** `historic_metar/munich.csv` — 250.492 observações, último UTC `2026-11-15 06:50:00`; `historic_metar/lucknow.csv` — 145.893 observações, último UTC `2026-11-15 07:00:00`. Incremental de 2026 via IEM `fetch_year`/`convert`, mesclado por timestamp, preservando registos existentes. Backups `.bak_20261115_073902` e `.bak_20261115_073927` em `historic_metar/`.
- **Resampling METAR 30 minutos** executado com `metar_resample_30min.py munich lucknow`: `historic_metar_30min/munich.csv` — **470.434 slots** e ~42M; `historic_metar_30min/lucknow.csv` — **403.674 slots** e ~36M. São slots reamostrados com forward-fill; **não** são observações reais independentes. Para timings causais preferir reportes originais e instante de disponibilidade quando conhecido.
- **WU**: `historic/munich.csv` até 2026-07-18 21:50 UTC, `historic/lucknow.csv` até 2026-07-19 18:00 UTC. `WU_API_KEY` existe no ambiente local. Endpoint V2 PWS `/v2/pws/history/all` com `stationId=EDDM` e `date=20260720` deu **HTTP 200, zero observações**. O V3 historical hourly 1day que existe em scripts atuais não permite selecionar automaticamente qualquer dia de julho–novembro. **Não dizer que WU já está atualizado; não importar METAR por cima de WU nem trocar features sem compatibilização.**
- **IEM API**: 25/04/2026 reportes de rotina VILK recebidos; pedido adicional de SPECI recebeu **HTTP 429**. Evitar insistência cega, respeitar rate-limit.
- **Polymarket arquivo:** tabelas verificadas: `events` (`city`, `market_date`, `slug`, ...), `markets` (`market_id`,`city`,`market_date`,`bracket`,`raw_json`,...), `tokens` (`token_id`,`market_id`,`outcome`), `price_points` (`token_id`,`ts`,`fidelity_minutes`,`price`,`source`). Índices `markets(city,market_date)`, `tokens(market_id)`, `price_points(token_id,ts,fidelity_minutes)` (PK), `price_points(ts)`. Continuar usando consultas `mode=ro`, `PRAGMA query_only=ON`, filtro por token_id e tempo; evitar scans globais, grandes materializações ou writes. Preços 5m **não são asks executáveis**.
- **Arquivo histórico de preços:** na última contagem operacional conhecida 22/34 históricos de cidades processados, 12 incompletos. Recontar cuidadosamente antes de repetir downloads. Separar descoberta de metadata (event found) de cobertura real de `price_points` (5m) e `book_snapshots` LIVE.

## A.2. Auditoria de WU vs METAR — Munique e Lucknow

**Comparação total em timestamps coincidentes:**

| Métrica | Munique | Lucknow |
|---|---:|---:|
| WU timestamps únicos | 289.510 | 225.284 |
| METAR timestamps únicos | 250.492 | 145.893 |
| Timestamps coincidentes | 157.829 | 109.499 |
| Igualdade de temperatura em pares válidos | ~100% | 99,92% |
| Erro absoluto médio da temperatura | 0,0001 °C | 0,0015 °C |
| Erro absoluto médio da humidade | 0,2070 p.p. | 0,2435 p.p. |
| Erro absoluto médio da pressão | 52,6421 hPa | 14,6130 hPa |

**Conclusão condicional:** temperaturas WU e METAR são praticamente idênticas nos timestamps coincidentes, sobretudo em 2026; **não são fontes independentes nesses registos**. Entretanto, a cobertura é distinta e as outras variáveis não são diretamente intercambiáveis. A forte diferença em pressão pode refletir definições/unidades/referências diferentes e requer auditoria antes de misturar features.

**Máximos diários locais**, 2026-03-05 a 2026-07-17 (dias com pelo menos 20 observações por fonte): Munique **135/135** dias com mesma bracket aproximada; Lucknow **133/134**. Total **268/269 = 99,63%**. Isto não prova que os restantes dias, regiões, estações, eventos ou **regras oficiais** coincidam. “Bracket aproximada” usou `floor(Tmax+0.5)`, ainda não validado contra contratos individualmente.

**Divergência única:** Lucknow, **2026-04-25**: WU 46 obs, máximo **42 °C**; METAR 48 obs, máximo **43 °C**. Faltam ao WU duas horas específicas de reporte **05:00 e 14:30 IST**, entre elas o reporte decisivo às 14:30. Todos os valores partilhados nesse dia são idênticos. O reporte de rotina original **`VILK 250900Z 31010KT 5000 HZ FEW100 43/09 Q1003 NOSIG`**, das **09:00 UTC = 14:30 IST**, confirma 43 °C. A metadata Gamma arquivada indica vencedor **43 °C**, consistente com o METAR; confirmar regras/resolução oficiais de cada mercado antes de criar labels de treino.

## A.3. Mini-replay real de preços Polymarket (Lucknow, 2026-04-25)

Script de auditoria usado: `cassiopeia_market_audit_v01.py --cities lucknow --days 2026-04-25` (inspecionar existência e implementação). Replays exploratórios de `price_points` para tokens YES das brackets **42, 43, 44 °C**, fidelidade **5 min**, 54 amostras recuperadas por token na janela explorada. Dados indicativos de preço histórico (último registado em até 10 min) e NÃO garantia de execução/asks.

| Hora IST | YES 42 °C | YES 43 °C | YES 44 °C | Meteorologia |
|---|---:|---:|---:|---|
| 12:00 | 13,5% | **71,0%** | 15,0% | Mín. do máximo observado: 41 °C no METAR das 12:00 |
| 13:30 | 5,5% | **82,5%** | 11,5% | METAR de rotina: 42 °C |
| 14:15 | 12,5% | **80,0%** | 7,0% | — |
| 14:20 | 9,0% | **87,5%** | 6,0% | Antes do METAR 43 °C de 14:30 |
| 14:25 | 8,5% | **86,0%** | 6,5% | — |
| 14:30 | 13,5% | **84,5%** | 3,0% | Observação METAR de rotina: 43 °C; horário de publicação por apurar |
| 14:35 | 10,5% | **87,5%** | 3,5% | — |
| 14:40 | 0,5% | **92,5%** | 4,8% | Forte queda da bracket 42 °C |
| 14:45 | 0,1% | **94,0%** | 7,6% | — |
| 15:00 | 0,1% | **95,5%** | 3,5% | — |
| 15:10 | 0,1% | **99,4%** | 0,5% | — |
| 15:30 | 0,1% | **99,3%** | 0,5% | METAR: 42 °C |

Maior variação observada em células consecutivas de 5m: YES 42 °C **−10 pp** entre 14:35–14:40; YES 43 °C **+7,5 pp** entre 14:15–14:20; YES 44 °C **−5,4 pp** entre 15:05–15:10. Não inferir reação causal exata sem tempo de publicação do METAR, timestamp do preço original, fuso normalizado e livro de ordens histórico. A soma de preços das brackets pode superar 100% e não equivale necessariamente a probabilidades calibradas/consistentes, dado spread, liquidez e asincronia.

**Hipóteses testáveis:** (1) pricing antecipa máximo do dia a partir de forecasts/tendências; (2) sinal não meteorológico ou dados externos disponíveis antes de 14:30; (3) atualização após disseminação oficial do METAR; (4) eventual arbitragem de latência apenas SE asks/depth reais, fees e publicação forem verificáveis. Sem esses elementos, o replay mostra a evolução informativa do mercado, **não P&L realizável**.

## A.4. Discovery de estratégias e abordagem científica

Preservar o plano-mestre W/M/H e acrescentar braços de investigação isolados:

- **Prediction-first:** classificador probabilístico, calibrado, da **bracket vencedora final** (ou distribuição por bracket), não confundir com `REBOUND > 0.3°C em 180min`. Avaliar previsão meteorológica e risco residual do máximo acumulado.
- **Early anticipation / price reaction:** testar quantitativamente *time-to-price-reaction*, probabilidade de acertar antes do METAR decisivo, lead/lag com publicação e spread; diferenciar movimento antecipatório de reação mecânica.
- **Price–weather disagreement:** entrar apenas em sinais conservadores onde `p_weather` calibrada excede ask executável + custos + margem; testar estratégias NO, reversões e movimentos entre brackets apenas se houver dados e política ex-ante.
- **Microstructure:** usar orderbook LIVE (bid, ask, tamanho/depth, spread, liquidez, fila/impacto) em forward paper; comparar MAKER vs TAKER, custos de execução, seleção adversa e fills parciais. Não retroprojetar snapshots de novembro a mercados de março.
- **Risk-first:** poucas posições, tamanho conservador, limites de concentração entre cidades e eventos, stop por risco/MaxDD, comparar retornos líquidos e **equity composta** sob walk-forward temporal. `No-trade` é um resultado válido e conta na estatística de decisão.
- **Baselines:** climatologia, persistência do máximo, previsão weather-only, market-only, híbrido, bots atuais A/B/C. Pressupor mercado eficiente até evidência contrária.

**Critérios de ciência aplicada:** dataset versionado, contrato/settlement por cidade/dia, disponibilidade temporal real, estatísticas por *contrato/dia* em vez de milhões de slots dependentes, walk-forward, holdout externo intacto, custos conservadores, análise de séries ruins, sensibilidade aos parâmetros, correlações entre cidades, intervalos de incerteza e robustez a missing meteorológico.

## A.5. Ordem de trabalho para a PRIMEIRA sessão de Codex

1. **Ler primeiro** `AGENTS.md` (se presente), `CODEX_HANDOVER_2026-11-15.md` e ESTE plano completo. Descobrir também qualquer plano, journal, README, mapa do repositório, regras de negócio e documentação existentes, sem os sobrescrever.
2. **Auditar somente em leitura:** `git status`, tmux/processos LIVE/PAPER, `df -h .`, tamanho do SQLite e WAL, últimas linhas dos logs relevantes, scripts/diretórios existentes, tabelas/índices via SQLite read-only, progresso REAL de 34 cidades, cobertura por token/dia.
3. Apresentar um **mapa factual do repositório** e reconciliar divergências entre o retrato de 14/11 e 15/11. Distinguir encontrado, suspeito, ausente. Não deduzir estado da runtime apenas deste handover.
4. Propor **experimento isolado** para medir cobertura/settlement, *lead-lag* meteo/mercado e capacidade prognóstica W/M/H, primeiro Lucknow 25/04 e Munique com dias de controlo, seguido de todas as datas com preços. Emular decision time + known available_at; mostrar incertezas.
5. **Pedir aprovação** antes de qualquer alteração de código, geração volumosa, chamadas de API em massa, upgrade de dependências, nova tarefa demorada ou alteração de bots e serviços. Escrever logs e resultados experimentais em diretório separado e pequeno, depois de verificar espaço e `.gitignore`.
6. Atualizar plano-mestre e log de experimentos com evidência de cada execução; priorizar métricas de edge líquido, MaxDD e equilíbrio retorno/risco sobre AUC/hit rate isolados.

**Do-not-touch:** processo `pm_books` e bot A/B/C sem necessidade e aprovação; D REAL `PAUSED`; SQLite writer e seus WAL/SHM; `historic/` e `historic_metar/` originais; produção, credenciais `.env`, cutoffs de dashboard; os históricos de preço em curso. Não aplicar otimizações pesadas, compactação, exclusão ou reprocessamento automático.

## A.6. Questões ainda abertas (não inventar)

- Identidade da fonte oficial de settlement, hora de publicação e regras de arredondamento para **cada contrato**; `Gamma` pode mudar após a resolução.
- Quais forecasts foram realmente publicadas antes de cada decisão, incluindo issue-time e latência.
- Disponibilidade bid/ask histórica versus `price_points` de 5m; snapshots LIVE começam apenas na data de recolha.
- Origem exata dos ficheiros WU e diferenças de estação/unidades para pressão e humidade; os valores idênticos de temperatura não tornam fontes equivalentes.
- Estado e conteúdo dos scripts que tiveram mudanças noutros chats; o Codex deve inspecionar o disco, não assumir que um ficheiro existe.
- Configuração efetiva de taxas, limites de capital e MaxDD ainda não decididos; **não** sugerir promoção a REAL só com backtest.
