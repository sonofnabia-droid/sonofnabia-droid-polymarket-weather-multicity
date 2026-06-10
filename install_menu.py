#!/usr/bin/env python3
"""
Script de instalação do menu interativo do Telegram Bot
=======================================================
Verifica e configura tudo necessário para o menu funcionar.
"""

import sys
import subprocess
from pathlib import Path

def check_dependencies():
    """Verifica dependências necessárias."""
    
    print("🔍 Verificando dependências...")
    
    # Verificar python-telegram-bot
    try:
        import telegram
        print("✅ python-telegram-bot instalado")
    except ImportError:
        print("❌ python-telegram-bot não instalado")
        print("   Instalando...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "python-telegram-bot"])
        print("✅ python-telegram-bot instalado")
    
    # Verificar outras dependências
    deps = [
        "requests",
        "python-dotenv"
    ]
    
    for dep in deps:
        try:
            __import__(dep.replace("-", "_"))
            print(f"✅ {dep} instalado")
        except ImportError:
            print(f"❌ {dep} não instalado")
            print(f"   Instalando {dep}...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", dep])
            print(f"✅ {dep} instalado")

def check_environment():
    """Verifica variáveis de ambiente."""
    
    print("\n🔍 Verificando variáveis de ambiente...")
    
    import os
    
    token = os.environ.get("TELEGRAM_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    
    if not token:
        print("❌ TELEGRAM_TOKEN não definido")
        print("   Defina a variável de ambiente:")
        print("   export TELEGRAM_TOKEN=seu_token_aqui")
        return False
    
    if not chat_id:
        print("❌ TELEGRAM_CHAT_ID não definido")
        print("   Defina a variável de ambiente:")
        print("   export TELEGRAM_CHAT_ID=seu_chat_id_aqui")
        return False
    
    print("✅ Variáveis de ambiente configuradas")
    return True

def check_directories():
    """Verifica diretórios necessários."""
    
    print("\n🔍 Verificando diretórios...")
    
    dirs = [
        "live_bot_logs",
        "cities",
        "predictor_models"
    ]
    
    for dir_name in dirs:
        path = Path(dir_name)
        if path.exists():
            print(f"✅ {dir_name} existe")
        else:
            print(f"⚠️ {dir_name} não existe - será criado automaticamente")

def check_files():
    """Verifica arquivos necessários."""
    
    print("\n🔍 Verificando arquivos...")
    
    files = [
        "tg.py",
        "live_bot.py",
        "trade_ledger.py",
        "cities/config.py",
        "predictor.py",
        "weather.py"
    ]
    
    for file_name in files:
        path = Path(file_name)
        if path.exists():
            print(f"✅ {file_name} existe")
        else:
            print(f"❌ {file_name} não encontrado")

def test_menu():
    """Testa o menu interativo."""
    
    print("\n🧪 Testando menu interativo...")
    
    try:
        from tg import TG
        tg = TG()
        
        if not tg.enabled:
            print("❌ Menu não está habilitado")
            print("   Configure TELEGRAM_TOKEN e TELEGRAM_CHAT_ID")
            return False
        
        # Testar funções
        summary = tg._generate_daily_summary()
        positions = tg._get_open_positions()
        wins = tg._get_recent_wins()
        status = tg._get_bot_status()
        
        print("✅ Todas as funções do menu funcionam")
        return True
        
    except Exception as e:
        print(f"❌ Erro ao testar menu: {e}")
        return False

def main():
    """Função principal."""
    
    print("=" * 60)
    print(" Instalação do Menu Interativo do Telegram Bot")
    print("=" * 60)
    
    # Verificar dependências
    check_dependencies()
    
    # Verificar arquivos
    check_directories()
    check_files()
    
    # Verificar ambiente
    env_ok = check_environment()
    
    # Testar menu
    menu_ok = test_menu()
    
    print("\n" + "=" * 60)
    if env_ok and menu_ok:
        print("✅ Tudo configurado corretamente!")
        print("\n🚀 Para usar o menu:")
        print("1. Inicie o bot: python live_bot.py --cities munich --mode single --run paper")
        print("2. Envie /menu no Telegram")
        print("3. Clique nos botões para ver detalhes")
    else:
        print("❌ Algo está errado. Verifique os erros acima.")
    print("=" * 60)

if __name__ == "__main__":
    main()