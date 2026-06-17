#!/usr/bin/env python3
"""
Simplified Enhanced Telegram Bot for Multi-City Trading Bot
Versão que não depende do Telegram para testes
"""

import os
import json
import threading
import time
from datetime import datetime, date
from pathlib import Path
from typing import Dict, List, Optional, Any
import logging

# Configuração de logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class SimplifiedTGBot:
    """Telegram Bot simplificado para testes (sem dependência externa)"""
    
    def __init__(self):
        self.token = os.environ.get("TELEGRAM_TOKEN", "")
        self.chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
        self.enabled = bool(self.token and self.chat_id)
        self.dashboard_interval = 1800  # 30 minutos em segundos
        self.last_dashboard = 0
        self.dashboard_thread = None
        self.running = False
        
        if not self.enabled:
            print("  [TG] TELEGRAM_TOKEN ou TELEGRAM_CHAT_ID não definidos — modo de teste")
        else:
            print("  [TG] Simplified Telegram Bot inicializado (modo de teste)")
    
    def start_dashboard(self):
        """Inicia thread de relatórios periódicos"""
        self.running = True
        self.dashboard_thread = threading.Thread(target=self._dashboard_loop, daemon=True)
        self.dashboard_thread.start()
        print("  [TG] Dashboard periódico iniciado (30 min)")
    
    def stop_dashboard(self):
        """Para o dashboard periódico"""
        self.running = False
        if self.dashboard_thread:
            self.dashboard_thread.join()
        print("  [TG] Dashboard periódico parado")
    
    def _dashboard_loop(self):
        """Loop principal de envio de relatórios"""
        while self.running:
            try:
                current_time = time.time()
                if current_time - self.last_dashboard >= self.dashboard_interval:
                    self.send_enhanced_dashboard()
                    self.last_dashboard = current_time
                time.sleep(60)  # Checar a cada minuto
            except Exception as e:
                logger.error(f"Erro no dashboard loop: {e}")
                time.sleep(60)
    
    def send_enhanced_dashboard(self):
        """Envia dashboard completo com todas as métricas"""
        try:
            # Carregar dados do snapshot
            snapshot_data = self._load_snapshot_data()
            if not snapshot_data:
                return
            
            # Gerar mensagem formatada
            message = self._generate_dashboard_message(snapshot_data)
            
            # Simular envio (modo de teste)
            print("\n" + "="*60)
            print("📊 DASHBOARD PERIÓDICO (SIMULADO)")
            print("="*60)
            print(message)
            print("="*60 + "\n")
            
        except Exception as e:
            logger.error(f"Erro ao enviar dashboard: {e}")
    
    def _load_snapshot_data(self) -> Optional[Dict]:
        """Carrega dados do snapshot atual"""
        try:
            LOG_DIR = Path("live_bot_logs")
            snapshot_file = LOG_DIR / "live_snapshot.json"
            
            if not snapshot_file.exists():
                logger.warning("Arquivo snapshot não encontrado")
                return None
            
            with open(snapshot_file, 'r') as f:
                return json.load(f)
                
        except Exception as e:
            logger.error(f"Erro ao carregar snapshot: {e}")
            return None
    
    def _generate_dashboard_message(self, data: Dict) -> str:
        """Gera mensagem formatada do dashboard"""
        trading_mode = data.get("trading_mode", "PAPER")
        session = data.get("session", {})
        summary = data.get("summary", {})
        cities = data.get("cities", [])
        
        # Formatação
        mode_icon = "🟢" if trading_mode == "REAL" else "🟡"
        now_str = datetime.now().strftime("%H:%M")
        
        lines = [
            f"{mode_icon} <b>Multi-City Trading Bot</b>",
            f"📊 Relatório Periódico — {now_str}",
            "─" * 50,
            ""
        ]
        
        # Estatísticas gerais
        lines.extend([
            "📈 <b>Resumo Geral</b>",
            f"   Modo: <b>{trading_mode}</b>",
            f"   Total Trades: <b>{session.get('total_trades', 0)}</b>",
            f"   P&L Total: <b>${session.get('total_pnl', 0):+.2f}</b>",
            f"   P&L Diário: <b>${summary.get('daily_pnl', 0):+.2f}</b>",
            f"   Trades Diários: <b>{summary.get('daily_trades', 0)}</b>",
            ""
        ])
        
        # Status das cidades
        lines.extend([
            "🌍 <b>Status por Cidade</b>"
        ])
        
        # Agrupar cidades por status
        active_cities = []
        monitoring_cities = []
        
        for city in cities:
            name = city.get("name", "N/A")
            temp = city.get("temp", 0)
            running_max = city.get("running_max", 0)
            p_ensemble = city.get("p_ensemble", 0)
            status = city.get("status", "N/A")
            local_time = city.get("local_hm", "N/A")
            
            city_info = {
                "name": name,
                "temp": temp,
                "running_max": running_max,
                "p_ensemble": p_ensemble,
                "status": status,
                "local_time": local_time
            }
            
            if "MONITORIZAR" in str(status):
                monitoring_cities.append(city_info)
            else:
                active_cities.append(city_info)
        
        # Mostrar cidades ativas primeiro
        if active_cities:
            lines.extend([
                "   <b>🟢 Ativas</b>"
            ])
            for city in active_cities[:5]:  # Top 5
                p_bar = self._probability_bar(city["p_ensemble"])
                lines.append(
                    f"   {city['name'].title()}: {city['temp']:.1f}°C "
                    f"(max {city['running_max']:.1f}°C) {p_bar} "
                    f"{city['p_ensemble']*100:.1f}%"
                )
        
        # Mostrar cidades em monitorização
        if monitoring_cities:
            lines.extend([
                "",
                "   <b>🔍 Em Monitorização</b>"
            ])
            for city in monitoring_cities[:5]:  # Top 5
                p_bar = self._probability_bar(city["p_ensemble"])
                lines.append(
                    f"   {city['name'].title()}: {city['temp']:.1f}°C "
                    f"(max {city['running_max']:.1f}°C) {p_bar} "
                    f"{city['p_ensemble']*100:.1f}%"
                )
        
        # Temperatura máxima por cidade
        lines.extend([
            "",
            "🌡️ <b>Temperaturas Máximas Atuais</b>"
        ])
        
        # Ordenar por temperatura máxima
        sorted_cities = sorted(cities, key=lambda x: x.get("running_max", 0), reverse=True)
        
        for city in sorted_cities[:8]:
            name = city.get("name", "N/A")
            max_temp = city.get("running_max", 0)
            local_time = city.get("local_hm", "N/A")
            lines.append(f"   {name.title()}: {max_temp:.1f}°C @ {local_time}")
        
        # Probabilidades de pico
        lines.extend([
            "",
            "🧠 <b>Probabilidades de Pico</b>"
        ])
        
        # Ordenar por probabilidade
        sorted_by_prob = sorted(cities, key=lambda x: x.get("p_ensemble", 0), reverse=True)
        
        for city in sorted_by_prob[:8]:
            name = city.get("name", "N/A")
            p_ensemble = city.get("p_ensemble", 0)
            p_bar = self._probability_bar(p_ensemble)
            
            if p_ensemble > 0.6:
                icon = "🔥"
            elif p_ensemble > 0.4:
                icon = "⚡"
            elif p_ensemble > 0.2:
                icon = "⚠️"
            else:
                icon = "📊"
            
            lines.append(f"   {icon} {name.title()}: {p_bar} {p_ensemble*100:.1f}%")
        
        # Rodapé
        lines.extend([
            "",
            "─" * 50,
            "🤖 <b>Comandos Disponíveis</b>",
            "   /menu - Menu interativo",
            "   /status - Status detalhado",
            "   /resumo - Resumo do dia",
            "   /posicoes - Posições abertas",
            "   /ultimas - Últimas vitórias"
        ])
        
        return "\n".join(lines)
    
    def _probability_bar(self, probability: float) -> str:
        """Gera barra de probabilidade"""
        if probability >= 0.8:
            return "████████"
        elif probability >= 0.6:
            return "███████ "
        elif probability >= 0.4:
            return "██████  "
        elif probability >= 0.2:
            return "█████   "
        elif probability >= 0.1:
            return "████    "
        elif probability >= 0.05:
            return "███     "
        elif probability >= 0.01:
            return "██      "
        else:
            return "█       "
    
    def send(self, message: str) -> bool:
        """Simula envio de mensagem (modo de teste)"""
        if not self.enabled:
            print("📝 [TESTE] Mensagem não enviada (Telegram não configurado)")
            print(message)
            return True
        
        print("📝 [TESTE] Mensagem enviada (simulado)")
        print(message)
        return True
    
    def send_alert(self, message: str) -> bool:
        """Envia alerta urgente"""
        return self.send(f"⚠️ <b>ALERTA</b>\n\n{message}")
    
    def send_trade_notification(self, city: str, action: str, details: Dict) -> bool:
        """Envia notificação de trade"""
        message = f"💰 <b>Trade {action.upper()}</b>\n\n"
        message += f"📍 Cidade: {city.title()}\n"
        message += f"🎯 Bracket: {details.get('bracket', 'N/A')}\n"
        message += f"💰 Valor: ${details.get('size_usdc', 0):.2f}\n"
        message += f"📊 Ask: {details.get('ask', 0)*100:.1f}¢\n"
        message += f"⏰ Horário: {details.get('time', 'N/A')}"
        
        return self.send(message)

# Função para iniciar o bot
def start_simplified_bot():
    """Inicia o bot simplificado"""
    bot = SimplifiedTGBot()
    return bot

if __name__ == "__main__":
    print("🤖 Simplified Enhanced Telegram Bot (Modo de Teste)\n")
    
    # Iniciar bot
    bot = start_simplified_bot()
    
    # Iniciar dashboard
    bot.start_dashboard()
    
    print("📊 Dashboard iniciado. Pressione Ctrl+C para parar...")
    
    try:
        # Manter o script rodando
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        print("\n⏹️ Parando dashboard...")
        bot.stop_dashboard()
        print("✅ Dashboard parado")