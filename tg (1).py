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

Notas (2026-06):
  - Migrado para python-telegram-bot v20+ (API assíncrona)
  - Updater/dispatcher/CallbackContext substituídos por Application/ContextTypes
  - Todos os handlers tornados async (obrigatório na v20+)
  - query.answer() agora com await (fix crítico para botões inline)
  - send() simplificado para HTTP direto via requests (evita conflitos de event loop)
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

# Importações para Telegram Bot (v20+)
try:
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot
    from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
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
        """Inicia polling para receber comandos do usuário (v20+)."""
        if not self.enabled or not TELEGRAM_AVAILABLE:
            return False

        self.bot_states = bot_states or {}
        self._app = None

        async def _run():
            import asyncio
            app = Application.builder().token(self.token).build()

            app.add_handler(CommandHandler("menu", self._cmd_menu))
            app.add_handler(CommandHandler("resumo", self._cmd_summary))
            app.add_handler(CommandHandler("posicoes", self._cmd_positions))
            app.add_handler(CommandHandler("ultimas", self._cmd_recent_wins))
            app.add_handler(CommandHandler("status", self._cmd_status))
            app.add_handler(CommandHandler("charts", self._cmd_charts))
            app.add_handler(CallbackQueryHandler(self._handle_button))

            self._app = app
            await app.initialize()
            await app.start()
            await app.updater.start_polling(poll_interval=1.0)
            self.polling_active = True
            print("  [TG] Polling iniciado - bot pode receber comandos")

            # Mantém a task viva sem bloquear a thread principal
            while self.polling_active:
                await asyncio.sleep(1)

            await app.updater.stop()
            await app.stop()
            await app.shutdown()

        def _thread():
            import asyncio
            try:
                asyncio.run(_run())
            except Exception as e:
                print(f"  [TG] Erro no polling thread: {e}")

        threading.Thread(target=_thread, daemon=True).start()
        return True

    def stop_polling(self):
        """Para o polling."""
        self.polling_active = False
        print("  [TG] Polling parado")

    async def _cmd_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler para /menu - mostra menu interativo."""
        keyboard = [
            [InlineKeyboardButton("📊 Resumo Hoje", callback_data='resumo_hoje')],
            [InlineKeyboardButton("📂 Posições Abertas", callback_data='posicoes_abertas')],
            [InlineKeyboardButton("🏆 Últimas Ganhas", callback_data='ultimas_ganhadas')],
            [InlineKeyboardButton("📈 Charts por Cidade", callback_data='charts_menu')],
            [InlineKeyboardButton("⚙️ Status Bot", callback_data='status_bot')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "🤖 <b>Menu do Bot</b>\n\nEscolha uma opção para ver detalhes:",
            reply_markup=reply_markup,
            parse_mode="HTML"
        )

    async def _cmd_charts(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler para /charts - mostra menu de cidades para ver charts."""
        text, keyboard = self._build_charts_menu()
        reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="HTML")

    async def _cmd_summary(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler para /resumo - mostra resumo do dia."""
        try:
            summary = self._generate_daily_summary()
            await update.message.reply_text(summary, parse_mode="HTML")
        except Exception as e:
            await update.message.reply_text(f"❌ Erro ao gerar resumo: {str(e)}")

    async def _cmd_positions(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler para /posicoes - mostra posições abertas."""
        try:
            positions = self._get_open_positions()
            await update.message.reply_text(positions, parse_mode="HTML")
        except Exception as e:
            await update.message.reply_text(f"❌ Erro ao obter posições: {str(e)}")

    async def _cmd_recent_wins(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler para /ultimas - mostra últimas vitórias."""
        try:
            wins = self._get_recent_wins()
            await update.message.reply_text(wins, parse_mode="HTML")
        except Exception as e:
            await update.message.reply_text(f"❌ Erro ao obter vitórias: {str(e)}")

    async def _cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler para /status - mostra status do bot."""
        try:
            status = self._get_bot_status()
            await update.message.reply_text(status, parse_mode="HTML")
        except Exception as e:
            await update.message.reply_text(f"❌ Erro ao obter status: {str(e)}")

    async def _handle_button(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler para botões inline."""
        query = update.callback_query
        await query.answer()  # CRÍTICO: deve ser await, senão o botão fica a girar

        # Dispatch simples para funções sem argumentos
        dispatch = {
            'resumo_hoje':      self._generate_daily_summary,
            'posicoes_abertas': self._get_open_positions,
            'ultimas_ganhadas': self._get_recent_wins,
            'status_bot':       self._get_bot_status,
        }

        # Menu de charts
        if query.data == 'charts_menu':
            text, keyboard = self._build_charts_menu()
            reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
            try:
                await query.edit_message_text(
                    text, reply_markup=reply_markup, parse_mode="HTML"
                )
            except Exception as e:
                await query.edit_message_text(f"❌ Erro: {str(e)}", parse_mode="HTML")
            return

        # Chart de uma cidade específica: callback_data = "chart:{city_name}"
        if query.data.startswith('chart:'):
            city_name = query.data[len('chart:'):]
            try:
                text, keyboard = self._generate_city_charts_message(city_name)
                reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
                # Se a mensagem for muito longa, dividir
                if len(text) <= 4000:
                    await query.edit_message_text(
                        text, reply_markup=reply_markup, parse_mode="HTML"
                    )
                else:
                    # Enviar em 2 partes: temperatura, depois brackets
                    # Parte 1: header + temperatura chart
                    await query.edit_message_text(text[:4000], parse_mode="HTML")
                    # Parte 2: resto (se couber)
                    if len(text) > 4000:
                        await context.bot.send_message(
                            chat_id=query.message.chat_id,
                            text=text[4000:],
                            parse_mode="HTML",
                            reply_markup=reply_markup,
                        )
            except Exception as e:
                await query.edit_message_text(f"❌ Erro: {str(e)}", parse_mode="HTML")
            return

        fn = dispatch.get(query.data)
        if fn:
            try:
                await query.edit_message_text(fn(), parse_mode="HTML")
            except Exception as e:
                await query.edit_message_text(f"❌ Erro: {str(e)}", parse_mode="HTML")

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
        """Envia mensagem via HTTP direto (thread-safe, compatível com v20+)."""
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
            if r.status_code != 200:
                print(f"  [TG] sendMessage falhou: HTTP {r.status_code} — {r.text[:200]}")
                return False
            return True
        except Exception as e:
            print(f"  [TG] sendMessage exception: {e}")
            return False

    def send_menu(self) -> bool:
        """Envia o menu interativo com botões inline."""
        if not self.enabled:
            return False
        
        # Criar o menu com botões inline
        keyboard = [
            [{"text": "📊 Resumo Hoje", "callback_data": "resumo_hoje"}],
            [{"text": "📂 Posições Abertas", "callback_data": "posicoes_abertas"}],
            [{"text": "🏆 Últimas Ganhas", "callback_data": "ultimas_ganhadas"}],
            [{"text": "📈 Charts por Cidade", "callback_data": "charts_menu"}],
            [{"text": "⚙️ Status Bot", "callback_data": "status_bot"}]
        ]
        
        menu_text = (
            "🤖 <b>Menu do Bot</b>\n\n"
            "Escolha uma opção para ver detalhes:"
        )
        
        # Enviar mensagem diretamente com a API do Telegram
        import json
        reply_markup = {"inline_keyboard": keyboard}
        
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        data = {
            "chat_id": self.chat_id,
            "text": menu_text,
            "parse_mode": "HTML",
            "reply_markup": json.dumps(reply_markup)
        }
        
        import requests
        try:
            response = requests.post(url, json=data, timeout=10)
            if response.status_code == 200:
                print("  [TG] Menu enviado com sucesso")
                return True
            else:
                print(f"  [TG] Erro ao enviar menu: {response.status_code}")
                return False
        except Exception as e:
            print(f"  [TG] Erro ao enviar menu: {e}")
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
        """
        Resumo consolidado de todas as cidades.

        cities_data (lista de dicts, campos opcionais além de name/pnl):
          - p_ensemble: float 0..1   (prob actual do modelo)
          - threshold:  float 0..1   (threshold calibrado)
          - hour_min:   int          (hora mínima de entrada)
          - bought:     bool         (já comprou hoje?)
          - temp_now:   float        (temperatura actual °C)
          - running_max: float       (máximo do dia °C)
          - local_hhmm: str          (hora local cidade)
        """
        mode_icon = "🟢" if mode_str == "REAL" else "🟡"
        pnl_icon = "📈" if total_pnl >= 0 else "📉"

        lines = [
            f"{mode_icon} <b>Relatório Multi-Cidade</b> — {datetime.now().strftime('%H:%M')}",
            f"  Modo: <b>{mode_str}</b>",
            f"  Apostas hoje: <b>{n_trades}</b>",
            f"  {pnl_icon} P&L Total: <b>${total_pnl:+.2f}</b>",
            "",
            "<b>Cidades (P(pico) / threshold / estado):</b>",
        ]

        # Ordenar cidades por p_ensemble desc (para ver quais estão mais perto de disparar)
        sorted_cities = sorted(
            cities_data,
            key=lambda x: x.get('p_ensemble', 0.0),
            reverse=True,
        )
        for c in sorted_cities[:10]:
            name   = c.get('name', '?').replace('_', ' ').title()
            pnl    = c.get('pnl', 0.0)
            p_ens  = c.get('p_ensemble', 0.0)
            thr    = c.get('threshold', 0.65)
            bought = c.get('bought', False)
            temp   = c.get('temp_now')
            rmax   = c.get('running_max')
            local  = c.get('local_hhmm', '')

            # Iconografia
            if bought:
                icon = "💼"  # já tem posição
            elif p_ens >= thr:
                icon = "🔥"  # sinal activo
            elif p_ens >= thr * 0.85:
                icon = "⚡"  # quase-sinal
            elif p_ens >= thr * 0.6:
                icon = "🔍"  # a aproximar-se
            else:
                icon = "💤"  # longe

            # Temperatura compacta
            temp_str = ""
            if temp is not None:
                temp_str = f" {temp:.0f}°C"
                if rmax is not None:
                    temp_str += f"/{rmax:.0f}°↑"

            # Barra P(pico)
            bar = _tg_bar(p_ens, width=8)
            gap = (thr - p_ens) * 100
            gap_str = f"  (faltam {gap:.0f}pts)" if gap > 0 else ""

            lines.append(
                f"  {icon} <b>{name}</b>{temp_str}  "
                f"{bar} {p_ens*100:>3.0f}/{thr*100:>2.0f}%{gap_str}"
            )

        return self.send("\n".join(lines))

    def alert_near_signal(self, city_name, p, threshold, rmax=None, temp_now=None):
        """
        Aviso de quase-sinal: p_ensemble perto do threshold mas ainda não disparou.
        Útil para debug — ajuda a perceber porque é que o bot não está a apostar.
        """
        pct     = p * 100
        thr_pct = threshold * 100
        gap     = thr_pct - pct
        bar     = _tg_bar(p, width=12)

        pretty = city_name.replace('_', ' ').title()

        temp_str = ""
        if temp_now is not None:
            temp_str = f"  🌡 {temp_now:.1f}°C"
        if rmax is not None:
            temp_str += f"  RMax {rmax:.0f}°C"

        lines = [
            f"⚡ <b>Quase-sinal</b> — {pretty}",
            f"  P(pico): <b>{pct:.1f}%</b>  (threshold {thr_pct:.0f}%)",
            f"  {bar}{temp_str}",
            f"  Faltam <b>{gap:.1f} pontos</b> para disparar",
            "",
            "<i>Se a probabilidade subir nas próximas horas, há bet.</i>",
        ]
        return self.send("\n".join(lines))

    def alert_eod_fallback(self, city_name, p, fallback_thr, original_thr, bracket_label, ask):
        """Aviso de que o EOD fallback foi activado e vai forçar uma bet."""
        pretty = city_name.replace('_', ' ').title()
        lines = [
            f"⏰ <b>EOD Fallback activado</b> — {pretty}",
            f"  P(pico): <b>{p*100:.1f}%</b>",
            f"  Threshold original: {original_thr*100:.0f}%  →  fallback: <b>{fallback_thr*100:.0f}%</b>",
            f"  🎯 {bracket_label}  ask <b>{ask*100:.1f}¢</b>",
            "",
            "<i>Forçando entrada — nenhuma bet feita hoje, hora limite a aproximar-se.</i>",
        ]
        return self.send("\n".join(lines))

    def alert_race_selected(self, city_name, p, original_thr, race_thr,
                             bracket_label=None, ask=None, rank=None, total=None):
        """
        Aviso de que o Top-K Race mode seleccionou esta cidade.

        Race mode: a cada N minutos, ordena todas as cidades não compradas
        por p_ensemble desc, e baixa temporariamente o threshold das top-K
        (com p >= race_min_threshold) para garantir buy.
        Não força — só dispara se p_ensemble >= race_min_threshold (default 0.50).
        """
        pretty = city_name.replace('_', ' ').title()
        rank_str = f"  (rank {rank}/{total})" if rank and total else ""

        bracket_str = ""
        if bracket_label:
            bracket_str = f"\n  🎯 {bracket_label}"
            if ask is not None:
                bracket_str += f"  ask <b>{ask*100:.1f}¢</b>"

        lines = [
            f"🏁 <b>RACE seleccionou</b> — {pretty}{rank_str}",
            f"  P(pico): <b>{p*100:.1f}%</b>",
            f"  Threshold: {original_thr*100:.0f}%  →  <b>{race_thr*100:.0f}%</b>",
            bracket_str,
            "",
            "<i>Top-K race: melhor oportunidade do momento. Não força — só dispara "
            "se P(pico) &gt;= min_abs.</i>",
        ]
        return self.send("\n".join(lines))

    def alert_race_no_candidates(self, race_min_threshold, n_cities_evaluated):
        """Aviso de que o race não encontrou candidatos elegíveis neste eval."""
        lines = [
            f"🏁 <b>RACE eval</b> — sem candidatos",
            f"  Avaliadas: <b>{n_cities_evaluated}</b> cidades",
            f"  Nenhuma com P(pico) &gt;= <b>{race_min_threshold*100:.0f}%</b>",
            "",
            "<i>Aguardando melhor oportunidade. Não força buys de baixa qualidade.</i>",
        ]
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
    #  CHARTS POR CIDADE (menu interativo)
    # ══════════════════════════════════════════════════════

    def _build_charts_menu(self):
        """Constrói o menu de selecção de cidade para ver charts.
        Retorna (text, keyboard) onde keyboard é lista de listas de dicts
        compatíveis com a API do Telegram (inline_keyboard).
        """
        if not hasattr(self, 'bot_states') or not self.bot_states:
            return (
                "📈 <b>Charts por Cidade</b>\n\n"
                "❌ Nenhuma cidade activa no momento.",
                []
            )

        cities = list(self.bot_states.keys())
        if not cities:
            return (
                "📈 <b>Charts por Cidade</b>\n\n"
                "❌ Nenhuma cidade activa no momento.",
                []
            )

        # Constrói keyboard: 2 cidades por linha
        keyboard = []
        row = []
        for cn in cities:
            pretty = cn.replace('_', ' ').title()
            # Limitar callback_data a 64 bytes (limite Telegram)
            cb_data = f"chart:{cn}"[:64]
            row.append({"text": f"🌍 {pretty}", "callback_data": cb_data})
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)

        text = (
            "📈 <b>Charts por Cidade</b>\n\n"
            f"<i>{len(cities)} cidades activas.</i>\n\n"
            "Escolhe uma cidade para ver:\n"
            "  • Curva de temperatura do dia (ASCII chart)\n"
            "  • Tabela completa de brackets do Polymarket\n"
            "  • Métricas: P(pico), running max, target bracket"
        )
        return text, keyboard

    def _build_temp_chart_ascii(self, slots, width=40, height=10):
        """
        Constrói um chart ASCII de temperatura ao longo do dia.
        Versão maior que a do dashboard periódico (40x10 em vez de 28x6).
        Retorna lista de strings (uma por linha).
        """
        if not slots:
            return ["  sem dados suficientes"]

        temps = []
        for s in slots:
            try:
                t = float(s.get("temp_c")) if s.get("temp_c") is not None else None
                if t is not None:
                    temps.append((int(s["hour"]), int(s.get("slot30", 0)), t))
            except (TypeError, ValueError):
                continue

        if not temps:
            return ["  sem dados válidos"]

        temps.sort(key=lambda x: x[0] * 60 + x[1])
        t_min = min(t[2] for t in temps)
        t_max = max(t[2] for t in temps)
        t_rng = max(t_max - t_min, 1.0)

        n = len(temps)
        if n > width:
            sampled = [temps[int(i * n / width)] for i in range(width)]
        else:
            sampled = temps

        lines = []
        # Linhas de cima para baixo (alta temp para baixa temp)
        for row in range(height, 0, -1):
            threshold = t_min + (t_rng * (row - 0.5) / height)
            line_chars = []
            for h, m, t in sampled:
                if t >= threshold + (t_rng / height / 2):
                    line_chars.append("█")
                elif t >= threshold:
                    line_chars.append("▄")
                elif t >= threshold - (t_rng / height / 2):
                    line_chars.append("▁")
                else:
                    line_chars.append(" ")
            label = f"{threshold:>5.1f}°C"
            lines.append(f"  {label} │{''.join(line_chars)}")

        # Eixo X
        lines.append(f"         └{'─' * width}")

        # Labels de hora nas extremidades + meio
        if len(sampled) >= 2:
            first_h = sampled[0][0]
            last_h = sampled[-1][0]
            mid_h = sampled[len(sampled) // 2][0]
            first_label = f"{first_h:02d}h"
            mid_label = f"{mid_h:02d}h"
            last_label = f"{last_h:02d}h"
            # Distribuir: first_label no início, mid_label no meio, last_label no fim
            n_pad_first = 9  # alinhar com "  {label} │"
            gap1 = max(1, (width - len(first_label) - len(mid_label) - len(last_label)) // 2)
            gap2 = max(1, width - len(first_label) - len(mid_label) - len(last_label) - gap1)
            lines.append(
                f"          {first_label}{' ' * gap1}{mid_label}{' ' * gap2}{last_label}"
            )

        # Anotação do pico
        peak_t = t_max
        peak_idx = max(range(len(sampled)), key=lambda i: sampled[i][2])
        peak_h = sampled[peak_idx][0]
        lines.append(
            f"  📍 Pico: <b>{peak_t:.1f}°C</b> @ {peak_h:02d}h  |  "
            f"Min: {t_min:.1f}°C  |  Range: {t_rng:.1f}°C  |  N slots: {n}"
        )

        return lines

    def _build_brackets_table_ascii(self, market, target_bracket=None, max_brackets=18):
        """
        Constrói uma tabela ASCII completa de brackets do mercado Polymarket.
        Mostra TODOS os brackets (até max_brackets), não só janela visível.
        Retorna lista de strings (uma por linha).
        """
        if not market or not market.get("brackets"):
            return ["  mercado não disponível"]

        brackets = market.get("brackets", [])[:max_brackets]
        n_total = len(market.get("brackets", []))
        n_hidden = max(0, n_total - max_brackets)

        target_label = ""
        if target_bracket:
            target_label = target_bracket.get("label", "")

        # Header
        lines = [
            "  Label              Bid/  Ask   Visual",
            "  " + "─" * 42,
        ]

        for b in brackets:
            label = b.get("label", "?")[:18]
            ask = float(b.get("ask") or b.get("price") or 0)
            bid = float(b.get("bid") or ask * 0.7)  # fallback se não houver bid
            is_tgt = (label == target_label) and target_label

            # Barra visual (10 chars)
            bar_w = 10
            filled = round(min(max(ask, 0), 1) * bar_w)
            bar = "█" * filled + "░" * (bar_w - filled)

            arrow = "🎯" if is_tgt else "  "
            lines.append(
                f"  {arrow} {label:<18} {bid*100:>3.0f}¢/{ask*100:>3.0f}¢  {bar}"
            )

        # Volume + info
        vol = float(market.get("volume", 0) or 0)
        n_outcomes = market.get("n_outcomes", 0)
        lines.append("  " + "─" * 42)
        lines.append(f"  Volume: ${vol:>10,.0f}   |   {n_outcomes} brackets")
        if n_hidden > 0:
            lines.append(f"  <i>... mais {n_hidden} brackets escondidos (limite {max_brackets})</i>")

        return lines

    def _generate_city_charts_message(self, city_name):
        """
        Gera mensagem HTML com os 2 charts (temperatura + brackets) de uma cidade.
        Retorna (text, keyboard) onde keyboard tem botões "Refresh" e "Back".

        Lê o state da cidade de self.bot_states (passado pelo live_bot).
        """
        from datetime import datetime
        from zoneinfo import ZoneInfo

        if not hasattr(self, 'bot_states') or city_name not in self.bot_states:
            pretty = city_name.replace('_', ' ').title()
            return (
                f"📈 <b>Charts — {pretty}</b>\n\n"
                f"❌ Cidade <code>{city_name}</code> não está activa.",
                [[InlineKeyboardButton("← Voltar", callback_data="charts_menu")]]
            )

        state = self.bot_states[city_name]
        city = state.city
        pretty = city_name.replace('_', ' ').title()
        now_city = datetime.now(tz=ZoneInfo(city.timezone))

        # ── Temperatura actual + running max
        temp_now = None
        if state.latest_obs:
            temp_now = state.latest_obs.get("temp_c")

        rmax = None
        rmax_time = "—"
        if state.slots_so_far:
            valid = [s for s in state.slots_so_far if s.get("temp_c") is not None]
            if valid:
                rmax_slot = max(valid, key=lambda s: float(s["temp_c"]))
                rmax = float(rmax_slot["temp_c"])
                rmax_time = f"{int(rmax_slot['hour']):02d}:{int(rmax_slot.get('slot30', 0)):02d}"

        # ── P(pico)
        p = float(getattr(state, 'last_p_ensemble', 0.0) or 0.0)
        thr = city.threshold if city.threshold is not None else 0.65

        # ── Forecasts
        wu = getattr(state, 'last_wu_forecast_max', None)
        om = getattr(state, 'last_om_forecast_max', None)

        # ── Posição
        position_str = "💤 Sem posição"
        if state.entry and getattr(state.entry, 'bought', False):
            rec = getattr(state.entry, 'record', None) or {}
            bracket_lbl = rec.get('bracket_label') or rec.get('bracket') or '?'
            ask = rec.get('ask', 0)
            size = rec.get('size_usdc', 0)
            position_str = f"💼 <b>{bracket_lbl}</b> @ {ask*100:.0f}¢  ${size:.2f}"

        # ── Construir mensagem
        lines = [
            f"📈 <b>Charts — {pretty}</b>",
            f"  {now_city.strftime('%Y-%m-%d %H:%M')} ({city.timezone})",
            "  ─────────────────────────────────────",
            "",
        ]

        # Temperatura actual + rmax
        temp_str = f"{temp_now:.1f}°C" if temp_now is not None else "—"
        rmax_str = f"{rmax:.1f}°C @ {rmax_time}" if rmax is not None else "—"
        lines.append(f"🌡 <b>Temperatura</b>")
        lines.append(f"  Agora: <b>{temp_str}</b>   Max: <b>{rmax_str}</b>")
        # Forecasts
        if wu is not None or om is not None:
            fc_parts = []
            if wu is not None:
                fc_parts.append(f"WU:{wu}°C")
            if om is not None:
                fc_parts.append(f"OM:{om}°C")
            lines.append(f"  Forecast: {' | '.join(fc_parts)}")
        lines.append("")

        # P(pico)
        p_bar = _tg_bar(p, width=14)
        peak_str = "  ✅ SIGNAL!" if p >= thr else ""
        lines.append(f"🧠 <b>P(pico)</b>")
        lines.append(f"  {p_bar}  <b>{p*100:.1f}%</b>  (thr {thr*100:.0f}%){peak_str}")
        lines.append("")

        # ── Chart de temperatura (ASCII grande)
        lines.append("🌡 <b>Curva de temperatura hoje</b>")
        temp_chart = self._build_temp_chart_ascii(state.slots_so_far, width=40, height=10)
        lines.extend(temp_chart)
        lines.append("")

        # ── Tabela de brackets (completa)
        lines.append("📋 <b>Brackets do Polymarket</b>")
        target_bracket = getattr(state, 'last_target_bracket', None)
        market = getattr(state, 'market', None)
        brackets_table = self._build_brackets_table_ascii(
            market, target_bracket, max_brackets=18
        )
        lines.extend(brackets_table)
        lines.append("")

        # ── Posição
        lines.append(f"💼 <b>Posição</b>")
        lines.append(f"  {position_str}")
        lines.append("")

        # ── Rodapé com botões
        keyboard = [
            [
                InlineKeyboardButton("🔄 Refresh", callback_data=f"chart:{city_name}"),
                InlineKeyboardButton("← Voltar", callback_data="charts_menu"),
            ]
        ]

        return "\n".join(lines), keyboard

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
                  bet_blocked_reason=None,
                  city_name=None):
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

        # Título dinâmico: usa city_name se fornecido, senão fallback "Munich"
        if city_name:
            city_display = city_name.replace("_", " ").title()
        else:
            city_display = "Munich"

        lines = [
            f"{mode_icon} <b>{city_display} Bot Live</b>  "
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
