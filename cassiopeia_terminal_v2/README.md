# CASSIOPEIA — Trading Command Center V2

Nova interface de leitura, sem alterar bots, ordens, estratégias ou configuração de trading.

## Como experimentar

1. Fazer backup da dashboard antiga.
2. Copiar `index.html` para `dashboard/static/index_v2.html` no repositório (ou outro diretório servido pelo Flask).
3. Abrir `http://127.0.0.1:8787/static/index_v2.html` enquanto o servidor atual estiver ativo.
4. Se o Flask não servir esse diretório, colocar os dois ficheiros desta pasta num diretório separado e executar `python -m http.server 8790` nesse diretório. A pré-visualização mostrará o snapshot histórico de demonstração, pois a API em 8787 é outra origem.

## APIs existentes utilizadas

`/api/overview`, `/api/cities`, `/api/era`, `/api/events?days=30`, `/api/equity`, `/api/avsb`.

A nova interface não chama endpoints de escrita nem executa operações. O indicador de processo vivo vem de `/api/overview`, não é uma inspeção independente de processos. A exposição financeira total, saldos reais e confirmação on-chain/exchange só devem ser mostrados quando houver endpoints fiáveis para isso.

O snapshot de demonstração foi sanitizado para remover token IDs e livros de ordens detalhados. É histórico de 2026-11-11, não dados em tempo real.
