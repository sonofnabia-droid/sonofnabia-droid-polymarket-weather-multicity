"""
tg.py — Telegram notifier para o munich_live_bot
==================================================
Suporta:
  - Início/paragem do bot
  - Detecção de pico, ordens colocadas/falhadas
  - Stop-loss (NOVO 2026-04 — vende posição se temp > bracket+1°C)
  - Resolução de posições com PnL
  - Resumo diário e dashboard periódico (30 em 30 min)
  - Mudança de zona de probabilidade

Variáveis de ambiente:
    TELEGRAM_TOKEN=...
    TELEGRAM_CHAT_ID=...

Notas (2026-04):
  - Modelo LightGBM puro: removidas referências a XGB e z-score nos alertas
  - Stop-loss adicionado em alert_stop_loss_triggered
  - UX refinada: mensagens mais concisas, emojis consistentes, formatação clara
"""

import os
import requests
from datetime import datetime


class TG:
    """Wrapper para Telegram Bot API com alertas estruturados."""

    def __init__(self):
        self.token   = os.environ.get("TELEGRAM_TOKEN", "")
        self.chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
        self.enabled = bool(self.token and self.chat_id)
        self._last_p_zone = -1
        if not self.enabled:
            print("  [TG] TELEGRAM_TOKEN ou TELEGRAM_CHAT_ID não definidos — "
                  "notificações desactivadas")

    def send(self, text: str) -> bool:
        """Envia mensagem; devolve True se sucesso."""
        if not self.enabled:
            return False
        try:
            r = requests.post(
                f"https://api.telegram.org/bot{self.token}/sendMessage",
                json={"chat_id": self.chat_id, "text": text,
                      "parse_mode": "HTML",
                      "disable_web_page_preview": True},
                timeout=10,
            )
            return r.status_code == 200
        except Exception:
            return False

    # ══════════════════════════════════════════════════════
    #  ALERTAS DE LIFECYCLE
    # ══════════════════════════════════════════════════════

    def alert_started(self, mode, bankroll, threshold_arg,
                      threshold_month=None, month=None,
                      market=None, today=None, hour_min=None):
        """Bot arrancou. mode = 'paper' ou 'real'."""
        mode_icon = "🟢" if mode == "real" else "🟡"

        if market:
            mkt = (f"✅ <b>{market['title'][:50]}</b>\n"
                   f"  vol ${market['volume']:,.0f}  |  "
                   f"{market['n_outcomes']} brackets")
        else:
            mkt = "⚠️ Mercado ainda não disponível"

        # Threshold pode vir adaptativo por mês
        if threshold_month and abs(threshold_month - threshold_arg) > 0.01:
            thr_str = f"{threshold_month*100:.0f}% <i>(adaptativo mês {month})</i>"
        else:
            thr_str = f"{threshold_arg*100:.0f}%"

        hour_str = f"  ⏰ Não entrar antes das <b>{hour_min}h</b>\n" if hour_min else ""

        lines = [
            f"{mode_icon} <b>Munich Bot iniciado</b> — {today}",
            "",
            f"  Modo: <b>{mode.upper()}</b>",
            f"  Bankroll: <b>${bankroll:.2f}</b>",
            f"  Threshold: <b>{thr_str}</b>",
            hour_str,
            f"  {mkt}",
        ]
        return self.send("\n".join(line for line in lines if line is not None))

    def alert_no_market(self, today):
        return self.send(
            f"⚠️ <b>Mercado não encontrado</b> — {today}\n"
            f"  O Polymarket ainda não criou o mercado de hoje.\n"
            f"  A tentar de novo a cada 10 minutos."
        )

    # ══════════════════════════════════════════════════════
    #  ALERTAS DE TRADING
    # ══════════════════════════════════════════════════════

    def alert_peak_detected(self, p, rmax, rmax_time,
                            bracket=None, ensemble_result=None,
                            market=None):
        """Modelo detectou pico — pode ou não ter resultado em ordem."""
        # Probabilidade
        if ensemble_result:
            p_used = ensemble_result.get("p_ensemble", p)
            p_lgbm = ensemble_result.get("p_lgbm", p_used)
            # Modelo LightGBM puro: p_ensemble == p_lgbm. Mostrar só uma vez.
            prob_block = (
                f"  🧠 P(pico) <b>LightGBM</b>: <b>{p_used*100:.1f}%</b>"
            )
        else:
            prob_block = f"  🧠 P(pico): <b>{p*100:.1f}%</b>"

        bracket_str = ""
        if bracket:
            ask = bracket.get("ask") or bracket.get("price", 0)
            bracket_str = (f"\n  🎯 Bracket alvo: <b>{bracket['label']}</b>  "
                           f"(ask <b>{ask*100:.1f}¢</b>)")

        market_str = ""
        if market and market.get("brackets"):
            best = max(market["brackets"],
                       key=lambda b: b.get("ask") or b.get("price") or 0)
            best_ask = best.get("ask") or best.get("price", 0)
            market_str = (f"\n  🏆 Mercado favorito: <b>{best['label']}</b> "
                          f"(ask {best_ask*100:.0f}¢)")

        lines = [
            "🔔 <b>PICO DETECTADO</b>",
            prob_block,
            f"  🌡 Running max: <b>{int(round(rmax))}°C</b> @ {rmax_time}",
            market_str,
            bracket_str,
        ]
        return self.send("\n".join(line for line in lines if line))

    def alert_order_placed(self, bet, clob_mode="paper"):
        """Ordem de compra colocada com sucesso."""
        simulated = bet.get("simulated", clob_mode != "real")
        mode = "PAPER 🟡" if simulated else "REAL 💰"
        icon = "🟡" if simulated else "✅"

        ask      = bet.get("ask") or bet.get("price", 0)
        size     = bet.get("bet_size") or bet.get("size_usdc", 0)
        shares   = bet.get("shares", 0)
        profit   = bet.get("max_profit", 0)
        order_id = str(bet.get("order_id", "?"))
        p_idx    = bet.get("parcel_idx")
        parcel_s = f"P{p_idx + 1} " if p_idx is not None else ""
        bracket  = bet.get("bracket", bet.get("bracket_label", "?"))

        lines = [
            f"{icon} <b>Ordem {parcel_s}colocada [{mode}]</b>",
            "",
            f"  🎯 <b>{bracket}</b>  ask <b>{ask*100:.1f}¢</b>",
            f"  💵 ${size:.2f}  →  {shares:.2f} shares",
            f"  📈 Max profit: <b>+${profit:.2f}</b>",
            f"  🔗 ID: <code>{order_id}</code>",
        ]
        return self.send("\n".join(lines))

    def alert_order_failed(self, error, bracket=None):
        """Ordem REAL falhou (saldo insuficiente, rede, etc)."""
        bracket_str = bracket["label"] if bracket else "?"
        return self.send(
            f"❌ <b>Ordem REAL falhou</b>\n"
            f"  Bracket: {bracket_str}\n"
            f"  Erro: <code>{str(error)[:200]}</code>"
        )

    def alert_bet_blocked(self, reason, p_ensemble=0.0):
        """Bet bloqueada por critério (threshold, hora, stop-loss, saldo, etc)."""
        lines = [
            "🚫 <b>Bet bloqueada</b>",
            f"  <i>{str(reason)[:200]}</i>",
        ]
        if p_ensemble > 0:
            lines.append(f"  P(pico): {p_ensemble*100:.1f}%")
        return self.send("\n".join(lines))

    # ══════════════════════════════════════════════════════
    #  ALERTAS DE STOP-LOSS (NOVO 2026-04)
    # ══════════════════════════════════════════════════════

    def alert_stop_loss_triggered(self, position, current_temp,
                                   bid_price, realized_pnl):
        """
        Stop-loss disparou e a posição foi vendida.

        Quando temp >= bracket_hi + 1°C, o bracket está praticamente morto.
        Vendemos ao bid corrente para recuperar parte do capital.
        """
        bracket_label = position.get("bracket_label", "?")
        bracket_hi    = position.get("temp_hi", "?")
        entry_ask     = position.get("ask", 0)
        size          = position.get("size_usdc", 0)
        shares        = size / entry_ask if entry_ask > 0 else 0

        recovered = shares * bid_price
        loss_pct = (realized_pnl / size * 100) if size > 0 else 0

        # Sem stop-loss teríamos perdido tudo. Quanto salvámos?
        # Loss potencial total = -size; loss real = realized_pnl
        saved = (-size) - realized_pnl  # diferença entre loss máximo e loss real

        lines = [
            "⚠️ <b>STOP-LOSS disparado</b>",
            "",
            f"  🌡 Temp atual: <b>{current_temp:.1f}°C</b>  "
            f"(bracket <b>{int(bracket_hi)}°C+1</b>)",
            f"  🎯 Bracket: <b>{bracket_label}</b>",
            "",
            f"  📤 Vendido a <b>{bid_price*100:.1f}¢</b>",
            f"  💵 Recuperado: <b>${recovered:.2f}</b> de ${size:.2f}",
            f"  📉 PnL: <b>${realized_pnl:+.2f}</b> ({loss_pct:+.1f}%)",
        ]
        if saved > 0:
            lines.append(f"  💾 <i>Capital salvo: ${saved:.2f}</i>")
        return self.send("\n".join(lines))

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
        bracket_label = position.get("bracket_label", "?")
        bracket_hi    = position.get("temp_hi", "?")
        size          = position.get("size_usdc", 0)

        lines = [
            "🚨 <b>STOP-LOSS BLOQUEADO</b>",
            "",
            f"  🌡 Temp atual: <b>{current_temp:.1f}°C</b>  "
            f"(bracket <b>{int(bracket_hi) if isinstance(bracket_hi, (int, float)) else bracket_hi}°C+1</b>)",
            f"  🎯 Bracket: <b>{bracket_label}</b>",
            f"  💰 Em risco: <b>${size:.2f}</b>",
            "",
            f"  ❌ Motivo: <i>{str(reason)[:150]}</i>",
            "",
            "  <i>Posição vai expirar — perda provável.</i>",
        ]
        return self.send("\n".join(lines))

    # ══════════════════════════════════════════════════════
    #  ALERTAS DE RESOLUÇÃO
    # ══════════════════════════════════════════════════════

    def alert_position_resolved(self, pos):
        """Mercado resolveu — posição ganhou ou perdeu."""
        won = pos.status.value == "won"
        icon = "🏆" if won else "💸"
        result = "GANHOU" if won else "PERDEU"
        pnl_s = f"{pos.pnl_usd:+.2f}" if pos.pnl_usd is not None else "?"
        pnl_p = f"{pos.pnl_pct:+.1f}%" if pos.pnl_pct is not None else "?"

        lines = [
            f"{icon} <b>Posição resolvida</b> — {pos.date_opened}",
            "",
            f"  🎯 <b>{pos.bracket_label}</b>",
            f"  Entrada: <b>{pos.entry_ask*100:.1f}¢</b>  "
            f"({pos.shares:.2f} shares)",
            f"  Resultado: <b>{result}</b>",
            f"  P&amp;L: <b>${pnl_s}</b>  ({pnl_p})",
        ]
        return self.send("\n".join(lines))

    def alert_day_summary(self, day_str, day_positions, cumulative_summary):
        """Resumo de fim-de-dia: bets do dia + acumulado."""
        n_bets   = len(day_positions)
        n_won    = sum(1 for p in day_positions if p.status.value == "won")
        n_lost   = sum(1 for p in day_positions if p.status.value == "lost")
        invested = sum(p.size_usdc for p in day_positions)
        day_pnl  = sum(p.pnl_usd for p in day_positions
                       if p.pnl_usd is not None)
        roi = (day_pnl / invested * 100) if invested > 0 else 0.0

        if n_bets == 0:
            lines = [
                f"📅 <b>Fim do dia</b> — {day_str}",
                "",
                "  💤 Sem bets hoje.",
                "  <i>O modelo não viu sinais suficientemente fortes.</i>",
            ]
        else:
            pnl_icon = "📈" if day_pnl >= 0 else "📉"
            lines = [
                f"📅 <b>Fim do dia</b> — {day_str}",
                "",
                f"  Bets: <b>{n_bets}</b>  "
                f"(✅ {n_won}  ❌ {n_lost})",
                f"  Investido: <b>${invested:.2f}</b>",
                f"  {pnl_icon} P&amp;L: <b>${day_pnl:+.2f}</b>  ({roi:+.1f}%)",
                "",
            ]
            for pos in day_positions:
                if pos.status.value == "won":
                    st_icon = "✅"
                elif pos.status.value == "lost":
                    st_icon = "❌"
                else:
                    st_icon = "⏳"
                pnl_s = (f"{pos.pnl_usd:+.2f}"
                         if pos.pnl_usd is not None else "—")
                lines.append(
                    f"  {st_icon} <b>{pos.bracket_label[:18]}</b>  "
                    f"{pos.entry_ask*100:.0f}¢  ${pnl_s}"
                )

        # Cumulativo
        s  = cumulative_summary
        nc = s["n_won"] + s["n_lost"]
        wr_s = f"{s['n_won']/nc*100:.0f}%" if nc > 0 else "—"
        cum_icon = "📈" if s["total_pnl_usd"] >= 0 else "📉"
        lines += [
            "",
            "─────────────────",
            "<b>Acumulado</b>",
            f"  {s['n_won']}W / {s['n_lost']}L  "
            f"(win rate <b>{wr_s}</b>)",
            f"  Investido: ${s['total_invested']:.2f}",
            f"  {cum_icon} P&amp;L: <b>${s['total_pnl_usd']:+.2f}</b> "
            f"({s['total_pnl_pct']:+.1f}%)",
        ]
        if s.get("n_open", 0) > 0:
            lines.append(f"  ⏳ Posições abertas: {s['n_open']}")
        return self.send("\n".join(lines))

    def alert_zone_change(self, p, zone):
        """Probabilidade mudou de zona (notifica só na transição)."""
        icons  = {0: "⚪", 1: "🟠", 2: "🟡", 3: "🟢"}
        labels = {0: "abaixo de 30%",
                  1: "30-60% — atenção",
                  2: "60-80% — forte",
                  3: "≥ 80% — muito forte"}
        return self.send(
            f"{icons.get(zone, '⚪')} <b>P(pico) entrou em nova zona</b>\n"
            f"  Agora: <b>{p*100:.0f}%</b>  "
            f"<i>({labels.get(zone, '?')})</i>"
        )

    # ══════════════════════════════════════════════════════
    #  DETECÇÃO DE ZONA
    # ══════════════════════════════════════════════════════

    def p_zone(self, p):
        if p >= 0.80: return 3
        if p >= 0.60: return 2
        if p >= 0.30: return 1
        return 0

    def zone_changed(self, p):
        z = self.p_zone(p)
        if z != self._last_p_zone:
            self._last_p_zone = z
            return True
        return False

    # ══════════════════════════════════════════════════════
    #  DASHBOARD COMPLETA (periódica 30 em 30 min)
    # ══════════════════════════════════════════════════════

    def dashboard(self, today, p, rmax, rmax_time,
                  temp_now=None, forecast_max=None,
                  market=None, bracket=None, ev=None,
                  peak_detected=False, bet=None,
                  clob_mode=None, trading_mode=None,
                  chart=None, reason="periodic",
                  positions_summary=None,
                  om_forecast=None,
                  forecast_agreement=None,
                  ensemble_result=None,
                  phased=None,
                  usdc_balance=None,
                  bet_blocked_reason=None):
        """
        Dashboard completa enviada periodicamente (default 30min).
        Combina: estado actual, ensemble, mercado, bet, P&L acumulado.
        """
        # Modo (string ou Enum)
        mode = trading_mode or clob_mode or "paper"
        mode_str = mode.value.upper() if hasattr(mode, "value") else \
                   str(mode).replace("TradingMode.", "").upper()
        mode_icon = "🟢" if mode_str == "REAL" else "🟡"
        now_str = datetime.now().strftime("%H:%M")

        lines = [
            f"{mode_icon} <b>Munich Bot Live</b>  "
            f"[{mode_str}]  {today}  {now_str}",
            "  ─────────────────────────────────────",
            "",
        ]

        # ── Saldo ─────────────────────────────────────
        if usdc_balance is not None:
            bal_icon = "💵" if usdc_balance >= 10 else "⚠️"
            lines.append(
                f"{bal_icon} <b>Saldo:</b> ${usdc_balance:,.2f} USDC"
            )
            lines.append("")

        # ── Chart ASCII (se disponível) ───────────────
        if chart:
            lines.append("🌡 <b>Curva de temperatura hoje</b>")
            lines.extend(chart)
            lines.append("")

        # ── Temperatura actual ────────────────────────
        temp_str = f"{int(round(temp_now))}°C" if temp_now is not None else "—"
        fc_str = f"   prev WU {forecast_max['temp_max']}°C" if forecast_max else ""
        lines += [
            "🌡 <b>Temperatura</b>",
            f"  Agora: <b>{temp_str}</b>   "
            f"Max: <b>{int(round(rmax))}°C</b> @ {rmax_time}{fc_str}",
            "",
        ]

        # ── Dual Forecast ─────────────────────────────
        if om_forecast:
            lines.append("🌤 <b>Previsão Dual</b>")
            if forecast_max:
                lines.append(
                    f"  🟦 WU: max <b>{forecast_max['temp_max']}°C</b>"
                )
            lines.append(
                f"  🟣 OM: max <b>{om_forecast['temp_max']}°C</b>"
            )
            if forecast_agreement:
                if forecast_agreement.get("valid"):
                    diff = forecast_agreement.get("diff", "?")
                    cons = forecast_agreement.get("consensus_max", "?")
                    lines.append(
                        f"  ✅ Concordam (diff {diff}°C)  "
                        f"consenso <b>{cons}°C</b>"
                    )
                else:
                    reason_fc = forecast_agreement.get("reason", "?")
                    lines.append(f"  ❌ Discordam — {reason_fc}")
            lines.append("")

        # ── Modelo (LightGBM puro) ────────────────────
        if ensemble_result:
            p_ens = ensemble_result["p_ensemble"]
            peak_str = "  ✓ <b>PICO DETECTADO</b>" if peak_detected else ""
            p_bar = _tg_bar(p_ens, width=10)
            lines.append("🧠 <b>Modelo LightGBM — P(pico)</b>")
            lines.append(
                f"  {p_bar}  <b>{p_ens*100:.1f}%</b>{peak_str}"
            )
            lines.append("")
        else:
            p_bar = _tg_bar(p, width=10)
            peak_str = "  ✓ <b>PICO DETECTADO</b>" if peak_detected else ""
            lines.append("🧠 <b>Modelo — P(pico)</b>")
            lines.append(f"  {p_bar}  <b>{p*100:.1f}%</b>{peak_str}")
            lines.append("")

        # ── Estratégia (Single ou Phased) ─────────────
        if phased is not None:
            is_single = (hasattr(phased, 'bought')
                         and not hasattr(phased, 'parcel_bought'))
            # check robusto: SingleEntry tem parcel_bought property mas é lista [b, F, F]
            # melhor verificar n_parcels_bought vs parcel_size
            try:
                if isinstance(phased.parcel_bought, list) and \
                   sum(1 for x in phased.parcel_bought if x is not False) <= 1 and \
                   not phased.parcel_bought[1] and not phased.parcel_bought[2]:
                    is_single = True
            except Exception:
                pass

            if is_single:
                # SingleEntry
                lines.append("🎯 <b>Estratégia SINGLE</b>")
                if phased.bought:
                    if getattr(phased, 'sold_by_stop', False):
                        lines.append(
                            f"  ${phased.parcel_size:.0f}  "
                            f"⚠️ vendido por stop-loss"
                        )
                    else:
                        lines.append(
                            f"  ${phased.parcel_size:.0f}  ✅ comprado"
                        )
                else:
                    lines.append(
                        f"  ${phased.parcel_size:.0f}  ⏳ aguardar sinal"
                    )
                lines.append("")
            else:
                # PhasedEntry
                p_icons_done = ["✅🌅", "✅⚡", "✅🔥"]
                p_icons_wait = ["⬜🌅", "⬜⚡", "⬜🔥"]
                parts = [p_icons_done[i] if phased.parcel_bought[i]
                         else p_icons_wait[i] for i in range(3)]
                total_inv = phased.total_invested
                total_max = phased.parcel_size * 3
                lines.append("🎯 <b>Estratégia PHASED</b>")
                lines.append(
                    f"  {' '.join(parts)}  "
                    f"({phased.n_parcels_bought}/3  "
                    f"${total_inv:.0f}/${total_max:.0f})"
                )
                lines.append("")

        # ── Bet bloqueada ─────────────────────────────
        if bet_blocked_reason:
            lines.append(
                f"🚫 <b>Bloqueio:</b> <i>{str(bet_blocked_reason)[:100]}</i>"
            )
            lines.append("")

        # ── Mercado ───────────────────────────────────
        if not market:
            lines.append("📋 <b>Mercado</b>: ainda não abriu")
            lines.append("")
        else:
            if market.get("brackets"):
                best = max(market["brackets"],
                           key=lambda b: b.get("ask") or b.get("price") or 0)
                best_ask = best.get("ask") or best.get("price", 0)
                lines.append("📋 <b>Polymarket</b>")
                lines.append(
                    f"  🏆 Favorito: <b>{best['label']}</b>  "
                    f"({best_ask*100:.0f}¢)"
                )
                lines.append("")

            # Tabela de brackets (top 8)
            if bracket and market.get("brackets"):
                bks = market["brackets"][:8]
                lines.append("<pre>")
                lines.append("Bracket          Ask   Visual")
                lines.append("─" * 32)
                for b in bks:
                    arrow = "→" if b["label"] == bracket["label"] else " "
                    ask_val = b.get("ask") or b.get("price") or 0
                    bar = _tg_bar(ask_val, width=8)
                    label_padded = b['label'][:15].ljust(15)
                    lines.append(
                        f"{arrow}{label_padded} {ask_val*100:>4.0f}¢  {bar}"
                    )
                lines.append("</pre>")
                lines.append("")

        # ── Edge / EV ─────────────────────────────────
        if bracket and ev:
            ev_icon = "✅" if ev["ev_positive"] else "❌"
            ask_val = ev.get("ask",
                             bracket.get("ask", bracket.get("price", 0)))
            lines.append(f"📊 <b>Edge</b>  [{bracket['label']}]")
            lines.append(
                f"  {ev_icon} ask {ask_val*100:.1f}¢  "
                f"EV {ev['ev_cents']:+.1f}¢  "
                f"edge {ev['edge_pct']:+.1f}%"
            )
            lines.append("")

        # ── Bet aberta ────────────────────────────────
        if bet:
            simulated = bet.get("simulated", mode_str != "REAL")
            sim_label = "PAPER" if simulated else "REAL"
            p_idx = bet.get("parcel_idx")
            parcel_s = f"P{p_idx + 1} " if p_idx is not None else ""
            ask  = bet.get("ask") or bet.get("price", 0)
            size = bet.get("bet_size") or bet.get("size_usdc", 0)
            bracket_lbl = bet.get('bracket', bet.get('bracket_label', '?'))
            lines.append(f"💰 <b>Bet {parcel_s}[{sim_label}]</b>")
            lines.append(
                f"  {bracket_lbl}  ask {ask*100:.1f}¢"
            )
            lines.append(
                f"  ${size:.2f}  →  {bet.get('shares', 0):.2f} shares  "
                f"max +${bet.get('max_profit', 0):.2f}"
            )
        elif not bet_blocked_reason:
            lines.append("💤 Sem bet ainda")

        # ── P&L acumulado ─────────────────────────────
        if positions_summary:
            s  = positions_summary
            nc = s["n_won"] + s["n_lost"]
            if nc > 0:
                wr = s["n_won"] / nc * 100
                wr_icon = "📈" if s["total_pnl_usd"] >= 0 else "📉"
                lines.append("")
                lines.append(f"{wr_icon} <b>Acumulado</b>")
                lines.append(
                    f"  {s['n_won']}W / {s['n_lost']}L  "
                    f"win rate <b>{wr:.0f}%</b>"
                )
                lines.append(
                    f"  P&amp;L: <b>${s['total_pnl_usd']:+.2f}</b>  "
                    f"({s['total_pnl_pct']:+.1f}%)"
                )
                if s.get("n_open", 0) > 0:
                    lines.append(f"  ⏳ Abertas: {s['n_open']}")

        # Rodapé
        reason_map = {
            "periodic":    "⏱ periódico (30min)",
            "zone_change": "⚡ mudança de zona",
            "market_open": "📋 mercado abriu",
            "stop_loss":   "⚠️ stop-loss disparou",
        }
        lines.append("")
        lines.append(f"<i>{reason_map.get(reason, reason)}</i>")

        return self.send("\n".join(lines))


# ══════════════════════════════════════════════════════
#  HELPER
# ══════════════════════════════════════════════════════

def _tg_bar(p, width=10):
    """Barra de progresso com blocos unicode."""
    p_clamped = min(max(p, 0), 1)
    filled = round(p_clamped * width)
    return "█" * filled + "░" * (width - filled)