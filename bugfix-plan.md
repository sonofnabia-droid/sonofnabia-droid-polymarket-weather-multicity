```markdown
# 🛠️ Fix Plan — Polymarket Temp Bot

Este documento contém instruções cirúrgicas para corrigir 28 bugs identificados no projeto.
O agente de IA (Codex) deve seguir a ordem de severidade (Crítico → Alto → Moderado → Menor).

---

## 🔴 CRITICAL BUGS (Prioridade Máxima)

### Bug 1: `backtester.py` truncado (SyntaxError)
**Ficheiro:** `backtester.py`
**Problema:** O ficheiro está cortado na linha `f"  Capital perdido por clipping ($100 piso): [bold]${sum_t`. Isto impede a importação e quebra todo o pipeline.
**Fix:** Encontrar a linha truncada no final do ficheiro e substituí-la por:
```python
            f"  Capital perdido por clipping ($100 piso): [bold]${sum_total_clip:+,.2f}[/bold]"
```

### Bug 2: `compute_stats.total_trades` subconta trades
**Ficheiro:** `backtester.py`
**Problema:** `total_trades` soma apenas `correct + premature`. Um trade que entrou tarde e perdeu não é contabilizado.
**Fix:** Na função `compute_stats`, encontrar a linha:
```python
total_trades  = int(df[f"{prefix}_correct"].sum() + df[f"{prefix}_premature"].sum()),
```
Substituir por:
```python
total_trades  = int((~df[f"{prefix}_missed"]).sum()),
```

### Bug 3: Poluição de estado global em multi-cidade (`predictor.py` / `live_bot.py`)
**Ficheiro:** `live_bot.py`
**Problema:** O `predictor.py` usa variáveis globais (`_city_config`, etc.) que são sobrescritas a cada cidade no `live_bot.py`, causando mistura de timezones e configs.
**Fix:** No ficheiro `live_bot.py`, dentro da função `_tick_city`, logo no início da função (após a linha `city = state.city`), adicionar:
```python
    from predictor import set_city
    set_city(city.name)
```
Isto garante que o contexto global do predictor está sempre correto para a cidade que está a ser processada no tick atual.

### Bug 4: `_last_save_time` partilhado entre cidades
**Ficheiro:** `predictor.py`
**Problema:** A variável global `_last_save_time` impede que o `history_max` de cidades diferentes seja guardado num intervalo curto.
**Fix:** Em `predictor.py`, substituir:
```python
_last_save_time: float = 0.0
```
Por:
```python
_last_save_times: dict[str, float] = {}
```
E na função `update_history_max`, substituir o bloco de salvamento no final:
```python
    import time
    now = time.time()
    if now - _last_save_time >= 300 or old_max is None or cur_max > old_max:
        _save_history_max_file(history, city_name)
        _last_save_time = now
```
Por:
```python
    import time
    now = time.time()
    key = city_name or _get_city().name
    last = _last_save_times.get(key, 0.0)
    if now - last >= 300 or old_max is None or cur_max > old_max:
        _save_history_max_file(history, city_name)
        _last_save_times[key] = now
```

### Bug 5: `ceil_slot(23, 45)` retorna hora inválida 24
**Ficheiro:** `live_bot.py`
**Problema:** A função não faz wrap de 24h para 23:30, ao contrário de `backtester.py`.
**Fix:** Em `live_bot.py`, substituir a função `ceil_slot` inteira por:
```python
def ceil_slot(hour: int, minute: int) -> tuple[int, int]:
    """Converte (hour, minute) para slot 30min (truncar para CIMA)."""
    if minute < 30:
        return (hour, 30)
    else:
        h = hour + 1
        if h == 24:
            return (23, 30)
        return (h, 0)
```

### Bug 6: Bankroll nunca atualizado no loop principal
**Ficheiro:** `live_bot.py`
**Problema:** O bankroll é carregado apenas no arranque. Sessões longas ficam com valores obsoletos.
**Fix:** Dentro do `while True:` loop principal, no bloco que faz o display multi-cidade (dentro do `if is_multi:` ou mesmo antes), adicionar a atualização por hora:
```python
                # Atualizar bankroll a cada hora
                if state.clob and trading_mode == TradingMode.REAL:
                    h_now = city_now(state.city).hour
                    if not hasattr(state, '_last_bankroll_hour') or state._last_bankroll_hour != h_now:
                        try:
                            usdc_balance = state.clob.get_usdc_balance()
                            if usdc_balance is not None:
                                city_bankrolls[city_name] = usdc_balance
                            state._last_bankroll_hour = h_now
                        except Exception:
                            pass
```

---

## 🟠 HIGH SEVERITY BUGS

### Bug 7: Flag `_stop_loss_blocked_alerted` nunca reseta
**Ficheiro:** `live_bot.py`
**Problema:** Se o stop-loss for bloqueado uma vez, o flag impede alertas futuros mesmo se as condições mudarem.
**Fix:** No bloco de reset diário dentro de `_tick_city` (onde `state._last_date` é verificado), adicionar:
```python
        if hasattr(state.entry, '_stop_loss_blocked_alerted'):
            state.entry._stop_loss_blocked_alerted = False
```

### Bug 8: Imports duplicados e frágeis em `live_bot.py`
**Ficheiro:** `live_bot.py`
**Problema:** Existem duas linhas de import do `predictor`, a segunda sobrescreve a primeira e omite `init_history_max`.
**Fix:** Apagar a segunda ocorrência de:
```python
from predictor import set_city, load_models, build_features, predict_ensemble, compute_prev7
```
Deixar apenas a primeira que contém `init_history_max`.

### Bug 9: Atributos dinâmicos em `CityState` dataclass
**Ficheiro:** `live_bot.py`
**Problema:** Atributos usados no runtime não estão declarados na dataclass, causando erros em linters e potenciais `AttributeError`.
**Fix:** Adicionar os seguintes campos à dataclass `CityState`:
```python
    last_p_ensemble: float = 0.0
    last_p_lgbm: Optional[float] = None
    last_target_bracket: Optional[dict] = None
    _last_date: Optional[date] = None
    _last_bankroll_hour: int = -1
```

### Bug 10: Cloudflare bypass afeta todos os clientes httpx
**Ficheiro:** `polymarket_clob.py`
**Problema:** O monkey-patch `_httpx.Client.send = _patched_send` afeta bibliotecas externas.
**Fix:** Tornar o patch mais seguro, verificando a instância. Substituir a atribuição global por uma abordagem que altera apenas o cliente em uso, ou simplificar o `_patched_send` para rejeitar não-Polymarket imediatamente. Em `_patched_send`, adicionar como primeira linha:
```python
        if 'polymarket.com' not in url_str:
            return _orig_send(self, request, **kwargs)
```

### Bug 11: Capital nunca atualizado em modo `ordertype == "fixed"`
**Ficheiro:** `backtester.py`
**Problema:** Em modo fixo, `capital += single_pnl` nunca é executado, mantendo o capital em 1000 e destruindo as métricas de Sharpe/Sortino.
**Fix:** Na função `run_backtest`, mover a lógica de atualização de capital para fora do bloco `if ordertype == "percent":`.

Encontrar e remover de dentro do bloco `if ordertype == "percent":` a linha:
```python
                if mode == "single":
                    capital += single_pnl
                else:  # "both"
                    capital += single_pnl
```

E adicioná-la logo acima desse bloco `if`, de forma a correr sempre:
```python
            # Atualizar capital com base no PnL do modo relevante
            if mode == "single":
                capital += single_pnl
            else:
                capital += single_pnl

            if ordertype == "percent":
                # Restante lógica de clipping...
```

### Bug 12: ROI negativo tratado como 0.0
**Ficheiro:** `calibrate_all.py`
**Problema:** A expressão `x or 0.0` transforma ROI `-5.0` em `0.0`.
**Fix:** Na função `_window_choice_score`, substituir:
```python
    return float(score_block.get(key, 0.0) or 0.0)
```
Por:
```python
    val = score_block.get(key, 0.0)
    return float(val) if val is not None else 0.0
```

### Bug 13: `_FakeResponse` não implementa a interface `httpx.Response`
**Ficheiro:** `polymarket_clob.py`
**Problema:** Faltam atributos como `.url` e `.reason_phrase`, o que pode causar `AttributeError` em versões futuras do `py_clob_client_v2`.
**Fix:** Adicionar à classe `_FakeResponse`:
```python
        self.url = ""
        self.method = "GET"
        self.reason_phrase = "OK" if status_code < 400 else "Error"
```

---

## 🟡 MODERATE BUGS

### Bug 14: Inconsistência na definição de "Premature"
**Ficheiro:** `backtester.py`
**Problema:** Backtester define "premature" como "entrou antes E perdeu". Calibrate define como "entrou antes".
**Fix:** Em `backtester.py`, na secção de avaliação fim-de-dia, substituir:
```python
            premature_s = rec["hour"] < peak_h and not single_won
```
Por:
```python
            premature_s = rec["hour"] < peak_h
```

### Bug 15: `SimulatedMarket` partilha RNG na calibração
**Ficheiro:** `calibrate.py`
**Problema:** A mesma instância de RNG é usada para todas as combinações, causando viés dependente da ordem.
**Fix:** Na função `run_grid_search`, mover a criação do `SimulatedMarket` para dentro do loop:
```python
    results = []
    total_combos = len(thresholds) * len(hour_mins)
    with Progress(...) as progress:
        task = progress.add_task("", total=total_combos)

        for thr in thresholds:
            for hmin in hour_mins:
                market_sim = SimulatedMarket(temp_range=city.temp_range, noise_std=0.05, seed=42) if realistic_market else None
                r = simulate_strategy(signals_df, city, thr, hmin,
                                      realistic_market=realistic_market,
                                      market_sim=market_sim)
                results.append(r)
                progress.update(task, advance=1)
```

### Bug 16: `enrich_bracket` sobrescreve preço original da Gamma API
**Ficheiro:** `polymarket_clob.py`
**Problema:** Se o CLOB estiver em baixo, o preço original da API é perdido.
**Fix:** Na função `enrich_bracket`, antes de sobrescrever `b["price"]`, guardar o original:
```python
        b["gamma_price"] = bracket.get("price")
        b["price"] = book.best_ask
```

### Bug 17: Bankroll PAPER é sempre fixo
**Ficheiro:** `live_bot.py`
**Problema:** PnL de trades paper não atualiza o bankroll.
**Fix:** No main loop, após `_tick_city`, adicionar para paper mode:
```python
                    if trading_mode == TradingMode.PAPER:
                        city_bankrolls[city_name] += stats.daily_pnl
```

### Bug 18: `iterrows()` extremamente lento em `train.py`
**Ficheiro:** `train.py`
**Problema:** `_compute_expanding_prior` usa `iterrows()` que é muito lento para grandes datasets.
**Fix:** Substituir o loop interior do `iterrows()` por uma operação vetorizada ou, no mínimo, usar `.itertuples()`:
```python
        for row in year_data.itertuples(index=True):
            idx = row.Index
            key = (int(row.month), int(row.hour), int(row.slot30))
            acc = prior_accumulator.get(key)
            if acc and acc["count"] > 0:
                prior_values.at[idx] = acc["sum"] / acc["count"]
```

### Bug 19: Default de `model_dir` é hardcoded para Munich
**Ficheiro:** `backtester.py`
**Problema:** A função `print_dashboard` tem um fallback perigoso.
**Fix:** Substituir a assinatura:
```python
    model_dir: Path = Path("cities/munich/munich_peak_model"),
```
Por:
```python
    model_dir: Path | None = None,
```
E adicionar no início da função:
```python
    if model_dir is None:
        from predictor import _get_city
        model_dir = Path(_get_city().model_dir)
```

### Bug 20: Anti-duplicado pode setar `strategy_used = None`
**Ficheiro:** `live_bot.py`
**Problema:** `_rec.get("strategy")` pode ser None.
**Fix:** Substituir:
```python
                state.entry.strategy_used = _rec.get("strategy")
```
Por:
```python
                state.entry.strategy_used = _rec.get("strategy") or state.strategy_mode
```

---

## 🔵 MINOR BUGS / CODE QUALITY

### Bug 21: Imports não utilizados em `live_bot.py`
**Ficheiro:** `live_bot.py`
**Fix:** Remover as seguintes linhas não utilizadas:
```python
from datetime import timezone as _tz
import numpy as np
import requests
```

### Bug 22: Docstring de retorno errada em `run_backtest`
**Ficheiro:** `backtester.py`
**Fix:** Alterar a docstring de:
```python
    """Retorna (yearly_dict, capital_history, day_records)."""
```
Para:
```python
    """Retorna (yearly_dict, capital_history, day_records, capital_flow_debug)."""
```

### Bug 23: Coluna inexistente `parcel1_lag_h` em `compute_stats`
**Ficheiro:** `backtester.py`
**Fix:** Substituir:
```python
    lag_col = f"{prefix}_lag_h" if mode == "single" else "parcel1_lag_h"
```
Por (fallback seguro):
```python
    lag_col = f"{prefix}_lag_h"
    if lag_col not in df.columns:
        lag_col = f"{prefix}_lag_h" if mode == "single" else df.filter(like='_lag_h').columns[0]
```

### Bug 24: Template HTML não fornecido referenciado em `web_dashboard.py`
**Ficheiro:** `web_dashboard.py`
**Fix:** Adicionar tratamento de erro em caso de falta do template:
```python
@app.get("/")
def index():
    try:
        return render_template("dashboard.html")
    except Exception:
        return "<h1>Dashboard HTML template missing. API available at /api/snapshot</h1>", 200
```

### Bug 25: Piso de capital artificial em $100
**Ficheiro:** `backtester.py`
**Problema:** Cria rede de segurança irreal no backtest percent.
**Fix:** Substituir:
```python
                capital = max(capital, 100.0)
```
Por:
```python
                capital = max(capital, 0.0)  # Deixar ir a 0 para ser honesto sobre drawdowns
```

### Bug 26: `resolve_closed_positions` é um no-op
**Ficheiro:** `polymarket_clob.py`
**Fix:** Adicionar um `pass` explícito ou log de aviso para deixar claro que é intencional:
```python
    def resolve_closed_positions(self, current_date: date) -> None:
        # Em PAPER a resolução é feita externamente pelo live_bot.
        # Em REAL o refresh() trata disto via API.
        pass
```

### Bug 27: `_compute_prev7_map` usa índices e não dias de calendário
**Ficheiro:** `backtester.py`
**Problema:** Se houver gaps de dados, a média de 7 dias pode abranger mais do que 7 dias reais.
**Fix:** Alterar a lógica do slice para basear-se em datas em vez de índices:
```python
    for i, d in enumerate(dates_list):
        if i == 0:
            prev7[d] = 15.0
        else:
            window_dates = [dd for dd in dates_list if (d - dd).days <= 7 and dd < d]
            window = daily_max[window_dates]
            prev7[d] = float(window.mean()) if len(window) else 15.0
```

### Bug 28: Bare `except` no parsing do Polymarket
**Ficheiro:** `live_bot.py` (e potencialmente `polymarket_clob.py`)
**Problema:** Captura `KeyboardInterrupt` e `SystemExit`.
**Fix:** Substituir todas as ocorrências de `except:` em blocos de JSON parsing por:
```python
            except (json.JSONDecodeError, TypeError, ValueError):
```
```