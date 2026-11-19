# Cassiopeia PAPER deployment

Este pacote descreve a frota de cinco bots e dois collectors num único ficheiro editável: `deployment/paper/fleet.json`.

| ID | Bot | Host indicado | Estado no pacote |
|---|---|---|---|
| A | Cassiopeia A | máquina PAPER de 32 GB | PAPER, lançável |
| B | Andromeda B | máquina PAPER de 32 GB | PAPER, lançável |
| C | Andromeda C | máquina PAPER de 32 GB | PAPER, lançável |
| D | Micro D | máquina PAPER de 32 GB | PAPER, lançável |
| E | Athena E | host atual | REAL, registado apenas; desativado e não lançável |

O launcher só aceita A-D em modo PAPER. Falha fechado se E for ativado ou se um dos ficheiros de modelo/histórico pedidos pela lista de cidades estiver em falta. Não contém credenciais nem launcher REAL.

## Cidades e configuração da frota

`fleet.json` tem `city_sets.all_cities`. A-D, `ask_csv` e `pm_books` referenciam esse conjunto. Para adicionar/remover uma cidade:

1. Edita a lista `all_cities` em `fleet.json`.
2. Confirma que existem `cities/<slug>/` com configuração, modelos peak/rebound/F1 e `historic/<slug>.csv`. Os relatórios F1 com `gate_pass=false` continuam bloqueados; incluir uma cidade não promove o modelo.
3. Reconstrói o bundle a partir do repositório atualizado com `python deployment/paper/build_bundle.py`.

O builder exige os artefactos e grava o SHA-256 de cada ficheiro no manifesto. Não altera os modelos nem os históricos originais.

## Instalar e lançar os quatro PAPER

Extrai o bundle e cria um ambiente novo no host de destino (Python 3.12):

```bash
python3.12 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Cria `.env` localmente com a configuração meteorológica/notificações necessária. `.env`, `.env2`, chaves privadas e posições não são copiados pelo bundle. O launcher remove variáveis de assinatura REAL antes de iniciar cada bot.

Para iniciar os PAPER habilitados no JSON:

```bash
bash deployment/paper/start_all_paper.sh
```

Cria sessões tmux `paper_deploy_a` a `paper_deploy_d`, usa logs/estado PAPER independentes e recusa sessões duplicadas. Não mata sessões, não inicia o dashboard e não migra posições/ledgers antigos.

## Collectors opcionais

Os dois collectors estão registados em `fleet.json`, ambos com `enabled: false` por omissão:

- `ask_csv`: consulta Gamma/CLOB e acrescenta snapshots ao `ask_collector_data.csv` ao intervalo configurado (padrão: 3.600 s). Não precisa da SQLite.
- `pm_books`: captura bid/ask e depth a cada 300 s com o schema de `polymarket_weather_archive.py`. Pode criar uma SQLite vazia e descobrir via Gamma apenas os mercados de hoje/amanhã; não faz backfill histórico. Se uma DB existir, o launcher verifica as tabelas sem alterar os dados durante o preflight.

Para lançar apenas collectors explicitamente ativados no JSON:

```bash
bash deployment/paper/start_collectors.sh
```

Antes de ativar `pm_books`, confirma o espaço no disco: limite configurado de 25 GiB para a DB e reserva mínima de 8 GiB livres. O preflight recusa DB inválida/excessiva ou pouco espaço; não copia dados nem descarrega histórico. Os collectors usam sessões/logs próprias e não param bots.

## Gates e operação

O inventário atual tem 34 cidades; F1 está aprovado em 20. As outras 14 continuam fail-closed em B/C/D. Alargar a lista não altera cutoffs nem promove gates. Quatro PAPER em 34 cidades multiplicam polling; observa memória e rate limits antes de deixar os processos correr continuamente. O pacote não arranca E/REAL em nenhuma circunstância.
