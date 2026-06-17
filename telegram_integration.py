#!/usr/bin/env python3
"""
Script de integração para Enhanced Telegram Bot
Adicione este código ao seu live_bot.py
"""

try:
    from enhanced_tg_bot import EnhancedTGBot
    ENHANCED_BOT_AVAILABLE = True
except ImportError:
    ENHANCED_BOT_AVAILABLE = False
    print("[INTEGRATION] Enhanced bot não disponível")

# Variável global para enhanced bot
_enhanced_bot = None

def get_enhanced_bot():
    """Retorna instância do enhanced bot"""
    global _enhanced_bot
    
    if _enhanced_bot is None and ENHANCED_BOT_AVAILABLE:
        _enhanced_bot = EnhancedTGBot()
        if _enhanced_bot.enabled:
            _enhanced_bot.start_dashboard()
            print("[INTEGRATION] Enhanced bot iniciado")
        else:
            _enhanced_bot = None
    
    return _enhanced_bot

def send_enhanced_dashboard():
    """Envia dashboard enhanced se disponível"""
    bot = get_enhanced_bot()
    if bot:
        bot.send_enhanced_dashboard()
