# CASSIOPEIA — PHASE G.1.B
# Production Compatibility Audit — SQLite V2

**Data da auditoria:** 2026-11-22, Europe/Lisbon  
**Escopo:** auditoria operacional e de código, somente leitura.  
**Fonte:** checkout /home/marco/POLY-MULTI-CITY-V2 e os três scripts Hermes indicados.

## 1. Executive summary

O consumidor que exige alteração para SQLite V2 é "polymarket_weather_archive.py". O módulo ainda inicializa a tabela física "price_points", cria o índice "idx_price_ts" sobre ela e, no modo de backfill, insere diretamente em "price_points". Com a V2, em que "price_points" passa a ser uma view de compatibilidade sobre "token_map" e "price_points_compact", estes comportamentos deixam de ser válidos.

"archive_orderbooks_live.py" é o escritor operacional relevante: abre a DB principal através de "arc.connect_db()" e grava "book_snapshots"; não escreve diretamente em "price_points", mas executa a inicialização que hoje contém o DDL incompatível. A variante "deployment/paper/pm_books_collector.py" tem o mesmo perfil e importa o mesmo módulo raiz.

"ask_collector.py" não usa SQLite: consulta Gamma/CLOB e acrescenta linhas a "ask_collector_data.csv". Não precisa de alteração para a view V2.

Os três scripts Hermes auditados são independentes do arquivo meteorológico: usam "data/soccer_draw_live.sqlite" e "data/football.sqlite". Não foi encontrada referência a "data/polymarket_weather_2026.sqlite".

No ambiente desta auditoria não foram observados processos de collectors/bots além da shell de auditoria. Isso não prova que estejam parados na máquina operacional: o acesso ao socket tmux, ao crontab do utilizador e ao bus systemd foi recusado.

## 2. Production dependency matrix

| Componente | SHA-256 / estado | DB ou saída | Papel | V2 |
|---|---|---|---|---|
| ask_collector.py | 5f1d105d61fede827f3ec92ced403e0b864b72a386f8d762a69bc0acc4318cb2 | ask_collector_data.csv | Gamma + CLOB BBO/depth, append CSV | Sem alteração |
| archive_orderbooks_live.py | c077c858d4ad7e8ce1c9d693c24115b42150f83b404c7c1c8eede4a39e25feaa | data/polymarket_weather_2026.sqlite | loop live, 34 cidades, hoje/amanhã, books | Requer módulo de arquivo V2-aware |
| polymarket_weather_archive.py | f3385e399839e75b66eb57a1d14fd74ab3ebf3d6ce1f48b1c6be20ef076d6f3d | DB acima, por defeito | schema, discovery, backfill, snapshots, stats | Alteração obrigatória |
| deployment/paper/pm_books_collector.py | variante do bundle; importa módulo raiz | DB do fleet.json, atualmente DB principal | launcher/loop PAPER de books | Mesmo requisito; fleet.json tem enabled=false |
| Hermes collect_live.py | 47816de7300c13016023e9f9a4076dd0429e356408ee931993310aef1fd0b59b | soccer_draw_live.sqlite, football.sqlite | books de soccer/contexto | Fora do escopo |
| Hermes context_loop.py | 8b873dd89aaff9ce86813f18360f240e374a210fbc27b880ed54875e1a7c172c | mesmas DBs Hermes | ESPN/contexto | Fora do escopo |
| Hermes pipeline_loop.py | 17ab7725543f19f8777924ec90cc7008f5ea2d086e83a14898a2a6f2271793f4 | mesma DB soccer e outputs data/ | audit/features/labels | Fora do escopo |

## 3. Exact database consumers

### ask_collector.py

Import local: cities.config.get_city. Imports runtime: curl_cffi.requests com fallback para requests; restante standard library.

Não chama sqlite3, não abre DB, não executa SQL, não inicializa schema e não configura journal mode. A única escrita é open(CSV_PATH, "a") em ask_collector_data.csv. Não há referência a price_points, índices ou à DB principal.

### archive_orderbooks_live.py

Imports locais: polymarket_weather_archive as arc; restantes standard library.

- DB: data/polymarket_weather_2026.sqlite.
- Lock: data/orderbooks_live.lock.
- Intervalo: 300 s; 34 cidades de cities_active.txt; dois dias locais por cidade.
- Abre db = arc.connect_db(DB), depois define sqlite3.Row.
- Lê COUNT(*) de book_snapshots e pesquisa events por city/market_date/status.
- Delega a escrita para arc.snapshot_books(...), que grava book_snapshots com INSERT OR REPLACE e, se necessário, events, markets e tokens através de save_event.
- Não contém INSERT/UPDATE/DELETE em price_points nem cria índices nessa tabela.
- Ainda assim chama connect_db() sempre; portanto herda o DDL incompatível de price_points, idx_price_ts e price_by_city.
- O processo usa o WAL via o módulo importado; connect_db() executa PRAGMA journal_mode=WAL.
- Não tem retry transacional próprio; usa os context managers do módulo e captura erros por ciclo.

### polymarket_weather_archive.py

Imports locais: cities.config.CITIES/get_city sob demanda. Dependência externa direta: requests. Restante standard library.

connect_db() abre em modo normal, timeout=30, executa PRAGMA journal_mode=WAL e PRAGMA foreign_keys=ON, cria events, markets, tokens, price_points, history_chunks e book_snapshots, cria idx_markets_city_day, idx_tokens_market e idx_price_ts, cria price_by_city e faz commit.

No backfill, process_one grava price_points diretamente com executemany INSERT ... ON CONFLICT ... DO UPDATE e grava history_chunks na mesma transação. snapshot_books grava book_snapshots. Discovery grava events, markets e tokens. stats consulta COUNT(*) em price_points; esse acesso pode continuar se a view V2 preservar as colunas, mas não autoriza escrita.

## 4. SQLite V2 compatibility findings

A DB foi aberta apenas com URI mode=ro e PRAGMA query_only=ON. O schema observado ainda é V1:

- price_points é tabela física com PK (token_id, ts, fidelity_minutes);
- existem idx_price_ts, idx_tokens_market e idx_markets_city_day;
- existe price_by_city sobre a tabela física;
- não foram observadas token_map nem price_points_compact;
- PRAGMA journal_mode devolveu wal;
- user_version=0;
- DB ~25 GiB, WAL ~4,3 MiB, SHM ~32 KiB; df mostrou 44 GiB livres.

Incompatibilidades exatas:

1. CREATE TABLE IF NOT EXISTS price_points não pode permanecer quando o nome for ocupado por view.
2. CREATE INDEX IF NOT EXISTS idx_price_ts ON price_points(ts) não pode permanecer: SQLite não indexa views.
3. O INSERT do backfill não pode escrever na view; deve ser roteado para token_map/price_points_compact pelo adapter OLIMPO.
4. price_by_city deve manter interface compatível e ser criada/reconciliada sem DDL incompatível.
5. events, markets, tokens, history_chunks e book_snapshots continuam físicos e fora da substituição proposta.
6. A inicialização não deve mudar journal mode durante o arranque do writer sem migração coordenada.

## 5. Minimum required source changes

O mínimo é alterar apenas polymarket_weather_archive.py para:

1. delegar inicialização e escritas de preços no adapter V2/OLIMPO;
2. remover/condicionar o DDL físico de price_points e idx_price_ts;
3. manter a API de connect_db, save_event, snapshot_books, stats e process_one, permitindo que os dois caminhos pm_books continuem sem alterações;
4. rotear o backfill para o caminho compacto/token map com a atomicidade e retries do adapter;
5. preservar pelo menos token_id, ts, fidelity_minutes, price e source na view de compatibilidade;
6. atualizar a cópia empacotada apenas se houver bundle separado; build_bundle.py inclui o módulo raiz e pm_books_collector.py importa esse módulo pela raiz do bundle.

Não há evidência de necessidade de alterar ask_collector.py, archive_orderbooks_live.py, Hermes, bots ou tabelas restantes, desde que o adapter preserve a API. Uma mudança de assinatura exigiria alterações nos dois launchers pm_books.

## 6. Components requiring a pause during migration

Pausa coordenada necessária para:

- archive_orderbooks_live.py / sessão operacional pm_books, se ativa;
- deployment/paper/pm_books_collector.py / sessão paper_deploy_pm_books, se ativa;
- qualquer backfill/discovery/snapshot que use polymarket_weather_archive.py em escrita;
- qualquer processo que importe connect_db() na versão V1.

A pausa deve abranger a troca do módulo e a verificação de schema; não é seguro trocar o ficheiro enquanto um writer antigo mantém conexão aberta.

## 7. Components that can remain operational

- ask_collector.py, por gravar apenas CSV;
- os três scripts Hermes, por usarem DBs de soccer independentes;
- leitores que usam somente SQL compatível com a view, depois de confirmar a definição V2;
- bots PAPER e o bot REAL suspenso, somente se a confirmação operacional mostrar que não abrem a DB meteorológica nem dependem do writer. Não se inferem posições ou ordens pela ausência de processos;
- dashboard/replay somente leitura, se estiverem ligados a mode=ro.

## 8. Target runtime details

Os launchers apontam para /home/marco/POLY-MULTI-CITY-V2/venv/bin/python, ou para python depois de source venv/bin/activate. Resolve para /usr/bin/python3.12.

Verificado no venv do checkout:

- Python 3.12.3;
- SQLite runtime 3.45.1;
- sqlite3 Python binding 2.6.0;
- requests 2.34.2;
- curl_cffi instalado;
- cities.config e polymarket_weather_archive importáveis.

O ambiente Hermes separado também usa Python 3.12.3/SQLite 3.45.1, mas requests 2.32.3; não é o runtime dos collectors meteorológicos.

Não foram instalados pacotes nem alterados ambientes. A validação do adapter deve usar o venv do checkout num workspace descartável.

## 9. Automatic restart risks

Confirmado pelo código:

- bots_alive_guard.py verifica bot, collector, v6bot, c_bot e micro_paper; em caso de problema executa ./venv/bin/python start_all_bots.py.
- start_all_bots.py pode relançar ask_collector.py na sessão collector e os PAPER; não relança archive_orderbooks_live.py/pm_books.
- start_paper.sh mata/recria collector e contém pkill -f "ask_collector".
- ask_collector_daemon.sh relança ask_collector.py 60 s após saída.
- deployment/paper/start_collectors.sh só lança collectors enabled no fleet.json; ask_csv e pm_books estavam enabled=false.
- deployment/paper/start_all_paper.sh lança A-D PAPER e não lança pm_books nem E/REAL.

Não confirmado operacionalmente:

STATUS_ATUAL.md documenta historicamente */5 bots_alive_guard e @reboot start_all_bots.py, mas o crontab atual não pôde ser lido. O socket tmux e o bus systemd também recusaram acesso. Cron/systemd ativos, sessões atuais e wrappers externos permanecem blockers, não factos negativos.

forecast_benchmark/crontab_backup_20261114.txt é backup histórico, não configuração atual. Não foram encontrados ficheiros service/timer relevantes no checkout.

## 10. Safety assessment

- PAPER: não foi possível confirmar sessões A/B/C na máquina operacional devido à restrição tmux; documentação histórica não substitui estado atual.
- REAL: start_all_bots.py e o bundle PAPER não lançam REAL; start_athena_real.sh é manual no repositório. Isto não demonstra ausência de processos REAL, posições ou ordens pendentes.
- Archive writer: archive_orderbooks_live.py é o caminho de maior risco; lock e WAL/SHM mostram uso anterior/em curso da DB, mas não provam PID ativo.
- Readers: inventário integral não foi possível por restrição de processos/sockets.
- Não foram lidos .env, chaves, contas ou APIs de trading.

## 11. Remaining blockers

1. Confirmar sessões tmux reais e PID/command line de pm_books, A/B/C/D e qualquer REAL.
2. Obter crontab atual e systemd user/timers para confirmar relaunches durante a janela.
3. Confirmar se pm_books ativo é o root archive_orderbooks_live.py ou deployment/paper/pm_books_collector.py.
4. Confirmar o contrato exato do adapter OLIMPO: API, token map, price_points_compact e views.
5. Validar num workspace descartável com /home/marco/POLY-MULTI-CITY-V2/venv/bin/python.
6. A DB observada ainda é V1 (user_version=0, tabela física price_points); a transição efetiva não começou neste audit.

## 12. Recommended next action

Preparar patch isolado apenas para polymarket_weather_archive.py, preservando a API pública usada pelos dois caminhos pm_books, e validá-lo no workspace descartável com fixtures V1/V2. Antes do rollout, obter janela coordenada que pause todos os writers e confirmar por PID/tmux/cron que nenhum mecanismo os relança. ask_collector.py, Hermes e bots não devem entrar no patch sem nova evidência.

## Audit restrictions and non-actions

Foram feitas apenas leituras de código, hashes, metadados, processos/configuração acessível e schema SQLite em mode=ro/query_only=ON. Não foram parados, reiniciados ou lançados processos; não foram alterados scripts existentes, Hermes, bases, journal modes, credenciais, ordens ou APIs; não foram instalados pacotes, criados snapshots, feitos backfills, benchmarks ou cópias; não foram feitos git add, commit ou push. A única criação deste trabalho é este relatório.
