# Runbook Pós-Reboot (Curto)

Data: 2026-05-20
Ambiente alvo: `STAGING`

## 1) Entrar no projeto e venv
```bash
cd /home/marco/POLY-MULTI-CITY-STAGING
source venv/bin/activate
```

## 2) Sanity check rápido
```bash
python -V
ls -1 strategy_config_*.json | wc -l
```

## 3) Confirmar que não há processo antigo preso
```bash
ps -ef | rg "calibrate_all.py|backtester.py|live_bot.py" | rg -v rg
```

## 4) Retomar calibração (equilibrado)
```bash
python calibrate_all.py --years 5 --mode standard --margin 0.01
```

## 5) Se quiseres forçar overwrite da lógica nova
```bash
python calibrate_all.py --years 5 --mode standard --margin 0.01 --force-write
```

## 6) Validar 1 cidade com profiles
```bash
python backtester.py --cities munich --start 2010-01-01 --use-city-profiles
```

## 7) Validar lote de cidades prioritárias
```bash
python backtester.py --cities karachi,beijing,singapore,kuala_lumpur,jakarta,tel_aviv --start 2010-01-01 --use-city-profiles
```

## 8) Avançar para paper-live (quando ok)
```bash
python live_bot.py --run paper
```

## 9) Regra de decisão rápida
- Se `NoEntry%` estiver extremo em quase todas as cidades: afrouxar filtros.
- Se `Prem%`/stops subir: voltar a apertar peak-now.
- Não promover para live sem backtest com `--use-city-profiles` nas cidades ativas.
