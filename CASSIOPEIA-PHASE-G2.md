# CASSIOPEIA — PHASE G.2

**Data da validação:** 2026-11-22, Europe/Lisbon  
**Escopo:** validação isolada de compatibilidade SQLite V1/V2; sem produção, APIs externas ou loops live.  
**Workspace:** `/tmp/cassiopeia-phase-g2.ACMYb8`

## Resultado executivo

**GO para planeamento da Phase H; NO-GO para deployment/cutover de produção.**

O adapter OLIMPO e o archive candidate passaram a suite isolada de **23/23 testes** no runtime exigido: Python **3.12.3**, binding sqlite3 **2.6.0**, SQLite **3.45.1**. Foram cobertos V1, V2, compact price writes, token mapping, atomicidade, rollback, `SQLITE_BUSY`, `SQLITE_BUSY_SNAPSHOT`, retenção de `source`, journal modes e integridade/FK.

O smoke offline do `archive_orderbooks_live.py` completou um único ciclo injectado em fixtures V1 e V2, com API falsa e sem chamadas de rede. Em ambos os casos gravou 2 eventos, 2 mercados, 4 tokens e 4 snapshots de livro; `integrity_check=ok`, `foreign_key_check=[]`, e preservou `DELETE`. Em V1 `price_points` permaneceu tabela; em V2 foi reconhecida como view.

Isto não autoriza alteração da DB, do collector, de bots ou de serviços. O caminho de produção continua **não liberado** até confirmação do source realmente implantado, dependências dos três processos Hermes e procedimento coordenado de cutover/rollback.

## Fontes e hashes

Os cinco primeiros hashes foram obtidos remotamente em OLIMPO antes da cópia e confirmados após a transferência.

| Ficheiro | Origem | SHA-256 |
|---|---|---|
| `weather_sqlite_adapter.py` | OLIMPO candidate | `9b5f3d41c05af7a1168d0631076a92d4a00ec1215f873bfb18d4393e8f724314` |
| `tests/test_weather_sqlite_adapter.py` | OLIMPO approved tests | `2fd413fe240a97015c735e42fc2ffb2a761412cd0dc76c74d543c84ebddc534c` |
| `polymarket_weather_archive.py` | OLIMPO candidate | `b908709a2e690889521983bca430b00f71e001fa66cbcb0917ccd0dbe49da225` |
| `deployment/paper/pm_books_collector.py` | OLIMPO reviewed wrapper | `a4b6b63e94bebce0ec23f9095bc69f4d09b7bf5cb67a44714e8021e35218f3aa` |
| `tests/test_paper_bundle.py` | OLIMPO approved test | `c8c5b309933378d16f56c5543af052bd6eccaf735cf4ed01d23ea4f9f1fb7313` |
| `archive_orderbooks_live.py` | CASSIOPEIA G.1.B local source | `c077c858d4ad7e8ce1c9d693c24115b42150f83b404c7c1c8eede4a39e25feaa` |
| `rotate_v6log.sh` | CASSIOPEIA G.1.B local source | `607fa7e364b868a9d0c7314e14be264f41f2369e82c40591d4b35c15395318f5` |

Nota: o hash do `archive_orderbooks_live.py` acima é o hash G.1.B confirmado no checkout local; a string foi mantida conforme o registo de G.1.B.

## Runtime

- Interpreter: `/home/marco/POLY-MULTI-CITY-V2/venv/bin/python`
- Python: `3.12.3`
- SQLite runtime: `3.45.1`
- Python sqlite3 binding: `2.6.0`
- Não foram instaladas dependências.
- O workspace foi criado fora do repositório e da DB de produção: `/tmp/cassiopeia-phase-g2.ACMYb8`.

## Suite V1/V2

Comando:

`python -m unittest discover -s tests -p 'test_weather_sqlite_adapter.py' -v`

Resultado: **23 tests, 23 OK, 0 failures, 0 errors**, duração observada 1,115 s.

Cobertura confirmada:

- inicialização/detecção V1 e reconhecimento V2;
- inserção/actualização compacta e views de leitura;
- mapeamento/reutilização de token IDs;
- transacções atómicas, nested transaction e rollback;
- falha tardia de history chunk sem persistir preço/mapping parcial;
- retries de writer contention em DELETE/WAL;
- `SQLITE_BUSY` e `SQLITE_BUSY_SNAPSHOT`;
- retry exhaustion, commit incerto e não-replay;
- retenção do `source` histórico em updates;
- preservação de journal mode;
- foreign keys, chaves/índices e integridade estrutural.

A execução da suite agregada que também descobria `test_paper_bundle.py` não foi considerada parte da suite adapter: esse teste requer `deployment/paper/build_bundle.py`, que não foi transferido por não ser necessário para G.2 e não estava no conjunto mínimo do smoke. O teste adapter isolado passou completamente.

## Smoke offline do collector

O source local auditado foi importado sem executar `main()` automaticamente. Para o smoke:

- fixtures novas V1/V2, pequenas e descartáveis;
- journal inicial `DELETE`;
- `Client` substituído por API falsa;
- `snapshot_books` real do archive candidate;
- `enforce_storage_budget` neutralizado apenas no fixture;
- cidades reduzidas a `lisbon`;
- um ciclo executado e o sleep substituído por `KeyboardInterrupt`;
- nenhuma chamada HTTP, Gamma, CLOB ou API externa;
- nenhum processo collector/tmux lançado.

Resultados:

| Fixture | `price_points` | Eventos | Mercados | Tokens | Books | Journal | Integrity | FK |
|---|---:|---:|---:|---:|---:|---|---|---|
| V1 | table | 2 | 2 | 4 | 4 | DELETE | ok | 0 |
| V2 | view | 2 | 2 | 4 | 4 | DELETE | ok | 0 |

A API pública usada pelo collector permanece disponível: `connect_db`, `Client`, `city_timezone`, `enforce_storage_budget` e `snapshot_books`. A comparação AST entre o archive V1 local e o candidate encontrou **zero símbolos públicos removidos**; o candidate apenas acrescenta `initialize_v1`.

## Journal mode

- V1 novo: WAL por defeito do archive candidate.
- V2 novo/aberto com mode explícito: mode solicitado é aplicado e reconhecido.
- Fixtures do smoke: DELETE permaneceu DELETE em V1 e V2.
- O adapter não força WAL nos caminhos de escrita; a abertura existente preserva o mode reportado, sujeito às regras normais do SQLite.
- A validação foi feita apenas em DBs descartáveis. A DB `data/polymarket_weather_2026.sqlite` nunca foi aberta.

## `rotate_v6log.sh`

Inspeção read-only concluída. O script:

- verifica ficheiros de log;
- se ultrapassarem 100 MB, faz gzip para um novo ficheiro e trunca o log original;
- não contém `python`, `exec`, `tmux`, `systemctl`, `pkill`, `kill`, `nohup`, start, stop ou restart;
- portanto **não lança nem termina processos**.

Apesar disso, pode alterar logs quando executado; não foi executado nesta validação.

## Estado operacional e blockers

Nenhum processo foi parado, reiniciado ou lançado. Nenhuma DB de produção foi aberta. Não foram alterados OLIMPO, cron, systemd, tmux, Hermes, bots, credenciais ou ordens.

Blockers restantes antes de qualquer Phase H deployment:

1. confirmar source/module path efetivamente usado pelo `pm_books` activo e pelos três processos Hermes;
2. confirmar que o artefacto final inclui o adapter e não permite import externo/legacy;
3. validar a matriz de leitores que tratam `price_points` como view read-only;
4. preparar cutover coordenado, rollback e tratamento de readers/conexões longas;
5. repetir smoke com o artefacto de deployment final, sem tocar em produção;
6. obter aprovação explícita antes de qualquer escrita em collector, bots, dashboard ou archive.

## Recomendação

**GO para Phase H planning only. NO-GO para produção.**

A compatibilidade do adapter no runtime CASSIOPEIA está demonstrada em fixtures. A compatibilidade operacional end-to-end e a segurança do cutover ainda não estão demonstradas.


