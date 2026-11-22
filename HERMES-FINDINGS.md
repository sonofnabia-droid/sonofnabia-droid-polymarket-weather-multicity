# HERMES-FINDINGS

Auditoria estática e dinâmica realizada em 17 de novembro de 2026.

Este documento regista bugs reproduzidos, problemas identificados por inspeção e hipóteses que precisam de confirmação. Nenhum ficheiro de código foi alterado durante a auditoria.

## Escopo

- Integrações CASSIOPEIA na raiz e em `integracoes/`.
- `portfolio.py`, `jobs.py`, `bots.py` e `tradingview.py`.
- `hermes_weatherbot/bot_v1.py`, `bot_v2.py`, `bot_v3.py`.
- Testes offline disponíveis.
- Duplicação por cidade/slot, timestamps e DST, retries, dados ausentes, fills, custos, treino/holdout e look-ahead.

## Estado dos testes

Comandos executados:

```text
integracoes/.venv/bin/python -m pytest -q integracoes/test_integracoes.py
3 passed

PYTHONPATH=. integracoes/.venv/bin/python -m pytest -q tests/test_integrations.py
4 passed

integracoes/.venv/bin/python -m pytest -q integracoes/test_integracoes.py tests/test_integrations.py --cov=. --cov-report=term-missing
1 failed, 6 passed
```

A falha combinada ocorre em `tests/test_integrations.py::test_tradingview_dedupe`: o módulo `tradingview` resolvido é `integracoes/tradingview.py`, mas o teste espera a API de `tradingview.py` da raiz (`secret()` e `init()`). As suites passam quando executadas isoladamente.

Cobertura combinada: 57%.

```text
integracoes/cassiopeia.py       46%
integracoes/tradingview.py      42%
tradingview.py                  0% na execução combinada
```

`compileall` passou para os módulos auditados.

Ruff nos ficheiros principais encontrou 13 diagnósticos, sobretudo imports e uso de aliases de timezone. O Ruff sobre toda a árvore encontrou muito mais diagnósticos porque também analisa `hermes_weatherbot` e subprojetos embutidos.

`mypy` e `pyright` não estão instalados. O `.venv` da raiz também não tem `pytest` nem `ruff`; os comandos do `README.md` não são executáveis nesse ambiente sem instalar dependências.

## Findings confirmados

### F-01 — TradingView aceita timestamp sem timezone

- **Estado:** reproduzido.
- **Ficheiro:** `tradingview.py:25`.
- **Comportamento:** `valid()` aceita `2026-11-17T10:00:00`.
- **Impacto:** o alerta pode ser persistido sem uma referência temporal inequívoca. Comparações e ordenação posteriores podem misturar timestamps locais e UTC.
- **Sugestão:** rejeitar timestamps ingênuos e normalizar os timestamps aceites para UTC antes da persistência.

### F-02 — TradingView aceita `NaN` e `Infinity` como preço

- **Estado:** reproduzido.
- **Ficheiro:** `tradingview.py:25`.
- **Comportamento:** `valid()` aceita `preco="NaN"` e `preco="Infinity"`.
- **Impacto:** valores não finitos podem contaminar a base de dados, relatórios e cálculos.
- **Sugestão:** converter para `float` e exigir `math.isfinite()`.

### F-03 — CSV externo inválido interrompe snapshot de portfolio

- **Estado:** reproduzido.
- **Ficheiro:** `portfolio.py:36`.
- **Reprodução:** uma linha com `quantity=not-a-number` provoca `ValueError` e termina `_external()`.
- **Impacto:** uma única linha inválida impede o snapshot completo.
- **Sugestão:** validar cada linha individualmente, registar a falha em `data_failures` e continuar com as restantes linhas.

### F-04 — Conversão silenciosa de timestamps ingênuos em `bots.py`

- **Estado:** reproduzido por inspeção do comportamento.
- **Ficheiro:** `bots.py:13`.
- **Comportamento:** timestamps sem timezone recebem UTC implicitamente.
- **Impacto:** se a origem tiver gravado hora local, o relatório desloca o evento sem aviso.
- **Sugestão:** rejeitar timestamps sem timezone ou aceitar uma timezone de origem explícita e documentada.

### F-05 — Duas implementações incompatíveis de TradingView

- **Estado:** reproduzido pela execução combinada dos testes.
- **Ficheiros:**
  - `tradingview.py:19-46`;
  - `integracoes/tradingview.py:18-34`;
  - `tests/test_integrations.py:24-26`.
- **Diferenças:** tabelas, funções, autenticação e formato de payload diferentes.
- **Impacto:** a suite depende da ordem e do caminho de importação.
- **Sugestão:** escolher uma implementação única ou transformar cada implementação num pacote com imports explícitos.

### F-06 — `bot_v2.py` configura `MAX_SLIPPAGE`, mas não filtra o spread

- **Estado:** confirmado por inspeção.
- **Ficheiro:**
  - configuração: `hermes_weatherbot/bot_v2.py:39`;
  - cálculo de entrada: `hermes_weatherbot/bot_v2.py:619-627`.
- **Comportamento:** o v2 calcula EV usando o ask, mas não rejeita spreads acima de `MAX_SLIPPAGE`.
- **Impacto:** entradas paper/live podem assumir condições de execução irrealistas.
- **Sugestão:** aplicar o mesmo filtro de spread existente no v3 ou retirar o v2 do caminho operacional.

### F-07 — Segredo configurado em JSON

- **Estado:** confirmado por inspeção; o valor não é reproduzido neste documento.
- **Ficheiro:** `hermes_weatherbot/config.json:12`.
- **Comportamento:** existe uma chave de serviço não mascarada no JSON.
- **Impacto:** risco de exposição por Git, backups, cópias e logs.
- **Sugestão:** revogar/rotacionar a chave, removê-la do ficheiro versionável e carregá-la exclusivamente de `.env` ou de um gestor de segredos. Verificar também o histórico Git.

### F-08 — Estado de simulação histórico não está claramente separado do estado atual

- **Estado:** confirmado por inspeção.
- **Ficheiro:** `hermes_weatherbot/simulation.json`.
- **Comportamento:** contém posições datadas de 18 a 20 de abril de 2026, enquanto a auditoria ocorre em 17 de novembro de 2026.
- **Impacto:** pode ser interpretado como estado atual ou performance recente.
- **Sugestão:** marcar explicitamente o ficheiro como fixture histórico e separar fixtures de estado live.

## Findings de fluxo live

### F-09 — Falta de idempotência antes de enviar ordem no v3

- **Estado:** bug identificado por inspeção; falta reprodução offline com API simulada.
- **Ficheiros:** `hermes_weatherbot/bot_v3.py:910-1000`, `1005-1074`, `1104-1123`.
- **Comportamento:** o scan calcula e envia a ordem antes de consultar/validar uma posição existente para a mesma cidade/data/market.
- **Impacto:** scans sucessivos podem comprar novamente o mesmo slot. A gravação posterior pode substituir o registo anterior.
- **Sugestão:** verificar uma chave idempotente (`city`, `date`, `market_id`) antes do envio e usar lock/transação para impedir concorrência.

### F-10 — Duplicação de cidade/slot em execuções concorrentes

- **Estado:** risco confirmado por inspeção; não foi executada uma ordem real.
- **Ficheiros:** `hermes_weatherbot/bot_v3.py:844-846` e `1041-1123`.
- **Comportamento:** o nome do ficheiro `city_date.json` evita apenas duplicação depois da persistência. Não protege a janela entre leitura, envio e escrita.
- **Impacto:** dois processos podem enviar duas ordens para o mesmo slot.
- **Sugestão:** lock por slot, operação idempotente no armazenamento e reconciliação com ordens abertas do CLOB antes de comprar.

### F-11 — Custos de execução não entram integralmente no P&L

- **Estado:** confirmado por inspeção; não há fixture de fill real para quantificar.
- **Ficheiros:**
  - `hermes_weatherbot/bot_v3.py:187-217`;
  - `hermes_weatherbot/bot_v3.py:1083-1098`;
  - lógica de fecho no fluxo de scan.
- **Comportamento:** `cost` representa essencialmente `shares * price`. Não há cálculo completo de fees, gas, aprovação ou preço efetivamente preenchido.
- **Impacto:** P&L e aprendizagem adaptativa podem ser sobrestimados.
- **Sugestão:** guardar preço/quantidade efetivos do fill, fees, gas, slippage realizado e distinguir P&L bruto de líquido.

### F-12 — Possível confusão entre `conditionId` e `token_id`

- **Estado:** hipótese de integração, não bug reproduzido.
- **Ficheiros:**
  - `hermes_weatherbot/bot_v3.py:793-806`;
  - `hermes_weatherbot/bot_v3.py:1041-1043`;
  - `hermes_weatherbot/bot_v3.py:600-605`.
- **Observação:** `get_condition_id()` retorna um valor chamado `conditionId`, que é atribuído a `token_id` antes de construir `MarketOrderArgs`.
- **Impacto potencial:** ordens rejeitadas ou associadas ao identificador incorreto.
- **Sugestão:** confirmar contra o contrato/API do CLOB e adicionar um teste de construção da ordem com fixture de mercado.

## Dados, treino e validação

Não encontrei uma implementação formal de backtest com:

- separação treino/holdout;
- prevenção explícita de look-ahead;
- fills baseados em bid/ask históricos;
- fees, gas e slippage históricos;
- tratamento mensurável de dados ausentes;
- métricas fora da amostra.

A calibração em `bot_v2.py`/`bot_v3.py` usa histórico resolvido e snapshots persistidos, mas não existe uma suite que prove isolamento temporal entre treino e avaliação. A validade financeira dos resultados não está demonstrada.

## Testes recomendados antes de qualquer correção

1. Repetir duas vezes o mesmo scan com APIs e CLOB simulados; verificar exatamente uma ordem.
2. Executar dois scans concorrentes para o mesmo `city/date/market_id`.
3. Simular timeout depois do fill e antes de `save_market()`; verificar reconciliação.
4. Testar timestamps ingênuos, UTC, DST e offsets diferentes.
5. Testar `NaN`, `Infinity`, strings vazias e preços fora de `(0, 1)`.
6. Testar CSV com uma linha inválida entre linhas válidas.
7. Testar spreads acima e abaixo do limite no v2 e v3.
8. Testar P&L líquido com fee, gas, spread e fill parcial.
9. Executar todas as suites no mesmo processo com imports de pacote explícitos.
10. Criar um fixture de backtest com treino, validação e holdout temporalmente separados.

## Estado final

Nenhum código foi alterado. Este ficheiro é apenas o registo da auditoria e das sugestões de correção.
