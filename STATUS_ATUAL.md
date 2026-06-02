# Status Atual - POLY-MULTI-CITY

Data: 2026-05-20 (Europe/Lisbon)
Repo principal: `/home/marco/POLY-MULTI-CITY`
Repo staging: `/home/marco/POLY-MULTI-CITY-STAGING`

## 1) O que já foi feito

### Main (`POLY-MULTI-CITY`)
- `live_bot.py`: corrigido settlement de paper positions antigas (não só do mesmo dia).
- `tg.py`: corrigido cálculo de `max_profit` no alerta de ordem colocada (evita mostrar `+0.00$` quando havia lucro potencial).

### Staging (`POLY-MULTI-CITY-STAGING`)
- Estratégia migrada para lógica **peak-now** (sem exigir descida confirmada).
- Integração de perfis por cidade (`city_profiles.py`) com parâmetros ajustáveis por cidade.
- `live_bot.py` adaptado para usar filtros por cidade e gatilho peak-now.
- `weather.py` alterado para fluxo WU e fallback de path por cidade/ICAO.
- `calibrate.py` expandido para otimizar automaticamente parâmetros de peak-now:
  - `peak_hold_slots`
  - `peak_lookback_slots`
  - `peak_plateau_c`
- `calibrate_all.py` atualizado para gravar parâmetros otimizados por cidade em `strategy_config_<city>.json`.
- `city_profiles.py` atualizado para ler overrides a partir dos `strategy_config_<city>.json`.

## 2) Estado da calibração atual

- Estava a correr `calibrate_all.py` e a mostrar muitos casos com:
  - `Action: KEEP -x% (below 1% threshold)`
- Interpretação:
  - A nova calibração ficou abaixo da config atual além da margem definida.
  - Logo **não sobrescreve** essa cidade (comportamento esperado).
- Isto pode acontecer por mudança de lógica (peak-now mais seletiva).

## 3) Leitura operacional atual

- A lógica nova ficou mais seletiva (menos trades, maior precisão por trade).
- No caso de Munich com `--use-city-profiles`:
  - Melhor timing (lag menor), menos stops.
  - Muito menos trades (NoEntry muito alto).
- Conclusão prática: alinhado com objetivo de segurança/seletividade, mas pode exigir multi-cidade para volume total.

## 4) Comandos úteis após reboot

### Ativar ambiente
```bash
cd /home/marco/POLY-MULTI-CITY-STAGING
source venv/bin/activate
```

### Verificar rapidamente configs geradas
```bash
ls -1 strategy_config_*.json
```

### Continuar calibração (modo equilibrado)
```bash
python calibrate_all.py --years 5 --mode standard --margin 0.01
```

### Forçar escrita mesmo se piorar (usar com cuidado)
```bash
python calibrate_all.py --years 5 --mode standard --margin 0.01 --force-write
```

### Backtest de validação por cidade com perfis
```bash
python backtester.py --cities munich --start 2010-01-01 --use-city-profiles
```

## 5) Próximo passo recomendado

1. Concluir calibração em staging.
2. Rodar backtest `--use-city-profiles` nas cidades prioritárias.
3. Escolher conjunto GO/WATCH final para paper-live multi-cidade.
4. Só depois promover alterações para live.

## 6) Nota importante

- Como houve mudança de lógica, evitar comparar resultados novos com antigos sem separar claramente:
  - versão de modelo,
  - versão de `strategy_config`,
  - flags usadas no backtest.
