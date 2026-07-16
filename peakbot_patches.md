# 🔧 PeakBot — Guia de Correções Críticas

> **Data:** 2026-07-16  
> **Versão do projeto analisada:** Multi-cidade (Munich, Dallas, Ankara, etc.)  
> **Severidade:** ⚠️ NÃO executar em modo REAL até aplicar patches #1-#5  

---

## 📋 Índice de Correções

| # | Ficheiro | Bug | Severidade | Linhas |
|---|----------|-----|------------|--------|
| 1 | `backtester.py` | Look-ahead bias em batch predictions | **CRÍTICO** | ~520-570 |
| 2 | `live_bot.py` | Corrupção permanente do threshold (EOD) | **CRÍTICO** | ~1101-1122 |
| 3 | `live_bot.py` | Double-processing em Race Mode | **CRÍTICO** | ~1972-1997 |
| 4 | `backtester.py` | Cálculo errado de fees em wins | **CRÍTICO** | ~260-275 |
| 5 | `backtester.py` | Capital clipping esconde drawdown | **CRÍTICO** | ~580-590 |
| 6 | `live_bot.py` | Race condition no anti-duplicado | SÉRIO | ~1040-1080 |
| 7 | `live_bot.py` | Falta validação de saldo | SÉRIO | ~1145-1150 |
| 8 | `weather.py` | Timezone bug no `ceil_slot` | SÉRIO | ~630-640 |
| 9 | `weather.py` | Memory leak no bootstrap cache | SÉRIO | ~40-45 |
| 10 | `weather.py` | Falta rate limiting WU | SÉRIO | ~280-320 |
| 11 | `tg.py` | Thread safety nos alerts | MÉDIO | — |
| 12 | `live_bot.py` | `_stop_loss_blocked_alerted` não resetado | MÉDIO | ~1325-1380 |

---

---

## PATCH #1 — Look-Ahead Bias no Backtester ⭐ CRÍTICO

### Ficheiro: `backtester.py`
### Problema
O backtester pré-computa predições em **batch para o dia inteiro** antes de simular o loop temporal. Quando avalia o slot das 10h, o modelo já "viu" os dados das 15h — invalidando completamente o backtest.

### Código Problemático (linhas ~520-570)
```python
# ❌ PROBLEMA: Precomputar predições em batch para o dia inteiro
features_list = []
valid_indices = []
for idx, (_, row) in enumerate(day_df.iterrows()):
    # ... constroi features ...
    feat = build_features(day_slots_prep.copy(), current_extra, ...)
    features_list.append([feat.get(col, 0.0) for col in models["feat_cols"]])
    valid_indices.append(idx)

p_ens_list = [0.0] * len(day_df)
if features_list:
    X_batch = np.array(features_list, dtype=np.float32)
    preds = models["model_lgb"].predict_proba(X_batch)[:, 1]  # ← VÊ O FUTURO!
    for p_idx, val_idx in enumerate(valid_indices):
        p_ens_list[val_idx] = float(np.clip(preds[p_idx], 0.0, 1.0))
```

### Solução: Predição Sequencial
Substituir o bloco de precomputação batch (aprox. linhas 520-570) por:

```python
# ✅ CORREÇÃO: Predizer um slot de cada vez, usando só dados disponíveis
p_ens_list = [0.0] * len(day_df)

for idx_in_day, (_, row) in enumerate(day_df.iterrows()):
    h = int(row["hour"])
    s = int(row["slot30"])

    if h < city.day_start or len(slots_so_far) < 4 or h < hour_min:
        slots_so_far.append({
            "hour": h, "slot30": s, "temp_c": float(row["temp_c"]),
            "humidity": float(row["humidity"]),
            "cloud_cover": float(row["cloud_cover"]),
            "dewpoint_c": float(row["dewpoint_c"]),
            "pressure_hpa": float(row["pressure_hpa"]),
            "wind_dir_deg": float(row["wind_dir_deg"]),
            "wind_speed_kmh": float(row["wind_speed_kmh"]),
            "wind_gust_kmh": float(row["wind_gust_kmh"]),
            "uv_index": float(row["uv_index"]),
        })
        continue

    # ✅ Predizer APENAS com dados até este slot
    current_extra = {
        "hour": h, "slot30": s, "temp_c": float(row["temp_c"]),
        "humidity": float(row["humidity"]),
        "cloud_cover": float(row["cloud_cover"]),
        "dewpoint_c": float(row["dewpoint_c"]),
        "pressure_hpa": float(row["pressure_hpa"]),
        "wind_dir_deg": float(row["wind_dir_deg"]),
        "wind_speed_kmh": float(row["wind_speed_kmh"]),
        "wind_gust_kmh": float(row["wind_gust_kmh"]),
        "uv_index": float(row["uv_index"]),
        "prev_7d_avg_max": prev7_map.get(d, 15.0),
    }

    feat = build_features(slots_so_far.copy(), current_extra, month, doy, 
                        models.get("prior_map", {}))
    X = np.array([[feat.get(col, 0.0) for col in models["feat_cols"]]], 
                 dtype=np.float32)
    p_ens_list[idx_in_day] = float(np.clip(
        models["model_lgb"].predict_proba(X)[:, 1][0], 0.0, 1.0
    ))

    # Adicionar este slot para o próximo
    slots_so_far.append({
        "hour": h, "slot30": s, "temp_c": float(row["temp_c"]),
        "humidity": float(row["humidity"]),
        "cloud_cover": float(row["cloud_cover"]),
        "dewpoint_c": float(row["dewpoint_c"]),
        "pressure_hpa": float(row["pressure_hpa"]),
        "wind_dir_deg": float(row["wind_dir_deg"]),
        "wind_speed_kmh": float(row["wind_speed_kmh"]),
        "wind_gust_kmh": float(row["wind_gust_kmh"]),
        "uv_index": float(row["uv_index"]),
    })
```

### Notas de Implementação
- **Impacto de performance:** O backtest fica ~10x mais lento (uma predição por slot vs. uma por dia). Para acelerar, considerar cache de features entre slots consecutivos.
- **Validação:** Após aplicar, o AUC walk-forward deve descer ligeiramente (o anterior estava inflacionado).
- **Teste:** Correr backtest com `--noise 0` antes e depois. O win-rate deve descer 5-15%.

---

---

## PATCH #2 — Corrupção Permanente do Threshold (EOD Fallback) ⭐ CRÍTICO

### Ficheiro: `live_bot.py`
### Problema
O EOD fallback baixa temporariamente o `threshold`, mas a restauração só acontece se `_eod_active` for True. Se `p_ensemble < fallback_thr`, o threshold **nunca é restaurado**.

### Análise do Bug
O `_original_threshold_for_restore` é uma **variável local** reinicializada a `None` no início de cada tick. Se no tick T o EOD ativa, o threshold é baixado. No tick T+1, se o EOD **não** ativa, a variável local é `None` novamente, mas o `state.entry.threshold` **permanece baixo** do tick anterior porque nunca foi restaurado!

### Solução: Guardar Threshold Original no Estado Persistente

**Passo 1:** Adicionar campo ao `CityState` (aprox. linha 220):
```python
@dataclass
class CityState:
    # ... campos existentes ...
    _original_threshold: Optional[float] = None  # ✅ NOVO
```

**Passo 2:** Substituir o bloco EOD (linhas ~1096-1133):
```python
# ✅ CORREÇÃO: EOD Fallback com restauração garantida
# Guardar threshold original na primeira vez que EOD se aplica
if (state.force_eod_trade
    and not state.entry.bought
    and h_cur >= city.day_end - state.eod_start_hours_before_close
    and p_ensemble > 0.0):

    current_thr = float(getattr(state.entry, 'threshold', 0.65) or 0.65)
    fallback_thr = current_thr * state.eod_fallback_threshold

    if p_ensemble >= fallback_thr:
        # ✅ Guardar threshold original no estado persistente (só 1x)
        if state._original_threshold is None:
            state._original_threshold = current_thr
            print(f"  {C['yellow']}{city.name.upper()} EOD FALLBACK: "
                  f"thr {current_thr:.2f}→{fallback_thr:.2f}, "
                  f"p={p_ensemble:.2f}, h={h_cur}{R}")
            # Avisar via Telegram (uma vez por dia)
            if state.last_target_bracket:
                _bracket_lbl = state.last_target_bracket.get('label', '?')
                _bracket_ask = state.last_target_bracket.get('ask') or state.last_target_bracket.get('price', 0)
                tg_eod = _get_tg()
                if tg_eod:
                    try:
                        _tg_thread(
                            tg_eod.alert_eod_fallback,
                            city.name, p_ensemble, fallback_thr, current_thr,
                            _bracket_lbl, _bracket_ask,
                        )
                    except Exception:
                        pass

        state.entry.threshold = fallback_thr
        _eod_active = True
    else:
        print(f"  {DIM}{city.name.upper()} EOD: p={p_ensemble:.2f} < "
              f"fallback={fallback_thr:.2f} (ainda sem forçar){R}")
```

**Passo 3:** Substituir a restauração (linhas ~1318-1323):
```python
# ✅ CORREÇÃO: Restaurar threshold no reset diário ou quando compra
# No reset diário (onde state._last_date é atualizado):
if city_today != state._last_date:
    # ... código existente de reset ...
    # ✅ Restaurar threshold se estava em EOD
    if state._original_threshold is not None:
        if state.entry:
            state.entry.threshold = state._original_threshold
        state._original_threshold = None
        print(f"  {C['cyan']}{city.name}: threshold restaurado para "
              f"{state.entry.threshold if state.entry else '?'}{R}")

# ✅ Também restaurar quando compra com sucesso:
# No bloco de processamento de buy (após result.success):
if result.success:
    # ... código existente ...
    # ✅ Restaurar threshold original após compra
    if state._original_threshold is not None:
        state.entry.threshold = state._original_threshold
        state._original_threshold = None
        print(f"  {C['cyan']}{city.name}: threshold restaurado após "
              f"compra EOD{R}")
```

### Notas
- O threshold só deve ser guardado uma vez por dia (na primeira vez que EOD ativa).
- A restauração deve acontecer no reset diário **ou** após compra bem-sucedida.
- Remover o bloco de restauração antigo (linhas ~1318-1323) pois já não é necessário.

---

---

## PATCH #3 — Double-Processing em Race Mode ⭐ CRÍTICO

### Ficheiro: `live_bot.py`
### Problema
O Race Mode chama `_tick_city()` recursivamente sem proteção de re-entrada. A mesma cidade pode ser processada 2x no mesmo ciclo, potencialmente duplicando bets.

### Código Problemático (linhas ~1989-1997)
```python
# ❌ PROBLEMA: Re-entrada sem proteção
s.entry.threshold = race_thr
# ...
try:
    city_bankroll_race = city_bankrolls.get(cn, PARCEL_SIZE * 100)
    _tick_city(s, args.run, city_bankroll_race)  # ← RECURSÃO!
finally:
    s.entry.threshold = original_thr
```

### Solução: Flag de Re-entrada no CityState

**Passo 1:** Adicionar flag ao `CityState` (aprox. linha 220):
```python
@dataclass
class CityState:
    # ... campos existentes ...
    _in_tick: bool = False  # ✅ NOVO: proteção de re-entrada
```

**Passo 2:** Modificar `_tick_city` (início da função, aprox. linha 900):
```python
def _tick_city(state: CityState, trading_mode_str: str, bankroll: float) -> DailyStats:
    # ✅ CORREÇÃO: Proteção de re-entrada
    if state._in_tick:
        print(f"  {C['yellow']}{state.city.name}: SKIP — tick já em "
              f"execução (re-entrada bloqueada){R}")
        return state.daily_stats or DailyStats(date=city_date(state.city))

    state._in_tick = True
    try:
        # ... TODO O CÓDIGO EXISTENTE DA FUNÇÃO ...

        # No final, antes do return:
        return stats
    finally:
        state._in_tick = False
```

**Passo 3:** O Race Mode já pode chamar `_tick_city` em segurança — a segunda chamada será ignorada se a primeira ainda estiver em execução.

### Notas
- Em Python (GIL), duas threads não executam código Python simultaneamente, mas o Race Mode corre na **mesma thread** (loop principal), então a re-entrada é síncrona.
- A flag `_in_tick` previne re-entrada síncrona (recursão) e assíncrona (threads futuras).

---

---

## PATCH #4 — Cálculo Errado de Fees em Wins ⭐ CRÍTICO

### Ficheiro: `backtester.py`
### Problema
A fee do Polymarket é de **2% sobre o payout total**, não sobre o lucro. O código subestima o impacto das fees.

### Código Problemático (linhas ~260-275)
```python
# ❌ PROBLEMA: Fee sobre lucro, não sobre payout
def _pnl_per_dollar(ask: float, won: bool, size_usdc: float = 5.0) -> float:
    shares = math.floor(size_usdc / ask)
    actual_invested = shares * ask
    if won:
        gross = float(shares) - actual_invested  # ← Lucro, não payout
        return gross - abs(gross) * TAKER_FEE_RATE  # ← Fee sobre lucro
    gross = -actual_invested
    return gross - abs(gross) * TAKER_FEE_RATE
```

### Solução: Fee sobre Payout Total
```python
# ✅ CORREÇÃO: Fee sobre payout total (comportamento real Polymarket)
def _pnl_per_dollar(ask: float, won: bool, size_usdc: float = 5.0) -> float:
    if not ask or ask <= 0:
        return 0.0
    shares = math.floor(size_usdc / ask)
    if shares <= 0:
        return 0.0
    actual_invested = shares * ask

    if won:
        # ✅ Payout total = shares * 1.0 (cada share vale $1 se ganhar)
        # Fee = 2% do payout total
        payout_gross = shares * 1.0
        fee = payout_gross * TAKER_FEE_RATE
        net_payout = payout_gross - fee
        return net_payout - actual_invested
    else:
        # Perda total do investido (não há fee em perdas no Polymarket)
        return -actual_invested
```

### Verificação
- Ask = 0.10, Size = $5 → Shares = 50
- **Antigo:** gross = 50 - 5 = 45, fee = 0.90, net = 44.10, ROI = +882%
- **Novo:** payout = 50, fee = 1.00, net_payout = 49, PnL = 44.00, ROI = +880%
- Diferença parece pequena, mas em asks altos (0.80) a distorção é maior:
  - **Antigo:** gross = 6.25 - 5 = 1.25, fee = 0.025, net = 1.225
  - **Novo:** payout = 6.25, fee = 0.125, net_payout = 6.125, PnL = 1.125

### Notas
- No Polymarket real, a fee é cobrada no **settlement** (quando o mercado resolve), não no lucro.
- Perdas não pagam fee (o investimento é perdido integralmente).

---

---

## PATCH #5 — Capital Clipping Esconde Drawdown ⭐ CRÍTICO

### Ficheiro: `backtester.py`
### Problema
O clipping `capital = max(capital, 0.0)` esconde o drawdown real. O aviso menciona $100 mas o código clipa a $0.

### Código Problemático (linhas ~580-590)
```python
# ❌ PROBLEMA: Clipping a $0, não $100. E o aviso diz $100.
cap_before = capital
capital += single_pnl
capital_after_pnl = capital
capital = max(capital, 0.0)  # ← Deveria ser max(capital, 100.0) ou remover
```

### Solução: Remover Clipping ou Implementar Floor Real

**Opção A — Remover clipping (recomendado para backtest honesto):**
```python
# ✅ CORREÇÃO: Remover clipping — deixar capital ir negativo
# Isso mostra o drawdown real
# ... no bloco de avaliação fim-de-dia ...

cap_before = capital
capital += single_pnl
# ✅ REMOVER: capital = max(capital, 0.0)

# Adicionar tracking de drawdown real
capital_history.append((d, capital))

# No dashboard, mostrar métricas sobre investido, não sobre capital
# (já é feito parcialmente, mas enfatizar)
```

**Opção B — Implementar floor de $100 (se quiser simular stop de trading):**
```python
# ✅ ALTERNATIVA: Floor de $100 com "quebra" do bot
FLOOR_CAPITAL = 100.0

cap_before = capital
capital += single_pnl

if capital < FLOOR_CAPITAL:
    # Bot "quebra" — não trade mais neste backtest
    capital = FLOOR_CAPITAL
    # Adicionar flag para parar de trade
    # ... (requer mais mudanças)
```

### Notas
- **Recomendo Opção A** para backtester. O capital simulado deve refletir a realidade.
- O ROI honesto é `PnL% / Invested%` (já calculado na tabela RESUMO TOTAL).
- O gráfico de capital em `--ordertype percent` deve mostrar drawdowns reais.

---

---

## PATCH #6 — Race Condition no Anti-Duplicado SÉRIO

### Ficheiro: `live_bot.py`
### Problema
O anti-duplicado verifica ficheiro JSON e CLOB positions sem lock. Em race mode, dois ticks podem verificar simultaneamente antes de qualquer um escrever.

### Solução: Lock por Ficheiro

**Passo 1:** Adicionar função de lock (novo bloco no início do ficheiro):
```python
import fcntl  # ✅ NOVO: para file locking (Unix)
import os

LOCK_DIR = Path("live_bot_logs/locks")
LOCK_DIR.mkdir(exist_ok=True)

def _acquire_city_lock(city_name: str, timeout: float = 5.0):
    """Adquire lock exclusivo para uma cidade."""
    lock_path = LOCK_DIR / f"{city_name}.lock"
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fd  # Guardar fd para libertar depois
    except (IOError, OSError):
        return None

def _release_city_lock(fd) -> None:
    """Liberta lock da cidade."""
    if fd is not None:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
```

**Passo 2:** Modificar `_tick_city` para usar lock:
```python
def _tick_city(state: CityState, trading_mode_str: str, bankroll: float) -> DailyStats:
    # ✅ Adquirir lock
    lock_fd = _acquire_city_lock(state.city.name)
    if lock_fd is None:
        print(f"  {C['yellow']}{state.city.name}: SKIP — lock não "
              f"disponível (outro tick em execução?){R}")
        return state.daily_stats or DailyStats(date=city_date(state.city))

    try:
        # ... TODO O CÓDIGO EXISTENTE ...
        return stats
    finally:
        _release_city_lock(lock_fd)
```

### Notas
- O lock por ficheiro funciona mesmo entre processos (útil se correr múltiplas instâncias).
- Em Windows, substituir `fcntl` por `msvcrt` ou usar `filelock` (pip install filelock).

---

---

## PATCH #7 — Falta de Validação de Saldo SÉRIO

### Ficheiro: `live_bot.py`
### Problema
O código aceita `action["size_usdc"]` sem verificar se há saldo suficiente.

### Solução: Verificar Saldo Antes de Comprar

**No bloco de processamento de buy (aprox. linha 1145):**
```python
for action in actions:
    if action.get("size_usdc", 0) > 0:
        # ✅ CORREÇÃO: Validar saldo
        bet_size = action["size_usdc"]

        # Verificar saldo disponível
        available_balance = bankroll
        if trading_mode_str == "real" and state.clob:
            try:
                available_balance = state.clob.get_usdc_balance() or bankroll
            except Exception:
                available_balance = bankroll

        if bet_size > available_balance:
            print(f"  {C['yellow']}{city.name.upper()} BUY BLOQUEADO: "
                  f"bet ${bet_size:.2f} > saldo ${available_balance:.2f}{R}")
            _tg_alert(
                f"🚫 <b>{city.name.title()}</b> buy bloqueado: "
                f"bet ${bet_size:.2f} > saldo ${available_balance:.2f}"
            )
            break

        # Continuar com o buy...
        bracket = action.get("bracket") or state.last_target_bracket
```

### Notas
- Em modo REAL, usar o saldo real da carteira.
- Em modo PAPER, usar o `bankroll` simulado.
- Considerar reservar uma margem de segurança (ex: 95% do saldo).

---

---

## PATCH #8 — Timezone Bug no `ceil_slot` SÉRIO

### Ficheiro: `weather.py`
### Problema
`ceil_slot(23, 45)` retorna `(23, 30)` em vez de `(0, 0)` do dia seguinte, ou rejeitar.

### Código Problemático (linhas ~630-640)
```python
def ceil_slot(hour: int, minute: int) -> tuple[int, int]:
    if minute < 30:
        return (hour, 30)
    h = hour + 1
    if h == 24:
        return (23, 30)  # ❌ Deveria ser (0, 0) do dia seguinte
    return (h, 0)
```

### Solução: Retornar Flag de "Próximo Dia"
```python
from typing import Tuple

def ceil_slot(hour: int, minute: int) -> Tuple[int, int, bool]:
    """
    Converte (hour, minute) para slot 30min.
    Retorna (slot_hour, slot_minute, is_next_day).
    """
    if minute < 30:
        return (hour, 30, False)
    h = hour + 1
    if h >= 24:
        return (0, 0, True)  # ✅ Próximo dia
    return (h, 0, False)
```

**E atualizar todos os callers:**
```python
# Em bootstrap_today e outros:
h2, s2, is_next = ceil_slot(h, m)
if is_next:
    continue  # Ignorar slots do dia seguinte
```

### Notas
- O bug atual causa slots duplicados (23:30 aparece 2x) ou dados do dia seguinte misturados.
- Verificar todos os callers de `ceil_slot` no projeto.

---

---

## PATCH #9 — Memory Leak no Bootstrap Cache SÉRIO

### Ficheiro: `weather.py`
### Problema
`_bootstrap_rows_cache` e `_bootstrap_obs_min` nunca são limpos.

### Solução: LRU Cache com Limite

**Substituir as globais (aprox. linhas 40-45):**
```python
from collections import OrderedDict

# ✅ CORREÇÃO: LRU cache com limite de 7 dias
MAX_CACHE_DAYS = 7
_bootstrap_rows_cache: OrderedDict[str, list] = OrderedDict()
_bootstrap_obs_min: OrderedDict[str, dict] = OrderedDict()

def _cache_set(city_name: str, rows: list, obs_min: dict) -> None:
    """Guarda no cache com eviction LRU."""
    global _bootstrap_rows_cache, _bootstrap_obs_min

    # Evict oldest if at capacity
    while len(_bootstrap_rows_cache) >= MAX_CACHE_DAYS:
        oldest = next(iter(_bootstrap_rows_cache))
        del _bootstrap_rows_cache[oldest]
        del _bootstrap_obs_min[oldest]

    _bootstrap_rows_cache[city_name] = rows
    _bootstrap_obs_min[city_name] = obs_min

def _cache_get(city_name: str):
    """Lê do cache e move para o fim (LRU)."""
    if city_name not in _bootstrap_rows_cache:
        return None
    # Move to end (most recently used)
    _bootstrap_rows_cache.move_to_end(city_name)
    _bootstrap_obs_min.move_to_end(city_name)
    return (_bootstrap_rows_cache[city_name], _bootstrap_obs_min[city_name])
```

---

---

## PATCH #10 — Rate Limiting nas Chamadas WU SÉRIO

### Ficheiro: `weather.py`
### Problema
Sem retry ou backoff nas chamadas à API WU.

### Solução: Decorator de Retry

```python
import time
from functools import wraps

def retry_with_backoff(max_retries=3, base_delay=1.0):
    """Decorator para retry com backoff exponencial."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except (requests.exceptions.Timeout, 
                        requests.exceptions.ConnectionError) as e:
                    if attempt == max_retries - 1:
                        raise
                    delay = base_delay * (2 ** attempt)
                    print(f"  [WU] Retry {attempt + 1}/{max_retries} "
                          f"após {delay:.1f}s...")
                    time.sleep(delay)
            return None
        return wrapper
    return decorator

# Aplicar aos fetchers:
@retry_with_backoff(max_retries=3, base_delay=2.0)
def fetch_wu_day(city, day, api_key, session):
    # ... código existente ...

@retry_with_backoff(max_retries=3, base_delay=1.0)
def fetch_wu_latest(city, api_key, session):
    # ... código existente ...
```

---

---

## PATCH #11 — Thread Safety nos Alerts Telegram MÉDIO

### Ficheiro: `tg.py`
### Problema
Os alerts usam daemon threads — se o main thread crashar, os alerts em voo são perdidos.

### Solução: Queue com Worker Thread

```python
import queue
import threading

class TG:
    def __init__(self):
        # ... código existente ...
        self._msg_queue = queue.Queue()  # ✅ NOVO
        self._worker_thread = threading.Thread(target=self._worker, daemon=True)
        self._worker_thread.start()

    def _worker(self):
        """Worker thread que consome a queue."""
        while True:
            try:
                text = self._msg_queue.get(timeout=1.0)
                if text is None:  # Sinal de shutdown
                    break
                self._send_sync(text)
            except queue.Empty:
                continue
            except Exception as e:
                print(f"  [TG] Worker error: {e}")

    def _send_sync(self, text: str) -> bool:
        """Envio síncrono (chamado apenas pelo worker)."""
        # ... código existente do send() ...

    def send(self, text: str) -> bool:
        """Envio assíncrono via queue."""
        if not self.enabled:
            return False
        try:
            self._msg_queue.put(text, block=False)
            return True
        except queue.Full:
            print("  [TG] Queue full — mensagem descartada")
            return False

    def stop(self):
        """Shutdown graceful."""
        self._msg_queue.put(None)
        self._worker_thread.join(timeout=5.0)
```

---

---

## PATCH #12 — `_stop_loss_blocked_alerted` Não Resetado MÉDIO

### Ficheiro: `live_bot.py`
### Problema
O flag `_stop_loss_blocked_alerted` impede spam de alerts, mas não é resetado quando a condição muda.

### Solução: Resetar em Condições Apropriadas

**No reset diário (aprox. linha 940):**
```python
if city_today != state._last_date:
    # ... código existente ...
    # ✅ Resetar flag de stop-loss
    if state.entry and hasattr(state.entry, '_stop_loss_blocked_alerted'):
        state.entry._stop_loss_blocked_alerted = False
```

**Também resetar após compra bem-sucedida:**
```python
# Após result.success no bloco de buy:
if result.success:
    # ... código existente ...
    # ✅ Resetar flag de stop-loss para permitir novos alerts
    if hasattr(state.entry, '_stop_loss_blocked_alerted'):
        state.entry._stop_loss_blocked_alerted = False
```

---

---

## 🧪 Testes de Validação Pós-Patch

Após aplicar os patches, executar:

```bash
# 1. Backtester — verificar se look-ahead bias foi removido
python backtester.py --city munich --mode single --years 3 --noise 0.05
# O win-rate deve descer 5-15% em relação ao anterior

# 2. Live bot — testar EOD fallback em modo PAPER
python live_bot.py --cities munich --mode single --run paper \
    --force-eod-trade --eod-fallback-threshold 0.5 \
    --interval 30 --tg-interval 1800
# Verificar que o threshold é restaurado no dia seguinte

# 3. Race mode — testar com 2+ cidades
python live_bot.py --cities munich,dallas --mode single --run paper \
    --race-top-k 2 --race-min-threshold 0.50
# Verificar que não há double-processing

# 4. Weather — testar bootstrap
python -c "from weather import ceil_slot; print(ceil_slot(23, 45))"
# Deve retornar (0, 0, True) ou equivalente
```

---

---

## 📁 Checklist de Aplicação

- [ ] **PATCH #1** — Look-ahead bias no backtester
- [ ] **PATCH #2** — Corrupção do threshold EOD
- [ ] **PATCH #3** — Double-processing Race Mode
- [ ] **PATCH #4** — Cálculo de fees
- [ ] **PATCH #5** — Capital clipping
- [ ] **PATCH #6** — Race condition anti-duplicado
- [ ] **PATCH #7** — Validação de saldo
- [ ] **PATCH #8** — Timezone ceil_slot
- [ ] **PATCH #9** — Memory leak bootstrap
- [ ] **PATCH #10** — Rate limiting WU
- [ ] **PATCH #11** — Thread safety Telegram
- [ ] **PATCH #12** — Reset stop-loss flag

---

> **⚠️ AVISO:** Não executar em modo REAL até todos os patches CRÍTICOS (#1-#5) estarem aplicados e validados.
