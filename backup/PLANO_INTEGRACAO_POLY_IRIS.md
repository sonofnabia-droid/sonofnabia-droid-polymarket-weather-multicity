# Plano de Integração — POLY-IRIS Features em POLY-MULTI-CITY

**Data:** 2026-05-08
**Status:** 📋 Planeado

---

## 🎯 Resumo Executivo

O POLY-IRIS (mono-city) recebeu diversas melhorias e bug fixes após a integração multi-city. Este plano visa integrar essas melhorias no POLY-MULTI-CITY, mantendo a arquitetura genérica.

**Restrições conhecidas:**
- PhasedEntry foi removido (só modes `single` e `dual`)
- polymarket_clob já está atualizado com API v2 e Cloudflare bypass

---

## 📊 Estado Atual vs Alvo

| Feature | POLY-MULTI-CITY (Atual) | POLY-IRIS (Alvo) | Status |
|---------|--------------------------|-------------------|--------|
| Stop-loss (check_stop_loss) | ✅ Implementado nos módulos | ✅ Integrado no live_bot | ⏳ Pendente |
| Telegram alerts | ⚠️ Parcial (falta stop_loss_blocked) | ✅ Completo | ⏳ Pendente |
| Detecção de posições existentes | ❌ Não implementado | ✅ Implementado | ⏳ Pendente |
| Bankroll REAL | ❌ Usa --bankroll arg | ✅ Usa USDC real | ⏳ Pendente |
| Smart Sleep | ❌ Não implementado | ✅ Polling ativo | ⏳ Pendente |
| OM Forecast Downloader | ❌ Não existe | ✅ Implementado | ⏳ Pendente |
| Calibration Tool | ❌ Não existe | ✅ Implementado | ⏳ Pendente |
| PhasedEntry | ⚠️ Referências espalhadas | ❌ Removido | ⏳ Pendente |

---

## 📝 Tarefas Detalhadas

### Tarefa 1: Remover PhasedEntry do código ⚠️

**Prioridade:** Alta
**Impacto:** Limpeza de código, evita confusão

**Arquivos a atualizar:**
1. `live_bot.py` - Remover "phased" das choices do `--mode`
2. Remover arquivos obsoletos:
   - `phased_entry.py`
   - `calibrate_phased.py`
   - `munich_phased_entry.py`
3. `munich_live_bot.py` - Remover PhasedEntry imports
4. `backtester.py` - Remover PhasedEntryStrategy class
5. `tg.py` - Remover referências a phased entry no dashboard

**Notas:**
- `modules/strategy_factory` já está correto (só single e dual)
- `modules/single_entry` e `modules/dual_strategy` já estão ok

---

### Tarefa 2: Implementar stop-loss em live_bot.py ⭐

**Prioridade:** Crítica
**Impacto:** Proteção contra perdas grandes

**Fonte:** `POLY-IRIS/munich_live_bot.py` (linhas 722-829)

**A implementar:**

1. Adicionar lógica de stop-loss no loop principal (após trade decision):
   ```python
   # ─── STOP-LOSS CHECK ────────────────────────────
   if mode in ("single", "dual") and hasattr(entry, 'check_stop_loss') and latest_obs:
       current_temp = latest_obs["temp_c"]
       stop_signal = entry.check_stop_loss(current_temp)
       if stop_signal and clob and market:
           # Lógica de throttle e tratamento dos 4 casos
   ```

2. Casos de tratamento:
   - Caso 1: bracket desapareceu do mercado → alert_stop_loss_blocked()
   - Caso 2: bid muito baixo (< 2¢) → alert_stop_loss_blocked()
   - Caso 3a: posição não encontrada no CLOB → alert_stop_loss_blocked()
   - Caso 3b: tentar vender com sucesso → alert_stop_loss_triggered()
   - Caso 3c: ordem de venda falhou → alert_stop_loss_blocked()

3. Stats:
   - Atualizar `daily_stats.stop_losses_triggered += 1`
   - Atualizar `session_stats.stop_losses_triggered += 1`

**Nota:** Modules já têm `check_stop_loss()` implementado, só falta integrar no live_bot.py

---

### Tarefa 3: Adicionar alert_stop_loss_blocked ao tg.py

**Prioridade:** Crítica (depende da Tarefa 2)
**Impacto:** Notificações completas de stop-loss

**Fonte:** `POLY-IRIS/tg.py` (linhas 224-252)

**A adicionar:**
```python
def alert_stop_loss_blocked(self, position, current_temp, reason):
    """
    Stop-loss DISPAROU mas não foi possível vender.

    Razões típicas:
      - bid muito baixo (<2¢, não vale a pena pelo gas/fee)
      - bracket sem match no mercado actual
      - posição não encontrada no CLOB
      - sell_yes falhou (rede, rate limit, etc)

    Posição vai expirar (perda total provável).
    """
    # ... implementação
```

**Nota:** POLY-MULTI-CITY já tem `alert_stop_loss_triggered`, falta apenas `alert_stop_loss_blocked`

---

### Tarefa 4: Implementar deteção de posições existentes

**Prioridade:** Alta
**Impacto:** Evita duplicação de ordens

**Fonte:** `POLY-IRIS/munich_live_bot.py` (linhas 460-512)

**A implementar:**

1. Verificar DUAS fontes para evitar duplicados:
   - Fonte 1: `bets_path.exists()` - Ler do arquivo bets_{date}.json
   - Fonte 2: `clob.positions.open_positions()` - Verificar posições abertas no CLOB

2. Se posição encontrada:
   - Restaurar estado: `entry.bought = True`, `entry.record = {...}`
   - Recuperar: `strategy_used`, `entry_ask`, `temp_hi`, `temp_lo`, `token_id`, `size_usdc`

3. Aplicar para ambos modos (single e dual)

**Nota:** Atualmente POLY-MULTI-CITY não tem esta lógica, o que pode causar duplicação de ordens.

---

### Tarefa 5: Fix bankroll em modo REAL

**Prioridade:** Alta
**Impacto:** Usa bankroll correto para decisões de trading

**Fonte:** `POLY-IRIS/munich_live_bot.py` (linhas 450-452)

**Bug atual:**
Em modo REAL, o bankroll usado é o argumento `--bankroll` em vez do saldo USDC real.

**Fix:**
```python
# Fix: em REAL mode, bankroll = saldo USDC real (não o --bankroll arg)
if trading_mode == TradingMode.REAL and usdc_balance is not None:
    bankroll = usdc_balance
```

**Local:** Em `live_bot.py` após inicializar CLOB e obter balance.

---

### Tarefa 6: Implementar Smart Sleep com polling ativo

**Prioridade:** Média
**Impacto:** Reduz latência de detecção de novos dados

**Fonte:** `POLY-IRIS/munich_config.py` (linhas 78-128)

**A implementar:**

1. Criar `utils/smart_sleep.py` (ou adicionar a config genérico):
   - Janelas de sinal EDDM: `[(18, 32), (45, 55)]` (minutos)
   - Fast poll interval: 2 segundos
   - Fora das janelas: dorme `interval` segundos normalmente
   - Dentro das janelas: polling ativo até nova temperatura ou sair da janela

2. Integrar em `live_bot.py`:
   - Substituir `time.sleep(interval)` por `smart_sleep(interval, ...)`
   - Passar `wu_key`, `wu_sess`, `last_temp` como parâmetros
   - Callback opcional `on_new_obs` para atualizar estado

**Nota:** Para multi-cidade, pode não ser necessário (cada cidade com fuso diferente), mas ajuda em cidades com WU.

---

### Tarefa 7: Adicionar OM Forecast Downloader

**Prioridade:** Média
**Impacto:** Permite calibrar Estratégia A

**Fonte:** `POLY-IRIS/om_forecast_downloader.py`

**A criar:** `om_forecast_downloader.py` na raiz

**Funcionalidade:**
- Baixa forecasts históricos do Open-Meteo (Previous Runs API)
- Baixa temperaturas reais (Archive API ERA5)
- Gera CSV com: date, forecast_day1, forecast_day2, actual_max
- Suporta múltiplas cidades (via lat/lon ou nome pré-configurado)
- Chunking para APIs (120 dias por chunk seguro)
- Estatísticas de accuracy preview

**Uso:**
```bash
python om_forecast_downloader.py                          # defaults: Munich, ontem
python om_forecast_downloader.py --start 2021-04-01 --end 2026-05-07
python om_forecast_downloader.py --lat 40.42 --lon -3.70 --city madrid
```

**Output:** `om_forecasts_<city>.csv`

---

### Tarefa 8: Criar Calibration Tool para multi-cidade

**Prioridade:** Média
**Impacto:** Permite calibrar thresholds otimizados

**Fonte:** `POLY-IRIS/munich_calibrate.py`

**A criar:** `calibrate.py` na raiz

**Funcionalidade:**
1. Grid search de thresholds (single e dual) por cidade
2. Modos: fast (21 combos), standard (69), detailed (161), full (560)
3. Métricas:
   - `roi`: Optimiza ROI $ via SimulatedMarket
   - `outcome`: Optimiza win-rate × log(volume) (métrica honesta)
4. 3 perfis de risco: CONSERVADOR, BALANCEADO, AGRESSIVO
5. Gera `strategy_config_<city>.json` com thresholds calibrados
6. Heatmaps e análise de estabilidade

**Uso:**
```bash
python calibrate.py --city munich --years 5 --mode full --metric outcome
python calibrate.py --city dallas --years 3 --mode standard
```

**Benefício:** Permite calibrar thresholds otimizados para cada cidade sem inventar preços.

---

## 🚀 Ordem de Implementação Sugerida

### Fase 1: Crítico (Prioridade Imediata)
1. ✅ Tarefa 2: Implementar stop-loss em live_bot.py
2. ✅ Tarefa 3: Adicionar alert_stop_loss_blocked ao tg.py
3. ✅ Tarefa 4: Implementar deteção de posições existentes
4. ✅ Tarefa 5: Fix bankroll em modo REAL

### Fase 2: Limpeza (Prioridade Alta)
5. ✅ Tarefa 1: Remover PhasedEntry do código

### Fase 3: Ferramentas (Prioridade Média)
6. ✅ Tarefa 7: Adicionar OM Forecast Downloader
7. ✅ Tarefa 6: Implementar Smart Sleep com polling ativo
8. ✅ Tarefa 8: Criar Calibration Tool para multi-cidade

---

## 📋 Checklist de Validação

Após implementar cada tarefa, validar:

- [ ] Testes unitários passam
- [ ] Live bot inicia sem erros
- [ ] Paper trading funciona
- [ ] Stop-loss dispara corretamente
- [ ] Telegram alerts funcionam
- [ ] Não há duplicação de ordens
- [ ] Bankroll real é usado em modo REAL
- [ ] OM forecast downloader gera CSV válido
- [ ] Calibration tool executa sem erros

---

**Última Atualização:** 2026-05-08
**Status:** 📋 Planeado
**Pronto para:** Implementação faseada
