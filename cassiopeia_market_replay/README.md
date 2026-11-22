# Cassiopeia Market Replay v0.2 — interface inspirada na organização da Polymarket

**Ferramenta local, só de leitura.** Reproduz um dia do mercado com gráfico de preços multi-bracket, gráfico separado de temperatura observada, tabela de brackets YES/NO e uma barra temporal sincronizada. Esta versão segue a familiaridade visual do ecrã da Polymarket, sem utilizar branding nem código da plataforma.

## Instalação em Ubuntu (projeto Cassiopeia)

Extrai o ZIP `cassiopeia_market_replay_v02.zip` na raiz de `~/POLY-MULTI-CITY-V2/` (mantém a pasta `cassiopeia_market_replay/`). **Faz primeiro backup da pasta v0.1 se tiveres alterações tuas.**

```bash
cd ~/POLY-MULTI-CITY-V2
unzip -o ~/Downloads/cassiopeia_market_replay_v02.zip
./venv/bin/python cassiopeia_market_replay/server.py
```

Abre <http://127.0.0.1:8788/>. Se a porta **8788** já estiver ocupada pela versão anterior, basta recarregar o navegador com `Ctrl+Shift+R` após a extração, pois o servidor existente serve ficheiros estáticos atuais a cada pedido. Se tiveres modificado o servidor, reinicia somente o servidor de replay (não os bots). Também é possível iniciar outra instância do replay com `--port 8789`.

Não há dependências JS externas nem instalações npm. Apenas Python padrão, SQLite e um navegador. O servidor acede a `data/polymarket_weather_2026.sqlite` em **read-only**; não escreve na SQLite, não envia ordens e não altera A/B/C/D, `pm_books` nem os backfills.

## Design e comportamento

- **Gráfico principal:** curvas de preços YES/NO das quatro brackets com maior preço histórico disponível **até ao instante de reprodução**; a bracket selecionada está sempre incluída, com linha em **ciano**. Outras cores distinguem as séries. Eixo y em percentagem do preço (preço YES é proxy de probabilidade, não probabilidade calibrada).
- **Tabela semelhante à Polymarket:** linhas com bracket, preço YES histórico, e duas áreas **YES** e **NO** com preços em cêntimos. Onde existe snapshot recente (até 15 min), exibe `ASK OBSERVADO`; caso contrário, apenas `HISTÓRICO` (não assume execução possível). Clicar num preço **apenas seleciona** o outcome e a bracket para análise, não compra nada.
- **Highlight:** ciano para seleção manual, dourado para bracket correspondente **aproximadamente** ao máximo observado após arredondamento inteiro. O dourado não equivale a regra oficial nem revela resultado futuro. O reconhecimento de brackets em intervalos `or below/above` ainda não está automatizado.
- **Temperatura:** gráfico separado com observações meteorológicas em **degraus** (não interpola), máximo acumulado, última leitura e idade do reporte. Seleciona uma fonte WU/METAR/NOAA ou sobrepõe fontes disponíveis. A atualização da temperatura só ocorre quando há um novo timestamp conhecido.
- **Relógio:** replay desde a meia-noite local, timeline drag, play/pause, saltos de ±5 minutos, botão para a próxima observação meteorológica, velocidades 1×, 2×, **3× por defeito**, 5×, 10×, 30× e **AUTO**. A convenção é 1× = 1 minuto de mercado / segundo real. AUTO passa a 2× perto dos timestamps de novas observações e a 10× fora desses períodos.
- **Causalidade:** cada gráfico, valor e ranking utiliza apenas pontos cujo timestamp seja ≤ ao relógio do replay. Não revela a bracket liquidada, nem faz uso do preço final no instante inicial. A seleção de TOP4 evolui com os preços disponíveis.

## Limitações meteorológicas e financeiras

- `price_points` é histórico de preços, **não histórico de asks executáveis**. `book_snapshots` é a única fonte de asks arquivados. Os livros antigos que não capturámos não podem ser reconstruídos a partir de preços.
- As séries meteorológicas fornecem em geral **hora de observação**, não a hora comprovada de publicação/disponibilização. Para backtests causais, deverá existir `available_at`, além de `observed_at`. Por ora, isto é uma visualização exploratória, não uma demonstração de execução histórica possível.
- O destaque dourado faz correspondência simples entre o máximo acumulado e uma bracket de temperatura inteira. O contrato pode exigir METAR de rotina, grupo T, elegibilidade de reportes e arredondamento específico. A regra oficial deve ser implementada por contrato antes de usar o destaque para trading.
- Os preços históricos podem ter cadências irregulares. O gráfico usa passos entre amostras e quebra sequências com lacunas longas. O replay conserva a hora real de cada observação.
- Não existem ordens, wallets, autenticação ou transações.

## Fontes locais

O backend Python v0.1 é preservado. Lê, quando disponíveis:

- `data/polymarket_weather_2026.sqlite`: `events`, `markets`, `tokens`, `price_points`, `book_snapshots`;
- `historic_noaa/ghcnh_history.sqlite`: `wu_observations` e/ou `observations`;
- `historic/<city>.csv` com `timestamp_utc,temp_c`;
- `weather_source_monitor.sqlite`;
- `--metar-csv-dir <diretório>` como fonte METAR CSV opcional.

O replay não inventa observações quando a série meteorológica não está disponível.

## Testes

A versão foi verificada com `node --check`, `python -m py_compile` e um teste headless de renderização e interação com **SQLite sintética**, incluindo tabelas de preços, bid/ask e observações meteorológicas. Os dados da captura de ecrã de pré-visualização são artificiais. A integração precisa ainda de ser validada com a **SQLite real do CASSIOPEIA**.

## Próximos passos

1. Regras de liquidação por contrato e horário verdadeiro de publicação `available_at`.
2. Overlay opcional de sinais A/B/C e instante em que o modelo sugeriu comprar.
3. Diferença WU–METAR e possíveis atrasos de reação de preços.
4. Simulação de ordens PAPER e curva de equity, quando a execução histórica estiver devidamente fundamentada.
