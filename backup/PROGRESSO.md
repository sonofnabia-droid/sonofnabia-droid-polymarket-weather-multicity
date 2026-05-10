# Progresso - Refactoring e Bug Fixing (ZAI)

## Data: 2026-04-27

## ✅ MUNICH (arquivos específicos `munich_*.py`) - COMPLETO

### Sprint 1 - Bugs Críticos ✅ TODOS
- [x] 1.1 Falsy check vento (0 km/h) ✅
- [x] 1.2 Throttling fetch APIs ✅
- [x] 1.3 Tracking trades/stats diárias ✅

### Sprint 2 - Bugs Moderados ✅ TODOS
- [x] 2.1 Comentários invertidos ✅
- [x] 2.2 ZScoreStreaming duplicada ✅
- [x] 2.3 SingleEntry reason ✅
- [x] 2.4 Pesos hardcoded ✅
- [x] 2.5 Deduplicar ceil_slot ✅
- [x] 2.6 compute_prev7 fallback ✅
- [x] 2.7 P2 "or lower" filter ✅
- [x] 2.8 init_history_max usa LOG_DIR ✅
- [x] 2.9 save_history_max com throttling ✅
- [x] 2.10 Posições resolvidas ✅
- [x] 2.11 Falsy check pressão/direção vento ✅

### Sprint 3 - Bugs Críticos ✅ TODOS
- [x] 1.1 P1 compra bracket running_max que PERDER ✅
- [x] 1.2 idxmax() PRIMEIRO máximo ✅
- [x] 1.3 prev7 OOD (climatologia) ✅
- [x] 1.4 find_bracket arredonda floor ✅
- [x] 1.5 Telegram alert_peak em P1 ✅

### Sprint 2 - Moderados ✅ TODOS
- [x] 2.1 MúLTIPLAS parcelas por slot ✅
- [x] 2.2 fc_agreement otimista ✅
- [x] 2.3 SimulatedMarket preços irreais ✅
- [x] 2.4 Market Date proteção ✅
- [x] 2.5 WU units=m retorna Celsius ✅
- [x] 2.6 Bootstrapping corta slots ✅

### Sprint 3 - Moderados ✅ TODOS
- [x] 3.1 doy_threshold otimiza PRIOR ✅
- [x] 3.2 Backtester não simula P&L ✅
- [x] 3.3 PhasedEntry P2/P3 janela horária ✅
- [x] 3.4 Z-Score reset entre dias ✅
- [x] 3.5 Features janelas diferentes ✅
- [x] 3.6 PolymarketFetcher labels ≥/≤ ✅
- [x] 3.7 Bootstrapping corta slots ✅
- [x] 3.8 log_tick protege I/O ✅
- [x] 3.9 fetch_wu retry ✅
- [x] 3.10 POLY_MAX_DAILY_LOSS validação ✅

## ✅ GENERICOS MULTI-CIDADE (completo)

### Arquivos verificados:
- **predictor.py**: init_history_max carrega do disco ✅, update_history_max com throttling ✅, compute_prev7 usa climatologia ✅
- **weather.py**: Falsy checks com is not None ✅, User-Agent corrigido ✅
- **polymarket_clob.py**: Position com temp_lo/temp_hi ✅, resolve_closed_positions ✅, ClobClient.buy_yes aceita temp_lo/temp_hi ✅
- **phased_entry.py**: SingleEntry reason correto ✅, P2/P3 com janela horária ✅
- **backtester.py**: compute_prev7_map usa climatologia ✅, idxmax usa ÚLTIMO máximo ✅
- **live_bot.py**: Passa temp_lo/temp_hi ao comprar ✅, resolve_closed_positions chamado ✅

## 📋 DALLAS E ANKARA

### O que já está pronto:
- Sistema genérico multi-cidade criado
- Configurações para Dallas/Ankara em cities/config.py com climatologia por mês
- Dados históricos em historic/dallas.csv e historic/ankara.csv
- Todos os bugs críticos do Munique aplicados

### O que falta para Dallas/Ankara:
1. Treinar modelos para Dallas e Ankara:
   - python train.py --city dallas
   - python train.py --city ankara

2. Calibrar thresholds para cada cidade:
   - Adaptar munich_calibrate.py para suportar --city <cidade>
   - Ou criar calibrate.py genérico que funciona para todas as cidades
   - Atualizar cities/config.py com thresholds/hour_min calibrados

3. Testar e validar:
   - python backtester.py --city dallas --years 3
   - python backtester.py --city ankara --years 3

### Nota: sistema genérico já usa predictor.py/weather.py/...
Portanto, uma vez que os modelos de Dallas/Ankara estiverem treinados e calibrados,
basta usar o live_bot.py genérico com:
   --cities dallas (ou dallas,ankara, munich)
