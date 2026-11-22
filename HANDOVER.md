cat > HANDOVER.md <<'EOF'
# HANDOVER — CASSIOPEIA Multi-City Weather Bot
Última atualização: 2026-09-10 · Válido até: execução da D7 final
Companheiro de: BUGS_PENDENTES.md (registo cronológico — ler os últimos 3 blocos)
Última actualização: 2026-11-08 · era v5 em curso (contrato n=60, §79-§90)

## 0. REGRA DE OURO (§90 — ler primeiro, sempre)
Estratégia = as 4 condições do PITCH.md (threshold · banda · janela · 1/dia).
Bots: A MEDE (paper 34) · B FILTRA (F1 0.85, §85) · D VALIDA (real $1-2, §87).
Tudo o resto — calipso, stairs, makers mortos, patches, eras fechadas — é ARQUIVO
(archive_legacy_20261107/) ou histórico (§1-§89). Nenhum mecanismo novo entra
sem pré-registo aprovado pelo dono. O veredicto da era é n=60 (leitura
intercalar n=30, §90).

## 1. O QUE É O PROJETO (30 seg)
Bot paper-trading no Polymarket (mercados "highest temperature in X on Y").
19 cidades ativas, modelo LGBM por cidade (spec 31 features), gates de ask
0.60-0.85, start_hours locais corrigidos por TZ. Edge previsto OOS: +19% (2026-09-02,
primeiro backtest limpo pós-bug DD/MM/YYYY). Objetivo: acumular amostra honesta →
D7 final → geração v4 → dinheiro real com critérios queimados (secção 6).

## 2. ESTADO OPERACIONAL (verificar sempre no reencontro)
tmux ls                          # esperado: bot (desde 09/09) + collector (10/09)
pgrep -f cassiopeia_live_bot | wc -l   # esperado: 2
grep -c BET_OPEN live_bot_logs/trade_ledger.jsonl  # ~99+ a crescer
Amostra era limpa (>=2026-09-08): 11 resolvidos + 10 abertos em 10/09.
Ritmo ~7/dia → D7 oficial quando >=60 (~16-18/09).

## 3. COMANDOS DE DIA-A-DIA
./venv/bin/python analyze_d7_final.py      # a análise-mãe (fee-aware, normaliza losses antigos)
./venv/bin/python analyze_collector.py --days 12   # mercado real (asks/depth)
./venv/bin/python analyze_collector_v2.py  # cobertura da banda por cidade
./venv/bin/python analyze_3days.py         # análise rápida semanal
Telegram: /resumo (usa outra função do multi-city summary — funcional)

## 4. DECISÕES E CRITÉRIOS PRÉ-REGISTADOS (queimar, não editar)
### D7 final (veredictos V1/V2/V3 — julgam por EV LÍQUIDO, fee weather 0.05×p×(1-p)):
- V1 min_ask: banda 0.60-0.70 EV líq <0 → propor subir 0.65/0.70
- V2 manila (emenda A5b; PACIFIC só tem 1 cidade ativa): >=8 trades, hit<60% → excluir
- V3 banda 0.70-0.80: EV líq <0 → excluir
### GO real-money (A5): TODOS exigidos
1. >=150 trades combinados v3.5+v4; 2. EV líq >= +3pp multi-era; 3. dd era v4 <= $15
4. fee na doc confirmada ✓ (0.05×p×(1-p), maker 0+rebate 25%) e no P&L teórico
5. circuit breaker implementado; 6. Gamma check antes do buy; 7. liquidez collector OK ✓
NO-GO: EV<0 em 2 eras | dd>$20 | mudança regras Polymarket.

## 5. FIXES EM DISCO À ESPERA DE RESTART (ativos no próximo restart)
a) CONTAB: polymarket_clob.py 3 ramos — loss = entry×shares (era -size_usdc → -1.00 flat)
b) TG-ALERT: cassiopeia_live_bot.py chave "threshold" duplicada removida + tg.py guard None
Restart recomendado: SÓ na D7 oficial (não antes — preservar amostra homogénea).
Até lá: losses novos continuam a gravar -1.00 (script normaliza na leitura);
alerta multi-city continua crashar (cosmético, /resumo manual funciona).

## 6. O QUE VEM DEPOIS (por ordem)
### FASE B — D7 FINAL (quando analyze_d7_final.py mostrar >=60)
1. analyze_d7_final.py completo → 2. analyze_collector.py --days 12 →
3. decidir V1/V2/V3 com o marco → 4. registo no doc → 5. RESTART ÚNICO
(leva fixes a+b, /resumo volta honesto) → 6. zerar contagem de amostra (era v4 configs)
### FASE C — GERAÇÃO V4 (após B)
./run_v4_pipeline.sh   # retreino 19 + calibração walk-forward + relatório OOS (~1.5-3h)
Regra: só promove calibrações com validation_oos.approved=true (edge OOS > 0).
### FASE D — INSTRUMENTAÇÃO DO REAL
D0: fix fee model do código real (linear 0.02 → fórmula 0.05×p×(1-p)) — OBRIGATÓRIO pré-E1
D1: circuit breaker (3 dias negativos seguidos → pausa)
D2: Gamma check estado do mercado antes do buy
D3: dossier GO (EV multi-era + collector + dd)
D4: entradas maker/GTC (fee 0 + rebate 25%; risco non-fill)
### FASE E — REAL + expansão
E1: real capital mínimo ($20-50, parcelas $1) — 1ª semana é verificação
E2: upgrade RAM 16G → reativar pool (config das 33 pronto; chongqing já corrigido)
E3: opcionais: ensemble pricing (1h), reviver OM (ver secção 8), Kelly fracional

## 7. ARQUIVO DE DECISÕES DA SESSÃO 10/09 (contexto)
- OM estacionado: mv om_data → om_data_PARKED; FEATURE_COLS restaurado a 31;
  munich 0.9433 (reprodução exata), panama 0.9107. Causas: live sem forecast OM
  (source mismatch) + cobertura OM só 2021+ + panama merge tz-aware (já fixado).
- Contabilidade: losses paper eram -1.00 flat; P&L real da amostra +$0.06 (não -0.96).
- Fee weather descoberta (A4): 0.05×p×(1-p) → amostra atual ~0 líquido;
  banda 0.60-0.65 duplamente penalizada (pior hit + fee mais cara).
- A1: oportunidade concentrada em tel_aviv/madrid/munich/milan/helsinki/warsaw;
  tokyo deserto (4.8%); moscow depth fino ($57 in-band, nota para parcelas reais).
- start_paper.sh: fix do collector (tr ',' ' ' → string comma direto).
- chongqing start_hour 3→15 (resquício TZ).

## 8. SE UM DIA O OM VOLTAR (condições acumuladas)
1. forecast OM real no live (om_cloud/om_radiation do forecast, não fallbacks WU)
2. coleta OM uniforme (om_resilient.py, profundidade 2010+ para todas)
3. D7 fechada
Passos: mv om_data_PARKED om_data → patch_om_train.py já está no train ✓
→ repor om_cloud/om_precip/om_radiation/om_radiation_dev no FEATURE_COLS
→ fix tz-aware já no inject ✓ → retreinar A/B (baseline: 0.9433/0.9107).

## 9. LIÇÕES INSTITUCIONAIS (os padrões que já morderam 2+ vezes)
- TIMEZONE: 4 bugs TZ na história (weather_v3, backtester, merge OM, hour_study).
  Nenhum timestamp entra em lógica sem conversão explícita; CSVs WU são UTC
  (exceto panama: tz-aware!). start_hours vivem em hora LOCAL da cidade.
- FALLBACKS SILENCIOSOS mascaram-se de sucesso (caso panama-OM: treino "verde"
  com features constantes). Regra: falha visível ou falha nenhuma.
- ORDENAR DATAS: nunca confiar em colunas date string (bug DD/MM/YYYY invalidou
  toda a era v1). date = timestamp convertido, sempre.
- N=8 não é estatística (regra >=30/60 trades, min_entries nos grids).
- AMOSTRA HOMOGÉNEA: não mexer em modelos/gates a meio de uma era.

## 10. FICHEIROS-CHAVE
cassiopeia_active_config.json   # 33 cidades (19 ativas via cities_active.txt)
cities_active.txt               # as 19 de elite (limite RAM 7.4G — R7)
analyze_d7_final.py             # a análise-mãe da D7 (fee-aware)
run_v4_pipeline.sh              # fase C inteira num comando (NÃO correr antes da D7)
BUGS_PENDENTES.md               # registo cronológico (R7, S1-15, D8-OM, CONTAB, A1-A5)
city_groups.py                  # PACIFIC/CONTINENTAL/ATLANTIC (fonte única)
om_data_PARKED/                 # OM 15 anos estacionado (ver secção 8)
possible-trash/logs_era_v1/     # arqueologia das eras anteriores
EOF
echo "HANDOVER.md gravado: $(wc -l < HANDOVER.md) linhas"

## 11. NOTA CONFIGS (10/09) — os DOIS mundos de config
- cities/*/strategy_config_*.json = mundo PEAK/SingleEntry (modo "single", INATIVO no live).
  Os win_pct ~92% da _meta deles são de outro desenho (validation=2026) — NÃO comparar
  com os hits da Cassiopeia.
- cassiopeia_active_config.json = a Cassiopeia (o que corre; threshold/start_hours/etc).
- rebound_model_config.json = spec do modelo (feature_cols, min_hour_target...).

## 12. CHAVES QUE O PIPELINE LÊ (validado 10/09 contra ficheiros reais)
- rebound_model_config.json: AUC = chave "global_auc" (get_auc do run_v4_pipeline.sh
  já procura: auc, best_auc, model_auc, global_auc). Outras: best_model, trained_at,
  train_samples, test_samples, pos_rate, feature_cols (31), min_hour_target.
- strategy_config_*.json = mundo peak (ver secção 11) — não usado pelo pipeline v4.

## 13. FONTES DE DADOS DE TRADES (descoberto no P0 da v5)
- live_bot_logs/bets_{city}_{date}.json = a fonte por trade (usada por analyze_3days)
- live_bot_logs/{city}_{date}.json = estado diário por cidade (slots/history)
- paper_positions.json na RAIZ = órfão vazio (PositionManager guarda por log_dir
  de cada instância ClobClient — o multi-cidade V2 não o partilha)
- trade_ledger.jsonl = eventos BET_OPEN/BET_CLOSE (tem realized_pnl_usd/result,
  mas NÃO tem bracket_label nem temp_lo/hi)

## 14. V5-EDGE — P0 FECHADO (11/09), veredicto e lições
- v5_p0_edge_study.py: modelo zero (análogos empíricos) testado nos trades da era limpa
- VEREDICTO: análogos NÃO separam WON/LOST (P~99% para ambos) → fundação empírica
  pura rejeitada; caminho = F1 LGBM quantile com features de regime
- descobertas úteis: push real mediana +0.5, max +1.0 em 17 trades, 50% push<=0
  (rmax na entrada era o pico) → o perigo é o perímetro, não a cauda
- bugs apanhados pelo P0 (5º TZ + 3 outros): CSVs aware (fix padrão tz_convert),
  cidades multi-palavra no split("_"), convenção half-open das brackets nos bets
  (temp_lo==temp_hi==inteiro → largura 1.0), átomo em push=0 nos intervalos
- bets_{city}_{date}.json TEM running_max + peak_temp + bracket (fonte rica p/ F1)

## 15. V5 F1 — FECHADO (11/09): quantile hurdle model PROMOVE COM RESTRIÇÃO
- v5_f1_quantile.py — munich piloto: dataset 36k contexts sintéticos (16 anos),
  hurdle = LGBM classifier P(push>0) [AUC OOS 0.8627, Brier 0.134 vs 0.213 baseline ✅]
  + LGBM quantiles push|push>0 (7750 treino)
- DESCOBERTA ESTRUTURAL: o push tem átomo de ~69% em 0 (rmax já era pico) E
  sub-átomo nos valores pequenos (grão 30-min) → LGBM colapsa taus 0.05-0.55
  no mesmo push previsto. CDF fiável só de F2 >= ~0.44
- GATE B (quantis úteis 0.45-0.95): 5/5 calibrados, erros <=3.7pp ✅
- RESTRIÇÃO documentada no f1_report.json: F2<0.44 = interp linear do átomo
  (erro <=3pp no P final — absorvido pelo threshold de edge no F2)
- lições de percurso: isotonic na val pequena PIOROU (revertido); cobertura
  composta global é inútil como gate com distribuição atómica (usar componentes);
  3 fórmulas de cobertura até a PIT correta (F_i(y_i) <= tau)
- MODELOS: cities/munich/v5_quantile_model/ (quantiles.pkl + atom_classifier.pkl)
- PRÓXIMO: F2 — backtest A/B (gates v3 vs edge-engine) sobre o mesmo período

## 16. V5 F2-a — FECHADO (11/09): mercado EFICIENTE na margem — v5-engine suspende
- v5_f2a_market_eff.py + v5_f2a_fetch_winners.py: 277 resoluções oficiais Gamma
  (cache permanente em live_bot_logs/market_winners.json) × asks do collector
- VEREDICTO pré-registo: NENHUM bin >= +5pp (melhor: 0.80-0.85 = +3.7pp, n=88, IC±7.2)
  → F2-b não corre; v5 como "edge engine" suspensa honestamente
- 3 achados: (1) mercado eficiente nas 35 cidades (−1.6 a −4.7pp = spread do MM);
  (2) favorito-longshot fraco (0.75-0.85 positivo, coerente com os nossos 4W/0L);
  (3) O SINAL DO MODELO VALE +2.8pp (marginal −2.3pp vs condicional +0.5pp nos trades)
- CAMINHO PARA +3pp (A5): maker entries (+1.3pp) + banda 0.75+ (evitar fee-fodder)
  + sinal condicional (+2.8pp) → v5-F1 recicla como FILTRO de entrada (não engine)
- NOTA: amostra = 11 dias, snapshots autocorrelacionados; collector acumula para re-teste
- estes números alimentam o V1 da D7: min_ask 0.75 é agora candidato com evidência

## 17. V6 ROADMAP APROVADO (11/09) — ver V6_ROADMAP.md
- filosofia do dono: máx WINRATE + equity curve suave > volume/EV bruto
- concentração: 4-5 cidades motor (por dados, na V6.2) sobre diversificação
- sizing: Kelly fracional (0.25x, cap 5% bankroll) com winrate-20 como constraint
- dual-track: bot A (v4, 19 cidades, canal atual) vs bot B (v6, 5 cidades,
  canal TG novo + .env2) — torneio 4-6 semanas/100 trades, critérios em V6_ROADMAP §5
- V6.1 (treino F1 ×34) aprovado — corrível em paralelo à era v4 paper,
  fora das janelas de trading; NADA corre antes da D7+restart+v4
- ficheiro-mestre: V6_ROADMAP.md (princípios queimados §0)

## 18. DUAL-TRACK (11/09): Cassiopeia (A) vs Andromeda (B)
- Bot A = Cassiopeia: v3.5-gates, 19 cidades, canal TG atual, start_paper.sh
- Bot B = Andromeda: v6-filtro p_win>=0.82 (F1 hurdle quantile), 10 motor
  (munich,madrid,paris,seoul,sao_paulo,shanghai,taipei,singapore,moscow,istanbul),
  canal TG novo (@polymarket_weather_2bot), start_paper_v6.sh, logs em live_bot_logs_v6/
- V6.1 fechado: F1 ×36 treinadas; 20 aprovadas (v6_approved_cities.txt)
  [reprovadas notáveis: milan, london, tel_aviv, helsinki, amsterdam, warsaw]
- v6_filter: fail-closed duplo (sem modelo OU gate_pass=false → bloqueia);
  teste funcional PASSOU (munich 87.9%, milan None)
- infra: V6_FILTER env-gated no live bot; CASS_LOG_DIR parametrizável;
  slots_so_far + prev7(history_max) nas features
- torneio: 4-6 semanas/100 trades (V6_ROADMAP §5); veredicto em §5

## 19. AUDIT MULTI-ESTAÇÃO (11/09) — ferramenta permanente + 1º veredicto
- v5_station_audit.py + cruzamento com {city}_history_max.json (163 dias-cidade)
- HEADLINE 27% mismatch é CONTAMINADO: ~13 do dia 02/09 = dias parciais da era
  restart TZ (bot morria de manhã → history_max incompleto)
- caso Helsinki 06/09 RESOLVIDO: WU 16.0 vs oficial 15 vs OM 15.4 → estação
  WU/PWS de helsinki lê +0.6-0.8 vs a régua oficial (o LOST de 06/09 era isto)
- suspeitas de viés real: helsinki, mexico_city (+2°C ×2 — PWS já suspeita no
  BUGS_PENDENTES), karachi (+1.2)
- regra nova: audit mensal obrigatório pré-A5; cidade com viés sustentado
  = exclusão antes de stakes grandes
- lição: history_max de dias com bot down = dias parciais → marcar era-restart
  nos dados ou filtrar por direção (WU << oficial = buraco, não estação)

## 19. AUDIT MULTI-ESTAÇÃO (11/09) — ferramenta permanente + 1º veredicto
- v5_station_audit.py + cruzamento com {city}_history_max.json (163 dias-cidade)
- HEADLINE 27% mismatch é CONTAMINADO: ~13 do dia 02/09 = dias parciais da era
  restart TZ (bot morria de manhã → history_max incompleto)
- caso Helsinki 06/09 RESOLVIDO: WU 16.0 vs oficial 15 vs OM 15.4 → estação
  WU/PWS de helsinki lê +0.6-0.8 vs a régua oficial (o LOST de 06/09 era isto)
- suspeitas de viés real: helsinki, mexico_city (+2°C ×2 — PWS já suspeita no
  BUGS_PENDENTES), karachi (+1.2)
- regra nova: audit mensal obrigatório pré-A5; cidade com viés sustentado
  = exclusão antes de stakes grandes
- lição: history_max de dias com bot down = dias parciais → marcar era-restart
  nos dados ou filtrar por direção (WU << oficial = buraco, não estação)

## 21. RESGATE DAS PRESCAS + LEDGER SEPARADO (12/09)
- 14 posições prescas da era restarts (08-10/09) resolvidas com resolução
  OFICIAL Gamma: 12 settle + 2 skip (tokens sem bracket no mapa bets)
- settle_stuck.py v3: brackets via token_id→bets (ledger OPEN não as tem!),
  cache+fetch com retries — 3 iteracções de diagnóstico até à verdade
- impacto na amostra: 12→24 resolvidos; D7 encurta (~16-17/09)
- LEITURA HONESTA: batch resgatado 6W/6L (50%) → EV total −8.5pp líq
  (o +2pp anterior era só o batch bom). Veredicto real só com 60.
- BUG descoberto em cascata: trade_ledger.py hard-coded — ambos os bots
  escreviam no MESMO ledger → fix CASS_LOG_DIR no ledger + restart Andromeda
  (o D7 verdict fica limpo: só trades da Cassiopeia contam)
- lição: mensagens de skip mentiam ("sem resolução" = na verdade "sem bracket
  no ledger") — sempre imprimir o motivo REAL

## 22. A SAGA DA KEY WU (12/09) — causa raiz de TODAS as falhas bootstrap
- a "API key" era a public key do SITE Wunderground (scraped do JS da página)
- keys públicas de frontend ROTAM periodicamente → quando rodam, os bots
  ficam cegos (401 CDN-0001) sem aviso nenhum
- a saga: reboots → autostarts sem a key (nunca esteve em ficheiro) → 401 em
  tudo → 4914 falhas → fail-closed protegeu (0 trades cegos) ✓
- FIX PERMANENTE: key legítima (Weather Data Services, grátis 1000/dia) no
  .env (WU_API_KEY) + wu_key lê os.environ no CityState
- NOVAS REGRAS: credenciais vivem no .env NUNCA no shell/ficheiro-scrapped;
  alarme automático se >20 falhas bootstrap seguidas (evitar dias cegos)

## 23. BUG ÓRFÃOS NO RESTART (12/09) — resolvido
- start_paper_v6.sh matava "v6bot" (nome tmux) mas o python filho sobrevivia
  como ÓRFÃO: tradeava + fazia polling → conflicts infinitos + risco de dupla
  contagem no ledger (não chegou a acontecer: 0 trades do B até agora ✓)
- descoberta: conflicts 17→20→27→32 a subir + caça por environ do token
- FIX: pkill por CMDLINE das cidades únicas do B (antes do tmux kill)
- start_paper.sh já era seguro (pkill genérico cassiopeia_live_bot)
- lição: matar processos por NOME DE SESSÃO não mata filhos; matar sempre por
  cmdline do processo real

## 25. SAGA TG-CONFLICT — FECHADA (12/09): send-only venceu
- 2 dias de caça (token, órfãos, openclaw/systemd) — TODOS reais mas NENHUM
  era o ladrão final: testes de isolação provaram (token virgem + Andromeda
  morta → 5× getUpdates OK) que o conflito era INTERNO ao processo
  (duplo updater / ciclo retry auto-alimentado no python-telegram-bot)
- CURA ESTRUTURAL: Andromeda SEND-ONLY (V6_NO_POLLING=1 — sem getUpdates,
  conflicts impossíveis por construção); menus interativos só na Cassiopeia
- trade-off documentado: Andromeda envia alertas ✓ mas não recebe comandos;
  dados dela via alertas + scripts (analyze_d7_final etc.)
- infra deixada: V6_NO_POLLING inline no tmux · wu_key_guard nos arranques
  + cron diário · trade_ledger respeita CASS_LOG_DIR · pkill por cmdline

## 26. O DIA CEGO + O REBOOT ESQUECIDO (12/09) — causa raiz humana
- 11/09: reboot da máquina (humano) SEM relançar os bots — o dia INTEIRO
  sem trading (forense: 0 temps nos ticks, 2078 oportunidades de banda ignoradas)
- o autostart @reboot EXISTIA no crontab mas falhou silenciosamente
  (linha duplicada + sem log = não sabemos se correu)
- forense analyze_dead_day.py provou: a banda EXISTIA (tel_aviv 82%, istanbul 73%)
  — não era mercado seco, era bot ausente
- FIX: crontab limpo (1 linha @reboot) → start_all_bots.py (idempotente, lança
  A+B, testado à mão); startup.log agora persiste
- custo: 1 dia de amostra D7 (desliza para ~18-19/09)
- LIÇÃO MESTRA: "o maior risco do projeto não é código — é o humano que reboota
  e não repõe os bots". Defesas: autostart testado + wu_key_guard 07:00 + backup
- pendência: monitor de "bots mortos" (se tmux não existir às 09:00 → alerta TG)

## 27. SUITE DE REGRESSÃO COMPLETA (12/09): 17/17
- test_regression.py: 8 fixes históricos + 9 v6 (D0 fee×4, D1 breaker×2,
  D2 gamma, D4 maker×2, v6_filter×2)
- qualquer refactor futuro → pytest vermelho antes de produção
- warnings sklearn (feature names) documentados — inofensivos, polish futuro

## 28. DRY-RUN V4 VERDE (13/09) — pipeline provado ponta a ponta
- dryrun_v4_pipeline.sh munich: backup→treino→calibração walk-forward→relatório
  OOS→RESTAURO (zero rastos na produção)
- treino: LGBM AUC 0.9433 (reprodução exata ✓)
- CALIBRAÇÃO OOS: 862 entradas, hit 84.45%, edge +24.45pp → APROVADA
  (o formato que a v4 usa para promover nas 19)
- leitura: o SINAL é forte (+24pp OOS); a lacuna live-vs-backtest (~-24pp)
  é execução/asks/timing — por isso D4 maker e banda fina são as alavancas
- CRONOLOGIA da quarta confirmada: D7 (~16/09) → decisões → restart único
  → run_v4_pipeline.sh ×19 → rever relatório → promoções aprovadas → era v4

## 28. DRY-RUN V4 VERDE (13/09) — pipeline provado ponta a ponta
- dryrun_v4_pipeline.sh munich: backup→treino→calibração walk-forward→relatório
  OOS→RESTAURO (zero rastos na produção)
- treino: LGBM AUC 0.9433 (reprodução exata ✓)
- CALIBRAÇÃO OOS: 862 entradas, hit 84.45%, edge +24.45pp → APROVADA
  (o formato que a v4 usa para promover nas 19)
- leitura: o SINAL é forte (+24pp OOS); a lacuna live-vs-backtest (~-24pp)
  é execução/asks/timing — por isso D4 maker e banda fina são as alavancas
- CRONOLOGIA da quarta confirmada: D7 (~16/09) → decisões → restart único
  → run_v4_pipeline.sh ×19 → rever relatório → promoções aprovadas → era v4

## 29. AUDIT DE CÓDIGO (13/09) — ruff+radon+greps dirigidos
- SEGURO: .env/.env2 removidos do git tracking (estavam desde 4550774;
  token 2bot já revogado, risco histórico baixo)
- BUG REAL apanhado e corrigido: F821 session_stats fantasma no gancho D1
  (eu próprio, ontem) → CB-2 estava MORTO (decorativo). Fix: 
  record_global_city_total() soma dailies por cidade → dd global real.
  TESTADO: dd 16>=15 → pausa total ✓
- E999: zero (sintaxe toda válida nos nossos)
- mapa complexidade (para refactor v4.1, NÃO agora): _tick_city 280,
  main 271, buy_yes 45, TG.dashboard 43
- higiene para v4.1: ~40 F401/F841, 574 bare excepts (maioria legítima),
  143 prints → unificar logger
- LIMPO: zero tokens hardcoded, zero iterrows no hot path, time.sleep só 1
- ferramentas instaladas: ruff 0.16.7, radon 6.0.1

## 30. AUDIT backtester.py (13/09) — o mundo PEAK decifrado
- backtester.py = backtester do mundo PEAK/SingleEntry (NÃO da Cassiopeia)
- ORIGEM dos "92% win/894 trades" do strategy_config: backtest contra
  SimulatedMarket (asks SIMULADOS climatologicamente) — circular, não
  comparável com hits da Cassiopeia (mercado real). Ignorar nas decisões.
- TAKER_FEE 0.02 linear "só lucros" — o D0 triplo-errado TAMBÉM aqui
  (verificar se live importa _compute_realized_pnl: partilhada!")
- descoberta valiosa: SimulatedMarket v2 = F2-b pré-construído (simulação
  climatológica de asks com confidence por hora + ruído por liquidez) —
  utilizável para backtest da v5/v6 sem inventar de novo
- boas práticas a roubar: batch prediction, diagnose económica (breakeven
  win-rate, EV por hora), capital floor com aviso honesto
- performance: load_data com loop python 300k × astimezone = lento (vetorizar v4.1)

## 32. AUDIT cassiopeia_train.py (13/09)
- VIRTUDES: [A] prior_map computado serializado (treino=produção) ✓,
  [B] janela futura incompleta descartada ✓, [C] min_hour_target ✓,
  [D] lgbm callbacks modernos ✓, --end-date EXISTE ✓ (walk-forward limpo
  possível na v4!), metadata rica no config ✓, preferência LGBM com
  racional documentado ✓
- BUG #1 (meu): gancho D1 possivelmente DUPLICADO no live bot (patch de
  ontem re-inseriu) — grep -c "D1: registar" → se 2, remover o duplicado
- BUG #2 (fragilidade): train procura om_data/ (que renomeámos) → cai
  sempre no fallback condition-mapping (comportamento OK mas acidental);
  v4.1: flag --om-dir explícita
- BUG #3 (frágil): conversão TZ vive DENTRO do build_dataset, não no
  load_csv — internamente coerente mas o 7º sítio onde TZ pode fugir;
  v4.1: mover para load_csv
- MELHORIA #4: sort_values("date") explícito antes do split 80/20
  (hoje funciona por sorte da ordem de geração — leakage silencioso
  se alguém introduzir sort)
- MELHORIA #5: flag --quick (só LGBM) para o pipeline ×19 (economiza ~1h)
- VERIFICAR: delta_threshold 0.3 — predictor lê do config ou hardcode?

## 33. AUDIT cassiopeia_predictor.py (13/09) — 2 fixes de produção aplicados
- BUG REAL #1: LOG_DIR hard-coded no predictor → Andromeda lia/escrevia os
  history_max NA PASTA DA CASSIOPEIA (colisão de estado entre bots!)
  FIX: CASS_LOG_DIR-aware (mesmo padrão do ledger/tick_logger) — confirmado:
  history_max próprios já a nascer em live_bot_logs_v6/
- BUG REAL #2: _save_history_max_file sem escrita atómica — o predictor já
  foi truncado a 0 bytes uma vez (incidente histórico documentado no header
  do próprio ficheiro, nunca investigado). FIX: temp+rename (padrão do
  _append_bet_record)
- ACHADOS v4.1 (não urgentes): predict_rebound_prob retorna p=1.0 semântica
  perigosa em vez de None; _get_city() fallback munich silencioso;
  build_features sem validação de schema (features ausentes → defaults
  silenciosos)
- arquitetura confirmada: 3 cérebros (peak ensemble · rebound Cassiopeia ·
  F1 quantile Andromeda) todos fail-closed ✓
- EFEITO COLATERAL do fix: Andromeda perde history_max partilhado (nasce
  vazio no v6/) → prev7 dela degradado 1-2 dias → sem trades dela até
  estabilizar. Aceitável e pontual.

## 34. AUDIT cassiopeia_strategy.py (13/09) — o mais curto e o mais simbólico
- 77 linhas, 0 lógica própria: delegação 100% ao cassiopeia_backtester
- é a CORREÇÃO FUNDAMENTAL: antes tinha random.random() e placeholders
  divergentes (spread/prev7 próprios) → parâmetros calibrados eram inválidos
  no live. A paridade calibração↔estratégia nasce AQUI e é o princípio
  fundador de toda a disciplina metodológica do projeto
- papel no sistema: testador rápido de parâmetros (--auto-params/CLI)
- único risco: nada estrutural impede divergência futura (a proteção é
  cultural) → v4.1: teste que compara run_strategy vs run_backtest (5 linhas)
- utilidade prática: testar cenários V1 (entry-price diferentes) num instante

## 35. AUDIT cassiopeia_params.py + cassiopeia_watchdog.py (13/09)
- params: escrita atómica ✓, sanitização com ranges ✓, versionamento
  + rollback ✓, CLI show/history/rollback ✓
  fragilidade: resolve_params não valida (só apply_calibration valida)
  — v4.1: mover validação para resolve_params
  fragilidade 2: max_trades_per_day/trailing_stop não estão em
  VALID_PARAM_KEYS — perdidos silenciosamente na sanitização (baixo risco)
- watchdog: DEDUPE POR HASH ✓, skip "all" ✓, 3 modos ✓, dry-run ✓
  estado: DORMENTE (promoção manual deliberada — reativar na v4.1 se
  confiança nas promoções automáticas)
  fragilidade: --watch SUBSTITUI paths (não adiciona); estado sem
  escrita atómica; .watchdog_state.json na raiz
- FLUXO REAL: calibrate → JSON → (apply manual) → active_config →
  resolve_params → live bot. A D7 final usará exatamente este caminho.
- _meta do munich: última calibração 2026-08-31 (era v2) — a D7 produz
  a próxima com os grids novos + entry_price por cidade + metric edge

## 36. AUDIT cassiopeia_entry.py (13/09) — o executor da Cassiopeia
- SOLIDO: fail-closed em camadas, gates em cascata na ordem certa,
  _find_bracket com caudas tratadas, epsilon no rmax, last_eval exposto
  (D5), restore() anti-duplicado, max/min ask divididos live/entry
  (maxask fresco), reason strings na ação
- VIOLAÇÃO corrigida: threshold default 0.25 no fallback ≠ 0.35 do
  cassiopeia_params (a era dos placeholders divergentes quase renasceu!)
  → fix 1 linha: alinhado a 0.35. inofensivo hoje (auto_params injeta
  sempre) mas a paridade fica restaurada
- NOTA: bootstrap history_max do CSV (parado em 19/07!) é só SEMENTE —
  o prev7 real vem do update_history_max em memória. Fluxo frágil mas
  funcional (o CSV desatualizado não bloqueia)
- check_stop_loss = NO-OP documentado (paridade com backtest: resolução
  a EOD) — decisão de design consciente

## 37. AUDIT cassiopeia_backtester.py v3.2 (13/09) — o motor de números
- 9 virtudes (P&L assimétrico, breakeven com fee, TZ+DST handling,
  override date incondicional, warm-up, _safe_float, _SLOT_SPEC coalescing,
  ML error suprimido, fail-closed)
- 🔴 DESCOBERTA: MODO STAIRS implementado e NUNCA corrido! (one more push:
  aposta floor(rmax)+1 a partir de plateau, p>=0.60, janela 11-16h)
  → estratégia complementar à Cassiopeia (upside vs当前 bracket)
  ⚠️ bug no hit: day_max >= strike SEM teto (deveria < strike+1.0) —
  nunca correu, por isso ninguém notou; fixar antes de usar
- 🔴 FEE_RATE_DEFAULT 0.0 → 0.009 (aprox linear da fee Weather 0.05×p×(1-p)):
  o dry-run de ontem (+24.45pp) foi SEM FEE! Com fee: edge cai ~0.9pp
  (ainda forte). Fix aplicado ao default + run_v4 + dryrun (--fee-rate 0.009)
- breakeven linear (p×(1+f)) vs exato por trade no analyze_d7 — diferença
  <0.5pp na banda, documentado
- stairs_analysis/stairs_grid no disco = os irmãos deste modo

## 38. MODO STAIRS — diagnóstico (13/09): adiado com causa documentada
- 1ª corrida real: 0 entradas em 6037 dias
- instrumentação: gap≤0.30 passa só ~40% dos contextos (matemática: gap
  uniforme [0,1)) + p_rebound do modelo atual raramente ≥0.60 (o modelo
  foi treinado para target rate 0.26, delta 0.3 — thresholds de prob
  NÃO são transferíveis entre perguntas diferentes)
- 12 None na instrumentação = slots subalimentados no MEU teste (artefacto)
- VEREDICTO: stairs exige MODELO PRÓPRIO (label = push forte ≥0.7-1.0°C)
  + fix do hit sem teto (day_max < strike+1.0) + revisão do gap_max
  → mini-projeto v7 (não é patch) — atrás da v4 e do torneio
- valor latente: é a estratégia complementar exata (upside push vs
  bracket atual) — e o SimulatedMarket do backtester.py mundo-peak
  pode servir para o seu backtest

## 38b. CORREÇÃO DO AUDIT (13/09): "live_bot.py" = cassiopeia_live_bot.py
- o paste analisado era o MEIO do cassiopeia_live_bot.py (header antigo
  "live_bot.py" nunca atualizado após o rename da era V2)
- a análise do "fóssil ancestral" estava ERRADA — é o MESMO ficheiro de
  produção; os FIXs (thread-safety, backoff, health alerts) SEMPRE
  estiveram lá (não os tinha visto na análise parcial)
- FIX aplicado ao header: docstring atualizado para o nome real
- pequena higiene: actualizar headers antigos quando se renomeiam ficheiros

## 39. ANDROMEDA + LUCKNOW (13/09) — 11ª cidade a pedido do dono
- razão: regime monçónico indiano único no portfólio do B + F1 aprovada
- trade-off conhecido: cobertura de banda 2% (trades raros — característica)
- rotation do log v6 (cron 03:00) instalada

## 40. CITY EASINESS — 1º ranking vivo (13/09)
- city_easiness.py: score composto (40% papel · 25% edge · 20% cobertura · 15% F1)
- 1º RANKING: milan 30.6 (100%×3 + cover 18%) · seoul 27.7 (100%×5) ·
  jeddah 27.1 · lucknow 11.1 · fundo: cape_town −12.7
- AVISO: n=3-5 por cidade — ranking INDICATIVO, endurece com a amostra
- GAP descoberto: f1_report.json só existe para munich! (V6.1 de ontem
  correu gates ×36 no stdout mas o save por cidade falhou/partial) —
  re-correr o treino F1 ×20 na v4.1 ou investigar o loop
- uso: re-correr semanalmente; decisões de concentração só pós-A5

## 41. BUG V6.1-LOOP + RELANÇAMENTO COMPLETO (14/09)
- BUG descoberto: o dump do atom_classifier rebentava (FileNotFoundError) nas
  cidades sem o diretório v5_quantile_model → 35 dos 36 saves falhavam
  (só munich tinha o dir de runs anteriores) → só 1 f1_report no disco
- FIX: mkdir(parents=True) antes do dump
- V6.1-v2 lançado: loop ×36 com output forense COMPLETO (tail -30, sem grep
  que esconde tracebacks) → v6_f1_all_v2.txt (~2-3h)
- bónus da 1ª passada: madrid base rate 47.7% (outlier ALTO — a cidade mais
  "pushy" da amostra, o dobro das outras!) — investigar

## 42. V6.1-v2 COMPLETO (14/09): 36/36 reports, 20 promovidas
- 12 cidades com gate 6/5 (perfeição) + 8 com 5/5 = 20 PROMOVIDAS
  (v6_approved_cities_v2.txt)
- padrão geográfico: asiáticas de push padrão (chengdu/chongqing/guangzhou/
  wuhan/shenzhen) calibram perfeitamente; london/taipei/marítimas piores
- madrid: promovida + base rate 47.7% (outlier alto — cidade-push, investigar)
- pool completo no disco: 36 f1_report.json + 36 atom_classifier.pkl
- uso futuro: trocar cidades da Andromeda = só mudar a lista (modelos prontos)

## 43. BUG CRÍTICO DO FILTRO ANDROMEDA — RESOLVIDO (15/09)
- os 258 julgamentos/0 PASS/2 dias sem trades da Andromeda = BUG, não
  seletividade: o caller passava hi com a convenção half-open (hi==lo==inteiro)
  e o gate calculava F(hi−rmax) = F(negativo) = 0.0 SEMPRE
- teste pós-fix: singapore rmax=32.8 hi=32.0 → p_win 98.7% (antes: 0.0%)
- causa: a convenção half-open (bracket [24,25) gravada como lo=hi=24) —
  a MESMA que apanhámos nos bets/analyze — nunca foi normalizada no GATE
- FIX: normalização no compute_p_win (hi<=rmax → floor(rmax)+1.0)
- a Andromeda estava estrangulada desde o nascimento; agora julga de verdade
- LIÇÃO: testar o filtro com um caso REAL do log (não só sintético) — o
  teste sintético inicial (hi>lo) não teria apanhado nunca

## 44. A LIÇÃO TZ Nº7 — MEU (13/09): "performance fix" = 6º bug TZ
- _normalize_tz_early no train (vetorização de performance) introduziu
  DUPLA conversão: load converte → build converte outra vez → +1-2h shift
- apanhado a tempo: pipeline morto antes do 1º treino completar
  (0 modelos contaminados — o log confirmou 0 secções ════)
- fix: _normalize_tz_early REMOVIDA (o build já converte certo, era
  redundante E perigoso)
- LIÇÃO MESTRA: performance fixes em pipelines de dados TÊM de ser testados
  com comparação de output (horas antes/depois) — nunca lançados em loops
  de treino de 19 cidades "porque é só perf"
- contagem TZ do projeto: 7 bugs (6 + este quase-acidente)

## 45. BUGS V4.1 FECHADOS (15/09): 4 fixes + suíte 17/17 mantida
- FIX: resolve_params valida ranges na LEITURA (JSON editado à mão não
  entra com valores absurdos — usa defaults)
- FIX: watchdog --watch ADITIVO (não substitui — não perde a raiz)
- FIX: watchdog estado com escrita atómica (padrão da casa)
- FIX: VALID_PARAM_KEYS completo (max_trades_per_day + trailing_stop)
- FIX: tg sendMessage timeout=15
- D2 gamma: já integrado com D1 no live (verificado — real only)
- RESTAM (v4.1+ mesmo): 143 prints→logger, _tick_city/buy_yes refactor,
  backtester peak fee (só se mundo peak voltar), matplotlib import

## 46. B4+B6+B7 FECHADOS (16/09)
- B4: predict_rebound_prob → None semântico (horas cedo/slots poucos);
  caller (entry) com guard None→bloqueia; teste de regressão adicionado
- B6: matplotlib lazy no backtester (import só se dashboard)
- B7: ruff --fix F401 nos ficheiros vivos (imports mortos limpos)
- validação: 18/18 testes (17+1 novo)

## 47. LIÇÃO CRÍTICA: REFACTORS PERDIDOS (13/09)
- B1-F1 a F4 foram extraídos e commitados ao longo de 2 dias
- MAS o commit dd3d7aa (seg+limpeza) REVERTIU o cassiopeia_live_bot.py
  para um estado antigo sem os refactors (o git checkout de um commit
  anterior sobrescreveu as mudanças não-commitadas)
- RESULTADO: 4 refactors perdidos (F1-F4) que precisam de ser refeitos
- LIÇÃO: nunca fazer `git checkout <commit> -- ficheiro` sem verificar
  que o ficheiro no disco está COMMITADO primeiro
- prevenção: git stash antes de checkouts, ou commit pequenos frequentes

## 48. RECUPERAÇÃO DO REFACTOR (14/09) — F1-F4 restaurados do a5165da
- o commit dd3d7aa (seg+limpeza) reverteu acidentalmente o live_bot
- os refactors F1-F4 existiam no commit a5165da (restaurado)
- prevenção: verificar que o ficheiro no disco está commitado ANTES de
  git checkout de qualquer commit anterior

## 49. D2 DUPLICADO — resolvido (14/09)
- 2 ganchos D2 idênticos no live_bot (o patch correu 2x na era dos restarts)
- removida a 1ª ocorrência (a 2ª com alias _mk_open mantida)
- sem impacto: ambos faziam a mesma verificação — mas era código morto

## 50. REFACTOR buy_yes — ABORTADO (14/09) — lição de método
- o refactor (237 linhas → 6 funções) causou: duplicadas, cortes, docstring
  partido, e um estado do ficheiro impossível de diagnosticar remotamente
- REVERT: git checkout feef8c0 -- polymarket_clob.py (estado saudável)
- LIÇÃO MESTRA: refactors de ficheiros grandes (200+ linhas) NÃO se fazem
  via patches de texto por heredoc — fazem-se em IDE com vista total e
  testes imediatos
- o buy_yes COMPLEXO fica documentado (complexidade 45) para refactor
  numa sessão com IDE — NÃO tentar via patches de texto de novo

## 51. V7 STAIRS — MODELOS TREINADOS ×15 (15/09) — 15/15 AUC ≥0.86!
- v7_train_stairs.py: dataset 941k contexts × 15 cidades (label push ≥1.0°C)
- TODAS as 15 cidades com AUC ≥0.86 (a mais baixa: moscow 0.8637)
- P@top20% (a métrica que importa):
  madrid 100% · lucknow 97.7% · milan 96.7% · sao_paulo 95.9% ·
  chengdu 95.7% · munich 95.2% · istanbul 94.3% · guangzhou 93.3% ·
  moscow 89.9% · seoul 87.9% · singapore 85.8% · manila 83.3% ·
  jeddah 79.3% · tel_aviv 66.0% · taipei 49.4% (fraca)
- base rate por cidade revela: madrid 77.7% push≥1.0 (outlier!) vs
  taipei 15.9% (o mais estável) — informação de trading pura
- modelos guardados: v7_stairs_models/{city}/stairs_model.pkl
- PRÓXIMO: Calipso entry (rebound + stairs no mesmo tick) + bot wrapper

## 52. V7 STAIRS COMPLETO (14/09): 36/36 modelos treinados
- v7_train_stairs.py: dataset 2.1M contexts × 36 cidades (label push ≥1.0°C)
- TODAS as 36 com AUC ≥0.75 (gate cumprido universalmente)
- modelos guardados: v7_stairs_models/{city}/stairs_model.pkl + stairs_config.json
- o arsenal do Calipso está completo — pode correr em QUALQUER cidade

## 53. REENCONTRO PÓS-LIMITE (19/09) — era v4 ainda não nasceu + 2 fixes
- sessão chat.z.ai morreu; continuação direta pelo HANDOVER (sem copy-paste)
- 🔴 ACHADO-CRÍTICO: D-V1 (0.80-0.86) nunca chegou ao live — entry usava
  defaults 0.60/0.85; trades 17/09→ são era v3.5 residuária (14W/7L +$3.18,
  NÃO contam para v4). FIX aplicado: config→resolve_params→CassiopeiaEntry
  (Calipso herda); 19/19 testes ✓. ATIVO SÓ NO PRÓXIMO RESTART.
- pipeline v4: 19/19 APROVADAS na passagem 17-18/09 (+21 a +34pp OOS);
  re-corrida de 19/09 era redundante (idêntica) → PARADA; máquina aliviada
- Calipso: NUNCA chegou a correr — argparse não aceita --mode calipso
  (choices falta; 1 linha, pendente)
- PRÓXIMOS PASSOS: 3) fix choices calipso → 4) rever promoções OOS 17-18/09
  → aplicar → RESTART ÚNICO (banda v4 a sério + promoções + Calipso se for
  já) → zerar amostra → era v4 começa para valer

## 54. PASSO 4 PREPARADO (19/09) — promoções v4 + plano do restart único
- REVISÃO OOS 17-18/09: 19/19 APROVADAS (16.924 entradas, +21 a +34pp;
  topo: cape_town +33.9, tel_aviv +32.6, jeddah +31.0, beijing +30.6)
- ⚠️ desmontada armadilha do apply: best_params não traz banda →
  apply_calibration AGORA preserva min/max_buy_ask (D-V1 intocável)
- apply_v4_promotions.py: dry-run default, --apply executa (suite 20/20)
- RESTART ÚNICO (ordem obrigatória — start_paper.sh pkill é genérico e
  mata A, B e Calipso):
  1. ./venv/bin/python apply_v4_promotions.py --apply
  2. bash start_paper.sh            (A + collector, código+config novos)
  3. bash start_paper_v6.sh         (B)
  4. bash start_calipso.sh          (C — 12/12 prontas, .env3 ok)
  5. verificar: tmux ls (4 sessões) + "[CassiopeiaEntry] Params ativos"
     com min_buy_ask 0.8/max 0.86 nos 3 logs + asks só em 0.80-0.86
  6. era v4 REAL começa: próximas análises D7 com --cutoff <data restart>
  - rollback se correr mal: cassiopeia_params.py rollback --city X
    (histórico automático por cidade no apply)
  - janela: de manhã WEST (fora das start_hours 12-14 locais) é o mais
    limpo; restore() anti-duplicado cobre posições abertas se for mid-day

## 55. CALIPSO LIVE (19/09 17:09) — 3 bots + collector a correr
- tmux: bot (A) · collector · v6bot (B) · calipso (C, 12 cidades, .env3,
  send-only, logs live_bot_logs_calipso) — C é o 1º bot com banda D-V1
  ativa (0.80-0.86 no log de arranque)
- fragilidade venv desmontada: v6/calipso start scripts agora
  autocontidos (venv + .env) — antes dependiam do shell lançador
- start_all_bots.py lança A→B→C; alive_guard exige 4 sessões/3 pythons
- C usa thresholds atuais até ao restart único; depois herda v4 (0.20)
- ⚠️ lição rollover: bots recriam entries à meia-noite local (config do
  disco + código em memória) — NUNCA aplicar calibrações com bots vivos

## 56. 🎂 ERA v4 REAL (19/09 17:52 WEST) — os 3 bots em produção
- A + B + C + collector vivos; TODOS com threshold 0.2, janelas 12-14h,
  BANDA 0.80-0.86 (D-V1 ativa pela 1ª vez)
- veredicto v4: analyze_d7_final.py --cutoff 2026-09-20 (hoje é dia misto)
- era residuária descartada: 17-19/09 banda velha (14W/7L não conta)
- rollback se necessário: cassiopeia_params.py rollback --city X

## 57. DECODER DE NOMES (19/09 — a pedido do dono, para nunca mais confundir)
- ERAS (regras de trading): v1 morta · v3.5 Cassiopeia clássica (0.60-0.85,
  fechou com D7) · v4 ATUAL (0.80-0.86, th 0.20, nasceu 19/09 17:52)
- PROJETOS (investigação): v5 edge-engine SUSPENSA (achados→D7) · v6 = filtro
  F1 (vive no bot B) · v7 = STAIRS (vive no bot C)
- BOTS (3, mesmo ficheiro cassiopeia_live_bot.py):
  A Cassiopeia = rebound puro, 19 cidades, TG interativo (1bot)
  B Andromeda  = rebound + FILTRO F1 p_win≥0.82, 11 cidades, send-only (2bot)
  C Calipso    = DUAL v7: p_stairs≥0.75→compra bracket SEGUINTE (push);
                 senão rebound→compra ATUAL (dia estável). 12 cidades (3bot)
- "modo duplo com stairs" = Calipso (já live). Stairs NÃO é bot, é o 2º cérebro.
- ROADMAP: era v4 + torneio triplo (critérios A-vsB queimados §5 V6_ROADMAP;
  critérios do C POR QUEIMAR antes de ler resultados) → D-v4 (≥60) →
  concentração 4-5 motor → GATE REAL A5 (150 trades, EV+3pp, dd≤$15) →
  D3 dossier + decisão D4 maker → E1 real $20-50 → E2 RAM/33 → E3 opcionais

## 58. ROADMAP DATADO (19/09 — estimativas, o manda-onças é o X/60)
- 20/09 dia 1 v4 (aberturas Ásia) · 21/09 contador X/60 acorda · ~27/09
  1ª leitura semanal · ~19/10 audit estações (mensal) · ~17-31/10 torneio
  A-vs-B amadurece (~100 trades) · ~20/10-05/11 D-v4 (≥60 → veredicto era
  + torneio + D-EXC + concentração) · início nov D3/D4 · ~meados nov E1
  real SE A5 passar · E2 RAM paralelo · E3 depois · PENDENTE: queimar
  critérios do C ANTES de resultados (proposta: wr_C ≥ max(A,B) E EV_C≥0
  E dd_C ≤ dd_A)
- ritmo esperado banda seletiva: 1.3-3/dia no A (v3.5 deu 1.3 na banda) —
  se <1/dia sustentado, acelera-se a conversa de concentração

## 59. CALIPSO V2 — PRÉ-REGISTO (21/09): veto-only por lista
- CALIPSO_V2_PROPOSTA.md = a proposta formal queimada antes da D-v4
- stairs-como-trade SUSPENSO (negativo 13/13 cidades, −17 a −77pp)
- C-v2 = rebound + veto slot-level (p_stairs≥0.75 bloqueia entrada) nas
  6 cidades vencedoras do backtest: madrid seoul milan lucknow paris
  amsterdam; confirmação live: hit_C ≥ hit_A com n≥30, senão C desliga
- corrida --veto-only (slot-level) a validar a lista antes de queimar
  (atualização §59, noite 21/09): tabelas finais na proposta. slot-level
  = no-op (rejeitado); day-level só tem tripé volume×ganho em lucknow/
  amsterdam (+seoul c/ volume menor). RECOMENDAÇÃO PRÉ-REGISTADA:
  (d) desligar C no restart D-v4 (primária) OU (c1) C-v2 day-level em
  {lucknow, amsterdam, seoul} (alternativa). Decisão do dono antes do
  restart; critério de confirmação live mantém-se.

## 60. DECISÃO DO DONO (22/09): C desliga no restart da D-v4
- CALIPSO_V2_PROPOSTA.md aprovada — opção (d) primária; (c1) não escolhida
- no restart D-v4: kill calipso + remover de start_all_bots.py/alive_guard
- até lá C corre em papel; ledgers/modelos preservados em disco

## 61. DECISÃO DO DONO (03/10) — ERA v4 FECHADA · ERA v4.1 ABERTA (banda 0.80-0.90)
- Era v4: NO-GO-POR-VOLUME (12/60, 9W/3L, EV líq −9.3pp; 0 aberturas 21/09→02/10).
  Sistema saudável; o mercado não vende 0.80-0.86 quando o modelo dispara
  (0.0% dos 10265 disparos bloqueados caíam na banda). Detalhe completo no
  bloco "DECISÃO DO DONO (03/10)" do BUGS_PENDENTES.md.
- Era v4.1 (cutoff 2026-10-04): BANDA 0.80-0.90 queimada · th 0.20 · A(19) +
  B(6: munich,madrid,paris,seoul,moscow,istanbul) · C DESLIGADO (03/10) ·
  D micro na banda nova (emenda ao critério 5).
- Critérios v4.1: ≥60 resolvidos → EV líq + dd≤$15; intermédia 20/10 mantida;
  final 03/11/2026 ou aos 60 (o que primeiro); n<60 → NO-GO #2 e D4 maker é a
  ÚNICA via restante. Perna 0.75-0.80: só shadow/maker, nunca taker.
- Decoder atualizado: ERAS = v1 · v3.5 · v4 (fechada 03/10, NO-GO-vol) ·
  v4.1 ATUAL. BOTS = A Cassiopeia · B Andromeda(6) · C Calipso MORTO · D micro.
- Fixes neste restart: LEDGER-1 (tests→/tmp), LEDGER-2 (dedup writer),
  settlement-órfãos (restore re-persiste), F821 ×2, lista do B limpa, C morto.
- PRÓXIMO: conversa D4 maker esta semana · leituras semanais com
  --cutoff 2026-10-04 · testar derive-api-key do micro antes do 1º buy real
  (falhou 400 no arranque de 30/09; 0 fills desde aí).

## 62. D4 MAKER V1 LIVE (03/10 15:32)
- Desenho queimado no BUGS_PENDENTES.md (bloco "D4 MAKER — DESENHO QUEIMADO" +
  notas de implementação): bid fixa 0.75 · GTC post_only (nunca-cruzar em dupla
  cerca) · gatilho = compra bloqueada PELO MÁXIMO · slot partilhado 1/dia ·
  TTL 60 min + fim de janela · contabilidade fee 0 + flag maker.
- Micro D (real) corre com D4_MAKER=1 · shadow paper no B com V6_MAKER=1
  (V6_MAKER_PRICE=0.75, TTL 60) — o hook antigo do shadow estava antes da
  banda e matava o torneio; v2 regista só no ramo do bloqueio máximo.
- Estado das bids: live_bot_logs_micro/maker_bids.json (real) ·
  live_bot_logs_v6/maker_{pending,filled}.json (shadow).
- Métricas a ler no dossiê 20/10: >=3 fills reais · EV fills = hit-75% ·
  adverse selection (hit fills vs shadow mesmas brackets) · fill rate.
- Suite 25/25 · commit D4 na história do git.

## 63. EMENDA ERA v4.1 (07/10) — BANDA 0.75-0.90 · MICRO PINADO
- 4 dias de era v4.1: ZERO oportunidades na banda 0.80-0.90 (mercado só serve
  <0.80 ou >=0.90). Dono aprovou: banda abre para 0.75-0.90 com KILL CRITERIA
  da perna queimados (BUGS_PENDENTES, bloco EMENDA 07/10): perna 0.75-0.80
  morre a n>=15 resolvidos se EV líq <0; análise por faixa nativa (bins 5¢).
  Fundamento do risco registado: D7 v3.5 −27.8pp vs shadow regime atual 3/3.
- Micro (real) PINADO em 0.80-0.90 via --min-buy-ask 0.80 (mecanismo novo:
  arg explícito > config; teste de regressão). A+B paper a 0.75-0.90.
- Fix no despejo: [CassiopeiaEntry] Params ativos agora mostra os valores
  EFETIVOS (o print mostrava só a config e escondia o override — quase
  enganou a verificação do pin).
- Estado: suite 27/27 · A(19) B(6) paper 0.75-0.90 · micro(4) real 0.80-0.90
  + maker 0.75 no bloqueio-máximo · cutoff era mantido 2026-10-04.

## 64. DASHBOARD WEB + FIX DISPLAY SIGNAL! (08/10)
- Dashboard local LIVE: http://127.0.0.1:8787 (Flask .webvenv + React SPA em
  dashboard/, tmux 'dashboard', start_dashboard.sh, entra no autostart @reboot).
  Tabs: Visão Geral / Era v4.1 (por faixa+cidade+dia por bot e combinado) /
  Cidades (snapshot ao vivo) / Maker-Shadow (bids reais, fills, adverse
  selection) / Eventos. Só lê os ficheiros dos bots — zero risco p/ trading.
- BUG cosmético importante resolvido: o display mostrava "SIGNAL!" quando
  p>=thr para TODAS as estratégias, mas a Cassiopeia compra quando
  p_rebound < thr (direção oposta à peak). 4 sítios corrigidos em display.py
  (detalhe no BUGS_PENDENTES). A "seca" NUNCA foi bug de trading: com
  p_rebound recente 0.20-0.44 (acima do th 0.20), o não-comprar é o
  comportamento certo — era o display que mentia.

## 65. DASHBOARD: EQUITY + A-vs-B AO VIVO + SHADOW HIST (09/10)
- 3 tabs novas em http://127.0.0.1:8787 (8 tabs no total):
  · Equity — curva diária acumulada de P&L realizado por bot (A/B/D) e Σ,
    todo o histórico do ledger, com marcas de fronteira de era (v3.5/v4/v4.1)
    e max drawdown por série.
  · A vs B — tabela da era lado a lado + grelha ao vivo cidade a cidade:
    p_rebound/th, ask e se está na banda 0.75-0.90, veredito A, e o p_win
    do F1 calculado NO SERVIDOR via v6_filter.compute_p_win (mesmo recheio
    do gate do B: slots do snapshot, prev7 do history_max do B, hora local
    da cidade) + veredito B. istambul vem do snapshot do B (A não cobre).
  · Shadow — by_band + contrafactual por dia + fills maker do B desde 03/10
    com resolução real (join market_slug→winners: WON/LOST/PENDENTE; labels
    "X or below" = LOST, "X or higher" compara bracket_lo).
- Endpoints novos: /api/equity /api/avsb /api/shadow_history.
- BUG SNAPSHOT-1: display.py tinha LOG_DIR hardcoded ("live_bot_logs") — os
  3 bots escreviam o mesmo live_snapshot.json (quem escrevia por último
  ganhava). Fix: CASS_LOG_DIR como no live_bot. B (paper) reiniciado →
  escreve em live_bot_logs_v6/ ✓. D (real) deixado a correr (não se toca em
  bot real a meio da semana): o servidor faz mirror de último snapshot bom
  do A em dashboard/last_snapshot_A.json (só aceita PAPER ≥10 cidades).
- .webvenv do dashboard ganhou numpy/joblib/scikit-learn/lightgbm (pinados
  às versões do venv principal) para correr v6_filter em-processo no /api/avsb.
- PENDENTE: quando o D reiniciar naturalmente (próximo restart/boot), fica
  a escrever o snapshot dele em live_bot_logs_micro/ e o mirror deixa de
  ser necessário (pode manter-se — é barato e robusto).
- Suite: 27/27. Todos os endpoints verificados com curl (200).

## 66. DASHBOARD: UX DAS TABS + DEDUP FILLS + WINNERS OUTUBRO (10/10)
- Feedback do dono sobre as 3 tabs novas → reescrita UX em toda a dashboard:
  · Visão Geral: barra de cor por bot (A ciano/B verde/D âmbar), card "todos os
    bots juntos" com explicação + tabela dos trades resolvidos da era (era_recent),
    card Maker com frases completas, card "Sinais de hoje" com glossário.
  · Shadow: banner explicativo ("simulação, zero dinheiro real"), hit% com cor
    (≥60 verde/40-60 âmbar/<40 vermelho), contrafactual por dia (13 dias
    27/09→09/10, hit 14-46%), fills maker dedup com coluna ×N.
  · Cidades: agrupadas por grupo climático (CONTINENTAL/ATLANTAL/...), legenda
    de cores âmbar=sinal/verde=comprada/vermelho=stop.
  · Maker: tab separado do Shadow (sem duplicação do by_band), Micro real vs
    sombra Andromeda lado a lado, fills com resolução WON/LOST/PEND.
  · Eventos: últimos 7 dias (param days), agrupados por bot com nome completo
    (CASSIOPEIA/ANDROMEDA/MICRO), ordenados por ts real.
- BUG DADOS (não de código do bot): maker_filled.json tinha 8 "fills" de madrid
  03/10 — mesmo token_id e mesmo filled_at ao milissegundo; o bot recoloca a
  bid a cada ~30s e o simulador preenche TODAS no mesmo tick. Dashboard faz
  dedup por (token_id, filled_at) → 30 fills → 18 únicos (madrid 8→1).
  Fills reais desde 03/10: 2 (madrid 21.0°C LOST, paris 16.0°C LOST; sombra).
- COLETA: market_winners.json estava parado em setembro (o collector só recolhe
  asks; quem resolve winners é o v5_f2a_fetch_winners.py, manual). Corrido
  hoje: 868 slugs em cache (190 de outubro, 171 resolvidos). PENDENTE: meter
  o fetch_winners no cron/morning_check para não voltar a apodrecer.
- BUG HERDADO: a Table() do index.html tinha um JSX container "{cols.map(...)"
  sem "}" de fecho desde a primeira versão (o Babel do browser tolerava; o
  node não). Corrigido — ficheiro validado com transform Babel completo.
- Suite 27/27 · todos os endpoints 200 · commit próprio.

## 67. FETCH_WINNERS AUTOMÁTICO (10/10)
- v5_f2a_fetch_winners.py (quem resolve os winners p/ market_winners.json) era
  MANUAL — o cache apodrecia. Agora:
  · cron 2x/dia: "20 7,19 * * *" → live_bot_logs/fetch_winners.log
  · FIX no script: corrida recorrente re-tenta slugs em cache com resolved=false
    e mercado fechado (date < hoje); erros >7d ficam de fora (slug morto).
    Antes: "s not in win" excluía para sempre os não-resolvidos.
  · 1ª corrida pós-fix: 842/871 slugs com vencedora.
- O dashboard (tabs Shadow/Maker) consome este cache — PEND só deve aparecer
  para mercados de hoje ainda abertos.

## 68. LEITURA SEMANAL ERA v4.1 #1 (11/10 — 7 dias, cutoff 2026-10-04)
- D7/análise-mãe (só ledger A): 0 resolvidos / 0 abertos — sem veredicto (0/60)
- ÚNICO trade da era (ledger B): paris 09/10 @ask 0.75 (borda exata do mínimo)
  bracket 17°C → WON +$0.25 (1W/0L, EV da era não computável com n=1)
- A (Cassiopeia) SECO desde 21/09 — 20 dias, 0 trades (era v4 residuária 12/60
  fechou; v4.1 zero). Dupla causa inalterada: (1) deserto de banda, (2) p_rebound
  0.20-0.44 >= th 0.20 → não-comprar é o comportamento certo (§64)
- ESTRUTURA DE MERCADO (opportunity_logger, 5816 snapshots em 8 dias):
  92% ask<0.75 (gate min) · 8% ask>0.90 (gate max) · ~0 dentro de 0.75-0.90.
  O deserto não é da banda 0.80-0.90 (era v4) — alargar a 0.75 mudou quase nada:
  desde 07/10 exactamente 1 momento com ask=0.75 (o trade do B)
- Maker: sombra 1 bid (paris 10/10 @0.75, ask real 0.92) NO_FILL · D real 0 fills
- RITMO: 0.13 trades/dia (estimativa §58 era 1.3-3/dia) → 60 resolvidos levaria
  ~1 ano; o constraint BINDING da era é a data final 03/11/2026, não a amostra
- Leitura honesta: se nada mudar, era v4.1 morre NO-GO #2 por volume e o D4
  maker (bid 0.75 a pescar na região onde vivem 92% dos asks) é a única via
  restante — a "conversa D4 maker" pendente (§61) fica ainda mais premente

## 68b. ESTIMATIVA PISO 0.70 (11/10 — pedido do dono, NÃO é decisão)
- VOLUME (emenda 07/10→11/10, band_limit 0.75): 13 pares dia-cidade em 5 dias
  com ask∈[0.70,0.75) bloqueados ≈ +2.6 trades/semana (era v4 dava ~5.6/sem)
  · na [0.75,0.90]: 0 → piso 0.70 ≈ 3-5 trades/sem vs ~0.2 atual
- HIT RATE na faixa (três linhas de evidência, TODAS n pequeno):
  · shadow th-0.2 (blocked fires 0.70-0.75): n=9, hit 66.7% vs BE 71.9%
    → EV −5.2pp · P&L −$0.53/trade (A-only: n=8, 75%, +$0.22 — ruído)
  · v3.5 trades REAIS 0.70-0.75: n=11, 54.5% vs BE 72.4% → EV −18.8pp
  · shadow geral: quanto mais barato pior (0.60-0.65 hit 37.5%) — mercado
    eficiente na margem (F2a): asks baratos são baratos por razão
- OBSERVAÇÃO NÃO-MONOTÓNICA: 0.65-0.70 foi positivo nas duas fontes
  (v3.5 +8.1pp n=17 · shadow +8.1pp n=8) vs 0.70-0.75 negativo — n pequeno,
  regime diferente, NÃO é recomendação; registado para auditoria futura
- P&L ESPERADO piso 0.70: −5pp a −19pp/trade × 3-5 trades/sem ≈ −$0.15 a
  −$1/sem; até 03/11 (~20 trades): −$1 a −$4 — volume −EV acelera o NO-GO,
  não o salva; contradiz §63 (perna baixa "só shadow/maker, nunca taker")
- CAMINHOS SE O DONO QUISER VOLUME: (1) deixar shadow acumular e re-avaliar
  a 0.70-0.75 com n≥20-30 (custo zero, já a correr) · (2) emenda formal com
  kill criteria queimados (n≥15 → EV<0 mata) — regressa ao fundamento §63 ·
  (3) D4 maker (fee 0 + rebate, escolhe o preço) — a via queimada em §61

## 69. MAKER SHADOW NO A + DERIVE-API-KEY OK (11/10 noite)
- MAKER SHADOW EXTENDIDO AO A (19 cidades): multiplica os dados maker até ao
  dossiê 20/10. FIX necessário em v6_maker.py: PEND/FILLED estavam hardcoded
  em live_bot_logs_v6/ (colisão A+B) → agora CASS_LOG_DIR-aware (padrão da
  casa; default preserva o B). start_paper.sh lança A com
  CASS_LOG_DIR=live_bot_logs V6_MAKER=1 V6_MAKER_PRICE=0.75 V6_MAKER_TTL_MIN=60.
  Dashboard: _load_maker_filled() faz merge A+B (3 sítios) + labels "sombra A+B"
- RESTART CIRÚRGICO DO A: tmux kill-session -t bot + relanço só da linha do A
  (start_paper.sh tem pkill genérico cassiopeia_live_bot → mata B e D real;
  NÃO correr na íntegra com bots vivos). Verificado por /proc/PID/environ:
  V6_MAKER=1 no python do A · B(6361) e D(6831) intocados · collector vivo
- SUITE 27/27 (fix de flake horário: test_d4_fill_cria_posicao usava
  end_hour=18 real — após as 18:00 locais o poll cancelava por "fim da janela"
  em vez de encher; city_now congelado ao meio-dia no teste)
- DERIVE-API-KEY DO MICRO ✅ (gargalo de 30/09 DESBLOQUEADO):
  test_derive_api_key.py (novo, raiz) replica _init_clob_client: T1 funder+
  sig_type=3 → api_key a8ee7d… derivado; leitura autenticada
  get_balance_allowance(COLLATERAL) OK ≈ $20 USDC no funder. Segredos nunca
  impressos. O D já pode colocar ordens reais quando disparar — o 0 fills não
  é mais auth, é o deserto de banda + bids maker por encher
- ⚠️ NOTA P/ ANÁLISES: fills maker do A entram no ledger A como trades paper
  @0.75 com flag maker — separar taker vs maker nas leituras da era (EV maker
  tem fee 0; misturar distorce os bins por faixa)
- Commit deste bloco: 199af22 (7 ficheiros, com HANDOVER)

## 70. DOSSIÊ D4 AGENDADO (12/10)
- analyze_d4_dossier.py (novo, raiz): gera o dossiê §62 numa secção diária —
  REAL micro D (maker_bids.json + taker fills do ledger da era) · SHADOW A+B
  (merge dos dois maker_filled, dedup token+filled_at, resolução via
  market_winners) · fill rate · adverse selection (hit vs breakeven 75%)
- HONESTIDADE DE REGIME: V1 legado (bid ao ask, pre-03/10) separado do V2
  (bid fixa 0.75 queimada) — nunca misturar no headline (V1 era otimista)
- Estado ao agendar: V2 = 2 fills resolvidos, 0/2 (madrid+paris LOST),
  fill rate 2/57 = 4%, 7 pendentes · REAL = 0 fills (gate >=3 em ⏳)
  → n=2 não é estatística; o dossiê diário vai mostrar a evolução até 20/10
- cron: "7 8 * * *" → live_bot_logs/d4_dossier.log (após o fetch_winners
  07:20 — winners frescos). Leitura de decisão: 20/10 (intermédia era v4.1)

## 71. DASHBOARD CIDADES: ESTADOS VISÍVEIS (12/10)
- Feedback do dono: "sem cores p/ distinguir comprado/resolvido/sinal" — a
  realidade era pior: as cores existiam mas eram só BORDER 1px (invisíveis) e
  o estado RESOLVIDO não existia no snapshot (só estado vivo)
- FIX backend: _latest_closes() em server.py lê BET_CLOSE reais dos ledgers
  A+B (slug→cidade, regex -in-(.+)-on-) e /api/cities injeta c.close
  {result, pnl, ts, bot} por cidade
- FIX frontend: classes .st-* com barra esquerda 4px + fundo tingido + badge
  de estado no card. Precedência: STOP > COMPRADA (posição viva) > SINAL >
  última resolução WON/LOST > cinza (sem atividade). Card mostra linha
  "última MM-DD [bot] WON/LOST ±$" sempre que há resolução
- Agrupamento climático mantido + contadores por estado no cabeçalho do grupo
  + cidades com atividade primeiro (rank bght>stp>sig>won>lost)
- GLOSSÁRIO no topo da tab ("comprada = posição viva") — resposta direta à
  pergunta do dono: sim, comprada = o bot comprou e a posição está aberta
- Validado com o babel vendored (mesmo motor do browser) + curl 200
- REDESENHO (13/10, feedback dono "confuso, não quero setembro, separa
  presente de histórico"): tab em DUAS ZONAS — 🟢 HOJE (só estado vivo:
  comprada/sinal/stop; SEM badges de histórico; vazio explica o porquê do
  deserto) · 📅 RESOLVIDAS EM OUTUBRO (tabela datada dia·cidade·bot·W/L·P&L,
  todas as resoluções do mês, com hit% e ΣP&L no cabeçalho) · ⚪ SEM ATIVIDADE
  (chips discretos flag·cidade·temp·estado). Backend: _month_closes(since=
  2026-10-01) devolve (latest_por_cidade, lista_desc); setembro fica de fora
  por construção. Agrupamento climático removido da tab (era ruído p/ este uso)

## 72. PRÉ-REGISTO EXCLUSÕES (17/10 — aprovado pelo dono "literalmente com tudo")
- HELSINKI: EXCLUÍDA do universo A no PRÓXIMO RESTART (fim da era v4.1 ou
  decisão D-v4). Fundamento INDEPENDENTE dos resultados: viés de estação
  documentado no audit §19 (WU/PWS lê +0.6-0.8°C vs oficial; caso 06/09
  resolvido: WU 16.0 vs oficial 15.0). Resultados da era são consistentes
  (LOST 10/14 @75¢, maker fill 10.0°C LOST) mas NÃO são a justificação —
  é a regra queimada "viés sustentado = exclusão antes de stakes grandes"
- CAPE-TOWN: MANTÉM-SE. Critério objetivo queimado: revisão na D-v4 se EV líq
  <0 com n>=5 resolvidos na era; até lá n=2 (WON+LOST) é ruído, não se exclui
  cidade por 1 LOST (regra n>=30/60)
- Salvaguarda anti data-snooping: excluir cidades a MEIO da era por terem
  perdido é proibido; esta decisão fica registada ANTES dos resultados
  finais e só se aplica no restart
- Nota de contexto (dashboard 17/10): era v4.1 com 10 resolvidos 8W/2L
  (+$0.50, EV +4.1pp) — os 2 LOST são exactamente helsinki+cape_town;
  TODAS as entradas a 75¢ (banda 0.75-0.90 continua deserto, era efetiva =
  perna 0.75-0.80) · maker shadow V2: 5/11 fills (45% vs 75% breakeven,
  EV −$0.30/fill) — adverse selection a confirmar no dossiê 20/10

## 73. DASHBOARD REDESENHADA 5 TABS (18/10 — aprovado "literalmente com tudo")
- Mapa novo (feedback dono: "reanalisa todos os tabs, proposta mais intuitiva
  e profissional"): HOJE (presente: cards bot vivo/morto·sinal·PnL dia·abertas,
  cidades ativas agora com badge COMPRADA/SINAL/STOP colorido, secção A-vs-B
  ao vivo condicional, posições abertas, bids maker live) · ERA V4.1 (a
  pergunta "a estratégia está a funcionar?": card VEREDICTO com critérios
  queimados — amostra n/60, hit, EV líq, perna 0.75-0.80 viva/em teste/morta,
  max dd, ritmo trades/dia até 03/11; WATCHLIST §72; spark equity realizada;
  breakdowns por bot/combinado) · LABORATÓRIO (exp maker com EV/fill + borda
  verde/vermelha + veredicto no dossiê 20/10; painel A contrafactual taker com
  hit/BE/EV/EV líq; painel B fills sombra+Micro) · CIDADES (inalterada —
  HOJE/RESOLVIDAS OUTUBRO/SEM ATIVIDADE) · HISTÓRICO (linha do tempo dos
  últimos 30 dias agrupada por dia, cor = bot, OPEN "comprou @¢" / CLOSE
  WON/LOST com Σ do dia)
- Backend: /api/shadow by_band agora devolve band,n,hit,be,ev,ev_net — BE =
  ask médio da faixa (breakeven real), fee = 0.05·p·(1−p); resposta directa
  ao dono: o bin 0.90-1.01 (hit 93.8%) tem BE 94.2% → EV líq ≈ −0.7pp, NÃO
  é oportunidade; hit% alto sem EV>0 é a armadilha
- Apagados do frontend: Visão Geral/Equity/A vs B/Shadow/Maker/Eventos
  (conteúdos absorvidos); events passa a days=30; refresh condicional por tab
- Validado: babel vendored transform OK · ast.parse server OK · start_
  dashboard.sh · curl 200 nas 9 rotas · shapes reais dos endpoints conferidas
  contra o JSX (nada de referências órfãs)

## 74. ÁRVORE DE DECISÃO PRÉ-REGISTADA — DOSSIÊ MAKER 20/10 (18/10, "segue a tua intuição")
- Registada ANTES dos números de 19-20/10, cega por construção. Mecânica: o
  dossiê D4 corre sozinho 08:07 diário (cron); no dia 20 lê-se a corrida da
  manhã e escolhe-se o ramo — sem improviso. Estado ao registar (18/10):
  fill rate 10% (12/118) · hit dos fills 42% (5/12) · EV/fill −$0.33 ·
  IC95% do hit [14,70] — teto abaixo do BE 75% → Ramo 1 é o provável,
  mas provável não executa nada até ao dia 20
- RAMO 1 — maker MORTO (hit fills <60% a n≥12, ou teto do IC <75%): mata-se
  a perna maker do D real (sem bids novas). D passa a PAUSA/OBSERVAÇÃO —
  NÃO vira taker (sombra: EV ≤0 em TODAS as faixas de ask, não há plano B
  taker). A sombra A+B CONTINUA tal-qual: é paper, zero custo, preserva a
  opção de redesenhar a bid (preço/TTL) na era v5/A5 e alimenta o fecho da
  era. Era v4.1 continua ao contracto próprio (n=60/03-11), inalterado
- RAMO 2 — FRONTEIRA (hit 60-72% e/ou EV/fill entre −0.10$ e +0.05$):
  nada muda no D real — fica a micro-stake $1-2 (é o teste da perna real
  mais barato que existe). Veredicto definitivo adia-se para o fecho da era
  (D-v4/03-11). PROIBIDO mexer na bid a meio da era: 75→78¢ ou TTL novo é
  um experimento novo, não um ajuste — pertence ao desenho da era v5
- RAMO 3 — maker VIVO (hit ≥75% a n≥15 e EV/fill ≥0): D real CONTINUA a
  $1-2. Subida de stake fica trancada atrás do GO A5 da era: maker positivo
  ≠ estratégia aprovada — as duas perguntas ficam deliberadamente separadas
  e só o veredicto da era (n=60) abre a porta da escala
- REGRAS TRANSVERSAIS (todos os ramos): (i) contracto GO/NO-GO A5 intocável
  por qualquer resultado do maker; (ii) stake do D nunca sobe acima de $1-2
  durante a era; (iii) o critério "fills reais ≥3" do dossiê NÃO será
  cumprido a 20/10 (D tem 0 fills na era) — o veredicto é da SOMBRA: se diz
  MORTO não se paga dinheiro real para confirmar; se diz VIVO, escalar exige
  na mesma fills reais ≥N numa fase posterior; (iv) cenário subpoderado:
  se a 03/11 chegar com n<40, a era estende-se automaticamente até n=60 —
  o contrato é a amostra, a data era só planning aid — sem outras mudanças
  durante a extensão
- Fundamento do "não antecipar" (rejeitado executar já em 18/10): exposição
  real ≈ 0 (D: 0 fills, bids raramente live) → não há sangramento a
  estancar; cada fill extra aperta o IC de graça; e excepções "desta vez era
  óbvio" são assim que se começa a mover metas — o precedente disciplinar
  vale mais que dois dias de dados

## 75. REAL 21/10 PRÉ-REGISTADO — UNIVERSO, EXECUÇÃO, TAKER MORTO (18/10, aprovado "sim")
- Contratado ANTES dos números de 19-20/10. O lançamento real de 21/10 fica assim:
- UNIVERSO: as 6 do B (munich, madrid, paris, seoul, moscow, istanbul) + LUCKNOW
  como 7ª DECLARADA — entra por decisão de desenho do dono (preferência declarada,
  NÃO evidência: n=2 na era é ruído e os fills maker da sombra em lucknow foram
  2 LOST em brackets diferentes). Mesmo gate F1 (p_win ≥ 0.82), mesmo stake
  $1-2, mesmo maker 75¢/TTL60. Custo aceite e registado: mais uma stream de
  bids (a adverse selection escala com o nº de bids)
- EXECUÇÃO por ramo do dossiê 20/10 (árvore §74): Ramo 3 maker vivo → B-config
  em real micro · Ramo 2 fronteira → continua micro, veredicto adiado para o
  fecho da era · Ramo 1 maker morto → sub-opção decidida no dia 20 com números:
  pausa OU colecionador de fills reais a $1-2 (custo esperado ~$2-4 até 03/11,
  preenche o critério "fills reais ≥N" que de outro modo fica vazio para sempre)
- TAKER-AT-ASK: MORTO por evidência — sombra com 255+ sinais resolvidos dá
  EV líq ≤ 0 em TODAS as faixas de ask (0.75-0.80 = −11.4pp; 0.86-0.90 =
  −37.6pp). Não é configuração de arranque do real a 21/10 nem fallback do
  maker ("comprar à ask com cuidado no spread" = pagar a edge do market maker
  + taxa; o EV da era vem exclusivamente da melhoria de preço 75¢ vs ask
  77-87¢). Só renasce como hipótese na era v5 com dados novos
- STAKE: ≤ $1-2 até GO A5 (regra transversal §74, inalterada)
- HELSINKI: nem candidata (§72, viés de estação). CAPE-TOWN: fora do real por
  desenho (não pertence ao universo B); o critério objetivo §72 (revisão se
  EV<0 a n≥5) continua a aplicar-se ao registo em paper

## 76. PAINEL CHART POR CIDADE — DEBUG VISUAL "MODO TERMINAL" (18/10, pedido do dono)
- Clique numa cidade (cards das tabs Hoje e Cidades) abre modal fullscreen:
  chart intradiário dual-axis (temp °C esq · probabilidade dir) + sub-painel de
  mercado (ask/bid do bracket alvo em ¢) + faixa REGRAS da era v4.1 em texto
  colorido (sempre visível, "permanentemente recordadas" — pedido do dono) +
  trades de outubro da cidade · Esc/setas ‹ ›/✕ fecham ou navegam cidades
- Séries: temp hoje (âmbar) · running_max (degrau branco) · ONTEM (cinza) ·
  forecast WU (laranja) · p_ensemble (ciano, dir) · p_lgbm quando existe ·
  threshold (roxo, dir) · gate F1 0.82 (azul, dir) · banda do bracket alvo
  (sombra ciano; "or lower" = sombra abaixo do teto) · stop level rmax−δ
  (vermelho) · linha de resolução 🏁 (verde, do market_winners) · portão
  horário (vertical âmbar) · markers ▲ compra / ▼ stop · legenda clicável p/
  esconder séries
- Backend: GET /api/city_chart?city=X&date=opcional — junta ticks A/B/D
  (live_bot_logs{,_v6,_micro}/ticks/ticks_<city>_<date>.jsonl, ficheiro com
  mais linhas vence; schema idêntico nos 3) downsampled passo 3 + série de
  ontem (só temp/rmax) + strategy_config da cidade + resolução do dia
  (match de slug no market_winners com sufixo -2) + closes de outubro da
  cidade (city vem do market_slug nos BET_CLOSE — o campo city está vazio
  nos closes!) · validação de city/date (400 em inválidos)
- Nota: imagem de referência do dono não chegou à conversa — desenho seguiu
  a descrição; ajustes visuais depois do primeiro uso
- Validado: babel vendored OK · ast OK · curl 200 (munich/istanbul) · 400
  cidade inválida · /api/maker íntegro após restauração de 2 linhas
  derrubadas num edit acidental (bids = {} + path maker_bids.json)

### 76a. Iteração visual (19/10) — imagem de referência do dono finalmente recebida
(photo_2026-10-18_18-33-32.jpg — secção "Charts" da Polymarket): fundo com BANDAS
VERTICAIS alternadas (rects 1.5h centradas entre labels de 3h, rgba(255,255,255,.028)
no tema escuro) · secções colapsáveis com chevron (Temperatura / Mercado) + header
"📊 Charts" com colapsar/expandir tudo · legenda CLICÁVEL movida para BAIXO do chart
(estilo ref.) · linha da temperatura em crimson #e5484d espessa 2.2 (hero line)
· helper Xmin() para posicionar bandas em minutos

## 77. VEREDICTO DOSSIÊ 20-21/10: MAKER MORTO — RAMO 1 ASSINADO (21/10)
- Sombra V2 (bid fixa 0.75 desde 03/10, n=14 resolvidos + 6 pendentes): hit 7/14 =
  50% vs breakeven 75% · EV −25pp · P&L −$3.50 · fill rate 9% (14/153) · P(≤7/14 |
  hit real 75%) ≈ 1.6% → adverse selection estrutural, não ruído. Fills reais do D:
  0 na era (gate ≥3 ⏳ para sempre). Critérios do Ramo 1 (§74) cumpridos com folga
- DECISÃO DO DONO no Ramo 1 (21/10): (b) COLECIONADOR — o D real continua como
  está (4 cidades madrid/seoul/moscow/munich, D4_MAKER=1, stake $1-2, SEM
  restart: 0 fills na era, o modo colecionador é a continuação natural). Custo
  esperado ~$2-4 até 03/11 · valida a perna real (API/timing/fills) + mantém a
  infra quente para a v5. Universo B-6 + lucknow do §75 fica em suspenso — era
  a decisão do lançamento maker, que o Ramo 1 matou; passa a matéria do
  desenho v5
- Era v4.1 ao assinar: n=14 · 12W/2L · hit 85.7% · P&L +$1.50 · EV +9.8pp · A n=10
  hit 80% / B n=4 hit 100% (entram istambul 10-20 e seul 10-19) / D n=0 · perdas
  continuam a ser só helsinki+cape-town (watchlist §72) · A abriu tel_aviv @0.75
  21/10 11:53 (taker no PISO da banda — não viola §75: a regra proíbe pagar
  77-94¢; o piso a 75¢ é a configuração com 85.7% de hit na era)
- PACE: 0.78 trades/dia → a 03/11 n≈24 < 40 → REGRA §74(iv) DISPARA: era estende-se
  automaticamente até n=60 (contrato é a amostra, a data era planning aid)
- Pergunta de engenharia v5 (NÃO decide a meio da era): como executar a 75¢ sem
  adverse selection — candidatos: taker-no-piso (modo do A: comprar quando ask =
  75¢, sem esperar que o preço atravesse a bid), momento de colocação da bid, TTL
- Nada mais muda: contracto GO/NO-GO A5 intocável · stake real ≤$1-2 · A/B paper
  seguem até ao fim da era

## 78. ERA V4.1 FECHADA PELO DONO (21/10, n=14 — sem esperar pelos 60)
- Veredicto estatístico FORMAL: INCONCLUSIVO (hit 85.7% ± ~18pp a n=14 — o IC inclui
  valores abaixo do breakeven; não provado nem refutado). Fica dito com letras —
  o fecho antecipado é decisão do dono, não resultado do contracto
- O que ficou PROVADO na v4.1: (i) maker a 75¢ MORTO — adverse selection estrutural
  (50% hit nos fills, p≈0.016) · (ii) taker-at-ask (77-94¢) morto desde o início
  (contrafactual EV ≤0 em todas as faixas) · (iii) helsinki/cape-town na watchlist
  pré-registada comportaram-se exactamente como o fundamento previa
- DESCOBERTA CHAVE AO FECHAR: as 14 entradas da era foram TODAS taker-no-piso
  (maker=False nos ledgers — o A/B compra quando ask ≤ 0.75; o maker era só o
  colecionador/sombra do D). Ou seja: a estratégia viva da era NUNCA foi o maker
  — é o taker-no-piso: 14 trades a 0.75 · 12W/2L · hit 85.7% · EV +9.8pp EM PAPER.
  O risco em aberto: o sim de paper assume fill ao ask 0.75 — validade em livro
  real (size, partial fills) é a pergunta nº1 da v5
- Pool para v5: 36 cidades calibradas. CORRECÇÃO ao que se dizia acima: as 4
  parked NUNCA foram excluídas por volume — re-screen 22/10 (gamma API, mercado
  de 21/10) mostra os 36 mercados num contínuo de $10.6k (panama_city) a $81k
  (istanbul), SEM penhasco; buenos_aires ($34k, vol24h $20k) está ACIMa de
  incumbentes aprovadas como moscow ($15.7k). Volume/liquidez NÃO discrimina
  o universo — a selecção original das 19 não foi um screen de liquidez
- O que limita o pace NÃO é liquidez: ticks mostram o ask do alvo a passar
  pela banda 0.75-0.92 em ~2064 ticks/dia (20 cidades, 15-21/10) — o deserto
  é o ALINHAMENTO portão-do-modelo × janela-de-preço: 0.039 entradas/cidade-dia
  realizadas na era → estimativa v5: 34 cidades ≈ 1.3 entradas/dia ≈ n=60 em
  ~45 dias
- Viés documentado (audit §19): helsinki confirmada (+0.6-0.8°C) e mexico_city
  (+2°C ×2, PWS) — excluídas por viés independente dos resultados · karachi
  (+1.2 suspeita) fica EM OBSERVAÇÃO para o audit mensal obrigatório
- D real colecionador (§77) mantém-se até ter fills reais suficientes; A/B paper
  seguem a correr (custo zero, dados continuam a acumular para validação cruzada)

## 79. ERA V5 — PRÉ-REGISTO (proposta aprovada em desenho 21/10, universo após re-screen 22-23/10)
- EXECUÇÃO: taker-no-piso — entradas SÓ quando ask ≤ 0.75¢ (o modo que a v4.1
  correu de facto: as 14 entradas eram todas maker=False). Maker morto (§77);
  bids à espera proibidas; pagar >0.75 proibido (contrafactual: EV ≤0 acima)
- UNIVERSO (34 cidades): as 36 calibradas − helsinki (viés §19 confirmado) −
  mexico_city (viés §19, +2°C×2 PWS). As 4 parked REGRESSAM (buenos_aires,
  panama_city, toronto + as outras 11 que nunca correram: chengdu, chongqing,
  guangzhou, kuala_lumpur, qingdao, sao_paulo, shanghai, shenzhen, singapore,
  taipei, wellington, wuhan) — re-screen 22/10 provou que volume NÃO era o
  motivo de exclusão (contínuo $10.6k-81k, sem penhasco). Karachi fica EM
  OBSERVAÇÃO (suspeita +1.2°C §19, audit mensal obrigatório). Cidades NUNCA
  escolhidas por resultados (regra queimada)
- BRAÇOS: A5 = taker-no-piso puro, 34 cidades · B5 = taker-no-piso + gate F1
  (p_win ≥ 0.82), 34 cidades — mesma metodologia A/B (mercados iguais,
  comparação limpa)
- GATES IGUAIS À V4.1: threshold do modelo por cidade · portão horário hour_min
  · stop-loss running_max − stop_loss_delta
- CONTRACTO: GO se EV líq > 0 a n=60 (critério primário; hit reportado, não é
  o contrato) · entradas só ≤0.75 sem excepções · nada mexe a meio da era ·
  se n<40 quando o calendário apertar, estende até n=60 (mesma regra §74iv)
- GATE DO REAL: paper v5 com n≥15 e EV líq >0 E colecionador D com ≥3 fills
  reais (≥1 taker) → D real passa a taker-no-piso, stake $2-5, config B5.
  Até lá D continua colecionador maker (decisão §77)
- PACE ESPERADO: 0.039 entradas/cidade-dia (era) × 34 ≈ 1.3/dia (A5) → n=60
  em ~45 dias
- CÓDIGO: bots A/B já correm o modo — lançamento = novos --cities + novo
  ERA_CUTOFF_V5 no dashboard. VERIFICADO 23/10: as 15 novas têm calibração +
  modelos completos em disco (lgbm_rebound.pkl + quantiles.pkl F1); o
  strategy_config_<city>.json NÃO é usado pelo live bot (artefacto de
  backtest) — as 3 parked têm MDL+CAL e não precisam de mais nada

## 80. ERA V5 LANÇADA (23/10 16:52) + LIÇÕES OPERACIONAIS (26/10)
- Lançamento real: A5/B5 relançados 23/10 com 34 cidades (cities_active.txt),
  --max-buy-ask 0.75 pinado nos DOIS (a regra do piso NÃO vinha das calibrações
  — best_params não têm min/max_buy_ask; o default do código era 0.60-0.90 e a
  v4.1 comprou a 0.75 por alinhamento modelo×preço, não por pinagem — as 15
  cidades novas COMPRARIAM a 0.80+ sem o pin). Gate F1 do B5: 0.82 (decidido
  23/10: precedente v4.1 4/4 + B5 é o braço qualidade; ESTUDO DE GATE no fecho
  v5 com os p_win registados — pré-registado cego)
- Contratempo 1 (23/10): crash no arranque — faltava o PEAK MODEL nas 3 parked
  (cities/<c>/<c>_peak_model/). Fix: copiado de excluded_cities/ (só os 3
  parked o tinham lá; as 12 nunca-corridas já tinham tudo em cities/)
- Contratempo 2 (23→26/10): TypeError no display.py (posição com size=None em
  cidade nova — `pos.get("size", 5.0)` devolve None quando a chave existe com
  valor None). Patch: `pos.get("ask") or 0` / `pos.get("size") or 5.0`.
  LIÇÃO QUEIMADA: o traceback no fim do bot_live.log NÃO mata o processo — o
  display renderiza num caminho que apanha a excepção e a trading loop continua.
  Os bots tradearam 23→26/10 com o traceback no log. ANTES de relançar por
  "crash": verificar `ps` / tmux, não o fim do log
- Contratempo 3 (26/10): relançamento DESNECESSÁRIO meu (matei processos
  saudáveis com posições abertas por assumir o contratempo 2 como fatal).
  Sem dano (resume de estado limpo, paper), mas registo o erro de procedimento
- Estado v5 a 26/10 07:30: n=11 resolvidos · 5W/6L · hit 45.5% · P&L −$3.25
  (paper) — começo fraco, n pequeno; contrato continua a ser n=60
- Anomalias explicadas: (i) busan aparece 9× LOST no ledger do A = SPAM DE
  ESCRITA do close (dedup 'último ganha' de _era_trades protege as stats;
  FIX do writer fica pendente) · (ii) toronto 5 posições A+B = uma compra/dia
  em mercados DIÁRIOS diferentes enquanto não resolviam — pipeline de winners
  cobre as cidades novas (cache tem 2-3 resolvidos/cidade); closes chegam com
  o ciclo do collector · (iii) toronto/buenos_aires/panama/sao_paulo sem ticks
  de manhã UTC = mercados das Américas FECHADOS nessa hora (panel mostra
  "FORA DE HORA") — NÃO é bug
- Dashboard: ERA_CUTOFF 2026-10-23 · labels era v5 · regras do painel cidade
  actualizadas (maker MORTO · taker-no-piso · gate real §79)
- TREINO: não foi preciso re-treino para lançar — modelos são artefactos
  congelados da era (mesma vintage Agosto/2026 nas 34); re-treino global é
  matéria de era v6 (decisão no fecho v5, nunca a meio)

## 81. REBOOT DA ERA V5 (26/10 — pedido do dono: "dashboard limpa, reiniciar bots")
- Ledgers/posições ARQUIVADOS (não apagados) em archive_era_v5_reboot_20261026/
  (1.1MB: trade_ledger + paper/real_positions + live_snapshot dos 3 bots) — o
  histórico v4.1+v5 fica preservado para análise; apagar fica a um rm do dono
- Contadores a ZERO: cutoff 2026-10-26 · n=0 · bots reiniciados (A5/B5 34
  cidades piso 0.75 · D colecionador via start_micro.sh) · collector 34 cidades
- Contrato INALTERADO: n=60 decide (GO = EV líq>0), nada mexe a meio. O reboot
  é higiene de contagem, não mudança de estratégia — as mecânicas são as
  mesmas; nota honesta: "assumir que vai falhar" + reiniciar o mesmo é coerente
  apenas como limpeza; o veredicto continua a pertencer ao n=60
- Dashboard: cards dos 3 bots com explicador "▸ como decide" (mecânicas +
  decisões de cada bot, BOT_INFO) · Era card sem data-fim — ritmo actual em
  trades/dia, "n=60 decide, a data é só planning aid"
- CIDADES DO REAL (pergunta do dono): confirmadas as mesmas 4 (madrid, seoul,
  moscow, munich) — papel do D é colecionador de execução real; as cidades são
  irrelevantes para esse papel (0 fills em 6 semanas; o binding é o gate §79,
  não a geografia). "As 5 melhores" REJEITADO por critério queimado: a n=11
  (agora 0) "melhores" = ruído (data-snooping proibido §79) e 5 cidades matam o
  pace (~0.3/dia → n=60 em ~7 meses = experimento morto). Alternativa objectiva
  se o dono quiser foco: top-5 por actividade de banda medida (re-screen §80:
  seoul, munich, moscow, paris, madrid) — disponível mas não recomendado
- Re-treino: continua NÃO preciso — modelos congelados da era (mesma vintage
  nas 34); re-treino global = decisão de era v6 no fecho

## 82. BACKTEST OOS SET→OUT — SELECÇÃO DAS 5 CIDADES DO REAL (pré-registo cego, 26/10)
- MOTIVAÇÃO do dono: modelos treinados até Jul/2026 → janela 2026-09-01→hoje é
  out-of-sample puro (zero leak). Resultado destina-se a escolher as 5 cidades
  do REAL (D) — o paper segue com 34 para o n=60 (pace do real é irrelevante)
- FONTE: replay dos TICKS REAIS (~1/min) — não o backtester.py, que usa
  SimulatedMarket (asks sintéticos por climatologia + ruído = não responde à
  pergunta). Ticks A desde 27-29/8, v6 desde 12/9 → janela 1 Set→26 Out coberta
- REGRA DE REPLAY (exacta do v5): entrada no 1º tick do dia em que
  0.60 ≤ ask_do_alvo ≤ 0.75 (min default 0.60 + pin 0.75) ∧ p_ensemble ≥
  threshold ∧ hora local dentro de [start_hour, end_hour] da calibração ·
  máx 1 posição/cidade/dia · preço de entrada = ask do tick · saída =
  resolução real (market_winners) coberta pelo bracket alvo (temp_lo≤w≤temp_hi)
- MÉTRICA QUEIMADA (decidida antes de correr): ranking por EV/trade (win
  +(1−entry) · lose −entry, por share) · ELEGIBILIDADE n≥5 trades na janela ·
  desempate: n maior → hit% · winner's curse assumido: 32 cidades testadas,
  top-5 é selecção dentro de amostra — tratado como escolha de CONCENTRAÇÃO
  para real micro, não como prova de edge (o edge prova-se no n=60 do paper)
- POOL: 34 − helsinki − mexico_city (viés §19, queimado) = 32 cidades ·
  karachi entra no ranking com flag de observação (+1.2°C §19)
- DESTINO: top-5 → cidades do D real (colecionador mantém mecânica e gate §79;
  start_micro.sh CITIES_M actualizado) · se o dono vetar uma cidade, entra a
  6ª da lista
- ADDENDO ÀS CEGAS (28/10, escrito DEPOIS de lançar o replay mas ANTES de abrir
  qualquer resultado): identificou-se uma discrepância de desenho — a regra
  queimada acima é a regra v5 (banda 0.60–0.75), mas o D real compra na banda
  0.80–0.90 + filtro F1 + maker D4. Decisão queimada agora:
  (a) MÉTRICA DE SELECÇÃO INALTERADA — ranking v5 por EV/trade, elegível n≥5.
      Rationale: a banda v5 é onde a era está a ser validada (paper n=60) e tem
      mais fills → mais poder estatístico; a banda D tem fills raros demais
      (shadow: bins 0.80+ com n=2–6 em ~3 semanas) para ranking por cidade.
  (b) DIAGNÓSTICO SECUNDÁRIO em banda D — replay 0.80≤ask≤0.90 SEM filtro de
      modelo (envelope pessimista; o F1 não é replayável: ticks não guardam
      p_win do cérebro B) + coluna informativa p_ensemble≥0.82 (proxy) +
      frequência maker (dias com sinal em que o ask chegou a ≤0.75). Este
      diagnóstico NÃO altera o ranking; serve de sanity check — se uma top-5
      for catastrófica na banda D (n≥3 e hit muito baixo), reporta-se ao dono
      com os números antes do restart, mas a selecção mantém-se salvo veto.
- RESULTADO (28/10, janela 2026-09-01→28, 58 dias, pool 34 — output do replay
  diz "pool 34": cities_active.txt tem 36 entradas, −2 excluídas):
  TOP-5 (métrica queimada EV/trade, elegível n≥5): beijing n=17 W14-3 hit 82.4%
  EV+0.142 · london n=13 10-3 76.9% +0.106 · paris n=15 12-3 80.0% +0.104 ·
  seoul n=7 5-2 71.4% +0.035 · munich n=17 12-5 70.6% +0.024.
  Elegíveis (14): as 5 acima + moscow −0.025 · amsterdam −0.078 · karachi
  −0.098 (flag +1.2°C, fora do top-5 de qualquer modo) · tokyo −0.103 ·
  warsaw −0.119 · milan −0.134 · cape_town −0.225 · madrid −0.328 ·
  manila −0.451. lucknow 3/3 W mas n=3 → inelegível (queimado, custa ao dono
  que gosta dela — fica no paper A/B que a mantêm).
  JSON: backtest_results/oos_replay_2026-09-01_2026-10-28.json
  SANITY BANDA D (sem filtro de modelo, envelope pessimista): beijing +0.028 ·
  london +0.053 · seoul +0.090 ✓ positivas; paris −0.098 (n=31, hit 74.2%) e
  munich −0.028 (n=27) ligeiramente negativas — reportado ao dono, selecção
  mantida: n_82 (proxy p_ens≥0.82) = 0 para ambas na banda D → com o filtro F1
  raramente comprariam na banda D; na banda v5 (onde o modelo as escolhe)
  são #2/#5 com n=13/17. Madrid/moscow (cidades antigas do D): −0.181/−0.070
  na banda D, −0.328/−0.025 na v5 → saem com confirmação OOS.
  JSON: backtest_results/oos_dband_2026-09-01_2026-10-28.json
  APLICADO (28/10): start_micro.sh CITIES_M=beijing,london,paris,seoul,munich
  · D real reiniciado 08:48 tmux micro · bootstrap OK 5/5 · 0 erros · V3 ICAO
  deu None nas 3 cidades novas → fallback V2 OK (padrão conhecido, não é erro)
## 83. JANELA LONGA 2025→18/7/26 — DIAGNÓSTICO IN-SAMPLE (pré-registo cego, 29/10)
- PEDIDO do dono (29/10): backtest "de todas as cidades desde 2025" p/ mais
  poder estatístico (motivação: lucknow n=3 inelegível no §82). Limites físicos
  explicados ao dono: (i) preços de mercado reais só existem desde 27/8/2026
  (ticks) — antes disso só mercado sintético; (ii) obs meteorológicas em
  historic/ acabam 19/7/2026; (iii) 1/1/2025→18/7/2026 é DENTRO do treino
  (modelos treinados até ~18/7/2026) = LEAK, não evidência de edge.
- O QUE FOI QUEIMADO antes de ver resultados: correr
  backtest_hist_cassiopeia.py = cassiopeia_backtester.run_backtest (rebound ML,
  resolve_params da calibração activa) sobre obs REAIS 2025-01-01→2026-07-18,
  preço fixo 0.70 · hit% é a métrica honesta (independente do preço); EV@p
  analítico a partir do hit% · diagnóstico usado APENAS para: (a) skill
  aparente em amostra grande, (b) GAP DE MEMORIZAÇÃO = hit_IS − hit_OOS (§82)
  por cidade — gap pequeno = modelo robusto na cidade; gap grande = skill IS
  era memorização. NÃO reabre a selecção do D: as 5 cidades (beijing, london,
  paris, seoul, munich) mantêm-se salvo veto/aprovação explícita do dono com
  os números na mão.
- Também re-corridos os replays OOS com a janela real máxima 27/8→29/10
  (--ini/--fim adicionados aos dois scripts).
- RESULTADO (29/10): IS 2025→18/7/26 (preço fixo 0.70, LEAK): hit% 98.2
  (qingdao) → 69.7 (sao_paulo); todas as cidades inflacionadas pelo treino —
  gap IS−OOS universalmente positivo. GAP como diagnóstico FUNCIONOU: as piores
  OOS (manila 65.0pp · madrid 48.3 · cape_town 48.7 · milan 37.5 · tokyo 32.4)
  têm os maiores gaps; as 5 do D têm gaps 9.6–20.6pp (london 9.6 menor).
  lucknow IS 87.7% (n=446) → o 3/3 OOS é consistente com skill real do modelo,
  mas evidência de LUCRO OOS continua fina (n=3 elegível; banda D n=33 EV
  −0.044). Mantém-se no paper; promoção futura se n≥5 elegível e dono aprovar.
  OOS com janela real máxima 27/8→29/10: TOP-5 INALTERADO (london 0.106 ·
  paris 0.104 · beijing 0.094 · seoul 0.035 · munich 0.024) — selecção do D
  confirmada; madrid caiu para −0.278. JSONs: hist_cassiopeia_2025-01-01_
  2026-07-18.json · oos_replay_2026-08-27_2026-10-29.json · oos_dband_ idem.
## 84. OBJECTIVO DO DONO = %WIN GLOBAL · SHRINKAGE MOSTRA QUE "CIDADES RARAS 100%" NÃO ELEVAM A %WIN (29/10)
- Dono clarificou: não liga a nº de trades; quer %winrate global alta — aceita
  10 cidades onde 7 façam pouquíssimos trades mas acertem sempre.
- RESPOSTA NUMÉRICA (shrinkage empírico, prior = base rate OOS do pool v5
  120/188=63.8%, k=30): a %win VERDADEIRA estimada de uma cidade 3/3 OOS é
  ~67% — idêntica a london 10/13 (67.8%). lucknow shrunk 67.1% = london:
  estatisticamente gêmeas; 3/3 vs 10/13 é ruído em torno do mesmo valor.
- CENÁRIOS de pool (pesos = ritmo OOS): D5 67.8% · D5+lucknow+jeddah 67.7% ·
  D5+todas as 100%-hit (12 cidades) 67.6% · D5+11 raras 67.4%. As "raras
  perfeitas" têm shrunk médio 65.9% — ABAIXO do pool: seleccioná-las piora
  (ligeiramente) a %win esperada. Winner's curse quantificado.
- ALAVANCAS QUE REALMENTE MOVEM %win global: (1) threshold F1 ↑ (menos trades,
  mais certeiras — é exactamente o motor "poucas mas ganham"; testar 0.85 em
  paper), (2) preço de entrada ↓ (breakeven mais baixo), (3) cortar perdedoras
  (madrid/manila/cape_town já fora). Nº de cidades é a alavanca mais fraca —
  %win é trade-weighted; 3 trades/mês de uma cidade rara movimentam o global
  ~0.1-0.3pp.
- Nenhuma acção tomada: D5 mantido. Se o dono quiser mais cidades no real
  mesmo assim, exige regra pré-registada nova + aprovação; toronto/buenos_aires/
  panama_city continuam excluded_cities (conflito de dados, não de resultados).
## 85. TESTE F1 0.85 NO PAPER (B) — PROTOCOLO PRÉ-REGISTADO (29/10, dono aprovou "sim")
- OBJECTIVO do dono (§84): maximizar %win global; aceita poucos trades se
  ganharem quase sempre. Alavanca escolhida: subir o threshold do filtro F1.
- MUDANÇA: start_paper_v6.sh — V6_MIN_PWIN 0.82→0.85 · CITIES_B +beijing,
  +london (cobertura das D5; madrid/moscovo/istanbul mantidas p/ amostra).
  A5 (34 cidades, sem filtro) = braço de controlo inalterado.
- BRAÇO 0.82 termina hoje no paper (histórico da era antiga mantido: B 0.82
  fez 83.3% hit em n pequeno). Ticks não persistem p_win → comparação forward
  é B(0.85) vs A5 vs histórico 0.82.
- REGRA DE DECISÃO (queimada): avaliar quando B(0.85) tiver n≥20 trades
  resolvidos OU em 2026-11-29 (o que chegar primeiro). Promover o D a
  V6_MIN_PWIN=0.85 SSE hit_B shrunk ≥ 85% E hit_B ≥ hit_A5 (mesma janela,
  cidades D5) + 8pp. Caso contrário D mantém 0.82. Nenhuma outra alteração.
- Dashboard: labels actualizados (A 34 · B 8 · D 5) no BOTS do server.py.
- PACE observado 26→29/10 (ticks, ground truth): A = 5 city-dias de compra
  em ~4 dias (~1.2-1.7/dia; OOS 64d média 2.9/dia) · banda 0.60-0.75 ocupa
  só ~2% dos ticks (oportunidade é estreita e sazonal — Outono = forecasts
  confiantes, asks nos extremos) · B = 5 city-dias (ainda a 0.82) · D = 0 fills
  (era continua zerada; maker_filled inexistente). Box rebootou 29/10 08:36;
  autostart recolocou as 5 sessões tmux (verificado).
- EMENDA §85 (29/10, dono aprovou): avaliação intercalar em 2026-11-29 com gate
  n≥8 + hit 100% → promove D a 0.85; caso contrário o teste continua até n≥20
  SEM data-limite (o ritmo 0.85 esperado é 1–3/mês; n≥20 demoraria meses).
## 86. RECALIBRAÇÃO SAZONAL PÓS-ERA (plano, dono aprovou 29/10 — executar DEPOIS do n=60)
- Motivação: era genérica tem thresholds/janelas únicas para todo o ano; o
  Outono esvazia a banda cara (asks nos extremos). Escalonado:
  1. Recalibração por estação (barata, infra existente): recalibrar thresholds/
     janelas com peso Outono–Inverno sobre os dados reais acumulados.
  2. Meta-modelo: logística P(win | p_ens, ask, hora, cidade) sobre os ticks
     reais resolvidos (~500+ até lá) em cima dos modelos congelados.
  3. Só depois, se 1+2 justificarem: retrain completo (dados até ~Dez).
- NOTA: treino actual JÁ inclui 16 Outonos (2010→Jul/26) e features month/doy —
  o problema não é o modelo não conhecer o Outono; é o mercado não ter dúvida.
- RESTRIÇÃO: nada disto mexe na era corrente (modelos congelados são o contrato
  do n=60). Só no fecho da era.
## 87. D-v5 NO REAL — DUPLO BRAÇO (dono aprovou 29/10)
- PROBLEMA: D colecionador = 0–2 trades/mês (don­o quer 0.5–1/dia). FRONTEIRA
  (§84): volume+%win+EV>0 — só 2 cabem. Ponto com volume: banda v5 a ~70% win.
- IMPLEMENTAÇÃO (single process, 1 posição/cidade/dia intacto):
  v6_filter.arm_decision(ask, v5_max, f1_min) + patch no bloco V6_FILTER do
  cassiopeia_live_bot.py. Sem envs → 'f1' sempre (back-compat byte-a-byte).
  start_micro.sh: --min-buy-ask 0.60 --max-buy-ask 0.90 · V6_V5_MAX_ASK=0.75 ·
  V6_F1_MIN_ASK=0.80 · V6_MIN_PWIN=0.82 (colecionador) · D4_MAKER=1.
  Braços: ask≤0.75 → v5 puro (sem F1) · 0.75–0.80 → ZONA MORTA · ≥0.80 → F1.
  Configs partilhadas com A NÃO foram tocadas (segmentação é interna/env).
- GATE DE QUALIDADE (queimado): ao fim de n≥20 trades resolvidos do braço v5,
  se hit shrunk <60% → D reverte para colecionador puro; senão mantém. Dono
  revê em qualquer caso. Check semanal de ritmo: se <0.3/dia ao fim de 2 semanas
  → reportar (provável sazonalidade vazia → candidato §86).
- RISCO honesto: braço v5 em real = regra do A5 a dinheiro real; EV esperado
  pequeno (+0.02..+0.10/shrunk nas 5 cidades) — stake $1-2 e kill-switch
  (dd>$5 / 3 losses) limitam o drawdown máximo enquanto medimos.
## 88. DIAGNÓSTICO 07/11 — D NUNCA COMPROU REAL: BREAKER PARTILHADO TRIPADO DESDE PRÉ-ERA
- FACTOS: real_positions.json no arquivo do reboot 26/10 = [] → D com ZERO fills
  em toda a vida. Era actual: 0 bought city-dias em 12 dias de log, 0 compras
  reais. Log do D mostra "⛔ breaker: drawdown global — revisão humana" em
  TODAS as tentativas de compra (ex. 07/11 london braço v5 a 69–73¢ ×4, todas
  bloqueadas).
- CAUSA: v6_breaker.STATE = live_bot_logs/breaker_state.json — FICHEIRO ÚNICO
  partilhado por A+B+D (todos correm do mesmo cwd). Estado acumulado pré-era
  (35 cidades, grand −29.18$, peak 0.54$, dd 29.72 ≥ CB-2 $15) e NÃO foi
  arquivado no reboot 26/10 ("contadores a zero" falhou aqui). A/B são paper
  e não consultam o breaker (compraram normalmente 26/10–07/11); o D (real)
  fica bloqueado. O breaker está a fazer o trabalho dele — o estado é que é
  inválido para a era.
- SECUNDÁRIO: live_bot_logs_v6/v6_gate_stats.json corrompido desde 9/10 (JSON
  "Extra data" → cada escrita falha silenciosamente "inofensivo") → monitoring
  do gate F1 cego desde 9/10; as DECISÕES do gate não são afectadas (o corte
  0.85 funciona: madrid 07/11 p_win 78.9% ⛔).
- ERA v5 (26/10→07/11): A n=9 resolvidos (6W/3L, hit 67%, ≈+0.9$/share) ·
  B 0 trades (gate a filtrar tudo) · D 0 (breaker). Box esteve OFF 06/11
  (sem ticks), reboot hoje 09:04, autostart OK (5 sessões).
- DECISÃO PENDENTE (dono): (a) arquivar breaker_state.json e reiniciar pico a
  zero (revisão humana = este diagnóstico: o trip é artefacto de estado
  pré-era, não sinal de risco real — D tem zero perdas reais); (b) corrigir o
  flaw estrutural: breaker por bot (STATE derivado de CASS_LOG_DIR, ex. D lê
  live_bot_logs_micro/breaker_state.json) para o paper do A não poder matar o
  real do D; (c) apagar v6_gate_stats.json corrompido; (d) restart D.
- APLICADO (07/11, dono aprovou): (a) breaker_state.json arquivado em
  archive_breaker_state_20261107/ (baseline pré-era fora do caminho); (b) FIX
  estrutural — v6_breaker.STATE = $CASS_LOG_DIR/breaker_state.json (por bot:
  A/B/D isolados; 3 testes novos, 34 passam) + escrita atómica tmp+rename em
  v6_breaker._save e no v6_gate_stats (o PC reboota à brava e write_text
  directo corrompia JSON); (c) v6_gate_stats.json corrompido apagado (recria-se
  fresco; stats agora seguem o CASS_LOG_DIR do caller); (d) restart A→B→D
  (ordem segura face ao pkill genérico do start_paper.sh). Verificado:
  can_trade=True para as 5 cidades do D · 4 sessões ticking · dashboard
  relançada. start_micro.sh: comentário kill-switch corrigido (CB-2 $15, não $5
  — texto antigo do MICROBOT_D.md).
## 89. RETROSPECTIVA 7/11 — 9 MESES, PORQUE DEMOROU (pedido do dono, análise sem alterações de código)
- LINHA DO TEMPO: Fev/26 solo mono-city munich (backtests "incríveis") · Mar/26
  ChatGPT+Claude entram, começa o ping-pong de bugs · Mar-Ago: multi-city,
  camadas de thresholds/features, 4 bugs TZ, fallback silenciosos, bug DD/MM
  "invalidou a era v1" · Set/26: mês da complexidade máxima (V6 roadmap, F1
  quantile ×36, stairs v7 ×36 modelos, audits) → era v4 (19/9) · Out: v4.1,
  dossiê maker → "maker morto" (§77), era fechada cedo n=14 (§78), era v5,
  e a viragem: pré-registo cego consolidado (§72+) · 7/11: breaker partilhado
  diagnosticado (§88), D desbloqueado.
- CAUSA DOS BACKTESTS INCRÍVEIS V1 (§30): backtester contra SimulatedMarket —
  circular (modelo vs climatologia que gerou os asks) + fee errada. Mediu o
  modelo contra si mesmo.
- LIÇÃO CENTRAL: com IA, código deixou de ser o gargalo — passou a ser a
  estatística (dias de mercado real). Cada camada nova era uma hipótese não
  validada antes da seguinte. Complexidade como anestesia da falta de validação.
- ESTADO: 69 py / ~25.6k linhas / 4 bots / 22 gates numa compra / 37 patches
  arquivados. Não é "um bot"; é um laboratório com plumbing de produção.
- DAQUI: congelar features até ao veredicto n=60; ARCHITECTURE.md de uma página
  pós-era (a árvore de decisão nunca foi desenhada — HANDOVER é cronológico,
  não arquitectónico); decisão GO/NO-GO/mais-60-era no fecho.
- Repo antigo (sonofnabia-droid/polyweather): 404 — privado ou apagado.
- ADDENDO V1 (07/11, clone local em polyweather-main/): Abril/26, mono-munich,
  ~120KB/10 ficheiros. LGBM + priors sazonais; REAL com confirmação manual y/n;
  Kelly + --threshold 0.80 + --min-edge; stop diário $50. munich_train.py e
  qualquer script de backtest NÃO estão no clone — o código que gerou os
  "resultados incríveis" nunca foi commitado/está perdido. O 92.17%/894 trades
  (§30, circular SimulatedMarket) continua fisicamente em
  cities/munich/strategy_config_munich.json a alimentar a cadeia de configs.
  AS FEATURES V1 (running_max, prev7, deltas, lags, morning_max...) são a
  mesma família do predictor.py actual → o núcleo do modelo sobreviveu 9 meses;
  o problema nunca foi o modelo, foi tudo à volta dele.
## 90. PLANO PÓS-RETROSPECTIVA (dono aprovou "sim a tudo", 08/11)
- LEITURA INTERCALAR QUEIMADA (decisão ~início Dez): em n=30 resolvidos da era
  v5 · se EV líq < 0 E hit < breakeven−5pp → NO-GO imediato (não esperar 60) ·
  se EV líq > 0 → continuar até 60 para confirmar · meio-termo → continuar.
  Métricas contabilizadas no cutoff da era (26/10), paper A + B, resolvidos.
- LIMPEZA EXECUTADA 08/11 → archive_legacy_20261107/: calipso_entry.py,
  calipso_live_bot.py, start_calipso.sh (C morto 03/10, autostart não chama),
  calibracoes_velhas/, cities_backup_20260828/, archive_applied_patches/,
  possible-trash/, v7_stairs_models/ (stairs parked §38; falha ALTA se usado —
  reproduzível via v7_train_stairs.py). MANTIDOS de propósito:
  cassiopeia_config_history/ (params.py escreve lá — §86 precisa),
  om_data_PARKED/ (§8 condições de regresso referem o path),
  testedmedia_data/ (edge_daily.py lê).
- REGRA DE OURO no topo do HANDOVER (§0). ARCHITECTURE.md = mapa de 1 página.
- LEITURA SEMANAL automática (cron segunda ~9h): ritmo n/60, erros, fills do D,
  estado dos checkpoints §85/§87.
## 91. FIX FOK orderType + CALIPSO IMPORT LAZY (08/11 — descoberto ao desbloquear o D)
- SEGUNDA camada que mascarou o D: com o breaker resolvido (§88), a primeira
  ordem real do braço v5 falhou: "ClobClient.post_order() got an unexpected
  keyword argument 'orderType'". A lib instalada é py_clob_client_v2 1.1.0 —
  a assinatura é post_order(order, order_type=... SNAKE_CASE). Só o ramo FOK
  (taker) usava camelCase → GTC/maker funcionavam, taker nunca. FIX:
  orderType= → order_type= (polymarket_clob.py:587) + teste de travão
  (grep-lock). D reiniciado, loop verde.
- ARQUIVO PARTIU O IMPORT: strategy_factory importava calipso_entry no topo
  (import morto desde 03/10) → ModuleNotFoundError ao arrancar o D após o
  §90. FIX: import lazy em _calipso_entry() com erro claro a apontar ao
  arquivo. Lição §9 reforçada: antes de arquivar, grep de IMPORTS — o meu
  grep de referências apanhou paths mas não este import directo (falso
  negativo: o ficheiro estava em modules/, o grep --include cobriu-o mas
  filtrei por diretórios de dados; correção de método, não de regra).
- ESTADO 08/11: D desbloqueado E com execução real funcional pela 1ª vez
  (breaker livre + post_order fixo). Próxima oportunidade braço v5 = 1ª
  compra real. A/B inalterados. 35 testes.

## 92. TG DO D: 4 MELHORIAS + 3 DESCOBERTAS DE FUNDO (08/11 — análise das msgs Telegram aprovada)
MELHORIAS APROVADAS E IMPLEMENTADAS (display só; nenhuma mexe na decisão):
- Icon coerente: calculado com os MESMOS p_use/thr_use do número mostrado
  (antes: icon via p_ensemble, número via p_rebound → "🔥 6/40%" absurdo).
- Ask do bracket alvo na linha do relatório (last_eval passa a guardar o ask
  assim que o bracket é encontrado, mesmo quando a compra é bloqueada).
- Relatório periódico só com atividade: envia se (a) 1º do dia, (b) estado
  mudou vs anterior, (c) 21h (resumo diário garantido). Mata o spam de 48
  cópias idênticas/dia. Alertas de transição (compra/bloqueio) inalterados.
- near_misses.jsonl no LOG_DIR: cada bloqueio "ask < mínimo" regista
  {ts, cidade, ask, p, threshold} — dados p/ decidir o piso 0.60 (§86/§90).
DESCOBERTA 1 — THRESHOLD DO TG ERA DO MUNDO ERRADO: o relatório mostrava
  35/40/55% (strategy_config_*.json, mundo SingleEntry) mas o gate real do
  modo cassiopeia (CassiopeiaEntry via cassiopeia_params.resolve_params) é
  threshold=0.20 p/ as 5 cidades, janelas 12–18/14–20, min 0.75/max 0.90
  (CLI do D faz override do min p/ 0.60). TG agora mostra o threshold real
  (last_eval.threshold). Lição reforçada: DOIS mundos de config (§11) —
  strategy_config só é lido por SingleEntry (backtest); o live todo é
  cassiopeia_active_config.json.
DESCOBERTA 2 — SEMÂNTICA DO GATE É FADE, O TG TRATAVA COMO MOMENTUM:
  CassiopeiaEntry compra quando p_rebound < threshold (fade do rebound:
  compra o bracket do floor(rmax) quando o modelo diz que o dia NÃO
  supera o máximo actual). O TG fazia "faltam N pts" = thr − p (semântica
  de subida). Agora: 🔥 = p_rebound < thr (sinal ativo); quando p > thr
  mostra "(faltam descer N pts)". P(pico) sem p_rebound mostra só a
  barra (não gateia nada no modo cassiopeia — não comparar com thr).
DESCOBERTA 3 — BUG MIN-SIZE $1 A BLOQUEAR TODA A COMPRA REAL DO D:
  log micro: "SEOUL BUY REJEITADO: invalid amount for a marketable BUY
  order ($0.7x), min size: 1" a CADA tick (hoje 8/11). Causa: PARCEL_SIZE=1.0
  → shares=floor(1.0/ask)=1 → size=1×ask=$0.76 < mínimo $1 da Polymarket.
  O milestone "1ª compra real" NUNCA ia acontecer — o breaker/orderType
  (§91) estavam certos; a ordem morre no size. MESMA causa provável nos
  D4-MAKER ERROR 400 (seoul, ordens GTC a 75¢). FIX PROPOSTO (aguarda
  aprovação, é sizing): shares = max(1, ceil(1.00/ask)) → size ≥ $1 sempre
  (ex.: ask 0.76 → 2 shares $1.52). Até lá o D continua sem conseguir comprar.
ESTADO: bots a correr com código antigo; restart do micro/bot/v6bot
  necessário p/ aplicar o TG novo. 1ª compra real segue BLOQUEADA pelo
  min-size (proposta em cima da mesa).

## 93. FIX MIN-SIZE $1 NO TAKER (08/11 — aprovado pelo dono)
- Log micro 8/11: "SEOUL BUY REJEITADO: invalid amount for a marketable BUY
  order ($0.7x), min size: 1" a cada tick. Causa: PARCEL $1.00 → 1 share;
  a 0.77¢ = $0.77 < mínimo $1 da Polymarket. Era a 3ª camada que matava a
  1ª compra real do D (§91 tinha resolvido breaker + orderType).
- FIX (cassiopeia_live_bot.py, antes do bet_record/buy): size ajustado para
  ceil(1.00/ask) shares — o maker D4 JÁ fazia isto (d4_maker.py MIN_NOTIONAL,
  emenda mecânica antiga): o taker é que ficou para trás nessa emenda.
- Efeito no sizing (dentro do $1–2 aprovado): braço v5 0.60–0.75¢ → 2 shares
  ($1.20–1.50); braço F1 0.80–0.90¢ → 2 shares ($1.60–1.80). Papers A/B
  passam a simular o mesmo size (coerência paper/real).
- FICA EM ABERTO: os "D4-MAKER ERROR 400" do micro NÃO eram min-size (o maker
  já usava 2 shares) — causa provável: post-only-reject quando o ask desce
  abaixo de bid+tick entre colocação e confirmação, ou mercado a fechar.
  Investigar na 1ª bid real que falhar com o novo logging.
- Milestone 1ª compra real do D: DESBLOQUEADO (breaker livre §88, orderType
  §91, min-size §93). Próximo sinal + ask na banda 0.60–0.75 → compra real.

## 94. GUARD COM RELAUNCH AUTOMÁTICO + PKILL DO A CIRCUNSCRITO (08/11 — aprovado)
- CONTEXT: 8/11 as sessões bot/v6bot/micro morreram misteriosamente entre
  12:07–12:44 (sem OOM, sem reboot, sem rasto no journal — causa em aberto).
  O alive_guard (hora a hora) só alertava: o real D ficaria 1h parado.
- FIX 1 (start_paper.sh): pkill genérico "cassiopeia_live_bot" (matava B e D!)
  → pkill -f "CASS_BOT=A" + tag CASS_BOT=A no comando tmux do A. Alinhado com
  os pkills circunscritos do B (cities) e do D (--run real).
- FIX 2 (bots_alive_guard.py): ao detetar problema, corre start_all_bots.py
  (idempotente; start_micro.sh valida chaves + pytest antes do real) e o
  alerta TG passa a incluir "relaçado automaticamente" ou o erro do relaunch.
  Anti-spam de alertas mantido (1x por incidente; resolução notificada).
- FIX 3 (cron): guard de hora a hora → */5 * * * * (janela de morte ≤5 min).
- TESTE PONTA A FIM: kill-session bot + guard manual → A de volta (ver log
  do alive_guard 8/11 ~13:10). Token TG em branco no teste p/ não spammar.
- RACE REAL NO TESTE (8/11 ~13:05): guard manual + guard cron (*/5)
  correram start_all EM PARALELO — o cron detetou o micro "morto" a meio
  do relaunch manual e lançou um 2º start_all. Sem duplicados no fim (os
  pkills/kill-session deduplicam), mas trabalho duplicado + janela de
  corrida. FIX: flock partilhado (live_bot_logs/.guard.lock, LOCK_EX|NB)
  no bots_alive_guard E no start_all_bots — quem não consegue o lock sai.
  O teste validou o relanço 2x: guard manual (A) e guard cron (micro).
  O dono pode ter recebido 1 alerta TG "micro MORTO — relançado" desse
  ciclo (o cron carregou o .env real).

## 95. AUDITORIA PROFUNDA (08/11 — dono pediu bug finding + strategy discovery; APROVADO)
Achados (evidência em cassiopeia_train.py / cassiopeia_backtester.py /
cassiopeia_calibrate.py / calibracoes_v1/ / historic/*.csv), por gravidade:
 1. CALIBRAÇÃO AO PREÇO ERRADO: calibracoes_v1 correram com entry 0.60 e
    fee 0 (confirmado aritmeticamente: pnl_per_trade = hit×0.40 − loss×0.60).
    O live compra a 75–90¢ com fee real 0.05·p·(1−p). Thresholds/janelas
    otimizados contra payoff errado.
 2. DADOS DE TREINO 100% INTEIROS (historic/*.csv, 289k linhas ×3 cidades
    verificadas) vs produção decimal. A label "rebound > rmax+0.3" em dados
    inteiros = "subida ≥1°C" na prática → p_rebound live é OOD.
 3. bracket_half PARÂMETRO MORTO: com dados inteiros, day_max ≤ rmax+0.3 e
    ≤ rmax+0.7 são idênticos (discordância zero em 16k entradas simuladas).
    O grid varreu-o em ruído puro; e o CassiopeiaEntry live nem o lê.
 4. GEOMETRIA DO BRACKET errada no backtester: hit = day_max ∈ rmax±0.5;
    real = bracket floor(rmax)..floor(rmax)+1. Invisível com dados inteiros.
 5. ENTRADA DIVERGENTE: backtest só entra quando temp == rmax; o live entra
    em qualquer tick da janela com p < threshold (inclui dips).
 6. BUG LATENTE train: se RF bater LGBM por ≥0.01 AUC → NameError (best_name
    indefinido), treino perdido após horas de compute.
 7. AUC reportado otimista: test set serve para early stopping E avaliação.
 8. SKEW cloud_real: 2.4% importância no treino (OM), em produção cai
    silenciosamente para cloud_cover WU. precip_last_3h e mais 4 features
    são peso morto (0 importância).
 9. LABEL 3h vs resolução EOD: entradas cedo têm ~8h de exposição, o modelo
    só vê 3h — subestima rebound tardio.
10. Fee do backtester 0.009×p subestima a real (~30–120% conforme preço).
APROVADO PELO DONO (8/11), execução em 4 itens:
 ITEM 1 (bugfixes puros, sem tocar em produção):
   - train: fix NameError (seleção robusta do melhor modelo); split 3-way
     temporal (64/16/20) — early stopping na val, AUC honesta no test;
     num_boost_round=500 explícito (n_estimators era ignorado).
   - backtester: fee passa a Polymarket real 0.05·p·(1−p)×shares (default
     "weather"; --fee-rate linear fica como override legado); hit passa a
     geometria floor-bracket real; entrada sem gate temp==rmax (alinha com
     o live: 1º slot da janela com p < threshold). Em dados inteiros a
     geometria nova é IDÊNTICA à antiga (verificado) — só muda com decimais.
   - calibrate: dimensão "bracket" removida do grid (parâmetro morto) →
     grids 3–7× mais rápidos; entry_price/fee propagados.
 ITEM 2 (recalibração, SÓ análise — apply fica a aguardar aprovação):
   5 cidades do D (munich/london/paris/seoul/beijing), entry_price 0.78,
   fee real, holdout-frac 0.25, grid standard, min_entries 30. Resultados
   apresentados ao dono ANTES de qualquer apply ao active config.
 ITEM 3 (estudo maker, só dados): quantificar nos fills sombra a 75¢
   (5W/6L, −3.25$) quantos seriam evitados com cancel-condicional
   (p_rebound sobe / temp aproxima-se do topo do bracket).
 ITEM 4 (ADIADO p/ depois da era v4.1): re-treino com histórico decimal
   (Open-Meteo archive) — resolve #2/#3/#4/#9 de raiz. Mexer nos modelos
   a meio da era invalidava a comparação n≥30 (§90).
§95 ITEM 3 — RESULTADO ESTUDO MAKER (8/11, dados 15/09–8/11, A+B):
  Fills deduplicados (city,slug,fill_ts): A=38, B=38 → 61W/15L = 80.3% hit.
  EV/fill = +5.3¢ (breakeven a 75¢ = 75.9%). O maker a 75¢ É LUCRATIVO.
  O alarme "adverse selection" (5W/6L) era artefacto do subset de 11 fills
  da era v4.1 no dashboard (incluía o colapso madrid ×8 contado a dobrar).
  Mecanismo das 15 perdas: 14 = o bracket morreu DEPOIS do fill (11–88 min;
  risco normal do trade, não toxicidade). SÓ 1 fill (busan 14/10) encheu com
  o bracket já morto há 43 min — guarda "cancelar bid se floor(rmax) > lo"
  teria evitado (−0.75$). Regra cancel-condicional NÃO se justifica agora.
  Contrafactual taker ao ask do momento da bid (~92¢): EV = −12¢/trade →
  o maker a 75¢ é precisamente o que torna estes sinais lucrativos.

## 96. APPLY RECALIBRAÇÃO v2 (09/11 — aprovado pelo dono)
- Recalibração §95 (commit 3defe79): entry 0.78 + fee weather real +
  geometria floor-bracket + entrada sem gate temp==rmax, holdout 25%.
  OOS (1511 dias, 2022-05→2026-07): edge +9.5% (munich) a +14.2% (seoul),
  hit 88–93%. Top-3 quase empatados → robusto.
- APLICADO ao active config (versões 20261109_081012_*): thr 0.25→0.20 em
  london/paris/seoul/beijing (munich já tinha 0.20); munich janela →12-20h;
  seoul →14-18h. Banda min/max_buy_ask preservada (0.75-0.90).
- BOUNDARY CHECK (thr 0.05-0.20): thr=0.05 dá hit OOS 97-99% mas é
  DISTORCIDO — entradas ~1h mais tarde (avg 16-17h vs 15-16h) quando o ask
  real já está >90¢; o backtester de preço fixo não vê isso. NÃO aplicado.
  thr=0.20 aplicado tem avg entry 15-16h (meio da tarde, saudável).
- PRÓXIMO ESTUDO (Item 5, aprovado): backtest price-aware com asks reais
  dos ticks — aí sim avaliar se thresholds <0.20 têm EV coletável.

## 97. BUG RESUMOS ESCONDEM LOSSES (09/11 — descoberto pelo dono, fix direto)
- O dono estranhou "11W/0L" no resumo TG do A. Auditoria ao ledger:
  8/11 teve 3 LOSSES (cape_town 28→29, munich 8→9, tokyo 17→18) + 7 wins
  que ficaram "SIMULATED" para sempre. Verdadeiro 7d: 18W/3L, não 11W/0L.
- CAUSA: posições paper evaporam num restart (paper_positions volátil).
  O crash de 8/11 12:44 matou as posições abertas de 10 cidades; o settle
  EOD só resolve posições em clob.positions (memória) → essas bets nunca
  foram marcadas. _reconcile_bets_from_csv só corria no ARRANQUE do
  processo — e o A não reiniciou desde 8/11 13:04.
- FIX: reconcile passa a correr também no rollover diário (passo 1b de
  _handle_day_rollover). PnL reconciliado NÃO entra nos daily_stats do dia
  (pertence a dias passados; resumos leem os ficheiros de bets).
- ONE-SHOT retroativo (9/11): A reconciliou 10 bets (−2.04$; 3 losses);
  B reconciliou 4 (−0.73$; incluía shanghai 26/10 — loss escondida há 14d).
- NOTA: D real nunca tocou cidades excluídas porque a sua lista é explícita
  (--cities beijing,london,paris,seoul,munich) — a exclusão não é por mecanismo.

## 98. BASIS RISK WU vs METAR — settle oficial + fonte live METAR (09/11 — aprovado pelo dono)
- DESCOBERTA (gatilho: 1ª compra real do D, 8/11 London 11°C @~68¢, $1.44):
  o mercado resolveu 10°C (METAR EGLC máx "10/07"); o nosso live via WU v3
  viu 11.0 das 12:49-15:29 UTC → comprámos um bracket que no mundo METAR
  nunca existiu. LOSS real −$1.44 (a contabilidade nem o registou — ver §97).
- AUDIT (v5_station_audit.py, 55 dias): 20% de mismatch WU-peak vs vencedor
  oficial (11/55; tokyo até 2°C). Critério ≥5% = basis risk real → confirmado.
- REGRAS DO MERCADO (descrição oficial Gamma): resolve pelo METAR do ICAO da
  cidade (ex.: EGLC), remark de temperatura em DÉCIMAS; SPECI não conta.
- DECISÕES APROVADAS (09/11):
  1. SETTLE PELA RESOLUÇÃO OFICIAL (Gamma winners), paper e real:
     _reconcile_bets_from_csv e _settle_paper_positions_for_day passam a
     preferir o vencedor oficial do market_slug (módulo novo
     official_resolution.py, cache live_bot_logs/market_winners.json);
     fallback para WU/history_max só se a Gamma não tiver resolução.
     Efeito: P&L paper = verdade do dinheiro; o trade de London 8/11 fica
     LOST (−$1.48 registado; fill real −$1.44, diferença ask snapshot 67¢
     vs fill 71¢ — aceite).
  2. FONTE LIVE METAR (aviationweather.gov, grátis, sem key) com fallback
     WU: _fetch_current_obs e _bootstrap_today preferem METAR do city.icao
     (staleness >90min ou <3 slots no bootstrap → WU). Humidade derivada de
     temp+dewpoint (Magnus); cloud_cover das camadas (FEW/SCT/BKN/OVC).
     Alinha a entrada (running_max, features) com a fonte de resolução.
     SKEW CONSCIENTE: modelos treinados em WU (inteiros); METAR também
     reporta inteiros no grupo principal — o bias removido é exatamente o
     que custou o trade de London. Re-treino com fonte METAR fica para o
     Item 4 (dados decimais), adiado para depois da era v4.1.
  3. Maker orderType: NÃO era bug vivo — §91 (3af76a0, 8/11 07:19) já
     corrigiu; bots reiniciados 8/11 13:04-13:05 e a compra das 13:34
     provou o caminho FOK. Braço maker GTC ainda sem fill real (não provado).
- CRITÉRIO DE SUCESSO: reconcile marca London 8/11 LOST; audit de
  mismatches sobre dias NOVOS (pós-deploy) deve cair para ~0% na
  contabilidade (settle oficial) — a % de mismatch de OBSERVAÇÃO live é
  monitorizada via tick logs (temp METAR vs WU fica registado).

## 98b. REGRAS OFICIAIS COMPLETAS + dados METAR (09/11)
- Lida a descrição COMPLETA do mercado (Gamma) + PDF oficial:
  · Fonte de resolução = aviationweather.gov (URL exata nas regras).
  · T-remark (T + 8 dígitos, décimas) governa quando presente; senão o
    grupo do corpo (inteiros). Arredondamento half-up: 13.9→14, 16.5→17,
    −8.5→−8 (para +inf). Bracket X°C = round_half_up(pico) == X, i.e.
    pico ∈ [X−0.5, X+0.5) — DIFERENTE do [X, X+1) que o settle paper usava
    (só difere com dados em décimas; com inteiros coincide).
  · Dia = tempo local da estação; SPECI não conta; COR conta; reports
    fora de hora CONTAM ("one issued off the nominal hour").
  · Fallback se AWC sem dados: WU Daily Observations.
- IEM É INCOMPLETO para labels: perde reports off-hour (prova: EHAM
  30/10/2026, report 11:25Z com 13°C na AWC, ausente no IEM → máximo IEM 12
  vs vencedor oficial 13). Cross-check parcial (2 cidades): 87% match.
- OGIMET tem o feed completo mas cobertura irregular por ano/estação
  (EHAM: 2020 vazio, 2023 ok) e só ~1 mês por query → remendo cirúrgico,
  não espinha dorsal. NOAA ISD estagnou em 2025-08. AWC só guarda 30 dias.
- PIPELINE DE DADOS (historic_metar/, formato idêntico ao WU):
  1. metar_history.py: IEM 2000→hoje (base; uv_index=0 — METAR não tem UV).
  2. ogimet_backfill.py: substitui dias cobertos (≥6 reports) em
     2025-01→hoje por linhas ogimet com temp em DÉCIMAS (T-remark).
  3. metar_archive_daily.py: cron diário a partir da AWC (arquivo oficial
     nosso a partir de hoje — a AWC só retém 30 dias).
- LIVE: metar.py passou a ler o T-remark do rawOb quando presente
  (décimas ao vivo = leitura idêntica à resolução). Deploy 9/11 ~10:30.
- NOTA p/ re-treino: labels devem usar round_half_up(pico) (convenção do
  mercado), não floor nem [lo,hi+1). Features live vêm em décimas de
  estações com T-remark e inteiros das outras — registar no treino.
- PENDENTE: cron metar_archive_daily (23:55); re-treino 34 cidades
  (treino ≤2024, OOS 2025→hoje) após validação do dataset.

## 99. PIPELINE RE-TREINO METAR — implementação (09/11 tarde)
- PROBLEMA CADÊNCIA: METAR raw é horário (e 3-em-3h em estações antigas,
  ex.: ZGGG 2000); os modelos foram treinados em WU ~30min e as features
  pressupõem slots de 30min (delta_30m, lag_3, janela futura = 6 slots = 3h).
- SOLUÇÃO (metar_resample_30min.py): reamostragem para grelha UTC de 30min
  com FORWARD-FILL limit=6 slots (3h) → historic_metar_30min/{city}.csv.
  ffill (não interpolação) porque é exatamente o que o live faz (cada slot
  usa a última obs METAR). Máximo diário preservado (ffill nunca inventa
  valores acima do observado). Efeito colateral aceite: 89/9809 dias
  (0,9%, chongqing) em que o ffill atravessa a meia-noite local quando há
  gap noturno — igual ao comportamento live; o settle oficial usa os
  vencedores Gamma, não estes CSVs.
- FIX feature_injection.py: cloud_real passa a ter fallback para sky_cover
  (fração 0-1; normaliza se vier em %) quando 'condition' está vazio
  (CSVs METAR não têm condition textual). Antes: cloud_real=NaN → dropna
  apagava o dataset METAR inteiro. Piloto chongqing: 45% cobertura.
- cassiopeia_train.py: (a) --model-dir-name (default inalterado
  "cassiopeia_rebound_model") → modelos METAR vão para
  cities/<city>/cassiopeia_rebound_model_metar/ SEM tocar nos modelos WU
  em produção; (b) drop automático de features degeneradas no dataset
  (nunique<=1: uv_index=0, condition_windy=0) — o config do modelo
  serializa a lista efetiva e a inferência live segue-a
  (cassiopeia_predictor lê feature_cols do config).
- cassiopeia_backtester.py / cassiopeia_calibrate.py: --model-dir para
  apontar ao dir do modelo METAR no backtest OOS e na calibração.
- SPLIT (trancado, §98b): treino+calibração ≤2024-12-31 (--end-date),
  OOS 2025-01-01→hoje numa única passada no fim.
- metar_archive_daily.py: cron instalado (55 23 * * *, venv) — arquivo
  oficial contínuo a partir de hoje.
- 41/41 testes de regressão passam após as edições.
- PILOTO chongqing em curso (437k linhas, 9132 dias 2000→2024).
- SEPARADO: earn-hunter (OKX Earn monitor) ativado — crontab 17 * * * *,
  scan.sh com OKX_PROFILE=live (API key mode). TG pendente: user tem de
  acrescentar TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID a
  ~/.okx/earn-hunter/env.snapshot para receber push fora da sessão.

## 100. BUG ZOMBIE PÓS-§98 — bots sem registar obs durante ~7h (09/11, fix 17:35)
- SINTOMA: "Tick failed: 'hour'" em TODAS as cidades das 3 fleets desde o
  restart das 10:28 (~19k ocorrências). "METAR current OK" imprimia, mas o
  tick morria logo a seguir.
- CAUSA: o dict de fetch_metar_current (metar.py) não traz "hour"/"minute"
  (traz obs_time UTC-aware); o tick faz new_obs["hour"] em
  cassiopeia_live_bot.py:1434 → KeyError → slots_so_far nunca atualizava →
  zero sinais/trades no caminho METAR. Descoberto porque o user perguntou
  se o Andromeda tinha morrido (estava vivo — pid 253747 — mas zombie como
  os outros).
- FIX: _fetch_current_obs deriva hour/minute na tz da cidade a partir de
  obs_time quando o dict vem do METAR. Verificado ao vivo (EGLC) + 41/41
  testes. Bots reiniciados ~17:35.
- LIÇÃO: o restart pós-deploy precisa de um SMOKE CHECK automático — contar
  "Tick failed" nos logs 5 min depois do arranque e alertar. Pendente:
  acrescentar ao start_all_bots.py ou ao guard.
- DADOS PERDIDOS: janela 10:28→17:35 sem slots/sinais — era v4.1 não
  registou nada nesse período (teria havido sinais? verificar no shadow
  collector, que corre em sessão separada e NÃO usa este codepath).

## 101. OOS BACKTEST 2025→hoje — METAR vs WU, 34 cidades (09/11 noite)
- METODOLOGIA: modelos METAR (cassiopeia_rebound_model_metar, treino
  ≤2024-12-31, 26 feats, LGBM, AUC 0.887–0.971) vs modelos WU em produção;
  MESMOS params de produção (resolve_params) + entry fixo 77¢ + fee weather
  real; janela METAR 2025-01-01→hoje, WU 2025-01-01→2026-07-18 (fim dos
  dados WU). Driver: oos_backtest.py → backtest_results/oos_2025_metar_vs_wu.csv.
- RESULTADO: METAR ganha ao WU em 34/34 cidades (d_pnl>0 em todas).
  Totais: METAR +$3049 (20.045 trades, 93.1% hit) vs WU +$1924 (16.563, 89.5%).
  Por trade: METAR ~15.2¢ vs WU ~11.6¢.
- WU perdia dinheiro OOS em 3 cidades (sao_paulo 75.4% hit, buenos_aires
  73.9%, panama 74.6%) — METAR resolve as 3 (+20.0¢/+14.1¢/+5.8¢ por trade).
- Top METAR ¢/trade: qingdao 20.7, sao_paulo 20.0, milan 19.2, karachi 18.6,
  chongqing 18.5, seoul 18.3, jeddah 18.3, shenzhen 18.2.
- Cauda METAR: toronto 3.5¢, panama 5.8¢, istanbul 12.6¢.
- CAVEATS: (1) fills a 77¢ hipotéticos — P&L absoluto otimista, mas
  comparação/ranking válidos (mesmo preço nos dois braços); (2) janelas
  diferentes — comparar ¢/trade, não totais; (3) params são WU-calibrados —
  calibração fresca METAR pode melhorar (próximo passo opcional).
- GATE §98b: OOS METAR ≥ WU → PASSA 34/34. Recomendação: era v4.2 com
  modelos METAR. Deploy aguarda aprovação explícita do dono.

## 102. ERA v4.2 — DEPLOY METAR EM PRODUÇÃO (09/11 ~19:00, aprovado pelo dono)
- GATE §98b passou 34/34 → dono aprovou troca completa (A/B paper + D real)
  + calibração METAR da shortlist.
- SWAP de modelos (reversível): cities/<city>/cassiopeia_rebound_model (WU)
  → _wu (backup); cassiopeia_rebound_model_metar → produção. 34/34 cidades.
  Bots carregam a dir padrão → passam a usar os modelos METAR (26 feats,
  sem uv_index/condition_windy; prior_map serializado incluído).
- ERA: dashboard ERA_CUTOFF 2026-10-26 → 2026-11-09 (contadores limpos,
  histórico em disco intacto); ERA_MARKERS += v4.2 (METAR). v4.1 fecha com
  n=20, 85% hit, ~break-even (pipeline WU).
- CALIBRAÇÃO shortlist (qingdao, sao_paulo, milan, karachi, chongqing,
  seoul, jeddah, shenzhen, madrid): calib_metar_shortlist.sh — CSVs
  trimmed ≤2024-12-31 (anti-leakage), entry 77¢, holdout-frac 0.2
  (grid ≤~2020, valida 2020→2024), escreve cassiopeia_calibration_<city>.json
  para REVISÃO — não aplica à config ativa sem aprovação.
- Smoke check pós-restart: contar "Tick failed" nos logs (lição §100).

## §103 — Item 5: backtest price-aware com asks reais (9/11 ~23:00)
`backtest_price_aware.py` (novo): replay dos ticks reais (3 fleets, ≥2026-10-01,
911 sinais, 35 cidades), entrada ao ASK REAL do minuto do sinal, resolução
oficial (market_winners; fallback rmax em 79/911). Output: backtest_results/price_aware_v1.txt.
Identidade útil: EV/share = hit% − ask − fee(0.05·p·(1−p)).
Resultados era v4.1 (sinais WU; v4.2 tem n=2 — amostra por encher):
- Hipótese flat-77¢ era otimista ~7¢/tr: ask real médio na banda = 84¢.
  Mesmas 73 entradas: ask real −0.95$ vs flat-77¢ +4.14$.
- Sweep teto (min 75¢): 0.85→−1.3¢, 0.90→−1.3¢, 0.93→−1.8¢, 0.95→−1.4¢,
  0.97→−0.7¢, 0.99→−1.4¢/tr. TUDO ~breakeven/negativo a asks reais.
- NÃO subir max_buy_ask: 0.90–0.99 acerta ~95% mas breakeven aí é 96.5–98%.
  O bucket "≥0.90 hit 97%" engana — é inflacionado por asks ≥0.99 (EV também ~0).
- Edge positivo existe no lado BARATO e é específico de cidade:
  istanbul n=36 ask 0.34 hit 53% → +18.8¢/tr; wellington/qingdao/shenzhen idem.
  min_buy_ask=0.75 pode estar a bloquear entradas +EV — investigar com dados v4.2.
- Implicação: EVs absolutos da tabela OOS §101 (flat 77¢) são otimistas;
  o RANKING relativo das cidades deve manter-se. Re-correr este script
  semanalmente sobre ticks v4.2 (METAR) para re-avaliar com n decente.

## §104 — Tick-ladder + DB local de mercado (10/11 ~06:50)
Aprovado pelo dono ("dados que não vêm na gamma API, para caçar pérolas").
- `tick_logger.py`: novos campos `market_full` (TODOS os brackets: label/lo/hi/
  ask/bid/spr + src=clob|gamma — só ±3° do rmax + pontas têm quotes CLOB reais,
  o resto é gamma outcomePrices) e `target_book` (top 5 níveis bid/ask + depth
  USDC do bracket alvo — para o estudo maker 75¢). Zero chamadas API extra
  (o OrderBook já era fetched pelo enrich_bracket). `market_top` intacto
  (compat dashboard). Smoke em produção: 11 brackets/tick, clob=3-9, book=S.
- Fleets reiniciadas 06:39 (bot/v6bot/micro via start_all_bots.py); 0 Tick failed.
- `compact_market_data.py` (novo): JSONL→SQLite `market_data/market_ladder.db`
  (tabelas ticks/ladder/book_depth/compacted), incremental, só dias fechados,
  cutoff SINCE=2026-11-10 (histórico pré-ladder fica em JSONL). Cron: 19 4 * * *.
- Análise futura: fills maker simulados com depth real, timing de entrada,
  edge cidade×faixa (§103) com dados v4.2 — re-correr backtest_price_aware.py
  semanalmente.

## §105 — Calibração METAR shortlist aplicada (10/11 13:11)
9/9 cidades shortlist approved no holdout OOS 2020→2024 (n=1255-1761/cidade,
hit 95.5-98.8%, +17.6 a +20.9¢/tr a 77¢ flat). Aplicadas via
cassiopeia_params.apply_calibration (histórico versionado + backup
cassiopeia_active_config.json.bak_20261110). Padrão: threshold 0.2 em todas,
janelas alargadas (12-14h → 18-20h), min_spread 0.3 (chongqing 0.7),
outlier_cap 2.0 em karachi/madrid. min/max_buy_ask intocados (decisão do dono).
Fleets reiniciadas 13:11 — smoke: 0 Tick failed, ticks novos com thr=0.2 +
market_full. Não-shortlist intocadas (verificado contra backup).
rest25 (25 cidades por OOS ¢/tr) a correr — ETA quinta 12/11 madrugada;
aplicar essas SÓ com aprovação do dono após tabela.

## §106 — Limpeza dashboard v4.2 + bug crítico cross-city settlement (11/11 12:00-13:40)
Pedido do dono: dashboard "bem limpa" de vestígios pré-v4.2. Feito E, durante
a verificação, descoberto e reparado um bug crítico no restart das fleets.

**Dashboard (cosmético/semântico):**
- display.py: `_active_params()` — threshold/hour_min dos cards e do status
  vêm de resolve_params (config calibrada ativa) com fallback ao last_eval do
  entry; antes liam o strategy_config SingleEntry (bug §92 só tinha sido
  corrigido no relatório TG). `n_signal` do snapshot agora conta o status
  "SIGNAL!" real (antes: direção invertida p>=thr — no rebound compra-se
  p<threshold). Position do card lê entry_ask dos registos restaurados
  (acabou o "? @0¢").
- index.html: era "v5"→"v4.2 METAR" em todo o lado; eraDays NaN fix (cutoff
  com hora); META 60→30 (checkpoint §101); gates reescritos (GO hit≥70% &
  EV>0 a n≥30); watchlist helsinki marcada EXCLUÍDA (já saiu no swap);
  "RESOLVIDAS EM OUTUBRO"→"DESDE 1 OUT"; Histórico conta compras+resolvidos;
  Regras reescritas p/ rebound (p_rebound<thr, banda 0.75-0.90); F1 0.82→0.85.
- server.py: /api/equity ganha `era_combined` (max_dd só pós-cutoff — o KPI
  mostrava -2.50$ de eras antigas com n=0); /api/events faz backfill de city
  via RE_SLUG (fim dos "—" no Histórico); /api/shadow + /api/shadow_history
  filtram captured_at >= HIST_SINCE (setembro fora, regra do dono);
  /api/city_chart: hour_min do strategy_config (stale) → resolve_params.
- 41/41 testes OK. Dashboard reiniciada (usa .webvenv, NÃO venv).

**BUG CRÍTICO — settlement cross-city (descoberto porque "PnL hoje" saltou
de -2.36 para -24.37 após restart):** `_settle_paper_positions_for_day`
corria por cidade sobre o paper_positions.json PARTILHADO pela frota, sem
filtro de cidade: cada uma das 34 cidades settle as posições das outras com o
SEU peak. A posição de kuala_lumpur (32°C @0.79, mercado ainda aberto) foi
resolvida LOST em 8 cidades → 8 BET_CLOSE duplicados no ledger, daily_pnl de
31 cidades com -0.79 fantasma, manila/KL com settle prematuro +0.21, e
paper_positions.json truncado pelos saves concorrentes.
- Fix: filtro de cidade (slug) + `settle_today=False` no startup (peak
  parcial não resolve o próprio dia) em _settle_paper_positions_for_day;
  mesmo filtro no bloco do tick loop (all_positions). B (v6) e D (real)
  não afetados (D é real-only; B tinha 0 posições abertas no ficheiro).
- Reparação (`repair_20261111.py`, backups em repair_backup_20261111/):
  8 closes duplicados removidos do ledger; paper_positions.json reconstruído
  do ledger (35 abertas reais + 2 históricos); daily_pnl/paper_state
  corrigidos por delta (+0.79/-0.21) — validado contra valores das 11:48
  (tokyo +0.20, singapore -1.68 ✓).
- Efeito colateral BOM: no restart seguinte o settle oficial (Gamma) fechou
  24 posições órfãs de 8-10/11 que nunca tinham tido BET_CLOSE no ledger —
  a era v4.2 passou de n=1 para n=12 (hit 83.3%, PnL -0.14$). "PnL hoje" de
  11/11 inclui essa regularização única (+0.26$) — não é performance do dia.
- §106b (11/11 ~13:50) FECHADO: re-persist do restore movido para DEPOIS do
  CLOB init — o bloco init grava `state._repersist_rec` e um novo bloco pós-CLOB
  faz `state.clob.positions.add(...)` se houver rec e clob. py_compile OK ·
  suite 41/41. NÃO se reiniciou nada por causa disto: o código em produção já
  tem o fix crítico §106; o §106b carrega no próximo restart natural.
- Micro (D) morreu ~13:16 sem traceback logo após BUY real paris FILLED
  (order 0xd1711a3b, 0.87, 2 shares). Log antigo truncado pelo restart
  (start_micro.sh usa `tee` sem -a — prova perdida). Dashboard flask morreu na
  mesma janela (12:50-13:25): 2 processos python mortos no mesmo minuto sem
  traceback = assinatura de SIGKILL/OOM — máquina com 7GB RAM, 6GB usados (bot A
  34 modelos LGBM + calibração rest19 + pytest de arranque). Hipótese OOM NÃO
  provada (sem acesso dmesg/journalctl). O alive_guard detetou mas o relanço
  automático do micro FALHOU (razão por investigar); `bash start_micro.sh`
  manual 13:38 funcionou, posição paris restaurada.
- MELHORIAS: `tee -a` APLICADO nos 4 start scripts (paper, v6, micro, dashboard —
  logs de crash já não se perdem no restart; bash -n OK nos 4). PENDENTE:
  watchdog de RAM · cuidado com pytest+arranques com calibração a correr.

## 17/11/2026 — alinhamento do Micro D PAPER / Atalanta
- Auditoria read-only confirmou que Dashboard 2 aponta D para `live_bot_logs_micro_paper`, mas `start_all_bots.py` ainda encaminhava D para `start_micro.sh` (legado REAL); o guardião exigia só A/B/D e não monitorizava sessões C/D PAPER.
- Atualizei o autostart para A/B/C/D PAPER: C chama `start_andromeda_c.sh`, D chama exclusivamente `start_micro_paper.sh`; D REAL não é chamado. O guardião agora exige sessões `bot`, `collector`, `v6bot`, `c_bot`, `micro_paper` e quatro processos Cassiopeia.
- O autostart também recupera o `collector` sozinho se A continuar vivo, evitando reiniciar Cassiopeia por falha isolada do auxiliar.
- Dashboard backend e rótulos apresentam D como Atalanta PAPER, TAKER direto, sem MAKER; D REAL legado é indicado como suspenso.
- Verificações locais: `py_compile` em `start_all_bots.py` e `bots_alive_guard.py`; `git diff --check` nos ficheiros alterados; verificações textuais dos rótulos. Não executei launchers, não reiniciei dashboard/bots e não confirmei estado runtime (socket tmux indisponível nesta sessão).
- Execução autorizada em 17/11: verificação inicial encontrou apenas A/B, collector e dashboard; o autostart lançou C (`c_bot`) e D (`micro_paper`) em PAPER, sem reiniciar A/B/collector e sem iniciar D REAL. Dashboard recarregada.
- Verificação final da API: A Cassiopeia, B Andromeda, C Andromeda C e D Atalanta aparecem `mode=paper`, `alive=true`. Corrigi também o padrão `pgrep` de C: o redirecionamento para log não fazia parte da linha de comando do processo e dava falso `alive=false`. Últimas 200 linhas dos logs de C/D: sem traceback nem falha de orderbook; os logs anteriores de C continham falhas transitórias de pedido CLOB.
- 17/11 09:20 Europe/Lisbon: novo snapshot read-only da API, os quatro bots `alive=true`; A/B/C/D reportam `n_signal=0`, `n_bought=0`, `daily_trades=0`, `daily_pnl=0` e capital PAPER de 1000. Sem oportunidade/execução até esta verificação; não interpretar como resultado de estratégia.
- 17/11: Dashboard V2 ganhou cobertura por bot em chips discretos (`COBERTURA · N CIDADES`). A lista de A deriva de `cities_active.txt`; B/C/D refletem as listas dos launchers. `/api/overview` validado após reload: A=34, B=8, C=12, D/Atalanta=5. Cartões agora mostram C como “Andromeda C” sem duplicar a letra e todos os quatro modos PAPER.
- 17/11 — Dashboard V2 refinements (pedido do utilizador): cartões mostram idade/frescura do snapshot, cobertura por cidade com estado (sinal/compra/stop/janela/ask) e Decision Flow do snapshot; contadores F1 identificados como acumulados. Radar de cidades agrega atividade A/B/C/D. O replay existente mantém temperatura, probabilidades, bid/ask, depth, gates registados e caveats de settlement; painel de qualidade agora inclui quantidade de snapshots cotados e spread mediano, explicitamente não-executáveis. Performance recebeu curvas de P&L PAPER e MaxDD por bot desde o mesmo cutoff da era (`/api/equity.era_bots`).
- Validação: Flask recarregada; API devolve listas/funil por bot e curvas era A/B/C/D; `/static/index_v2.html` servido com os novos módulos. Sintaxe Python/JS e `git diff --check` sem erros. Nenhum bot, cutoff, modelo, SQLite ou regra de negociação foi alterado.
- 17/11 — Dashboard V2 pro desk (aprovado): módulo isolado `dashboard/static/v2_pro_desk.js` acrescenta health rail global (processos, snapshots atrasados, cidades ativas, frescura API), oportunidade atual por snapshot com bracket/ask/bid/hora e caveat de executabilidade, matriz Cidade × Bot, filtros bot/cidade/período persistidos em `localStorage`, formatação tabular e alternância de densidade. A matriz distingue estado não reportado de estado de gate; a tape declara que é snapshot, não timeline histórica. Período filtra a Auditoria e a Performance; esta usa data de fecho do trade, cidade e bot. Para suportar isso, `/api/era` fornece `ts_close` e `resolved_trades` com campos mínimos, e `/api/equity` expõe `era_days`; os filtros de bot/cidade também delimitam cobertura/tape/tabelas, enquanto health continua global. Período “máximo disponível” pede até 10 anos no endpoint de eventos. V2 e template terminal carregam o módulo; serviço `dashboard` recarregado via `start_dashboard.sh`, sem reiniciar bots/collector. Verificações: `node --check`, AST de `dashboard/server.py`, `git diff --check` nos alvos e Flask test-client (JS estático 200; `/api/overview` 200). O `alive` observado no Flask test-client não foi usado como prova de runtime, pois o subprocesso `pgrep` nesse contexto de teste não confirma visibilidade das sessões tmux. Nenhuma alteração de bot, serviço de trading, cutoff, modelo, dado de origem ou SQLite.
- 17/11 — Módulo Hermes Analyst (pedido do utilizador): tab V2 com botão manual e saída sanitizada; `POST /api/hermes/status` recolhe um allowlist dos snapshots/ledgers atuais (apenas métricas e estados, sem IDs de token, segredos ou ledgers crus), chama `hermes chat -q ... --oneshot --format stream-json --toolsets , --max-turns 1 --source tool`, interpreta o evento final e devolve texto/tokens/duração. A seleção vazia explícita de toolsets é resolvida pelo Hermes como sessão sem ferramentas; o prompt também limita a leitura ao JSON e proíbe aconselhamento de execução. Mutex impede concorrência e cooldown é 20s; timeout 100s; nenhuma invocação automática no refresh. Recarreguei apenas a dashboard. Validei AST/JS, `git diff --check`, rota recusando GET (405) e recurso estático (200). Não executei uma chamada real do modelo: isso é feito só ao carregar no botão e pode consumir tokens; a invocação do CLI dentro do sandbox Codex ainda não foi validada, pois o wrapper Hermes tentou escrever o lock de instalação fora da área gravável. A sessão interativa que o utilizador mostrou continua independente. Não alterei instalação/config Hermes, bots, serviços de trading, dados, SQLite, modelos ou ordens.
- 18/11 — Ajuste semântico solicitado no Command Center: P&L positivo PAPER passou de verde para âmbar nos KPIs consolidados e por bot, pois verde sugere lucro realizado. P&L negativo continua vermelho e zero neutro. Alteração só de apresentação em `v2_pro_desk.js`; `node --check` e `git diff --check` passaram.


## 18/11/2026 — posições recentes e estados visuais da Dashboard V2
- A antiga tab “Auditoria” foi convertida em “Posições recentes”: agrega as 30 posições mais recentes de A/B/C/D por hora de abertura, com filtros globais de bot/cidade. Mostra ganhos a verde, posições por resolver a âmbar e perdas a vermelho, além do P&L PAPER por linha; período continua a aplicar-se apenas à Performance.
- `/api/era` passa a expor até 50 posições recentes por bot (ledger da era), suficientes para compor o top 30 global sem consultar `/api/events`. A atualização periódica da dashboard já não requisita o endpoint de eventos de 30 dias.
- As tabelas de posições abertas mostram uma coluna explícita “A AGUARDAR” a âmbar; nos cartões, as cidades são identificadas como “CIDADES DO BOT” e têm chips mais legíveis.
- Alterações em `dashboard/server.py`, `dashboard/static/index_v2.html`, `dashboard/static/v2_pro_desk.js` e espelho `cassiopeia_terminal_v2/index.html`. Verificações: `node --check`, AST Python e `git diff --check` passaram. Apenas a dashboard será recarregada; sem alterações a bots, coletor, dados, SQLite, modelos ou ordens.

- 18/11/2026 — complemento pedido para “Posições & Ordens”: a página agora lista também as 30 posições fechadas mais recentes da era, com resultado GANHO verde / PERDA vermelho, bot, cidade, entrada, hora de fecho e P&L PAPER. Abertas continuam separadas e amarelas; inclui-se no espelho do terminal. Validação textual e `git diff --check` passaram; dashboard recarregada via sessão `tmux dashboard`.

- 18/11/2026 — replay de posições históricas: posições fechadas são clicáveis; a rota `/api/era` inclui `ts_open` no registo resolvido. O replay converte entrada/fecho para a hora local da cidade, abre na data da entrada, marca os horários nos gráficos e oferece salto para o dia do fecho. Na vista histórica removem-se os KPIs/mercado atuais da cidade para evitar misturar datas. Warsaw foi verificado: entrada 16/11 13:12 UTC (14:12 local), fecho 17/11 05:00 UTC (06:00 local); API de chart tem 171 e 301 pontos nos respetivos dias. `node --check`, AST e `git diff --check` passaram. Nenhuma alteração a dados, bots, coletor ou SQLite.

- 18/11/2026 — contexto no replay histórico: painel da posição agora separa temperatura, máxima acumulada, bracket alvo, estado bought do tick, ask do tick, preço registado no ledger e previsão WU. Se ledger/ask divergirem, a UI assinala que são registos distintos; não afirma fill. Warsaw analisado: às 14:12 local (16/11) temp/rmax=8°C, alvo 8°C, bought=true, WU 8,3°C; máxima atingiu 9°C às 14:35 e o cache de resolução e ledger oficial apontam 9°C/LOST. O replay inicial abre no dia da entrada; o salto para 17/11 mantém os dados de contexto da entrada e marca o fecho. Exatamente a razão/score do modelo no tick de compra não está guardada (`actions=[]`); ticks próximos anteriores mostram `p_rebound=0.20<0.2` formatado a duas casas. Registo ledger de entrada $0.75 versus ask do tick 0.49 no mesmo horário/token: discrepância não resolvida, independente da causa do settlement. `node --check`, AST, endpoints de replay dos dois dias e `git diff --check` passaram.

- 18/11/2026 — auditoria da divergência de entrada Warsaw (somente leitura): `trade_ledger.jsonl`, `paper_positions.json` e `orders_2026-11-16.json` concordam no mesmo order_id/token, preço registado 0,75, 2 shares, size $1,50 e status SIMULATED. O tick às 13:12:11Z (14:12 Warsaw) para o mesmo token/bracket 8°C grava ask 0,49/bid 0,30, depth e bought=true. Não há snapshot `book_snapshots` SQLite ±15min; `market_ladder.db` não tem linha Warsaw 16/11; logo não existe uma terceira amostra histórica para reconstruir o livro fresco usado pela compra. `buy_yes` PAPER responde success SIMULATED sem validar execução; os seus dois campos de preço são ask de entrada vs preço-limite FOK protegido, mas o log guardado mostra ambos 0,75. Pela fórmula FOK de código (`ceil(1,05×ask)` para `result.price`, `ceil(ask)` para `entry_ask`), esses dois campos não poderiam ambos resultar em 0,75 numa chamada FOK comum. `orders` não persiste `order_type` nem o ask bruto, portanto não se determina se a instância executou versão/caminho diferente, nem se o livro fresco divergiu do snapshot. O ficheiro legado `bets_warsaw_2026-11-16.json` ainda contém artefacto incompatível (MAKER-75c, $1,00, 1,3333 shares, P&L -$1,00, sem position_id/timestamp); não é reconciliável com o ledger e não é a fonte da Dashboard. Conclusão: simulação PAPER e telemetria não permitem provar preço/fill; não corrigir retroativamente. Nenhum processo, bot, dado ou SQLite alterado.

- 18/11/2026 — inventário de cidades e reconciliação PAPER pós-cutoff (somente leitura): a configuração servida pela Dashboard lista A=34 cidades (`cities_active.txt`), B=8, C=12 e D PAPER=5; `tmux ls` mostra sessões `bot`, `v6bot`, `c_bot`, `micro_paper`, além do collector e dashboard. O snapshot A guardado foi gerado 18/11 09:19 UTC e cobre 34 cidades. Não adicionar cidades até validar a qualidade das entradas. Desde 14/11, o ledger canónico A tem 5 fechadas (Buenos Aires, Shenzhen, Manila e Busan GANHO; Warsaw PERDA) e 3 abertas; P&L PAPER nominal agregado +$0,50, não evidência de execução/edge. B tem 1 aberta e nenhuma resolvida identificável; C não tem ledger de trades/eventos no caminho consultado; D tem 1 aberta.
  Nos cinco fechamentos A, o tick mais próximo da abertura ocorre a <1 s, usa o mesmo token e marca `bought=true`; temperatura/rmax e alvo foram: Buenos Aires 29/29→29°C; Shenzhen 27/27→27°C; Manila 32/33→33°C; Busan 18/18→18°C; Warsaw 8/8→8°C. Os asks top do `target_book` nesses ticks foram respetivamente 27,8¢, 45¢, 62¢, 70,2¢ e 49¢; o ledger regista 75¢ em todos. O livro observado não comprova fill, mas a divergência é sistemática o suficiente para impedir avaliação económica por cidade até reconciliar o quote fresco, runtime/código carregado e telemetria. Os ticks têm `actions=[]`; `p_ensemble` não substitui o p_rebound usado pelo gate. Os JSON `bets_{cidade}_{dia}.json` legados mostram `MAKER-75c` e não são reconciliáveis com os order IDs do ledger. Abiertas 18/11: Kuala Lumpur 33°C/ask tick 60¢; Chongqing 17°C/64,5¢; Manila 33°C/55,5¢ sem book guardado; Beijing B 7°C/75¢; Beijing D 6°C/72¢. Estes valores são observações tick, não prova de execução.
  Próximo passo: auditar o caminho de execução PAPER e tornar observável, por posição, o ask fresco, token, bid/ask/depth, preço simulado, versão/runtime e motivo/score do gate; depois refazer a comparação por cidade com regras de inclusão explícitas. Sem alterações a bots, serviços, modelos, parâmetros, SQLite, ordens ou dados de origem.

- 18/11/2026 — correção da interpretação dos fills A: o launch script `start_paper.sh` ativa `venv` e arranca A com `V6_MAKER=1`; o código `v6_maker.py` coloca bid shadow fixa a 0,75 quando o ask de sinal está acima de 0,76 e, num tick posterior, marca fill quando `latest_ask <= 0,75`. As cinco posições A fechadas pós-cutoff estão confirmadas em `live_bot_logs/maker_filled.json`: placement/ask de sinal→fill: Buenos Aires 94,9¢→75¢ (1,39 min), Shenzhen 92¢→75¢ (25,81 min), Manila 93,6¢→75¢ (14,68 min), Busan 93,1¢→75¢ (8,63 min), Warsaw 92¢→75¢ (39,77 min). Quatro GANHO e Warsaw PERDA. Assim, o 75¢ do ledger é o limite da ordem shadow, não o ask observado no tick de fill; a diferença é esperada e não prova corrupção do ledger.
  A limitação permanece económica: a simulação não persiste evento/volume de transações nem fila, depth consumível ou confirmação de ordem real; `check_fills()` usa apenas o ask observado, declara fill integral ao limite e fee zero. Snapshot a ask abaixo de 75¢ mostra cruzamento observado, mas não comprova que uma ordem real passiva estaria na frente nem qual seria o fill. A contagem desde 14/11 em `maker_filled.json`: A 35 tentativas, 8 marcadas fill, 27 NO_FILL, mais 1 ordem pendente; B 5 tentativas, 1 fill (Beijing aberto), 4 NO_FILL. `filled_at` é a hora de processamento do tick, não timestamp independente de execução. D PAPER não tem V6_MAKER e o seu registro Beijing é direto: entry ask 72–73¢, ordem simulada protegida a 77¢.
  Conclusão/ordem de trabalho atualizada: não adicionar cidades nem concluir que a divergência de preço do tick invalida o ledger; auditar separadamente a validade do modelo de fill maker (tick interval, fila, profundidade, ordem passiva e seleção adversa) e mantê-lo distinto do taker D. Não há fills reais para usar como confirmação. Sem alterações a bots, configs, serviços ou dados.

- 18/11/2026 09:52–09:53 UTC — por autorização explícita, removido o shadow maker dos launchers PAPER A/B: `start_paper.sh` e `start_paper_v6.sh` já não definem `V6_MAKER`, preço ou TTL; os comandos das sessões limpam esses nomes do ambiente depois de carregar `.env`. Reiniciadas apenas sessões `bot` (A, 09:52) e `v6bot` (B, 09:53), em PAPER. `tmux ls` confirma também C, D PAPER, collector e dashboard mantidos; logs de A/B mostram inicialização CLOB PAPER. `bash -n` e `git diff --check` passaram. C/D, `pm_books`, dashboard, D REAL, parâmetros, models, SQLite e dados de origem não foram alterados. Os registos históricos `maker_filled.json` e o estado shadow pendente foram preservados; sem `V6_MAKER`, A/B não colocam nem processam novos fills shadow. A única entrada em `live_bot_logs/maker_pending.json` (Lucknow, expires 10:02 UTC) é virtual e inerte após o restart; B tinha apenas uma entrada antiga (Amsterdam, outubro). Nenhuma ordem REAL criada.
  Após o pedido explícito de TAKER-only em todos os bots, o launcher dormente `start_micro.sh` também foi alterado para limpar `D4_MAKER` e `V6_MAKER` depois de carregar os ficheiros de ambiente. D REAL continua suspenso; esta alteração não iniciou nem reiniciou essa sessão. Agora nenhum launcher de bot ativo define `V6_MAKER=1` ou `D4_MAKER=1`.

- 18/11/2026 10:36 Europe/Lisbon — piloto Athena E e integração na dashboard, por autorização explícita: criado launcher manual `start_athena_real.sh` (não integrado no autostart), Munich apenas, Cassiopeia/rebound + gate F1 ≥0,85, ask 0,60–0,90 e ordem TAKER FOK. Limites REAL do processo: máximo $2 por ordem após arredondamento para shares inteiras e proteção FOK; $2 de exposição aberta; $4 de perda acumulada projetada incluindo taxas. O launcher verifica presença/formato das credenciais sem as imprimir, `f1_report.json` de Munich com `gate_pass=true` e recusa sessão duplicada; limpa variáveis MAKER e não toca no Micro D REAL legado, que permanece suspenso.
  `/api/overview` antes do arranque confirmou A/B/C/D PAPER ativos (34/8/12/5 cidades), collector e dashboard, sem Athena. Iniciada apenas a nova sessão `athena_real`; reiniciada apenas a dashboard para carregar o backend atualizado. `/api/overview` depois confirmou A/B/C/D `mode=paper, alive=true` e E/Athena `mode=real, alive=true`, Munich (1 cidade). `/api/era` mantém `combined` PAPER (n=5, W=4, L=1, P&L nominal +$0,50) separado de E REAL (n=0, abertas=0, P&L=0); o primeiro tick não colocou ordem e não há posição Athena. O snapshot/log observado mostrava Munich à espera, ask 83¢. Collector e sessões PAPER não foram reiniciados.
  Alterações de integração: `dashboard/server.py` regista E em separado e não agrega o P&L REAL ao combinado PAPER; dashboard mostra o modo/cidade de Athena e informa que B é TAKER com shadow maker desativado; `v2_pro_desk.js` reconhece E nos filtros e discrimina modo nas posições recentes; `index_v2.html` e o espelho `cassiopeia_terminal_v2/index.html` estão sincronizados. Launchers ativos A/B/C/D limpam variáveis MAKER; C/D/E também. A interface pode continuar a mostrar registos maker históricos como histórico, sem execução atual.
  Verificações: `bash -n` nos launchers A/B/C/D/E, `node --check` no módulo V2 e no JS inline, AST dos módulos Python e `git diff --check` passaram. A API runtime confirmou os cinco processos e separação PAPER/REAL. Sem testes de trading, downloads, escrita SQLite, alterações de cutoff/modelo ou ordens manuais. Nota pendente: `polymarket_clob.py` ainda usa `py_clob_client_v2`; a migração solicitada anteriormente para o SDK unificado não foi feita neste passo e deve ser planeada separadamente, sem confundir o lançamento atual com essa migração.

- 18/11/2026 10:55 Europe/Lisbon — Athena E ampliada por pedido explícito para `munich,lucknow,seoul`, nominal `PARCEL_SIZE=$1` por trade. Escolha de Seoul: `f1_report.json` tem `gate_pass=true`, `B_useful=6`, teste 2024-01-01–2026 com n=5.579; acresce diversificação horária face a Munich/Lucknow. Isto é critério de elegibilidade/modelo, não prova de EV económico. Lucknow foi incluída como pedido, embora o respetivo relatório tenha `gate_pass=false` (B_useful=4, n_test=5.142); o gate runtime p_win≥0,85 continua ligado. A limitação é explicitada no launcher e na Dashboard.
  Como o CLOB obriga shares inteiras e notional mínimo de $1, um trade nominal de $1 pode ser aumentado pelo sizing; teto defensivo é $2 por ordem. Limites Athena alterados para $20 de exposição aberta total e $20 de perdas acumuladas projetadas. Havia 0 posições E antes do restart. Reiniciada apenas a sessão Athena com as três cidades; reiniciada apenas a dashboard. `/api/overview` às 10:56 confirma A/B/C/D PAPER ativos (34/8/12/5 cidades) e E REAL ativo com as três cidades; `/api/era` confirma E com 0 abertas/0 resolvidas, e agregado PAPER continua separado (n=5, W=4, L=1, P&L nominal +$0,50). Nenhuma ordem manual enviada. `bash -n`, AST Python, `node --check`, JS inline e `git diff --check` passaram. O Micro D REAL legado permanece suspenso; sem alterações à SQLite/dados/modelos.

## 18/11/2026 — migração para SDK Polymarket unificado e reconciliação
- Corrigida a nota anterior: a migração estava pendente às 10:55. O adaptador principal e os utilitários read-only de conta agora usam `polymarket-client==0.18.0`; o SDK antigo foi removido do `./venv`. Compatibilidade testada no venv partilhado com `web3==7.16.0` e `eth-abi==5.2.0` (`pip check`: sem conflitos). `requirements.txt` fixa o SDK e limita Web3 a `<8`.
- A compra REAL assina e submete explicitamente apenas FOK; venda REAL também é FOK, com limite inferior de 5% face ao bid observado. Não se usa o helper do SDK que pode recuperar allowance automaticamente. `place_maker_buy` está bloqueado e as ramificações maker/shadow do live bot têm guarda `TAKER_ONLY`. A/B/C/D não foram reiniciados; os launchers mantêm as variáveis maker limpas. A Athena foi parada com posição zero, validada com o novo SDK e relançada sozinha.
- Read-only autenticado do SDK: autenticação OK, sem ordens abertas; API/dashboard confirma A/B/C/D PAPER vivos e E/Athena REAL viva em Munich/Lucknow/Seoul, com E sem posições abertas. O teste de books com os tokens alvo do snapshot encontrou ask em Munich e nenhum ask em Lucknow/Seoul; são quotes observadas e não houve ordem submetida durante as verificações.
- O resultado de uma venda REAL passou a usar o preço efetivamente devolvido pelo fill, em vez do bid anterior. A resolução de posição REAL calcula P&L líquido de fees de entrada/saída e regista gross, fees e net no ledger. Settlements continuam a exigir `resolved` e `winner` da Gamma; sem winner, a posição mantém-se pendente.
- Criado `reports/ops/generate_ops_reports.py` e gerado o pacote atual com quatro documentos: estado/âmbito, contexto das decisões por cidade, posições/reconciliação/P&L, outcomes recentes. O estado atual mostra A=3, B=1 e D=1 posições PAPER de hoje ainda abertas; E=0. Isto não é falha de settlement antes do fecho do dia. Há, contudo, divergências históricas nos ledgers: A tem 24 `BET_CLOSE` repetidos e 3 `BET_OPEN` sem posição aberta nem fecho; B tem 3 posições sem evento de ledger, 7 `BET_OPEN` sem posição/fecho e um `BET_CLOSE` repetido. Não reparar automaticamente, pois os registos podem representar migração/legado e não provam fills. Os outcomes PAPER recentes também têm `win=null`; os reports não alegam baseline executável quando não há ligação entre fill, book e settlement.
- Verificações: `pip check`; import/versões do SDK; `py_compile` dos módulos alterados; quatro testes unitários isolados passaram, cobrindo FOK, bloqueio de GTC/maker e posição aberta após rejeição de venda. Nenhum teste submeteu ordens ou tocou em SQLite. A/B/C/D, coletor e dashboard não foram reiniciados.
- Continuação da manutenção autorizada: A/B/C/D PAPER e Athena foram parados graciosamente; collector e dashboard ficaram ativos. A auditoria por `position_id` mostrou que os `BET_CLOSE` repetidos A/B são históricos: há duplicados separados por segundos/minutos (p.ex. Munich 07/11, Karachi 09/11) e alguns pares de fallback histórico + confirmação Gamma em 11/11. A função atual de fecho já impede um segundo fecho para o mesmo objeto; a fragilidade restante estava no ledger, que deduplicava apenas dentro de ±2 segundos.
- `trade_ledger.append_event` agora trata `BET_OPEN` e `BET_CLOSE` como transições únicas por `position_id`, serializa escritores com lock de processo e `flock` no Linux, e deixa intactos todos os eventos antigos. Acrescentados testes para repetição após um dia e 12 chamadas concorrentes. Resultado combinado: 48 testes passaram, incluindo `test_regression.py`; `py_compile` passou. Nenhum ledger histórico foi reescrito. As posições PAPER ainda abertas de 18/11 foram preservadas nos seus ficheiros; E/Athena continua sem posição REAL. Próxima operação: relançar os cinco bots individualmente, sem interromper collector/dashboard, e verificar que os ficheiros pendentes foram restaurados.
- Correção operacional após a nota anterior: durante a suite inicial, a ordem de import dos testes gravou acidentalmente uma única linha sintética `test_contab` no ledger PAPER A. Foi parada apenas a sessão A, removida a linha pela combinação exata de tipo, posição, mercado, origem e timestamp (as restantes 190 linhas foram preservadas), e os testes foram isolados com `CASS_LOG_DIR` em `/tmp` antes da importação dos módulos. A suite repetida passou 48/48 e não voltou a tocar no ledger live. A sessão A foi relançada com o pipeline de log reconhecido pela dashboard. API read-only `/api/overview` confirmou A/B/C/D PAPER e E REAL vivos; cidades de E: Munich, Lucknow e Seoul. Coletor e dashboard mantiveram as sessões originais. Nenhuma ordem REAL foi submetida.
- 18/11/2026 14:07 UTC — smoke check e reconciliação após arranque: API local confirmou os cinco processos vivos; A/B/D restauraram as posições pendentes esperadas (A: Kuala Lumpur, Chongqing, Manila; B: Beijing; D: Beijing); C e E sem posição pendente. Logs recentes sem erros de SDK; os snapshots continuavam a atualizar. Relatórios 01–04 regenerados a partir de ficheiros existentes e API local, sem SQLite/downloads: 5 posições abertas, E=0; P&L de E não realizado/fechado $0.00 nos registos locais. Permanecem divergências históricas sem reparação: A 24 `BET_CLOSE` duplicados e 3 `BET_OPEN` sem posição/fecho; B 1 close duplicado, 7 opens sem posição/fecho e 3 posições sem evento. As transições recentes não mostram `BET_OPEN` duplicado. Estes totais históricos não foram reescritos.
- E/Athena, consulta read-only autenticada: saldo CLOB $19.43 e zero ordens abertas. O launcher define $1 nominal/trade (sujeito ao mínimo CLOB), teto de $2 por ordem, $20 de exposição aberta e perda acumulada máxima de $20; não houve submissão de ordem. Uma busca ampla de diagnóstico mostrou o URL WU; o dono confirmou que a chave é pública e partilhada para uso em frontend. Não é necessária rotação e nenhuma credencial foi alterada.
- Preparação do commit: alterações candidatas limitadas a adaptador SDK, guardas TAKER-only, utilitários read-only, ledger/deduplicação, `requirements.txt`, testes novos e este handover. Nenhum ficheiro foi staged/commitado nesta verificação; excluir `.venv`, snapshots, logs, históricos, dados e ficheiros operacionais já modificados.
- 18/11/2026 — Dashboard V3 iniciada como página estática isolada em `dashboard/static/index_v3.html`, com tema próprio (`v3.css`) e lógica (`v3.js`). Inspiração PancakeSwap recriada com tokens locais; sem CSS externo, dependências, alteração de API/backend, serviço, bots ou dados. A página reutiliza `/api/overview`, `/api/cities`, `/api/era`, `/api/equity` e `/api/positions`, e `/api/city_chart` no replay. Inclui resumo, cartões de bots/cobertura, curvas da era, posições abertas/fechadas, monitor de cidades e replay com ticks, temperatura, máxima, quotes, depth e contexto da entrada. A V2 foi preservada. `node --check dashboard/static/v3.js` passou; não foi possível fazer inspeção visual em browser neste ambiente.
- 18/11/2026 — Ajuste visual pedido para Dashboard V3: base branco quente, superfícies brancas e acentos pastel amarelo/rosa/menta/céu inspirados na variante clara do PancakeSwap; retirado o fundo escuro e reduzido o roxo a acento discreto de gráfico. Estados continuam semanticamente distintos: posição aberta/comprada âmbar, ganho verde, perda vermelho e saúde/info menta. CSS e SVG da V3 atualizados; V2, backend, rotas, bots, serviços, dados e SQLite intactos. Verificação sintática JS executada após a alteração.
- 18/11/2026 — Inventário de deployment PAPER para segunda máquina (32 GB), apenas leitura: A cobre 34 cidades; B 8; C 12; D PAPER 5; E/Athena REAL fica excluído. Gates F1 locais: Beijing/London `gate_pass=false` em B/D; C tem gate aprovado nas 12 cidades. Um clone Git limpo perde artefactos locais: 245 modelos `.pkl` em `cities/`, só 99 rastreados; peak necessários de Buenos Aires/Panama City/Toronto e rebound de Buenos Aires/Toronto não estão no Git; modelos F1 quase todos são ignorados. `.venv/` tem 9.820 caminhos rastreados e ocupa ~890 MB; `historic/` ~753 MB, necessário no bootstrap atual de `prev7`; `cities/` ~392 MB. O conjunto de dados PAPER ativo calculado tem 890,3 MiB sem compressão, antes do código. Três configurações city opcionais ausentes caem nos defaults em `cities/config.py`. Criado `PAPER_DEPLOYMENT_2026-11-18.md` com scopes, dependências e plano seletivo. Nenhum bot, launcher, modelo, configuração operacional, dado, SQLite ou serviço foi alterado; não foi feito commit nem bundle.
- 19/11/2026 — Preparação PAPER local para host novo: deployment overlay passa A/B/C/D às 34 cidades sem alterar launchers/processos PAPER atuais; 20 cidades têm `gate_pass=true` nos reports F1 e 14 ficam fail-closed em B/C/D. E/REAL excluído. O bundle all-34 final é `/tmp/cassiopeia-paper-20261119T001320Z.tar.gz` (174.243.179 bytes; SHA-256 `a4f8413fd70a9f71ffbd1365819dd44960ba57b1987852af00e361d8175dd2d9`), 340 entradas, 34 históricos e modelos peak/rebound/F1; manifesto contém tamanhos e hashes. Sem `.env`, chaves, SQLite, logs, `.venv` ou launchers REAL. Reserva pós-build: 8,78 GiB. Launcher isolado passou `bash -n`, mas não foi executado. Commits locais `9ba79fb` e `12fd1b6` contêm inventário/builder/launcher all-34. Nenhum push; aguarda-se o URL GitHub pretendido.
- 22/11/2026 — Auditoria de origem antes de commit: branch `pos-chatgpt-6` em `4226687`, sem upstream configurado; `origin` tem refs remotas de `master`, `DEPLOYMENT`, `JULY2017` e `JUNE2016`, sem `origin/HEAD` local. O working tree contém alterações vivas/geradas que ficam fora do commit: `.venv`, históricos METAR/WU, `data/`, SQLite, logs/snapshots/posições PAPER, calibrações, dashboard e deployment PAPER. Foi preparado commit local separado apenas para documentação, investigação experimental e ferramentas isoladas; nenhum bot, coletor, dashboard ou processo foi reiniciado e nenhum push foi feito.
