"""
tg.py — Telegram Bot com menu interativo e notificações
=======================================================
Suporta:
  - Menu interativo com comandos: /menu, /resumo, /posicoes, /ultimas, /status
  - Notificações proativas de trading (ordens, stop-loss, resoluções)
  - Dashboard periódico multi-cidade
  - Resumo diário com estatísticas detalhadas
  - Detecção de pico e mudança de zona de probabilidade

Variáveis de ambiente:
    TELEGRAM_TOKEN=***
    TELEGRAM_CHAT_ID=...

Comandos disponíveis:
  /menu - Mostra menu interativo com botões
  /resumo - Resumo do dia: PnL, nº de apostas, % win rate
  /posicoes - Posições abertas atuais
  /ultimas - Últimas 5 vitórias
  /status - Status do bot em todas as cidades

Notas (2026-04):
  - Modelo LightGBM puro: removidas referências a XGB e z-score nos alertas
  - Stop-loss adicionado em alert_stop_loss_triggered
  - UX refinada: mensagens mais concisas, emojis consistentes, formatação clara
  - Suporte a botões inline para melhor experiência do usuário
"""

import os
import json
import requests
import threading
from datetime import datetime, date
from pathlib import Path
from typing import Dict, List, Optional, Any

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# Importações para Telegram Bot
try:
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot
    from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, CallbackContext
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False
    print("[TG] python-telegram-bot não instalado - modo compatibilidade")


class TG:
    """Telegram Bot com menu interativo e notificações de trading."""

    def __init__(self):
        self.token = os.environ.get("TELEGRAM_TOKEN", "")
        self.chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
        self.enabled = bool(self.token and self.chat_id)
        self._last_p_zone = -1
        self.updater = None
        self.polling_active = False
        
        if not self.enabled:
            print("  [TG] TELEGRAM_TOKEN ou TELEGRAM_CHAT_ID não definidos — "
                  "notificações desactivadas")
        elif TELEGRAM_AVAILABLE:
            print("  [TG] Bot com menu interativo inicializado")
        else:
            print("  [TG] Modo compatibilidade - apenas envio de mensagens")

    def start_polling(self, bot_states: Dict = None) -> bool:
        """Inicia polling para receber comandos do usuário."""
        if not self.enabled or not TELEGRAM_AVAILABLE:
            return False
        
        try:
            self.updater = Updater(token=self.token)
            dispatcher = self.updater.dispatcher
            
            # Armazenar estados do bot para acesso nos handlers
            self.bot_states = bot_states or {}
            
            # Adicionar handlers de comandos
            dispatcher.add_handler(CommandHandler("menu", self._cmd_menu))
            dispatcher.add_handler(CommandHandler("resumo", self._cmd_summary))
            dispatcher.add_handler(CommandHandler("posicoes", self._cmd_positions))
            dispatcher.add_handler(CommandHandler("ultimas", self._cmd_recent_wins))
            dispatcher.add_handler(CommandHandler("status", self._cmd_status))
            
            # Adicionar handler para botões inline
            dispatcher.add_handler(CallbackQueryHandler(self._handle_button))
            
            # Iniciar polling em thread separada
            threading.Thread(target=self.updater.start_polling, 
                           kwargs={"poll_interval": 1.0}, 
                           daemon=True).start()
            
            self.polling_active = True
            print("  [TG] Polling iniciado - bot pode receber comandos")
            return True
            
        except Exception as e:
            print(f"  [TG] Erro ao iniciar polling: {e}")
            return False

    def stop_polling(self):
        """Para o polling."""
        if self.updater and self.polling_active:
            self.updater.stop()
            self.polling_active = False
            print("  [TG] Polling parado")

    def _cmd_menu(self, update: Update, context: CallbackContext):
        """Handler para /menu - mostra menu interativo."""
        keyboard = [
            [InlineKeyboardButton("📊 Resumo Hoje", callback_data='resumo_hoje')],
            [InlineKeyboardButton("📂 Posições Abertas", callback_data='posicoes_abertas')],
            [InlineKeyboardButton("🏆 Últimas Ganhas", callback_data='ultimas_ganhadas')],
            [InlineKeyboardButton("⚙️ Status Bot", callback_data='status_bot')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        update.message.reply_text(
            "🤖 <b>Menu do Bot</b>\n\n"
            "Escolha uma opção para ver detalhes:",
            reply_markup=reply_markup
        )

    def _cmd_summary(self, update: Update, context: CallbackContext):
        """Handler para /resumo - mostra resumo do dia."""
        try:
            summary = self._generate_daily_summary()
            update.message.reply_text(summary, parse_mode="HTML")
        except Exception as e:
            update.message.reply_text(f"❌ Erro ao gerar resumo: {str(e)}")

    def _cmd_positions(self, update: Update, context: CallbackContext):
        """Handler para /posicoes - mostra posições abertas."""
        try:
            positions = self._get_open_positions()
            update.message.reply_text(positions, parse_mode="HTML")
        except Exception as e:
            update.message.reply_text(f"❌ Erro ao obter posições: {str(e)}")

    def _cmd_recent_wins(self, update: Update, context: CallbackContext):
        """Handler para /ultimas - mostra últimas vitórias."""
        try:
            wins = self._get_recent_wins()
            update.message.reply_text(wins, parse_mode="HTML")
        except Exception as e:
            update.message.reply_text(f"❌ Erro ao obter vitórias: {str(e)}")

    def _cmd_status(self, update: Update, context: CallbackContext):
        """Handler para /status - mostra status do bot."""
        try:
            status = self._get_bot_status()
            update.message.reply_text(status, parse_mode="HTML")
        except Exception as e:
            update.message.reply_text(f"❌ Erro ao obter status: {str(e)}")

    def _handle_button(self, update: Update, context: CallbackContext):
        """Handler para botões inline."""
        query = update.callback_query
        query.answer()
        
        if query.data == 'resumo_hoje':
            summary = self._generate_daily_summary()
            query.edit_message_text(summary, parse_mode="HTML")
        elif query.data == 'posicoes_abertas':
            positions = self._get_open_positions()
            query.edit_message_text(positions, parse_mode="HTML")
        elif query.data == 'ultimas_ganhadas':
            wins = self._get_recent_wins()
            query.edit_message_text(wins, parse_mode="HTML")
        elif query.data == 'status_bot':
            status = self._get_bot_status()
            query.edit_message_text(status, parse_mode="HTML")

    def _generate_daily_summary(self) -> str:
        """Gera resumo do dia a partir dos logs."""
        try:
            from trade_ledger import read_events
            from pathlib import Path
            
            today = date.today().isoformat()
            events = read_events()
            
            # Filtrar eventos de hoje
            today_events = [e for e in events if e.get('date') == today]
            
            if not today_events:
                return "📅 <b>Resumo de Hoje</b>\n\n💤 Sem trades hoje."
            
            # Calcular estatísticas
            total_trades = len(today_events)
            total_invested = sum(e.get('size_usdc', 0) for e in today_events)
            total_pnl = sum(e.get('pnl', 0) for e in today_events)
            
            # Calcular win rate
            wins = sum(1 for e in today_events if e.get('pnl', 0) > 0)
            win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
            
            roi = (total_pnl / total_invested * 100) if total_invested > 0 else 0
            
            # Formatar mensagem
            lines = [
                f"📊 <b>Resumo de Hoje</b> — {today}",
                "",
                f"  🎯 Trades: <b>{total_trades}</b>",
                f"  💰 Investido: <b>${total_invested:.2f}</b>",
                f"  📈 PnL: <b>${total_pnl:+.2f}</b> ({roi:+.1f}%)",
                f"  🏆 Win Rate: <b>{win_rate:.1f}%</b> ({wins}/{total_trades})",
                "",
                "<b>Detalhes dos trades:</b>"
            ]
            
            # Adicionar detalhes de cada trade
            for i, event in enumerate(today_events[:5]):  # Mostrar até 5 trades
                city = event.get('city', 'Unknown')
                bracket = event.get('bracket_label', 'Unknown')
                pnl = event.get('pnl', 0)
                icon = "✅" if pnl > 0 else "❌"
                
                lines.append(
                    f"  {icon} {city}: {bracket} (${pnl:+.2f})"
                )
            
            if len(today_events) > 5:
                lines.append(f"  ... e mais {len(today_events) - 5} trades")
            
            return "\n".join(lines)
            
        except Exception as e:
            return f"❌ Erro ao gerar resumo: {str(e)}"

    def _get_open_positions(self) -> str:
        """Obtém posições abertas atuais."""
        try:
            from polymarket_clob import PositionStatus
            from pathlib import Path
            
            positions_text = []
            
            # Verificar paper positions
            paper_positions_path = Path("live_bot_logs") / "paper_positions.json"
            if paper_positions_path.exists():
                try:
                    with open(paper_positions_path, 'r') as f:
                        paper_positions = json.load(f)
                    
                    for pos in paper_positions:
                        if pos.get('status') == 'open':
                            city = pos.get('city', 'Unknown')
                            bracket = pos.get('bracket_label', 'Unknown')
                            entry_ask = pos.get('ask', 0)
                            size_usdc = pos.get('size_usdc', 0)
                            
                            positions_text.append(
                                f"📂 <b>{city}</b>\n"
                                f"  🎯 {bracket}\n"
                                f"  💵 Entrada: {entry_ask*100:.1f}¢\n"
                                f"  🏦 Size: ${size_usdc:.2f}\n"
                            )
                except Exception as e:
                    positions_text.append(f"❌ Erro ao ler paper positions: {str(e)}")
            
            # Verificar real positions
            real_positions_path = Path("live_bot_logs") / "real_positions.json"
            if real_positions_path.exists():
                try:
                    with open(real_positions_path, 'r') as f:
                        real_positions = json.load(f)
                    
                    for pos in real_positions:
                        if pos.get('status') == 'open':
                            city = pos.get('city', 'Unknown')
                            bracket = pos.get('bracket_label', 'Unknown')
                            entry_ask = pos.get('ask', 0)
                            size_usdc = pos.get('size_usdc', 0)
                            
                            positions_text.append(
                                f"💰 <b>{city}</b>\n"
                                f"  🎯 {bracket}\n"
                                f"  💵 Entrada: {entry_ask*100:.1f}¢\n"
                                f"  🏦 Size: ${size_usdc:.2f}\n"
                            )
                except Exception as e:
                    positions_text.append(f"❌ Erro ao ler real positions: {str(e)}")
            
            if not positions_text:
                return "📂 <b>Posições Abertas</b>\n\n✅ Sem posições abertas no momento."
            
            header = "📂 <b>Posições Abertas</b>\n\n"
            return header + "\n".join(positions_text)
            
        except Exception as e:
            return f"❌ Erro ao obter posições: {str(e)}"

    def _get_recent_wins(self) -> str:
        """Obtém últimas 5 vitórias."""
        try:
            from trade_ledger import read_events
            from pathlib import Path
            
            events = read_events()
            
            # Filtrar vitórias (pnl > 0) e ordenar por data
            wins = [
                e for e in events 
                if e.get('pnl', 0) > 0 and e.get('status') == 'won'
            ]
            wins.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
            recent_wins = wins[:5]
            
            if not recent_wins:
                return "🏆 <b>Últimas Vitórias</b>\n\n💤 Sem vitórias recentes."
            
            lines = [
                "🏆 <b>Últimas 5 Vitórias</b>",
                ""
            ]
            
            for i, win in enumerate(recent_wins, 1):
                city = win.get('city', 'Unknown')
                bracket = win.get('bracket_label', 'Unknown')
                entry_ask = win.get('ask', 0)
                pnl = win.get('pnl', 0)
                timestamp = win.get('timestamp', '')
                
                # Extrair data do timestamp
                if 'T' in timestamp:
                    date_str = timestamp.split('T')[0]
                else:
                    date_str = timestamp[:10]
                
                lines.append(
                    f"🥇 {i}. <b>{city}</b> — {date_str}\n"
                    f"   🎯 {bracket}\n"
                    f"   💵 Entrada: {entry_ask*100:.1f}¢\n"
                    f"   📈 PnL: <b>+${pnl:.2f}</b>\n"
                )
            
            return "\n".join(lines)
            
        except Exception as e:
            return f"❌ Erro ao obter vitórias: {str(e)}"

    def _get_bot_status(self) -> str:
        """Obtém status do bot em todas as cidades."""
        try:
            if not hasattr(self, 'bot_states') or not self.bot_states:
                return "⚙️ <b>Status do Bot</b>\n\n❌ Estados do bot não disponíveis."
            
            lines = [
                "⚙️ <b>Status do Bot</b>",
                ""
            ]
            
            for city_name, state in self.bot_states.items():
                if hasattr(state, 'daily_stats'):
                    stats = state.daily_stats
                    trades_count = len(getattr(stats, 'trades', []))
                    daily_pnl = getattr(stats, 'daily_pnl', 0.0)
                    
                    icon = "🟢" if daily_pnl >= 0 else "🔴"
                    lines.append(
                        f"{icon} <b>{city_name}</b>\n"
                        f"   📊 Trades: {trades_count}\n"
                        f"   💰 PnL: ${daily_pnl:+.2f}\n"
                    )
                else:
                    lines.append(f"⚪ <b>{city_name}</b>\n   📊 Status: desconhecido\n")
            
            lines.append("")
            lines.append("🤖 Bot está ativo e monitorando as cidades.")
            
            return "\n".join(lines)
            
        except Exception as e:
            return f"❌ Erro ao obter status: {str(e)}"

    def send(self, text: str) -> bool:
        """Envia mensagem; devolve True se sucesso."""
        if not self.enabled:
            return False
        
        # Modo compatibilidade - sem telegram.ext
        if not TELEGRAM_AVAILABLE:
            try:
                r = requests.post(
                    f"https://api.telegram.org/bot{self.token}/sendMessage",
                    json={"chat_id": self.chat_id, "text": text,
                          "parse_mode": "HTML",
                          "disable_web_page_preview": True},
                    timeout=10,
                )
                if r.status_code != 200:
                    print(f"  [TG] sendMessage falhou: HTTP {r.status_code} — {r.text[:200]}")
                    return False
                return True
            except Exception as e:
                print(f"  [TG] sendMessage exception: {e}")
                return False
        
        # Modo com telegram.ext
        try:
            from telegram import Bot
            bot = Bot(token=self.token)
            bot.send_message(chat_id=self.chat_id, text=text, 
                           parse_mode="HTML", disable_web_page_preview=True)
            return True
        except Exception as e:
            print(f"  [TG] send_message exception: {e}")
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
        raw_ask  = bet.get("raw_ask")
        size     = bet.get("bet_size") or bet.get("size_usdc", 0)
        shares   = bet.get("shares", 0)
        profit = bet.get("max_profit")
        order_id = str(bet.get("order_id", "?"))
        p_idx    = bet.get("parcel_idx")
        parcel_s = f"P{p_idx + 1} " if p_idx is not None else ""
        bracket  = bet.get("bracket", bet.get("bracket_label", "?"))
        city     = bet.get("city", "?")
        market   = bet.get("market_slug", "")
        p_ens    = bet.get("p_ensemble")
        rmax     = bet.get("running_max")

        if profit is None or (isinstance(profit, float) and profit <= 0.0001):
            try:
                ask_f = float(ask if ask is not None else 0.0)
                shares_f = float(shares if shares is not None else 0.0)
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
            except Exception:
                profit = 0.0

        lines = [
            f"{icon} <b>Ordem {parcel_s}colocada [{mode}]</b>",
            "",
            f"  🏙 <b>{city}</b>",
            f"  🎯 <b>{bracket}</b>  ask <b>{ask*100:.1f}¢</b>",
            f"  🔬 raw ask <b>{raw_ask*100:.1f}¢</b>" if raw_ask is not None else None,
            f"  🧠 P(pico) <b>{p_ens*100:.1f}%</b>" if p_ens is not None else None,
            f"  📍 RMax <b>{rmax:.1f}°C</b>" if rmax is not None else None,
            f"  💵 ${size:.2f}  →  {shares:.2f} shares",
            f"  📈 Max profit: <b>+${profit:.2f}</b>",
            f"  🔎 <code>{market}</code>" if market else None,
            f"  🔗 ID: <code>{order_id}</code>",
        ]
        return self.send("\n".join(line for line in lines if line))

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

    def alert_multi_city_summary(self, mode_str, total_pnl, n_trades, cities_data):
        """Resumo consolidado de todas as cidades."""
        mode_icon = "🟢" if mode_str == "REAL" else "🟡"
        pnl_icon = "📈" if total_pnl >= 0 else "📉"
        
        lines = [
            f"{mode_icon} <b>Relatório Multi-Cidade</b> — {datetime.now().strftime('%H:%M')}",
            f"  Modo: <b>{mode_str}</b>",
            f"  Apostas hoje: <b>{n_trades}</b>",
            f"  {pnl_icon} P&L Total: <b>${total_pnl:+.2f}</b>",
            "",
            "<b>Top Cidades (PnL):</b>"
        ]
        
        # Ordenar cidades por PnL e mostrar top 5
        top_cities = sorted(cities_data, key=lambda x: x['pnl'], reverse=True)
        for c in top_cities[:8]:
            c_icon = "✅" if c['pnl'] > 0 else ("❌" if c['pnl'] < 0 else "⚪")
            lines.append(f"  {c_icon} {c['name'].title()}: <b>${c['pnl']:+.2f}</b>")
            
        return self.send("\n".join(lines))

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

        # ── Forecast ──────────────────────────────────
        if om_forecast:
            lines.append("🌤 <b>Previsão</b>")
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
