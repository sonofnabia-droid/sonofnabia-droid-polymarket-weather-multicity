CHANGES_17_2.md — Bugfixes e melhorias
Aplica-se a: weather.py, tg.py, live_bot.py, backtester.py, modules/single_entry.py

🔴 CRÍTICOS — Bot não arranca ou crasha em runtime
FIX-01: Completar live_bot.py (truncado)
O ficheiro corta-se a meio da construção de bet_record no _tick_city. Completar o dict e o resto da função (processamento da acção, stop-loss check, CLOB order, stats update, return).

# Onde está:"temp_hi":       bra# Deve ser algo como (adaptar ao contexto exacto da função):bet_record = {    "city":          city.name,    "hour":          h_cur,    "slot30":        s30_cur,    "bracket":       bracket["label"],    "bracket_label": bracket["label"],    "ask":           ask,    "raw_ask":       raw_best_ask,    "size_usdc":     size_usdc,    "bet_size":      size_usdc,    "shares":        math.floor(size_usdc / ask) if ask > 0 else 0,    "temp_lo":       bracket.get("temp_lo"),    "temp_hi":       bracket.get("temp_hi"),    "token_id":      token_id,    "market_slug":   current_market_slug,    "strategy":      state.strategy_mode,    "p_ensemble":    p_ensemble,    "running_max":   running_max,}
Depois deste dict, falta todo o bloco de execução da ordem, verificação de stop-loss, actualização de stats, e o return stats. Copiar a lógica da versão anterior do ficheiro ou reconstruir seguindo o padrão das outras cidades.

FIX-02: Completar tg.py — fim de _build_brackets_table_ascii
O ficheiro corta-se a meio da função. Completar:

python

# Onde está:
        lines.append("  " + "─" * 42)
        li

# Completar com:
        lines.append(f"  Vol: ${vol:,.0f}  |  {n_outcomes} outcomes")
        if n_hidden > 0:
            lines.append(f"  (+ {n_hidden} brackets ocultos)")
        return lines
FIX-03: Criar _generate_city_charts_message na classe TG
Este método é chamado pelo _handle_button quando o utilizador clica num botão chart:{city_name} mas nunca foi implementado. Criar em tg.py:

python

def _generate_city_charts_message(self, city_name: str) -> tuple[str, list]:
    """Gera mensagem de chart para uma cidade específica.
    Retorna (text, keyboard) para uso no callback handler.
    """
    if not hasattr(self, 'bot_states') or not self.bot_states:
        return "❌ Nenhuma cidade activa.", []

    state = self.bot_states.get(city_name)
    if not state:
        return f"❌ Cidade {city_name} não encontrada.", []

    city = state.city
    now_city = datetime.now(tz=ZoneInfo(city.timezone))
    today = now_city.date()

    # ── Header ──
    lines = [
        f"📈 <b>{city.name.replace('_', ' ').title()}</b> — {today.isoformat()}",
        f"  Hora local: <b>{now_city.strftime('%H:%M')}</b>",
        "",
    ]

    # ── Temperatura actual e running max ──
    temp_now = None
    rmax = 0.0
    rmax_time = "—"
    if state.slots_so_far:
        valid = [s for s in state.slots_so_far if s.get("temp_c") is not None]
        if valid:
            rmax_slot = max(valid, key=lambda s: float(s["temp_c"]))
            rmax = float(rmax_slot["temp_c"])
            rmax_time = f"{int(rmax_slot['hour']):02d}:{int(rmax_slot.get('slot30', 0)):02d}"
    if state.latest_obs and state.latest_obs.get("temp_c") is not None:
        temp_now = state.latest_obs["temp_c"]

    lines.append(f"  🌡 Temp agora: <b>{temp_now:.1f}°C</b>" if temp_now is not None else "  🌡 Temp agora: —")
    lines.append(f"  📍 Running max: <b>{rmax:.1f}°C</b> @ {rmax_time}")
    lines.append("")

    # ── P(pico) ──
    p_ens = getattr(state, 'last_p_ensemble', 0.0)
    thr = city.threshold if city.threshold is not None else 0.65
    bar = self._tg_bar(p_ens, width=12)
    lines.append(f"  🧠 P(pico): <b>{p_ens*100:.1f}%</b> / {thr*100:.0f}%")
    lines.append(f"  {bar}")
    lines.append("")

    # ── Chart ASCII ──
    chart_lines = self._build_temp_chart_ascii(state.slots_so_far, width=36, height=8)
    lines.extend(chart_lines)
    lines.append("")

    # ── Tabela de brackets ──
    market = getattr(state, 'market', None)
    target = getattr(state, 'last_target_bracket', None)
    if market and market.get("brackets"):
        bracket_lines = self._build_brackets_table_ascii(market, target_bracket=target, max_brackets=15)
        lines.extend(bracket_lines)
    else:
        lines.append("  ⚠️ Mercado não disponível ainda.")

    # ── Posição actual ──
    entry = getattr(state, 'entry', None)
    if entry and getattr(entry, 'bought', False):
        rec = getattr(entry, 'record', None) or {}
        lines.append("")
        lines.append(
            f"  💼 <b>Posição aberta:</b> {rec.get('bracket_label', '?')} "
            f"@ {rec.get('ask', 0)*100:.1f}¢"
        )
        if getattr(entry, 'sold_by_stop', False):
            lines.append("  ⚠️ <i>Vendida por stop-loss</i>")

    # ── Keyboard: voltar ao menu de charts ──
    keyboard = [
        [{"text": "↩️ Voltar ao menu de cidades", "callback_data": "charts_menu"}],
        [{"text": "🏠 Menu principal", "callback_data": "resumo_hoje"}],
    ]

    return "\n".join(lines), keyboard
Nota: Este método usa self._tg_bar() (FIX-04) e ZoneInfo (adicionar from zoneinfo import ZoneInfo no topo de tg.py).

FIX-04: Criar função _tg_bar em tg.py
Função de utilidade para gerar barras visuais de progresso. Adicionar como função de módulo (fora da classe) no topo do ficheiro, após os imports:

python

def _tg_bar(value: float, width: int = 8) -> str:
    """Barra visual para Telegram (mono-spaced).
    value: 0.0 a 1.0
    """
    if value <= 0:
        return "░" * width
    if value >= 1:
        return "█" * width
    filled = round(value * width)
    return "█" * filled + "░" * (width - filled)
FIX-05: Criar método dashboard na classe TG
O live_bot.py chama tg_inst.dashboard(...) com muitos kwargs. Este método não existe. Criar em tg.py:

python

def dashboard(self, *, today, p, rmax, rmax_time, temp_now,
              forecast_max, om_forecast, forecast_agreement,
              market, bracket, ensemble_result, peak_detected,
              bet, trading_mode, chart, reason,
              positions_summary=None, usdc_balance=None,
              city_name=None) -> bool:
    """Envia dashboard periódico de uma cidade via Telegram.
    Chamado pelo live_bot.py a cada N segundos.
    """
    city_label = (city_name or "Unknown").replace("_", " ").title()
    mode_icon = "🟢" if str(trading_mode).upper() == "REAL" else "🟡"

    lines = [
        f"{mode_icon} <b>{city_label}</b> — {today}",
        f"  Hora local: {rmax_time}",
        "",
    ]

    # Temperatura
    if temp_now is not None:
        lines.append(f"  🌡 Temp: <b>{temp_now:.1f}°C</b>  |  RMax: <b>{rmax:.1f}°C</b> @ {rmax_time}")
    else:
        lines.append(f"  🌡 Temp: —  |  RMax: <b>{rmax:.1f}°C</b> @ {rmax_time}")

    # P(pico)
    p_lgbm = ensemble_result.get("p_lgbm") if ensemble_result else None
    p_str = f"{p*100:.1f}%"
    if p_lgbm is not None and abs(p - p_lgbm) > 0.001:
        p_str += f" (LGBM {p_lgbm*100:.1f}%)"
    thr = 0.65  # default; idealmente vir da city config
    bar = _tg_bar(p, width=10)
    peak_icon = "🔥" if peak_detected else "💤"
    lines.append(f"  {peak_icon} P(pico): <b>{p_str}</b>  {bar}")

    # Forecast
    if forecast_max:
        lines.append(f"  📊 WU forecast: {forecast_max.get('temp_max', '?')}°C")
    if om_forecast:
        lines.append(f"  📊 OM forecast: {om_forecast.get('temp_max', '?')}°C")
    if forecast_agreement and forecast_agreement.get("diff") is not None:
        diff = forecast_agreement["diff"]
        icon = "✅" if forecast_agreement.get("valid") else "⚠️"
        lines.append(f"  {icon} Acordo: {diff}°C diferença")

    lines.append("")

    # Chart ASCII
    if chart:
        lines.extend(chart)
        lines.append("")

    # Posição
    if bet and bet.get("size_usdc", 0) > 0:
        lines.append(
            f"  💼 <b>Posição:</b> {bet.get('bracket_label', '?')} "
            f"@ {bet.get('ask', 0)*100:.1f}¢  "
            f"${bet.get('size_usdc', 0):.2f}"
        )

    # Positions summary (acumulado)
    if positions_summary:
        s = positions_summary
        nc = s.get("n_won", 0) + s.get("n_lost", 0)
        wr = f"{s['n_won']/nc*100:.0f}%" if nc > 0 else "—"
        pnl = s.get("total_pnl_usd", 0)
        icon = "📈" if pnl >= 0 else "📉"
        lines.append("")
        lines.append(
            f"  {icon} Acumulado: {s.get('n_won',0)}W/{s.get('n_lost',0)}L "
            f"({wr})  PnL: ${pnl:+.2f}"
        )
        if s.get("n_open", 0) > 0:
            lines.append(f"  ⏳ Posições abertas: {s['n_open']}")

    # USDC balance (REAL only)
    if usdc_balance is not None:
        lines.append(f"  💰 Saldo USDC: <b>${usdc_balance:.2f}</b>")

    return self.send("\n".join(lines))
🟠 ALTOS — Comportamento errado, perda de dinheiro possível
FIX-06: Usar _lock em tg.py ao ler bot_states
O lock foi criado (comentado "FIX C2") mas nunca usado. A polling thread do Telegram lê self.bot_states enquanto a main thread a escreve.

python

# Em todos os métodos que leem self.bot_states, envolver com lock:

def _build_charts_menu(self):
    with self._lock:
        if not hasattr(self, 'bot_states') or not self.bot_states:
            return ("📈 <b>Charts por Cidade</b>\n\n❌ Nenhuma cidade activa.", [])
        cities = list(self.bot_states.keys())
        # ... resto do método ...

def _get_bot_status(self) -> str:
    with self._lock:
        if not hasattr(self, 'bot_states') or not self.bot_states:
            return "⚙️ <b>Status do Bot</b>\n\n❌ Estados não disponíveis."
        # ... fazer cópia dos dados necessários ...
        snapshot = {
            name: {
                "daily_pnl": getattr(s, 'daily_stats', None) and getattr(s.daily_stats, 'daily_pnl', 0.0),
                "trades": len(getattr(s, 'daily_stats', None) and getattr(s.daily_stats, 'trades', [])),
            }
            for name, s in self.bot_states.items()
        }
    # Formatar mensagem fora do lock
    # ...
E na main thread (live_bot.py), envolver escritas a bot_states com o mesmo lock:

python

# Em live_bot.py, onde se faz tg.bot_states = states:
with tg._lock:
    tg.bot_states = states
FIX-07: PnL do stop-loss consistente com PnL normal
Ficheiro: backtester.py, na secção "STOP-LOSS" dentro de run_backtest

O problema: _pnl_per_dollar usa invested = size_usdc (assumindo que todos os $5 foram investidos), mas o stop-loss calcula invested = shares * ask (que pode ser menor por causa do floor).

Solução: Usar o mesmo critério nos dois — invested = size_usdc:

python

# ANTES (stop-loss no backtester):
shares = math.floor(pos["size_usdc"] / entry_ask)
invested = shares * entry_ask
sell_value = shares * sell_bid
gross_pnl = sell_value - invested

# DEPOIS:
shares = math.floor(pos["size_usdc"] / entry_ask) if entry_ask > 0 else 0
invested = pos["size_usdc"]  # ← consistente com _pnl_per_dollar
sell_value = shares * sell_bid
# O "resto" (invested - shares*ask) fica em cash, não se perde
gross_pnl = sell_value - (shares * entry_ask)
# Mas para o PnL reportado, subtrair o invested total (como _pnl_per_dollar faz)
reported_pnl = sell_value - invested
Alternativa mais simples (recomendada): reutilizar _pnl_per_dollar para calcular o PnL teórico se tivesse expirado, e depois subtrair o valor recuperado pelo stop-loss:

python

# PnL se deixasse expirar (usando a lógica de _pnl_per_dollar):
pnl_if_expired = _pnl_per_dollar(entry_ask, won=False, size_usdc=pos["size_usdc"])

# Valor recuperado pelo stop-loss:
shares = math.floor(pos["size_usdc"] / entry_ask) if entry_ask > 0 else 0
recovered = shares * sell_bid

# PnL real = recovered - size_usdc (o que não foi investido em shares fica em cash)
realized_pnl = recovered - pos["size_usdc"]
if realized_pnl > 0:
    realized_pnl -= realized_pnl * TAKER_FEE_RATE
FIX-08: _select_target_bracket — fallback correto para brackets de cauda
Ficheiro: modules/single_entry.py

O midpoint de "25°C or higher" (lo=25, hi=99) é 62, o que faz o fallback escolher brackets errados. Corrigir:

python

@staticmethod
def _select_target_bracket(market: dict | None, running_max: float) -> dict | None:
    if not market:
        return None
    brackets = market.get("brackets") or []
    if not brackets:
        return None

    target_temp = int(math.floor(running_max))

    # 1. Match exacto
    best = None
    for bracket in brackets:
        lo = bracket.get("temp_lo")
        hi = bracket.get("temp_hi")
        if lo is None or hi is None:
            continue
        if lo <= target_temp <= hi:
            best = bracket
            break

    if best is not None:
        return best

    # 2. Fallback: bracket de cauda "or higher" / "or lower"
    for bracket in brackets:
        lo = bracket.get("temp_lo")
        hi = bracket.get("temp_hi")
        if lo is None or hi is None:
            continue
        if hi >= 99 and target_temp >= lo:
            return bracket
        if lo <= -99 and target_temp <= hi:
            return bracket

    # 3. Fallback: bracket mais próximo (usar temp_lo para caudas, midpoint para normais)
    def _distance(b):
        lo = float(b.get("temp_lo", 0))
        hi = float(b.get("temp_hi", 0))
        if hi >= 99:
            return abs(lo - target_temp)  # distância ao limite inferior
        if lo <= -99:
            return abs(hi - target_temp)
        return abs((lo + hi) / 2 - target_temp)

    valid_brackets = [
        b for b in brackets
        if b.get("temp_lo") is not None and b.get("temp_hi") is not None
    ]
    if valid_brackets:
        return min(valid_brackets, key=_distance)
    return None
FIX-09: Filtro de plateau — medir tempo real, não slots
Ficheiro: modules/single_entry.py, dentro de evaluate

python

# ANTES:
if slots_so_far and len(slots_so_far) >= 2:
    temps = [s["temp_c"] for s in slots_so_far[-2:]]
    delta = temps[-1] - temps[0]
    if delta > 0.2:
        return [...]

# DEPOIS:
if slots_so_far and len(slots_so_far) >= 2:
    # Encontrar o slot de ~30 min atrás (não o penúltimo da lista)
    now_minutes = hour * 60 + (slots_so_far[-1].get("slot30", 0) if slots_so_far else 0)
    target_minutes = now_minutes - 30

    # Buscar o slot mais próximo de 30 min atrás
    prev_slot = None
    for s in reversed(slots_so_far[:-1]):  # excluir o slot actual
        s_minutes = int(s["hour"]) * 60 + int(s.get("slot30", 0))
        if s_minutes <= target_minutes:
            prev_slot = s
            break

    if prev_slot is not None:
        delta = slots_so_far[-1]["temp_c"] - prev_slot["temp_c"]
        if delta > 0.2:
            return [{
                "parcel_idx": 0,
                "size_usdc": 0,
                "reason": f"SINGLE: temp subiu {delta:+.2f}°C nos últimos 30min (> +0.20°C). À espera de plateau.",
                "model_ok": True,
                "market_ok": None,
            }]
🟡 MÉDIOS — Comportamento incorreto sem crash
FIX-10: alert_started — usar nome da cidade dinâmico
Ficheiro: tg.py

python

# ANTES:
f"{mode_icon} <b>Munich Bot iniciado</b> — {today}",

# DEPOIS — adicionar parâmetro city_name (default "Bot"):
def alert_started(self, mode, bankroll, threshold_arg,
                  threshold_month=None, month=None,
                  market=None, today=None, hour_min=None,
                  city_name=None):
    label = (city_name or "Bot").replace("_", " ").title()
    # ...
    f"{mode_icon} <b>{label} iniciado</b> — {today}",
Actualizar a chamada em live_bot.py para passar city_name=city.name.

FIX-11: Escapar HTML em campos controlados por dados externos
Ficheiro: tg.py — adicionar função de utilidade no topo:

python

def _esc(text: str) -> str:
    """Escapa caracteres HTML para Telegram."""
    if not text:
        return ""
    return (str(text)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;"))
Aplicar nos locais críticos:

python

# alert_order_failed:
f"  Erro: <code>{_esc(str(error)[:200])}</code>"

# alert_peak_detected (market title, bracket label):
f"  🏆 Mercado favorito: <b>{_esc(best['label'])}</b>"
f"  🎯 Bracket alvo: <b>{_esc(bracket['label'])}</b>"

# _generate_daily_summary:
f"  {icon} {_esc(city)}: {_esc(bracket)} (${pnl:+.2f})"

# alert_order_placed:
f"  🏙 <b>{_esc(city)}</b>",
f"  🎯 <b>{_esc(bracket)}</b>  ask <b>{ask*100:.1f}¢</b>",
Não escapar campos que usam <code>...</code> para formatar IDs técnicos (order_id, market_slug) — esses são controlados internamente.

FIX-12: _get_recent_wins — filtro de status robusto
Ficheiro: tg.py

python

# ANTES:
wins = [
    e for e in events
    if e.get('pnl', 0) > 0 and e.get('status') == 'won'
]

# DEPOIS:
def _is_won(event):
    status = event.get('status')
    if status is None:
        return event.get('pnl', 0) > 0  # fallback: positivo = won
    # Aceitar string ou enum
    s = status.value if hasattr(status, 'value') else str(status)
    return s.lower() in ('won', 'win', 'true', '1')

wins = [e for e in events if _is_won(e)]
FIX-13: _get_open_positions — usar CLOB em vez de ficheiros hardcoded
Ficheiro: tg.py

Esta função devia ler do bot_states (que tem acesso ao CLOB) em vez de ficheiros JSON hardcoded. Se bot_states não estiver disponível, mostrar mensagem de fallback:

python

def _get_open_positions(self) -> str:
    # Tentar via bot_states (fonte de verdade)
    if hasattr(self, 'bot_states') and self.bot_states:
        positions_text = []
        with self._lock:
            for city_name, state in self.bot_states.items():
                if not hasattr(state, 'clob') or not state.clob:
                    continue
                try:
                    for pos in state.clob.positions.open_positions():
                        icon = "💰" if str(state.trading_mode).upper() == "REAL" else "📂"
                        positions_text.append(
                            f"{icon} <b>{city_name.replace('_', ' ').title()}</b>\n"
                            f"  🎯 {getattr(pos, 'bracket_label', '?')}\n"
                            f"  💵 Entrada: {getattr(pos, 'entry_ask', 0)*100:.1f}¢\n"
                            f"  🏦 Size: ${getattr(pos, 'size_usdc', 0):.2f}\n"
                        )
                except Exception:
                    pass

        if positions_text:
            return "📂 <b>Posições Abertas</b>\n\n" + "\n".join(positions_text)

    # Fallback: tentar ficheiros (mantido para compatibilidade)
    # ... manter o código existente como fallback ...
FIX-14: restore() — preservar estado de stop-loss
Ficheiro: live_bot.py, no bloco de anti-duplicado

Após restaurar a posição, verificar se a temperatura actual já disparou o stop-loss:

python

if _skip and _rec and state.entry:
    if hasattr(state.entry, "restore"):
        state.entry.restore(_rec, state.strategy_mode)
    else:
        state.entry.bought = True
        state.entry.record = _rec

    # Verificar se stop-loss já foi disparado antes do restart
    if state.slots_so_far and state.entry.record:
        current_temp = max(s["temp_c"] for s in state.slots_so_far)
        sl_check = state.entry.check_stop_loss(current_temp)
        if sl_check:
            # Marcar como vendida sem enviar alerta duplicado
            state.entry.sold_by_stop = True
            state.entry.record["sold_by_stop"] = True
            if hasattr(state.entry, '_stop_loss_blocked_alerted'):
                state.entry._stop_loss_blocked_alerted = True
            print(f"  {C['yellow']}{city.name}: stop-loss já disparado antes do restart — marcando como vendida{R}")

    if hasattr(state.entry, '_stop_loss_blocked_alerted'):
        state.entry._stop_loss_blocked_alerted = False
FIX-15: Documentar intenção de history_max_for_features
Se o train/serving mismatch é intencional, adicionar comentário explícito. Se não é, corrigir:

python

# live_bot.py — _tick_city

# OPÇÃO A (se o modelo foi treinado COM rmax do dia):
# Usar history_max actualizado (inclui hoje)
update_history_max(state.history_max, state.slots_so_far, city.name)
prev7_value = compute_prev7(state.history_max, city_today, city.name)

# OPÇÃO B (se o modelo foi treinado SEM rmax do dia — actual):
# Manter a cópia antes do update, mas documentar PORQUÊ:
# NOTA: compute_prev7 usa apenas history_max de dias ANTERIORES
# para evitar data leakage. O rmax do dia actual entra como
# feature separada em current_extra["temp_c"] via running_max implícito.
history_max_for_features = dict(state.history_max)
update_history_max(state.history_max, state.slots_so_far, city.name)
prev7_value = compute_prev7(history_max_for_features, city_today, city.name)
Verificar qual opção foi usada no treinamento (ver predictor.py / build_features) e garantir consistência.

🔵 BAIXOS — Limpeza de código
FIX-16: Remover _compute_sharpe_sortino(capital_history) morto
Ficheiro: backtester.py — apagar a função _compute_sharpe_sortino que recebe capital_history: list (não a que recebe day_records). Nunca é chamada.

FIX-17: Remover imports redundantes em send_menu
Ficheiro: tg.py

python

# REMOVER estas linhas de dentro de send_menu():
    import json
    import requests
# (já estão importados no topo do ficheiro)
FIX-18: Melhorar stop_polling com timeout
Ficheiro: tg.py

python

def stop_polling(self, timeout: float = 5.0):
    """Para o polling com timeout."""
    self.polling_active = False
    # Dar tempo ao loop de asyncio para detectar a flag
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not self._app or not self._app.updater.running:
            break
        time.sleep(0.1)
    print("  [TG] Polling parado")
📋 Checklist de verificação após aplicar
 python -c "import tg" — sem SyntaxError
 python -c "import live_bot" — sem SyntaxError
 python -c "import backtester" — sem SyntaxError
 python modules/single_entry.py — self-test passa
 Bot arranca com --cities munich --mode single --run paper
 Clicar em botão de chart no Telegram — não crasha
 Enviar /status no Telegram — não crasha
 Enviar /charts no Telegram — não crasha
 Deixar correr 10 minutos — sem RuntimeError: dictionary changed size
 Verificar que dashboard periódico chega ao Telegram (se activado)
