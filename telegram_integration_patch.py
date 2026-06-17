
# Enhanced Telegram Bot Integration
try:
    from enhanced_tg_bot import EnhancedTGBot
    ENHANCED_BOT_AVAILABLE = True
except ImportError:
    ENHANCED_BOT_AVAILABLE = False

# Modificar _get_tg() para usar enhanced bot
def _get_tg():
    """Retorna instância do enhanced bot"""
    global _tg_instance
    
    if _tg_instance is None:
        if ENHANCED_BOT_AVAILABLE:
            _tg_instance = EnhancedTGBot()
            if _tg_instance.enabled:
                _tg_instance.start_dashboard()
            else:
                _tg_instance = None
        else:
            # Fallback para bot original
            _tg_instance = TG()
    
    return _tg_instance

# Modificar o loop principal para usar enhanced bot
def main():
    # ... (código existente) ...
    
    # Inicializar enhanced bot
    enhanced_bot = None
    if ENHANCED_BOT_AVAILABLE:
        enhanced_bot = EnhancedTGBot()
        if enhanced_bot.enabled:
            enhanced_bot.start_dashboard()
    
    try:
        # Loop principal do bot
        while True:
            # ... (código existente) ...
            
            # Enviar relatório enhanced se disponível
            if enhanced_bot and enhanced_bot.enabled:
                enhanced_bot.send_enhanced_dashboard()
            
            time.sleep(args.interval)
            
    except KeyboardInterrupt:
        # ... (código existente) ...
        
        finally:
            if enhanced_bot:
                enhanced_bot.stop_dashboard()
