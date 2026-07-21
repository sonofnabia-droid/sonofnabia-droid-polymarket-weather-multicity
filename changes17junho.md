```markdown
# Changes 17 Junho — Master Fix List (Passes 1 & 2)

Instruções exatas para o Codex aplicar na máquina local. 
Corrige todos os bugs críticos, lógicos e de produção encontrados no deep-dive.

---

## FICHEIRO: `modules/single_entry.py`

### FIX 1: `or` chain ignora valores `0` e `0.0` (Crítico)
**Problema:** Se `hour_min=0` ou `stop_loss_delta=0.0` forem passados, o Python avalia como `False` e usa o fallback.
**Instrução:** Adicionar a função helper no topo da classe e substituir as inicializações.

```python
# ENCONTRAR (linhas iniciais da classe, após o docstring):
    is_single = True

    def __init__(self, city_config: CityConfig, **kwargs):

# SUBSTITUIR POR:
    is_single = True

    @staticmethod
    def _first_non_none(*values):
        """Retorna o primeiro valor que não é None. Evita bugs do `or` com 0/0.0."""
        for v in values:
            if v is not None:
                return v
        return None

    def __init__(self, city_config: CityConfig, **kwargs):
```

```python
# ENCONTRAR:
        # Fallback: kwargs → CityConfig → defaults
        self.parcel_size = kwargs.get("parcel_size", 5.0)
        self.threshold = (
            kwargs.get("threshold")
            or threshold
            or city_config.threshold
            or 0.65
        )
        self.hour_min = (
            kwargs.get("hour_min")
            or hour_min
            or city_config.hour_min
            or 11
        )
        self.stop_loss_delta = (
            kwargs.get("stop_loss_delta")
            or stop_loss_delta
            or 1.0
        )
        self.min_buy_ask = (
            kwargs.get("min_buy_ask")
            or min_buy_ask
            or 0.15
        )
        self.max_buy_ask = (
            kwargs.get("max_buy_ask")
            or max_buy_ask
            or 0.85
        )

# SUBSTITUIR POR:
        # Fallback: kwargs → CityConfig → defaults
        self.parcel_size = kwargs.get("parcel_size", 5.0)
        self.threshold = self._first_non_none(
            kwargs.get("threshold"),
            threshold,
            city_config.threshold,
        ) or 0.65
        self.hour_min = self._first_non_none(
            kwargs.get("hour_min"),
            hour_min,
            city_config.hour_min,
        ) or 11
        self.stop_loss_delta = self._first_non_none(
            kwargs.get("stop_loss_delta"),
            stop_loss_delta,
        ) or 1.0
        self.min_buy_ask = self._first_non_none(
            kwargs.get("min_buy_ask"),
            min_buy_ask,
        ) or 0.15
        self.max_buy_ask = self._first_non_none(
            kwargs.get("max_buy_ask"),
            max_buy_ask,
        ) or 0.85
```

### FIX 2: `evaluate()` retorna buy sem bracket (Alto)
**Problema:** Se `market` for `None` ou não encontrar bracket, a função retorna `size_usdc > 0` com `bracket=None`, causando crash no live_bot.
**Instrução:** Adicionar early return se não houver bracket válido.

```python
# ENCONTRAR:
        if p_ensemble >= self.threshold:
            bracket = self._select_target_bracket(market, running_max) if market else None
            if bracket is not None:
                ask = float(bracket.get("ask", bracket.get("price", 1.0)) or 1.0)
                if ask < self.min_buy_ask:
                    return [{
                        "parcel_idx": 0,
                        "size_usdc": 0,
                        "reason": (
                            f"SINGLE: bracket barato demais ({ask*100:.1f}¢ < "
                            f"{self.min_buy_ask*100:.0f}¢)"
                        ),
                        "model_ok": True,
                        "market_ok": False,
                        "bracket": bracket,
                    }]
                if ask > self.max_buy_ask:
                    return [{
                        "parcel_idx": 0,
                        "size_usdc": 0,
                        "reason": (
                            f"SINGLE: bracket caro demais ({ask*100:.0f}¢ > "
                            f"{self.max_buy_ask*100:.0f}¢)"
                        ),
                        "model_ok": True,
                        "market_ok": False,
                        "bracket": bracket,
                    }]
            return [{
                "parcel_idx": 0,
                "size_usdc": self.parcel_size,
                "reason": f"SINGLE: p={p_ensemble*100:.0f}% >= {self.threshold*100:.0f}% @ {hour}h",
                "model_ok": True,
                "market_ok": True,
                "bracket": bracket,
            }]

# SUBSTITUIR POR:
        if p_ensemble >= self.threshold:
            bracket = self._select_target_bracket(market, running_max) if market else None
            
            # Bloquear compra se não houver bracket válido no mercado
            if bracket is None:
                return [{
                    "parcel_idx": 0,
                    "size_usdc": 0,
                    "reason": "SINGLE: p acima do threshold mas sem bracket válido no mercado",
                    "model_ok": True,
                    "market_ok": False,
                    "bracket": None,
                }]
                
            ask = float(bracket.get("ask", bracket.get("price", 1.0)) or 1.0)
            if ask < self.min_buy_ask:
                return [{
                    "parcel_idx": 0,
                    "size_usdc": 0,
                    "reason": (
                        f"SINGLE: bracket barato demais ({ask*100:.1f}¢ < "
                        f"{self.min_buy_ask*100:.0f}¢)"
                    ),
                    "model_ok": True,
                    "market_ok": False,
                    "bracket": bracket,
                }]
            if ask > self.max_buy_ask:
                return [{
                    "parcel_idx": 0,
                    "size_usdc": 0,
                    "reason": (
                        f"SINGLE: bracket caro demais ({ask*100:.0f}¢ > "
                        f"{self.max_buy_ask*100:.0f}¢)"
                    ),
                    "model_ok": True,
                    "market_ok": False,
                    "bracket": bracket,
                }]
            return [{
                "parcel_idx": 0,
                "size_usdc": self.parcel_size,
                "reason": f"SINGLE: p={p_ensemble*100:.0f}% >= {self.threshold*100:.0f}% @ {hour}h",
                "model_ok": True,
                "market_ok": True,
                "bracket": bracket,
            }]
```

---

## FICHEIRO: `live_bot.py`

### FIX 3: Import em falta (Crítico)
**Problema:** A dataclass `CityState` usa `threading.Lock` mas não existe import.
**Instrução:** Adicionar import no topo.

```python
# ENCONTRAR (na zona dos imports, ex: depois de `from typing import Optional`):
from cities.config import CityConfig, get_city, CITIES

# SUBSTITUIR POR:
import threading
from cities.config import CityConfig, get_city, CITIES
```

### FIX 4: Código truncado no `bet_record` (Crítico)
**Problema:** O ficheiro termina a meio da string `"p_ensemb`, causando SyntaxError.
**Instrução:** Completar o dicionário e fechar o bloco de código corretamente.

```python
# ENCONTRAR (no final do ficheiro):
                    "p_ensemb

# SUBSTITUIR POR (completando o dict e o fluxo normal):
                    "p_ensemble": p_ensemble,
                    "running_max": running_max,
                }

                # Marcar estratégia como comprada
                state.entry.mark_bought(0, bet_record)

                # Executar ordem no CLOB
                try:
                    result = state.clob.buy(
                        token_id=token_id,
                        size_usdc=size_usdc,
                        ask_price=ask,
                        mode=trading_mode_str,
                    )
                    bet_record["order_id"] = result.get("order_id")
                    bet_record["shares"] = result.get("shares")
                    bet_record["simulated"] = result.get("simulated", False)

                    # Atualizar stats
                    stats.total_invested += size_usdc
                    stats.trades.append(bet_record)
                    session_stats.total_trades += 1

                    _tg_alert_order_placed(bet_record, trading_mode_str)
                    _append_bet_record(bet_record, city.name, city_today)

                except Exception as e:
                    print(f"  {C['red']}{city.name}: ORDEM FALHOU: {e}{R}")
                    _tg_alert(f"❌ <b>{city.name}</b> ordem falhou: {str(e)[:150]}")
                    state.entry.reset()  # Desfazer marcação de compra

                break  # Sai do loop de actions
```

### FIX 5: Spam infinito da API no Bootstrap (Crítico)
**Problema:** O flag `_bootstrap_pending` é colocado a `False` mesmo que o retry não resolva o problema, ou não é colocado se tiver sucesso condicional.
**Instrução:** Corrigir a lógica do FIX 5.

```python
# ENCONTRAR:
    # FIX 5: backoff para bootstrap (evita spam de tentativas se API down)
    if getattr(state, "_bootstrap_pending", False) and len(state.slots_so_far) < 4:
        now_ts_boot = time.time()
        if now_ts_boot - state._last_bootstrap_attempt >= 60:  # só a cada 60s
            state._last_bootstrap_attempt = now_ts_boot
            try:
                _bootstrap_state_today(state)
                state._bootstrap_pending = False
            except Exception:
                pass  # mantém pending, tenta de novo daqui a 60s

# SUBSTITUIR POR:
    # FIX 5: backoff para bootstrap (evita spam de tentativas se API down)
    if getattr(state, "_bootstrap_pending", False) and len(state.slots_so_far) < 4:
        now_ts_boot = time.time()
        if now_ts_boot - state._last_bootstrap_attempt >= 60:  # só a cada 60s
            state._last_bootstrap_attempt = now_ts_boot
            try:
                _bootstrap_state_today(state)
                # Só desativa o flag se realmente resolveu o problema
                if len(state.slots_so_far) >= 4:
                    state._bootstrap_pending = False
            except Exception:
                pass  # mantém pending, tenta de novo daqui a 60s
```

### FIX 6: Falha ao ler Posições Paper Antigas (Alto)
**Problema:** Assume que a data no CSV Histórico é `dd/mm/yyyy`. Se for ISO (`yyyy-mm-dd`), nunca faz match e as posições ficam eternamente "open".
**Instrução:** Tentar múltiplos formatos de data.

```python
# ENCONTRAR:
            target_key = target_day.strftime("%d/%m/%Y")
            max_temp: Optional[float] = None
            try:
                with hist_path.open("r", encoding="utf-8", newline="") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        if str(row.get("date", "")).strip() != target_key:
                            continue

# SUBSTITUIR POR:
            # Tenta múltiplos formatos comuns de data para evitar falhas de parsing
            target_keys = {
                target_day.strftime("%Y-%m-%d"), # ISO 8601
                target_day.strftime("%d/%m/%Y"), # EU
                target_day.strftime("%m/%d/%Y"), # US
            }
            max_temp: Optional[float] = None
            try:
                with hist_path.open("r", encoding="utf-8", newline="") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        if str(row.get("date", "")).strip() not in target_keys:
                            continue
```

---

## FICHEIRO: `backtester.py`

### FIX 7: Stop-loss aplica fee sobre PERDAS (Alto)
**Problema:** Na Polymarket, a fee de 2% aplica-se apenas sobre lucros. O código atual subtrai fee até quando `gross_pnl` é negativo.
**Instrução:** Aplicar fee condicionalmente.

```python
# ENCONTRAR:
                    gross_pnl = sell_value - invested
                    realized_pnl = gross_pnl - abs(gross_pnl) * TAKER_FEE_RATE

# SUBSTITUIR POR:
                    gross_pnl = sell_value - invested
                    # Na Polymarket real, fee aplica-se apenas sobre lucros
                    if gross_pnl > 0:
                        realized_pnl = gross_pnl - (gross_pnl * TAKER_FEE_RATE)
                    else:
                        realized_pnl = gross_pnl
```

### FIX 8: Win-Rate Falsa no Backtester com Stop-Loss (Alto)
**Problema:** Se o stop-loss dispara (vendendo com perda), mas o pico real do dia acabou por bater no bracket antes de a temp subir mais, o backtester conta como "Win".
**Instrução:** Um trade que acionou stop-loss nunca deve contar como vitória de modelo.

```python
# ENCONTRAR:
            correct_s = single_won
            missed_s = not entry_single.bought

# SUBSTITUIR POR:
            # Se disparou stop-loss, o modelo falhou na proteção/tempo. Não conta como win.
            correct_s = single_won and not entry_single.sold_by_stop
            missed_s = not entry_single.bought
```

---

## FICHEIRO: `backtester_all.py`

### FIX 9: NameError `be_wr`, `ev`, `margin` sem trades (Crítico)
**Problema:** Se não houver trades (`all_asks` vazio), as variáveis financeiras não são declaradas, causando crash no JSON final.
**Instrução:** Declarar defaults antes do bloco condicional e limpar linhas redundantes.

```python
# ENCONTRAR:
    # Break-even analysis agregado
    all_asks = [
        rec["single_ask"]
        for r in ok for rec in r.day_records
        if rec.get("single_ask") and not rec["single_missed"]
    ]
    if all_asks:
        avg_ask = float(np.mean(all_asks))
        # Proteger contra ask muito baixo (ruído pode ir < 0.01)
        avg_payoff = (1.0 / max(avg_ask, 0.001) - 1.0) if avg_ask > 0 else 0.0
        be_wr = (1.0 / (1.0 + avg_payoff) * 100) if avg_payoff > 0 else 100.0
        margin = g_win_pct - be_wr
        ev = (g_win_pct / 100 * avg_payoff) - ((1 - g_win_pct / 100) * 1.0)

        st.add_row("Ask médio (todos os trades)", f"{avg_ask:.3f}  ({avg_ask*100:.1f}¢)")
        st.add_row("Payoff por $ (quando ganha)", f"+${avg_payoff:.3f}")
        st.add_row("Win-rate break-even", f"{be_wr:.1f}%")
        mc = "green" if margin > 5 else "yellow" if margin > 0 else "red"
        st.add_row("Margem sobre break-even", f"[{mc}]{margin:+.1f}pp[/{mc}]")
        ec = "green" if ev > 0.05 else "yellow" if ev > 0 else "red"
        st.add_row("EV por $ apostado", f"[{ec}]${ev:+.4f}[/{ec}]")
        st.add_row("", "")

# SUBSTITUIR POR:
    # Break-even analysis agregado
    all_asks = [
        rec["single_ask"]
        for r in ok for rec in r.day_records
        if rec.get("single_ask") and not rec["single_missed"]
    ]
    
    # Inicializar defaults para evitar NameError se all_asks estiver vazio
    avg_ask = 0.0
    be_wr = 100.0
    margin = 0.0
    ev = 0.0
    
    if all_asks:
        avg_ask = float(np.mean(all_asks))
        # Proteger contra ask muito baixo (ruído pode ir < 0.01)
        avg_payoff = (1.0 / max(avg_ask, 0.001) - 1.0) if avg_ask > 0 else 0.0
        be_wr = (1.0 / (1.0 + avg_payoff) * 100) if avg_payoff > 0 else 100.0
        margin = g_win_pct - be_wr
        ev = (g_win_pct / 100 * avg_payoff) - ((1 - g_win_pct / 100) * 1.0)

        st.add_row("Ask médio (todos os trades)", f"{avg_ask:.3f}  ({avg_ask*100:.1f}¢)")
        st.add_row("Payoff por $ (quando ganha)", f"+${avg_payoff:.3f}")
        st.add_row("Win-rate break-even", f"{be_wr:.1f}%")
        mc = "green" if margin > 5 else "yellow" if margin > 0 else "red"
        st.add_row("Margem sobre break-even", f"[{mc}]{margin:+.1f}pp[/{mc}]")
        ec = "green" if ev > 0.05 else "yellow" if ev > 0 else "red"
        st.add_row("EV por $ apostado", f"[{ec}]${ev:+.4f}[/{ec}]")
        st.add_row("", "")
```

*(Nota Codex: Após fazer a substituição acima, apagar estas duas linhas que existem mais abaixo no ficheiro para evitar duplicação/confusão de variáveis:)*
```python
# ENCONTRAR E APAGAR ESTAS DUAS LINHAS (aparecem na secção VEREDICTO mais abaixo):
    be_wr = be_wr if all_asks else 100.0  # 100% = nunca ganha = break-even trivial
    margin_val = g_win_pct - be_wr if all_asks else 0
```
*(E substituir o resto do VEREDICTO que usava `margin_val` para usar apenas `margin`)*
```python
# ENCONTRAR:
    if g_pnl_pct > 5 and margin_val > 5:
        _console.print(
            f"[green bold]✓ EDGE POSITIVA ROBUSTA[/green bold] — "
            f"Margem +{margin_val:.1f}pp, PnL ${G['pnl']:+,.0f} "
            f"em {G['trades']:,} trades."
        )
    elif g_pnl_pct > 0 and margin_val > 0:
        _console.print(
            f"[yellow bold]⚠ EDGE MARGINAL[/yellow bold] — "
            f"Margem +{margin_val:.1f}pp. Slippage em produção pode eliminá-la."
        )

# SUBSTITUIR POR:
    if g_pnl_pct > 5 and margin > 5:
        _console.print(
            f"[green bold]✓ EDGE POSITIVA ROBUSTA[/green bold] — "
            f"Margem +{margin:.1f}pp, PnL ${G['pnl']:+,.0f} "
            f"em {G['trades']:,} trades."
        )
    elif g_pnl_pct > 0 and margin > 0:
        _console.print(
            f"[yellow bold]⚠ EDGE MARGINAL[/yellow bold] — "
            f"Margem +{margin:.1f}pp. Slippage em produção pode eliminá-la."
        )
```

---

## FICHEIRO: `display.py`

### FIX 10: PnL de Paper Trading calculado ao contrário (Alto)
**Problema:** Usava o preço de entrada em vez do atual, e a fórmula `(ask - 1.0)` garantia que era sempre negativo.
**Instrução:** Reescrever o bloco de cálculo de PnL Paper.

```python
# ENCONTRAR:
            # Calcular PnL para posições paper
            current_price = ask  # Para paper trading, usar o preço de entrada
            size_usdc = cd.position.get("size_usdc", 5.0)
            if current_price > 0:
                pnl_u = size_usdc * (current_price - 1.0)  # PnL baseado no preço atual
                pnl_p = (current_price - 1.0) * 100  # PnL em %
            else:
                pnl_u = None
                pnl_p = None
            
            tbl_open.add_row(
                clbl, d_op, bkt,
                f"{ask*100:.1f}¢" if ask > 0 else "—",
                f"{current_price*100:.1f}¢" if current_price > 0 else "—",
                Text(f"{pnl_u:+.2f}$" if pnl_u is not None else "—", 
                     style="bold green" if pnl_u and pnl_u > 0 else "bold red" if pnl_u and pnl_u < 0 else "dim"),
                Text(f"{pnl_p:+.1f}%" if pnl_p is not None else "—", 
                     style="bold green" if pnl_p and pnl_p > 0 else "bold red" if pnl_p and pnl_p < 0 else "dim"),
                f"{size_usdc:.2f}",
                Text("📄 PAPER", style="yellow"),
            )

# SUBSTITUIR POR:
            # Calcular PnL para posições paper (buscar preço ATUAL do mercado)
            entry_ask = ask
            current_ask = entry_ask  # Fallback para o preço de entrada
            size_usdc = cd.position.get("size_usdc", 5.0)
            
            # Tentar obter o preço de mercado atual para este bracket
            if cd.market and cd.position:
                pos_label = cd.position.get("bracket", "")
                for b in cd.market.get("brackets", []):
                    if b.get("label") == pos_label:
                        current_ask = b.get("ask") or b.get("price") or entry_ask
                        break
            
            shares = math.floor(size_usdc / entry_ask) if entry_ask > 0 else 0
            if shares > 0 and current_ask > 0:
                pnl_u = shares * (current_ask - entry_ask)
                pnl_p = ((current_ask / entry_ask) - 1.0) * 100 if entry_ask > 0 else 0.0
            else:
                pnl_u = None
                pnl_p = None
            
            tbl_open.add_row(
                clbl, d_op, bkt,
                f"{entry_ask*100:.1f}¢" if entry_ask > 0 else "—",
                f"{current_ask*100:.1f}¢" if current_ask > 0 else "—",
                Text(f"{pnl_u:+.2f}$" if pnl_u is not None else "—", 
                     style="bold green" if pnl_u and pnl_u > 0 else "bold red" if pnl_u and pnl_u < 0 else "dim"),
                Text(f"{pnl_p:+.1f}%" if pnl_p is not None else "—", 
                     style="bold green" if pnl_p and pnl_p > 0 else "bold red" if pnl_p and pnl_p < 0 else "dim"),
                f"{shares:.2f}",
                Text("📄 PAPER", style="yellow"),
            )
```

### FIX 11: `getattr` em dicionário (Médio)
**Problema:** `getattr(cd.position, "entry_time")` falha porque `cd.position` é um dict.

```python
# ENCONTRAR:
            # Adicionar hora da abertura se disponível
            entry_time = getattr(cd.position, "entry_time", None)
            if entry_time:

# SUBSTITUIR POR:
            # Adicionar hora da abertura se disponível
            entry_time = cd.position.get("entry_time") if cd.position else None
            if entry_time:
```

### FIX 12: Falso Positivo "Sanity abertas fora do dia" (Médio)
**Problema:** Ao comparar datas, se o CLOB guardou a data como objeto `datetime.date`, a conversão falha e acende o aviso vermelho injustamente.

```python
# ENCONTRAR:
            for pos in cd.positions_all or []:
                status = getattr(getattr(pos, "status", None), "value", getattr(pos, "status", None))
                if str(status).lower() != "open":
                    continue
                d_open = str(getattr(pos, "date_opened", "") or "")
                if d_open and d_open != city_today:
                    open_out_of_day += 1

# SUBSTITUIR POR:
            for pos in cd.positions_all or []:
                status = getattr(getattr(pos, "status", None), "value", getattr(pos, "status", None))
                if str(status).lower() != "open":
                    continue
                d_open_raw = getattr(pos, "date_opened", None)
                # Garantir que ambos são strings no formato ISO para comparação segura
                d_open = d_open_raw.isoformat() if hasattr(d_open_raw, 'isoformat') else str(d_open_raw or "")
                if d_open and d_open != city_today:
                    open_out_of_day += 1
```

---

## FICHEIRO: `tg.py`

### FIX 13: Código truncado no final do ficheiro (Crítico)
**Problema:** A função `_build_brackets_table_ascii` termina a meio.
**Instrução:** Completar o loop e o retorno.

```python
# ENCONTRAR (final do ficheiro):
            arrow = "🎯" if is_tgt else "  "
          

# SUBSTITUIR POR:
            arrow = "🎯" if is_tgt else "  "
            lines.append(f"  {arrow} {label:<18} {bid*100:>5.1f}/{ask*100:>5.1f}  {bar}")

        return lines

    def _generate_city_charts_message(self, city_name: str):
        """Gera mensagem de chart para uma cidade específica."""
        # Placeholder - implementar se necessário para o menu de charts
        return f"📊 Chart para {city_name} não implementado neste contexto.", None
```

### FIX 14: Cálculo de Lucro Perigoso (Médio)
**Problema:** Assume que se `ask >= 1.0` é porque veio em cêntimos (ex: 10 em vez de 0.10) e divide por 100. Isto é perigoso e já causou lucros irreais nos alertas do Telegram.

```python
# ENCONTRAR:
            if 0.0 < ask_f < 1.0 and shares_f > 0:
                # Lucro máximo bruto se resolver YES em 1.00.
                # Ex: ask 0.10, shares 50 -> profit = (1.0 - 0.10) * 50 = 45.0
                profit = max(0.0, (1.0 - ask_f) * shares_f)
            elif ask_f >= 1.0 and shares_f > 0:
                # Se ask_f >= 1.0, provavelmente está em cêntimos (ex: 10.0 para 10¢)
                ask_norm = ask_f / 100.0
                profit = max(0.0, (1.0 - ask_norm) * shares_f)
            else:
                profit = 0.0

# SUBSTITUIR POR:
            # Normalizar ask de forma segura (sem assumir que >1.0 é cêntimos)
            ask_safe = min(max(float(ask_f if ask_f is not None else 0.0), 0.01), 0.99)
            if shares_f > 0:
                profit = max(0.0, (1.0 - ask_safe) * shares_f)
            else:
                profit = 0.0
```

---

## FICHEIRO: `weather.py`

### FIX 15: Sanity Check de Temperatura muito permissivo (Médio)
**Problema:** Permitia `clim_max + 50`. Se a API devolvesse Fahrenheit em vez de Celsius, passava no check. Alterar para margem segura de 15°C.

```python
# ENCONTRAR:
    # Sanity check de temperatura
    if city.climatology:
        clim_max = max(city.climatology.values())
        sanity_limit = clim_max + 50.0
        if any(row.get("temp_c", 0.0) > sanity_limit for row in rows):

# SUBSTITUIR POR:
    # Sanity check de temperatura (margem justa para detetar Fahrenheit vs Celsius)
    if city.climatology:
        clim_max = max(city.climatology.values())
        sanity_limit = clim_max + 15.0 
        if any(row.get("temp_c", 0.0) > sanity_limit for row in rows):
```
