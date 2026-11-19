# PAPER deployment package — 18/11/2026

## Objetivo e fronteira

Preparar uma cópia reproduzível para uma segunda máquina de 32 GB, exclusivamente para os bots PAPER. O bot REAL Athena E, as suas credenciais e o seu launcher ficam na máquina atual. O overlay de deployment usa as 34 cidades em A/B/C/D sem alterar launchers nem processos ativos na máquina de origem.

## Universo PAPER encontrado nos launchers

| Bot | Scope atual na origem | Scope do bundle novo | Notas de cobertura |
|---|---:|---|
| A — Cassiopeia | 34 | 34 | Já cobre o universo completo. |
| B — Andromeda | 8 | 34 | F1 aprovado em 20/34; falha fechada em Amsterdam, Beijing, Busan, Cape Town, Jeddah, Karachi, Kuala Lumpur, London, Lucknow, Milan, Qingdao, Tel Aviv, Warsaw e Wellington. |
| C — Andromeda C | 12 | 34 | Mesmo gate F1; as 14 cidades sem promoção falham fechadas. |
| D — Micro PAPER | 5 | 34 | Mesmo gate F1; as 14 cidades sem promoção falham fechadas. |
| E — Athena REAL | 3 | Excluído | Permanece na máquina atual, sem alteração. |

O utilizador pediu todas as variantes PAPER nas 34 cidades no host novo. Esta ampliação existe apenas no launcher isolado do bundle; não reescreve os launchers nem os processos da máquina atual. As 14 cidades sem aprovação F1 permanecem fail-closed em B/C/D.

## Componentes que o bundle PAPER tem de conter

1. Código runtime: `cassiopeia_live_bot.py`, `cassiopeia_entry.py`, `cassiopeia_predictor.py`, `predictor.py`, `cassiopeia_params.py`, `cassiopeia_strategy.py`, `modules/`, `cities/config.py`, `cities/__init__.py`, `polymarket_clob.py`, `resolution_rules.py`, `weather.py`, `weather_v3.py`, `v6_filter.py`, `trade_ledger.py`, `tick_logger.py`, `opportunity_logger.py`, `tg.py` e os módulos importados por estes.
2. Launchers apenas PAPER: `start_paper.sh`, `start_paper_v6.sh`, `start_andromeda_c.sh`, `start_micro_paper.sh` e `wu_key_guard.py`. Não incluir nem invocar `start_micro.sh` ou `start_athena_real.sh`.
3. Configuração versionável sem segredos: `cities_active.txt`, `cassiopeia_active_config.json`, `cities/<cidade>/strategy_config_<cidade>.json`, configurações dos modelos e relatórios F1 usados pelos gates.
4. Modelos binários necessários às 34 cidades: peak e rebound para A-D; F1 quantiles/classifier e relatório para cada cidade em B/C/D. Fixar hash SHA-256 por artefacto no manifesto final e conferir versão de scikit-learn/LightGBM antes de arrancar.
5. Histórico meteorológico `historic/<cidade>.csv` das 34 cidades: `CassiopeiaEntry` chama `cassiopeia_backtester.load_csv()` no bootstrap de `history_max`/`prev7`. O bundle pode conter só estes CSV, não todo o arquivo de pesquisa. `historic_metar/`, SQLite, books e históricos de mercado não são dependências identificadas do arranque PAPER.
6. `requirements.txt`, instruções de instalação e um template de ambiente sem valores secretos. Instalar um venv novo na máquina de destino; nunca copiar `.venv`.

## Achados que impedem um clone Git limpo hoje

- A `.gitignore` exclui `*.pkl`, mas há artefactos locais necessários não rastreados. Na comparação do filesystem com `git ls-files`, os modelos peak de Buenos Aires, Panama City e Toronto, e rebound de Buenos Aires e Toronto existem localmente, mas não estão no Git. Os modelos F1 quantiles/classifier necessários para quase todos os universos B/C/D também estão ignorados/não rastreados.
- Há 245 `.pkl` sob `cities/`; apenas 99 aparecem rastreados pelo Git. O diretório `cities/` ocupa cerca de 392 MB. Um clone não terá o conjunto local de modelos sem um bundle explícito.
- O conjunto all-34 final — modelos peak/rebound/F1, relatórios/configuração e os 34 CSV usados por `prev7` — tem cerca de 1,0 GiB sem compressão, ainda sem contar código/runtime; o arquivo gzip ficou em 174.243.179 bytes. Faltam três `strategy_config` opcionais (Buenos Aires, Panama City e Toronto); `cities/config.py` usa defaults, e o bundle regista esse fallback sem criar configuração ou alterar parâmetros.
- `.venv/` está no índice Git (9.820 caminhos) apesar de estar no `.gitignore`; a cópia local ocupa cerca de 890 MB e está massivamente modificada/apagada. Um commit geral ou clone do estado atual não é um deployment reproduzível.
- Os CSV `historic/` ocupam aproximadamente 753 MB. Preservar apenas as 34 cidades ativas no pacote; não adicionar os outros conjuntos históricos.
- O workspace tem alterações operacionais/de dados preexistentes. Não usar `git add -A`, não limpar/restaurar o workspace e não incluir logs, posições, `.env*`, `.venv`, SQLite ou credenciais.

## Plano de empacotamento seguro

1. Criar uma lista permitida de ficheiros runtime e um manifesto por bot/cidade; validar imports e existência dos modelos/históricos sem iniciar bots.
2. Montar uma pasta de staging limpa fora dos diretórios live; copiar os artefactos necessários sem modificar os originais; gravar hashes e versões.
3. Produzir um commit de deployment seletivo, sem staging global. Excluir `.venv` do tree de deployment e manter credenciais/estado PAPER fora do Git.
4. Na máquina de destino, reconstruir o ambiente, fazer smoke check em PAPER sem chaves REAL e observar um ciclo completo antes de considerar migrar os processos.

## Estado atualizado em 19/11/2026

O bundle final é `/tmp/cassiopeia-paper-20261119T001320Z.tar.gz` (174.243.179 bytes; SHA-256 `a4f8413fd70a9f71ffbd1365819dd44960ba57b1987852af00e361d8175dd2d9`) com checksum ao lado. Contém 340 entradas (339 ficheiros + manifesto), 34 CSV históricos, modelos peak/rebound/F1 das 34 cidades e scopes A/B/C/D todas com 34. A inspeção do arquivo excluiu `.env`, chaves, SQLite, logs, `.venv` e launchers REAL. O arquivo inicial `...000456Z.tar.gz` é obsoleto e não deve ser instalado. Após gerar o final, restaram 8,78 GiB livres (reserva mínima: 8 GiB).

O bundle inclui `deployment/paper/start_all_paper.sh`, que usa sessões `paper_deploy_*`, recusa duplicados, não mata sessões e não inicia o coletor legado. O launcher passou `bash -n` e não foi executado. Commits locais `9ba79fb` e `12fd1b6` contêm inventário, builder e launcher all-34. Nenhum push foi feito. Nenhum bot, serviço, modelo original, histórico original, configuração operacional ou SQLite foi alterado; não foram transferidas posições PAPER nem credenciais. Quatro variantes × 34 cidades aumentam polling; monitorizar rate limits e RSS antes de deixar correr continuamente. Aguarda-se o destino GitHub pretendido antes de publicar.
