# Stake spectrum diagnostic — price bands 35–90¢

**READ-ONLY historical simulation.** Reads Cassiopeia tick JSONL, `cassiopeia_active_config.json` and `market_winners.json`; only this experiment directory is written. No orders, bots, services, SQLite or source data changed.

## Pre-registered hypothetical schedule

| Best ask CLOB | Stake per signal |
|---:|---:|
| 35–<50¢ | $1 |
| 50–<60¢ | $2 |
| 60–<75¢ | $3 |
| 75–90¢ | $4 |

## Dataset filters and execution caveat

Dates scanned: 2026-11-10–2026-11-16. Parsed 117053 of 117084 JSONL lines; 31 malformed/incomplete lines were skipped. Action ticks with a Cassiopeia `p_rebound` reason were filtered to target market source CLOB, non-empty target ask ladder, target quote/book best ask within 1.1¢, best ask in [35¢,90¢], and one unique resolved winner in the local cache. One earliest qualifying candidate per city-day. Qualified candidate ticks before dedup: 340; unique city-days: 42; cities: 25; dates: 6.
The bot allows one entry per city/day. The `spectrum_*` arms enter once at the first Cassiopeia signal whose CLOB ask falls in [35¢,90¢]; the $1-flat and banded-stake arms use this exact same first entry. They never add a later purchase, so an early low-price entry can displace a later high-price confirmation. The `current_gate_*` arms instead select the first signal that passes the active per-city min/max. These are competing path policies, not positions that can all be held together.
The order-book walk consumes displayed asks up to the band's upper boundary and stake budget. This is a snapshot-depth upper bound, not a fill; book age, queue, latency, cancellation, market impact, settlement-source correctness and outcome-cache provenance remain unverified. P&L shown after fee assumes taker fee 5% for Weather; actual maker/taker treatment may differ by execution. No-fee gross is also included in CSV.
Labels come from local `market_winners.json`, not an independent audit of official settlement. Nov 16 is included only if the cache reports one resolved winner.

## Entry timing and displaced later opportunities

Among 42 city-days with a qualifying 35–90¢ spectrum candidate, 18 first entries were below the current city min or otherwise outside the active band. In 5 city-days a later candidate did pass the current gate; the current-gate arm takes that later signal, while the spectrum arm is already committed to its first entry. Outcomes in those paired paths: early loss/later win 2; early win/later loss 0. The event CSV has separate records for both paths.

## Aggregate results

All P&L metrics below use simulated top-five ask ladder VWAP and taker-fee scenario. Percent positive is per contract (net P&L > 0). Sharpe/Sortino annualize daily P&L divided by that day's deployed stake with √252; the short sample makes them unstable and non-predictive. Drawdown assumes $100 starting equity and additive, fixed stakes, no compounding.

| Arm | n | cities | dates | wins | hit % | profitable contracts % | invested $ | net P&L $ | ROI on spent % | profit factor | positive days % | MaxDD $ (from $100) | Sharpe | Sortino |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| spectrum_flat1 | 42 | 25 | 6 | 27 | 64.29 | 64.29 | 42.00 | -7.61 | -18.12 | 0.50 | 16.67 | 8.58 | -5.62 | -6.88 |
| spectrum_curve | 42 | 25 | 6 | 27 | 64.29 | 64.29 | 134.00 | -12.38 | -9.24 | 0.66 | 16.67 | 14.33 | -4.49 | -5.66 |
| current_gate_flat1 | 29 | 23 | 6 | 24 | 82.76 | 82.76 | 29.00 | -0.87 | -2.98 | 0.83 | 50.00 | 2.45 | -3.71 | -4.12 |
| current_gate_curve | 29 | 23 | 6 | 24 | 82.76 | 82.76 | 113.00 | -2.05 | -1.81 | 0.89 | 50.00 | 7.76 | -3.70 | -4.10 |

Paired day-cluster bootstrap (10,000 draws, seed 20261116) for curve minus flat-$1 taker-net P&L in the full 35–90¢ spectrum: 6 shared event dates; 95% percentile interval [-12.30, 2.65] USD.

## Results by price band

| Band | n | cities | wins | hit % | curve stake | gross P&L $ | taker fee $ | net P&L $ | profitable contracts % | median ask depth $ | full scheduled stake visible |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 35–<50¢ | 2 | 2 | 0 | 0.0 | $1 | -2.00 | 0.061 | -2.06 | 0.0 | 32.54 | 2/2 |
| 50–<60¢ | 9 | 8 | 2 | 22.2 | $2 | -10.36 | 0.414 | -10.78 | 22.2 | 39.68 | 9/9 |
| 60–<75¢ | 10 | 9 | 6 | 60.0 | $3 | -2.85 | 0.503 | -3.35 | 60.0 | 76.25 | 10/10 |
| 75–90¢ | 21 | 18 | 19 | 90.5 | $4 | 4.40 | 0.580 | 3.82 | 90.5 | 160.33 | 21/21 |

## Per-city table

O CSV contém cada cidade-dia e os quatro braços; não promover cidades por desempenho nesta amostra curta.

| Cidade | candidatos 35–90¢ | wins | preço mediano | curva gross $ | curva fee-net $ | atuais elegíveis | current-gate curve net $ |
|---|---:|---:|---:|---:|---:|---:|---:|
| amsterdam | 1 | 1 | 82.0¢ | 0.88 | 0.84 | 1 | 0.84 |
| buenos_aires | 2 | 0 | 64.0¢ | -5.00 | -5.09 | 1 | -3.05 |
| busan | 2 | 1 | 50.0¢ | 0.00 | -0.10 | 1 | 0.52 |
| chengdu | 2 | 0 | 62.0¢ | -5.00 | -5.10 | 1 | 0.44 |
| chongqing | 1 | 1 | 90.0¢ | 0.44 | 0.42 | 1 | 0.42 |
| guangzhou | 1 | 0 | 70.0¢ | -3.00 | -3.04 | 1 | -4.04 |
| jeddah | 1 | 1 | 87.0¢ | 0.60 | 0.57 | 1 | 0.57 |
| karachi | 2 | 2 | 78.0¢ | 2.76 | 2.67 | 2 | 2.10 |
| kuala_lumpur | 2 | 2 | 90.0¢ | 1.73 | 1.67 | 1 | 0.42 |
| london | 2 | 2 | 90.0¢ | 1.04 | 1.00 | 2 | 1.00 |
| lucknow | 3 | 2 | 83.0¢ | -0.74 | -0.83 | 2 | 1.21 |
| manila | 2 | 1 | 90.0¢ | -3.56 | -3.60 | 2 | -3.60 |
| milan | 2 | 2 | 89.0¢ | 1.97 | 1.90 | 1 | 0.47 |
| munich | 1 | 1 | 82.0¢ | 0.88 | 0.84 | 1 | 0.84 |
| panama_city | 3 | 1 | 61.0¢ | -3.08 | -3.23 | 2 | -1.19 |
| paris | 2 | 2 | 84.0¢ | 2.68 | 2.59 | 1 | 0.73 |
| seoul | 1 | 1 | 89.2¢ | 0.48 | 0.46 | 1 | 0.46 |
| shanghai | 1 | 1 | 87.0¢ | 0.60 | 0.57 | 1 | 0.57 |
| shenzhen | 2 | 0 | 86.0¢ | -6.00 | -6.08 | 2 | -3.60 |
| singapore | 1 | 1 | 89.0¢ | 0.49 | 0.47 | 1 | 0.47 |
| tel_aviv | 2 | 1 | 73.0¢ | 0.01 | -0.06 | 0 | 0.00 |
| tokyo | 1 | 1 | 80.0¢ | 1.00 | 0.96 | 1 | 0.96 |
| warsaw | 1 | 1 | 80.0¢ | 1.00 | 0.96 | 1 | 0.96 |
| wellington | 1 | 1 | 66.0¢ | 1.55 | 1.49 | 0 | 0.00 |
| wuhan | 3 | 1 | 57.0¢ | -2.56 | -2.65 | 1 | 0.42 |

## Interpretation limits

- Este resultado testa uma regra hipotética de stake e, no braço amplo, também a inclusão contrafactual de sinais abaixo do mínimo atualmente ativo; não é validação prospectiva nem recomendação de alteração.
- O `p_rebound` é guardado no motivo da ação, mas continua a prever rebound de temperatura, não probabilidade calibrada da bracket final. Esta experiência não usa `p_rebound` como `p_win`; apenas toma os sinais existentes como universo de candidatos.
- Um snapshot com depth suficiente não garante execução, e a taxa de taker é cenário conservador de fee, não prova do tipo de execução do PAPER.
- A amostra é pequena, multi-cidade e possivelmente dependente; os dias do holdout já foram vistos. Sharpe/Sortino não validam edge com poucos dias.
- Próximo teste confirmatório: nova janela intocada e PAPER prospectivo, com labels oficiais auditados, bid/ask/depth frescos, fills, fees reais, capital total simultaneamente exposto e bootstrap agrupado por data.
