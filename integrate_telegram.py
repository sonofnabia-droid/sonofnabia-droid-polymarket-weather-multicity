#!/usr/bin/env python3
"""
Integration script for Enhanced Telegram Bot with Live Bot
Adiciona relatórios periódicos de 30 minutos ao live_bot.py
"""

import time
import threading
from pathlib import Path
from datetime import datetime
from typing import Dict, Any
import json

# Importar o enhanced bot
try:
    from enhanced_tg_bot import EnhancedTGBot
    ENHANCED_BOT_AVAILABLE = True
except ImportError:
    ENHANCED_BOT_AVAILABLE = False
    print("[INTEGRATION] Enhanced bot não disponível")

def integrate_with_live_bot():
    """Integra o enhanced bot com o live_bot.py"""
    
    print("=== INTEGRAÇÃO COM ENHANCED TELEGRAM BOT ===\n")
    
    # 1. Verificar se o enhanced bot está disponível
    if not ENHANCED_BOT_AVAILABLE:
        print("❌ Enhanced bot não está disponível")
        return False
    
    # 2. Iniciar o enhanced bot
    enhanced_bot = EnhancedTGBot()
    if not enhanced_bot.enabled:
        print("❌ Bot do Telegram não configurado")
        return False
    
    print("✅ Enhanced bot inicializado")
    
    # 3. Iniciar dashboard periódico
    enhanced_bot.start_dashboard()
    print("✅ Dashboard periódico iniciado (30 min)")
    
    # 4. Simular o loop do live_bot com relatórios
    print("\n=== SIMULAÇÃO DE LOOP DO LIVE BOT ===\n")
    
    try:
        # Loop principal (simulação)
        for i in range(6):  # 6 iterações (3 minutos)
            time.sleep(30)  # 30 segundos por iteração
            
            current_time = datetime.now().strftime("%H:%M")
            print(f"[{current_time}] Enviando relatório {i+1}...")
            
            # Enviar relatório personalizado
            enhanced_bot.send(
                f"🤖 <b>Relatório Automático</b>\n\n"
                f"📊 Iteração: {i+1}/6\n"
                f"⏰ Horário: {current_time}\n"
                f"📈 Status: Bot em operação"
            )
            
    except KeyboardInterrupt:
        print("\n⏹️ Parando integração...")
    
    finally:
        enhanced_bot.stop_dashboard()
        print("✅ Integração finalizada")
    
    return True

def create_telegram_integration_patch():
    """Cria patch para integrar enhanced bot no live_bot.py"""
    
    print("\n=== CRIANDO PATCH PARA INTEGRAÇÃO ===\n")
    
    # Ler o live_bot.py
    live_bot_path = Path("live_bot.py")
    if not live_bot_path.exists():
        print("❌ live_bot.py não encontrado")
        return False
    
    with open(live_bot_path, 'r') as f:
        content = f.read()
    
    # Procurar pela função _get_tg()
    if "_get_tg()" not in content:
        print("❌ Função _get_tg() não encontrada no live_bot.py")
        return False
    
    # Criar versão modificada
    enhanced_integration = '''
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
'''
    
    # Criar arquivo de integração
    integration_file = Path("telegram_integration_patch.py")
    with open(integration_file, 'w') as f:
        f.write(enhanced_integration)
    
    print(f"✅ Patch criado: {integration_file}")
    print("Para aplicar o patch:")
    print("1. Adicione o código acima ao live_bot.py")
    print("2. Importe o enhanced_tg_bot")
    print("3. Modifique _get_tg() para usar EnhancedTGBot")
    
    return True

def create_telegram_config():
    """Cria arquivo de configuração para o Telegram"""
    
    print("\n=== CRIANDO CONFIGURAÇÃO DO TELEGRAM ===\n")
    
    config_template = '''# Configuração do Telegram Bot
# Copie estas variáveis para seu .env ou exporte no terminal

# Token do Bot do Telegram (obtenha do @BotFather)
TELEGRAM_TOKEN=seu_token_aqui

# ID do chat para receber mensagens
# Para obter seu chat ID:
# 1. Envie uma mensagem para o bot
# 2. Acesse: https://api.telegram.org/bot<token>/getUpdates
TELEGRAM_CHAT_ID=seu_chat_id_aqui

# Configurações opcionais
TELEGRAM_DASHBOARD_INTERVAL=1800  # 30 minutos em segundos
TELEGRAM_ENABLE_ALERTS=true
TELEGRAM_ENABLE_DASHBOARD=true
'''
    
    config_file = Path("telegram_config.env")
    with open(config_file, 'w') as f:
        f.write(config_template)
    
    print(f"✅ Arquivo de configuração criado: {config_file}")
    print("\n📝 Passos para configurar:")
    print("1. Obtenha o token do BotFather do Telegram")
    print("2. Obtenha seu chat ID")
    print("3. Preencha o arquivo telegram_config.env")
    print("4. Exporte as variáveis de ambiente:")
    print("   export TELEGRAM_TOKEN='seu_token'")
    print("   export TELEGRAM_CHAT_ID='seu_chat_id'")
    
    return True

if __name__ == "__main__":
    print("🤖 Enhanced Telegram Bot Integration Script\n")
    
    # Criar configuração
    create_telegram_config()
    
    # Criar patch de integração
    create_telegram_integration_patch()
    
    # Testar integração
    print("\n=== TESTANDO INTEGRAÇÃO ===\n")
    integrate_with_live_bot()
    
    print("\n🎉 Integração concluída!")
    print("\nPróximos passos:")
    print("1. Configure suas credenciais do Telegram")
    print("2. Reinicie o live_bot.py com a integração")
    print("3. Você receberá relatórios a cada 30 minutos")