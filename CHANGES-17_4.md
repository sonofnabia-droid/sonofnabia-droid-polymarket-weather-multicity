Changes_17_4.md
Instruções para Claude Code executar os fixes
FIX 1: PnL usa custo real em vez de size_usdc (Bug 4)
Ficheiro: backtester.pyFunção: _pnl_per_dollar

Substituir:

def _pnl_per_dollar(ask: float, won: bool, size_usdc: float = 5.0) -> float:    if not ask or ask <= 0:        return 0.0    shares = math.floor(size_usdc / ask)    if shares <= 0:        return 0.0    invested = size_usdc    if won:        gross = float(shares) - invested        return gross - abs(gross) * TAKER_FEE_RATE    return -invested
Por:

python

def _pnl_per_dollar(ask: float, won: bool, size_usdc: float = 5.0) -> float:
    """
    PnL realista Polymarket.
    O utilizador pede size_usdc (ex: $5.00), mas só compra shares inteiros.
    O custo REAL é shares * ask (ex: 10 * $0.47 = $4.70).
    O "resto" fica em cash e NÃO é investido.
    """
    if not ask or ask <= 0:
        return 0.0
    shares = math.floor(size_usdc / ask)
    if shares <= 0:
        return 0.0
    actual_invested = shares * ask  # Custo real (pode ser < size_usdc)
    if won:
        # Recebe $1.00 por share, fee de 2% sobre o lucro
        gross_profit = float(shares) - actual_invested
        return gross_profit - abs(gross_profit) * TAKER_FEE_RATE
    # Perda: perde-se apenas o investido, sem fee adicional
    return -actual_invested
FIX 2: Stop-loss PnL usa custo real (Bug 10)
Ficheiro: backtester.py
Localização: Dentro de run_backtest(), no bloco if stop_signal:

Substituir:

python

entry_ask = pos["ask"]
shares = math.floor(pos["size_usdc"] / entry_ask) if entry_ask > 0 else 0
invested = pos["size_usdc"]  # ← ERRADO
recovered = shares * sell_bid
realized_pnl = recovered - invested
Por:

python

entry_ask = pos["ask"]
shares = math.floor(pos["size_usdc"] / entry_ask) if entry_ask > 0 else 0
actual_invested = shares * entry_ask if entry_ask > 0 else 0.0  # ← CORRIGIDO
recovered = shares * sell_bid
realized_pnl = recovered - actual_invested
FIX 3: Flag _stop_loss_blocked_alerted não é sobrescrito (Bug 11)
Ficheiro: live_bot.py
Localização: No bloco anti-duplicado, após if sl_check:

Encontrar este bloco:

python

if sl_check:
    state.entry.sold_by_stop = True
    state.entry.record["sold_by_stop"] = True
    if hasattr(state.entry, '_stop_loss_blocked_alerted'):
        state.entry._stop_loss_blocked_alerted = True
    print(f"  {C['yellow']}{city.name}: stop-loss já disparado antes do restart — marcando como vendida{R}")

if hasattr(state.entry, '_stop_loss_blocked_alerted'):
    state.entry._stop_loss_blocked_alerted = False
Substituir por:

python

if sl_check:
    state.entry.sold_by_stop = True
    state.entry.record["sold_by_stop"] = True
    if hasattr(state.entry, '_stop_loss_blocked_alerted'):
        state.entry._stop_loss_blocked_alerted = True
    print(f"  {C['yellow']}{city.name}: stop-loss já disparado antes do restart — marcando como vendida{R}")
else:
    # Só resetar o flag se NÃO foi triggerado antes do restart
    if hasattr(state.entry, '_stop_loss_blocked_alerted'):
        state.entry._stop_loss_blocked_alerted = False
FIX 4: series_today actualizado quando chega nova obs (Bug 1)
Ficheiro: live_bot.py
Localização: No bloco que actualiza slots_so_far com nova observação

Encontrar o bloco que começa com:

python

exists = any(s["hour"] == h_slot and s["slot30"] == s30 for s in state.slots_so_far)
if exists:
    # ... actualiza slot existente ...
else:
    state.slots_so_far.append(slot_entry)
    state.slots_so_far.sort(key=lambda x: x["hour"] * 60 + x["slot30"])
Substituir TODO este bloco por:

python

exists = any(s["hour"] == h_slot and s["slot30"] == s30 for s in state.slots_so_far)
if exists:
    current_rmax = max(s["temp_c"] for s in state.slots_so_far) if state.slots_so_far else None
    latest_slot_key = max(
        (int(s["hour"]) * 60 + int(s.get("slot30", 0)) for s in state.slots_so_far),
        default=None,
    )
    new_slot_key = h_slot * 60 + s30
    for s in state.slots_so_far:
        if s["hour"] == h_slot and s["slot30"] == s30:
            if (
                state.entry and state.entry.bought
                and latest_slot_key is not None
                and new_slot_key < latest_slot_key
                and current_rmax is not None
                and slot_entry["temp_c"] > current_rmax
            ):
                print(
                    f"  {C['yellow']}{city.name}: clamped late high temp "
                    f"at {h_slot:02d}:{s30:02d}{R}"
                )
                s["temp_c_real"] = slot_entry["temp_c"]
                slot_entry["temp_c"] = s["temp_c"]
            else:
                s["temp_c_real"] = slot_entry["temp_c"]
            s["date"] = city_today
            s["temp_c"] = slot_entry["temp_c"]
            if "hour" in slot_entry:
                s["hour"] = slot_entry["hour"]
            if "slot30" in slot_entry:
                s["slot30"] = slot_entry["slot30"]
            for key in (
                "cloud_cover", "humidity", "dewpoint_c", "pressure_hpa",
                "wind_dir_deg", "wind_speed_kmh", "wind_gust_kmh", "uv_index",
            ):
                if key in new_obs and new_obs[key] is not None:
                    s[key] = slot_entry[key]
            # FIX: actualizar series_today para slot existente
            for key in list(state.series_today.keys()):
                if key[0] == h_slot and key[1] == s30:
                    state.series_today[key] = s["temp_c"]
            break
else:
    state.slots_so_far.append(slot_entry)
    state.slots_so_far.sort(key=lambda x: x["hour"] * 60 + x["slot30"])
    # FIX: adicionar a series_today para novo slot
    new_idx = len(state.slots_so_far) - 1
    state.series_today[(h_slot, s30, new_idx)] = slot_entry["temp_c"]
FIX 5: Date parsing US removido (Bug 2)
Ficheiro: live_bot.py
Função: _settle_paper_positions_for_day > _peak_for_date

Substituir:

python

target_keys = {
    target_day.strftime("%Y-%m-%d"),  # ISO 8601
    target_day.strftime("%d/%m/%Y"),  # EU
    target_day.strftime("%m/%d/%Y"),  # US
}
Por:

python

target_keys = {
    target_day.strftime("%Y-%m-%d"),  # ISO 8601
    target_day.strftime("%d/%m/%Y"),  # EU (formato mais comum nos dados)
}
FIX 6: Lock adquirido em operações críticas (Bug 3)
Ficheiro: live_bot.py
Função: _tick_city

No INÍCIO da função _tick_city, logo após a linha:

python

city_today = city_date(city)
Adicionar:

python

with state._lock:
E no FINAL da função, antes do return stats, adicionar (com indentação correcta):

python

    return stats  # indentado dentro do with block
Nota: Todo o corpo da função precisa de ser indentado mais um nível. Se isso for muito invasivo, alternativa mais segura — proteger apenas as escritas críticas:

Encontrar estas linhas e envolver cada uma com with state._lock::

state.slots_so_far.append(slot_entry) e state.series_today[...]
state.market = state.fetcher.fetch_market(city_today)
state.entry.restore(_rec, ...) ou state.entry.bought = True
FIX 7: hour_min calculado uma vez (Bug 14)
Ficheiro: backtester.py
Função: run_backtest

Encontrar (aparece DUAS vezes):

python

hour_min = city.hour_min if city.hour_min is not None else 6
Mover para ANTES do loop for d, day_df in df.groupby("date"):, logo após:

python

sim_mkt = SimulatedMarket(temp_range=city.temp_range, noise_std=noise_std)
prev7_map = _compute_prev7_map(df, city)
Adicionar:

python

hour_min = city.hour_min if city.hour_min is not None else 6
E REMOVER as duas ocorrências dentro dos loops.

FIX 8: Remover código morto (Bugs 13, 15, 16, 17)
Ficheiro: live_bot.py

Remover campo _last_stats_save do dataclass CityState (não é usado)
Remover import não usado:
python

from predictor import update_history_max, init_history_max
Substituir por:

python

from predictor import update_history_max
Remover hasattr redundante:
python

if not hasattr(state, '_last_date'):
    state._last_date = city_today
Substituir por (nada — o campo já está inicializado no dataclass)

FIX 9: Unificar lógica de slots no backtester (Bug 6)
Ficheiro: backtester.py
Função: run_backtest

Substituir os DOIS loops (batch prediction + execução) por um único loop que constrói slots uma vez:

python

# Construir todos os slots do dia uma vez
all_day_slots = []
for _, row in day_df.iterrows():
    h = int(row["hour"])
    s = int(row["slot30"])
    t = float(row["temp_c"])
    all_day_slots.append({
        "hour": h, "slot30": s, "temp_c": t,
        "humidity": float(row["humidity"]),
        "cloud_cover": float(row["cloud_cover"]),
        "dewpoint_c": float(row["dewpoint_c"]),
        "pressure_hpa": float(row["pressure_hpa"]),
        "wind_dir_deg": float(row["wind_dir_deg"]),
        "wind_speed_kmh": float(row["wind_speed_kmh"]),
        "wind_gust_kmh": float(row["wind_gust_kmh"]),
        "uv_index": float(row["uv_index"]),
    })

# Batch prediction
p_ens_list = [0.0] * len(all_day_slots)
features_list = []
valid_indices = []
slots_so_far_batch = []
for idx, slot in enumerate(all_day_slots):
    h = slot["hour"]
    slots_so_far_batch.append(slot)
    if h < city.day_start or len(slots_so_far_batch) < 4 or h < hour_min:
        continue
    current_extra = {**slot, "prev_7d_avg_max": prev7_map.get(d, 15.0)}
    feat = build_features(slots_so_far_batch.copy(), current_extra, month, doy, models.get("prior_map", {}))
    features_list.append([feat.get(col, 0.0) for col in models["feat_cols"]])
    valid_indices.append(idx)

if features_list:
    X_batch = np.array(features_list, dtype=np.float32)
    preds = models["model_lgb"].predict_proba(X_batch)[:, 1]
    for p_idx, val_idx in enumerate(valid_indices):
        p_ens_list[val_idx] = float(np.clip(preds[p_idx], 0.0, 1.0))

# Execução
slots_so_far = []
for idx_in_day, slot in enumerate(all_day_slots):
    h = slot["hour"]
    s = slot["slot30"]
    t = slot["temp_c"]
    slots_so_far.append(slot)

    if h < city.day_start or len(slots_so_far) < 4 or h < hour_min:
        continue

    running_max = max(sl["temp_c"] for sl in slots_so_far)
    if np.isnan(running_max) or np.isinf(running_max):
        running_max = 15.0

    p_ens = p_ens_list[idx_in_day]
    # ... resto da lógica de trade ...
Verificação
Após aplicar todos os fixes, executar:

bash

python backtester.py --city munich --mode single --years 2 --noise 0.05
Verificar:

PnL por trade é ligeiramente diferente (mais preciso agora)
Stop-loss PnL é consistente com PnL normal
Sem erros de sintaxe ou indentação
Resultados sazonais e anuais fazem sentido
text


---

## Resumo dos Fixes

| Fix | Bug | Severidade | Ficheiro |
|-----|-----|------------|----------|
| 1 | PnL usa custo real | 🔴 Crítico | backtester.py |
| 2 | Stop-loss PnL consistente | 🔴 Crítico | backtester.py |
| 3 | Flag não sobrescrito | 🔴 Crítico | live_bot.py |
| 4 | series_today actualizado | 🔴 Crítico | live_bot.py |
| 5 | Date parsing US removido | 🔴 Crítico | live_bot.py |
| 6 | Lock adquirido | 🔴 Crítico | live_bot.py |
| 7 | hour_min uma vez | 🟡 Médio | backtester.py |
| 8 | Código morto removido | 🟡 Médio | live_bot.py |
| 9 | Lógica unificada | 🟡 Médio | backtester.py |
mas ele esta a guardar os csv onde ? 

Thought Process
Pela análise do código que forneceste, o bot não guarda/guarda CSVs em lado nenhum. O código fornecido apenas lê CSVs e escreve ficheiros JSON e PNG.

Aqui está o mapeamento exato do que entra e o que sai:

📥 Onde ele LÊ os CSVs (Input)
live_bot.py (na função _settle_paper_positions_for_day, linha ~165):
Lê de: Path("historic") / f"{state.city.name}.csv"
Exemplo: historic/munich.csv
Para que serve: Para ir buscar a temperatura máxima real de dias passados e fazer o settle (fechar) de posições Paper que ficaram abertas de um dia para o outro.
backtester.py (na função load_data, linha ~135):
Lê de: O caminho é passado como argumento csv_path para a função (o código do argparse no fundo do ficheiro estava cortado, mas espera receber um caminho).
Para que serve: Para correr o backtest com o histórico real da cidade.

